from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

import generate_media

AUDIO_PARTS_GLOB = "assets/audio/panoramic_arrival_15s.ogg.b64.part*"
TARGET_DURATION_SECONDS = 15


def clean_base64(part: Path) -> str:
    return "".join(part.read_text(encoding="utf-8").split())


def decode_part(part: Path) -> bytes:
    encoded = clean_base64(part)
    encoded += "=" * (-len(encoded) % 4)
    return base64.b64decode(encoded, validate=True)


def print_part_diagnostics(parts: list[Path]) -> None:
    print("AUDIO_PART_DIAGNOSTICS_BEGIN")
    raw_join = ""
    for index, part in enumerate(parts):
        encoded = clean_base64(part)
        raw_join += encoded
        decoded = decode_part(part)
        print(
            f"part={index:02d} encoded_chars={len(encoded)} mod4={len(encoded) % 4} "
            f"first16={encoded[:16]} last16={encoded[-16:]} "
            f"decoded_bytes={len(decoded)} decoded_first8={decoded[:8].hex()} "
            f"decoded_last8={decoded[-8:].hex()} oggs_count={decoded.count(b'OggS')}"
        )
    print(
        f"raw_join_chars={len(raw_join)} raw_join_mod4={len(raw_join) % 4} "
        f"raw_join_first16={raw_join[:16]} raw_join_last16={raw_join[-16:]}"
    )
    print("AUDIO_PART_DIAGNOSTICS_END")


def reconstruct_audio(output: Path) -> Path:
    parts = sorted(Path().glob(AUDIO_PARTS_GLOB))
    expected_names = [f"panoramic_arrival_15s.ogg.b64.part{i:02d}" for i in range(5)]
    actual_names = [part.name for part in parts]
    if actual_names != expected_names:
        raise RuntimeError(
            "Expected exactly five Panoramic Arrival parts part00-part04; "
            f"found: {actual_names}"
        )

    print_part_diagnostics(parts)
    audio_bytes = b"".join(decode_part(part) for part in parts)
    if len(audio_bytes) < 10_000:
        raise RuntimeError(f"Decoded audio is unexpectedly small: {len(audio_bytes)} bytes")

    output.write_bytes(audio_bytes)

    codec = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=nw=1:nk=1",
            str(output),
        ],
        text=True,
    ).strip()
    duration_text = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(output),
        ],
        text=True,
    ).strip()
    duration = float(duration_text)
    if not codec:
        raise RuntimeError("Decoded music asset has no audio stream")
    if not 14.0 <= duration <= 16.0:
        raise RuntimeError(f"Decoded music duration is invalid: {duration:.3f}s")

    print(f"Validated music asset: codec={codec}, duration={duration:.3f}s, bytes={len(audio_bytes)}")
    return output


def build_video_with_music(cards: list[Path], output: Path) -> None:
    with tempfile.TemporaryDirectory() as temp_name:
        temp = Path(temp_name)
        silent_video = temp / "market_risk_short_silent.mp4"
        audio_file = reconstruct_audio(temp / "panoramic_arrival_15s.ogg")

        original_build_video(cards, silent_video)

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(silent_video),
                "-stream_loop",
                "-1",
                "-i",
                str(audio_file),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-af",
                "volume=0.20,afade=t=in:st=0:d=0.35,afade=t=out:st=14.20:d=0.80",
                "-t",
                str(TARGET_DURATION_SECONDS),
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


original_build_video = generate_media.build_video
generate_media.build_video = build_video_with_music


if __name__ == "__main__":
    raise SystemExit(generate_media.main())

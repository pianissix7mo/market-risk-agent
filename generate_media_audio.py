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


def reconstruct_audio(output: Path) -> Path:
    parts = sorted(Path().glob(AUDIO_PARTS_GLOB))
    expected_names = [f"panoramic_arrival_15s.ogg.b64.part{i:02d}" for i in range(5)]
    actual_names = [part.name for part in parts]
    if actual_names != expected_names:
        raise RuntimeError(
            "Expected exactly five Panoramic Arrival parts part00-part04; "
            f"found: {actual_names}"
        )

    audio_bytes = b"".join(decode_part(part) for part in parts)
    if len(audio_bytes) < 10_000:
        raise RuntimeError(f"Decoded audio is unexpectedly small: {len(audio_bytes)} bytes")
    output.write_bytes(audio_bytes)
    return output


def probe_duration(path: Path) -> float:
    duration_text = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(duration_text)


def recover_audio(source: Path, output: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-err_detect",
            "ignore_err",
            "-i",
            str(source),
            "-vn",
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    duration = probe_duration(output)
    if duration < 9.0:
        raise RuntimeError(f"Recovered music is too short: {duration:.3f}s")
    print(f"Recovered Panoramic Arrival audio: duration={duration:.3f}s")
    return output


def build_video_with_music(cards: list[Path], output: Path) -> None:
    with tempfile.TemporaryDirectory() as temp_name:
        temp = Path(temp_name)
        silent_video = temp / "market_risk_short_silent.mp4"
        damaged_audio = reconstruct_audio(temp / "panoramic_arrival_parts.ogg")
        recovered_audio = recover_audio(damaged_audio, temp / "panoramic_arrival_recovered.wav")

        original_build_video(cards, silent_video)

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(silent_video),
                "-i",
                str(recovered_audio),
                "-i",
                str(recovered_audio),
                "-filter_complex",
                "[1:a][2:a]acrossfade=d=0.5:c1=tri:c2=tri,"
                "atrim=0:15,volume=0.20,"
                "afade=t=in:st=0:d=0.35,afade=t=out:st=14.20:d=0.80[a]",
                "-map",
                "0:v:0",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-t",
                str(TARGET_DURATION_SECONDS),
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )


original_build_video = generate_media.build_video
generate_media.build_video = build_video_with_music


if __name__ == "__main__":
    raise SystemExit(generate_media.main())

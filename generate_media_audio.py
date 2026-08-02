from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

import generate_media

AUDIO_PARTS_GLOB = "assets/audio/panoramic_arrival_15s.ogg.b64.part*"
TARGET_DURATION_SECONDS = 15


def reconstruct_audio(output: Path) -> Path:
    parts = sorted(Path().glob(AUDIO_PARTS_GLOB))
    expected_names = [f"panoramic_arrival_15s.ogg.b64.part{i:02d}" for i in range(5)]
    actual_names = [part.name for part in parts]
    if actual_names != expected_names:
        raise RuntimeError(
            "Expected exactly five Panoramic Arrival parts part00-part04; "
            f"found: {actual_names}"
        )

    encoded = "".join(part.read_text(encoding="utf-8") for part in parts)
    encoded = "".join(encoded.split())
    encoded += "=" * (-len(encoded) % 4)
    audio_bytes = base64.b64decode(encoded, validate=True)
    if len(audio_bytes) < 10_000:
        raise RuntimeError(f"Decoded audio is unexpectedly small: {len(audio_bytes)} bytes")

    output.write_bytes(audio_bytes)
    subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,duration",
            "-of",
            "default=nw=1",
            str(output),
        ],
        check=True,
    )
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

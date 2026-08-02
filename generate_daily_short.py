from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import requests

import generate_media

FPS = 30
DURATION_SECONDS = 16
MUSIC_FILE = Path("assets/audio/a_night_alone_16s.mp3")
MUSIC_URL = "https://happysoulmusic.com/wp-content/grand-media/audio/A_Night_Alone_-_TrackTribe.mp3"


def probe_duration(path: Path) -> float:
    return float(
        subprocess.check_output(
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
    )


def ensure_music() -> Path:
    if MUSIC_FILE.exists():
        duration = probe_duration(MUSIC_FILE)
        if 15.8 <= duration <= 16.2:
            return MUSIC_FILE

    MUSIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_name:
        source = Path(temp_name) / "a_night_alone_full.mp3"
        response = requests.get(
            MUSIC_URL,
            timeout=60,
            headers={"User-Agent": "Mozilla/5.0 market-risk-agent"},
        )
        response.raise_for_status()
        source.write_bytes(response.content)
        if source.stat().st_size < 500_000:
            raise RuntimeError("Downloaded music file is unexpectedly small")

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-t",
                str(DURATION_SECONDS),
                "-ac",
                "1",
                "-b:a",
                "96k",
                str(MUSIC_FILE),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    duration = probe_duration(MUSIC_FILE)
    if not 15.8 <= duration <= 16.2:
        raise RuntimeError(f"Unexpected music duration: {duration:.3f}s")
    return MUSIC_FILE


def build_silent_video(cards: list[Path], output: Path) -> None:
    if len(cards) != 4:
        raise RuntimeError(f"Expected four cards, got {len(cards)}")

    with tempfile.TemporaryDirectory() as temp_name:
        temp = Path(temp_name)
        segments: list[Path] = []
        for index, card in enumerate(cards):
            segment = temp / f"segment_{index:02d}.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loop",
                    "1",
                    "-framerate",
                    str(FPS),
                    "-i",
                    str(card),
                    "-t",
                    "4",
                    "-an",
                    "-r",
                    str(FPS),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-g",
                    str(FPS),
                    "-keyint_min",
                    str(FPS),
                    "-sc_threshold",
                    "0",
                    str(segment),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            segments.append(segment)

        concat_file = temp / "segments.txt"
        concat_file.write_text(
            "\n".join(f"file '{segment.as_posix()}'" for segment in segments),
            encoding="utf-8",
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-t",
                str(DURATION_SECONDS),
                "-an",
                "-r",
                str(FPS),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def build_video_with_music(cards: list[Path], output: Path, title: str) -> None:
    music = ensure_music()
    with tempfile.TemporaryDirectory() as temp_name:
        silent_video = Path(temp_name) / "silent.mp4"
        build_silent_video(cards, silent_video)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(silent_video),
                "-i",
                str(music),
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
                "volume=0.22,afade=t=in:st=0:d=0.25,afade=t=out:st=15.25:d=0.75",
                "-t",
                str(DURATION_SECONDS),
                "-metadata",
                f"title={title}",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/latest_data.json")
    parser.add_argument("--output-dir", default="output/media")
    args = parser.parse_args()

    data: dict[str, Any] = json.loads(Path(args.input).read_text(encoding="utf-8"))
    market_date = str(data["market_date"])
    title = f"Market Risk Monitor {market_date}"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cards = [
        output_dir / "01_volatility.png",
        output_dir / "02_sentiment.png",
        output_dir / "03_macro.png",
        output_dir / "04_summary.png",
    ]

    generate_media.render_volatility(data, cards[0])
    generate_media.render_sentiment(data, cards[1])
    generate_media.render_macro(data, cards[2])
    generate_media.render_summary(data, cards[3])

    for old_video in output_dir.glob("*.mp4"):
        old_video.unlink()

    video = output_dir / f"{title}.mp4"
    build_video_with_music(cards, video, title)
    print(
        json.dumps(
            {
                "title": title,
                "duration_seconds": DURATION_SECONDS,
                "cards": [str(path) for path in cards],
                "video": str(video),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

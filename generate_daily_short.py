from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

import generate_media

FPS = 30
DURATION_SECONDS = 16
SECONDS_PER_CARD = 4
MUSIC_FILE = Path("assets/audio/a_night_alone_16s.mp3")
EXPECTED_CARD_NAMES = [
    "01_volatility.png",
    "02_sentiment.png",
    "03_macro.png",
    "04_summary.png",
]


def run(command: list[str], *, quiet: bool = True) -> None:
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else None,
    )


def probe_json(path: Path) -> dict[str, Any]:
    return json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            text=True,
        )
    )


def probe_duration(path: Path) -> float:
    data = probe_json(path)
    return float(data["format"]["duration"])


def ensure_music() -> Path:
    if not MUSIC_FILE.exists():
        raise FileNotFoundError(
            f"Fixed Short music is missing: {MUSIC_FILE}. "
            "The approved 16-second music file must remain at this exact path."
        )
    duration = probe_duration(MUSIC_FILE)
    if not 15.8 <= duration <= 16.2:
        raise RuntimeError(f"Fixed music must be about 16 seconds; got {duration:.3f}s")
    return MUSIC_FILE


def validate_cards(cards: list[Path]) -> None:
    if len(cards) != 4:
        raise RuntimeError(f"Expected exactly four cards, got {len(cards)}")
    if [card.name for card in cards] != EXPECTED_CARD_NAMES:
        raise RuntimeError(f"Unexpected card order/names: {[card.name for card in cards]}")
    for card in cards:
        if not card.exists() or card.stat().st_size == 0:
            raise FileNotFoundError(f"Missing rendered card: {card}")
        with Image.open(card) as image:
            if image.size != (1080, 1920):
                raise RuntimeError(f"Unexpected image size for {card}: {image.size}")
            if image.mode != "RGB":
                raise RuntimeError(f"Expected RGB image for {card}, got {image.mode}")


def build_silent_video(cards: list[Path], output: Path) -> None:
    validate_cards(cards)
    with tempfile.TemporaryDirectory() as temp_name:
        temp = Path(temp_name)
        segments: list[Path] = []
        for index, card in enumerate(cards):
            segment = temp / f"segment_{index:02d}.mp4"
            run(
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
                    str(SECONDS_PER_CARD),
                    "-an",
                    "-r",
                    str(FPS),
                    "-c:v",
                    "libx264",
                    "-profile:v",
                    "baseline",
                    "-level:v",
                    "4.2",
                    "-preset",
                    "medium",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-g",
                    str(FPS),
                    "-keyint_min",
                    str(FPS),
                    "-sc_threshold",
                    "0",
                    "-movflags",
                    "+faststart",
                    str(segment),
                ]
            )
            segments.append(segment)

        concat_file = temp / "segments.txt"
        concat_file.write_text(
            "\n".join(f"file '{segment.as_posix()}'" for segment in segments),
            encoding="utf-8",
        )
        run(
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
                "-profile:v",
                "baseline",
                "-level:v",
                "4.2",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )


def assert_faststart(path: Path) -> None:
    payload = path.read_bytes()
    moov = payload.find(b"moov")
    mdat = payload.find(b"mdat")
    if moov < 0 or mdat < 0 or moov > mdat:
        raise RuntimeError(
            f"MP4 is not faststart-compatible: moov={moov}, mdat={mdat}"
        )


def validate_final_video(path: Path) -> dict[str, Any]:
    data = probe_json(path)
    streams = data.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(video_streams) != 1:
        raise RuntimeError(f"Expected one video stream, got {len(video_streams)}")
    if len(audio_streams) != 1:
        raise RuntimeError(f"Expected one audio stream, got {len(audio_streams)}")

    video = video_streams[0]
    audio = audio_streams[0]
    duration = float(data["format"]["duration"])
    profile = str(video.get("profile", "")).strip().lower()
    sar = str(video.get("sample_aspect_ratio", "")).strip()
    dar = str(video.get("display_aspect_ratio", "")).strip()
    checks = {
        "duration": 15.8 <= duration <= 16.2,
        "width": int(video.get("width", 0)) == 1080,
        "height": int(video.get("height", 0)) == 1920,
        "sample_aspect_ratio": sar == "1:1",
        "display_aspect_ratio": dar == "9:16",
        "video_codec": str(video.get("codec_name", "")).lower() == "h264",
        "profile": profile in {"baseline", "constrained baseline"},
        "pixel_format": str(video.get("pix_fmt", "")).lower() == "yuv420p",
        "audio_codec": str(audio.get("codec_name", "")).lower() == "aac",
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Final MP4 validation failed: {failed}; probe={data}")
    assert_faststart(path)
    return {
        "duration_seconds": round(duration, 3),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "sample_aspect_ratio": sar,
        "display_aspect_ratio": dar,
        "video_codec": video["codec_name"],
        "profile": video.get("profile"),
        "pixel_format": video.get("pix_fmt"),
        "audio_codec": audio["codec_name"],
        "faststart": True,
    }


def build_video_with_music(cards: list[Path], output: Path, title: str) -> dict[str, Any]:
    music = ensure_music()
    with tempfile.TemporaryDirectory() as temp_name:
        silent_video = Path(temp_name) / "silent.mp4"
        build_silent_video(cards, silent_video)
        run(
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
                "-vf",
                "setsar=1,setdar=9/16",
                "-c:v",
                "libx264",
                "-profile:v",
                "baseline",
                "-level:v",
                "4.2",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-t",
                str(DURATION_SECONDS),
                "-shortest",
                "-metadata",
                f"title={title}",
                "-aspect",
                "9:16",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
    return validate_final_video(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/latest_data.json")
    parser.add_argument("--output-dir", default="output/media")
    args = parser.parse_args()

    input_path = Path(args.input)
    data: dict[str, Any] = json.loads(input_path.read_text(encoding="utf-8"))
    market_date = str(data["market_date"])
    title = f"Market Risk Monitor {market_date}"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cards = [output_dir / name for name in EXPECTED_CARD_NAMES]

    generate_media.render_volatility(data, cards[0])
    generate_media.render_sentiment(data, cards[1])
    generate_media.render_macro(data, cards[2])
    generate_media.render_summary(data, cards[3])
    validate_cards(cards)

    for old_video in output_dir.glob("Market Risk Monitor *.mp4"):
        old_video.unlink()
    video = output_dir / f"{title}.mp4"
    media_info = build_video_with_music(cards, video, title)

    print(
        json.dumps(
            {
                "title": title,
                "cards": [str(path) for path in cards],
                "video": str(video),
                "media_info": media_info,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

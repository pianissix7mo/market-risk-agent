import json
import os
import subprocess
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_metadata(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("TITLE\n") or "\n\nDESCRIPTION\n" not in text:
        raise ValueError(f"Unexpected metadata format in {path}")

    title_part, description = text.split("\n\nDESCRIPTION\n", 1)
    title = title_part.removeprefix("TITLE\n").strip()
    description = description.strip()

    if not title:
        raise ValueError("YouTube title is empty")
    if len(title) > 100:
        raise ValueError(f"YouTube title is too long ({len(title)} chars): {title}")

    # Keep an explicit Shorts signal in both title/description metadata.
    if "#shorts" not in title.lower():
        title = f"{title} #Shorts"
    if "#shorts" not in description.lower():
        description = f"{description}\n\n#Shorts"

    return title, description


def find_video(media_dir: Path) -> Path:
    videos = sorted(media_dir.glob("Market Risk Monitor *.mp4"))
    if len(videos) != 1:
        raise RuntimeError(
            f"Expected exactly one Market Risk Monitor MP4 in {media_dir}, found {len(videos)}"
        )
    return videos[0]


def inspect_short_format(video_path: Path) -> None:
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,sample_aspect_ratio,display_aspect_ratio:format=duration",
                "-of",
                "json",
                str(video_path),
            ],
            text=True,
        )
    )

    stream = probe["streams"][0]
    width = int(stream["width"])
    height = int(stream["height"])
    duration = float(probe["format"]["duration"])
    sar = stream.get("sample_aspect_ratio", "unknown")
    dar = stream.get("display_aspect_ratio", "unknown")

    print("Shorts format diagnostics:")
    print(f"  resolution: {width}x{height}")
    print(f"  duration: {duration:.3f}s")
    print(f"  sample_aspect_ratio: {sar}")
    print(f"  display_aspect_ratio: {dar}")

    if width >= height:
        raise RuntimeError(f"Video is not portrait: {width}x{height}")
    if duration > 180.0:
        raise RuntimeError(f"Video is longer than 3 minutes: {duration:.3f}s")


def build_credentials() -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=require_env("YOUTUBE_REFRESH_TOKEN"),
        token_uri=TOKEN_URI,
        client_id=require_env("YOUTUBE_CLIENT_ID"),
        client_secret=require_env("YOUTUBE_CLIENT_SECRET"),
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def upload_video(video_path: Path, title: str, description: str) -> str:
    privacy_status = os.environ.get("YOUTUBE_PRIVACY_STATUS", "private").strip().lower()
    if privacy_status not in {"private", "unlisted", "public"}:
        raise ValueError(f"Invalid YOUTUBE_PRIVACY_STATUS: {privacy_status}")

    youtube = build(
        "youtube",
        "v3",
        credentials=build_credentials(),
        cache_discovery=False,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": "27",
                "tags": ["Shorts", "美股", "Market Risk"],
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        },
        media_body=MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            chunksize=8 * 1024 * 1024,
            resumable=True,
        ),
        notifySubscribers=False,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status is not None:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"YouTube upload successful: {video_id}")
    print(f"Standard URL: https://youtu.be/{video_id}")
    print(f"Shorts URL: https://www.youtube.com/shorts/{video_id}")
    print(f"Privacy: {privacy_status}")
    return video_id


def main() -> None:
    media_dir = Path("output/media")
    metadata_path = media_dir / "title_description.txt"

    if not metadata_path.is_file():
        raise FileNotFoundError(metadata_path)

    video_path = find_video(media_dir)
    inspect_short_format(video_path)
    title, description = parse_metadata(metadata_path)

    print(f"Uploading as Shorts-compatible portrait video: {video_path}")
    print(f"Title: {title}")
    upload_video(video_path, title, description)


if __name__ == "__main__":
    main()

import base64
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
UPLOAD_STATE_BRANCH = os.environ.get("UPLOAD_STATE_BRANCH", "upload-state").strip() or "upload-state"
UPLOAD_STATE_PATH = "upload_state.json"


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


def privacy_status() -> str:
    value = os.environ.get("YOUTUBE_PRIVACY_STATUS", "unlisted").strip().lower()
    if value not in {"private", "unlisted", "public"}:
        raise ValueError(f"Invalid YOUTUBE_PRIVACY_STATUS: {value}")
    return value


def build_youtube_client():
    return build(
        "youtube",
        "v3",
        credentials=build_credentials(),
        cache_discovery=False,
    )


def upload_video(youtube, video_path: Path, title: str, description: str, privacy: str) -> str:
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
                "privacyStatus": privacy,
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
    print(f"Privacy: {privacy}")
    return video_id


def _github_headers() -> dict[str, str]:
    token = require_env("GITHUB_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_api(method: str, path: str, *, json_body=None, allow_404=False):
    repo = require_env("GITHUB_REPOSITORY")
    url = f"https://api.github.com/repos/{repo}/{path.lstrip('/')}"
    response = requests.request(
        method,
        url,
        headers=_github_headers(),
        json=json_body,
        timeout=30,
    )
    if allow_404 and response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json() if response.content else {}


def _ensure_upload_state_branch() -> None:
    ref_path = f"git/ref/heads/{UPLOAD_STATE_BRANCH}"
    if _github_api("GET", ref_path, allow_404=True) is not None:
        return

    base_sha = require_env("GITHUB_SHA")
    try:
        _github_api(
            "POST",
            "git/refs",
            json_body={"ref": f"refs/heads/{UPLOAD_STATE_BRANCH}", "sha": base_sha},
        )
        print(f"Created upload state branch: {UPLOAD_STATE_BRANCH}")
    except requests.HTTPError as exc:
        # A concurrent creator may have won the race. Verify before failing.
        if _github_api("GET", ref_path, allow_404=True) is None:
            raise exc


def load_upload_state() -> tuple[dict, str | None]:
    _ensure_upload_state_branch()
    item = _github_api(
        "GET",
        f"contents/{UPLOAD_STATE_PATH}?ref={UPLOAD_STATE_BRANCH}",
        allow_404=True,
    )
    if item is None:
        return {"version": 1, "uploads": {}}, None

    raw = base64.b64decode(item["content"]).decode("utf-8")
    state = json.loads(raw)
    if not isinstance(state, dict):
        raise RuntimeError("Upload state is not a JSON object")
    uploads = state.setdefault("uploads", {})
    if not isinstance(uploads, dict):
        raise RuntimeError("Upload state 'uploads' must be an object")
    state.setdefault("version", 1)
    return state, item.get("sha")


def save_upload_state(state: dict, sha: str | None, message: str) -> str:
    payload = {
        "message": message,
        "branch": UPLOAD_STATE_BRANCH,
        "content": base64.b64encode(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        ).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha

    result = _github_api(
        "PUT",
        f"contents/{UPLOAD_STATE_PATH}",
        json_body=payload,
    )
    return result["content"]["sha"]


def _state_key(channel: str, market_date: str) -> str:
    return f"{channel}:{market_date}"


def _write_receipt(entry: dict) -> None:
    path = Path("output/upload_receipt.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    media_dir = Path("output/media")
    metadata_path = media_dir / "title_description.txt"
    data_path = Path("output/latest_data.json")

    if not metadata_path.is_file():
        raise FileNotFoundError(metadata_path)
    if not data_path.is_file():
        raise FileNotFoundError(data_path)

    market_data = json.loads(data_path.read_text(encoding="utf-8"))
    market_date = str(market_data.get("market_date", "")).strip()
    if not market_date:
        raise RuntimeError("market_date is missing from output/latest_data.json")

    video_path = find_video(media_dir)
    inspect_short_format(video_path)
    title, description = parse_metadata(metadata_path)
    privacy = privacy_status()

    channel = os.environ.get("YOUTUBE_CHANNEL_KEY", "finance").strip() or "finance"
    key = _state_key(channel, market_date)
    state, state_sha = load_upload_state()
    existing = state["uploads"].get(key)

    if isinstance(existing, dict):
        status = str(existing.get("status", "")).lower()
        if status == "confirmed" and existing.get("video_id"):
            print(
                f"Upload already confirmed for {key}: {existing['video_id']}. "
                "Skipping duplicate YouTube upload."
            )
            _write_receipt(existing)
            return
        if status == "pending":
            raise RuntimeError(
                f"Upload state for {key} is pending from run "
                f"{existing.get('run_id', 'unknown')}. Refusing an automatic retry "
                "because the previous YouTube result is ambiguous; reconcile that "
                "video/state first to avoid a duplicate upload."
            )

    # Authenticate before writing the pending marker so credential failures do not
    # leave an unnecessary ambiguous state.
    youtube = build_youtube_client()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pending = {
        "channel": channel,
        "market_date": market_date,
        "status": "pending",
        "video_id": None,
        "privacy": privacy,
        "title": title,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "updated_at": now,
    }
    state["uploads"][key] = pending
    state_sha = save_upload_state(
        state,
        state_sha,
        f"Mark Market Risk upload pending for {channel} {market_date}",
    )

    print(f"Uploading as Shorts-compatible portrait video: {video_path}")
    print(f"Title: {title}")
    video_id = upload_video(youtube, video_path, title, description, privacy)

    confirmed = {
        **pending,
        "status": "confirmed",
        "video_id": video_id,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    state["uploads"][key] = confirmed
    save_upload_state(
        state,
        state_sha,
        f"Confirm Market Risk upload for {channel} {market_date}",
    )
    _write_receipt(confirmed)


if __name__ == "__main__":
    main()

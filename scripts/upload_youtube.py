#!/usr/bin/env python3
"""upload_youtube.py - upload a video to the owner's YouTube channel.

DEFAULT OFF. Nothing uploads unless the owner turns it on twice:
a flag AND an environment variable, and only with THEIR OWN
credentials. This is deliberate: an upload goes to a real channel,
so the tool must never upload on its own.

    # What WOULD upload (no network, no credentials needed):
    python3 scripts/upload_youtube.py --video video.mp4 \\
        --title "My title" --dry-run --json

    # Real upload (owner's channel, private by default):
    YOUTUBE_UPLOAD_ENABLED=1 python3 scripts/upload_youtube.py \\
        --video video.mp4 --title "My title" \\
        --description "..." --tags a b c --privacy private \\
        --credentials ~/secrets/yt-client.json \\
        --token ~/secrets/yt-token.json

Credentials ONLY from files the owner points at (flags) or from
environment variables - never in the repo, never committed, never
printed. The token and secret values are never written to stdout,
stderr, or any file this script creates.

    YOUTUBE_CLIENT_SECRETS_FILE - OAuth client secrets JSON
        (Google's standard format: {"installed": {...}} or
        {"web": {...}} with client_id / client_secret)
    YOUTUBE_TOKEN_FILE          - stored token JSON:
        {"client_id", "client_secret", "refresh_token",
         "token_uri" (optional, default Google's token endpoint)}

Setup the owner must do once (exact steps - the runner prints
these when anything is missing):
    1. In Google Cloud Console, create a project, enable the
       YouTube Data API v3, create OAuth 2.0 credentials
       (Desktop app), download the client secrets JSON.
    2. Run the OAuth consent flow once to get a refresh token
       (scope: https://www.googleapis.com/auth/youtube.upload)
       and save it as the token JSON above.
    3. Point the flags / env vars at those two files and set
       YOUTUBE_UPLOAD_ENABLED=1.

Upload method: YouTube Data API v3 resumable upload
(POST .../upload/youtube/v3/videos?uploadType=resumable, then
chunked PUTs of 8 MB). Privacy defaults to "private" so even an
enabled upload never goes public by accident - pass
--privacy unlisted or public only on purpose.

Exit codes: 0 = uploaded (prints {"video_id", "url"}) or dry-run
plan printed; 1 = upload failed or credentials missing (error on
stderr, no secrets in it); 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

UPLOAD_URL = ("https://www.googleapis.com/upload/youtube/v3/videos"
              "?uploadType=resumable&part=snippet,status")
TOKEN_URL_DEFAULT = "https://oauth2.googleapis.com/token"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
CHUNK_SIZE = 8 * 1024 * 1024
PRIVACY_CHOICES = ("private", "unlisted", "public")


class UploadError(Exception):
    """An upload failure. Messages never contain secrets."""


def _post_json(url: str, payload: dict, headers: dict | None = None,
               timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise UploadError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise UploadError(f"network error calling {url}: {exc}") from exc


def load_client_secrets(path: str) -> dict:
    """Read an OAuth client-secrets file. Returns client_id/secret."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise UploadError(f"client secrets file not found: {path}")
    except json.JSONDecodeError as exc:
        raise UploadError(f"client secrets file is not valid JSON: "
                          f"{path}: {exc}")
    section = data.get("installed") or data.get("web") or data
    client_id = section.get("client_id")
    client_secret = section.get("client_secret")
    if not client_id or not client_secret:
        raise UploadError(
            f"client secrets file has no client_id/client_secret: {path}")
    return {"client_id": client_id, "client_secret": client_secret}


def load_token(path: str) -> dict:
    """Read a stored token file. Returns the refresh credentials."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise UploadError(f"token file not found: {path}")
    except json.JSONDecodeError as exc:
        raise UploadError(f"token file is not valid JSON: {path}: {exc}")
    refresh = data.get("refresh_token")
    if not refresh:
        raise UploadError(f"token file has no refresh_token: {path}")
    return {
        "client_id": data.get("client_id"),
        "client_secret": data.get("client_secret"),
        "refresh_token": refresh,
        "token_uri": data.get("token_uri") or TOKEN_URL_DEFAULT,
    }


def resolve_credentials(credentials_path: str | None,
                        token_path: str | None) -> dict:
    """Merge flag/env credential sources. Raises UploadError naming
    exactly what is missing - never a guess, never a fake upload."""
    secrets_path = credentials_path or os.environ.get(
        "YOUTUBE_CLIENT_SECRETS_FILE", "")
    token_file = token_path or os.environ.get("YOUTUBE_TOKEN_FILE", "")
    missing = []
    if not secrets_path:
        missing.append("client secrets file (--credentials or "
                       "YOUTUBE_CLIENT_SECRETS_FILE)")
    if not token_file:
        missing.append("token file (--token or YOUTUBE_TOKEN_FILE)")
    if missing:
        raise UploadError("missing upload credentials: "
                          + "; ".join(missing))
    secrets = load_client_secrets(secrets_path)
    token = load_token(token_file)
    # The token file carries its own client id/secret when the
    # consent flow saved them; the secrets file wins when both exist.
    token["client_id"] = token.get("client_id") or secrets["client_id"]
    token["client_secret"] = (token.get("client_secret")
                              or secrets["client_secret"])
    return token


def refresh_access_token(creds: dict) -> str:
    """Exchange the refresh token for a short-lived access token."""
    body = {
        "grant_type": "refresh_token",
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
    }
    data = _post_json(creds.get("token_uri") or TOKEN_URL_DEFAULT, body)
    token = data.get("access_token")
    if not token:
        raise UploadError("token endpoint returned no access_token "
                          "(check the refresh token and client id/secret)")
    return token


def build_metadata(title: str, description: str, tags: list[str],
                   privacy: str, category: str) -> dict:
    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category,
        },
        "status": {"privacyStatus": privacy},
    }


def plan_upload(video_path: str, title: str, description: str,
                tags: list[str], privacy: str, category: str) -> dict:
    """The dry-run plan: exactly what WOULD upload. No network."""
    if not os.path.exists(video_path):
        raise UploadError(f"video file not found: {video_path}")
    return {
        "dry_run": True,
        "video": video_path,
        "size_bytes": os.path.getsize(video_path),
        "title": title,
        "description": description,
        "tags": tags,
        "privacy": privacy,
        "category_id": category,
        "target": "YouTube Data API v3 (resumable upload)",
        "note": "DRY RUN - nothing was sent, nothing was uploaded.",
    }


def _start_session(metadata: dict, size: int, access_token: str) -> str:
    req = urllib.request.Request(
        UPLOAD_URL, data=json.dumps(metadata).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(size),
        }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            session = resp.headers.get("Location")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise UploadError(f"upload session failed, HTTP {exc.code}: "
                          f"{detail}") from exc
    except urllib.error.URLError as exc:
        raise UploadError(f"network error starting upload: {exc}") from exc
    if not session:
        raise UploadError("upload session started but YouTube returned "
                          "no session URL")
    return session


def _upload_chunks(session_url: str, video_path: str, size: int,
                   access_token: str) -> str:
    """PUT the file in 8 MB chunks. Returns the video id."""
    offset = 0
    with open(video_path, "rb") as fh:
        while offset < size:
            chunk = fh.read(CHUNK_SIZE)
            end = offset + len(chunk) - 1
            req = urllib.request.Request(
                session_url, data=chunk,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                }, method="PUT")
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 308:
                    # Resume Incomplete - keep going from the Range
                    # header YouTube returns.
                    ranged = exc.headers.get("Range", "")
                    if ranged.startswith("bytes=0-"):
                        offset = int(ranged.split("-")[1]) + 1
                        fh.seek(offset)
                        continue
                    raise UploadError(
                        "upload interrupted (308) with no usable "
                        "Range header - retry the upload") from exc
                detail = exc.read().decode("utf-8", "replace")[:500]
                raise UploadError(
                    f"upload chunk failed, HTTP {exc.code}: {detail}"
                ) from exc
            except urllib.error.URLError as exc:
                raise UploadError(
                    f"network error during upload at byte {offset}: "
                    f"{exc}") from exc
            video_id = body.get("id")
            if not video_id:
                raise UploadError("upload finished but YouTube returned "
                                  "no video id")
            return video_id
    raise UploadError("upload ended without a video id")


def do_upload(video_path: str, title: str, description: str,
              tags: list[str], privacy: str, category: str,
              creds: dict) -> dict:
    """Real upload. Only call when the owner enabled it twice
    (flag + YOUTUBE_UPLOAD_ENABLED=1) with their own credentials."""
    if not os.path.exists(video_path):
        raise UploadError(f"video file not found: {video_path}")
    if privacy not in PRIVACY_CHOICES:
        raise UploadError(f"privacy must be one of {PRIVACY_CHOICES}, "
                          f"got {privacy!r}")
    access_token = refresh_access_token(creds)
    metadata = build_metadata(title, description, tags, privacy, category)
    size = os.path.getsize(video_path)
    session = _start_session(metadata, size, access_token)
    video_id = _upload_chunks(session, video_path, size, access_token)
    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "privacy": privacy,
        "title": title,
    }


def missing_setup() -> list[str]:
    """The exact setup steps, for the honest-failure stage file."""
    return [
        "1. Google Cloud Console: create a project, enable the "
        "YouTube Data API v3, create OAuth 2.0 credentials "
        "(Desktop app), download the client secrets JSON.",
        "2. Run the OAuth consent flow once (scope "
        "https://www.googleapis.com/auth/youtube.upload) and save "
        "the refresh token as a token JSON file.",
        "3. Set YOUTUBE_CLIENT_SECRETS_FILE and YOUTUBE_TOKEN_FILE "
        "(or pass --credentials / --token), set "
        "YOUTUBE_UPLOAD_ENABLED=1, and re-run with --auto-upload.",
        "4. Privacy defaults to private - pass --upload-privacy "
        "unlisted or public only on purpose.",
    ]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Upload a video to the owner's YouTube channel. "
                    "DEFAULT OFF - needs --auto-upload (runner) or "
                    "YOUTUBE_UPLOAD_ENABLED=1 plus the owner's own "
                    "credentials. --dry-run never touches the network.")
    ap.add_argument("--video", required=True, help="Video file to upload.")
    ap.add_argument("--title", required=True, help="Video title.")
    ap.add_argument("--description", default="",
                    help="Video description.")
    ap.add_argument("--tags", nargs="*", default=[],
                    help="Tags (space separated).")
    ap.add_argument("--privacy", default="private",
                    choices=PRIVACY_CHOICES,
                    help="Privacy status (default: private).")
    ap.add_argument("--category", default="22",
                    help="YouTube category id (default: 22).")
    ap.add_argument("--credentials", default="",
                    help="OAuth client secrets JSON path (or "
                         "YOUTUBE_CLIENT_SECRETS_FILE).")
    ap.add_argument("--token", default="",
                    help="Stored token JSON path (or "
                         "YOUTUBE_TOKEN_FILE).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print exactly what WOULD upload; no network.")
    ap.add_argument("--json", action="store_true",
                    help="Machine-readable output.")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.dry_run:
            plan = plan_upload(args.video, args.title, args.description,
                               args.tags, args.privacy, args.category)
            if args.json:
                print(json.dumps(plan, indent=1))
            else:
                print("DRY RUN - nothing was sent, nothing was uploaded.")
                for key, value in plan.items():
                    if key in ("dry_run", "note"):
                        continue
                    print(f"  {key}: {value}")
            return 0
        if os.environ.get("YOUTUBE_UPLOAD_ENABLED") != "1":
            print("upload is OFF: set YOUTUBE_UPLOAD_ENABLED=1 and "
                  "re-run with the owner's credentials (see "
                  "--help / README 'Auto-upload').", file=sys.stderr)
            for step in missing_setup():
                print(f"  {step}", file=sys.stderr)
            return 1
        creds = resolve_credentials(args.credentials or None,
                                    args.token or None)
        result = do_upload(args.video, args.title, args.description,
                           args.tags, args.privacy, args.category, creds)
    except UploadError as exc:
        print(f"upload failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print(f"uploaded: {result['url']} (privacy: "
              f"{result['privacy']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

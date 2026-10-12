from __future__ import annotations

import json
import logging
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import Settings
from .scripts import VideoCopy

log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def upload_video(video_path: Path, copy: VideoCopy, cfg: Settings) -> str:
    if not cfg.yt_token_json:
        raise RuntimeError("YOUTUBE_TOKEN_JSON is missing; configure OAuth before enabling uploads")
    try:
        token = json.loads(cfg.yt_token_json)
    except json.JSONDecodeError as exc:
        raise ValueError("YOUTUBE_TOKEN_JSON must contain the complete OAuth token.json object") from exc
    creds = Credentials.from_authorized_user_info(token, SCOPES)
    if not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError("YouTube OAuth token has no refresh_token; re-authorize with offline access")
        creds.refresh(__import__("google.auth.transport.requests", fromlist=["Request"]).Request())
    service = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = {
        "snippet": {"title": copy.title, "description": copy.description, "tags": copy.tags,
                    "categoryId": cfg.yt_category, "defaultLanguage": "en"},
        "status": {"privacyStatus": cfg.yt_privacy, "selfDeclaredMadeForKids": cfg.yt_made_for_kids},
    }
    request = service.videos().insert(part="snippet,status", body=body,
        notifySubscribers=cfg.yt_notify,
        media_body=MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True))
    response = None
    while response is None:
        # Retry chunks on the same resumable upload session to avoid restarting
        # the entire upload (and creating a duplicate) after a transient failure.
        _, response = request.next_chunk(num_retries=5)
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube upload completed without a video ID")
    log.info("Uploaded video https://youtube.com/shorts/%s", video_id)
    return video_id

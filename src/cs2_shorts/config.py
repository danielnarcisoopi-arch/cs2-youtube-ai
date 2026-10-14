from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    currency: str = os.getenv("MARKET_CURRENCY", "EUR").upper()
    app_id: int = int(os.getenv("SKINPORT_APP_ID", "730"))
    min_volume_24h: int = int(os.getenv("MIN_ITEM_VOLUME_24H", "1"))
    min_listings: int = int(os.getenv("MIN_ITEM_LISTINGS", "1"))
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", "output"))
    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
    history_days: int = int(os.getenv("HISTORY_DAYS", "35"))
    image_fetch: bool = _bool("MARKET_IMAGE_FETCH", True)
    image_timeout: int = int(os.getenv("IMAGE_TIMEOUT_SECONDS", "8"))
    skinshotter_enabled: bool = _bool("SKINSHOTTER_ENABLED", False)
    skinshotter_clip_seconds: float = float(os.getenv("SKINSHOTTER_CLIP_SECONDS", "5"))
    skinshotter_fallback_to_static: bool = _bool("SKINSHOTTER_FALLBACK_TO_STATIC", False)
    voice: str = os.getenv("EDGE_TTS_VOICE", "en-US-GuyNeural")
    upload_enabled: bool = _bool("UPLOAD_ENABLED", False)
    yt_token_json: str = os.getenv("YOUTUBE_TOKEN_JSON", "")
    yt_privacy: str = os.getenv("YOUTUBE_PRIVACY_STATUS", "public")
    yt_category: str = os.getenv("YOUTUBE_CATEGORY_ID", "20")
    yt_notify: bool = _bool("YOUTUBE_NOTIFY_SUBSCRIBERS", False)
    yt_made_for_kids: bool = _bool("YOUTUBE_MADE_FOR_KIDS", False)
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()


settings = Settings()


def validate_settings(s: Settings = settings) -> None:
    if s.currency not in {"AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "EUR", "GBP", "HRK", "NOK", "PLN", "RUB", "SEK", "TRY", "USD"}:
        raise ValueError(f"Unsupported Skinport currency: {s.currency}")
    if s.history_days < 8:
        raise ValueError("HISTORY_DAYS must be at least 8 to retain a 7-day comparison baseline")
    if not 3 <= s.skinshotter_clip_seconds <= 12:
        raise ValueError("SKINSHOTTER_CLIP_SECONDS must be between 3 and 12")
    if s.yt_privacy not in {"public", "unlisted", "private"}:
        raise ValueError("YOUTUBE_PRIVACY_STATUS must be public, unlisted, or private")

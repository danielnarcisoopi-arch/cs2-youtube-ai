from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .analytics import choose_topic, rankings
from .config import settings, validate_settings
from .media import render_video
from .providers.skinport import SkinportProvider
from .scripts import build_copy
from .storage import MarketStore
from .youtube import upload_video

log = logging.getLogger(__name__)


def run() -> Path:
    cfg = settings
    validate_settings(cfg)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    store = MarketStore(cfg.data_dir / "market.sqlite3")
    try:
        rows = SkinportProvider(currency=cfg.currency, app_id=cfg.app_id).get_market_data()
        captured_at = store.insert_snapshot(rows)
        store.prune(cfg.history_days)
        current = store.candidates(captured_at)
        rank = rankings(current, cfg.min_volume_24h, cfg.min_listings)
        now = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Lisbon"))
        slot = now.hour // 4
        topic_idx = ((now.timetuple().tm_yday * 4) + slot) % 6
        topic, selected = choose_topic(rank, topic_idx)
        if not selected:
            raise RuntimeError("No items meet the minimum activity/data rules; refusing to fabricate a market story")
        # Avoid publishing identical item/topic combinations within the same daily cycle.
        selected = [r for r in selected if not store.already_published(r["name"], topic)] or selected
        copy = build_copy(topic, selected[:5], cfg.currency)
        featured_name = copy.featured["name"]
        trend = store.db.execute("SELECT captured_at,price FROM snapshots WHERE name=? ORDER BY captured_at DESC LIMIT 40", (featured_name,)).fetchall()
        chart_points = [(datetime.fromisoformat(r["captured_at"]).astimezone(ZoneInfo("Europe/Lisbon")).strftime("%d %b"), r["price"])
                        for r in reversed(trend)]
        stamp = now.strftime("%Y%m%d-%H%M")
        video_path = cfg.output_dir / f"{stamp}-{topic}.mp4"
        duration = render_video(copy, cfg.currency, copy.featured.get("market_page"), chart_points,
            cfg.data_dir / "render", video_path, cfg.voice, cfg.image_fetch, cfg.image_timeout)
        metadata = {"captured_at": captured_at, "topic": topic, "title": copy.title,
                    "duration_seconds": round(duration, 2), "currency": cfg.currency,
                    "market_source": "Skinport public REST API", "featured_item": featured_name,
                    "video_file": str(video_path), "upload_enabled": cfg.upload_enabled}
        (cfg.output_dir / f"{stamp}-{topic}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        log.info("Rendered %s (%s seconds): %s", video_path, round(duration, 1), copy.title)
        if cfg.upload_enabled:
            video_id = upload_video(video_path, copy, cfg)
            store.record_published(topic, video_id, copy.title, featured_name)
            log.info("Publish URL: https://youtube.com/shorts/%s", video_id)
        return video_path
    finally:
        store.close()


def main() -> None:
    logging.basicConfig(level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run()


if __name__ == "__main__":
    main()

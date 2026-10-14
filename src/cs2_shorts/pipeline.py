from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .analytics import choose_spotlight, rankings
from .config import settings, validate_settings
from .media import filter_rankings_to_weapon_skins, render_video
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
        # Skinport also returns music kits and other collectibles. Select from
        # weapon skins with verified catalog art so a non-weapon cannot break a run.
        rank = filter_rankings_to_weapon_skins(rank, cfg.data_dir / "render", cfg.image_timeout)
        now = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Lisbon"))
        try:
            recent_items = store.recently_published_items(within_hours=48)
            topic, featured = choose_spotlight(rank, recent_items)
        except ValueError:
            raise RuntimeError("No items meet the minimum activity/data rules; refusing to fabricate a market story")
        # Keep the topic selection, then turn its strongest fresh rows into a quick showcase list.
        topic_rows = rank.get(topic, [])
        fresh_rows = [row for row in topic_rows if row["name"] not in recent_items]
        eligible = fresh_rows or topic_rows
        showcase_rows = [featured, *[row for row in eligible if row["name"] != featured["name"]][:4]]
        hook_variant = secrets.choice(("market_move", "price_gap"))
        copy = build_copy(topic, showcase_rows, cfg.currency, spotlight=True, hook_variant=hook_variant)
        featured_name = copy.featured["name"]
        run_id = os.getenv("GITHUB_RUN_ID") or secrets.token_hex(3)
        stamp = f"{now.strftime('%Y%m%d-%H%M')}-{run_id}"
        video_path = cfg.output_dir / f"{stamp}-{topic}.mp4"
        duration = render_video(copy, cfg.currency, cfg.data_dir / "render", video_path,
            cfg.voice, cfg.image_fetch, cfg.image_timeout,
            cfg.skinshotter_enabled, cfg.skinshotter_clip_seconds,
            cfg.skinshotter_fallback_to_static)
        renderer_status_path = cfg.data_dir / "render" / "renderer-status.json"
        renderer_status = json.loads(renderer_status_path.read_text(encoding="utf-8")) if renderer_status_path.exists() else {}
        metadata = {"captured_at": captured_at, "topic": topic, "title": copy.title,
                    "duration_seconds": round(duration, 2), "currency": cfg.currency,
                    "visual_renderer": renderer_status.get("renderer", "static catalog art"),
                    "visual_renderer_error": renderer_status.get("error"),
                    "market_source": "Skinport public REST API", "featured_item": featured_name,
                    "featured_items": [row["name"] for row in copy.items],
                    "hook_variant": copy.hook_variant,
                    "current_lowest_listing": copy.featured.get("price"),
                    "reported_average_sale_24h": copy.featured.get("avg_sale_24h"),
                    "change_24h_pct": copy.featured.get("change_24h_pct"),
                    "change_7d_pct": copy.featured.get("change_7d_pct"),
                    "video_file": str(video_path), "upload_enabled": cfg.upload_enabled}
        metadata_path = cfg.output_dir / f"{stamp}-{topic}.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        log.info("Rendered %s (%s seconds): %s", video_path, round(duration, 1), copy.title)
        if cfg.upload_enabled:
            video_id = upload_video(video_path, copy, cfg)
            metadata["youtube_video_id"] = video_id
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            store.record_published(topic, video_id, copy.title, [row["name"] for row in copy.items],
                                   copy.hook_variant, duration)
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

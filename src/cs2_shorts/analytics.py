from __future__ import annotations

from typing import Any


def rankings(rows: list[dict[str, Any]], min_volume: int = 1, min_listings: int = 1) -> dict[str, list[dict[str, Any]]]:
    liquid = [r for r in rows if r["volume_24h"] >= min_volume and r["quantity"] >= min_listings]
    with_day = [r for r in liquid if r["change_24h_pct"] is not None]
    with_week = [r for r in liquid if r["change_7d_pct"] is not None]
    budget = [r for r in liquid if r["price"] <= 20 and r["avg_sale_24h"]]
    for r in liquid:
        avg = r.get("avg_sale_24h")
        low, high = r.get("min_sale_24h"), r.get("max_sale_24h")
        r["volatility_pct"] = round((high - low) / avg * 100, 2) if avg and low is not None and high is not None else None
    return {
        "gainers": sorted([r for r in with_day if r["change_24h_pct"] > 0], key=lambda x: x["change_24h_pct"], reverse=True)[:10],
        "losers": sorted([r for r in with_day if r["change_24h_pct"] < 0], key=lambda x: x["change_24h_pct"])[:10],
        "weekly": sorted([r for r in with_week if r["change_7d_pct"] is not None], key=lambda x: x["change_7d_pct"], reverse=True)[:10],
        "budget": sorted(budget, key=lambda x: (x["volume_24h"], x["avg_sale_24h"] or 0), reverse=True)[:10],
        "dollar_volume": sorted(liquid, key=lambda x: (x["avg_sale_24h"] or 0) * x["volume_24h"], reverse=True)[:10],
        "volatility": sorted([r for r in liquid if r["volatility_pct"] is not None], key=lambda x: x["volatility_pct"], reverse=True)[:10],
    }


def choose_topic(ranks: dict[str, list[dict[str, Any]]], run_number: int = 0) -> tuple[str, list[dict[str, Any]]]:
    topics = [("gainers", ranks["gainers"]), ("losers", ranks["losers"]),
              ("budget", ranks["budget"]), ("weekly", ranks["weekly"]),
              ("dollar_volume", ranks["dollar_volume"]), ("volatility", ranks["volatility"])]
    for offset in range(len(topics)):
        topic, rows = topics[(run_number + offset) % len(topics)]
        if rows:
            return topic, rows[:5]
    return "market_watch", []

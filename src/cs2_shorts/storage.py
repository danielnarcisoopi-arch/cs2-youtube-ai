from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class MarketStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY, captured_at TEXT NOT NULL, name TEXT NOT NULL,
            price REAL NOT NULL, quantity INTEGER NOT NULL, volume_24h INTEGER NOT NULL,
            avg_sale_24h REAL, avg_sale_7d REAL, min_sale_24h REAL, max_sale_24h REAL, volume_7d INTEGER NOT NULL,
            item_page TEXT, market_page TEXT, currency TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_snap_name_time ON snapshots(name, captured_at);
        CREATE INDEX IF NOT EXISTS idx_snap_time ON snapshots(captured_at);
        CREATE TABLE IF NOT EXISTS published (
            id INTEGER PRIMARY KEY, published_at TEXT NOT NULL, topic TEXT NOT NULL,
            video_id TEXT NOT NULL, title TEXT NOT NULL, item_key TEXT NOT NULL
        );
        """)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def insert_snapshot(self, rows: list[dict[str, Any]], at: datetime | None = None) -> str:
        captured = (at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
        self.db.executemany("""INSERT INTO snapshots
            (captured_at,name,price,quantity,volume_24h,avg_sale_24h,avg_sale_7d,min_sale_24h,max_sale_24h,volume_7d,item_page,market_page,currency)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
            (captured, r["market_hash_name"], r["price"], r["quantity"], r["volume_24h"],
             r.get("avg_sale_24h"), r.get("avg_sale_7d"), r.get("min_sale_24h"), r.get("max_sale_24h"), r["volume_7d"], r.get("item_page"),
             r.get("market_page"), r["currency"]) for r in rows
        ])
        self.db.commit()
        return captured

    def latest_snapshot(self) -> str | None:
        row = self.db.execute("SELECT MAX(captured_at) AS ts FROM snapshots").fetchone()
        return row["ts"] if row and row["ts"] else None

    def candidates(self, captured_at: str) -> list[dict[str, Any]]:
        current = self.db.execute("SELECT * FROM snapshots WHERE captured_at=?", (captured_at,)).fetchall()
        now = datetime.fromisoformat(captured_at)
        result: list[dict[str, Any]] = []
        for row in current:
            entry = dict(row)
            for key, duration in (("price_24h_ago", timedelta(hours=24)), ("price_7d_ago", timedelta(days=7))):
                target = now - duration
                # Nearest earlier point, with a wider tolerance for delayed GH schedules.
                min_time = target - timedelta(hours=8)
                max_time = target + timedelta(hours=8)
                prior = self.db.execute("""SELECT price,captured_at FROM snapshots
                    WHERE name=? AND captured_at BETWEEN ? AND ? ORDER BY ABS(julianday(captured_at)-julianday(?)) LIMIT 1""",
                    (row["name"], min_time.isoformat(timespec="seconds"), max_time.isoformat(timespec="seconds"),
                     target.isoformat(timespec="seconds"))).fetchone()
                entry[key] = prior["price"] if prior else None
            entry["change_24h_pct"] = _pct(entry["price"], entry["price_24h_ago"])
            entry["change_7d_pct"] = _pct(entry["price"], entry["price_7d_ago"])
            result.append(entry)
        return result

    def prune(self, days: int = 35) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        cur = self.db.execute("DELETE FROM snapshots WHERE captured_at < ?", (cutoff,))
        self.db.commit()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return cur.rowcount

    def already_published(self, item_key: str, topic: str, within_hours: int = 18) -> bool:
        since = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat(timespec="seconds")
        return self.db.execute("SELECT 1 FROM published WHERE item_key=? AND topic=? AND published_at>=? LIMIT 1",
                               (item_key, topic, since)).fetchone() is not None

    def record_published(self, topic: str, video_id: str, title: str, item_key: str) -> None:
        self.db.execute("INSERT INTO published(published_at,topic,video_id,title,item_key) VALUES(?,?,?,?,?)",
                        (datetime.now(timezone.utc).isoformat(timespec="seconds"), topic, video_id, title, item_key))
        self.db.commit()


def _pct(current: float, before: float | None) -> float | None:
    if before is None or before <= 0:
        return None
    return round((current / before - 1) * 100, 2)

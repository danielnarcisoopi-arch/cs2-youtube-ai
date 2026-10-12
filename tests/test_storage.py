from datetime import datetime, timezone, timedelta

from cs2_shorts.storage import MarketStore


def test_snapshot_changes_use_nearby_persisted_prices(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    start = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    def row(price):
        return {"market_hash_name": "AK-47 | Redline (Field-Tested)", "price": price, "quantity": 20,
                "volume_24h": 5, "avg_sale_24h": 10, "avg_sale_7d": 9,
                "min_sale_24h": 8, "max_sale_24h": 12, "volume_7d": 30, "currency": "EUR"}
    store.insert_snapshot([row(10)], start)
    store.insert_snapshot([row(9)], start + timedelta(hours=24))
    current = store.candidates((start + timedelta(hours=24)).isoformat(timespec="seconds"))[0]
    assert current["price_24h_ago"] == 10
    assert current["change_24h_pct"] == -10
    assert current["price_7d_ago"] is None
    store.close()

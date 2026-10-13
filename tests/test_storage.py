import sqlite3

from cs2_shorts.storage import MarketStore


def test_published_hook_metadata_migrates_existing_database(tmp_path):
    database = tmp_path / "market.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("""CREATE TABLE published (
        id INTEGER PRIMARY KEY, published_at TEXT NOT NULL, topic TEXT NOT NULL,
        video_id TEXT NOT NULL, title TEXT NOT NULL, item_key TEXT NOT NULL
    )""")
    connection.commit()
    connection.close()

    store = MarketStore(database)
    store.record_published("gainers", "video-1", "Market title", ["Skin Name", "Skin Two"], "price_gap", 22.7)
    row = store.db.execute("SELECT hook_variant,duration_seconds FROM published WHERE video_id='video-1'").fetchone()
    assert row["hook_variant"] == "price_gap"
    assert row["duration_seconds"] == 22.7
    assert store.recently_published_items() == {"Skin Name", "Skin Two"}
    assert store.already_published("Skin Two", "gainers")
    store.close()

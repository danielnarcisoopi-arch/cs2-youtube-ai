from cs2_shorts.analytics import choose_spotlight, choose_topic, rankings


def item(name, **kw):
    base = {"name": name, "price": 15.0, "quantity": 10, "volume_24h": 12,
            "avg_sale_24h": 14.0, "min_sale_24h": 12.0, "max_sale_24h": 16.0,
            "change_24h_pct": 10.0, "change_7d_pct": 5.0}
    base.update(kw)
    return base


def test_rankings_use_real_coverage_and_activity_filters():
    rows = [item("up", change_24h_pct=10), item("down", change_24h_pct=-5),
            item("thin", volume_24h=0), item("no_history", change_24h_pct=None, change_7d_pct=None)]
    result = rankings(rows, min_volume=1, min_listings=1)
    assert [r["name"] for r in result["gainers"]] == ["up"]
    assert [r["name"] for r in result["losers"]] == ["down"]
    assert all(r["name"] != "thin" for r in result["budget"])
    assert result["volatility"][0]["volatility_pct"] == 28.57


def test_topic_picker_skips_empty_rankings():
    empty = {key: [] for key in ("gainers", "losers", "budget", "weekly", "dollar_volume", "volatility")}
    empty["budget"] = [item("budget")]
    assert choose_topic(empty, 0)[0] == "budget"


def test_spotlight_avoids_recent_skins_when_fresh_candidates_exist():
    ranks = {"gainers": [item("recent"), item("fresh")], "losers": [item("another")]}
    topic, selected = choose_spotlight(ranks, {"recent"}, chooser=lambda choices: choices[0])
    assert topic == "gainers"
    assert selected["name"] == "fresh"


def test_spotlight_falls_back_after_fresh_pool_is_exhausted():
    ranks = {"budget": [item("recent")]}
    topic, selected = choose_spotlight(ranks, {"recent"}, chooser=lambda choices: choices[0])
    assert topic == "budget"
    assert selected["name"] == "recent"

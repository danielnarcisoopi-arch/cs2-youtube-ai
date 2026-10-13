from cs2_shorts.scripts import build_copy


def sample(**changes):
    row = {
        "name": "AK-47 | Redline (Field-Tested)",
        "price": 21.50,
        "quantity": 42,
        "volume_24h": 18,
        "avg_sale_24h": 20.75,
        "min_sale_24h": 18.50,
        "max_sale_24h": 23.00,
        "change_24h_pct": 12.4,
        "change_7d_pct": -3.2,
        "volatility_pct": 21.7,
    }
    row.update(changes)
    return row


def test_opening_hook_creates_a_question_before_naming_the_item():
    video = build_copy("gainers", [sample()], "EUR", spotlight=True)
    hook, reveal = video.narration.split("The item is ", 1)
    assert "AK-47" not in hook
    assert hook.startswith("A CS2 skin is up")
    assert reveal.startswith("AK-47")
    assert "The item is AK-47" in video.narration


def test_listing_and_sale_statistics_are_distinguished():
    video = build_copy("market_watch", [sample()], "EUR")
    assert "lowest current listing is EUR 21.50" in video.narration
    assert "reported 24-hour sale average is EUR 20.75" in video.narration
    assert "not a forecast" in video.narration


def test_missing_history_does_not_invent_a_price_change():
    video = build_copy("weekly", [sample(change_7d_pct=None)], "EUR")
    assert "NO STORED COMPARISON" not in video.narration
    assert "full week" in video.narration
    hook = video.narration.split("The item is ", 1)[0]
    assert "%" not in hook


def test_spotlight_voiceover_stays_short_and_ends_with_a_specific_prompt():
    video = build_copy("budget", [sample()], "EUR", spotlight=True)
    assert len(video.narration.split()) <= 70
    assert video.narration.endswith("Comment with your call—and why.")

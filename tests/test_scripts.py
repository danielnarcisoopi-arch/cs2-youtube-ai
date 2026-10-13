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


def test_hook_builds_curiosity_before_revealing_skin_name():
    video = build_copy("gainers", [sample()], "EUR")
    hook, reveal = video.narration.split("This is the ", 1)
    assert "AK-47" not in hook
    assert "up twelve point four percent" in hook
    assert "AK forty-seven Redline" in reveal


def test_voice_copy_is_short_conversational_and_ends_with_a_question():
    video = build_copy("budget", [sample()], "EUR")
    assert len(video.narration.split()) <= 35
    assert video.narration.endswith("Would you add it to your loadout?")
    assert "not a forecast" not in video.narration


def test_price_gap_variant_uses_actual_ask_sale_gap_and_delays_skin_name():
    video = build_copy("gainers", [sample()], "EUR", hook_variant="price_gap")
    hook, reveal = video.narration.split("It's the ", 1)
    assert "AK-47" not in hook
    assert "three point six percent" in reveal
    assert "AK forty-seven Redline" in reveal
    assert video.hook_variant == "price_gap"


def test_unknown_history_does_not_fabricate_a_market_move():
    video = build_copy("weekly", [sample(change_7d_pct=None)], "EUR")
    assert "percent this week" not in video.narration
    assert "full week" not in video.narration


def test_five_skin_showcase_keeps_skin_names_out_of_the_voiceover():
    rows = [sample(name=f"AK-47 | Skin {number} (Field-Tested)", price=number + 1.0)
            for number in range(5)]
    video = build_copy("budget", rows, "EUR")
    assert video.title.startswith("5 CS2 Skins:")
    assert len(video.items) == 5
    assert all(row["name"] not in video.narration for row in rows)
    assert "Five affordable CS2 skins" in video.narration
    assert video.narration.endswith("Tell me below.")


def test_unsupported_hook_variant_fails_clearly():
    try:
        build_copy("gainers", [sample()], "EUR", hook_variant="invented")
    except ValueError as exc:
        assert "Unsupported hook variant" in str(exc)
    else:
        raise AssertionError("An unsupported hook variant was accepted")

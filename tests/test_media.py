from PIL import Image, ImageDraw

from cs2_shorts import media
from cs2_shorts.scripts import build_copy


def test_market_shortlist_excludes_items_without_weapon_catalog_art(monkeypatch, tmp_path):
    weapon = {"name": "AK-47 | Redline (Field-Tested)"}
    music_kit = {"name": "Music Kit | Ben Bromfield, Rabbit Hole"}
    monkeypatch.setattr(media, "_skin_catalog", lambda *_args: [
        {"market_hash_name": weapon["name"], "weapon": {"name": "AK-47"},
         "pattern": {"name": "Redline"}, "category": {"name": "Rifles"}},
    ])

    filtered = media.filter_rankings_to_weapon_skins(
        {"gainers": [music_kit, weapon], "losers": []}, tmp_path,
    )

    assert filtered["gainers"] == [weapon]
    assert filtered["losers"] == []


def test_market_shortlist_excludes_gloves_from_weapon_pov(monkeypatch, tmp_path):
    weapon = {"name": "AK-47 | Redline (Field-Tested)"}
    gloves = {"name": "★ Sport Gloves | Pandora's Box (Field-Tested)"}
    monkeypatch.setattr(media, "_skin_catalog", lambda *_args: [
        {"market_hash_name": weapon["name"], "weapon": {"name": "AK-47"},
         "pattern": {"name": "Redline"}, "category": {"name": "Rifles"}},
        {"market_hash_name": gloves["name"], "weapon": {"name": "Sport Gloves"},
         "pattern": {"name": "Pandora's Box"}, "category": {"name": "Gloves"}},
    ])

    filtered = media.filter_rankings_to_weapon_skins(
        {"gainers": [gloves, weapon]}, tmp_path,
    )

    assert filtered["gainers"] == [weapon]


def test_weapon_art_stays_inside_safe_box_even_when_scale_exceeds_one(tmp_path):
    frame = Image.new("RGB", (200, 200), "black")
    art = Image.new("RGBA", (1000, 100), (0, 0, 0, 0))
    ImageDraw.Draw(art).rectangle((0, 20, 999, 80), fill=(255, 0, 0, 255))
    art_path = tmp_path / "test-cs2-long-weapon.png"
    art.save(art_path)

    media._draw_weapon(frame, art_path, (20, 20, 180, 180), scale=1.12)

    red = frame.load()
    points = [(x, y) for y in range(200) for x in range(200)
              if red[x, y][0] > 200 and red[x, y][1] < 40]
    assert points
    assert min(x for x, _ in points) >= 20
    assert max(x for x, _ in points) < 180


def test_cold_open_displays_the_featured_skin_market_hook_without_its_name():
    item = {
        "name": "AK-47 | Redline (Field-Tested)", "price": 21.50,
        "avg_sale_24h": 20.75, "change_24h_pct": 12.4,
        "change_7d_pct": -3.2, "volume_24h": 18, "volatility_pct": 21.7,
    }
    copy = build_copy("gainers", [item], "EUR", spotlight=True)
    headline, detail = media._hook_overlay(copy, "EUR")
    assert headline == "+12.4%"
    assert detail == "IN 24 HOURS"
    assert item["name"] not in f"{headline} {detail}"


def test_cold_open_price_gap_matches_the_voiceover_metric():
    item = {
        "name": "AK-47 | Redline (Field-Tested)", "price": 21.50,
        "avg_sale_24h": 20.75, "change_24h_pct": 12.4,
        "volume_24h": 18,
    }
    copy = build_copy("gainers", [item], "EUR", spotlight=True, hook_variant="price_gap")
    headline, detail = media._hook_overlay(copy, "EUR")
    assert headline == "3.6%"
    assert detail == "ASK ABOVE RECENT SALES"


def test_market_voiceover_has_a_matching_line_for_every_skin_and_promo_bookends():
    rows = [
        {"name": f"AK-47 | Skin {number} (Field-Tested)", "price": number + 1.5}
        for number in range(3)
    ]
    copy = build_copy("budget", rows, "EUR")

    lines = media._voiceover_lines(copy, "EUR")

    assert len(lines) == 5
    assert lines[0] == "Get a ten dollar free skin. Link in description."
    assert "AK forty-seven Skin 0, lowest listing" in lines[1]
    assert "€1.50" in lines[1]
    assert "AK forty-seven Skin 2, lowest listing" in lines[3]
    assert "Claim your ten dollar free skin." in lines[-1]


def test_slow_tts_is_compressed_to_fit_the_short_limit_without_losing_scene_alignment():
    durations, speed = media._scene_timing([8.0] * 7)

    assert speed > 1.0
    assert len(durations) == 7
    assert sum(durations) <= 44.01
    assert durations[0] >= 2.8
    assert durations[-1] >= 3.2


def test_normal_tts_keeps_its_natural_speed_and_promo_cards_readable():
    durations, speed = media._scene_timing([2.0, 2.4, 2.2])

    assert speed == 1.0
    assert [round(value, 2) for value in durations] == [2.8, 2.68, 6.52]

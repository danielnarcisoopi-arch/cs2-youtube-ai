from PIL import Image, ImageDraw

from cs2_shorts import media


def test_market_shortlist_excludes_items_without_weapon_catalog_art(monkeypatch, tmp_path):
    weapon = {"name": "AK-47 | Redline (Field-Tested)"}
    music_kit = {"name": "Music Kit | Ben Bromfield, Rabbit Hole"}
    monkeypatch.setattr(media, "_skin_catalog", lambda *_args: [
        {"market_hash_name": weapon["name"]},
    ])

    filtered = media.filter_rankings_to_weapon_skins(
        {"gainers": [music_kit, weapon], "losers": []}, tmp_path,
    )

    assert filtered["gainers"] == [weapon]
    assert filtered["losers"] == []


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

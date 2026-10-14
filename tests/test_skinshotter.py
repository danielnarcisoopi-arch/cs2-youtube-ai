from cs2_shorts.skinshotter import skin_page_url
from cs2_shorts.skinshotter import skin_wear_value


def test_skinport_market_name_resolves_to_skinshotter_page():
    catalog = [{
        "market_hash_name": "AK-47 | Redline (Field-Tested)",
        "weapon": {"name": "AK-47"},
        "pattern": {"name": "Redline"},
        "category": {"name": "Rifles"},
        "wear": {"name": "Field-Tested"},
        "min_float": 0.06,
        "max_float": 0.8,
    }]

    assert skin_page_url("AK-47 | Redline (Field-Tested)", catalog) == (
        "https://skinshotter.com/rifles/ak-47/redline"
    )


def test_stat_track_variant_reuses_the_canonical_skin_page():
    catalog = [{
        "market_hash_name": "AK-47 | Redline (Field-Tested)",
        "weapon": {"name": "AK-47"},
        "pattern": {"name": "Redline"},
        "category": {"name": "Rifles"},
        "wear": {"name": "Field-Tested"},
        "min_float": 0.06,
        "max_float": 0.8,
    }]

    assert skin_page_url("StatTrak™ AK-47 | Redline (Field-Tested)", catalog).endswith(
        "/rifles/ak-47/redline"
    )


def test_skinshotter_float_matches_market_exterior():
    catalog = [{
        "market_hash_name": "AK-47 | Redline (Field-Tested)",
        "weapon": {"name": "AK-47"},
        "pattern": {"name": "Redline"},
        "category": {"name": "Rifles"},
        "wear": {"name": "Field-Tested"},
        "min_float": 0.06,
        "max_float": 0.8,
    }]

    value = skin_wear_value("AK-47 | Redline (Field-Tested)", catalog)
    assert 0.15 <= value < 0.38


def test_unsupported_market_item_fails_instead_of_fabricating_route():
    try:
        skin_page_url("Music Kit | Example", [])
    except ValueError as exc:
        assert "cannot be resolved" in str(exc)
    else:
        raise AssertionError("Unsupported items must not generate invented Skinshotter URLs")

from cs2_shorts.skinshotter import _no_canvas_reason, skin_page_url, skin_wear_value, supports_weapon_pov


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


def test_glove_catalog_entries_are_not_treated_as_weapon_pov_skins():
    glove_names = (
        "★ Sport Gloves | Pandora's Box (Field-Tested)",
        "★ Driver Gloves | King Snake (Minimal Wear)",
        "★ Specialist Gloves | Crimson Kimono (Field-Tested)",
        "★ Moto Gloves | POW! (Battle-Scarred)",
        "★ Hand Wraps | Cobalt Skulls (Field-Tested)",
        "★ Bloodhound Gloves | Charred (Well-Worn)",
        "★ Hydra Gloves | Emerald (Minimal Wear)",
        "★ Broken Fang Gloves | Jade (Field-Tested)",
    )
    for name in glove_names:
        # Include weapon-like route fields deliberately: the glove name/type
        # exclusion must still win if a catalog row is inconsistent.
        assert not supports_weapon_pov({
            "market_hash_name": name,
            "weapon": {"name": "AK-47"},
            "pattern": {"name": "Test Finish"},
            "category": {"name": "Rifles"},
        }), name


def test_glove_category_is_excluded_even_when_name_is_unusual():
    assert not supports_weapon_pov({
        "market_hash_name": "★ Mystery Item | Unusual Finish",
        "weapon": {"name": "Mystery Item"},
        "pattern": {"name": "Unusual Finish"},
        "category": {"name": "Gloves"},
    })


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


def test_no_canvas_diagnostic_distinguishes_access_challenge():
    reason = _no_canvas_reason({
        "http_status": 200,
        "body_excerpt": "Please verify you are human before continuing",
    })
    assert "anti-bot/access-check" in reason


def test_no_canvas_diagnostic_surfaces_javascript_failure():
    reason = _no_canvas_reason({
        "page_errors": ["WebGPU device request failed"],
        "failed_requests": [],
    })
    assert "JavaScript failed" in reason
    assert "WebGPU device request failed" in reason

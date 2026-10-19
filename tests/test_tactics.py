import json
import io
from PIL import Image

from cs2_shorts.tactics import (
    TACTICS,
    _draw_frame,
    _record_published,
    build_tactic_copy,
    choose_tactic,
    MAP_CONTEXT,
    _load_radar,
    _load_callouts,
    _resolve_callout,
)


def test_round_iq_starts_with_twenty_distinct_curated_episodes():
    assert len(TACTICS) >= 20
    assert len({item.key for item in TACTICS}) == len(TACTICS)
    assert len({item.title for item in TACTICS}) == len(TACTICS)


def test_each_episode_has_a_short_hook_and_original_conversational_narration():
    for tactic in TACTICS:
        copy = build_tactic_copy(tactic)
        assert len(tactic.hook.split()) <= 12
        assert 35 <= len(copy.narration.split()) <= 76
        assert copy.narration.endswith(tactic.question)
        assert "real" in copy.description
        assert "not to scale" in copy.description
        assert "not captured demo data" in copy.description
        assert copy.title.startswith("CS2 Round IQ:")


def test_tactic_history_advances_and_does_not_repeat_until_the_bank_is_used(tmp_path):
    history = tmp_path / "tactics-history.json"
    seen = []
    for _ in range(len(TACTICS)):
        tactic, _episode = choose_tactic(history)
        assert tactic.key not in seen
        seen.append(tactic.key)
        _record_published(history, tactic)
    assert len(seen) == len(TACTICS)
    assert json.loads(history.read_text()) == {"published": []}
    next_tactic, _episode = choose_tactic(history)
    assert next_tactic.key == TACTICS[0].key


def test_every_tactic_uses_a_real_map_context_with_named_callouts():
    assert set(MAP_CONTEXT) == {tactic.key for tactic in TACTICS}
    assert all(map_id.startswith("de_") and map_name and source and target
               for map_id, map_name, source, target in MAP_CONTEXT.values())


def test_all_anubis_routes_use_callouts_that_exist_in_the_published_map_data():
    # This is the current upstream de_anubis.json callout set. It intentionally
    # contains no A Main or B Main entry; earlier route labels crashed on these.
    points = {
        "tspawn": (.10, .72), "canal": (.22, .60), "mid": (.38, .50),
        "palace": (.20, .35), "asite": (.48, .28), "flower": (.55, .35),
        "ctspawn": (.70, .45), "bsite": (.60, .72), "connector": (.45, .62),
        "alley": (.35, .72),
    }
    anubis_keys = ("late-round", "deny-isolation", "focus-fire", "regroup-after-pick")
    for key in anubis_keys:
        map_id, _map_name, source, target = MAP_CONTEXT[key]
        assert map_id == "de_anubis"
        assert _resolve_callout(points, source) == points[source.replace(" ", "").lower()]
        assert _resolve_callout(points, target) == points[target.replace(" ", "").lower()]


def test_map_radar_download_is_cached_and_reopened(monkeypatch, tmp_path):
    source = io.BytesIO()
    Image.new("RGBA", (32, 32), (20, 40, 60, 255)).save(source, format="PNG")
    png = source.getvalue()
    calls = []

    def fake_open(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(png)

    monkeypatch.setenv("CS2_MAP_CACHE", str(tmp_path))
    monkeypatch.setattr("cs2_shorts.tactics.urllib.request.urlopen", fake_open)
    assert _load_radar("de_mirage").size == (32, 32)
    assert _load_radar("de_mirage").size == (32, 32)
    assert len(calls) == 1


def test_callout_coordinates_are_downloaded_cached_and_normalized(monkeypatch, tmp_path):
    data = json.dumps({"callouts": [
        {"name": "Top Mid", "x": 0.42, "y": 0.51},
        {"name": "Connector", "x": 0.61, "y": 0.39},
    ]}).encode()
    calls = []

    def fake_open(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(data)

    monkeypatch.setenv("CS2_MAP_CACHE", str(tmp_path))
    monkeypatch.setattr("cs2_shorts.tactics.urllib.request.urlopen", fake_open)
    first = _load_callouts("de_mirage")
    second = _load_callouts("de_mirage")
    assert first == {"topmid": (.42, .51), "connector": (.61, .39)}
    assert second == first
    assert len(calls) == 1


def test_renderer_makes_vertical_phase_art_over_a_real_map_backdrop():
    radar = Image.new("RGBA", (512, 512), (74, 82, 71, 255))
    tactic = TACTICS[0]
    positions = {"topmid": (.45, .55), "connector": (.58, .45)}
    first = _draw_frame(tactic, 1, 0, radar, positions)
    action = _draw_frame(tactic, 1, 5, radar, positions)
    cta = _draw_frame(tactic, 1, 9, radar, positions)
    assert first.size == (1080, 1920)
    assert first.tobytes() != action.tobytes()
    assert action.tobytes() != cta.tobytes()

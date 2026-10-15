import json

from cs2_shorts.tactics import (
    TACTICS,
    _draw_frame,
    _record_published,
    build_tactic_copy,
    choose_tactic,
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
        assert "not to scale" in copy.description
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


def test_renderer_makes_vertical_phase_art_with_visual_changes():
    first = _draw_frame(TACTICS[0], 1, 0)
    action = _draw_frame(TACTICS[0], 1, 5)
    cta = _draw_frame(TACTICS[0], 1, 9)
    assert first.size == (1080, 1920)
    assert first.tobytes() != action.tobytes()
    assert action.tobytes() != cta.tobytes()

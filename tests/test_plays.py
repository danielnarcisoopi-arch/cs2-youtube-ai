from PIL import Image

from cs2_shorts.plays import (
    PLAYS,
    _draw_play_frame,
    _history,
    _record_play,
    build_play_copy,
    choose_play,
)
from cs2_shorts.tactics import _resolve_callout


def test_playbook_has_distinct_scenarios_and_explicit_simulation_disclosure():
    assert len(PLAYS) >= 5
    assert len({play.key for play in PLAYS}) == len(PLAYS)
    for play in PLAYS:
        copy = build_play_copy(play)
        assert copy.title.startswith("CS2 Playbook:")
        assert "not captured demo footage" in copy.description
        assert "illustrative" in copy.description.lower()
        assert copy.description.startswith("10$ FREE SKIN: http://clash.gg/r/CSSKINNS")


def test_play_history_rotates_independently(tmp_path):
    path = tmp_path / "plays-history.json"
    first, episode = choose_play(path)
    assert episode == 1
    _record_play(path, first)
    second, episode = choose_play(path)
    assert second.key != first.key
    assert episode == 2
    assert _history(path) == [first.key]


def test_five_v_five_play_frame_uses_real_radar_backdrop_and_moves_over_time():
    play = PLAYS[0]
    radar = Image.new("RGB", (512, 512), (82, 91, 76))
    callouts = {
        "aramp": (.72, .52), "asite": (.82, .41), "jungle": (.78, .35),
        "ticket": (.88, .38), "stairs": (.74, .34), "connector": (.64, .43),
        "topmid": (.50, .55), "palace": (.83, .48),
    }
    early = _draw_play_frame(play, 1, 8, radar, callouts)
    later = _draw_play_frame(play, 1, 60, radar, callouts)
    intro = _draw_play_frame(play, 1, 0, radar, callouts, duration=17)
    outro = _draw_play_frame(play, 1, 99, radar, callouts, duration=17)
    assert early.size == (1080, 1920)
    assert early.tobytes() != later.tobytes()
    assert intro.getpixel((540, 550)) == (5, 9, 15)
    assert outro.getpixel((540, 550)) == (5, 9, 15)
    assert later.getpixel((540, 550)) != (5, 9, 15)


def test_anubis_b_split_uses_published_callouts_instead_of_missing_b_main():
    play = next(play for play in PLAYS if play.key == "anubis-b-execute")
    callouts = {
        "tspawn": (.10, .72), "canal": (.22, .60), "mid": (.38, .50),
        "palace": (.20, .35), "asite": (.48, .28), "flower": (.55, .35),
        "ctspawn": (.70, .45), "bsite": (.60, .72), "connector": (.45, .62),
        "alley": (.35, .72),
    }
    assert play.attackers_start == "Canal"
    assert _resolve_callout(callouts, play.attackers_start) == callouts["canal"]
    assert _resolve_callout(callouts, play.bombsite) == callouts["bsite"]
    frame = _draw_play_frame(play, 1, 0, Image.new("RGB", (512, 512)), callouts)
    assert frame.size == (1080, 1920)

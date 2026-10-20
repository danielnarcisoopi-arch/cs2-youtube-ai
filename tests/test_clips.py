import random

from cs2_shorts import clips
from cs2_shorts.promotion import PROMO_URL


def test_dataset_candidate_accepts_video_and_rejects_preview_or_traversal():
    candidate = clips._candidate({
        "file": "videos/clip_123.webm", "title": "Ace", "steamid": "7656119", "fps": 120,
    })
    assert candidate is not None
    assert candidate.clip_id == "clip_123"
    assert candidate.title == "Ace"
    assert candidate.steam_id == "7656119"
    assert candidate.fps == 120
    assert clips._candidate({"file": "previews/clip_123.jpg"}) is None
    assert clips._candidate({"file": "videos/../../secret.mp4"}) is None


def test_select_dataset_clip_avoids_recently_used_paths(monkeypatch):
    monkeypatch.setattr(clips, "_dataset_split", lambda _dataset: ("metadata", "metadata", 2))
    monkeypatch.setattr(clips, "_http_json", lambda *_args, **_kwargs: {
        "rows": [
            {"row": {"file": "videos/clip_1.mp4", "title": "Old clip"}},
            {"row": {"file": "videos/clip_2.mp4", "title": "New clip"}},
        ],
    })

    selected = clips.select_dataset_clip("owner/dataset", {"videos/clip_1.mp4"}, random.Random(4))

    assert selected.path == "videos/clip_2.mp4"
    assert selected.title == "New clip"


def test_clip_copy_includes_promo_link_and_source_attribution():
    clip = clips.DatasetClip("videos/clip_9.mp4", "clip_9", "A clean 4K", "7656119", 120)

    copy = clips.build_clip_copy(clip, "owner/dataset")

    assert copy.title == "CS2 Highlight: A clean 4K"
    assert copy.description.startswith(f"10$ FREE SKIN: {PROMO_URL}")
    assert "Source clip: owner/dataset / videos/clip_9.mp4" in copy.description
    assert "7656119" in copy.description


def test_intro_and_outro_promo_cards_are_vertical_and_high_contrast():
    intro = clips._draw_promo_card("intro")
    outro = clips._draw_promo_card("outro")

    assert intro.size == (1080, 1920)
    assert outro.size == (1080, 1920)
    assert intro.getpixel((540, 800)) == (5, 9, 15)
    assert outro.getpixel((540, 800)) == (5, 9, 15)
    assert intro.tobytes() != outro.tobytes()

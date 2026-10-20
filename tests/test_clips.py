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
    monkeypatch.setattr(clips, "_dataset_split", lambda _dataset: ("metadata", "metadata"))

    def fake_http_json(_url, params, **_kwargs):
        if params["length"] == 1:
            return {"num_rows_total": 2, "rows": []}
        return {
            "num_rows_total": 2,
            "rows": [
                {"row": {"file": "videos/clip_1.mp4", "title": "Old clip"}},
                {"row": {"file": "videos/clip_2.mp4", "title": "New clip"}},
            ],
        }

    monkeypatch.setattr(clips, "_http_json", fake_http_json)

    selected = clips.select_dataset_clip("owner/dataset", {"videos/clip_1.mp4"}, random.Random(4))

    assert selected.path == "videos/clip_2.mp4"
    assert selected.title == "New clip"


def test_select_dataset_clip_falls_back_when_dataset_viewer_returns_500(monkeypatch):
    import requests

    monkeypatch.setattr(clips, "_dataset_split", lambda _dataset: ("metadata", "metadata"))

    def viewer_error(*_args, **_kwargs):
        raise requests.HTTPError("500 Server Error")

    fallback = clips.DatasetClip("videos/clip_2.webm", "clip_2", "Fallback clip", "", 120)
    monkeypatch.setattr(clips, "_http_json", viewer_error)
    monkeypatch.setattr(clips, "_load_dataset_metadata", lambda _dataset: (fallback,))

    selected = clips.select_dataset_clip("owner/dataset", set(), random.Random(4))

    assert selected == fallback


def test_source_metadata_fallback_decodes_compressed_jsonl(monkeypatch):
    dataset_id = "owner/compressed-dataset"
    payload = clips.zstandard.ZstdCompressor().compress(
        b'{"file":"videos/clip_7.webm","title":"Compressed metadata","fps":120}\n'
    )

    class FakeResponse:
        content = payload

        @staticmethod
        def raise_for_status():
            pass

    monkeypatch.delitem(clips._DATASET_METADATA_CACHE, dataset_id, raising=False)
    monkeypatch.setattr(clips.requests, "get", lambda *_args, **_kwargs: FakeResponse())

    result = clips._load_dataset_metadata(dataset_id)

    assert len(result) == 1
    assert result[0].path == "videos/clip_7.webm"
    assert result[0].title == "Compressed metadata"


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

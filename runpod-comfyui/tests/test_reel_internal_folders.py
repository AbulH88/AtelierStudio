import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webapp"))
import r2_store


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_reel_folder_list_hides_internal_media_prefixes(monkeypatch):
    monkeypatch.setattr(r2_store._SESSION, "get", lambda *args, **kwargs: _Response({
        "prefixes": ["Joy/", "gallery/", "thumbs/", "thumbs-reels/", "Sami/"]
    }))
    assert r2_store.list_folders() == ["Joy", "Sami"]


def test_all_reels_excludes_gallery_and_thumbnail_objects(monkeypatch):
    monkeypatch.setattr(r2_store._SESSION, "get", lambda *args, **kwargs: _Response({
        "objects": [
            {"key": "Joy/clip.mp4", "size": 1000000},
            {"key": "gallery/Joy/image.png", "size": 1000000},
            {"key": "thumbs/Joy/image.webp", "size": 1000},
            {"key": "thumbs-reels/Joy/clip.webp", "size": 1000},
        ]
    }))
    reels = r2_store.list_reels("")
    assert [item["key"] for item in reels] == ["Joy/clip.mp4"]

import os
import sys

import pytest

pytest.importorskip("flask")

ROOT = os.path.join(os.path.dirname(__file__), "..")
WEBAPP = os.path.join(ROOT, "webapp")
sys.path.insert(0, ROOT)
sys.path.insert(0, WEBAPP)

import app as studio  # noqa: E402


def test_gallery_list_provides_preview_urls_for_video_and_image(monkeypatch):
    monkeypatch.setattr(studio.r2_store, "list_objs", lambda _prefix: [
        {"key": "gallery/Joy/a.mp4", "name": "a.mp4", "size_mb": 1.0, "url": "/api/media?key=x"},
        {"key": "gallery/Joy/b.png", "name": "b.png", "size_mb": 1.0, "url": "/api/media?key=y"},
    ])
    with studio.app.test_client() as client:
        data = client.get("/api/gallery/list?group=Joy").get_json()
    thumbs = {item["name"]: item["thumb_url"] for item in data["images"]}
    assert thumbs["a.mp4"].endswith("thumbs%2FJoy%2Fa.webp")
    assert thumbs["b.png"].endswith("thumbs%2FJoy%2Fb.webp")


def test_missing_video_thumb_is_built_from_the_gallery_video(monkeypatch):
    class Response:
        status_code = 200
        content = b"video"

    requested = []
    saved = {}
    monkeypatch.setattr(studio.r2_store, "stream", lambda key, _range: requested.append(key) or Response())
    monkeypatch.setattr(studio.r2_store, "upload_bytes", lambda key, raw: saved.update({key: raw}))
    monkeypatch.setattr(studio, "_make_video_thumb", lambda raw: b"webp")

    assert studio._ensure_thumb("thumbs/Joy/video.webp") == b"webp"
    assert requested == ["gallery/Joy/video.png", "gallery/Joy/video.mp4"]
    assert saved == {"thumbs/Joy/video.webp": b"webp"}

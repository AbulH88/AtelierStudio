import os
import sys

import pytest

pytest.importorskip("flask")

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path[:0] = [ROOT, os.path.join(ROOT, "webapp")]
import app as studio  # noqa: E402


def test_move_gallery_media_moves_its_thumbnail(monkeypatch):
    moved = []
    monkeypatch.setattr(studio.r2_store, "move", lambda source, destination: moved.append((source, destination)))
    monkeypatch.setattr(studio.r2_store, "exists", lambda key: key == "thumbs/Joy/clip.webp")

    assert studio._move_library_media("gallery/Joy/clip.mp4", "Sami", "gallery/", "thumbs/") == "gallery/Sami/clip.mp4"
    assert moved == [
        ("gallery/Joy/clip.mp4", "gallery/Sami/clip.mp4"),
        ("thumbs/Joy/clip.webp", "thumbs/Sami/clip.webp"),
    ]


def test_move_reel_rejects_internal_source_before_moving(monkeypatch):
    monkeypatch.setattr(studio.r2_store, "move", lambda *_: pytest.fail("must not move internal media"))
    monkeypatch.setattr(studio, "load_users", lambda: {"owner": {"status": "active", "role": "admin"}})
    with studio.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "owner"
        response = client.post("/api/reels/move", json={"key": "gallery/Joy/clip.mp4", "folder": "Sami"})
    assert response.status_code == 400
    assert "Reel library" in response.get_json()["error"]


def test_folder_names_are_single_safe_segments():
    assert studio._folder_name("Summer reels 2") == "Summer reels 2"
    for invalid in ("../../private", "A/B", "", "  "):
        if invalid.strip():
            with pytest.raises(ValueError):
                studio._folder_name(invalid)
        else:
            assert studio._folder_name(invalid) == ""

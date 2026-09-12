import os
import sys

import pytest

pytest.importorskip("flask")

ROOT = os.path.join(os.path.dirname(__file__), "..")
WEBAPP = os.path.join(ROOT, "webapp")
sys.path.insert(0, ROOT)
sys.path.insert(0, WEBAPP)

import app as studio  # noqa: E402


def test_krea2_character_picker_groups_live_krea2_loras_by_folder(monkeypatch):
    monkeypatch.setattr(studio, "build_krea2_helper_loras", lambda: [
        {"path": "Keara2/Alice/Alice-final.safetensors", "label": "Alice-final"},
        {"path": "Keara2/Alice/Alice-step00000100.safetensors", "label": "Alice-step00000100"},
        {"path": "Keara2/Bella/Bella-final.safetensors", "label": "Bella-final"},
    ])

    characters = studio.build_krea2_characters()

    assert [character["label"] for character in characters] == ["Alice", "Bella"]
    assert [variant["path"] for variant in characters[0]["variants"]] == [
        "Keara2/Alice/Alice-final.safetensors",
        "Keara2/Alice/Alice-step00000100.safetensors",
    ]

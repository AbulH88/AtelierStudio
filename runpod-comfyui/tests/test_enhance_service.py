"""Local Enhance validation does not require an active GPU job."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "home_agent"))
import enhance_service


def test_capabilities_find_installed_rife_models(monkeypatch, tmp_path):
    model_dir = tmp_path / "custom_nodes" / "ComfyUI-Frame-Interpolation" / "ckpts" / "rife"
    model_dir.mkdir(parents=True)
    for name in ("rife47.pth", "rife49.pth", "unrelated.pth"):
        (model_dir / name).touch()
    monkeypatch.setattr(enhance_service, "_comfy_root", lambda: tmp_path)
    assert enhance_service._models() == ["rife47.pth", "rife49.pth"]


def test_options_reject_missing_engines_and_unknown_model():
    with pytest.raises(ValueError):
        enhance_service.validate_options({"interpolation": "off", "upscaler": "off"})
    with pytest.raises(ValueError):
        enhance_service.validate_options({"interpolation": "rife", "rife_model": "../../evil.pth"})


def test_options_accept_separate_engines():
    options = enhance_service.validate_options({"interpolation": "rife", "upscaler": "rtx_vsr",
                                                  "rife_model": "rife49.pth", "scale": 2})
    assert options["interpolation"] == "rife"
    assert options["upscaler"] == "rtx_vsr"


def test_enhancer_python_is_copied_runtime(monkeypatch, tmp_path):
    python = tmp_path / "bin" / "python-3.13.15-embed-amd64" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(enhance_service, "_enhancer_root", lambda: tmp_path)
    monkeypatch.delenv("ATELIER_ENHANCER_PYTHON", raising=False)
    assert enhance_service._runner_python() == str(python)

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


def test_dlss5_options_have_mod_style_defaults():
    options = enhance_service.validate_options({"interpolation": "off", "upscaler": "dlss"})
    assert options["nr_passes"] == 2
    assert options["nr_style"] == "Default"
    assert options["dlss_scale"] == 1.0
    assert options["local_structure_strength"] == 1.5
    assert enhance_service.validate_options({"interpolation": "off", "upscaler": "dlss", "dlss_scale": .75})["dlss_scale"] == .75


@pytest.mark.parametrize("field,value", [
    ("nr_passes", 0), ("nr_passes", 5), ("nr_style", "Invented"),
    ("nr_intensity", 2.1), ("local_tone_strength", -0.1),
    ("local_structure_strength", 2.1), ("skin_structure_strength", -1.1),
    ("nr_color_strength", 1.1), ("tone_preservation", -0.1),
    ("face_skin_protection", 1.1), ("grain_preservation", 1.1),
    ("mask_feather", 129), ("dlss_scale", 1.3), ("automatic_mask", "yes"),
])
def test_dlss5_options_reject_invalid_values(field, value):
    with pytest.raises(ValueError):
        enhance_service.validate_options({"interpolation": "off", "upscaler": "dlss", field: value})


@pytest.mark.parametrize("name,kind", [
    ("portrait.png", "image"), ("portrait.JPEG", "image"),
    ("clip.mp4", "video"), ("clip.MKV", "video"),
])
def test_media_kind(name, kind):
    assert enhance_service.media_kind(name) == kind


def test_image_rejects_interpolation_and_non_dlss_engine():
    rife = enhance_service.validate_options({"interpolation": "rife", "upscaler": "dlss"})
    with pytest.raises(ValueError, match="only for videos"):
        enhance_service.validate_media_options("image", rife)
    vsr = enhance_service.validate_options({"interpolation": "off", "upscaler": "rtx_vsr"})
    with pytest.raises(ValueError, match="require DLSS5"):
        enhance_service.validate_media_options("image", vsr)


def test_enhancer_python_is_copied_runtime(monkeypatch, tmp_path):
    python = tmp_path / "bin" / "python-3.13.15-embed-amd64" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(enhance_service, "_enhancer_root", lambda: tmp_path)
    monkeypatch.delenv("ATELIER_ENHANCER_PYTHON", raising=False)
    assert enhance_service._runner_python() == str(python)

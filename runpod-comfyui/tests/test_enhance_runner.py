import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "home_agent"))
import enhance_runner


def args(**changes):
    values = dict(
        nr_style="Default", nr_intensity=1.0, nr_passes=2,
        local_tone_strength=1.0, local_structure_strength=1.5,
        skin_structure_strength=-1.0, nr_color_strength=1.0,
        tone_preservation=0.0, face_skin_protection=0.0,
        grain_preservation=0.0, mask_feather=0, automatic_mask=0,
        dlss_scale=1.0,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def result(passes=2, evaluations=4, **changes):
    values = dict(
        bridge_status={"nr_passes": passes, "feature_evaluations": evaluations},
        nr_count_evidence=1, output_path="output.mp4",
    )
    values.update(changes)
    return SimpleNamespace(**values)


def test_feature_evidence_requires_requested_multipass():
    enhance_runner._require_feature_evidence(result(), 2)
    with pytest.raises(RuntimeError, match="multipass evidence"):
        enhance_runner._require_feature_evidence(result(passes=1), 2)
    with pytest.raises(RuntimeError, match="frame evidence"):
        enhance_runner._require_feature_evidence(result(nr_count_evidence=0), 2)


def _install_fake_modules(monkeypatch, names):
    for name, module in names.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_video_adapter_passes_all_neural_options_once(monkeypatch, tmp_path):
    captured = {}

    class Options:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    converted = result(output_path=str(tmp_path / "done.mp4"))
    batch_result = SimpleNamespace(
        successes=[SimpleNamespace(result=converted)], failures=[]
    )
    batch = ModuleType("src.neural_rendering.video.batch")
    batch.convert_videos = lambda paths, options, **kwargs: batch_result
    models = ModuleType("src.neural_rendering.video.models")
    models.ConversionOptions = Options
    _install_fake_modules(monkeypatch, {
        "src.neural_rendering.video.batch": batch,
        "src.neural_rendering.video.models": models,
    })
    monkeypatch.setattr(enhance_runner, "enhancer_root", lambda: tmp_path)

    output = enhance_runner.run_dlss_video(tmp_path / "source.mp4", tmp_path, args())

    assert output == tmp_path / "done.mp4"
    assert captured["nr_passes"] == 2
    assert captured["local_structure_strength"] == 1.5
    assert captured["upscaling_factor"] == 1.0


def test_image_adapter_uses_native_multipass_and_png(monkeypatch, tmp_path):
    captured = {}

    class Options:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    converted = result(output_path=str(tmp_path / "done.png"))
    del converted.nr_count_evidence
    batch_result = SimpleNamespace(successes=[converted], failures=[])
    batch = ModuleType("src.neural_rendering.image.batch")
    batch.convert_images = lambda paths, options, **kwargs: batch_result
    models = ModuleType("src.neural_rendering.image.models")
    models.ImageConversionOptions = Options
    _install_fake_modules(monkeypatch, {
        "src.neural_rendering.image.batch": batch,
        "src.neural_rendering.image.models": models,
    })
    monkeypatch.setattr(enhance_runner, "enhancer_root", lambda: tmp_path)

    output = enhance_runner.run_dlss_image(tmp_path / "source.webp", tmp_path, args())

    assert output == tmp_path / "done.png"
    assert captured["nr_passes"] == 2
    assert captured["output_format"] == "PNG"
    assert captured["preserve_metadata"] is True

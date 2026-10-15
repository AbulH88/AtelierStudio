import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comfy_common as cc


def _graph():
    path = Path(__file__).resolve().parents[1] / "workflow_ltx25i2v.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_ltx_submission_preserves_source_defaults_and_fixed_refinement_seed():
    graph = cc._build_ltx25i2v(_graph(), {"prompt": "A slow camera move"},
                               seed=123456, image_name="uploaded.png")
    assert graph["61"]["inputs"]["image"] == "uploaded.png"
    assert graph["48"]["inputs"]["image"] == ["61", 0]
    assert graph["49"]["inputs"]["image"] == ["61", 0]
    assert graph["5"]["inputs"]["value"] == 2720
    assert graph["6"]["inputs"]["value"] == 1536
    assert graph["4"]["inputs"]["value"] == 10
    assert graph["7"]["inputs"]["value"] == 24
    assert graph["44"]["inputs"]["noise_seed"] == 123456
    assert graph["41"]["inputs"]["noise_seed"] == 23
    assert graph["8"]["inputs"]["value"] == "A slow camera move"
    assert graph["48"]["inputs"]["strength"] == 0.7
    assert graph["49"]["inputs"]["strength"] == 1
    assert graph["18"]["inputs"]["sampler_name"] == "euler_ancestral"
    assert graph["23"]["inputs"]["sampler_name"] == "euler_ancestral"


def test_ltx_explicit_form_inputs_only_change_the_requested_values():
    original = _graph()
    graph = cc._build_ltx25i2v(_graph(), {
        "prompt": "Flowers move gently", "duration": 5,
        "width": 1536, "height": 2720,
    }, seed=42, image_name="portrait.png")
    assert graph["5"]["inputs"]["value"] == 1536
    assert graph["6"]["inputs"]["value"] == 2720
    assert graph["4"]["inputs"]["value"] == 5
    assert graph["44"]["inputs"]["noise_seed"] == 42
    dynamic = {"61", "8", "4", "5", "6", "44"}
    assert {k: v for k, v in graph.items() if k not in dynamic} == {
        k: v for k, v in original.items() if k not in dynamic
    }

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_build_krea2_sets_image_prompt_seed_lora_resize():
    graph = _load_graph()
    inp = {"prompt": "a woman in a red dress", "trigger": "ing2lorance",
           "character_lora_path": "Keara2/CristinaCosplay/CosplayGirl_000000600.safetensors",
           "character_strength": 0.9, "resize_size": 1536}
    out = cc._build_krea2(graph, inp, seed=12345, frame_name="frame_abc.png")
    assert out["316"]["inputs"]["image"] == "frame_abc.png"
    assert out["314"]["inputs"]["text"] == "ing2lorance, a woman in a red dress"
    assert out["302"]["inputs"]["seed"] == 12345
    assert out["313"]["inputs"]["lora_name"] == inp["character_lora_path"]
    assert out["313"]["inputs"]["strength_model"] == 0.9
    assert out["324"]["inputs"]["Number"] == "1536"


def test_build_krea2_resize_defaults_to_1920():
    graph = _load_graph()
    out = cc._build_krea2(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    assert out["324"]["inputs"]["Number"] == "1920"


def test_build_krea2_denoise_defaults_match_baked_workflow_values():
    graph = _load_graph()
    out = cc._build_krea2(graph, {"prompt": "x", "refine": True}, seed=1, frame_name="f.png")
    assert out["302"]["inputs"]["denoise"] == 0.71
    assert out["335"]["inputs"]["denoise"] == 0.1


def test_build_krea2_denoise_overrides_are_applied():
    graph = _load_graph()
    inp = {"prompt": "x", "refine": True, "denoise": 0.5, "refine_denoise": 0.2}
    out = cc._build_krea2(graph, inp, seed=1, frame_name="f.png")
    assert out["302"]["inputs"]["denoise"] == 0.5
    assert out["335"]["inputs"]["denoise"] == 0.2


def test_build_krea2_refine_off_drops_refine_subgraph_and_saves_base_only():
    graph = _load_graph()
    out = cc._build_krea2(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    for nid in ("334", "335", "336", "339", "345"):
        assert nid not in out
    assert out["346"]["inputs"]["images"] == ["303", 0]


def test_build_krea2_refine_on_keeps_refine_subgraph_and_saves_both():
    graph = _load_graph()
    out = cc._build_krea2(graph, {"prompt": "x", "refine": True}, seed=7, frame_name="f.png")
    for nid in ("334", "335", "336", "339", "345", "346"):
        assert nid in out
    assert out["345"]["inputs"]["images"] == ["336", 0]
    assert out["346"]["inputs"]["images"] == ["303", 0]
    assert out["335"]["inputs"]["seed"] == 7


def test_build_krea2_applies_sampler_override_to_both_stages():
    graph = _load_graph()
    inp = {"prompt": "x", "refine": True,
           "sampler_override": {"cfg": 4, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._build_krea2(graph, inp, seed=1, frame_name="f.png")
    assert out["302"]["inputs"]["cfg"] == 4
    assert out["302"]["inputs"]["sampler_name"] == "euler"
    assert out["335"]["inputs"]["scheduler"] == "karras"

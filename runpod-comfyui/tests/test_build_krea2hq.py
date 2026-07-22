import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2hq.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_build_krea2hq_sets_image_prompt_seed_lora_size():
    graph = _load_graph()
    inp = {"prompt": "a woman in a red dress", "trigger": "ing2lorance",
           "character_lora_path": "Keara2/krea2_cristiana/Cristina-2600.safetensors",
           "character_strength": 0.9, "width": 1024, "height": 1536}
    out = cc._build_krea2hq(graph, inp, seed=12345, frame_name="frame_abc.png")
    assert out["16"]["inputs"]["image"] == "frame_abc.png"
    assert out["5"]["inputs"]["text"] == "ing2lorance, a woman in a red dress"
    assert out["2"]["inputs"]["seed"] == 12345
    assert out["14"]["inputs"]["seed"] == 12345
    assert out["11"]["inputs"]["lora_1"]["on"] is True
    assert out["11"]["inputs"]["lora_1"]["lora"] == inp["character_lora_path"]
    assert out["11"]["inputs"]["lora_1"]["strength"] == 0.9
    assert out["13"]["inputs"]["width"] == 1024
    assert out["13"]["inputs"]["height"] == 1536


def test_build_krea2hq_size_defaults_to_1080x1920():
    graph = _load_graph()
    out = cc._build_krea2hq(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    assert out["13"]["inputs"]["width"] == 1080
    assert out["13"]["inputs"]["height"] == 1920


def test_build_krea2hq_applies_sampler_override_to_both_stages():
    graph = _load_graph()
    inp = {"prompt": "x", "sampler_override": {"cfg": 4, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._build_krea2hq(graph, inp, seed=1, frame_name="f.png")
    for nid in ("1", "4"):
        assert out[nid]["inputs"]["cfg"] == 4
        assert out[nid]["inputs"]["sampler_name"] == "euler"
        assert out[nid]["inputs"]["scheduler"] == "karras"


def test_build_krea2hq_no_character_turns_off_slot():
    graph = _load_graph()
    out = cc._build_krea2hq(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    assert out["11"]["inputs"]["lora_1"]["on"] is False


def test_build_krea2hq_leaves_helper_lora_slots_untouched():
    graph = _load_graph()
    out = cc._build_krea2hq(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    assert out["11"]["inputs"]["lora_2"]["on"] is True
    assert out["11"]["inputs"]["lora_3"]["on"] is True

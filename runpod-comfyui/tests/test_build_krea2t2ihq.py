import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2t2ihq.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_build_krea2t2ihq_sets_prompt_seed_lora_size():
    graph = _load_graph()
    inp = {"prompt": "a woman in a red dress", "trigger": "ing2lorance",
           "character_lora_path": "Keara2/krea2_cristiana/Cristina-2600.safetensors",
           "character_strength": 0.9, "width": 1024, "height": 1536}
    out = cc._build_krea2t2ihq(graph, inp, seed=12345)
    assert out["439"]["inputs"]["text"] == "ing2lorance, a woman in a red dress"
    assert out["433"]["inputs"]["seed"] == 12345
    assert out["458"]["inputs"]["width"] == 1024
    assert out["458"]["inputs"]["height"] == 1536
    assert out["449"]["inputs"]["lora_1"]["on"] is True
    assert out["449"]["inputs"]["lora_1"]["lora"] == inp["character_lora_path"]
    assert out["449"]["inputs"]["lora_1"]["strength"] == 0.9


def test_build_krea2t2ihq_size_defaults_to_1080x1920():
    graph = _load_graph()
    out = cc._build_krea2t2ihq(graph, {"prompt": "x"}, seed=1)
    assert out["458"]["inputs"]["width"] == 1080
    assert out["458"]["inputs"]["height"] == 1920


def test_build_krea2t2ihq_batch_size_from_variations():
    graph = _load_graph()
    out = cc._build_krea2t2ihq(graph, {"prompt": "x", "variations": 4}, seed=1)
    assert out["458"]["inputs"]["batch_size"] == 4


def test_build_krea2t2ihq_applies_sampler_override_to_both_stages():
    graph = _load_graph()
    inp = {"prompt": "x", "sampler_override": {"cfg": 4, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._build_krea2t2ihq(graph, inp, seed=1)
    for nid in ("426", "427"):
        assert out[nid]["inputs"]["cfg"] == 4
        assert out[nid]["inputs"]["sampler_name"] == "euler"
        assert out[nid]["inputs"]["scheduler"] == "karras"


def test_build_krea2t2ihq_no_character_turns_off_slot():
    graph = _load_graph()
    out = cc._build_krea2t2ihq(graph, {"prompt": "x"}, seed=1)
    assert out["449"]["inputs"]["lora_1"]["on"] is False


def test_build_krea2t2ihq_leaves_helper_lora_slots_untouched_when_no_list_sent():
    graph = _load_graph()
    out = cc._build_krea2t2ihq(graph, {"prompt": "x"}, seed=1)
    assert out["449"]["inputs"]["lora_2"]["on"] is True
    assert out["449"]["inputs"]["lora_3"]["on"] is True


def test_build_krea2t2ihq_applies_explicit_helper_list():
    graph = _load_graph()
    inp = {"prompt": "x", "helper_loras": [
        {"path": "Keara2/mix/RealisomHelper/RealisticSnapshotKrea2.safetensors", "strength": 0.5}]}
    out = cc._build_krea2t2ihq(graph, inp, seed=1)
    assert out["449"]["inputs"]["lora_2"]["on"] is True
    assert out["449"]["inputs"]["lora_2"]["lora"] == inp["helper_loras"][0]["path"]
    assert out["449"]["inputs"]["lora_2"]["strength"] == 0.5
    assert out["449"]["inputs"]["lora_3"]["on"] is False

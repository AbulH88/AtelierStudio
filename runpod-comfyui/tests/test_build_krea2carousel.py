import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2carousel.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_build_krea2carousel_sets_prompt_seed_lora_size():
    graph = _load_graph()
    inp = {"prompt": "a woman in a red dress", "trigger": "ing2lorance",
           "character_lora_path": "Keara2/krea2_cristiana/Cristina-2700.safetensors",
           "character_strength": 0.9, "width": 1024, "height": 1536}
    out = cc._build_krea2carousel(graph, inp, seed=12345)
    assert out["6"]["inputs"]["text"] == "ing2lorance, a woman in a red dress"
    assert out["98"]["inputs"]["seed"] == 12345
    assert out["10"]["inputs"]["width"] == 1024
    assert out["10"]["inputs"]["height"] == 1536
    assert out["28"]["inputs"]["lora_1"]["on"] is True
    assert out["28"]["inputs"]["lora_1"]["lora"] == inp["character_lora_path"]
    assert out["28"]["inputs"]["lora_1"]["strength"] == 0.9


def test_build_krea2carousel_seeds_the_grain_node_too():
    """Renoise shares the run seed so a re-roll changes the grain, not just the frames."""
    graph = _load_graph()
    out = cc._build_krea2carousel(graph, {"prompt": "x"}, seed=777)
    assert out["110"]["inputs"]["seed"] == 777


def test_build_krea2carousel_size_defaults_to_1080x1920():
    graph = _load_graph()
    out = cc._build_krea2carousel(graph, {"prompt": "x"}, seed=1)
    assert out["10"]["inputs"]["width"] == 1080
    assert out["10"]["inputs"]["height"] == 1920


def test_build_krea2carousel_batch_size_is_the_slide_count():
    graph = _load_graph()
    out = cc._build_krea2carousel(graph, {"prompt": "x", "variations": 6}, seed=1)
    assert out["10"]["inputs"]["batch_size"] == 6


def test_build_krea2carousel_batch_size_floors_at_one():
    graph = _load_graph()
    out = cc._build_krea2carousel(graph, {"prompt": "x", "variations": 0}, seed=1)
    assert out["10"]["inputs"]["batch_size"] == 1


def test_build_krea2carousel_keeps_the_turbo_schedule():
    """8 steps @ cfg 1 is what the turbo fp8 checkpoint needs — not user-tunable,
    and _build must not let a stray `steps` in the input override it."""
    graph = _load_graph()
    out = cc._build_krea2carousel(graph, {"prompt": "x", "steps": 30, "denoise": 0.5}, seed=1)
    assert out["98"]["inputs"]["steps"] == 8
    assert out["98"]["inputs"]["cfg"] == 1
    assert out["98"]["inputs"]["denoise"] == 1


def test_build_krea2carousel_applies_sampler_override():
    graph = _load_graph()
    inp = {"prompt": "x", "sampler_override": {"cfg": 4, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._build_krea2carousel(graph, inp, seed=1)
    assert out["98"]["inputs"]["cfg"] == 4
    assert out["98"]["inputs"]["sampler_name"] == "euler"
    assert out["98"]["inputs"]["scheduler"] == "karras"


def test_build_krea2carousel_no_character_turns_off_slot():
    graph = _load_graph()
    out = cc._build_krea2carousel(graph, {"prompt": "x"}, seed=1)
    assert out["28"]["inputs"]["lora_1"]["on"] is False


def test_build_krea2carousel_leaves_helper_slots_untouched_when_no_list_sent():
    graph = _load_graph()
    out = cc._build_krea2carousel(graph, {"prompt": "x"}, seed=1)
    for slot in ("lora_2", "lora_3", "lora_4"):
        assert out["28"]["inputs"][slot]["on"] is True


def test_build_krea2carousel_applies_explicit_helper_list():
    """An explicit list refills slots 2..N and switches off every baked-in helper
    the user unchecked — here slots 3 and 4."""
    graph = _load_graph()
    inp = {"prompt": "x", "helper_loras": [
        {"path": "Keara2/mix/skindetails_krea2_loraholic.safetensors", "strength": 0.4}]}
    out = cc._build_krea2carousel(graph, inp, seed=1)
    assert out["28"]["inputs"]["lora_2"]["on"] is True
    assert out["28"]["inputs"]["lora_2"]["lora"] == inp["helper_loras"][0]["path"]
    assert out["28"]["inputs"]["lora_2"]["strength"] == 0.4
    assert out["28"]["inputs"]["lora_3"]["on"] is False
    assert out["28"]["inputs"]["lora_4"]["on"] is False


def test_build_krea2carousel_empty_trigger_leaves_prompt_bare():
    graph = _load_graph()
    out = cc._build_krea2carousel(graph, {"prompt": "just this", "trigger": ""}, seed=1)
    assert out["6"]["inputs"]["text"] == "just this"

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2new.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_build_krea2new_sets_image_prompt_seed_lora_size():
    graph = _load_graph()
    inp = {"prompt": "a woman in a red dress", "trigger": "ing2lorance",
           "character_lora_path": "Keara2/krea2_cristiana/Cristina-2600.safetensors",
           "character_strength": 0.9, "width": 1024, "height": 1536}
    out = cc._build_krea2new(graph, inp, seed=12345, frame_name="frame_abc.png")
    assert out["32"]["inputs"]["image"] == "frame_abc.png"
    assert out["6"]["inputs"]["text"] == "ing2lorance, a woman in a red dress"
    assert out["2"]["inputs"]["seed"] == 12345
    assert out["38"]["inputs"]["lora_name"] == inp["character_lora_path"]
    assert out["38"]["inputs"]["strength_model"] == 0.9
    assert out["10"]["inputs"]["width"] == 1024
    assert out["10"]["inputs"]["height"] == 1536


def test_build_krea2new_size_defaults_to_1080x1920():
    graph = _load_graph()
    out = cc._build_krea2new(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    assert out["10"]["inputs"]["width"] == 1080
    assert out["10"]["inputs"]["height"] == 1920


def test_build_krea2new_applies_sampler_override():
    graph = _load_graph()
    inp = {"prompt": "x", "sampler_override": {"cfg": 4, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._build_krea2new(graph, inp, seed=1, frame_name="f.png")
    assert out["2"]["inputs"]["cfg"] == 4
    assert out["2"]["inputs"]["sampler_name"] == "euler"
    assert out["2"]["inputs"]["scheduler"] == "karras"


def test_build_krea2new_no_character_zeroes_strength():
    graph = _load_graph()
    out = cc._build_krea2new(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    assert out["38"]["inputs"]["strength_model"] == 0.0

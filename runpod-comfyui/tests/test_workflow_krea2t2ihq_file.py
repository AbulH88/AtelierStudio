import json
import os

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2t2ihq.json")


def _load():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_no_leaked_api_key():
    with open(WF_PATH, encoding="utf-8") as f:
        raw = f.read()
    assert "sk-or-v1" not in raw
    assert "api_key" not in raw


def test_remaining_nodes_present():
    graph = _load()
    expected = {"426", "427", "428", "429", "430", "431", "433", "439", "449", "450", "458", "460"}
    assert set(graph.keys()) == expected


def test_no_load_image_node_pure_t2i():
    graph = _load()
    assert all(n["class_type"] != "LoadImage" for n in graph.values())


def test_latent_is_plain_empty_latent_image_not_preset_node():
    graph = _load()
    assert graph["458"]["class_type"] == "EmptyLatentImage"
    assert isinstance(graph["458"]["inputs"]["width"], int)
    assert isinstance(graph["458"]["inputs"]["height"], int)


def test_positive_prompt_has_no_dangling_link():
    graph = _load()
    assert isinstance(graph["439"]["inputs"]["text"], str)


def test_save_node_is_plain_save_image():
    graph = _load()
    assert graph["460"]["class_type"] == "SaveImage"
    assert graph["460"]["inputs"]["images"] == ["450", 0]


def test_two_stage_sampler_chain_wired_through_character_lora():
    graph = _load()
    assert graph["426"]["inputs"]["latent_image"] == ["458", 0]
    assert graph["427"]["inputs"]["latent_image"] == ["426", 1]
    assert graph["427"]["inputs"]["model"] == ["449", 0]
    assert graph["426"]["inputs"]["model"] == ["449", 0]
    assert graph["450"]["inputs"]["samples"] == ["427", 1]

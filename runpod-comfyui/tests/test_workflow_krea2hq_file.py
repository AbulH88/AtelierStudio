import json
import os

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2hq.json")


def _load():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_no_leaked_api_key_or_openrouter_node():
    with open(WF_PATH, encoding="utf-8") as f:
        raw = f.read()
    assert "sk-or-v1" not in raw
    assert "api_key" not in raw


def test_video_captioner_and_resolution_nodes_removed():
    graph = _load()
    for nid in ("7", "19", "23", "25"):
        assert nid not in graph, f"node {nid} should have been stripped"


def test_remaining_nodes_present():
    graph = _load()
    expected = {"1", "2", "3", "4", "5", "6", "8", "9", "10", "11", "12", "13", "14", "16", "24"}
    assert set(graph.keys()) == expected


def test_resize_size_is_literal_not_linked_to_removed_preset_node():
    graph = _load()
    assert isinstance(graph["13"]["inputs"]["width"], int)
    assert isinstance(graph["13"]["inputs"]["height"], int)


def test_load_image_is_plain_load_image():
    graph = _load()
    assert graph["16"]["class_type"] == "LoadImage"


def test_positive_prompt_has_no_dangling_link():
    graph = _load()
    assert isinstance(graph["5"]["inputs"]["text"], str)


def test_save_node_is_plain_save_image():
    graph = _load()
    assert graph["12"]["class_type"] == "SaveImage"
    assert graph["12"]["inputs"]["images"] == ["6", 0]


def test_two_stage_sampler_chain_wired_through_character_lora():
    graph = _load()
    # base pass (4) encodes the resized/noise-augmented source; refine pass (1)
    # continues from base's latent. Both pull the model from the LoRA stack (11).
    assert graph["4"]["inputs"]["latent_image"] == ["24", 0]
    assert graph["1"]["inputs"]["latent_image"] == ["4", 1]
    assert graph["1"]["inputs"]["model"] == ["11", 0]
    assert graph["4"]["inputs"]["model"] == ["11", 0]
    assert graph["6"]["inputs"]["samples"] == ["1", 1]

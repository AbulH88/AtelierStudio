import json
import os

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2new.json")


def _load():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_no_leaked_api_key_or_openrouter_node():
    with open(WF_PATH, encoding="utf-8") as f:
        raw = f.read()
    assert "sk-or-v1" not in raw
    assert "api_key" not in raw


def test_resolution_and_caption_nodes_removed():
    graph = _load()
    for nid in ("30", "36", "39", "40"):
        assert nid not in graph, f"node {nid} should have been stripped"


def test_remaining_nodes_present():
    graph = _load()
    expected = {"2", "3", "4", "6", "8", "10", "15", "18",
                "31", "32", "33", "34", "35", "37", "38"}
    assert set(graph.keys()) == expected


def test_latent_size_is_literal_not_linked_to_removed_resolution_node():
    graph = _load()
    assert isinstance(graph["10"]["inputs"]["width"], int)
    assert isinstance(graph["10"]["inputs"]["height"], int)


def test_positive_prompt_has_no_dangling_link():
    graph = _load()
    assert isinstance(graph["6"]["inputs"]["text"], str)


def test_save_node_is_plain_save_image():
    graph = _load()
    assert graph["37"]["class_type"] == "SaveImage"


def test_control_chain_wired_through_character_lora():
    graph = _load()
    # depth-control LoRA stacks on top of the character LoRA, which stacks on the base UNET
    assert graph["38"]["inputs"]["model"] == ["15", 0]
    assert graph["33"]["inputs"]["model"] == ["38", 0]
    assert graph["35"]["inputs"]["control_latent"] == ["34", 0]
    assert graph["2"]["inputs"]["model"] == ["35", 0]

import json
import os

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2.json")


def _load():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_no_leaked_api_key_or_openrouter_node():
    with open(WF_PATH, encoding="utf-8") as f:
        raw = f.read()
    assert "sk-or-v1" not in raw
    assert "api_key" not in raw


def test_video_switch_and_debug_nodes_removed():
    graph = _load()
    for nid in ("321", "327", "328", "329", "330", "333", "337", "338"):
        assert nid not in graph, f"node {nid} should have been stripped"


def test_remaining_nodes_present():
    graph = _load()
    expected = {"302", "303", "304", "305", "310", "311", "312", "313",
                "314", "316", "317", "322", "323", "324", "334", "335",
                "336", "339"}
    assert set(graph.keys()) == expected


def test_resize_reads_directly_from_load_image():
    graph = _load()
    assert graph["322"]["inputs"]["image"] == ["316", 0]


def test_positive_prompt_has_no_dangling_link():
    graph = _load()
    # 314.text must be a literal (app sets it at runtime), not a link to the
    # removed ShowText/OpenRouterVLM nodes (321/330).
    assert isinstance(graph["314"]["inputs"]["text"], str)


def test_save_image_defaults_to_base_output():
    graph = _load()
    assert graph["304"]["inputs"]["images"] == ["303", 0]

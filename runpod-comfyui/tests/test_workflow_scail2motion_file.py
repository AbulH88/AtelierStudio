import json
import os

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_scail2motion.json")


def _load():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_no_leaked_api_key():
    with open(WF_PATH, encoding="utf-8") as f:
        raw = f.read()
    assert "sk-or-v1" not in raw
    assert "api_key" not in raw.lower()


def test_remaining_nodes_present():
    graph = _load()
    expected = {"6", "7", "37", "38", "39", "48", "56", "57", "58", "96", "102", "103",
                "104", "107", "109", "110", "112", "113", "115", "116", "127", "128",
                "130", "132", "133", "155", "157", "163",
                "172:160", "172:161", "172:162", "172:164", "172:165", "172:166"}
    assert set(graph.keys()) == expected


def test_debug_nodes_dropped():
    """117 (PreviewImage) and 134 (a save_output:false VHS_VideoCombine) are pure
    UI/debug nodes with no headless purpose — neither may come back."""
    graph = _load()
    assert "117" not in graph
    assert "134" not in graph


def test_two_video_combine_outputs_only():
    graph = _load()
    combiners = [nid for nid, n in graph.items() if n["class_type"] == "VHS_VideoCombine"]
    assert sorted(combiners) == ["133", "163"]
    assert all(graph[nid]["inputs"]["save_output"] for nid in combiners)


def test_raw_output_reads_the_sampler_directly():
    graph = _load()
    assert graph["163"]["inputs"]["images"] == ["132", 0]
    assert graph["163"]["inputs"]["audio"] == ["113", 2]


def test_final_output_chain_runs_through_color_match_rtx_and_rife():
    graph = _load()
    assert graph["172:161"]["inputs"]["anything"] == ["132", 0]
    assert graph["172:162"]["inputs"]["anything"] == ["172:161", 0]
    assert graph["172:160"]["inputs"]["image_target"] == ["172:162", 0]
    assert graph["172:160"]["inputs"]["image_ref"] == ["58", 0]     # color-matched to the ref photo
    assert graph["172:164"]["inputs"]["images"] == ["172:160", 0]
    assert graph["172:165"]["inputs"]["frames"] == ["172:164", 0]
    assert graph["133"]["inputs"]["images"] == ["172:165", 0]
    assert graph["133"]["inputs"]["frame_rate"] == ["172:166", 1]


def test_reference_photo_sizing_drives_the_driving_video_resize():
    """No separate resolution picker: the ref photo's resize (102/103) sizes both
    the video load (113) and the sampler (132) via GetImageSize (104)."""
    graph = _load()
    assert graph["102"]["inputs"]["input"] == ["58", 0]
    assert graph["103"]["inputs"]["input"] == ["102", 0]
    assert graph["104"]["inputs"]["image"] == ["103", 0]
    assert graph["113"]["inputs"]["custom_width"] == ["104", 0]
    assert graph["113"]["inputs"]["custom_height"] == ["104", 1]
    assert graph["132"]["inputs"]["width"] == ["104", 0]
    assert graph["132"]["inputs"]["height"] == ["104", 1]


def test_locked_lora_chain_feeds_the_sampler():
    graph = _load()
    assert graph["96"]["inputs"]["model"] == ["37", 0]
    assert graph["130"]["inputs"]["model"] == ["96", 0]
    assert graph["128"]["inputs"]["model"] == ["130", 0]
    assert graph["127"]["inputs"]["model"] == ["128", 0]
    assert graph["48"]["inputs"]["model"] == ["127", 0]
    assert graph["132"]["inputs"]["model"] == ["48", 0]


def test_every_link_points_at_a_node_that_exists():
    graph = _load()
    for nid, node in graph.items():
        for k, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                assert v[0] in graph, f"{nid}.{k} -> missing node {v[0]}"

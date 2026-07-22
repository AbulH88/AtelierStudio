import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_video.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_workflow_has_no_leaked_keys():
    with open(WF_PATH, encoding="utf-8") as f:
        raw = f.read()
    assert "sk-or-v1" not in raw
    assert "api_key" not in raw.lower()


def test_dev_preview_node_stripped():
    graph = _load_graph()
    assert "358" not in graph   # dev-only PreviewImage removed


def test_build_video_wires_core_inputs():
    graph = _load_graph()
    inp = {"prompt": "dancing in a field", "trigger": "ing2lorance", "fps": 24, "frame_cap": 60}
    out = cc._build_video(graph, inp, seed=999, video_name="drv.mp4", ref_name="ref.png")
    assert out["275"]["inputs"]["video"] == "drv.mp4"
    assert out["275"]["inputs"]["frame_load_cap"] == 60
    assert out["264"]["inputs"]["value"] == 24        # force_rate int node
    assert out["299"]["inputs"]["image"] == "ref.png"
    assert out["356"]["inputs"]["text"] == "ing2lorance, dancing in a field"
    assert out["222"]["inputs"]["seed"] == 999


def test_build_video_no_character_lora_by_default():
    graph = _load_graph()
    out = cc._build_video(graph, {"prompt": "x"}, seed=1, video_name="v.mp4", ref_name="r.png")
    assert "char_lora" not in out
    assert "prev_lora" not in out["276"]["inputs"]   # multi-stack left unchained


def test_build_video_optional_character_lora_chains_into_multistack():
    graph = _load_graph()
    inp = {"prompt": "x", "character_lora_path": "wan/Own/Alice/Alice.safetensors",
           "character_strength": 0.9}
    out = cc._build_video(graph, inp, seed=1, video_name="v.mp4", ref_name="r.png")
    assert out["char_lora"]["class_type"] == "WanVideoLoraSelect"
    assert out["char_lora"]["inputs"]["lora"] == inp["character_lora_path"]
    assert out["char_lora"]["inputs"]["strength"] == 0.9
    assert out["276"]["inputs"]["prev_lora"] == ["char_lora", 0]


def test_build_video_upscale_off_drops_tail_keeps_raw():
    graph = _load_graph()
    out = cc._build_video(graph, {"prompt": "x"}, seed=1, video_name="v.mp4", ref_name="r.png")
    for nid in cc.VIDEO_UPSCALE_CHAIN:
        assert nid not in out, f"node {nid} should be dropped when upscale is off"
    assert "285" in out   # raw h264 output stays
    # no surviving node should still reference a dropped upscale node
    dropped = set(cc.VIDEO_UPSCALE_CHAIN)
    for node in out.values():
        for v in (node.get("inputs") or {}).values():
            if isinstance(v, list) and len(v) == 2:
                assert str(v[0]) not in dropped


def test_build_video_upscale_on_keeps_both_outputs():
    graph = _load_graph()
    out = cc._build_video(graph, {"prompt": "x", "upscale": True}, seed=1,
                          video_name="v.mp4", ref_name="r.png")
    assert "285" in out            # raw
    assert "369" in out            # upscaled + RIFE final
    assert "368" in out            # RTX super-res survives


def test_build_video_applies_sampler_override():
    graph = _load_graph()
    inp = {"prompt": "x", "sampler_override": {"cfg": 2, "scheduler": "unipc"}}
    out = cc._build_video(graph, inp, seed=1, video_name="v.mp4", ref_name="r.png")
    assert out["222"]["inputs"]["cfg"] == 2
    assert out["222"]["inputs"]["scheduler"] == "unipc"

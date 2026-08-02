import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_scail2motion.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_workflow_has_no_leaked_keys():
    with open(WF_PATH, encoding="utf-8") as f:
        raw = f.read()
    assert "sk-or-v1" not in raw
    assert "api_key" not in raw.lower()


def test_workflow_is_the_users_export_verbatim():
    """The app must not strip or rewire anything in the shipped JSON — including
    117/134 (idle preview/debug nodes) and 172:166 (now-orphaned "fps*2" node,
    since 133 reads fps straight from 157 in this export). They're harmless: none
    of them are reachable from either result output (163/133), so run_video never
    surfaces them, but they stay in the file exactly as exported."""
    graph = _load_graph()
    assert "117" in graph
    assert "134" in graph
    assert "172:166" in graph
    assert graph["117"]["class_type"] == "PreviewImage"


def test_build_scail2motion_wires_core_inputs():
    graph = _load_graph()
    inp = {"prompt": "walking through a market", "trigger": "ing2lorance",
           "fps": 30, "frame_cap": 60}
    out = cc._build_scail2motion(graph, inp, seed=999, video_name="drv.mp4", ref_name="ref.png")
    assert out["113"]["inputs"]["video"] == "drv.mp4"
    assert out["113"]["inputs"]["frame_load_cap"] == 60
    assert out["157"]["inputs"]["value"] == 30        # fps primitive
    assert out["58"]["inputs"]["image"] == "ref.png"
    assert out["6"]["inputs"]["text"] == "ing2lorance, walking through a market"
    assert out["132"]["inputs"]["seed"] == 999


def test_build_scail2motion_negative_prompt_left_at_workflow_default():
    """Unlike i2i/t2i, this mode's negative prompt isn't overwritten with the
    generic NEGATIVE constant — the shipped Wan 2.1 negative stays as-is."""
    graph = _load_graph()
    baked = graph["7"]["inputs"]["text"]
    out = cc._build_scail2motion(graph, {"prompt": "x"}, seed=1, video_name="v.mp4", ref_name="r.png")
    assert out["7"]["inputs"]["text"] == baked
    assert baked != cc.NEGATIVE


def test_build_scail2motion_no_fps_or_frame_cap_leaves_workflow_defaults():
    """V2.0 shipped defaults: fps 30 (was 24 in V1), frame_load_cap 0 = uncapped
    (was 81 in V1)."""
    graph = _load_graph()
    out = cc._build_scail2motion(graph, {"prompt": "x"}, seed=1, video_name="v.mp4", ref_name="r.png")
    assert out["157"]["inputs"]["value"] == 30
    assert out["113"]["inputs"]["frame_load_cap"] == 0


def test_build_scail2motion_no_character_lora_by_default():
    graph = _load_graph()
    out = cc._build_scail2motion(graph, {"prompt": "x"}, seed=1, video_name="v.mp4", ref_name="r.png")
    assert "sc2_char_lora" not in out
    assert out["128"]["inputs"]["model"] == ["130", 0]   # sage-attn left reading the locked chain


def test_build_scail2motion_optional_character_lora_chains_after_locked_loras():
    graph = _load_graph()
    inp = {"prompt": "x", "character_lora_path": "wan/Own/Alice/Alice.safetensors",
           "character_strength": 0.85}
    out = cc._build_scail2motion(graph, inp, seed=1, video_name="v.mp4", ref_name="r.png")
    assert out["sc2_char_lora"]["class_type"] == "LoraLoaderModelOnly"
    assert out["sc2_char_lora"]["inputs"]["lora_name"] == inp["character_lora_path"]
    assert out["sc2_char_lora"]["inputs"]["strength_model"] == 0.85
    assert out["sc2_char_lora"]["inputs"]["model"] == ["130", 0]   # after the locked Pusa lora
    assert out["128"]["inputs"]["model"] == ["sc2_char_lora", 0]   # sage-attn rewired to it


def test_build_scail2motion_upscale_off_drops_tail_keeps_raw():
    graph = _load_graph()
    out = cc._build_scail2motion(graph, {"prompt": "x"}, seed=1, video_name="v.mp4", ref_name="r.png")
    for nid in cc.SCAIL2MOTION_UPSCALE_CHAIN:
        assert nid not in out, f"node {nid} should be dropped when upscale is off"
    assert "163" in out   # raw output stays
    dropped = set(cc.SCAIL2MOTION_UPSCALE_CHAIN)
    for node in out.values():
        for v in (node.get("inputs") or {}).values():
            if isinstance(v, list) and len(v) == 2:
                assert str(v[0]) not in dropped


def test_build_scail2motion_upscale_on_keeps_both_outputs():
    graph = _load_graph()
    out = cc._build_scail2motion(graph, {"prompt": "x", "upscale": True}, seed=1,
                                 video_name="v.mp4", ref_name="r.png")
    assert "163" in out            # raw
    assert "133" in out            # color-matched + RTX + RIFE final
    assert "172:164" in out        # RTX super-res survives


def test_build_scail2motion_final_output_is_same_framerate_as_raw():
    """V2.0 behavior change from V1: the "final" (upscaled) output no longer runs
    at 2x the fps via RIFE frame-doubling — it's the same frame rate as the raw
    output, just spatially upscaled. Both combiners must tag the same fps."""
    graph = _load_graph()
    out = cc._build_scail2motion(graph, {"prompt": "x", "fps": 25, "upscale": True},
                                 seed=1, video_name="v.mp4", ref_name="r.png")
    assert out["163"]["inputs"]["frame_rate"] == ["157", 0]
    assert out["133"]["inputs"]["frame_rate"] == ["157", 0]
    assert out["157"]["inputs"]["value"] == 25
    assert out["172:165"]["inputs"]["multiplier"] == 1   # RIFE no longer doubles frame count


def test_build_scail2motion_applies_sampler_override_where_applicable():
    """WanSCAILInfinity's class_type has no 'Sampler' substring, so the generic
    broadcast is a no-op on node 132 — verifying that rather than assuming it."""
    graph = _load_graph()
    inp = {"prompt": "x", "sampler_override": {"cfg": 2, "scheduler": "unipc"}}
    out = cc._build_scail2motion(graph, inp, seed=1, video_name="v.mp4", ref_name="r.png")
    assert out["132"]["inputs"]["cfg"] == 1          # untouched — not a "*Sampler*" class_type
    assert "WanSCAILInfinity" == out["132"]["class_type"]
    assert "Sampler" not in out["132"]["class_type"]

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc


WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_scail2motiontest.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_test_workflow_uses_wan_style_reference_crop_before_scail_resize():
    graph = _load_graph()
    crop = graph["sc2_ref_crop"]["inputs"]
    assert graph["sc2_video_info"]["class_type"] == "VHS_VideoInfo"
    assert crop["image"] == ["58", 0]
    assert crop["width"] == ["sc2_video_info", 8]
    assert crop["height"] == ["sc2_video_info", 9]
    assert crop["keep_proportion"] == "crop"
    assert crop["crop_position"] == "top"
    assert graph["102"]["inputs"]["input"] == ["sc2_ref_crop", 0]


def test_test_workflow_generation_resolution_presets_and_safe_default():
    for preset, megapixels in (("480p", 0.4), ("720p", 0.9), ("1080p", 2.1), ("bad", 0.9), (None, 0.9)):
        graph = _load_graph()
        inp = {"prompt": "x"}
        if preset is not None:
            inp["generation_resolution"] = preset
        out = cc._build_scail2motion(graph, inp, seed=1, video_name="v.mp4", ref_name="r.png")
        assert out["102"]["inputs"]["resize_type.megapixels"] == megapixels


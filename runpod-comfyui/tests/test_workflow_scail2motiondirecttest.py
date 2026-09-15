import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_scail2motiondirecttest.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_direct_test_uses_fixed_portrait_dimensions_before_scail():
    graph = _load_graph()
    assert graph["sc2_target_width"]["inputs"]["value"] == 720
    assert graph["sc2_target_height"]["inputs"]["value"] == 1280
    assert graph["sc2_target_width"]["class_type"] == "PrimitiveInt"
    assert graph["sc2_target_height"]["class_type"] == "PrimitiveInt"
    assert graph["sc2_ref_crop"]["inputs"]["width"] == ["sc2_target_width", 0]
    assert graph["sc2_ref_crop"]["inputs"]["height"] == ["sc2_target_height", 0]
    assert graph["104"]["inputs"]["image"] == ["sc2_ref_crop", 0]
    assert graph["113"]["inputs"]["custom_width"] == ["104", 0]
    assert graph["113"]["inputs"]["custom_height"] == ["104", 1]
    assert graph["132"]["inputs"]["width"] == ["104", 0]
    assert graph["132"]["inputs"]["height"] == ["104", 1]
    assert graph["56"]["inputs"]["image"] == ["sc2_ref_crop", 0]
    assert graph["116"]["inputs"]["images"] == ["sc2_ref_crop", 0]
    assert graph["132"]["inputs"]["reference_image"] == ["sc2_ref_crop", 0]


def test_direct_test_uses_the_installed_scail2_model_path():
    graph = _load_graph()
    assert graph["37"]["inputs"]["unet_name"] == "INT8Convert\\wan2.1_14B_SCAIL_2_int8_convrot.safetensors"

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc


def test_noop_when_override_absent():
    graph = {"1": {"class_type": "KSampler",
                   "inputs": {"cfg": 1, "sampler_name": "res_2s", "scheduler": "simple"}}}
    out = cc._apply_sampler_override(graph, {})
    assert out["1"]["inputs"] == {"cfg": 1, "sampler_name": "res_2s", "scheduler": "simple"}


def test_broadcasts_to_every_sampler_node_only():
    graph = {
        "1": {"class_type": "KSampler",
              "inputs": {"cfg": 1, "sampler_name": "res_2s", "scheduler": "simple"}},
        "2": {"class_type": "ClownsharKSampler_Beta",
              "inputs": {"cfg": 1, "sampler_name": "exponential/res_2s", "scheduler": "bong_tangent"}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    }
    inp = {"sampler_override": {"cfg": 3.5, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._apply_sampler_override(graph, inp)
    assert out["1"]["inputs"]["cfg"] == 3.5
    assert out["1"]["inputs"]["sampler_name"] == "euler"
    assert out["2"]["inputs"]["scheduler"] == "karras"
    assert out["3"]["inputs"] == {"images": ["1", 0]}


def test_skips_keys_the_node_class_does_not_have():
    graph = {"1": {"class_type": "WanVideoSampler", "inputs": {"cfg": 1, "scheduler": "dpm++_sde"}}}
    inp = {"sampler_override": {"cfg": 2, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._apply_sampler_override(graph, inp)
    assert out["1"]["inputs"]["cfg"] == 2
    assert out["1"]["inputs"]["scheduler"] == "karras"
    assert "sampler_name" not in out["1"]["inputs"]


def test_partial_override_only_touches_given_keys():
    graph = {"1": {"class_type": "KSampler",
                   "inputs": {"cfg": 1, "sampler_name": "res_2s", "scheduler": "simple"}}}
    out = cc._apply_sampler_override(graph, {"sampler_override": {"cfg": 2}})
    assert out["1"]["inputs"]["cfg"] == 2
    assert out["1"]["inputs"]["sampler_name"] == "res_2s"
    assert out["1"]["inputs"]["scheduler"] == "simple"

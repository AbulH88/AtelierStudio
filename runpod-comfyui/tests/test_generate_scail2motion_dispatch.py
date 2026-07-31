import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..")

_B64 = base64.b64encode(b"x").decode()


def test_generate_scail2motion_returns_both_outputs(monkeypatch):
    calls = {}

    monkeypatch.setattr(cc, "upload_video", lambda base, raw, filename="driving.mp4": "drv.mp4")
    monkeypatch.setattr(cc, "upload_image", lambda base, raw: "ref.png")

    def fake_run_video(base, graph, out_node="319", timeout=1800, client_id=None):
        calls["out_node"] = out_node
        calls["timeout"] = timeout
        calls["graph"] = graph
        return ["RAWb64", "UPSCALEDb64"]

    monkeypatch.setattr(cc, "run_video", fake_run_video)

    inp = {"mode": "scail2motion", "prompt": "p", "video_b64": _B64, "ref_b64": _B64,
           "upscale": True, "seed": 7}
    out = cc.generate("http://fake", WORKFLOW_DIR, inp)

    assert out == {"videos": ["RAWb64", "UPSCALEDb64"], "seed": 7}
    assert calls["out_node"] == [cc.SCAIL2MOTION["output_raw"], cc.SCAIL2MOTION["output_final"]]
    assert calls["timeout"] == 1800
    # upscale on -> the color-match/RTX/RIFE tail is present in the submitted graph
    assert "133" in calls["graph"]


def test_generate_scail2motion_raw_only_when_upscale_off(monkeypatch):
    monkeypatch.setattr(cc, "upload_video", lambda base, raw, filename="driving.mp4": "drv.mp4")
    monkeypatch.setattr(cc, "upload_image", lambda base, raw: "ref.png")

    def fake_run_video(base, graph, out_node="319", timeout=1800, client_id=None):
        return ["RAWb64"]

    monkeypatch.setattr(cc, "run_video", fake_run_video)

    inp = {"mode": "scail2motion", "prompt": "p", "video_b64": _B64, "ref_b64": _B64, "seed": 3}
    out = cc.generate("http://fake", WORKFLOW_DIR, inp)
    assert out == {"videos": ["RAWb64"], "seed": 3}


def test_generate_scail2motion_no_video_produced_is_an_error(monkeypatch):
    monkeypatch.setattr(cc, "upload_video", lambda base, raw, filename="driving.mp4": "drv.mp4")
    monkeypatch.setattr(cc, "upload_image", lambda base, raw: "ref.png")
    monkeypatch.setattr(cc, "run_video", lambda *a, **k: [])

    inp = {"mode": "scail2motion", "prompt": "p", "video_b64": _B64, "ref_b64": _B64}
    out = cc.generate("http://fake", WORKFLOW_DIR, inp)
    assert "error" in out

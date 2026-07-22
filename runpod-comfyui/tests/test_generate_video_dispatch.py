import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..")

_B64 = base64.b64encode(b"x").decode()


def test_generate_video_returns_both_outputs(monkeypatch):
    calls = {}

    monkeypatch.setattr(cc, "upload_video", lambda base, raw, filename="driving.mp4": "drv.mp4")
    monkeypatch.setattr(cc, "upload_image", lambda base, raw: "ref.png")

    def fake_run_video(base, graph, out_node="319", timeout=1800, client_id=None):
        calls["out_node"] = out_node
        calls["graph"] = graph
        # emulate both the raw (285) and upscaled (369) combiners producing a clip
        return ["RAWb64", "UPSCALEDb64"]

    monkeypatch.setattr(cc, "run_video", fake_run_video)

    inp = {"mode": "video", "prompt": "p", "video_b64": _B64, "ref_b64": _B64,
           "upscale": True, "seed": 7}
    out = cc.generate("http://fake", WORKFLOW_DIR, inp)

    assert out == {"videos": ["RAWb64", "UPSCALEDb64"], "seed": 7}
    # generate() must ask run_video for BOTH the raw and final output nodes
    assert calls["out_node"] == [cc.VIDEO["output_raw"], cc.VIDEO["output_final"]]
    # upscale on -> the RTX/RIFE tail is present in the submitted graph
    assert "369" in calls["graph"]


def test_run_video_collects_from_multiple_nodes(monkeypatch):
    # /history shows two saved combiners; run_video should return both, in order.
    hist = {"pid1": {"status": {"status_str": "success"}, "outputs": {
        "285": {"gifs": [{"filename": "raw.mp4", "type": "output"}]},
        "369": {"gifs": [{"filename": "up.mp4", "type": "output"}]},
    }}}

    class FakeResp:
        def __init__(self, payload=None, content=b""):
            self._payload = payload
            self.content = content

        def json(self):
            return self._payload

    def fake_post(url, **kw):
        return FakeResp({"prompt_id": "pid1"})

    def fake_get(url, **kw):
        if "/history/" in url:
            return FakeResp(hist)
        # /view -> return distinct bytes per filename so we can tell them apart
        fn = kw["params"]["filename"]
        return FakeResp(content=fn.encode())

    monkeypatch.setattr(cc.requests, "post", fake_post)
    monkeypatch.setattr(cc.requests, "get", fake_get)

    vids = cc.run_video("http://fake", {}, out_node=["285", "369"])
    assert vids == [base64.b64encode(b"raw.mp4").decode(),
                    base64.b64encode(b"up.mp4").decode()]

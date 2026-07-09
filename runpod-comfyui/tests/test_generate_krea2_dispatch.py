import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..")


def test_generate_dispatches_krea2_without_network(monkeypatch):
    calls = {}

    def fake_upload_image(base, raw_bytes):
        calls["uploaded"] = raw_bytes
        return "uploaded_frame.png"

    def fake_run(base, graph, timeout=900, client_id=None, out_node=None):
        calls["graph"] = graph
        return ["ZmFrZQ=="]   # base64 "fake"

    monkeypatch.setattr(cc, "upload_image", fake_upload_image)
    monkeypatch.setattr(cc, "run", fake_run)

    inp = {"mode": "krea2", "prompt": "a woman in red",
           "image_b64": base64.b64encode(b"fake-image-bytes").decode(),
           "variations": 1, "seed": 42}
    out = cc.generate("http://fake-comfy", WORKFLOW_DIR, inp)

    assert out == {"images": ["ZmFrZQ=="], "seed": 42}
    assert calls["uploaded"] == b"fake-image-bytes"
    assert calls["graph"]["316"]["inputs"]["image"] == "uploaded_frame.png"
    assert calls["graph"]["314"]["inputs"]["text"] == "ing2lorance, a woman in red"

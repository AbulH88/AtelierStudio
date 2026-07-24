import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..")


def test_generate_dispatches_krea2t2ihq_without_network_or_upload(monkeypatch):
    calls = {}

    def fail_upload_image(base, raw_bytes):
        raise AssertionError("krea2t2ihq is pure t2i — must never upload an image to ComfyUI")

    def fake_run(base, graph, timeout=900, client_id=None, out_node=None):
        calls["graph"] = graph
        return ["ZmFrZQ=="]

    monkeypatch.setattr(cc, "upload_image", fail_upload_image)
    monkeypatch.setattr(cc, "run", fake_run)

    inp = {"mode": "krea2t2ihq", "prompt": "a woman in red", "variations": 1, "seed": 42}
    out = cc.generate("http://fake-comfy", WORKFLOW_DIR, inp)

    assert out == {"images": ["ZmFrZQ=="], "seed": 42}
    assert calls["graph"]["439"]["inputs"]["text"] == "ing2lorance, a woman in red"
    assert calls["graph"]["458"]["inputs"]["batch_size"] == 1

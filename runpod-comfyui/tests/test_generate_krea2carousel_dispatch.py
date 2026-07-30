import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..")


def test_generate_dispatches_krea2carousel_without_network_or_upload(monkeypatch):
    calls = {}

    def fail_upload_image(base, raw_bytes):
        raise AssertionError("krea2carousel is pure t2i — must never upload an image to ComfyUI")

    def fake_run(base, graph, timeout=900, client_id=None, out_node=None):
        calls["graph"] = graph
        return ["ZmFrZQ=="]

    monkeypatch.setattr(cc, "upload_image", fail_upload_image)
    monkeypatch.setattr(cc, "run", fake_run)

    inp = {"mode": "krea2carousel", "prompt": "a woman in red", "variations": 1, "seed": 42}
    out = cc.generate("http://fake-comfy", WORKFLOW_DIR, inp)

    assert out == {"images": ["ZmFrZQ=="], "seed": 42}
    assert calls["graph"]["6"]["inputs"]["text"] == "ing2lorance, a woman in red"
    assert calls["graph"]["10"]["inputs"]["batch_size"] == 1


def test_generate_krea2carousel_shoots_the_whole_carousel_in_one_pass(monkeypatch):
    """A carousel should come out of a single sampler batch when it fits under
    max_batch — 6 slides = 1 queued graph with batch_size 6, not 6 separate runs."""
    graphs = []

    def fake_run(base, graph, timeout=900, client_id=None, out_node=None):
        graphs.append(graph)
        return ["ZmFrZQ=="] * graph["10"]["inputs"]["batch_size"]

    monkeypatch.setattr(cc, "run", fake_run)

    inp = {"mode": "krea2carousel", "prompt": "x", "variations": 6, "seed": 7}
    out = cc.generate("http://fake-comfy", WORKFLOW_DIR, inp, max_batch=8)

    assert len(graphs) == 1
    assert graphs[0]["10"]["inputs"]["batch_size"] == 6
    assert len(out["images"]) == 6


def test_generate_krea2carousel_chunks_when_over_max_batch(monkeypatch):
    """Over max_batch it falls back to the shared chunking loop, with a distinct
    seed per chunk so the extra slides aren't carbon copies of the first ones."""
    graphs = []

    def fake_run(base, graph, timeout=900, client_id=None, out_node=None):
        graphs.append(graph)
        return ["ZmFrZQ=="] * graph["10"]["inputs"]["batch_size"]

    monkeypatch.setattr(cc, "run", fake_run)

    inp = {"mode": "krea2carousel", "prompt": "x", "variations": 5, "seed": 100}
    out = cc.generate("http://fake-comfy", WORKFLOW_DIR, inp, max_batch=2)

    assert [g["10"]["inputs"]["batch_size"] for g in graphs] == [2, 2, 1]
    assert [g["98"]["inputs"]["seed"] for g in graphs] == [100, 102, 104]
    assert len(out["images"]) == 5
    assert out["seed"] == 100

"""Tests for the cloud (RunPod) seam: cost map, LoRA manifest, and the
/api/cloud/* endpoints. Run:  python -m pytest test_cloud.py -q   (or python test_cloud.py)

These cover the pure logic + endpoint wiring that is buildable/verifiable without
a live RunPod endpoint (cloud unconfigured is a first-class, tested state)."""
import json
import os
import tempfile

import pytest

import app as A


@pytest.fixture
def client(monkeypatch):
    A.app.config["TESTING"] = True
    # bypass the login gate with a fake active admin
    monkeypatch.setattr(A, "load_users",
                        lambda: {"tester": {"status": "active", "role": "admin"}})
    c = A.app.test_client()
    with c.session_transaction() as s:
        s["user"] = "tester"
    return c


# --- cost map ----------------------------------------------------------------
def test_price_per_sec_from_table(monkeypatch):
    monkeypatch.delenv("RUNPOD_PRICE_PER_SEC", raising=False)
    monkeypatch.setattr(A, "RUNPOD_GPU", "L40S")
    assert A._price_per_sec() == 0.00053


def test_price_per_sec_normalizes_gpu_name(monkeypatch):
    monkeypatch.delenv("RUNPOD_PRICE_PER_SEC", raising=False)
    monkeypatch.setattr(A, "RUNPOD_GPU", "rtx 4090")
    assert A._price_per_sec() == 0.00034


def test_price_per_sec_env_override_wins(monkeypatch):
    monkeypatch.setenv("RUNPOD_PRICE_PER_SEC", "0.009")
    monkeypatch.setattr(A, "RUNPOD_GPU", "L40S")
    assert A._price_per_sec() == 0.009


def test_price_per_sec_unknown_gpu_falls_back(monkeypatch):
    monkeypatch.delenv("RUNPOD_PRICE_PER_SEC", raising=False)
    monkeypatch.setattr(A, "RUNPOD_GPU", "MadeUpGPU")
    assert A._price_per_sec() == 0.0005


# --- manifest ----------------------------------------------------------------
def _write_manifest(data):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    json.dump(data, open(path, "w", encoding="utf-8"))
    return path


def test_cloud_lora_set_list_form(monkeypatch):
    p = _write_manifest(["wan/A/x.safetensors", "wan/B/Y.SafeTensors"])
    monkeypatch.setattr(A, "CLOUD_LORAS_FILE", p)
    s = A._cloud_lora_set()
    assert "wan/a/x.safetensors" in s          # lowercased
    assert "wan/b/y.safetensors" in s
    os.remove(p)


def test_cloud_lora_set_dict_form_and_backslashes(monkeypatch):
    p = _write_manifest({"loras": ["wan\\C\\z.safetensors"]})
    monkeypatch.setattr(A, "CLOUD_LORAS_FILE", p)
    assert A._cloud_lora_set() == {"wan/c/z.safetensors"}   # normalized slashes
    os.remove(p)


def test_cloud_lora_set_missing_file_is_empty(monkeypatch):
    monkeypatch.setattr(A, "CLOUD_LORAS_FILE", "/no/such/file.json")
    assert A._cloud_lora_set() == set()


# --- status (unconfigured) ---------------------------------------------------
def test_cloud_status_unconfigured(monkeypatch):
    monkeypatch.setattr(A, "ENDPOINT_ID", "")
    monkeypatch.setattr(A, "API_KEY", "")
    assert A._cloud_status() == {"configured": False}


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _configured(monkeypatch, payload):
    monkeypatch.setattr(A, "ENDPOINT_ID", "ep123")
    monkeypatch.setattr(A, "API_KEY", "key123")
    monkeypatch.setattr(A.requests, "get", lambda *a, **k: _FakeResp(payload))


def test_cloud_status_warming(monkeypatch):
    _configured(monkeypatch, {"workers": {"initializing": 1, "ready": 0, "running": 0,
                                          "idle": 0}, "jobs": {"inQueue": 2}})
    st = A._cloud_status()
    assert st["configured"] and st["warming"] and not st["ready"]
    assert st["queued"] == 2


def test_cloud_status_ready(monkeypatch):
    _configured(monkeypatch, {"workers": {"idle": 1, "running": 1},
                              "jobs": {"inProgress": 1}})
    st = A._cloud_status()
    assert st["ready"] and not st["warming"]
    assert st["in_progress"] == 1


def test_cloud_status_error_is_caught(monkeypatch):
    monkeypatch.setattr(A, "ENDPOINT_ID", "ep123")
    monkeypatch.setattr(A, "API_KEY", "key123")

    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(A.requests, "get", boom)
    st = A._cloud_status()
    assert st["configured"] is True and "error" in st


# --- endpoints ---------------------------------------------------------------
def test_cloud_info_endpoint(client, monkeypatch):
    p = _write_manifest(["wan/A/x.safetensors"])
    monkeypatch.setattr(A, "CLOUD_LORAS_FILE", p)
    monkeypatch.setattr(A, "RUNPOD_GPU", "L40S")
    d = client.get("/api/cloud/info").get_json()
    assert d["gpu"] == "L40S"
    assert d["price_per_sec"] == 0.00053
    assert d["manifest_count"] == 1
    assert d["manifest"] == ["wan/a/x.safetensors"]
    os.remove(p)


def test_cloud_status_endpoint_unconfigured(client, monkeypatch):
    monkeypatch.setattr(A, "ENDPOINT_ID", "")
    monkeypatch.setattr(A, "API_KEY", "")
    assert client.get("/api/cloud/status").get_json() == {"configured": False}


def test_request_sync_persists_and_dedupes(client, monkeypatch):
    fd, p = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(p)  # start with no file
    monkeypatch.setattr(A, "SYNC_FILE", p)

    r = client.post("/api/cloud/request-sync",
                    json={"path": "wan/A/x.safetensors", "label": "X"})
    assert r.get_json() == {"ok": True}
    # duplicate path is ignored
    client.post("/api/cloud/request-sync", json={"path": "wan/A/x.safetensors"})
    saved = json.load(open(p, encoding="utf-8"))
    assert len(saved) == 1
    assert saved[0]["path"] == "wan/A/x.safetensors"
    assert saved[0]["user"] == "tester"

    listed = client.get("/api/cloud/sync-requests").get_json()
    assert listed["requests"][0]["label"] == "X"
    os.remove(p)


def test_request_sync_rejects_empty_path(client):
    r = client.post("/api/cloud/request-sync", json={"path": "  "})
    assert r.status_code == 400


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))

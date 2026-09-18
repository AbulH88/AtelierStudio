"""Admin-managed global RunningHub key behavior."""
import json

import app as A


def _admin_client(monkeypatch, tmp_path):
    users = {"admin": {"status": "active", "role": "admin"},
             "maker": {"status": "active", "role": "user"}}
    monkeypatch.setattr(A, "load_users", lambda: users)
    monkeypatch.setattr(A, "RUNNINGHUB_GLOBAL_SETTINGS_FILE", str(tmp_path / "global-key.json"))
    monkeypatch.setattr(A, "RUNNINGHUB_GLOBAL_API_KEY", "legacy_global_key_123456")
    client = A.app.test_client()
    with client.session_transaction() as session:
        session["user"] = "admin"
    return client, users


def test_admin_managed_global_key_is_encrypted_and_preferred(monkeypatch, tmp_path):
    client, _ = _admin_client(monkeypatch, tmp_path)
    response = client.put("/api/runninghub/global-key", json={"api_key": "managed_global_key_123456", "concurrency": 3})
    assert response.status_code == 200
    stored = json.loads((tmp_path / "global-key.json").read_text())
    assert "managed_global_key_123456" not in json.dumps(stored)
    assert A._runninghub_global_settings()["key"] == "managed_global_key_123456"
    assert A._runninghub_global_settings()["concurrency"] == 3


def test_removing_global_key_disables_legacy_environment_fallback(monkeypatch, tmp_path):
    client, _ = _admin_client(monkeypatch, tmp_path)
    assert client.delete("/api/runninghub/global-key").status_code == 200
    assert A._runninghub_global_settings()["key"] == ""
    assert A._runninghub_global_settings()["source"] == "none"


def test_non_admin_cannot_manage_global_key(monkeypatch, tmp_path):
    client, _ = _admin_client(monkeypatch, tmp_path)
    with client.session_transaction() as session:
        session["user"] = "maker"
    assert client.get("/api/runninghub/global-key").status_code == 403
    assert client.put("/api/runninghub/global-key", json={"api_key": "managed_global_key_123456"}).status_code == 403

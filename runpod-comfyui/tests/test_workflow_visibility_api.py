import json
import os
import sys

import pytest

pytest.importorskip("flask")

ROOT = os.path.join(os.path.dirname(__file__), "..")
WEBAPP = os.path.join(ROOT, "webapp")
sys.path.insert(0, ROOT)
sys.path.insert(0, WEBAPP)

import app as studio  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    workflows_path = tmp_path / "workflows.json"
    users_path.write_text(json.dumps({
        "admin": {"password": "unused", "role": "admin", "status": "active"},
        "member": {"password": "unused", "role": "user", "status": "active"},
    }), encoding="utf-8")
    monkeypatch.setattr(studio, "USERS_FILE", str(users_path))
    monkeypatch.setattr(studio, "WORKFLOWS_FILE", str(workflows_path))
    studio.app.config.update(TESTING=True)
    return studio.app.test_client()


def _login_session(client, username):
    with client.session_transaction() as session:
        session["user"] = username


def test_admin_can_set_workflow_disabled_and_enabled_idempotently(client):
    _login_session(client, "admin")

    for enabled in (False, False, True, True):
        response = client.post(
            "/api/workflows/krea2t2ihq/state", json={"enabled": enabled})
        assert response.status_code == 200
        assert response.get_json() == {"ok": True, "enabled": enabled}
        assert studio.load_workflow_settings()["krea2t2ihq"] is enabled


def test_state_endpoint_rejects_non_boolean_and_unknown_workflow(client):
    _login_session(client, "admin")
    response = client.post(
        "/api/workflows/krea2t2ihq/state", json={"enabled": "false"})
    assert response.status_code == 400
    assert "true or false" in response.get_json()["error"]

    response = client.post("/api/workflows/not-real/state", json={"enabled": False})
    assert response.status_code == 404


def test_state_endpoint_requires_admin(client):
    _login_session(client, "member")
    response = client.post(
        "/api/workflows/krea2t2ihq/state", json={"enabled": False})
    assert response.status_code == 403
    assert response.get_json()["error"] == "admin only"


def test_existing_workflow_settings_format_stays_compatible(client):
    _login_session(client, "admin")
    with open(studio.WORKFLOWS_FILE, "w", encoding="utf-8") as handle:
        json.dump({"krea2t2ihq": False, "krea2carousel": True}, handle)

    response = client.get("/api/workflows")
    assert response.status_code == 200
    values = {item["id"]: item["enabled"]
              for item in response.get_json()["workflows"]}
    assert values["krea2t2ihq"] is False
    assert values["krea2carousel"] is True

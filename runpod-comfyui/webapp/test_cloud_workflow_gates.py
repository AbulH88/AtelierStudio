"""Cloud workflow permissions are deny-by-default and enforced server-side."""
import app as A


def _client(monkeypatch, workflows=None, role="user"):
    users = {"maker": {"status": "active", "role": role}}
    if workflows is not None:
        users["maker"]["cloud_workflows"] = workflows
    monkeypatch.setattr(A, "load_users", lambda: users)
    client = A.app.test_client()
    with client.session_transaction() as session:
        session["user"] = "maker"
    return client, users


def test_cloud_workflows_deny_non_admins_by_default(monkeypatch):
    client, _ = _client(monkeypatch)
    response = client.get("/api/runninghub/settings")
    assert response.status_code == 200
    assert response.get_json()["cloud_workflows"] == []
    assert client.get("/api/runninghub/jobs").status_code == 403
    assert client.post("/api/runninghub/jobs").status_code == 403
    assert client.post("/api/runninghub/h3/jobs").status_code == 403
    assert client.post("/api/runninghub/krea2/jobs").status_code == 403


def test_admins_have_all_cloud_workflows(monkeypatch):
    client, _ = _client(monkeypatch, role="admin")
    assert set(client.get("/api/runninghub/settings").get_json()["cloud_workflows"]) == A.CLOUD_WORKFLOW_IDS


def test_admin_can_set_a_users_cloud_allowlist(monkeypatch):
    users = {
        "admin": {"status": "active", "role": "admin"},
        "maker": {"status": "active", "role": "user"},
    }
    saved = []
    monkeypatch.setattr(A, "load_users", lambda: users)
    monkeypatch.setattr(A, "save_users", lambda value: saved.append(value))
    client = A.app.test_client()
    with client.session_transaction() as session:
        session["user"] = "admin"
    response = client.post("/api/users/maker/set-cloud-workflows", json={"workflows": ["h3", "jobs"]})
    assert response.status_code == 200
    assert users["maker"]["cloud_workflows"] == ["h3", "jobs"]
    assert saved

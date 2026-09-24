import io
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / "webapp")]
import app as studio


@pytest.fixture
def client(tmp_path, monkeypatch):
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"owner": {"role": "admin", "status": "active", "password": "unused"},
                                 "other": {"role": "user", "status": "active", "password": "unused"}}))
    monkeypatch.setattr(studio, "USERS_FILE", str(users))
    studio.app.config.update(TESTING=True)
    studio.ENHANCE_JOB_OWNERS.clear()
    test_client = studio.app.test_client()
    with test_client.session_transaction() as session:
        session["user"] = "owner"
    return test_client


def test_job_proxy_records_owner_and_rejects_other_user(client, monkeypatch):
    class Upstream:
        status_code = 202
        content = b'{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","status":"queued"}'
        headers = {"Content-Type": "application/json"}
        def json(self):
            return json.loads(self.content)

    monkeypatch.setattr(studio, "_enhance_agent", lambda *args, **kwargs: Upstream())
    response = client.post("/api/enhance/jobs", data={"video": (io.BytesIO(b"clip"), "clip.mp4"),
                                                      "options": "{}"})
    assert response.status_code == 202
    assert studio.ENHANCE_JOB_OWNERS["a" * 32] == "owner"
    with client.session_transaction() as session:
        session["user"] = "other"
    assert client.get("/api/enhance/jobs/" + "a" * 32).status_code == 404
    assert client.post("/api/enhance/jobs/" + "a" * 32 + "/cancel").status_code == 404
    assert client.get("/api/enhance/jobs/" + "a" * 32 + "/result").status_code == 404


def test_image_job_uses_media_field(client, monkeypatch):
    captured = {}

    class Upstream:
        status_code = 202
        content = b'{"id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","status":"queued"}'
        headers = {"Content-Type": "application/json"}
        def json(self):
            return json.loads(self.content)

    def agent(method, path, **kwargs):
        captured.update(kwargs)
        return Upstream()

    monkeypatch.setattr(studio, "_enhance_agent", agent)
    response = client.post(
        "/api/enhance/jobs",
        data={"media": (io.BytesIO(b"image"), "portrait.png"), "options": "{}"},
    )
    assert response.status_code == 202
    assert captured["files"]["media"][0] == "portrait.png"


def test_result_proxy_preserves_image_content_type(client, monkeypatch):
    class Upstream:
        status_code = 200
        content = b""
        headers = {
            "Content-Type": "image/png",
            "Content-Disposition": 'inline; filename="portrait_DLSS5.png"',
        }
        def iter_content(self, _size):
            yield b"png"

    studio.ENHANCE_JOB_OWNERS["c" * 32] = "owner"
    monkeypatch.setattr(studio, "_enhance_agent", lambda *args, **kwargs: Upstream())
    response = client.get("/api/enhance/jobs/" + "c" * 32 + "/result")
    assert response.status_code == 200
    assert response.content_type == "image/png"
    assert "portrait_DLSS5.png" in response.headers["Content-Disposition"]

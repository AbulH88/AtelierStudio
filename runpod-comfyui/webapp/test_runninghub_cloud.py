"""Focused RunningHub Cloud contract tests; all HTTP is mocked."""
import json
from io import BytesIO

import pytest

import app as A


@pytest.fixture
def users(monkeypatch):
    data = {
        "admin": {"status": "active", "role": "admin", "runninghub_plus": False},
        "maker": {"status": "active", "role": "user", "runninghub_plus": False},
    }
    monkeypatch.setattr(A, "load_users", lambda: data)
    monkeypatch.setattr(A, "save_users", lambda _users: None)
    return data


@pytest.fixture
def maker_client(users):
    A.app.config["TESTING"] = True
    client = A.app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = "maker"
    return client


def test_credential_is_encrypted_and_masked():
    key = "rh_example_secret_1234567890"
    encrypted = A._encrypt_runninghub_key(key)
    assert encrypted != key
    assert A._decrypt_runninghub_key(encrypted) == key
    assert A._mask_runninghub_key(key).endswith("7890")


def test_user_can_save_key_without_getting_it_back(maker_client, users):
    response = maker_client.put("/api/runninghub/settings", json={"api_key": "rh_example_secret_1234567890"})
    body = response.get_json()
    assert response.status_code == 200
    assert body["configured"] is True
    assert "rh_example" not in json.dumps(body)
    assert A._decrypt_runninghub_key(users["maker"]["runninghub_key_enc"]).startswith("rh_example")


def test_plus_requires_an_admin_entitlement(maker_client, users):
    users["maker"]["runninghub_key_enc"] = A._encrypt_runninghub_key("rh_example_secret_1234567890")
    response = maker_client.post("/api/runninghub/jobs", data={
        "instance_type": "plus",
        "reference": (BytesIO(b"fake-image"), "reference.png"),
        "video": (BytesIO(b"fake-video"), "drive.mp4"),
    })
    assert response.status_code == 403
    # The public settings contract still withholds Plus for this user.
    assert maker_client.get("/api/runninghub/settings").get_json()["plus_allowed"] is False


def test_admin_can_enable_plus(users):
    client = A.app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = "admin"
    response = client.post("/api/users/maker/set-runninghub-plus", json={"enabled": True})
    assert response.status_code == 200
    assert users["maker"]["runninghub_plus"] is True


def test_submit_uses_published_image_video_and_clip_nodes(monkeypatch):
    seen = {}

    class Response:
        ok = True
        status_code = 200
        def json(self):
            return {"taskId": "task-123", "status": "QUEUED"}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["payload"] = kwargs["json"]
        return Response()

    monkeypatch.setattr(A.requests, "post", fake_post)
    clip = {"skip_first_frames": 48, "frame_load_cap": 120, "select_every_nth": 2}
    response = A._runninghub_submit("key", "api/ref.png", "api/drive.mp4", "default", clip)
    assert response["taskId"] == "task-123"
    assert seen["payload"]["instanceType"] == "default"
    assert seen["payload"]["nodeInfoList"] == [
        {"nodeId": A.RUNNINGHUB_REFERENCE_NODE_ID, "fieldName": A.RUNNINGHUB_REFERENCE_FIELD, "fieldValue": "api/ref.png"},
        {"nodeId": A.RUNNINGHUB_VIDEO_NODE_ID, "fieldName": A.RUNNINGHUB_VIDEO_FIELD, "fieldValue": "api/drive.mp4"},
        {"nodeId": A.RUNNINGHUB_VIDEO_NODE_ID, "fieldName": "force_rate", "fieldValue": "24"},
        {"nodeId": A.RUNNINGHUB_VIDEO_NODE_ID, "fieldName": "skip_first_frames", "fieldValue": "48"},
        {"nodeId": A.RUNNINGHUB_VIDEO_NODE_ID, "fieldName": "frame_load_cap", "fieldValue": "120"},
        {"nodeId": A.RUNNINGHUB_VIDEO_NODE_ID, "fieldName": "select_every_nth", "fieldValue": "2"},
    ]


def test_public_completed_job_has_preview_download_and_timing():
    job = {"id": "job", "created_at": 0, "status": "done", "gallery_key": "gallery/cloud/video.mp4"}
    public = A._runninghub_public_job(job)
    assert public["gallery_url"].endswith("gallery%2Fcloud%2Fvideo.mp4")
    assert public["download_url"].endswith("gallery%2Fcloud%2Fvideo.mp4&download=1")
    assert public["elapsed_seconds"] >= 0


def test_job_list_keeps_active_and_latest_completed_only(maker_client, monkeypatch):
    monkeypatch.setattr(A, "RUNNINGHUB_JOBS", {
        "done-old": {"id": "done-old", "user": "maker", "status": "done", "created_at": 1},
        "failed": {"id": "failed", "user": "maker", "status": "failed", "created_at": 2},
        "done-new": {"id": "done-new", "user": "maker", "status": "done", "created_at": 3},
        "running": {"id": "running", "user": "maker", "status": "running", "created_at": 4},
    })
    job_ids = [job["id"] for job in maker_client.get("/api/runninghub/jobs").get_json()["jobs"]]
    assert job_ids == ["running", "done-new"]

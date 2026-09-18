"""Focused RunningHub Cloud contract tests; all HTTP is mocked."""
import json
from io import BytesIO

import pytest

import app as A


@pytest.fixture
def users(monkeypatch):
    data = {
        "admin": {"status": "active", "role": "admin", "runninghub_plus": False},
        "maker": {"status": "active", "role": "user", "runninghub_plus": False,
                  "cloud_workflows": ["krea2_i2i_hq", "scail", "h3", "jobs"]},
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


@pytest.fixture
def admin_client(users):
    A.app.config["TESTING"] = True
    client = A.app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = "admin"
    return client


def test_credential_is_encrypted_and_masked():
    key = "rh_example_secret_1234567890"
    encrypted = A._encrypt_runninghub_key(key)
    assert encrypted != key
    assert A._decrypt_runninghub_key(encrypted) == key
    assert A._mask_runninghub_key(key).endswith("7890")


def test_only_admin_can_assign_key_without_getting_it_back(maker_client, admin_client, users):
    assert maker_client.put("/api/runninghub/settings", json={"api_key": "rh_example_secret_1234567890"}).status_code == 403
    response = admin_client.post("/api/users/maker/set-runninghub-key", json={"api_key": "rh_example_secret_1234567890", "concurrency": 2})
    body = response.get_json()
    assert response.status_code == 200
    assert "rh_example" not in json.dumps(body)
    assert A._decrypt_runninghub_key(users["maker"]["runninghub_key_enc"]).startswith("rh_example")
    assert users["maker"]["runninghub_concurrency"] == 2


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


def test_h3_submit_maps_confirmed_nodes_and_clears_unused_samples(monkeypatch):
    seen = {}

    class Response:
        ok = True
        status_code = 200
        def json(self):
            return {"taskId": "h3-task"}

    monkeypatch.setattr(A.requests, "post", lambda _url, **kwargs: (seen.update(kwargs) or Response()))
    job = {"h3_refs": {"image": [{}, {}], "video": [], "audio": [{}]},
           "h3_prompt": "test", "h3_aspect": "9:16", "h3_duration": 10}
    result = A._runninghub_submit_h3("key", job, {"image": ["one.png", "two.png"], "video": [], "audio": ["sound.mp3"]})
    values = {(item["nodeId"], item["fieldName"]): item["fieldValue"] for item in seen["json"]["nodeInfoList"]}
    assert result["taskId"] == "h3-task"
    assert values[(331, "image")] == "one.png"
    assert values[(43, "image")] == "two.png"
    assert values[(19, "image")] == "None"
    assert values[(27, "video")] == ""
    assert values[(48, "audio")] == "sound.mp3"
    assert values[(14, "audio")] == "None"


def test_h3_defaults_to_standard_instance():
    assert A.RUNNINGHUB_H3_INSTANCE == "default"


def test_krea_lora_registry_normalizes_paths_and_one_default():
    data = A._normalize_runninghub_loras([{"id": "sophie", "name": "Sophie", "versions": [
        {"id": "v1", "label": "V1", "filename": r"models\loras\Sophie-v1.safetensors", "default": True},
        {"id": "v3", "label": "V3", "filename": "models/loras/Sophie-v3.safetensors", "default": True},
    ]}])
    assert [v["filename"] for v in data[0]["versions"]] == ["Sophie-v1.safetensors", "Sophie-v3.safetensors"]
    assert [v["default"] for v in data[0]["versions"]] == [True, False]


def test_krea_submit_maps_published_nodes_and_selected_lora(monkeypatch):
    seen = {}

    class Response:
        ok = True
        status_code = 200
        def json(self):
            return {"taskId": "krea-task"}

    monkeypatch.setattr(A.requests, "post", lambda url, **kwargs: (seen.update(url=url, **kwargs) or Response()))
    job = {"krea_prompt": "portrait prompt", "krea_width": 1080, "krea_height": 1920,
           "krea_lora_filename": "Sophie-v3.safetensors", "krea_denoise": 0.64}
    result = A._runninghub_submit_krea2("key", job, "api/source.png")
    values = {(item["nodeId"], item["fieldName"]): item["fieldValue"] for item in seen["json"]["nodeInfoList"]}
    assert result["taskId"] == "krea-task"
    assert values[(33, "image")] == "api/source.png"
    assert values[(5, "text")] == "portrait prompt"
    assert values[(13, "width")] == "1080"
    assert values[(13, "height")] == "1920"
    assert values[(46, "lora_name")] == "Sophie-v3.safetensors"
    assert values[(4, "denoise")] == "0.64"
    assert (1, "denoise") not in values
    state = json.loads(values[(46, "LoraLoaderState")])
    assert state["loras"] == [{"name": "Sophie-v3.safetensors", "on": True, "sm": 1, "sc": 1, "triggers": []}]


def test_krea_job_rejects_out_of_range_denoise(maker_client, users):
    users["maker"]["runninghub_key_enc"] = A._encrypt_runninghub_key("rh_example_secret_1234567890")
    response = maker_client.post("/api/runninghub/krea2/jobs", data={
        "denoise": "1.2",
        "image": (BytesIO(b"fake-image"), "source.png"),
    })
    assert response.status_code == 400
    assert response.get_json()["error"] == "Denoise must be a number from 0 to 1."


def test_public_completed_job_has_preview_download_and_timing():
    job = {"id": "job", "created_at": 0, "status": "done", "gallery_key": "gallery/cloud/video.mp4", "key_fingerprint": "secret-fingerprint"}
    public = A._runninghub_public_job(job)
    assert public["gallery_url"].endswith("gallery%2Fcloud%2Fvideo.mp4")
    assert public["download_url"].endswith("gallery%2Fcloud%2Fvideo.mp4&download=1")
    assert public["elapsed_seconds"] >= 0
    assert "key_fingerprint" not in public


def test_job_list_keeps_active_and_compact_recent_history(maker_client, monkeypatch):
    monkeypatch.setattr(A, "RUNNINGHUB_JOBS", {
        "done-old": {"id": "done-old", "user": "maker", "status": "done", "created_at": 1},
        "failed": {"id": "failed", "user": "maker", "status": "failed", "created_at": 2},
        "done-new": {"id": "done-new", "user": "maker", "status": "done", "created_at": 3},
        "running": {"id": "running", "user": "maker", "status": "running", "created_at": 4},
    })
    job_ids = [job["id"] for job in maker_client.get("/api/runninghub/jobs").get_json()["jobs"]]
    assert job_ids == ["running", "done-new", "failed", "done-old"]


def test_dispatch_serializes_jobs_with_same_key(monkeypatch):
    started = []
    class Thread:
        def __init__(self, target, args, daemon): self.args = args
        def start(self): started.append(self.args[0])
    monkeypatch.setattr(A.threading, "Thread", Thread)
    monkeypatch.setattr(A, "_save_runninghub_jobs", lambda: None)
    monkeypatch.setattr(A, "RUNNINGHUB_JOBS", {
        "active": {"id": "active", "status": "running", "key_fingerprint": "same", "key_concurrency": 1, "created_at": 1},
        "next": {"id": "next", "status": "waiting", "key_fingerprint": "same", "key_concurrency": 1, "created_at": 2},
        "other": {"id": "other", "status": "waiting", "key_fingerprint": "different", "key_concurrency": 1, "created_at": 3},
    })
    A._runninghub_dispatch()
    assert started == ["other"]
    assert A.RUNNINGHUB_JOBS["next"]["status"] == "waiting"


def test_cancel_calls_runninghub_cancel_contract(monkeypatch):
    seen = {}

    class Response:
        ok = True
        status_code = 200
        def json(self):
            return {"code": 0, "msg": "success"}

    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(A.requests, "post", fake_post)
    A._runninghub_cancel("rh-secret", "task-123")
    assert seen["url"] == "https://www.runninghub.ai/task/openapi/cancel"
    assert seen["json"] == {"apiKey": "rh-secret", "taskId": "task-123"}
    assert seen["headers"]["Authorization"] == "Bearer rh-secret"


def test_owner_can_cancel_waiting_job_without_provider_call(maker_client, monkeypatch):
    monkeypatch.setattr(A, "_save_runninghub_jobs", lambda: None)
    monkeypatch.setattr(A, "_runninghub_dispatch", lambda: None)
    monkeypatch.setattr(A, "_runninghub_cleanup_uploads", lambda _job: None)
    monkeypatch.setattr(A, "RUNNINGHUB_JOBS", {
        "waiting": {"id": "waiting", "user": "maker", "workflow_key": "h3",
                    "status": "waiting", "created_at": 1}
    })
    response = maker_client.post("/api/runninghub/jobs/waiting/cancel")
    assert response.status_code == 200
    assert response.get_json()["status"] == "cancelled"
    assert A.RUNNINGHUB_JOBS["waiting"]["status"] == "cancelled"


def test_active_workflow_detection_is_scoped_per_user_and_workflow(monkeypatch):
    monkeypatch.setattr(A, "RUNNINGHUB_JOBS", {
        "h3": {"id": "h3", "user": "maker", "workflow_key": "h3", "status": "running"},
        "scail": {"id": "scail", "user": "other", "workflow_key": "scail", "status": "waiting"},
    })
    with A.RUNNINGHUB_JOBS_LOCK:
        assert A._runninghub_has_active_locked("maker", "h3") is True
        assert A._runninghub_has_active_locked("maker", "scail") is False

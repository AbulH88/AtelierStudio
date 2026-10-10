import json

import pytest

import app as A


MODELS = ("intorealismKrea2_FlashV1.safetensors", "lustifyNSFWCheckpoint_v10Krea2.safetensors")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(A, "load_users", lambda: {"maker": {
        "status": "active", "role": "user", "cloud_workflows": ["krea2_realism", "jobs"]}})
    monkeypatch.setattr(A, "RUNNINGHUB_JOBS", {})
    monkeypatch.setattr(A, "_save_runninghub_jobs", lambda: None)
    monkeypatch.setattr(A, "_runninghub_dispatch", lambda: None)
    monkeypatch.setattr(A, "_runninghub_user_settings", lambda _user: {
        "configured": True, "key_enc": "encrypted", "key_fingerprint": "fp", "concurrency": 1})
    monkeypatch.setattr(A, "_resolve_runninghub_lora", lambda *_args: {
        "filename": "Character.safetensors", "character_id": "char", "character_name": "Character",
        "version_id": "v1", "version_label": "V1", "trigger_words": "character"})
    c = A.app.test_client()
    with c.session_transaction() as session:
        session["user"] = "maker"
    return c


@pytest.mark.parametrize("model", MODELS)
def test_realism_job_persists_model_and_source_defaults(client, model):
    response = client.post("/api/runninghub/krea2-realism/jobs", data={
        "prompt": "portrait", "model": model, "resolution_key": "workflow_default"})
    assert response.status_code == 202
    job = A.RUNNINGHUB_JOBS[response.get_json()["id"]]
    assert job["workflow_key"] == "krea2_realism"
    assert job["workflow_id"] == "2108901395561816066"
    assert job["krea_model"] == model
    assert (job["krea_width"], job["krea_height"]) == (1280, 1728)
    assert job["krea_helpers"] == []
    assert job["krea_prompt"] == "character, portrait"


def test_realism_rejects_arbitrary_model(client):
    response = client.post("/api/runninghub/krea2-realism/jobs", data={
        "prompt": "portrait", "model": "Other.safetensors", "resolution_key": "workflow_default"})
    assert response.status_code == 400
    assert not A.RUNNINGHUB_JOBS


def test_realism_is_independently_permission_gated(client, monkeypatch):
    monkeypatch.setattr(A, "load_users", lambda: {"maker": {
        "status": "active", "role": "user", "cloud_workflows": ["krea2_t2i"]}})
    assert client.post("/api/runninghub/krea2-realism/jobs").status_code == 403


@pytest.mark.parametrize("model", MODELS)
def test_realism_submission_maps_source_nodes_without_changing_sampling(monkeypatch, model):
    seen = {}

    class Response:
        ok = True
        def json(self):
            return {"taskId": "realism-task"}

    monkeypatch.setattr(A.requests, "post", lambda url, **kwargs: (
        seen.update(url=url, **kwargs) or Response()))
    job = {"krea_prompt": "portrait", "krea_model": model, "krea_width": 1280,
           "krea_height": 1728, "krea_batch_size": 1, "krea_seed": 42,
           "krea_lora_filename": "Character.safetensors"}
    assert A._runninghub_submit_krea2_realism("key", job)["taskId"] == "realism-task"
    assert seen["url"].endswith("/run/workflow/2108901395561816066")
    values = {(n["nodeId"], n["fieldName"]): n["fieldValue"] for n in seen["json"]["nodeInfoList"]}
    assert values[(541, "unet_name")] == model
    assert values[(500, "text")] == "portrait"
    assert values[(508, "width")] == "1280"
    assert values[(508, "height")] == "1728"
    assert values[(508, "batch_size")] == "1"
    assert values[(504, "seed")] == "42"
    assert values[(538, "lora_name")] == "Character.safetensors"
    assert len(json.loads(values[(538, "LoraLoaderState")])["loras"]) == 1
    assert not any(n["fieldName"] in {"steps", "cfg", "denoise"} or n["nodeId"] == 539
                   for n in seen["json"]["nodeInfoList"])


def test_realism_config_exposes_only_allowed_models(client):
    r = client.get("/api/runninghub/krea2-realism/config")
    assert r.status_code == 200
    assert [m["filename"] for m in r.get_json()["models"]] == list(MODELS)


def test_realism_worker_imports_images_and_completes(client, monkeypatch):
    job = {"id": "real", "user": "maker", "workflow_key": "krea2_realism",
           "status": "queued", "task_id": "rh-real", "key_enc": "encrypted"}
    A.RUNNINGHUB_JOBS["real"] = job
    monkeypatch.setattr(A, "_decrypt_runninghub_key", lambda _key: "key")
    monkeypatch.setattr(A, "_runninghub_query", lambda *_args: {
        "status": "SUCCESS", "results": [{"outputType": "png", "url": "https://example.test/image.png"}]})
    monkeypatch.setattr(A, "_runninghub_import_result", lambda _job, _result: {
        "gallery_key": "gallery/Realism/01.png"})
    A._runninghub_run("real")
    assert job["status"] == "done"


def test_realism_imports_all_images_into_gallery_folder(monkeypatch, tmp_path):
    uploads = []

    class Response:
        def raise_for_status(self):
            pass
        def iter_content(self, _size):
            yield b"image-bytes" * 200

    monkeypatch.setattr(A.requests, "get", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(A.r2_store, "create_folder", lambda _folder: None)
    monkeypatch.setattr(A.r2_store, "upload", lambda path, key: uploads.append(key))
    monkeypatch.setattr(A, "_set_media_creator", lambda *_args: None)
    result = A._runninghub_import_result({"id": "real", "workflow_key": "krea2_realism",
        "user": "maker", "krea_character_name": "Character", "created_at": 1}, {
        "results": [{"nodeId": "544", "outputType": "png", "url": "https://example.test/1.png"},
                    {"nodeId": "544", "outputType": "png", "url": "https://example.test/2.png"}]})
    assert len(uploads) == 2
    assert result["gallery_keys"] == uploads
    assert uploads[0].endswith('/01.png') and uploads[1].endswith('/02.png')


def test_realism_submission_worker_uses_new_workflow(client, monkeypatch):
    client.post("/api/runninghub/krea2-realism/jobs", data={
        "prompt": "portrait", "model": MODELS[1], "resolution_key": "workflow_default"})
    job = next(iter(A.RUNNINGHUB_JOBS.values()))
    seen = []
    monkeypatch.setattr(A, "_decrypt_runninghub_key", lambda _key: "key")
    monkeypatch.setattr(A, "_runninghub_submit_krea2_realism", lambda _key, j: (
        seen.append(j["krea_model"]) or {"taskId": "realism-task"}))
    monkeypatch.setattr(A, "_runninghub_query", lambda *_args: {"status": "SUCCESS"})
    monkeypatch.setattr(A, "_runninghub_import_result", lambda *_args: {"gallery_key": "gallery/test.png"})
    A._runninghub_run(job["id"])
    assert seen == [MODELS[1]]
    assert job["status"] == "done" and job["task_id"] == "realism-task"

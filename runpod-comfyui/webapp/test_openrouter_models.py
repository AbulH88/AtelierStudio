"""Contract tests for Atelier's curated OpenRouter vision-model list."""
from pathlib import Path

import app as A


EXPECTED_MODEL_IDS = [
    "qwen/qwen3.8-27b",
    "qwen/qwen3.8-27b:free",
    "x-ai/grok-4.6",
    "z-ai/glm-5.3-flash",
    "google/gemini-3.8-flash",
    "deepseek/deepseek-v4.1-flash",
]


def test_curated_openrouter_models_and_default(monkeypatch):
    assert A.OPENROUTER_MODEL == EXPECTED_MODEL_IDS[0]
    assert [model["id"] for model in A.VISION_MODELS] == EXPECTED_MODEL_IDS

    monkeypatch.setattr(A, "load_users", lambda: {
        "tester": {"status": "active", "role": "user"},
    })
    client = A.app.test_client()
    with client.session_transaction() as session:
        session["user"] = "tester"
    response = client.get("/api/openrouter/models")
    assert response.status_code == 200
    assert [model["id"] for model in response.get_json()["models"]] == EXPECTED_MODEL_IDS


def test_initial_html_fallbacks_use_the_default_model():
    html = Path(A.__file__).with_name("index.html").read_text(encoding="utf-8")
    fallback = '<option value="qwen/qwen3.8-27b">Qwen 3.8 27B (default · balanced)</option>'
    assert html.count(fallback) == 2
    assert "qwen/qwen3-vl-235b-a22b-instruct" not in html

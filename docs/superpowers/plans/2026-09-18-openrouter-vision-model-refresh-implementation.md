# OpenRouter Vision Model Refresh Implementation Plan

**Goal:** Replace Atelier Studio's stale OpenRouter vision choices with the six-model curated list approved in the design.

**Design:** `docs/superpowers/specs/2026-09-18-openrouter-vision-model-refresh-design.md`

## Tasks

1. Update `OPENROUTER_MODEL` and `VISION_MODELS` in `runpod-comfyui/webapp/app.py`.
2. Update the Local Studio and Cloud Studio initial HTML fallbacks in `runpod-comfyui/webapp/index.html`.
3. Update the documented environment default in `runpod-comfyui/webapp/.env.example`.
4. Add a focused test that locks the exact IDs, order, default, API response, and HTML fallbacks.
5. Run Python compilation, focused tests, and inline JavaScript syntax validation.


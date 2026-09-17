# OpenRouter Vision Model Refresh Design

Date: 2026-09-18

## Goal

Replace Atelier Studio's outdated curated OpenRouter vision-model choices with a small, current list suited to the Describe with AI workflow. Keep the selector predictable rather than exposing OpenRouter's full catalog.

## Curated models

The selector will contain exactly these models, in this order:

1. `qwen/qwen3.8-27b` — Qwen 3.8 27B; default balanced model.
2. `qwen/qwen3.8-27b:free` — Qwen 3.8 27B Free; availability may fluctuate.
3. `x-ai/grok-4.6` — Grok 4.6; premium, less-filtered alternative.
4. `z-ai/glm-5.3-flash` — GLM 5.3 Flash; inexpensive alternative.
5. `google/gemini-3.8-flash` — Gemini 3.8 Flash; SFW-focused option.
6. `deepseek/deepseek-v4.1-flash` — DeepSeek V4.1 Flash; inexpensive native-vision option.
7. `openai/gpt-5.6-luna` — GPT-5.6 Luna; SFW/OpenAI option for general image descriptions.

The application default will change from `qwen/qwen3-vl-235b-a22b-instruct` to `qwen/qwen3.8-27b`. Existing stale entries will be removed rather than retained as legacy choices.

## Implementation

- Update the server-side `OPENROUTER_MODEL` fallback and `VISION_MODELS` list in `runpod-comfyui/webapp/app.py`.
- Update the initial fallback options in both Local Studio and Cloud Studio in `runpod-comfyui/webapp/index.html`. The API-populated list remains authoritative after page load.
- Update `runpod-comfyui/webapp/.env.example` to show the new default.
- Keep the current static curated-list architecture. Do not fetch or expose the full OpenRouter catalog to users.
- Preserve the existing request format, API endpoint, prompt construction, and API-key handling.

## Labels and safety

Labels will communicate cost/availability and the known intended role of each option without claiming guaranteed moderation behavior. Provider-side safety behavior can change and must not be treated as an application guarantee. Gemini and GPT-5.6 Luna remain labeled as SFW-focused; the other models are alternatives for the existing body-description workflow.

## Validation

- Add focused tests asserting the exact model IDs, order, and default.
- Assert that removed stale models are absent from the curated API response.
- Run Python compilation and the focused webapp test suite.
- Syntax-check the inline JavaScript in `index.html`.
- A live description smoke test is optional because it requires a configured OpenRouter key and incurs external usage; static validation must not make paid calls.

## Non-goals

- Automatically synchronizing every vision-capable OpenRouter model.
- Adding image-generation, batch-only, safety-only, experimental, or contributor-tier models.
- Changing Describe with AI prompts or moderation behavior.
- Benchmarking model output quality in this change.

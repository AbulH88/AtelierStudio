# Plan: Replace on-GPU QwenVL with an OpenRouter vision "describe image" step

> Status: **APPROVED, not yet implemented.** This is the NEXT task (do before RunPod).
> Prerequisite: an **OpenRouter API key** from the user (openrouter.ai → Keys) → `.env`.

## Context
Today **Video→Character (i2i)** uses an on-GPU vision model (`AILab_QwenVL_Advanced`,
~9 GB + a custom node) to caption the chosen frame, and **Text→Character (t2i)** has no
image-describe option. Goal:
1. Drop QwenVL; instead call a cheap/free **OpenRouter vision model** to describe an image.
2. Steer the description with **parameters** (style preset, body shape, clothing).
3. **Editable prompt** in both modes (describe → tweak → generate).

Big win: removes the 9 GB QwenVL model **and** its custom node from the RunPod footprint
(smaller volume, simpler Dockerfile, faster cold start) — that's why it's done before
RunPod. Description is computed in the **app backend** (VPS has internet + the key), so
the ComfyUI worker (local or cloud) just receives a ready-made prompt; it never needs
QwenVL or OpenRouter.

## Decisions (confirmed with user)
- Parameter controls: **Style preset** (Amateur / Cinematic / Editorial / Studio),
  **Body shape** (toggle → appends emphasis tags), **Clothing note** (text field).
- **Identity exclusion is always-on** (baked into the instruction; the LoRA handles
  face/hair) — not a toggle. No free-text "extra notes" field.
- **Editable prompt box in both modes**; a "Describe with AI" button fills it from the
  image/frame + params; user can edit before Develop.
- **T2I gets a Text / Image input toggle**: *Text* (default) = type the prompt directly;
  *Image* = upload → "Describe with AI" → editable prompt. Image path is optional/off by default.
- **I2I (video→character): just swap QwenVL → OpenRouter** to describe the picked frame;
  keep the existing flow (frame stays the I2I latent reference).
- **OpenRouter model selector**: a UI dropdown of OpenRouter's **vision-capable** models
  (fetched live, filtered to image-input); chosen model sent with each describe request.
  Default `google/gemini-2.0-flash-exp:free`.

## Approach
Describe happens in `webapp/app.py` via OpenRouter BEFORE building the ComfyUI graph.
The resulting text (+ `ing2lorance` trigger) becomes the positive prompt. Workflows
become pure text→image (i2i keeps the frame only as the I2I latent reference).

## Files to change

### 1. `runpod-comfyui/workflow_i2i.json`
- **Remove node `2`** (`AILab_QwenVL_Advanced`) and node `4` (`StringConcatenate`).
- Node `5` (positive `CLIPTextEncode`) `inputs.text` → a **literal string** (handler sets)
  instead of `["4",0]`.
- Keep `1` (LoadImage) → `20` (ImageResizeKJv2) → `21`/`22` (VAEEncode) — frame is still
  the I2I reference. Everything else unchanged.

### 2. `runpod-comfyui/comfy_common.py`
- `I2I` map: drop `qwen`/`face_concat`; add `positive: "5"`.
- `_build_i2i`: `graph["5"].inputs.text = FACE_PREFIX + inp.get("prompt","")`; remove the
  QwenVL `custom_prompt`/`caption_prompt` handling.
- `_build_t2i`: already uses `inp["prompt"]` — no change. `generate()`/`run()` unchanged.

### 3. `webapp/app.py`
- Env: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (default `google/gemini-2.0-flash-exp:free`).
- `_describe_instruction(params)`: builds instruction from style/body/clothing + always-on
  "describe pose, clothing, setting in one paragraph; ignore face/hair/identity/text/logos."
- `describe_image(image_b64, params, model) -> str`: POST `https://openrouter.ai/api/v1/chat/completions`
  with chosen `model` + `messages:[{role:user, content:[{type:text,text:instruction},
  {type:image_url,image_url:{url:"data:image/jpeg;base64,..."}}]}]`; return `choices[0].message.content`.
- `POST /api/describe`: `{params, model}` + uploaded image OR `{session, frame}` → `{prompt}`.
- `GET /api/openrouter/models`: fetch `/api/v1/models`, filter vision (`"image"` in
  `architecture.input_modalities`), return `[{id,name}]` (cached). Powers the dropdown.
- `_build_input`: both modes set `inp["prompt"]` from the (edited) box. i2i empty-box →
  auto-describe the frame (selected model). Remove `caption_prompt`.

### 4. `webapp/index.html`
- Options: **Style preset** dropdown, **Body shape** toggle, **Clothing note** field,
  **OpenRouter model** dropdown (from `/api/openrouter/models`). Remove `#captionField`.
- **T2I:** Text / Image input toggle. Text (default) = `#prompt`; Image = upload +
  "Describe with AI" → fills `#prompt`.
- **I2I:** editable prompt textarea + "Describe with AI" (describes picked frame). Empty →
  auto-describe on Develop. All describe calls send params + model.

### 5. `webapp/.env.example` (+ live VPS `.env`)
- `OPENROUTER_API_KEY=` and `OPENROUTER_MODEL=google/gemini-2.0-flash-exp:free`.

### 6. `runpod-comfyui/Dockerfile`
- Remove the `ComfyUI-QwenVL-Mod` clone/install (lighter cloud image).

## Reuse (don't reinvent)
- `comfy_common._set_lora`, `generate`, `run`. `app.py` `_build_input`, `/api/generate`,
  `FRAMES_DIR`, base64 handling; the helper-toggle + range-input UI patterns in `index.html`.

## Verification
1. Set `OPENROUTER_API_KEY` in `webapp/.env`; start local ComfyUI + app.
2. T2I: upload image → Describe → edit → Develop → clean image; also manual-prompt works.
3. I2I: pick frame → Describe → Develop; also empty-box auto-describe fallback.
4. ComfyUI logs show no QwenVL load for i2i. Toggling Style/Body/Clothing changes output.
5. Deploy to VPS (`/root/atelier` + `webapp`), `systemctl restart atelier`, set VPS `.env`
   key, retest on https://studio.thecristinaadam.com. Commit to `main` + push.

---

## After this: RunPod (planned, see below)
Bring cloud online so the **Cloud** toggle works. Decisions to confirm at that time:
- **Scope:** T2I first (~45 GB models, no QwenVL now) then I2I; or both.
- **GPU:** L40S 48 GB (High stock, ~$1.90/hr) recommended; A40 48 GB cheaper but Medium stock.
- **Image build:** RunPod builds from GitHub repo `AbulH88/AtelierStudio`
  (Dockerfile `runpod-comfyui/Dockerfile`) — simplest; or Docker Hub.
- **Models:** Network volume (~$5/mo). Public models (Wan, umt5, VAE, lightx2v) download
  from HuggingFace onto the volume via a temp pod; private character LoRAs upload from
  `H:\ConfiuiModels`.
- Need a **RunPod API key** → VPS `.env` (`RUNPOD_API_KEY` + `RUNPOD_ENDPOINT_ID`).
- RunPod MCP is connected; I can create volume/endpoint/test jobs. Account is empty
  (no volumes/endpoints yet).

## Also pending (raised by user): a VIDEO-gen workflow
User has a 1 video-gen wf to add. Decide **local-only vs cloud-too** — it changes RunPod
sizing (bigger GPU + ~56 GB video models). Recommended order: add it to the app (local)
to lock the full model list, THEN do RunPod once. Get the wf JSON + input/output spec.

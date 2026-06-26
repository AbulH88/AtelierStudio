# INSTARAW Advanced Mode — v1 Plan

Goal: add the user's **INSTARAW WAN 2.2 V2.0** workflow as a new **Local-only** app mode —
an "advanced" t2i+i2i that produces fully-detailed, authenticity-processed character images.
Single workflow handles BOTH t2i and i2i via an internal toggle (node `576`).

Decisions locked (this session):
- **Keep the in-workflow LLM prompt-gen** (node `584` `INSTARAW_RealityPromptGenerator`) — the
  app drives ITS inputs; it does NOT inject CLIP text into `29`/`30`.
- **Full pipeline** — base WAN gen + SDXL detailer suite + authenticity/EXIF post.
- **Character picker wired** — parameterize the rgthree LoRA stacks (`287`/`256`), replacing the
  hardcoded Hazil.

All **app-side + a new `workflow_adv.json`** (the export, cleaned). No worker-image rebuild
(cloud doesn't have the INSTARAW pack — this mode is Local-only, runs on the home 5090).

---

## What the workflow does (node map)

**Controls / entry**
- `576` `PrimitiveBoolean` "ENABLE IMG TO IMG?" → **t2i/i2i toggle**
- `523` `INSTARAW_WANAspectRatio` ("3:4 Portrait") → **dimensions**
- `581` `LoadImage` "CHARACTER REF" → **character reference photo** (feeds `584`)
- `583` `INSTARAW_AdvancedImageLoader` → **i2i source image** (batch loader; `enable_img2img`←`576`)
- `584` `INSTARAW_RealityPromptGenerator` → LLM builds **pos/neg/seed** from `trigger_word` +
  `prompt_batch_data` (JSON) + `character_image` + API keys. Outputs → `29`/`30` (CLIP) + seed.

**Base generation (WAN 2.2 T2V)**
- `92`/`97` = T2V **low/high-noise BF16**; `287` (low) / `256` (high) = rgthree **Lora Stacks**:
  slot01 = **character LoRA (Hazil, hardcoded)**, slot02 = lightx2v lightning @0.6, slot03 = Lenovo @0.6.
- `515` KSampler (2-step) → `41`/`42`/`202` ClownsharKSampler (RES4LYF) with `36`/`203` latent upscales → decode `93`.

**SDXL detailer suite** (checkpoint `116` bigLust + per-part LoRAs/prompts)
- `127` face → `501` eyes → `141` hands → `140` nipples → `147` pussy → `142` feet → `171` lips. (NSFW detailers.)
- Plus `218` Ultimate SD Upscale (4x-UltraSharpV2).

**Authenticity / anti-detection post**
- `171` → `543` Color-Science LUT (`natural_look.cube`) → `537` GLCM normalize → `548` realistic noise
  → `533` pixel perturb → `551` multi-compression → `402` **Synthesize fake EXIF** (iphone_12).
- Saves: `402` (with metadata) + `613` `SaveImage` (of `171`, pre-authenticity).

**Required custom packs (must exist on local ComfyUI):** ~24 `INSTARAW_*` nodes, RES4LYF
(ClownsharKSampler), Impact (FaceDetailer/Ultralytics/SAM/MediaPipe-SEGS), rgthree, JPS,
controlnet_aux MediaPipe, APersonMaskGenerator, UltimateSDUpscale.

---

## Interactive popups — KEEP them (image picker + mask editor)

The user wants the two human-in-the-loop nodes surfaced in the app (NOT bypassed):
- `344` `INSTARAW_ImageFilter` — pick which of the generated batch to proceed with. Sits in the
  **main path** (`93`→`477`→**`344`**→`590`→`127` FaceDetailer).
- `285` `INSTARAW_MaskImageFilter` — paint a mask. Feeds the mask path (`285`→`288`→`211`/`498`).

**Protocol (from the INSTARAW source — authoritative):**
- The node blocks server-side in `send_and_wait` and **broadcasts a WS event** `"instaraw-interactive-images"`
  to all connected clients: `{uid, unique, urls:[{filename,subfolder,type}], ...}` —
  `maskedit:true` for `285`; `allsame`/`video_frames` for `344`. Re-broadcasts `{tick}` every 0.5s,
  `{timeout:true}` on expiry (default 600s).
- The client replies via `POST {COMFY}/instaraw/interactive_message`, form field `response` = JSON:
  - picker → `{unique, selection:[indices], extras?}`
  - mask   → `{unique, masked_data:"data:image/png;base64,…", extras?}` (alpha channel = painted mask)
  - control → `{unique, special:"-3"}` cancel / `"-1"` reshow.
- `unique` = the node's `node_identifier` (`344`→`958955`, `285`→`623902`; already in the graph).
- Single-flight: one interaction at a time (global `MessageState`); node always re-runs (`IS_CHANGED`).
  `cache_behavior` can replay a prior selection/mask — default to "Run … normally" so it always prompts.

**Constraint — WS dies over the Cloudflare tunnel** (already true for progress: the VPS polls the
home agent's `/progress` because "WS through the tunnel 502s"). The popup arrives ONLY as a WS
broadcast, so the **home agent** (local to ComfyUI) is the only place that can catch it. The agent's
`_ws_loop` already receives every message — add one event handler.

**Data flow:** ComfyUI(home) –WS→ home agent (catch event, fetch preview via local `/view`, hold
`PENDING`) → VPS proxies → browser modal → user picks/paints → VPS → agent → `POST
/instaraw/interactive_message` (local) → ComfyUI unblocks → gen continues.

**Build:**
1. **`home_agent/agent.py`**: handle `type=="instaraw-interactive-images"` in `_ws_loop` — store
   `{uid, unique, maskedit, images:[b64]}` (fetch `urls` from local ComfyUI `/view`). Clear on
   timeout/response. Add `GET /interaction` (secret-gated) + `POST /interact` (forwards
   `{unique, selection|masked_data|special}` to ComfyUI locally).
2. **VPS `app.py`**: `GET /api/generate/result` also returns `pending_interaction` (proxied from
   agent `/interaction`); new `POST /api/generate/interact` → agent `/interact`. Local-dev branch
   talks to ComfyUI directly (mirror the existing `AGENT_URL` split).
3. **`index.html`**: when a poll carries `pending_interaction`, open the modal —
   **image picker** (selectable thumbnail grid → `selection`) or **mask editor** (brush canvas over
   the preview, export PNG with alpha=mask → `masked_data`). The brush-canvas editor is the only
   substantial new UI; reuse the lightbox/gallery styling for the grid.

## Other blockers to handle at graph-build time

1. **In-workflow API keys** — node `580` holds a **LEAKED OpenRouter key** and `579` a Gemini slot.
   `_build_adv` must inject the app's `OPENROUTER_API_KEY` (env) into `580` and clear the leaked
   literal. (Add the leaked key to the rotation list in HANDOFF.)

3. **Character LoRA hardcoded** (`287`/`256` slot01 = Hazil) — set slot01 `lora_01`/`strength_01`
   from the app's character picker in BOTH stacks.

4. **i2i = image-guided prompting, NOT latent img2img** — ✅ RESOLVED (see Image-input section).
   No VAEEncode; sampler always uses empty latent `407`; source images only steer prompt gen.
   Decision: keep as-is. No graph change.

5. **Final-image return** — app `run()` pulls images from `/history` outputs. With full pipeline the
   true final pixels are `551` (saved by `402` with EXIF). Confirm `402` emits an output to
   `/history`; if not, add/ensure a `SaveImage` on `551` so the gallery gets the authenticity-processed
   image (not the pre-authenticity `171`/`613`).

---

## Prompt Studio — replicate their UI, reuse their engine (LOCKED)

The fancy RPG panel does NOT compute anything at run-time. Node `584`'s Python (`execute`) is
deterministic: it takes `prompt_batch_data` (JSON list of finished `{positive_prompt,
negative_prompt, tags, seed, repeat_count}`), expands by repeat, prepends `trigger_word`, returns
the lists. **All intelligence lives in 3 ComfyUI HTTP endpoints** (`creative_api.py`), which we reuse:
- `POST /instaraw/generate_creative_prompts` — the AI generator. Body: `generation_count, is_sdxl,
  model, gemini/grok/openrouter keys, temperature, top_p, character_description,
  use_character_likeness, generation_mode, images[], multi_images[], affect_elements[] (expressions),
  random_inspiration_prompts[], user_text_input, generation_style, source_prompts[],
  inspiration_count, character_reference, system_prompt`.
- `POST /instaraw/generate_character_description` — "Generate from image" (image → character desc).
- `POST /instaraw/get_random_prompts` — library inspiration: `{count, filters}` → random sample.
- Prompt DB = remote file `https://instara.s3.us-east-1.amazonaws.com/prompts.db.json` (~22MB),
  loaded+cached by ComfyUI. We do NOT host it.

**Decisions:** reuse the engine (call the 3 endpoints; full feature parity, no DB to host) AND
**replicate their UI design** (dark violet studio — `#a78bfa/#8b5cf6/#6366f1`, 135° brand gradient,
Inter + Monaco, 4px radii, section cards, expression chips, generation-batch cards), rendered in the
Atelier app. v1 = full studio (model settings, character consistency, expression grid, library
inspiration, batch cards). Mockup approved this session.

**Build:**
- **app.py** proxy endpoints → forward to ComfyUI's 3 `/instaraw/*` routes (HTTP works through the
  tunnel; inject our OpenRouter key; rotate the leaked one). The browser never holds the key.
- **index.html** Prompt Studio panel (the recreated design); its buttons call the proxies; the
  resolved prompt cards become `prompt_batch_data` sent to node `584` at gen time.
- Confirm the 3 endpoints' exact response shapes in `creative_api.py` before wiring (impl detail).
- Home ComfyUI must be running (true for Local mode anyway).

## Image input / i2i — Advanced Image Loader (node 583)

TWO distinct image inputs (don't conflate):
- **Character reference** (`581`) — face/identity photo, used always (t2i+i2i), fed to `584` for
  consistency. = the app's character-ref concept.
- **i2i source batch** (`583` `INSTARAW_AdvancedImageLoader`) — the images to transform; only when
  the **Enable img2img** toggle (`576`) is on.

`583` is a batch builder driven by hidden `batch_data` JSON + the `576` toggle:
- **i2i (576=true):** `batch_data = {images:[{id,filename,original_name,width,height,thumbnail,
  repeat_count}], order:[...]}`. Images upload via `POST /instaraw/batch_upload` (multipart field
  `files`) → saved to ComfyUI `input/INSTARAW_ImagePool/`, returns the meta. Loader resizes to the
  aspect target (`resize_mode` default Center Crop), stacks a batch with per-image `repeat_count`.
- **t2i (576=false):** same panel builds EMPTY latents — `batch_data = {latents:[{id,width,height,
  repeat_count,aspect_label}], order, total_count}`. I.e. it IS the variations/size builder.
- **mode** Batch Tensor (all at once) vs Sequential (one at a time, stateful). `total_count` = batch size.
- Routes also: `DELETE /instaraw/batch_delete/{node_id}/{image_id}`, `GET /instaraw/view/{filename}`.

**Build:** reuse `/instaraw/batch_upload` (HTTP, works through tunnel). App UI = the recreated loader
(drop zone → thumbnail cards w/ repeat steppers + remove + reorder; mode/resize/aspect/total). The
app assembles `batch_data` and sets `576`. Mockup approved this session.

**✅ VERIFIED (2026-06-26): there is NO latent img2img — and the user wants it kept "same as wf".**
Traced the graph: no `VAEEncode` anywhere; sampler `515` always reads the empty latent `407`
(LatentSwitch `406` `input_true` is unwired; `INSTARAW_SwitchBase` returns `input_true`=None when
`boolean`=true → so toggling `576` on would feed the sampler None). Source images (`583`) flow ONLY
to `584` (vision captioning), a preview, and a dead-end bypass (`410`). So "i2i" here = **image-guided
prompting + txt2img**, not pixel/latent transform. **Decision: replicate as-is** — generation stays
txt2img on the empty latent; uploaded images steer prompt generation (583→584). Do NOT add VAEEncode
or wire `input_true`. Keep the latent path on `407` regardless of the toggle to avoid the None-latent break.

## The prompt model for this mode

- **`trigger_word`** (`584`) = character **identity/appearance** string — constant per character
  (the export embeds a full face description). Source it per-character.
- **`prompt_batch_data`** (`584`, JSON) `positive_prompt`/`negative_prompt`/`tags`/`seed`/`repeat_count`
  = the **scene** the user wants. The app's typed prompt (or Describe-with-AI) populates this; `584`'s
  LLM enhances it. `repeat_count` = variations.
- Net: app sends **scene** + **character** + **aspect** + **t2i/i2i toggle**; `584` does the rest.

---

## Backend (comfy_common.py)

1. **`ADV` node-map** dict (like `I2I`/`T2I`/`VIDEO`): keys for `toggle`(576), `aspect`(523),
   `char_ref`(581), `i2i_src`(583), `prompt_gen`(584), `lora_low`(287), `lora_high`(256),
   `final_save`(551/402), interactive nodes (`344`,`285`,`517`).
2. **`_build_adv(graph, inp, seed, ...)`**:
   - set `576.value` = `bool(inp["img2img"])`
   - `523.aspect_ratio` from `inp` (map app width/height → INSTARAW aspect labels; e.g. 1080×1920 → "3:4 (Portrait)")
   - upload + set `581.image` (character ref) and, when img2img, `583` source image
   - `584`: `trigger_word`=character appearance, `prompt_batch_data`=built JSON from `inp["prompt"]`/
     negative/`variations`/seed, inject `OPENROUTER_API_KEY` into `580`, clear leaked literal
   - char LoRA → `287`/`256` slot01 (path+strength from picker)
   - **bypass `344`/`285`** (rewire passthrough) ; honor `517`
   - set seed across the seed-consuming nodes; ensure final SaveImage on `551`
   - `_normalize_model_paths(graph)` (Windows backslash heal — this export uses `\\`)
3. **`generate()` branch** `mode == "adv"` → load `workflow_adv.json`, `_build_adv`, run via the
   existing `run()` (image path). Variations via `prompt_batch_data.repeat_count` (no max_batch chunk,
   or chunk like the others — TBD by VRAM).

## Backend (app.py)
- `_build_input`: `mode == "adv"` branch (img2img flag, ref/src images, aspect, character appearance).
- Reuse async job system + R2 gallery save unchanged (it's an image mode).
- Validation: require character (+ source image when img2img).

## Frontend (index.html)
- New mode button in `.modes`: **"⚡ Advanced"** (`data-mode="adv"`).
- `setMode("adv")`: show character picker, scene prompt, aspect, **t2i/i2i toggle**, variations;
  hide irrelevant controls.
- **`onTargetChange`**: `adv` is **Local-only** → hide the button on Cloud (like the other image
  modes; Cloud forces Motion).
- Generate-body builder: send `mode:"adv"`, `img2img`, `prompt`, `aspect`, character fields, variations.

---

## Implementation steps
1. **Clean the export → `workflow_adv.json`**: keep API format, strip dead `rgthree_comparer`
   preview blobs/`PreviewImage`/`Image Comparer` nodes where safe, remove the leaked key literal,
   normalize `\\`→`/` paths. Keep all generation + detailer + authenticity + `584`.
2. **Confirm local ComfyUI has every custom pack** (load the graph once in the UI / API `/object_info`).
3. **comfy_common**: `ADV` map + `_build_adv` + `generate()` branch. Keep `344`/`285` active; set
   their `cache_behavior` to "Run … normally" and a generous `timeout`.
3b. **Interactive popups** — agent WS handler + `/interaction`/`/interact`, VPS proxy endpoints,
    browser picker + mask-editor modals (see "Interactive popups" section).
4. **app.py**: `adv` branch in `_build_input` + validation.
5. **index.html**: Advanced mode button + controls + t2i/i2i toggle + Local-only hide + generate body.
6. **Test on Local target**, t2i first (`576`=false), then i2i (`576`=true) — through the tunnel.

## Risks / open questions to resolve during build
- **Interactive popups round-trip**: verify the agent's local WS catches `instaraw-interactive-images`
  and that `POST /instaraw/interactive_message` (local) unblocks the node. The #1 build risk is the
  VPS↔agent↔ComfyUI relay latency/secret wiring, not the node itself.
- **Mask data format**: confirm the browser's exported PNG alpha maps to the node's expected mask
  (painted alpha=1 → mask=1, per `masked_data` path in `image_filter.py`).
- **`584` contract**: exact meaning/format of `trigger_word` vs `prompt_batch_data`, and whether it
  hard-requires `character_image` + a working OpenRouter key to emit a prompt. Inspect the node source
  or test in the canvas before wiring.
- ~~i2i source-encode path~~ — ✅ RESOLVED: no latent img2img exists; keep as image-guided prompting.
- **Final output node** — does `402` return to `/history`, or add `SaveImage(551)`?
- **Per-character appearance string** — where to store each character's `trigger_word` (a small
  map alongside the character picker / `.cloud_loras.json` equivalent for local).
- **Speed** — full detailer + upscale + authenticity is heavy; expect minutes per image on the 5090.
- ⚠️ **Rotate** the leaked OpenRouter key in node `580` (`sk-or-v1-2ecf…`).

# Krea I2I New (depth-ControlNet) mode — Design

Date: 2026-07-19
Status: Approved, not built. Source workflow:
`C:\Users\jimi\Downloads\Krea-2-Turbo_Depth-Controlnet.json`.

## Goal

Add a 6th local-only generation mode, **Krea I2I New** (`mode="krea2new"`),
wrapping a Krea2-Turbo depth-ControlNet graph. Distinct pipeline from the
existing **Krea2 I2I** mode: that one is true img2img (VAEEncode of the
resized/noised source, denoise 0.6). This one runs the source photo through
DepthAnythingV2 to get a depth map, then conditions a **full generation**
(denoise 1, KSampler from an empty latent) on that depth map via a Krea2
control-LoRA — pose/composition transfer, not pixel-level editing.

## Security

The source JSON has a live OpenRouter key baked into node 39
(`sk-or-v1-2ecfce...80749`) — same key already flagged in `HANDOFF.md` from the
original Krea2 import, still unrotated. That node is dropped entirely (see
below). Do not copy the raw JSON into the repo; only the cleaned
`workflow_krea2new.json` goes in. Rotating the key itself stays on the existing
pending-rotation list, not blocking for this feature.

## Workflow surgery

Starting from the source graph, before it becomes
`runpod-comfyui/workflow_krea2new.json`:

**Dropped nodes** (and why):
- `30` FluxResolutionNode — a fixed dropdown preset (e.g. "720×1280 (9:16) -
  Vertical HD") driving `10` EmptyLatentImage's width/height. Replaced by
  wiring `10.width`/`10.height` directly from the app's existing aspect picker
  (Portrait/Square/Landscape), same as `_build_t2i`. No new UI control needed.
- `39` OpenRouterVLMAdvanced, `40` ShowText — graph-embedded auto-caption with
  its own (leaked) API key and a hardcoded character-specific description
  ("Always Start with word cristinaDDM2M woman..."). Replaced by the app's
  existing "Describe with AI" (OpenRouter, backend-side, already used by
  T2I/I2I/Krea2). `6` CLIPTextEncode's `text` becomes a literal string the app
  sets directly (`_prompt_with_trigger`), exactly like `_build_krea2`.
- `36` PreviewImage (of `34`'s control-image output) — dev-only debug preview.
  Must be dropped: this mode's `generate()` branch calls `run()` without an
  `out_node` (same as i2i/krea2/t2i), so `run()` collects images from *every*
  node that produced one — leaving this in would add a spurious depth-map
  image to every generation's result.

**Kept, wired to per-request inputs:**
- `32` LoadImage — source image (upload or extracted frame, same plumbing as
  I2I/Krea2).
- `38` LoraLoaderModelOnly — character LoRA, same `Keara2` root/picker as the
  existing Krea2 mode (confirmed folder name, per `HANDOFF.md`).
- `10` EmptyLatentImage — width/height set from `inp["width"]`/`inp["height"]`
  (already parsed generically in `_build_input`, same source as T2I's aspect
  picker).
- `2` KSampler + `3` VAEDecode — always runs (steps 8, cfg 1, `er_sde`,
  `simple`, denoise 1 — fixed defaults from the source graph, left as workflow
  file constants; tunable later via the existing cross-mode sampler-override
  panel).
- `31` DepthAnythingV2Preprocessor, `33` Krea2ControlLoRALoader (fixed
  `depth-control-lora.safetensors`, strength 1 — not user-selectable, it's a
  technique-LoRA not an identity-LoRA), `34` Krea2ControlImageEncode
  (`resize=match_latent_size`, so the depth map auto-resizes to whatever
  aspect the user picked), `35` Krea2ControlApply — kept as-is, no per-request
  wiring needed beyond the source image already flowing through `32`.
- `37` SaveImage — the sole save node (of `3`'s decoded output). Single-image
  mode, no refine pass (unlike Krea2, this workflow ships without one — YAGNI,
  can add later if wanted).
- `4` VAELoader, `15` UNETLoader, `18` CLIPLoader — fixed model paths from the
  source graph, left as backslash paths as-is (this mode is local-only,
  same convention as `_build_krea2`, which also skips `_normalize_model_paths`
  — that guard exists for Video mode's cloud/Linux worker, where backslash
  paths actually break; the local Windows ComfyUI install handles them fine).

**Node-id map** (`comfy_common.py`, mirrors `I2I`/`T2I`/`KREA2` style):
```python
KREA2NEW = {"load_image": "32", "positive": "6", "latent": "10",
            "base_ksampler": "2", "char": "38"}
```

**`_build_krea2new(graph, inp, seed, frame_name)`**, mirroring `_build_krea2`
and `_build_t2i`:
- Set `32.image = frame_name`.
- Set `10.width = inp.get("width", 1080)`, `10.height = inp.get("height", 1920)`.
- Set `6.text = _prompt_with_trigger(inp)`.
- `2.seed = seed`.
- `_set_lora(graph, "38", inp.get("character_lora_path"), inp.get("character_strength", 1.0))`.
- `_apply_sampler_override(graph, inp)`.

**`generate()`**: add `"krea2new"` to the `mode in ("i2i", "krea2")` single
upload-once check, and an `elif mode == "krea2new": graph = _build_krea2new(...)`
branch in the existing chunk/batch loop (same `max_batch` chunking as
i2i/krea2/t2i — this mode has no batch-native node either).

## Files touched

- **New**: `runpod-comfyui/workflow_krea2new.json` (cleaned, remapped, key
  stripped, debug preview stripped).
- **`comfy_common.py`**: `KREA2NEW` map, `_build_krea2new()`, `mode=="krea2new"`
  branch in `generate()` (+ upload-once tuple).
- **`webapp/app.py`**: `krea2new` branch in `_build_input` (reuses krea2's
  image/frame source resolution; no `resize_size`/`refine`/`denoise` fields
  needed — width/height already generic), `/api/generate` mode validation
  (local-only gate + frame-exists check, mirrors `krea2`/`adv`), empty-prompt
  auto-describe tuple extended to include `krea2new`.
- **`webapp/index.html`**: new mode button (`Krea I2I New`, local-only, hidden
  on Cloud like Advanced/Krea2), reuses the shared frame-picker pane
  (`#paneVideo`) that i2i/krea2 already use, reuses the T2I aspect-ratio
  picker (already visible for this class of mode via existing `.imgonly`
  classes — no new control), reuses the Krea2 character picker
  (`S.krea2Chars`), hides Lightning/helper-LoRA controls (`.stdlora`) since
  this mode has only a single character LoRA, same as krea2/adv.
- No `Dockerfile`/worker/RunPod changes — local-only, same reasoning as Krea2
  (cloud volume holds only Motion models).

## Testing

Mirrors the existing 3-file Krea2 test convention:
- `tests/test_workflow_krea2new_file.py` — regression guard, the shipped JSON
  must never contain `sk-or-v1` / `api_key`.
- `tests/test_build_krea2new.py` — `_build_krea2new()` wiring (frame name,
  width/height, prompt, seed, character LoRA all land on the right nodes).
- `tests/test_generate_krea2new_dispatch.py` — `generate()` dispatch + the
  `/api/generate` local-only gate.

## Open items to verify during build (not blocking design)

- Confirm `Krea2ControlImageEncode`'s `resize=match_latent_size` actually
  produces a sane result when the chosen aspect ratio differs a lot from the
  source photo's native aspect (e.g. portrait source, landscape output) —
  check against a real render, note in `HANDOFF.md` if it needs a caveat.
- Rotate the leaked OpenRouter key (independent of this feature, same
  outstanding class of issue as the prior HF/RunPod/OpenRouter key rotations
  in `HANDOFF.md`).

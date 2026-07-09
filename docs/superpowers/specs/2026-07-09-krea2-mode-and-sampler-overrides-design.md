# Krea2 I2I mode + cross-mode sampler overrides — Design

Date: 2026-07-09
Status: Approved, not built. Source workflow: `C:\Users\jimi\Downloads\Krea 2 I2I (3).json`
(a Krea2-base img2img graph, distinct pipeline from the existing WAN 2.2 modes).

## Goal
1. Add a 5th local-only generation mode, **Krea2 I2I**, wrapping the user's Krea2
   workflow (true img2img: VAEEncode of a resized+noise-augmented source image,
   denoise 0.6, optional skin-detail refine pass).
2. Add an opt-in **sampler override** (cfg / sampler_name / scheduler) to every
   mode's Options rail, without touching any mode's tuned defaults unless the user
   explicitly turns it on.

## ⚠️ Security
The source JSON has a live OpenRouter key baked into node 330
(`sk-or-v1-2ecfce...`). That node is being dropped entirely (see below), but the
key must be **rotated** regardless — it was pasted into this session. Do not copy
the raw JSON into the repo; only the cleaned `workflow_krea2.json` goes in.

## Krea2 mode — workflow surgery
Starting from the source graph, before it becomes `runpod-comfyui/workflow_krea2.json`:

**Dropped nodes** (and why):
- `327` VHS_LoadVideo, `328` Image Filter, `329` Switch image — video-frame
  sourcing is already handled upstream by the app (frame extraction / reel
  picker → single `image_b64`), same as WAN I2I. After removal, `322`'s `image`
  input wires directly to `316` LoadImage's output.
- `321` ShowText, `330` OpenRouterVLMAdvanced — graph-embedded auto-caption with
  its own (leaked) API key. Replaced by the app's existing "Describe with AI"
  (OpenRouter, backend-side, already used by T2I/I2I). `314` CLIPTextEncode's
  `text` becomes a literal string the app sets directly (`_prompt_with_trigger`),
  exactly like `_build_i2i`/`_build_t2i`.
- `333`, `337`, `338` — rgthree Image Comparer ×2 + PreviewImage. Dev-only,
  matches the precedent of stripping debug nodes from `workflow_i2i.json`.

**Kept, wired to per-request inputs:**
- `316` LoadImage — source image (upload or extracted frame, same plumbing as I2I).
- `313` LoraLoaderModelOnly — character LoRA, scoped to the Krea2 LoRA folder
  (path in the source: `Keara2\CristinaCosplay\...` under UNET/CLIP loaders it's
  spelled `Kera2\...` — **verify the actual on-disk folder name** when building;
  don't assume either spelling is correct).
- `324` Int → feeds both `width` and `height` of `322` ImageResizeKJv2 (the graph
  resizes to one square-ish target). Exposed as a single "Resize target · px"
  number, default 1920 (matches source).
- `302`/`303` base KSampler + VAEDecode — always runs (steps 8, cfg 1, `er_sde`,
  `simple`, denoise 0.6). This is the primary generation pass.
- `334`/`335`/`336` refine pass (VAEEncode → KSampler steps 4/denoise 0.15/
  `res_6s`/`beta57`, fixed prompt "Natural skin textures with visible peach fuzz,
  natural shadows" → VAEDecode) — **UI toggle**, default off matches nothing-extra
  cost by default; when off these 3 nodes are removed from the graph outright
  (not bypassed) and `304` SaveImage's `images` input stays on `303`. When on,
  `304` is rewired to read from `336` instead.

**Node-id map** (`comfy_common.py`, mirrors `I2I`/`T2I`/`VIDEO`/`ADV` style):
```python
KREA2 = {"load_image": "316", "positive": "314", "negative": "305",
         "resize_size": "324", "char": "313", "base_ksampler": "302",
         "base_decode": "303", "refine_encode": "334", "refine_ksampler": "335",
         "refine_decode": "336", "save": "304"}
```

**`_build_krea2(graph, inp, seed, frame_name)`**, mirroring `_build_i2i`:
- Set `316.image = frame_name`.
- Set `324.Number = inp.get("resize_size", 1920)`.
- Set `314.text = _prompt_with_trigger(inp)` (drop 321/330 from the loaded graph).
- Rewire `322.image` to `[316, 0]` (drop 327/328/329).
- `_set_lora(graph, "313", inp.get("character_lora_path"), inp.get("character_strength", 1.0))`.
- `302.seed = seed`.
- If `inp.get("refine")`: leave `334/335/336` in place, rewire `304.images` to
  `[336, 0]`, set `335.seed = seed`. Else: pop `334/335/336/337/338` from the
  graph dict, leave `304.images = [303, 0]` (its source default).
- Drop `333` unconditionally (dev-only comparer, not part of either path).

**`generate()`**: add a `mode == "krea2"` branch parallel to the existing `i2i`
branch — same `upload_image` + chunk/batch loop as `_build_i2i` (Krea2 has no
batch-native node, so reuse the same `max_batch` chunking already used for i2i).

## Sampler override (all modes)
Resolves "nothing changes unless touched" vs "broadcast to every sampler node in
a multi-sampler mode":

- **UI**: one "Override Sampler" toggle per mode's Options rail, **off by
  default**. Reveals 3 fields when on: cfg (number + slider), sampler_name
  (editable dropdown/datalist), scheduler (editable dropdown/datalist). Fields
  pre-fill with the mode's primary sampler's current baked value as a starting
  point (convenience only — has no effect until the user actually submits with
  the toggle on).
- **Wire format**: `inp["sampler_override"] = {"cfg": float, "sampler_name": str,
  "scheduler": str}` (any subset; omit a key to leave that param alone). Absent
  entirely when the toggle is off — zero payload change for existing callers
  (e.g. the RunPod handler, which passes `event["input"]` straight through).
- **Backend**: `_apply_sampler_override(graph, inp)` in `comfy_common.py`, called
  once at the end of every mode's build function (`_build_i2i`, `_build_t2i`,
  `_build_video`, `_build_adv`, `_build_krea2`) right before it returns. Iterates
  every node in the graph, and for any node whose `class_type` contains
  `"Sampler"`, sets whichever of `cfg`/`sampler_name`/`scheduler` both (a) was
  provided in the override dict and (b) already exists as a key in that node's
  `inputs` (skips silently otherwise — e.g. `WanVideoSampler` has no
  `sampler_name`, so Video mode's override just skips that key for that node).
  This is a **broadcast** per the user's explicit choice: Advanced's 4-stage
  detailer and Krea2's refine pass will all receive the same override when the
  toggle is on. This is a known, accepted risk — documented in-app via a short
  warning under the toggle ("applies to every sampler stage in this mode,
  including detail/refine passes").
- **Datalist seed values** (known-good, pulled from the existing workflow JSONs):
  sampler_name: `res_2s`, `res_2m`, `res_6s`, `er_sde`, `exponential/res_2s`,
  `dpm++_sde`; scheduler: `simple`, `beta57`, `bong_tangent`, `normal`, `karras`.
  Free-text, not a hard enum — an invalid value for a given node class surfaces
  as a normal ComfyUI node error via the existing `_history_error` path.

## Files touched
- **New**: `runpod-comfyui/workflow_krea2.json` (cleaned, remapped, key stripped).
- **`comfy_common.py`**: `KREA2` map, `_build_krea2()`, `_apply_sampler_override()`
  (+ one call site added to each existing `_build_*`), `mode=="krea2"` branch in
  `generate()`.
- **`webapp/app.py`**: `krea2` branch in `_build_input` (reuses i2i's image/frame
  source resolution, adds `resize_size`, `refine`, `sampler_override`), mode
  validation, character-LoRA folder scoping for Krea2.
- **`webapp/index.html`**: new mode entry (Local-only mode selector, alongside
  Advanced), Krea2's Options-rail fields (resize target, refine toggle), the
  Override-Sampler block (added once, shown for every mode via existing
  mode-conditional field classes).
- No `Dockerfile`/worker/RunPod changes — Krea2 is local-only (cloud is
  Motion-only per current architecture); its node types (UNETLoader, CLIPLoader,
  KJNodes resize, LoraLoaderModelOnly, standard KSampler/VAEEncode/VAEDecode) are
  already available in the local ComfyUI install.

## Open items to verify during build (not blocking design)
- Actual on-disk LoRA folder name (`Kera2` vs `Keara2`) — check the local
  ComfyUI `models/loras` tree before wiring the character picker.
- `ImageResizeKJv2` with `keep_proportion="resize"` and equal W/H — confirm
  actual resize semantics (pad vs stretch vs crop) against a real render before
  exposing it as a single number; adjust label/help text if it's not literally
  "long edge" or "square target."
- Rotate the leaked OpenRouter key (independent of this feature, same class of
  issue as prior HF/RunPod key rotations noted in `HANDOFF.md`).

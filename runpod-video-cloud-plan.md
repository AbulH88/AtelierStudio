# Plan — Motion-only Cloud, fresh 40 GB volume (fp8 encoder)

Goal: cloud endpoint runs **Motion (Wan Animate) only** for the 2 teammates. Images stay on the
local 5090. Fresh **40 GB** network volume holding all OWN character LoRAs + the motion stack,
using the **fp8** text encoder to fit. Cost-sensitive — billable steps flagged 💲.

Decided this session: motion-only on cloud · 40 GB volume · fp8 umt5 · UI = Cloud shows only
Motion mode.

---

## Size budget — fits 40 GB with headroom

| File | ~GB |
|---|---|
| Animate-14B fp8 (`Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2`) | 16 |
| **umt5 fp8** (`umt5_xxl_fp8_e4m3fn_scaled`) | 6.7 |
| 5 motion LoRAs (relight / Seko / FastWan / Pusa rank512 / Fun) | 5.7 |
| clip_vision_h | 1.3 |
| 4 ONNX (vitpose / yolov10m / yolox_l / dw-ll) | 1.75 |
| RIFE flownet.pkl | 0.05 |
| wan 2.1 vae | 0.25 |
| your 6 own character LoRAs | ~2–3 |
| **Total** | **≈ 34 GB** → 40 GB volume, ~6 GB headroom ✅ |

## Done already this session (free, in repo — deploy when ready)
- `index.html` `onTargetChange()` — **Cloud hides Frame→Character + Text→Character, forces Motion.**
- `workflow_video.json` node 491 — text encoder set to **fp8** (`umt5_xxl_fp8_e4m3fn_scaled`),
  matches local + the 40 GB volume.

---

## SAFE SEQUENCE (don't delete the live volume until the new one is proven)
Build the populate path first; stand up the new 40 GB volume **alongside** the old 60 GB; populate
+ test motion on it; **only then delete the old 60 GB.** No window where cloud is broken/empty.

### Phase 1 — Dockerfile node packs + rebuild (FREE)
Add to `runpod-comfyui/Dockerfile` (KJNodes already present):
`kijai/ComfyUI-WanVideoWrapper`, `kijai/ComfyUI-WanAnimatePreprocess`,
`Kosinkadink/ComfyUI-VideoHelperSuite`, `JPS-Nodes`, `rgthree-comfy`,
`Fannovel16/ComfyUI-Frame-Interpolation` (RIFE), `Fannovel16/comfyui_controlnet_aux` (DWPose).
Rebuild via `.github/workflows/build-worker.yml` (GitHub Actions, free). Note the new image SHA.

### Phase 2 — Write the motion populate path (FREE, code)
Rewrite `populate_volume.py` for the motion set (drop the image t2v UNet entirely):
- **Public pulls on the pod (VERIFY repo ids):** Animate-14B fp8 + clip_vision_h
  (`Comfy-Org/Wan_2.1_ComfyUI_repackaged` : `split_files/clip_vision/clip_vision_h.safetensors`)
  + umt5 fp8 (`Comfy-Org/Wan_2.1_ComfyUI_repackaged` : `.../umt5_xxl_fp8_e4m3fn_scaled.safetensors`
  → place at `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` to match the workflow) + vae.
- **New `_upload_video.py`** (mirrors `_upload_loras.py`): upload the 5 motion LoRAs + 4 ONNX +
  RIFE from the proven local install → private HF repo `orthoraj21/atelier-loras`.
- Pull the 6 OWN character LoRAs (already in the private repo) onto the volume.
- ⚠️ ONNX/RIFE go in **node-expected dirs**, not `models/loras` — verify on the pod, hardlink.

### Phase 3 — Create the new 40 GB volume + populate 💲 (one short pod)
- Create `atelier-motion` 40 GB, **EU-RO-1** (same DC as endpoint; volume-DC support required).
- 💲 Mount on a cheap pod, run populate (`HF_TOKEN`, `HF_HUB_ENABLE_HF_TRANSFER=1`). ~34 GB pull.
- Verify every file present + non-zero; tear pod down.

### Phase 4 — Point endpoint at new image + volume + 48 GB GPU 💲
- Template `4fo2wrxxci` → new image SHA + attach the new 40 GB volume.
- Needs a **48 GB+ GPU** (Animate-14B + blockswap 20). Use the check-stock button. workersMin=0.

### Phase 5 — Test one cloud motion gen 💲
- App → **Cloud** target (now Motion-only) → driving video + ref photo → mp4 to R2.
- 💲 first run cold-pulls the image once. Fix any model path + re-run (no re-download).

### Phase 6 — Delete the old 60 GB volume (after motion is proven) 💲→ saves $
- Confirm motion works on the new volume, THEN delete `atelier-models` (3qu8532k8s).
- Storage drops 60→40 GB (~$4.20 → ~$2.80/mo).
- Update `webapp/.cloud_loras.json`: keep the 6 own char LoRAs, **remove the 2 image lightning
  LoRAs** (not on the motion volume; image lightning is local-only anyway).

---

## Cost summary
- Build (Dockerfile/rebuild/code): **free**.
- Populate pod: 💲 ~$0.30–1 (one session, ~34 GB).
- Endpoint test: 💲 minutes of 48 GB GPU; $0 idle after.
- Ongoing storage after old-volume delete: **~$2.80/mo** (40 GB).
- One-off stand-up: **≈ $1–2**.

## Open items / risks
- ⚠️ Confirm the public repo ids (Animate fp8 + clip_vision + umt5-fp8 paths) before the pod.
- ⚠️ ONNX/RIFE node-expected paths — verify on the pod (the one fiddly bit).
- ⚠️ 48 GB GPU scarcity in volume-DCs may gate Phase 4/5.
- 🔑 Rotate leaked keys (RunPod / OpenRouter / HF write).

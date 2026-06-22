# Video Mode (Wan Animate / "Motion Control") — Integration Design

Date: 2026-06-23
Status: Design / not built. Gated on RunPod (cloud-only, heavy GPU). The workflow
JSON (`runpod-comfyui/workflow_video.json`) is a **faithful, complete** conversion
of `workflow_sources/Motion_2.2.source.json` — verified node-by-node + param-by-param.
Nothing functional is missing from the file; what's missing is the **app integration**.

## Goal
Add a third generation mode — **Motion → Character** — that drives a character
(LoRA) with the motion of a reference video, via the Wan 2.2 Animate workflow, and
returns an mp4. Reuse the existing dispatch pattern so cloud + (future) local behave
identically through `comfy_common.generate`.

## What the workflow needs as dynamic input (today it's hardcoded)
The JSON currently has static values baked in. These must become per-request inputs,
the same way `_build_i2i`/`_build_t2i` inject character/prompt today:
- **Driving video** — `VHS_LoadVideo.video` (currently `madison.moorgan_reel_...mp4`)
- **Reference photo** — the `LoadImage` feeding `WanVideoClipVisionEncode`
- **Prompt** — the `Text Prompt (JPS)` positive node, **auto-filled by describing the
  reference photo** through the existing OpenRouter `describe_image` pipeline (exactly
  like i2i auto-describes an empty-prompt frame). User can override. [user requirement]
- **Character LoRA** — `WanVideoLoraSelect.lora` (currently `wan/Own/LoranceNew/...`) + strength
- **BlockSwap** — a **UI toggle** (default on); `WanVideoSetBlockSwap`/`WanVideoBlockSwap`
  applied only when enabled (VRAM offload). [user requirement]
- **Length** — `VHS_LoadVideo.frame_load_cap` + `WanVideoContextOptions.context_frames` (default 81)
- **Seed** — `WanVideoSampler.seed`
FIXED (engine config, baked like Lightning is for images — do NOT expose in UI v1):
the 5-LoRA relight/speed stack (relight 0.85, Seko-high_noise 0.3, FastWan 0.75,
PusaV1 0.7, Fun-A14B 0.9), sampler (4 steps / cfg 1 / dpm++_sde / shift 5),
RIFE ×4, pose-rig models.

## Changes by file

### `comfy_common.py` (the shared builder — biggest change)
1. **`VIDEO` node-id map** (like `I2I`/`T2I`): ids for load_video, ref_image,
   positive, char_lora, sampler, load_video-cap, context-options.
2. **`_build_video(graph, inp, seed, video_name, ref_name)`**: inject the dynamic
   inputs above; leave the fixed stack alone. Mirror `_build_i2i` style.
3. **`run()` output extraction** — currently only reads `out.get("images", [])`.
   Wan Animate's `VHS_VideoCombine` writes results under a **`gifs`** key in
   `/history` outputs (filename ends `.mp4`). Extend `run()` to also collect
   `out.get("gifs", [])`, fetch via `/view`, and tag them as video. Return shape
   needs to distinguish images vs video.
4. **`generate()`**: add `mode == "video"` branch. It does NOT batch (one mp4 per
   run — ignore `max_batch`/variations or treat variations as separate runs).
   Upload **two** assets first: the driving video and the ref image. Return
   `{"video": "<b64 mp4>", "seed": int}` (or `{"media":[{type,b64}]}` for a unified shape).
5. **Video upload helper** — `upload_video(base, bytes, name)` (ComfyUI `/upload/image`
   accepts video into the input folder for VHS; confirm on the real endpoint).

### `handler.py` (RunPod worker)
No code change — it's a thin pass-through to `comfy_common.generate`. The new output
shape (`video`/`media`) flows through automatically. (The container Dockerfile DOES
need the nodes added — see Assets.)

### `webapp/app.py`
- **`_build_input`**: add the `video` branch — read driving video + ref image (base64),
  `frame_cap`, character lora, prompt/trigger.
- **New uploads**: driving video can be (a) uploaded, or (b) **picked from the existing
  R2 reel library** (nice synergy — reels are already there). Ref photo uploaded or
  picked from the gallery.
- **`_run_gen_job` / result**: handle the `video`/`media` output; save the mp4 to R2
  (new gallery media type) and return it to the browser.
- **`_save_to_gallery`**: support video items (store mp4 in R2 under the gallery,
  render with a `<video>` tag).

### `webapp/index.html`
- Third mode button: **Motion → Character** (alongside Video→Character / Text→Character).
  NOTE the existing i2i mode is confusingly labelled "Video → Character" but is image
  frame-extraction; rename for clarity (e.g. i2i = "Frame → Character").
- Motion pane: driving-video dropzone (or "pick a reel"), ref-photo slot (or "pick from
  gallery"), prompt, character picker (reuse), length (frames) control. Cloud-only:
  show the existing cloud card; hard-require target=cloud.
- Result: render mp4 in a `<video controls>` instead of `<img>`.

## RunPod volume + image assets (exact list from the workflow)
**Models (network volume):**
- `WAN/Kijai Collection/Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors`
- `wan_2.1_vae.safetensors` · `clip_vision_h.safetensors`
- umt5 text encoder (e.g. `Wan/umt5_xxl_fp16.safetensors`)

**LoRAs (under `wan/` — also the cloud manifest entries):**
- `wan/WanLightning/WanAnimate_relight_lora_fp16/WanAnimate_relight_lora_fp16.safetensors`
- `wan/WanLightning/Wan2.2-I2V-A14B-4steps-lora-rank64-Seko-V1/...-high_noise.safetensors`
- `wan/WanLightning/KijjiLora/FastWan_T2V_14B_480p_lora_rank_128_bf16/...safetensors`
- `wan/WanLightning/KijjiLora/Wan21_PusaV1_LoRA_14B_rank512_bf16/...safetensors`
- `wan/WanLightning/KijjiLora/Wan2.2-Fun-A14B-InP-LOW-HPS2.1.../Wan2.2-Fun-A14B-InP-low-noise-MPS.safetensors`
- `wan/Own/LoranceNew/LoranceNew.safetensors` (+ any other character LoRAs)

**Pose / ONNX:** `vitpose_h_wholebody_model.onnx`, `yolov10m.onnx`, `yolox_l.onnx`,
`dw-ll_ucoco.onnx` · **RIFE:** `flownet.pkl`

**Custom nodes (Dockerfile):** ComfyUI-WanVideoWrapper (Kijai) + WanAnimate preprocess
(provides PoseAndFaceDetection / OnnxDetectionModelLoader), ComfyUI-KJNodes,
ComfyUI-VideoHelperSuite (VHS), ComfyUI-Frame-Interpolation (RIFE), JPS nodes, rgthree.

## Open decisions (flagged, not blocking)
1. **Driving video source** — upload only, or also pick from the R2 reel library?
   (Recommend both; the library is already wired.)
2. **Ref photo** — upload, or also pick a prior generated image from the gallery?
   (Recommend both.)
3. **Output return shape** — `{"video": b64}` vs a unified `{"media":[{type,b64}]}`.
   (Recommend unified `media` so image + video modes share one path.)
4. **Length cap** — expose frames (default 81 ≈ 2.7s @30fps) or fix it. (Recommend expose,
   small range, since longer = much more VRAM/time/cost.)

## Risks / notes
- **VRAM**: 14B fp8 + BlockSwap 20 + ONNX pose + 5 LoRAs → needs a big GPU (well past the
  L40S that's fine for images). Confirm GPU tier during RunPod build; cost will be higher.
- **Cold start** will be longer than images (bigger model + more assets) — the warming
  card already handles this UX.
- **mp4 output** is the #1 integration gotcha (the `gifs` key) — covered above.
- The static negative/prompt nodes and the "stop before Upscaler" section from the source
  are not in our API graph — that's correct (upscaler intentionally excluded).

# Atelier Character Studio — Handoff

Last updated by Claude (Opus 4.8), 2026-06-27. **INSTARAW "Advanced" mode is BUILT + WORKING
end-to-end** (local-only). A full render proven this session: ~470s, eye-detailer + upscale +
authenticity + real iPhone-12 EXIF, 2 images to Gallery. Memory: `instaraw-advanced-mode`,
`runpod-cloud-build-state`. Plan: `instaraw-advanced-plan.md`. (Cloud Motion still LIVE — see below.)

## ✅ KREA2 IMAGE TO IMAGE HIGH QUALITY — 2-stage ClownsharKSampler mode (this session — built + unit-tested, NOT yet live-verified)
8th local-only generation mode (`mode="krea2hq"`), built from the user's
`Krea2 I2I HighQuality.json` export. Distinct from both existing Krea2 modes: true img2img like
`krea2` (VAEEncode of the resized+noise-augmented source image), but always runs a fixed **two-stage**
`ClownsharKSampler_Beta` pipeline — base pass (denoise 0.8) feeding straight into a quality-refine pass
(denoise 0.27) — with no optional-refine toggle (unlike `krea2`, where the refine pass is opt-in). 19/19
new backend tests passing (`test_workflow_krea2hq_file.py`, `test_build_krea2hq.py`,
`test_generate_krea2hq_dispatch.py`), 45/45 total.
- **`workflow_krea2hq.json`** (repo root of `runpod-comfyui`) — cleaned from the source export:
  leaked OpenRouter key + hardcoded character-specific caption instruction (node 19,
  `sk-or-v1-2ecfce...80749` — **same key already flagged below, still needs rotating**) dropped, app's
  existing "Describe with AI" reused instead; the in-graph video source + interactive frame picker
  (`VHS_LoadVideo` node 25, `Image Filter` node 16) dropped in favor of the app's own frame
  extraction/picker (same plumbing as `i2i`/`krea2`/`krea2new` — a plain `LoadImage` node now sits at
  id `16`); the `EmptyLatentImageResPreset` in-graph resolution-preset dropdown (node 7) dropped in
  favor of the app computing width/height itself (new `RES_PRESETS` list in `webapp/app.py`, 16 named
  presets — Landscape/Portrait/Full Body/Square × 1K–4K — matching the source node's own preset table);
  an unused orphan `Int` node (23) dropped; the debug `PreviewImage` (node 12) converted to a real
  `SaveImage` (this mode's sole output node).
- **`comfy_common.py`** — `KREA2HQ` node map, `_set_power_lora_slot()` helper (the character LoRA lives
  in slot 1 of an rgthree "Power Lora Loader" node — a *third* LoRA-node convention alongside the
  existing `_set_lora`/`LoraLoaderModelOnly` and `_set_stack_slot`/"Lora Loader Stack" helpers: this one
  uses a nested `{"on","lora","strength"}` dict per slot), `_build_krea2hq()` (frame image, resize
  width/height, prompt+trigger, shared sampler seed, character LoRA slot, sampler override — the two
  fixed realism-helper LoRAs in slots 2/3 are left untouched, technique LoRAs not identity LoRAs, same
  treatment as `krea2new`'s control-LoRA), wired into `generate()`'s dispatch and upload-once check.
- **`webapp/app.py`** — `krea2hq` branch in `_build_input` (session/frame → image_b64, reuses the
  generic width/height already parsed for every mode), `/api/generate` local-only gate + frame-exists
  check, empty-prompt auto-describe extended to cover `krea2hq`, new `RES_PRESETS` list exposed via
  `/api/config` as `res_presets`.
- **`webapp/index.html`** — 8th mode button (`Krea2 Image to Image High Quality`, local-only, hidden on
  Cloud), reuses the shared frame-picker pane (`#paneVideo`) and the Krea2 character picker (`Keara2`
  root). New **resolution-preset `<select>`** (grouped `<optgroup>`s by Landscape/Portrait/Full
  Body/Square) replaces the generic aspect-ratio picker for this mode only — selecting a preset sets
  `S.aspect` the same way the aspect-picker buttons do, so the existing `body.width`/`body.height`
  wiring in the generate handler needed no changes.
- **`.github/workflows/deploy.yml`** — added `workflow_krea2hq.json` to the deploy tar manifest
  up front this time (the `krea2`/`krea2new` rollout hit a `FileNotFoundError` on the VPS because this
  hardcoded whitelist wasn't updated — see the `deploy(fix)` commit referenced above).

### Krea2 Image to Image High Quality — still open before shipping
- **Not yet live-verified**: needs a real ComfyUI install with the Krea2 checkpoint/CLIP/character
  LoRA/realism-helper-LoRA files present to confirm the two-stage sampler chain and the rgthree Power
  Lora Loader wiring render correctly.
- **Deploy**: not yet pushed to VPS — confirm the GitHub Actions `deploy.yml` run goes green and test a
  real render.
- The leaked OpenRouter key from the source JSON is stripped from the shipped file but the key itself
  still needs rotating — same outstanding item as below (this is the third time this exact key has
  turned up graph-embedded in a Krea2-family export).

## ✅ KREA2 IMAGE TO IMAGE NEW — depth-ControlNet mode (this session — built + unit-tested, NOT yet live-verified)
7th local-only generation mode (`mode="krea2new"`), built via `superpowers:subagent-driven-development`
in a worktree (`worktree-krea2new-depth-mode`), all 6 tasks task-reviewed clean, 31/31 backend tests
passing. Design: `docs/superpowers/specs/2026-07-19-krea2new-depth-mode-design.md`. Plan:
`docs/superpowers/plans/2026-07-19-krea2new-depth-mode.md`.
- Distinct pipeline from the existing Krea2 mode: **not** img2img. The source photo runs through
  DepthAnythingV2 to get a depth map, which conditions a **full generation** (denoise 1, KSampler
  from an empty latent) via a Krea2 control-LoRA (`Keara2\mix\depth-control-lora.safetensors`,
  fixed strength 1) stacked on top of the character LoRA — pose/composition transfer, not
  pixel-level editing.
- **`workflow_krea2new.json`** (repo root of `runpod-comfyui`) — cleaned from the user's
  `Krea-2-Turbo_Depth-Controlnet.json` export: leaked OpenRouter key (node 39,
  `sk-or-v1-2ecfce...80749` — same key already flagged below, still needs rotating) + graph-embedded
  auto-caption (node 40) dropped, app's existing "Describe with AI" reused instead; the
  `FluxResolutionNode` preset dropdown (node 30) dropped in favor of wiring `EmptyLatentImage`
  directly from the app's aspect picker (same as T2I); a debug `PreviewImage` of the depth map
  (node 36) dropped (would otherwise leak into every generation's returned image list).
- **`comfy_common.py`** — `KREA2NEW` node map, `_build_krea2new()` (frame image, width/height,
  prompt+trigger, seed, character LoRA, sampler override — no Lightning chain, no refine pass),
  wired into `generate()`'s dispatch and upload-once check.
- **`webapp/app.py`** — `krea2new` branch in `_build_input` (session/frame → image_b64 only, reuses
  the generic width/height already parsed for every mode), `/api/generate` local-only gate +
  frame-exists check, empty-prompt auto-describe extended to cover `krea2new`.
- **`webapp/index.html`** — 7th mode button, reuses the shared frame-picker pane (`#paneVideo`),
  the T2I aspect-ratio picker, and the Krea2 character picker (`Keara2` root) — no new UI controls.
  Also relabeled all 6 mode buttons per user request this session: Wan Image to Image (i2i), Wan
  Text To Image (t2i), Wan Animate Motion Control (video), Instaraw Advance (adv), Krea2 Image to
  Image (krea2), Krea2 Image to Image new (krea2new). Display text only — mode keys/`data-mode`
  attrs unchanged.

### Krea2 Image to Image new — still open before shipping
- **Not yet live-verified**: needs a real ComfyUI install with the Krea2 checkpoint/CLIP/character
  LoRA/depth-control-LoRA files present to confirm the depth-control chain and character LoRA
  render correctly, and to check `Krea2ControlImageEncode`'s `resize=match_latent_size` behavior
  when the chosen aspect ratio differs a lot from the source photo's native aspect.
- **Deploy**: merged to `main` and pushed this session — confirm the GitHub Actions `deploy.yml`
  run went green (check the API/Actions tab) and test a real render on the VPS.
- The leaked OpenRouter key from the source JSON is stripped from the shipped file but the key
  itself still needs rotating — same outstanding item as below.

## ✅ KREA2 I2I MODE + CROSS-MODE SAMPLER OVERRIDE (this session — built + unit-tested, NOT yet live-verified on VPS)
6th local-only generation mode wrapping the user's Krea2 workflow (true img2img: VAEEncode of a
resized+noise-augmented source image, denoise 0.6, optional skin-detail refine pass), plus an opt-in
cfg/sampler_name/scheduler override usable across every mode (T2I/I2I/Video/Advanced/Krea2) without
touching any mode's tuned defaults unless a user explicitly turns it on. Built via
`superpowers:subagent-driven-development` in a worktree (`feature/krea2-i2i-mode`), all 5 tasks
task-reviewed clean, 16/16 backend tests passing. Design: `docs/superpowers/specs/
2026-07-09-krea2-mode-and-sampler-overrides-design.md`. Plan: `docs/superpowers/plans/
2026-07-09-krea2-mode-and-sampler-overrides.md`.
- **`workflow_krea2.json`** (repo root of `runpod-comfyui`) — cleaned Krea2 graph, leaked OpenRouter
  key + graph-embedded auto-caption dropped (app's existing "Describe with AI" reused instead), debug
  nodes (rgthree comparers/preview) stripped. Confirmed on-disk LoRA root is **`Keara2`** (verified
  against the home PC's `models/loras/Keara2/{CristinaCosplay,GothNiche}`) — NOT `Kera2`, which is a
  different root used only for the base UNET/CLIP checkpoint folders.
- **`comfy_common.py`** — `KREA2` node map, `_build_krea2()` (image/prompt/seed/LoRA/resize wiring,
  refine-pass toggle that drops or keeps nodes 334/335/336/339), `_apply_sampler_override(graph, inp)`
  (broadcasts cfg/sampler_name/scheduler to every node whose `class_type` contains `"Sampler"`, only
  touching keys the node already has — a true no-op when `inp` has no `sampler_override` key), wired
  into all 5 `_build_*` functions, `generate()` `mode=="krea2"` branch.
- **`webapp/app.py`** — `KREA2_LORA_ROOT="Keara2"` + `build_krea2_characters()` (own character picker,
  separate from WAN's `wan/MyLoras` root), `/api/config` gains `krea2_characters`, `_build_input()`
  gains a `krea2` branch (reuses i2i's frame/session upload plumbing + `resize_size`/`refine`) and a
  universal `sampler_override` passthrough applied once for every mode, `/api/generate` gates `krea2`
  to `target=="local"` (mirrors `adv`'s gate), empty-prompt auto-describe extended to cover `krea2`.
- **`webapp/index.html`** — 5th mode button (`Krea2 I2I`, hidden on Cloud like Advanced), reuses the
  existing `#paneVideo` frame-picker pane, Options-rail fields (Resize target · px, Skin-detail refine
  toggle), shared "⚙ Override Sampler" block (cfg slider + editable sampler_name/scheduler datalists)
  shown for every mode. Krea2 has no Lightning node — `applyLightningDefault()` skips it, `.stdlora`
  controls hidden same as `adv`. Live-verified in-browser this session (dev server, all 5 mode buttons,
  Cloud correctly hides Krea2, fields toggle correctly, zero console errors across mode switches).

### Krea2 mode — still open before shipping
- **Not yet live-VPS-verified**: character LoRA render correctness, actual resize semantics of
  `ImageResizeKJv2` with equal W/H (pad vs stretch vs crop — confirm against a real render), whether
  the refine toggle visibly changes skin texture, whether the sampler override actually changes output
  when toggled on. Needs a real ComfyUI install with the Krea2 checkpoint/CLIP/LoRA files present.
- **Deploy**: not yet pushed to VPS. Add `workflow_krea2.json` to the "Manual deploy" tar list below,
  deploy `comfy_common.py`/`workflow_krea2.json`/`webapp/app.py`/`webapp/index.html`, restart `atelier`.
- **⚠️ Another OpenRouter key was pasted into this session** (`sk-or-v1-2ecfce...`, was graph-embedded
  in the source Krea2 JSON, node 330 — that node was dropped from `workflow_krea2.json` entirely, and
  a test in `tests/test_workflow_krea2_file.py` guards against `sk-or-v1`/`api_key` ever reappearing in
  the file). The key itself still needs rotating in the OpenRouter dashboard + VPS `.env` update — same
  outstanding class of issue as the HF/RunPod/OpenRouter keys already flagged below.

## ✅ INSTARAW ADVANCED MODE (this session — local only, on the home 5090)
New app mode wrapping the user's `INSTARAW WAN 2.2 V2.0` workflow (t2i + image-guided "i2i" via the
`576` toggle; "i2i" = image-guided PROMPTING, NOT latent img2img — verified, generation is always
txt2img on the empty latent). Heavy pipeline: WAN 2.2 base → SDXL detailers (face/eyes/hands/feet/
nipples/pussy/lips) → upscale → authenticity (LUT/GLCM/grain/perturb/compression) → fake-EXIF save.
Needs the INSTARAW custom-node pack (home ComfyUI has it; cloud doesn't → why local-only).
- **`workflow_adv.json`** (repo root of runpod-comfyui) — the export, leaked key stripped, model
  paths remapped to the reorganized loras folder (`_remap_paths.py` does this — re-run on re-export).
- **`comfy_common.py`** — `ADV` map, `_build_adv` (aspect 523, char-ref 581, prompt_batch 584,
  OpenRouter key→580 from env, char LoRA synced to both rgthree stacks 287/256, lightning→287 slot2,
  helpers per group, popups, `interactive` flag, `ADV_STAGES`+`_bypass_node` Main-Menu toggles),
  `run(out_node=402)` returns only the final image, `generate()` `mode=="adv"` branch.
- **`webapp/app.py`** — `adv` `_build_input` branch + validation; proxies: `/api/interaction`,
  `/api/interact` (popups via agent), `/api/instaraw/{generate_creative_prompts,
  generate_character_description,get_random_prompts,batch_upload,view}`, and `/api/instaraw/
  prompts_db` + `/prompts_filters` (server-paginated 7.9k library, cached from S3, parses Python-repr).
- **`webapp/index.html`** — Advanced mode (Local-only, hidden on Cloud), violet studio + branded
  header. Prompt Studio tabs: **Generate** (AI prompts via Grok `x-ai/grok-4.3`, char-from-image,
  expression chips, library inspiration) + **Library** (search/filter/paginate/fav/+Add). Always-on
  **Generation Batch** (rich cards: positive/negative/repeat/seed/after-gen/source). Two **LoRA
  groups** (high 256 / low 287; Lenovo seeded in low). **Main Menu** stage toggles. Interactive
  **popup modals** (picker + mask canvas). Rail hides redundant Aspect + Describe in adv.
- **`home_agent/agent.py`** — popup relay: catches WS `instaraw-interactive-images`, exposes
  `/interaction` + `/interact`. Restart via `home_agent/Start_Agent.bat` after edits (it ran already).
- **Reuse-their-engine:** the Prompt Studio + Library call the home ComfyUI's own `/instaraw/*` HTTP
  routes (work through the tunnel); 22MB prompt DB = `instara.s3...prompts.db.json`.

### Advanced mode — known + open
- **MediaPipe/controlnet_aux fix (this session):** eye detailer crashed (`mp.tasks.vision` has no
  `drawing_utils`). Patched `comfyui_controlnet_aux/.../mediapipe_face/mediapipe_face_common.py`
  (new-API branch now reads drawing_utils/DrawingSpec from `mp.solutions`; `.bak` saved). Needs a
  ComfyUI restart to load. NOT in git (it's the ComfyUI install).
- A full render ≈ **8 min**, so the app sits on "developing…" a while — that's normal, not a hang.
- Interactive popups only fire for **app-triggered** Develop with **Interactive ✓**; the popup also
  shows in ComfyUI's canvas (WS broadcast). Both UI-update + popup confirmed working this session.
- Not yet built (the smaller wf bits): Temperature/Top-P, complexity, SDXL toggle, i2i image-loader,
  Create/Import/Export prompts, after-gen auto-reseed. Eye-detailer is one of the 12 Main-Menu toggles.

## ⏭️ NEXT (in order)
1. Finish polishing Advanced mode per user (see "not yet built" above) + the in-app i2i image loader.
2. **⚠️ ROTATE LEAKED KEYS** — HF write token + RunPod API key + OpenRouter key are exposed
   (OpenRouter also baked in `workflow_*` node 580, now stripped from `workflow_adv.json`). Mint new,
   update VPS `.env`. The Prompt Studio uses the VPS `OPENROUTER_API_KEY` (works; just rotate it).
3. **Motion Storyboard v1** (parked) — plan in `motion-storyboard-plan.md`.
4. Optional perf/buttons as before (idleTimeout, stop/cancel, per-char triggers).

## ✅ MOTION CLOUD — the fix chain this session (so it's not re-debugged)
Worker now makes finished, audio'd character mp4s on a Blackwell GPU in ~90s compute. Fixes (committed):
- **Blackwell GPU crash (exit 1 loop)** → image was CUDA 12.4 / torch cu124, can't drive RTX PRO 6000 /
  5090 (sm_120). Rebuilt Dockerfile to **CUDA 12.8 + torch cu128** + `build-essential`. EU-RO-1 has
  ONLY Blackwell cards, so cu128 was mandatory.
- **Missing RIFE node** → workflow's `RIFEInterpolation` is from **GACLove/ComfyUI-VFI** (not Fannovel16,
  which gives `RIFE_VFI`). Swapped the pack. `flownet.pkl` placed at `models/rife/` on the volume.
- **Backslash paths** → workflow_video.json was Windows-exported (`wan\..`); Linux worker lists with `/`
  → "Value not in list". Converted to `/` + `_normalize_model_paths()` self-heal guard in comfy_common.
- **Got pose preview not the video** → run_video grabbed node 117 (DWPose temp) when 319 missing; now
  returns only the saved output node + diagnostics.
- **"No output from worker" at ~90s** → app used `/runsync` (90s cap) → switched to async `/run` + poll.
- **Slow (~6 min)** → BlockSwap=0 + load_device=main + force_offload=false (96 GB fits in VRAM). All
  nodes on GPU EXCEPT the two `ImageResizeKJv2` (KJNodes lanczos = CPU-only) + ffmpeg video I/O.

## ✅ APP / UI shipped this session (all app-side, deployed to VPS)
- **Cloud = Motion-only** UI (image modes hidden on Cloud target).
- **Cloud character picker** built from `.cloud_loras.json` (CHAR_DEFS folders differed from the volume
  layout → only Lorance showed; now all 6 own chars: Cristina, FscvrDD×2, Hazil, LoranceNew, MasterGothGirl).
- **Motion audio** — `_mux_audio` ffmpeg muxes the driving video's audio onto the (silent) output.
- **Reel → Motion** button (driving video) + **Gallery → Motion ref** button (reference photo).
- **t2i matched to the user's good ComfyUI wf**: BF16 model, rank256 lightning (also LIGHTNING_DEFAULTS),
  sage auto, fp8 clip. t2i/i2i run LOCAL only now (cloud is motion-only).

## 🔧 How to operate (deploy / infra)
- **VPS app deploy (instant, no rebuild)** for app.py/index.html/workflow_*.json used locally: tar over
  SSH with the deploy key (see "Manual deploy"), `systemctl restart atelier`.
- **Worker image rebuild (~15-20 min, free)**: push Dockerfile/handler/comfy_common/workflow_*.json to
  `main` → GitHub Actions `build-worker.yml` → Docker Hub `orthoraj21/atelier-comfy-worker:<full-sha>`.
  Then PATCH template `4fo2wrxxci` imageName to the new SHA (REST from VPS).
- **RunPod control: REST from the VPS** (`https://rest.runpod.io/v1`, key in VPS `.env`) — the MCP 401s
  and the home PC has TLS issues to some endpoints. Job submit/status/cancel use `https://api.runpod.ai/v2`.
- **`populate_motion.py`** rebuilds the volume from HF; `_upload_video.py` pushes local motion models to HF.

## ✅ CLOUD STATE — MOTION is now LIVE (image cloud path retired)
- **Motion endpoint** `tgh96neez89ei8` (name `atelier-motion`, serverless, workersMin=0 → $0
  idle), template `4fo2wrxxci` → image `:0a2613536e...` (video node packs), **EU-RO-1**, 48 GB
  GPU list (A40/A6000/L40/L40S/6000Ada). VPS `.env RUNPOD_ENDPOINT_ID` points here.
- **Motion volume** `atelier-motion` id `p8od5of3fb` (**60 GB**, EU-RO-1) — fully populated:
  18 files, 45.2 GB (Animate-14B fp8, umt5-fp8, clip_vision_h, vae, 5 motion LoRAs, 3 detection
  incl. vitpose .bin, 6 char LoRAs). Manifest `_motion_manifest.json` in the HF repo (all_ok).
- **OLD image volume `atelier-models`/endpoint `d27ehaezfyja3o` were DELETED** — cloud now does
  Motion only (images run locally on the 5090). `populate_motion.py` rebuilds the volume from HF.
- DWPose (yolox_l, dw-ll) + RIFE (flownet) are NOT on the volume — controlnet_aux +
  Frame-Interpolation auto-download them at runtime on first gen (~350 MB, also in HF repo under
  dwpose/ + rife/ as backup). UI: Cloud target shows Motion mode only (onTargetChange).
- **Worker image** `orthoraj21/atelier-comfy-worker` on Docker Hub. :latest = sage-disabled
  (commit `8573c3d`). Built by `.github/workflows/build-worker.yml` (GitHub Actions, free).
- **Private HF repo** `orthoraj21/atelier-loras` holds the own/lightning LoRAs.
- **SAGE BUG FIXED**: `PathchSageAttentionKJ`→sageattention→triton needs a C compiler the slim
  runtime image lacks; disabled sage in both image workflows. Image gen PROVEN working on cloud.
- **Cloud UI is live**: status card, **live GPU picker** (pulls real stock+price from RunPod
  GraphQL — `_live_gpus()`), **⟳ check-stock** button, LoRA availability tagging, cost estimate.
- **Use the REST API, not the MCP** (`https://rest.runpod.io/v1`, `Authorization: Bearer <key>`).
  MCP auth went flaky (401s). GPU names use a fixed enum (filter against it). Availability via
  GraphQL `gpuTypes{...lowestPrice(input:{dataCenterId}){stockStatus uninterruptablePrice}}`.
- **GPU scarcity is the recurring wall**: cheap 48 GB cards (L40S/A40/A6000) often out across
  volume-DCs. The check-stock button shows what's actually free. US-KS-2/US-CA-2 ran dry; chose
  EU-RO-1. CA-MTL has cheap GPUs but **no network-volume support**.
- Endpoint creation 500 "graphql: Something went wrong" is often transient — retry; name must be
  non-trivial length. RunPod bills only while a worker RUNS (queued/throttled = $0).

## 🎬 MOTION MODE (Wan Animate) — BUILT + works LOCALLY (free, on the 5090)
- Third app mode **"Motion → Video"**: driving video + ref photo → animated character mp4.
- `comfy_common.py`: `VIDEO` node map, `upload_video`, `run_video` (mp4 from /history `gifs`),
  `_build_video` (injects driving video #75, ref image #515, prompt #549, char LoRA #544, seed,
  frame_cap, fps), `mode=="video"` branch in `generate()`.
- `workflow_video.json` = the user's CURRENT Motion 2.2 API export (30 nodes; Animate 14B fp8,
  5-LoRA stack, BlockSwap 20, 4-step/cfg-1 sampler, pose-rig, final mp4 = node 319).
- `app.py`: video branch in `_build_input` (video_b64/ref_b64/frame_cap/fps), mp4 → R2, validation.
- `index.html`: driving-video + ref-photo upload, **AI "Describe ref photo"** (reuses OpenRouter
  describe), **frames + FPS + ⤢ max** (fills frames from clip length×fps), **"→ Motion ref"**
  button on generated images, decluttered (image-only controls tagged `.imgonly`, hidden in
  motion mode — only character LoRA + describe stay).
- Test it via the app's **Local** target (home 5090 ComfyUI through the tunnel). NOT on cloud yet.

## Source control — all pushed
- GitHub: **https://github.com/AbulH88/AtelierStudio**, primary branch **`main`** (HEAD `1bc064c`).
- Auto-deploy ships app code on push to `main`; `build-worker.yml` rebuilds the worker image on
  changes to Dockerfile/handler/comfy_common/workflow_*.json.
- VPS `.env` now has `RUNPOD_API_KEY`/`RUNPOD_ENDPOINT_ID`/`RUNPOD_REGION`. The LOCAL
  `runpod-comfyui/webapp/.env` was accidentally wiped + rebuilt from the VPS copy (HF_TOKEN lost
  — regenerate if syncing LoRAs); user runs cloud/VPS only so local doesn't matter.
- No secrets tracked. Deploy key lives OUTSIDE the repo (see Auto-deploy).

## What this is
A web app running custom **Wan 2.2 ComfyUI** character workflows for ~3 people, on the
**local 5090** or (planned) **RunPod serverless**, with an Instagram **reel library** in
Cloudflare R2. Live at **https://studio.thecristinaadam.com**.

## Repo layout (`runpod-comfyui/`)
- `comfy_common.py` — shared workflow logic (build + run via ComfyUI HTTP API), used by both
  the web app and the RunPod handler. Sends Cloudflare Access headers. **Now builds a dynamic
  LoRA chain**: `model → Lightning (lightx2v) → [extra/helper LoRAs] → character → sampler`.
  `_prompt_with_trigger` prepends the trigger word; `_apply_lightning`, `_apply_extra_loras`.
- `workflow_i2i.json` — Video→Character. **QwenVL removed.** Positive prompt = a literal
  string the app sets (trigger + description). Dead Realism node 12 removed; node 13 = char.
- `workflow_t2i.json` — Text→Character: single low-noise sampler, `start_at_step=4`, **cfg=1**,
  lightx2v v2 distill @0.6, BF16. Do NOT raise cfg or revert to two-stage (→ confetti noise).
- `workflow_video.json` — **Wan Animate** motion-transfer (API format, ready). Cloud-only; not
  wired into the app yet. Driving video + ref photo → mp4. See the `video-wan-animate` memory.
- `handler.py` — RunPod serverless entrypoint (thin wrapper; passes `event["input"]` through).
- `Dockerfile`, `start.sh` — RunPod image (ComfyUI + KJNodes + RES4LYF + sageattention;
  **QwenVL clone removed**). Video mode will need WanVideoWrapper/WanAnimatePreprocess/VHS/
  JPS/rgthree/RIFE added here.
- `webapp/` — Flask app + single-page UI (`app.py`, `r2_store.py`, `index.html`, `login.html`).
  `.env` gitignored; `.env.example` documents vars. Caches `.catalog.json`/`.loras.json`/
  `.nsfw_loras.json`/`.lightning_loras.json`, state `notes.json`/`users.json` — all gitignored.

## Describe-with-AI (replaced on-GPU QwenVL — DONE)
Images are described by an **OpenRouter vision model** in the backend; the result (+ trigger)
becomes the positive prompt. The worker never needs QwenVL.
- **Vision models** (`VISION_MODELS` in app.py, curated): default **`qwen/qwen3-vl-235b-a22b-instruct`**
  (handles SFW **and** NSFW), + Qwen3-VL 32B, Grok 4.3, Mistral Small 3.2, GLM-4.6V (all "both"),
  Gemini 2.5 Flash (SFW/fast), Nemotron free (SFW). `OPENROUTER_MODEL` env = the fallback/default.
  Gemini/GPT/Claude REFUSE NSFW — that's why the default is Qwen.
- **Controls** (Options rail, "✦ Describe with AI"): Vision Model, Style Preset, Body Type
  dropdown (None default), Shot Type, Detail Level, **Explicit/NSFW toggle** (loosens the
  instruction), Clothing Note, Custom Instruction (free text the model follows), **Trigger Word**
  (editable, default `ing2lorance`, prepended to the prompt in BOTH modes).
- Instruction (`_describe_instruction`): always excludes face/identity (LoRA owns it) but
  **forces the face to stay in frame** (fixes headless output from face-hiding reference poses).
- Endpoints: `POST /api/describe` (form upload or `{session,frame}`), `GET /api/openrouter/models`.
- Needs `OPENROUTER_API_KEY` in `.env` (set on VPS). ⚠️ A key was pasted in chat — rotate it.

## LoRA system (rebuilt this session)
- **Character**: two-level picker (character → checkpoint), live list from ComfyUI, cached.
  ⚠️ **Character LoRAs are trained on chin-cropped selfies** → at strength **1.0 they crop the
  face off**. Default strength is now **0.8**; keep 0.65–0.8 for faces. (Proven by A/B test.)
- **⚡ Lightning** (editable dropdown + strength): defaults per mode — i2i 4-step rank64 @1.0,
  t2i v2-distill rank128 **@0.6** (do not stray far for t2i). Mode switch resets to safe default.
- **Helper "Add LoRA"**: short curated `HELPER_LORAS` (Lenovo, Smartphone Snapshot low,
  Instagirl v2.5 low, Instareal low, Detail Enhancer) **+ a dedicated "NSFW" group listing all
  of `wan/NSFW`** (dynamic via `_folder_loras`). Slots are **remembered in browser localStorage**.
- **Cloud manifest (TODO at RunPod):** the picker lists the *home* ComfyUI's LoRAs regardless of
  target, so on Cloud anything not on the volume fails. Plan: a `CLOUD_LORAS` manifest + make the
  character/helper lists target-aware (full list on Local, manifest on Cloud). See memory.

## Async generation (fixes Cloudflare 100s cutoff — IMPORTANT)
Cloudflare drops any proxied request >~100s, so long gens died with `Unexpected token '<'`.
Now: `POST /api/generate` starts a background-thread job → returns `{job_id}`; browser polls
`GET /api/generate/result?job_id=` (each request short). Results still saved to R2 gallery.
- Frontend `safeJson()` wraps generate/start/stop/describe so HTML error pages (502/504) show a
  readable message instead of the JSON-parse error.
- `index.html` is served with **`Cache-Control: no-store`** — deploys show up without hard-refresh.
- Service runs single-process (`python3 app.py`) so the in-memory job store is shared. Do NOT
  switch to multi-worker gunicorn without moving the job store out of process.

## Sticky Board (new "Notes" page)
Shared wall, all logged-in users. Add **text + image/video** (upload, drag-drop, or paste),
6 colors. Links auto-linkified; text HTML-escaped (no stored XSS). Delete = author or admin.
Metadata in `webapp/notes.json` (thread-locked); media in R2 under `notes/`, served via
`/api/media`. Endpoints: `GET/POST /api/notes`, `POST /api/notes/<id>/delete`.

## Auto-deploy (GitHub Actions — secrets added; verify it's green)
- `.github/workflows/deploy.yml`: on push to `main`, ships code via **tar-over-SSH** and
  `systemctl restart atelier`. Never touches VPS state (.env, users.json, notes.json, caches).
- Uses tar (not rsync/scp): the VPS has **no rsync** and its **SFTP is chrooted** (paramiko
  sftp ENOENT) — only exec-based transfer works.
- Dedicated deploy key installed on the VPS (`/root/.ssh/authorized_keys`); private key at
  `C:\Users\jimi\Documents\APP\.atelier_deploy_key\id_deploy` (outside the repo).
- **Secrets are added** (`VPS_HOST`=192.3.81.151, `VPS_USER`=root, `VPS_PORT`=22, `VPS_SSH_KEY`).
  First run failed with `hostname contains invalid characters` (pasted secret had a trailing
  newline); a fix to **strip whitespace from the secrets** was pushed (commit `3ce9d7b`).
  ⚠️ Confirm the latest run on the **Actions** tab is green; if not, paste the failing step.

### Manual deploy (fallback)
From `runpod-comfyui/`, tar the changed files and pipe over SSH with the deploy key:
```
tar czf - webapp/app.py webapp/index.html comfy_common.py workflow_i2i.json \
 | ssh -i C:/Users/jimi/Documents/APP/.atelier_deploy_key/id_deploy root@192.3.81.151 \
   "tar xzf - -C /root/atelier && systemctl restart atelier"
```
(Or use the legacy password helper `python C:\...\Blog\.deploy\ssh_run.py "<cmd>"` for remote
commands; `scp_upload.py` is broken by the SFTP chroot — use base64-over-exec or tar instead.)

## VPS deployment
- VPS: RackNerd AlmaLinux 9, `192.3.81.151`. Password creds in
  `C:\Users\jimi\Documents\APP\Blog\.deploy\deploy_env.json` (+ deploy SSH key above).
- App at `/root/atelier/` (comfy_common + workflows) and `/root/atelier/webapp/`. Runs as
  systemd **`atelier`** on :8000 (`systemctl restart atelier`). ffmpeg static in /usr/local/bin.
- nginx vhost `/www/server/panel/vhost/nginx/studio.thecristinaadam.com.conf` proxies :8000
  (300m body, 900s timeouts). Blog (node :3000) + aaPanel nginx untouched — DO NOT disturb.

## Public URL
**https://studio.thecristinaadam.com** — live, Cloudflare-proxied, Full SSL, DNS A → 192.3.81.151.

## ComfyUI tunnel + Cloudflare Access
- `comfy.thecristinaadam.com` = cloudflared tunnel (home PC → ComfyUI on :8189), behind CF Access.
  VPS reaches it with an Access service token (`CF_ACCESS_CLIENT_ID/SECRET` in VPS `.env`).
- `Windows_Run_GPU.bat` (in `I:\@home\jimi\Documents\ComfyUI_V82\`) launches ComfyUI on :8189.
  **`--auto-launch` removed** (was opening a browser tab every start).

## Home agent — remote Start/Stop ComfyUI
- `home_agent/agent.py`: Flask on home PC :8190 (`/status` `/start` `/stop`, `x-agent-secret`),
  published as **agent.thecristinaadam.com** via the same tunnel. VPS `/api/start-comfy` /
  `/api/stop-comfy` call it when `AGENT_URL`/`AGENT_SECRET` set.
- **Fix this session:** `Start_Agent.bat` now calls the full python path
  `C:\Users\jimi\miniconda3\python.exe` (a logon/detached shell lacks conda's PATH, so bare
  `python` had no Flask → autostart silently failed). Auto-starts at logon via the Startup folder.
- If "Start ComfyUI" shows "ComfyUI host is offline", the home PC is off or the agent isn't
  running — run `Start_Agent.bat`.

## Reel library — R2 via Cloudflare Worker
- R2's per-account S3 endpoint has a **broken TLS cert** (boto3 can't connect). Workaround: a
  Worker `reels-proxy` at `https://reels-proxy.cristina-studio.workers.dev` (valid cert,
  `x-auth` secret); `r2_store.py` talks to it (`R2_PROXY_URL`/`R2_PROXY_SECRET` in VPS `.env`).
- Gallery, Reels, Notes media all flow through this Worker; browser never sees the secret
  (`/api/media` proxies). Worker source is inline in the deploy (not in repo); edit via CF API
  (account `ea51aa6cf4958fdf86555ce6ca27bf48`, subdomain `cristina-studio`).
- Reel features: unique filenames, search/sort, admin-only folders, IG `cookies.txt` login.

## Cloudflare API token
- Broad token (`cfat_...`, "For Claude") for zone/Access/Workers/R2. Zone
  `thecristinaadam.com` = `ed3bab68604a0ad5f4cbb78139123a2b`. If expired, user mints a new one.

## Known environment quirk
- The **home PC can't reach some Cloudflare TLS endpoints** (R2, workers.dev) — test R2/Worker
  from the **VPS**, not locally. Local ComfyUI generation works fine on the home PC.

## Auth / login gate
- All routes require login (`before_request`). First signup = admin (active); others pending.
  Admin page activates/disables/promotes/deletes. Users in `webapp/users.json` (hashed),
  session secret `webapp/.secret` (both gitignored).

## What's verified working
- Local + VPS: T2I and I2I generation (async, through the tunnel); describe (Qwen, follows
  instructions, face kept in frame); Lightning + helper/NSFW LoRA pickers; Gallery; Reels;
  Sticky Board; live progress; remote Start/Stop; batch chunking (`max_batch=2`).

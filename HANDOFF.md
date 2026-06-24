# Atelier Character Studio — Handoff

Last updated by Claude (Opus 4.8), 2026-06-24. The big cloud + motion work happened this
session — read the "CLOUD STATE" and "MOTION MODE" sections below first. Original intent in
`runpod-serverless-build-plan.md`. Memory files: `runpod-cloud-build-state`, `video-wan-animate`.

## ⏭️ NEXT (in order)
1. **VIDEO (Wan Animate) on cloud** — the user's ACTUAL primary goal (images they run locally;
   they need *video* on cloud for 2 teammates). **Already works LOCALLY** (5090 via the app's
   Local target). To put it on cloud (billable phase, user is cost-sensitive — confirm first):
   a. **Dockerfile**: add video node packs — `kijai/ComfyUI-WanVideoWrapper`,
      `kijai/ComfyUI-WanAnimatePreprocess`, `Kosinkadink/ComfyUI-VideoHelperSuite`,
      `JPS-Nodes`, `rgthree-comfy`, `Fannovel16/ComfyUI-Frame-Interpolation` (RIFE). KJNodes
      already in image.
   b. **Rebuild image** via `build-worker.yml` (free) — it auto-bakes the video `comfy_common`
      + `workflow_video.json` (both committed).
   c. **Add video models to the volume** (~+25 GB → ~85 GB, OR drop the 28 GB image t2v UNet
      since video doesn't use it → ~57 GB). Files: `Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2`,
      `clip_vision_h`, the 5 video LoRAs (relight/Seko/FastWan/Pusa/Fun under wan/WanLightning),
      ONNX pose (vitpose_h_wholebody, yolov10m, yolox_l, dw-ll_ucoco), RIFE `flownet.pkl`.
      umt5-fp8 + vae already on the volume (hardlink to the path the video wf expects). On H:/I:.
   d. Point the endpoint template at the new image SHA; needs a **48 GB+ GPU**.
   e. Test one cloud motion gen.
2. **Sync Lenovo (+ other helper LoRAs) to the cloud volume** for image gen — quick (~$0.30 pod).
   `.cloud_loras.json` (local + VPS `/root/atelier/webapp/`) lists what's on the volume.
3. **⚠️ ROTATE LEAKED KEYS**: RunPod API key + OpenRouter key + HF write token were all pasted
   in chat / are on the VPS. Mint new ones, update VPS `.env` + the MCP + HF.
4. Optional: per-character trigger words; protect agent.thecristinaadam.com with Access.

## ✅ CLOUD STATE (image path is LIVE on the VPS this session)
- **Endpoint** `d27ehaezfyja3o` (serverless, workersMin=0 → $0 idle), template `4fo2wrxxci`,
  **EU-RO-1**, volume attached. GPU list set live; cheap-first.
- **Volume** `atelier-models` id `3qu8532k8s` (60 GB, EU-RO-1) — image models + 6 char LoRAs +
  2 lightning LoRAs (~56 GB, verified). ~$4-7/mo storage = the only ongoing cost.
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

# Atelier Character Studio — Handoff

Last updated by Claude (Opus 4.8). Read this first, then `runpod-serverless-build-plan.md`
for original intent. The OpenRouter-vision task (old `PLAN-openrouter-vision.md`) is **DONE**.

## ⏭️ NEXT (in order)
1. **Turn on auto-deploy** — add 4 GitHub secrets (see "Auto-deploy" below). Until then,
   deploy is manual via tar-over-SSH (command below).
2. **Add the VIDEO-gen workflow** — user has 1 video wf to add as a new mode. Get the wf
   JSON + input/output spec. Decide local-only vs cloud-too (changes RunPod sizing). Reels
   already handles video preview/R2. Do before RunPod so the model list is locked once.
3. **RunPod cloud path** — make the Cloud toggle work. Build the `CLOUD_LORAS` manifest +
   target-aware LoRA/character filtering at this point (see "LoRA system" + the
   `runpod-lora-manifest` memory). Recommended: T2I first, GPU L40S 48 GB, image from the
   GitHub repo (`runpod-comfyui/Dockerfile`), models on a network volume. Set
   `RUNPOD_ENDPOINT_ID`/`RUNPOD_API_KEY` in VPS `.env`. RunPod MCP connected; account empty.
4. Optional: per-character trigger words (currently one editable default `ing2lorance`);
   protect agent.thecristinaadam.com with an Access app; real IG reel download test.

## ⚠️ Uncommitted work
This whole session's changes are **uncommitted on branch `feature/openrouter-vision`** and
deployed to the VPS manually. They are NOT on `main` and NOT pushed. Before auto-deploy is
useful, the work must land on `main` (which is the deploy trigger).

## Source control
- GitHub: **https://github.com/AbulH88/AtelierStudio**, primary branch **`main`**.
  Current working branch: `feature/openrouter-vision` (not merged/pushed).
- `dev`/`master` are stale duplicates — use `main`. No secrets tracked (only `.env.example`).

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
- `handler.py` — RunPod serverless entrypoint (thin wrapper; passes `event["input"]` through).
- `Dockerfile`, `start.sh` — RunPod image (ComfyUI + KJNodes + RES4LYF + sageattention;
  **QwenVL clone removed** by prev work).
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

## Auto-deploy (GitHub Actions — built, NOT yet active)
- `.github/workflows/deploy.yml`: on push to `main`, ships code via **tar-over-SSH** and
  `systemctl restart atelier`. Never touches VPS state (.env, users.json, notes.json, caches).
- Uses tar (not rsync/scp): the VPS has **no rsync** and its **SFTP is chrooted** (paramiko
  sftp ENOENT) — only exec-based transfer works.
- A dedicated deploy key is installed on the VPS (`/root/.ssh/authorized_keys`); private key at
  `C:\Users\jimi\Documents\APP\.atelier_deploy_key\id_deploy` (outside the repo).
- **To activate:** add repo secrets in GitHub → Settings → Secrets → Actions:
  `VPS_HOST`=192.3.81.151, `VPS_USER`=root, `VPS_PORT`=22, `VPS_SSH_KEY`=(that private key).

### Manual deploy (until auto-deploy is on)
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

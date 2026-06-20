# Atelier Character Studio — Handoff

Last updated by Claude (Opus 4.8). Read this first, then `runpod-serverless-build-plan.md` for original intent.

## What this is
A web app that runs custom **Wan 2.2 ComfyUI** character workflows for ~3 people, on
either the **local 5090** or **RunPod serverless**, with an Instagram **reel library**
stored in Cloudflare R2. Built from `runpod-serverless-build-plan.md`.

## Repo layout (`runpod-comfyui/`)
- `comfy_common.py` — shared workflow logic (build + run via ComfyUI HTTP API). Used by
  BOTH the local web app and the RunPod handler so they behave identically. Sends
  **Cloudflare Access** headers (`CF_ACCESS_*` env) on every ComfyUI call.
- `workflow_i2i.json` — Video→Character: frame → QwenVL auto-caption → Wan 2.2 I2I + LoRAs.
- `workflow_t2i.json` — Text→Character: two-stage Wan 2.2 (high/low noise) + LoRAs. **Fixed
  schedule (12 steps, 0→4 / 4→12); steps/denoise NOT user-editable here — do not change.**
- `handler.py` — RunPod serverless entrypoint (thin wrapper over comfy_common). For the cloud path.
- `Dockerfile`, `start.sh` — RunPod image (ComfyUI + KJNodes + RES4LYF + QwenVL-Mod + sageattention).
- `Start_Studio.bat` — one-click local launch (web app + opens browser).
- `webapp/` — the Flask app + single-page UI (`app.py`, `r2_store.py`, `index.html`).
  - `.env` is gitignored; `.env.example` documents all vars.

## Workflow facts (validated against live ComfyUI)
- Models on `H:/ConfiuiModels` (local). Wan 2.2 low-noise 14B fp16 (27GB), umt5_xxl, wan_2.1_vae,
  lightx2v + Lenovo helper LoRAs, ~14 character LoRAs under `loras/wan/Own/*`.
- Custom node fields confirmed: QwenVL uses `custom_prompt`/`num_beams`/`frame_count`/`keep_last_prompt`
  (NOT prompt/top_k). Samplers `res_2s` + schedulers `bong_tangent`(i2i)/`beta57`(t2i) exist.
- I2I default steps 8 (editable), denoise 0.65 (editable). Character picker is two-level:
  character → checkpoint (all `.safetensors` in that char's folder).

## Compute paths
- **Local:** app → `http://127.0.0.1:8189` (ComfyUI; note port **8189**, set in `Windows_Run_GPU.bat`).
- **Cloud:** app → RunPod endpoint (NOT set up yet — `RUNPOD_*` env empty; Cloud toggle exists in UI).
- Local/Cloud toggle + auto-detect in the header. `/api/health` checks both.

## VPS deployment (DONE — app is live there)
- VPS: RackNerd AlmaLinux 9, `192.3.81.151`. Creds in `C:\Users\jimi\Documents\APP\Blog\.deploy\deploy_env.json`.
  Run remote commands with `python C:\...\Blog\.deploy\ssh_run.py "<cmd>"`.
- App at `/root/atelier/` (comfy_common + workflows) and `/root/atelier/webapp/` (app.py, r2_store.py,
  index.html, .env). Runs as **systemd service `atelier`** on port 8000 (`systemctl restart atelier`).
- ffmpeg = static build in /usr/local/bin. Python deps via `python3 -m pip` (system py 3.9).
- **NOT yet exposed on a public subdomain** — only on VPS `127.0.0.1:8000`. Blog (node :3000) + aaPanel
  nginx (:80/:443) are untouched — DO NOT disturb them.

## ComfyUI tunnel + Cloudflare Access
- `comfy.thecristinaadam.com` = cloudflared tunnel from home PC → ComfyUI, protected by **Cloudflare Access**
  (login wall). The VPS reaches it with an Access **service token** (`atelier-vps`):
  client_id + secret are in the VPS `/root/atelier/webapp/.env` as `CF_ACCESS_CLIENT_ID/SECRET`.
  A policy ("atelier-vps service auth", non_identity) was added to the `comfy` Access app.
- ⚠️ At handoff, the service token still returned 302 (login) — likely propagation. RE-TEST:
  `curl -H "CF-Access-Client-Id: <id>" -H "CF-Access-Client-Secret: <secret>" https://comfy.thecristinaadam.com/system_stats`
  Expect 200 (or 502 if home ComfyUI is down). If still 302 after a while, check the Access app policy.

## Reel library — R2 via Cloudflare Worker (IMPORTANT)
- R2's per-account **S3 endpoint** (`<acct>.r2.cloudflarestorage.com`) has a **broken TLS cert** —
  handshake fails everywhere (confirmed via openssl, IPv4+IPv6, home + VPS). boto3 cannot connect.
  This is a Cloudflare-side cert issue, not code/token. (May self-resolve or need CF support.)
- WORKAROUND (working): a Cloudflare **Worker** `reels-proxy` reads/writes the `reels` bucket via an
  internal binding, served on `https://reels-proxy.cristina-studio.workers.dev` (valid cert), secured
  by an `x-auth` secret. `r2_store.py` talks to this Worker. Worker URL + secret in VPS `.env`
  (`R2_PROXY_URL`, `R2_PROXY_SECRET`). Verified: create folder / list / put / get / delete all work from VPS.
- The browser never sees the secret — `/api/reels/media` proxies previews/downloads through the app.
- Worker source is inline in the deploy (not in repo). To redeploy/edit it, use the CF API
  (account `ea51aa6cf4958fdf86555ce6ca27bf48`, workers.dev subdomain `cristina-studio`).

## Cloudflare access for agents
- A broad **Cloudflare API token** (`cfat_...`, "For Claude", expires soon) was used for zone/Access/Workers/R2.
  Zone `thecristinaadam.com` = `ed3bab68604a0ad5f4cbb78139123a2b`. If expired, the user must mint a new one.

## Known environment quirk
- The **home PC cannot reach some Cloudflare TLS endpoints** (R2, workers.dev) — handshake fails
  (likely Cloudflare WARP/AV interception). So test R2/Worker from the **VPS**, not locally. Local
  ComfyUI generation still works fine on the home PC.

## Auth / login gate
- All routes require login (`before_request` gate). `webapp/login.html` = sign-in / request-access page.
- **First signup auto-becomes admin (active); everyone else = pending** until an admin activates them.
- Admin page (nav item, admin-only) lists users → activate / disable / make-admin / delete.
- Users stored in `webapp/users.json` (werkzeug-hashed passwords); session secret in `webapp/.secret`.
  Both gitignored. On the VPS, `users.json` was wiped at handoff so the owner's first signup = admin.
- API: `/api/login`, `/api/signup`, `/api/logout`, `/api/me`, `/api/users`, `/api/users/<name>/<action>`.

## What's verified working
- Local: T2I and I2I generations on the 5090 (images returned, no errors).
- VPS: app running, reels folder create/list via Worker, R2 reachable.

## Public URL (DONE)
- **https://studio.thecristinaadam.com** is live (Cloudflare-proxied, Full SSL). DNS A → 192.3.81.151.
  nginx vhost: `/www/server/panel/vhost/nginx/studio.thecristinaadam.com.conf` (listen 80+443, shared
  cert `/etc/ssl/cristina/`, proxy_pass 127.0.0.1:8000, client_max_body_size 300m, 900s timeouts).

## TODO / next steps
1. **Confirm VPS→ComfyUI** end-to-end: an IP-bypass Access policy for 192.3.81.151 lets the VPS through
   (verified 502 = past Access, tunnel/home-ComfyUI was down). Re-test with home ComfyUI + tunnel up → expect 200.
3. **Start/Stop ComfyUI remotely**: current buttons run a local `.bat` (only works when app is on the
   same PC). For VPS, build a small **home agent** behind the tunnel/Access, or go manual/always-on.
4. **RunPod cloud path**: create endpoint + (network volume or baked models), set `RUNPOD_*` in VPS .env.
5. Optional: real IG reel download test (yt-dlp may need an Instagram cookies file for private/age-gated).

## Branches
- Work on `dev`, merge to `master` (main). Both currently at the Worker-proxy commit.

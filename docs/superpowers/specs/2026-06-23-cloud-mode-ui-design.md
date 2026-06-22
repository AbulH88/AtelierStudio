# Cloud (RunPod) Mode UI — Design

Date: 2026-06-23
Status: BUILT + verified (front-end + app.py seam). Backend unit-tested
(`webapp/test_cloud.py`, 15 tests); cloud card rendered live via Playwright. Goes
fully live once real RunPod creds + a `.cloud_loras.json` manifest exist — no code
change needed, just env + the manifest file. See `HANDOFF.md` "NEXT" #1.

## What shipped (this session)
- `app.py`: `_price_per_sec()` + GPU price table; `_cloud_lora_set()` manifest
  loader; `_cloud_status()` real RunPod /health call (degrades gracefully);
  endpoints `GET /api/cloud/info`, `GET /api/cloud/status`,
  `POST /api/cloud/request-sync`, `GET /api/cloud/sync-requests` (admin).
- `index.html`: cloud status card (warming strip + health + cost tiles), header
  spend chip, per-gen cost line, cloud-aware LoRA list with grey-out + request-sync,
  Generate blocked when a selected LoRA isn't on the volume.
- `webapp/test_cloud.py`: 15 passing tests (cost map, manifest, status parsing,
  endpoints, request-sync dedupe).
- `.gitignore`: `.cloud_loras.json`, `cloud_sync_requests.json`.

## Goal
Flesh out the **Cloud** compute target in the existing Studio page so a user can run
generations on a RunPod serverless endpoint with the same confidence as Local. Reuse the
existing design language (Fraunces/Hanken/JetBrains Mono, amber-on-near-black, pill toggles,
numbered cards). No new theme. The `Local | Cloud` toggle and header status LED already exist.

## Scope (the four concerns)
1. **Cold-start / warming state**
2. **Cost awareness** (estimates only)
3. **LoRA availability** vs the `CLOUD_LORAS` network volume
4. **Endpoint health / errors**

## Components

### A. Cloud status card (new)
- Renders **only when `S.target === 'cloud'`**, directly below the mode switch (above the
  existing left-column cards). Hidden entirely on Local.
- Header: endpoint label — GPU type, VRAM, region (e.g. `L40S · 48GB · us-east`).
- **Cold-start strip:** when the endpoint has no warm worker and a job is queued/initializing,
  show a shimmering progress bar + live ETA ("~24s remaining") + one line of copy explaining
  the worker stays warm ~5 min so later gens are instant.
- **Three stat tiles:**
  - **Health** — `Healthy · N/M active` (green); turns rose/red on endpoint error/throttle.
  - **This generation** — `≈ $0.03 · ~25s` (estimate).
  - **Session spend** — `$0.18 · 6 gens` (running tally, session-scoped).

### B. Header additions
- **Spend chip:** small amber-outlined pill `≈ $X today` next to the status LED. Glanceable.
- **Status LED label:** reuse existing LED; in Cloud it reflects endpoint state —
  `warming` (amber) / `RunPod · cloud` ready (green) / `cloud not set` / error (rose).

### C. Per-generation cost line
- Next to the Generate button: `≈ $0.03 each · 2 variations ≈ $0.06` — multiplies the
  per-gen estimate by the current variation count.

### D. Cloud-aware LoRA picker
- Each LoRA row gets a status dot + tag.
- **On volume** → green dot, `on volume` tag, selectable normally.
- **Not on volume** → DECISION: **grey out + request sync**. Row is disabled/greyed with a
  rose `not on cloud volume` label and a `request sync` button. The button records which LoRA
  the user wants pushed to the volume (a queue/log the user reviews later — it does NOT auto-push).
- On **Local**, all LoRAs show normally with no tags (current behavior).

## Decisions (locked)
- **Cost source:** *Estimates only.* Computed client-side as `gpu_$per_sec × measured_gen_seconds`.
  No RunPod billing API. "Session spend" resets per browser session (in-memory).
- **Missing LoRA behavior:** *Grey out + request sync* (as above). Not hidden, not allow-with-warn.

## Data / wiring notes (for the future build)
- Needs a **`CLOUD_LORAS` manifest** of what's on the network volume (see `runpod-lora-manifest`
  memory). The character/helper LoRA lists become **target-aware**: full list on Local, manifest-
  filtered tags on Cloud.
- Per-gen `$ /sec` comes from a small static GPU price map keyed by the endpoint GPU type.
- Health/warming state comes from RunPod endpoint status + job lifecycle (queued → initializing
  → running). The existing async job poller (`/api/generate/result`) can surface a `phase` field.
- `request sync` posts to a new endpoint that appends to a server-side wishlist (no auto-sync).

## Out of scope for this UI
- Video (Wan Animate) cloud UI — separate, later.
- Actually building the RunPod volume/image/endpoint (the backend this UI talks to).
- Real billing reconciliation.

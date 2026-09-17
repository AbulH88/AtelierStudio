# Atelier Studio RunningHub Cloud Handoff

Last updated: 2026-09-18

## Current deployed state

The production site is `https://studio.thecristinaadam.com`. The following work is deployed from `main`:

- `593d9a8` — cancel cloud jobs and prevent duplicate runs
- `c0b7d0a` — Krea2 cloud image workflow and Admin LoRA registry
- `be09306` — Krea2 base-denoise and Describe-with-AI controls
- `ca65094` — Cloud workspace responsive-width fix

The latest deployment workflow completed successfully. The primary implementation files are:

- `runpod-comfyui/webapp/app.py`
- `runpod-comfyui/webapp/index.html`
- `runpod-comfyui/webapp/test_runninghub_cloud.py`

Do not add or commit the unrelated untracked scripts and state files currently visible at the repository root.

## Krea2 Image-to-Image HQ

Cloud Studio now has **Image → Krea2 Image to Image HQ**. It supports:

- Source-image click upload and drag-and-drop
- Prompt entry
- Describe source with AI
- Existing Local Studio resolution presets
- Admin-configured character and version selection
- Base-denoise slider plus exact numeric input
- Persistent RunningHub queue, duplicate-run prevention, cancellation, and Gallery import
- Responsive wide, tablet, and mobile layouts

The Describe-with-AI section has independent Cloud controls for Vision Model, Style Preset, Body Type, Shot Type, Detail Level, Explicit/NSFW, Clothing Note, and Custom Instruction. These use the existing `/api/describe` endpoint and the same server-side prompt construction as Local Studio; they do not read hidden Local Studio controls.

## Confirmed RunningHub mapping

Workflow ID: `2100309003213901825`

| Purpose | Node | Field |
|---|---:|---|
| Source image | 33 | `image` |
| Positive prompt | 5 | `text` |
| Width | 13 | `width` |
| Height | 13 | `height` |
| Character LoRA | 46 | `lora_name` and `LoraLoaderState` |
| User-controlled base denoise | 4 | `denoise` |

Node `1` is the second ClownsharKSampler. Its denoise remains fixed in the published workflow at `0.27`; Atelier intentionally sends no override for node 1. Node 4 defaults to `0.60` in Cloud Studio and accepts `0.00` through `1.00` in `0.01` increments.

Node 46 receives only the selected character version. `LoraLoaderState` is generated for each job with `sm: 1`, `sc: 1`, and `on: true`.

## Private LoRA administration

RunningHub's public model-list API does not expose the account's private **My Models** entries. Atelier therefore stores a small server-side character/version registry in `runpod-comfyui/webapp/runninghub_loras.json` at runtime.

Admins manage it under **Admin → RunningHub Characters**:

1. Add a character.
2. Add one or more versions.
3. Enter the exact `.safetensors` filename used by RunningHub.
4. Choose one default version.
5. Enable the character and desired versions.
6. Save characters.

The backend normalizes `models/loras/Filename.safetensors` to `Filename.safetensors`. The seeded fallback is:

- Character: `SophieJoyTalking`
- Version: `V1.0`
- Filename: `Sophie-step00003000.safetensors`

The application does not upload LoRA model files. The LoRA must already exist in the **My Models** storage belonging to the RunningHub account whose API key executes the job. A shared/global key gives its users access to that key owner's private models. A user assigned a key from another RunningHub account can use a registered filename only if that account also contains the model under the expected filename.

## RunningHub credentials and concurrency

- An admin may assign one global RunningHub key or a private key to a user.
- Keys are encrypted server-side and are never returned to the browser.
- Jobs sharing a key obey that key's configured concurrency. With concurrency `1`, simultaneous requests are serialized in Atelier's queue.
- Generate buttons enter a loading/disabled state while the workflow has an active job.
- Waiting jobs cancel locally; submitted jobs call RunningHub's cancellation endpoint.

## Tests and known test condition

The focused suite currently passes:

```powershell
cd C:\Users\jimi\Documents\APP\Runpod\runpod-comfyui\webapp
python -m py_compile app.py
pytest -q test_runninghub_cloud.py
```

Latest result: `16 passed`.

Inline JavaScript can be syntax-checked with:

```powershell
node -e "const fs=require('fs'),s=fs.readFileSync('index.html','utf8');for(const m of s.matchAll(/<script(?:\\s[^>]*)?>([\\s\\S]*?)<\\/script>/gi))new Function(m[1]);console.log('javascript ok')"
```

The broader `test_cloud.py` suite has one pre-existing assertion mismatch in `test_cloud_status_endpoint_unconfigured`: it expects only `{"configured": false}`, while the endpoint also returns `agent_up`, `gated`, and `open`. This is unrelated to the RunningHub feature and was not changed.

## Important implementation details

- Krea jobs use workflow key `krea2_i2i_hq`.
- The backend resolves dimensions from server-owned `RES_PRESETS`; browsers cannot submit arbitrary dimensions.
- The backend resolves character/version IDs against the server-owned LoRA registry; regular users cannot submit arbitrary filenames.
- Each queued job stores the resolved filename and denoise value so later Admin edits cannot mutate an existing job.
- Successful image results are downloaded from RunningHub and stored below `gallery/cloud/` with their image extension.
- The responsive blank-space bug came from `.cloud-workspace` inheriting Local Studio's global `<main>` margin. The Cloud override must retain `margin:0; max-width:none; display:block`.

## Recommended next work

1. Add the user's remaining private characters and every actual RunningHub version filename through Admin.
2. Run one controlled Krea2 generation with a low-cost resolution and confirm node 46 resolves the selected private model.
3. Confirm node 4 receives the chosen denoise and node 1 remains `0.27` in RunningHub task details.
4. Verify the returned image appears in Gallery.
5. Add future Cloud image workflows by reusing the existing credential, queue, upload, cancellation, and result-import helpers. A generalized workflow registry was designed but has not yet been implemented.

## Design references

- `docs/superpowers/specs/2026-09-17-runninghub-krea2-image-workflows-design.md`
- `docs/superpowers/specs/2026-09-17-krea2-cloud-controls-design.md`


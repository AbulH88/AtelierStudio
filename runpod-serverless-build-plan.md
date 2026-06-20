# RunPod Serverless ComfyUI — Build Plan

Goal: Run our custom ComfyUI workflow (Wan2.1 + `ing2lorance` LoRA) on RunPod
Serverless. Pay only per generation. Three people trigger the same workflow via
an API endpoint — no one touches the local 5090.

This plan is written for Claude Code to execute step by step. Build and test
**locally with Docker first**, then deploy. Do not deploy untested.

---

## 0. Prerequisites (do these before any code)

- [ ] Docker Desktop installed and running locally.
- [ ] RunPod account created, billing added, API key generated.
- [ ] Workflow exported from local ComfyUI as **API format** JSON
      (`Save (API Format)`, NOT the normal workflow save). Save as `workflow_api.json`.
- [ ] List every custom node the workflow uses. In ComfyUI, open the workflow,
      note each custom node's GitHub repo URL. This list is critical — a missing
      node = silent failure at runtime.
- [ ] Identify every model file the workflow loads: base checkpoint, the
      `ing2lorance` LoRA, VAE, any upscale/interpolation models. Note exact
      filenames and which ComfyUI subfolder each belongs in
      (`models/checkpoints`, `models/loras`, etc.).

> ⚠️ IP NOTE: The `ing2lorance` LoRA is core business IP. Decide where it lives:
> baked into the image (simplest, but the model sits in RunPod's registry) or
> pulled from private storage at boot (more control). Default below = network
> volume, so the model is NOT in the public image.

---

## 1. Repo structure

```
runpod-comfyui/
├── Dockerfile
├── handler.py            # RunPod serverless entrypoint
├── workflow_api.json     # exported workflow (API format)
├── start.sh              # boots ComfyUI in background, then handler
├── requirements.txt
├── test_input.json       # sample job for local testing
└── README.md
```

---

## 2. Dockerfile

Base it on an existing ComfyUI + CUDA image to save hours. Requirements:

- Start from a CUDA + Python base (e.g. `nvidia/cuda:12.4.1-runtime-ubuntu22.04`)
  or an existing community ComfyUI worker base if one is current.
- Clone ComfyUI.
- Clone EACH custom node repo from the list in step 0 into
  `ComfyUI/custom_nodes/` and pip-install each one's `requirements.txt`.
- Install `runpod` Python package.
- Do NOT bake large models into the image (keeps image small, protects IP) —
  models come from a network volume mounted at runtime.
- Copy in `handler.py`, `start.sh`, `workflow_api.json`.

Deliverable: a Dockerfile that builds clean with no missing-node errors.

---

## 3. Models: network volume (not baked in)

- Create a RunPod **Network Volume** in the same region as the serverless endpoint.
- Upload models into it matching ComfyUI's expected structure:
  - `checkpoints/<base_model>.safetensors`
  - `loras/ing2lorance.safetensors`
  - plus VAE / interpolation models as needed.
- At runtime the volume mounts (commonly at `/runpod-volume`); symlink or point
  ComfyUI's `models/` paths at it so the workflow finds everything.

---

## 4. start.sh

- Launch ComfyUI in the background (`--listen 127.0.0.1 --port 8188`),
  headless, no preview.
- Wait until the ComfyUI API is responsive (poll `http://127.0.0.1:8188`).
- Then start the RunPod handler.

---

## 5. handler.py (the core piece)

This is where most of the real work is. It must:

1. Receive a job: `event["input"]` containing the variable params
   (e.g. `prompt`, `negative_prompt`, `seed`, `width`, `height`).
2. Load `workflow_api.json`.
3. Inject the params into the correct nodes by node ID. (You must map which node
   ID holds the prompt text, which holds the seed, etc. — pull these IDs from the
   exported JSON. Document the mapping in README.)
4. POST the workflow to the local ComfyUI `/prompt` endpoint.
5. Poll `/history/<prompt_id>` until the run completes.
6. Read the output image/video from ComfyUI's output dir.
7. Return it — base64 in the response for small images, OR upload to S3/bucket
   and return a URL for video (RunPod response size limits make base64 a bad
   idea for video).

Build defensively: if a node is missing or a model fails to load, surface the
actual ComfyUI error in the handler response — do not return a silent empty result.

---

## 6. Local test BEFORE deploy

- [ ] `docker build` succeeds with zero errors.
- [ ] Run the container locally with the RunPod test harness
      (`handler.py` supports local `--test_input test_input.json`).
- [ ] `test_input.json` contains one real prompt matching the Cristina workflow.
- [ ] Confirm output matches a local 5090 generation: same LoRA fidelity,
      correct resolution, interpolation present if the workflow includes it.
- [ ] Only proceed once a local run produces a correct image/video.

---

## 7. Deploy to RunPod Serverless

- [ ] Push image to a registry (Docker Hub or RunPod's registry).
- [ ] Create a Serverless endpoint: select GPU tier (match VRAM to the workflow —
      video gen needs a lot; don't under-spec), attach the network volume,
      point it at the pushed image.
- [ ] Set min workers = 0 (so you pay nothing when idle) and a sane max.
- [ ] Note the endpoint ID + API key.

---

## 8. Friend-facing trigger

Pick the simplest thing that works for 3 people:

- **Option A (fastest):** a small Python script each person runs — posts params
  to the endpoint, saves the returned image. Zero hosting.
- **Option B (nicer):** a one-page web form (host on the VPS) that calls the
  endpoint and shows the result. More work; do only if Option A annoys people.

Start with A. Upgrade only if there's a real complaint.

---

## 9. Cost sanity check (do this with real numbers)

- After ~10 real generations, check the actual RunPod bill.
- Note **cold-start time** — every wake from 0 workers eats paid seconds before
  generating. If you do many small quick gens, cold starts may cost more than
  expected; consider keeping 1 warm worker during active sessions and scaling to
  0 otherwise.
- Compare against: just running the local 5090 with a tunnel. If cloud isn't
  meaningfully cheaper or faster for your actual volume, the local route wins.

---

## Hard checkpoints (do not skip)

1. Custom node list is complete and every node installs in the image — verify
   before anything else.
2. Decide the LoRA IP exposure question (volume vs baked) before uploading.
3. Local Docker run produces a correct generation before deploying.
4. Real bill checked after 10 runs before letting volume scale up.

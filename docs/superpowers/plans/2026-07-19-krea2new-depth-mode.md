# Krea I2I New (depth-ControlNet) mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 6th local-only generation mode, "Krea I2I New" (`mode="krea2new"`), that runs the uploaded photo through DepthAnythingV2 and generates a fresh image conditioned on that depth map via a Krea2 control-LoRA (full denoise, not img2img).

**Architecture:** Same layered pattern as every other mode: a cleaned workflow JSON → a node-id map + `_build_krea2new()` in `comfy_common.py` → a `generate()` dispatch branch → `webapp/app.py` request wiring/gating → `webapp/index.html` mode button + UI state wiring (reusing existing frame-picker pane, aspect picker, and Krea2 character picker).

**Tech Stack:** Python (Flask backend, `comfy_common.py` graph builder), vanilla JS SPA (`webapp/index.html`), pytest.

## Global Constraints

- Design doc: `docs/superpowers/specs/2026-07-19-krea2new-depth-mode-design.md` — every task here traces back to it.
- The workflow file must never contain `sk-or-v1` or `api_key` (leaked-key regression guard, same as `workflow_krea2.json`).
- Local-only mode — no Dockerfile/worker/RunPod changes, mirrors Krea2's local-only gating exactly.
- Follow existing naming/structure conventions from Krea2 (`comfy_common.py`'s `KREA2` map / `_build_krea2` / `generate()` branch; `app.py`'s `krea2` branch in `_build_input` and `/api/generate`; `index.html`'s `mKrea2`/`paneVideo`/`krea2Chars` wiring) — do not invent new patterns where a Krea2 equivalent already exists.
- Test runner: `"/c/Users/jimi/miniconda3/python.exe" -m pytest tests/<file> -v` from `runpod-comfyui/`.
- Deploy: after all tests pass, commit and push to `main` — GitHub Actions (`deploy.yml`) ships it to the VPS automatically (`systemctl restart atelier`).

---

### Task 1: Cleaned workflow JSON (`workflow_krea2new.json`)

**Files:**
- Create: `runpod-comfyui/workflow_krea2new.json`
- Test: `runpod-comfyui/tests/test_workflow_krea2new_file.py`

**Interfaces:**
- Produces: a ComfyUI graph with these node ids: `2` (KSampler), `3` (VAEDecode), `4` (VAELoader), `6` (CLIPTextEncode/positive), `8` (ConditioningZeroOut/negative), `10` (EmptyLatentImage), `15` (UNETLoader), `18` (CLIPLoader), `31` (DepthAnythingV2Preprocessor), `32` (LoadImage), `33` (Krea2ControlLoRALoader), `34` (Krea2ControlImageEncode), `35` (Krea2ControlApply), `37` (SaveImage), `38` (LoraLoaderModelOnly/character). Nodes `30`, `36`, `39`, `40` from the source export are dropped. Later tasks (`_build_krea2new`) read/write these exact node ids.

- [ ] **Step 1: Write the failing test**

Create `runpod-comfyui/tests/test_workflow_krea2new_file.py`:

```python
import json
import os

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2new.json")


def _load():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_no_leaked_api_key_or_openrouter_node():
    with open(WF_PATH, encoding="utf-8") as f:
        raw = f.read()
    assert "sk-or-v1" not in raw
    assert "api_key" not in raw


def test_resolution_and_caption_nodes_removed():
    graph = _load()
    for nid in ("30", "36", "39", "40"):
        assert nid not in graph, f"node {nid} should have been stripped"


def test_remaining_nodes_present():
    graph = _load()
    expected = {"2", "3", "4", "6", "8", "10", "15", "18",
                "31", "32", "33", "34", "35", "37", "38"}
    assert set(graph.keys()) == expected


def test_latent_size_is_literal_not_linked_to_removed_resolution_node():
    graph = _load()
    assert isinstance(graph["10"]["inputs"]["width"], int)
    assert isinstance(graph["10"]["inputs"]["height"], int)


def test_positive_prompt_has_no_dangling_link():
    graph = _load()
    assert isinstance(graph["6"]["inputs"]["text"], str)


def test_save_node_is_plain_save_image():
    graph = _load()
    assert graph["37"]["class_type"] == "SaveImage"


def test_control_chain_wired_through_character_lora():
    graph = _load()
    # depth-control LoRA stacks on top of the character LoRA, which stacks on the base UNET
    assert graph["38"]["inputs"]["model"] == ["15", 0]
    assert graph["33"]["inputs"]["model"] == ["38", 0]
    assert graph["35"]["inputs"]["control_latent"] == ["34", 0]
    assert graph["2"]["inputs"]["model"] == ["35", 0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd runpod-comfyui && "/c/Users/jimi/miniconda3/python.exe" -m pytest tests/test_workflow_krea2new_file.py -v`
Expected: FAIL — `FileNotFoundError` (workflow_krea2new.json doesn't exist yet).

- [ ] **Step 3: Create the cleaned workflow file**

Create `runpod-comfyui/workflow_krea2new.json` with this exact content (source graph with nodes `30`/`36`/`39`/`40` removed, node `10`'s width/height replaced with literal defaults, node `6`'s text replaced with a literal empty string — both get set at runtime by `_build_krea2new`):

```json
{
  "2": {
    "inputs": {
      "seed": 474731759263502,
      "steps": 8,
      "cfg": 1,
      "sampler_name": "er_sde",
      "scheduler": "simple",
      "denoise": 1,
      "model": ["35", 0],
      "positive": ["6", 0],
      "negative": ["8", 0],
      "latent_image": ["10", 0]
    },
    "class_type": "KSampler",
    "_meta": {"title": "KSampler"}
  },
  "3": {
    "inputs": {"samples": ["2", 0], "vae": ["4", 0]},
    "class_type": "VAEDecode",
    "_meta": {"title": "VAE Decode"}
  },
  "4": {
    "inputs": {"vae_name": "Krea2\\Krea2-HD-vae.safetensors"},
    "class_type": "VAELoader",
    "_meta": {"title": "VAE Loader"}
  },
  "6": {
    "inputs": {"text": "", "clip": ["18", 0]},
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "Positive Prompt"}
  },
  "8": {
    "inputs": {"conditioning": ["6", 0]},
    "class_type": "ConditioningZeroOut",
    "_meta": {"title": "Negative (Zero Out)"}
  },
  "10": {
    "inputs": {"width": 1080, "height": 1920, "batch_size": 1},
    "class_type": "EmptyLatentImage",
    "_meta": {"title": "Empty Latent Image"}
  },
  "15": {
    "inputs": {"unet_name": "Kera2\\krea2_turbo_bf16.safetensors", "weight_dtype": "default"},
    "class_type": "UNETLoader",
    "_meta": {"title": "Load Diffusion Model"}
  },
  "18": {
    "inputs": {"clip_name": "Krea-2\\Huihui-Qwen3-VL-4B-Instruct-abliterated.safetensors", "type": "krea2", "device": "default"},
    "class_type": "CLIPLoader",
    "_meta": {"title": "Load CLIP"}
  },
  "31": {
    "inputs": {"ckpt_name": "depth_anything_v2_vitl.pth", "resolution": 512, "image": ["32", 0]},
    "class_type": "DepthAnythingV2Preprocessor",
    "_meta": {"title": "Depth Anything V2 - Relative"}
  },
  "32": {
    "inputs": {"image": "ComfyUI_00116_.png"},
    "class_type": "LoadImage",
    "_meta": {"title": "Load Image"}
  },
  "33": {
    "inputs": {"lora_name": "Keara2\\mix\\depth-control-lora.safetensors", "strength": 1, "model": ["38", 0]},
    "class_type": "Krea2ControlLoRALoader",
    "_meta": {"title": "Krea2 Control LoRA Loader"}
  },
  "34": {
    "inputs": {
      "resize": "match_latent_size",
      "upscale_method": "lanczos",
      "crop": "center",
      "channel_mode": "rgb",
      "normalize": "none",
      "invert": false,
      "batch_mode": "independent_images",
      "control_image": ["31", 0],
      "vae": ["4", 0],
      "latent": ["10", 0]
    },
    "class_type": "Krea2ControlImageEncode",
    "_meta": {"title": "Krea2 Control Image Encode"}
  },
  "35": {
    "inputs": {"model": ["33", 0], "control_latent": ["34", 0]},
    "class_type": "Krea2ControlApply",
    "_meta": {"title": "Krea2 Control Apply"}
  },
  "37": {
    "inputs": {"filename_prefix": "ComfyUI", "images": ["3", 0]},
    "class_type": "SaveImage",
    "_meta": {"title": "Save Image"}
  },
  "38": {
    "inputs": {"lora_name": "Keara2\\krea2_cristiana\\Cristina-2600.safetensors", "strength_model": 1, "model": ["15", 0]},
    "class_type": "LoraLoaderModelOnly",
    "_meta": {"title": "Load LoRA"}
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd runpod-comfyui && "/c/Users/jimi/miniconda3/python.exe" -m pytest tests/test_workflow_krea2new_file.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add runpod-comfyui/workflow_krea2new.json runpod-comfyui/tests/test_workflow_krea2new_file.py
git commit -m "feat(krea2new): add cleaned depth-controlnet workflow with regression guards"
```

---

### Task 2: Node map + `_build_krea2new()` in `comfy_common.py`

**Files:**
- Modify: `runpod-comfyui/comfy_common.py` (add `KREA2NEW` map near the existing `KREA2` map at line 72; add `_build_krea2new()` right after `_build_krea2()`, currently ending at line 352)
- Test: `runpod-comfyui/tests/test_build_krea2new.py`

**Interfaces:**
- Consumes: `cc._set_lora(graph, nid, path, strength)`, `cc._prompt_with_trigger(inp)`, `cc._apply_sampler_override(graph, inp)` (all existing, unchanged signatures, defined earlier in `comfy_common.py`).
- Produces: `KREA2NEW = {"load_image": "32", "positive": "6", "latent": "10", "base_ksampler": "2", "char": "38"}` and `_build_krea2new(graph, inp, seed, frame_name) -> graph`, consumed by Task 3's `generate()` dispatch.

- [ ] **Step 1: Write the failing test**

Create `runpod-comfyui/tests/test_build_krea2new.py`:

```python
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2new.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_build_krea2new_sets_image_prompt_seed_lora_size():
    graph = _load_graph()
    inp = {"prompt": "a woman in a red dress", "trigger": "ing2lorance",
           "character_lora_path": "Keara2/krea2_cristiana/Cristina-2600.safetensors",
           "character_strength": 0.9, "width": 1024, "height": 1536}
    out = cc._build_krea2new(graph, inp, seed=12345, frame_name="frame_abc.png")
    assert out["32"]["inputs"]["image"] == "frame_abc.png"
    assert out["6"]["inputs"]["text"] == "ing2lorance, a woman in a red dress"
    assert out["2"]["inputs"]["seed"] == 12345
    assert out["38"]["inputs"]["lora_name"] == inp["character_lora_path"]
    assert out["38"]["inputs"]["strength_model"] == 0.9
    assert out["10"]["inputs"]["width"] == 1024
    assert out["10"]["inputs"]["height"] == 1536


def test_build_krea2new_size_defaults_to_1080x1920():
    graph = _load_graph()
    out = cc._build_krea2new(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    assert out["10"]["inputs"]["width"] == 1080
    assert out["10"]["inputs"]["height"] == 1920


def test_build_krea2new_applies_sampler_override():
    graph = _load_graph()
    inp = {"prompt": "x", "sampler_override": {"cfg": 4, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._build_krea2new(graph, inp, seed=1, frame_name="f.png")
    assert out["2"]["inputs"]["cfg"] == 4
    assert out["2"]["inputs"]["sampler_name"] == "euler"
    assert out["2"]["inputs"]["scheduler"] == "karras"


def test_build_krea2new_no_character_zeroes_strength():
    graph = _load_graph()
    out = cc._build_krea2new(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    assert out["38"]["inputs"]["strength_model"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd runpod-comfyui && "/c/Users/jimi/miniconda3/python.exe" -m pytest tests/test_build_krea2new.py -v`
Expected: FAIL — `AttributeError: module 'comfy_common' has no attribute '_build_krea2new'`.

- [ ] **Step 3: Add the node map and build function**

In `runpod-comfyui/comfy_common.py`, right after the existing `KREA2` map (ends at line 75, right before the blank line / `def _bypass_node`), add:

```python

# Krea I2I New (workflow_krea2new.json) — depth-ControlNet guided generation:
# DepthAnythingV2 map of the source photo drives a Krea2ControlLoRA + Apply
# chain that conditions a full (denoise 1) KSampler pass from an empty latent.
# NOT img2img (unlike KREA2 above) — no VAEEncode of the source pixels.
KREA2NEW = {"load_image": "32", "positive": "6", "latent": "10",
            "base_ksampler": "2", "char": "38"}
```

Then, right after the end of `_build_krea2()` (after its `return graph` and blank lines, before the `# --- high level ---` comment block), add:

```python
def _build_krea2new(graph, inp, seed, frame_name):
    """Krea I2I New: depth-ControlNet guided generation. The source photo drives
    a DepthAnythingV2 map -> Krea2ControlLoRA/Apply chain that conditions a
    full-denoise KSampler pass from an empty latent sized by the app's aspect
    picker (same width/height convention as _build_t2i). Single character
    LoRA, no Lightning/helper-LoRA chain, no refine pass."""
    nm = KREA2NEW
    graph[nm["load_image"]]["inputs"]["image"] = frame_name
    graph[nm["latent"]]["inputs"]["width"] = int(inp.get("width", 1080))
    graph[nm["latent"]]["inputs"]["height"] = int(inp.get("height", 1920))
    graph[nm["positive"]]["inputs"]["text"] = _prompt_with_trigger(inp)
    graph[nm["base_ksampler"]]["inputs"]["seed"] = seed
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    _apply_sampler_override(graph, inp)
    return graph
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd runpod-comfyui && "/c/Users/jimi/miniconda3/python.exe" -m pytest tests/test_build_krea2new.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add runpod-comfyui/comfy_common.py runpod-comfyui/tests/test_build_krea2new.py
git commit -m "feat(krea2new): add KREA2NEW node map + _build_krea2new()"
```

---

### Task 3: `generate()` dispatcher wiring

**Files:**
- Modify: `runpod-comfyui/comfy_common.py:513-531` (the `generate()` function's upload-once check and batching loop)
- Test: `runpod-comfyui/tests/test_generate_krea2new_dispatch.py`

**Interfaces:**
- Consumes: `cc._build_krea2new` (from Task 2), `cc.upload_image`, `cc.run` (both existing, monkeypatched in the test).
- Produces: `cc.generate(base, workflow_dir, inp)` now handles `inp["mode"] == "krea2new"`, returning `{"images": [...], "seed": int}` — same shape every other image mode returns.

- [ ] **Step 1: Write the failing test**

Create `runpod-comfyui/tests/test_generate_krea2new_dispatch.py`:

```python
import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..")


def test_generate_dispatches_krea2new_without_network(monkeypatch):
    calls = {}

    def fake_upload_image(base, raw_bytes):
        calls["uploaded"] = raw_bytes
        return "uploaded_frame.png"

    def fake_run(base, graph, timeout=900, client_id=None, out_node=None):
        calls["graph"] = graph
        return ["ZmFrZQ=="]   # base64 "fake"

    monkeypatch.setattr(cc, "upload_image", fake_upload_image)
    monkeypatch.setattr(cc, "run", fake_run)

    inp = {"mode": "krea2new", "prompt": "a woman in red",
           "image_b64": base64.b64encode(b"fake-image-bytes").decode(),
           "variations": 1, "seed": 42}
    out = cc.generate("http://fake-comfy", WORKFLOW_DIR, inp)

    assert out == {"images": ["ZmFrZQ=="], "seed": 42}
    assert calls["uploaded"] == b"fake-image-bytes"
    assert calls["graph"]["32"]["inputs"]["image"] == "uploaded_frame.png"
    assert calls["graph"]["6"]["inputs"]["text"] == "ing2lorance, a woman in red"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd runpod-comfyui && "/c/Users/jimi/miniconda3/python.exe" -m pytest tests/test_generate_krea2new_dispatch.py -v`
Expected: FAIL — `FileNotFoundError` for `workflow_krea2new.json` looked up as-is, or a `KeyError`/wrong-branch failure, because `generate()` doesn't route `krea2new` to `_build_krea2new` yet (it currently falls through to the `else: graph = _build_t2i(...)` branch, and `_build_t2i` will raise a `KeyError` on `T2I`'s node ids not matching this graph).

- [ ] **Step 3: Wire the dispatch branches**

In `runpod-comfyui/comfy_common.py`, in `generate()`:

Change line 514 from:
```python
    if mode in ("i2i", "krea2"):
```
to:
```python
    if mode in ("i2i", "krea2", "krea2new"):
```

Change the branch at lines 524-529 from:
```python
        if mode == "i2i":
            graph = _build_i2i(graph, sub, cseed, frame_name)
        elif mode == "krea2":
            graph = _build_krea2(graph, sub, cseed, frame_name)
        else:
            graph = _build_t2i(graph, sub, cseed)
```
to:
```python
        if mode == "i2i":
            graph = _build_i2i(graph, sub, cseed, frame_name)
        elif mode == "krea2":
            graph = _build_krea2(graph, sub, cseed, frame_name)
        elif mode == "krea2new":
            graph = _build_krea2new(graph, sub, cseed, frame_name)
        else:
            graph = _build_t2i(graph, sub, cseed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd runpod-comfyui && "/c/Users/jimi/miniconda3/python.exe" -m pytest tests/test_generate_krea2new_dispatch.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run the full comfy_common test suite to check for regressions**

Run: `cd runpod-comfyui && "/c/Users/jimi/miniconda3/python.exe" -m pytest tests/ -v`
Expected: all tests pass (19 existing + 12 new from Tasks 1-3 = 31 passed).

- [ ] **Step 6: Commit**

```bash
git add runpod-comfyui/comfy_common.py runpod-comfyui/tests/test_generate_krea2new_dispatch.py
git commit -m "feat(krea2new): wire krea2new into generate() dispatch"
```

---

### Task 4: Backend request wiring (`webapp/app.py`)

**Files:**
- Modify: `runpod-comfyui/webapp/app.py:1107-1121` (`_build_input`), `:1519-1522` (empty-prompt auto-describe), `:1591-1607` (`/api/generate` mode validation)

**Interfaces:**
- Consumes: `_build_input(body) -> inp` (existing function, this task adds one more `elif` branch), the existing `session`/`frame` upload pattern already used by `i2i`/`krea2`.
- Produces: a request with `body.mode == "krea2new"` now round-trips through `_build_input` into an `inp` dict shaped like `krea2`'s (minus `resize_size`/`refine`/`denoise`), and `/api/generate` now accepts (and gates local-only) `mode=="krea2new"` requests.

- [ ] **Step 1: Add the `_build_input` branch**

In `runpod-comfyui/webapp/app.py`, in `_build_input()`, change:
```python
    elif inp["mode"] == "krea2":
        session, frame_name = body["session"], body["frame"]
        fpath = os.path.join(FRAMES_DIR, session, frame_name)
        with open(fpath, "rb") as f:
            inp["image_b64"] = base64.b64encode(f.read()).decode()
        inp["resize_size"] = int(body.get("resize_size", 1920))
        inp["refine"] = bool(body.get("refine", False))
        inp["denoise"] = float(body.get("denoise", 0.71))
        inp["refine_denoise"] = float(body.get("refine_denoise", 0.1))
```
to:
```python
    elif inp["mode"] == "krea2":
        session, frame_name = body["session"], body["frame"]
        fpath = os.path.join(FRAMES_DIR, session, frame_name)
        with open(fpath, "rb") as f:
            inp["image_b64"] = base64.b64encode(f.read()).decode()
        inp["resize_size"] = int(body.get("resize_size", 1920))
        inp["refine"] = bool(body.get("refine", False))
        inp["denoise"] = float(body.get("denoise", 0.71))
        inp["refine_denoise"] = float(body.get("refine_denoise", 0.1))
    elif inp["mode"] == "krea2new":
        session, frame_name = body["session"], body["frame"]
        fpath = os.path.join(FRAMES_DIR, session, frame_name)
        with open(fpath, "rb") as f:
            inp["image_b64"] = base64.b64encode(f.read()).decode()
```

- [ ] **Step 2: Extend the empty-prompt auto-describe check**

In the same file, find:
```python
        if inp["mode"] in ("i2i", "krea2") and not inp.get("prompt"):
```
Change to:
```python
        if inp["mode"] in ("i2i", "krea2", "krea2new") and not inp.get("prompt"):
```

- [ ] **Step 3: Add `/api/generate` mode validation**

Find, in the `generate()` route:
```python
    elif mode == "krea2":
        if target != "local":
            return jsonify({"error": "Krea2 mode runs on Local only."}), 400
        fpath = os.path.join(FRAMES_DIR, body.get("session", ""), body.get("frame", ""))
        if not os.path.exists(fpath):
            return jsonify({"error": "Frame not found."}), 404
```
Change to:
```python
    elif mode == "krea2":
        if target != "local":
            return jsonify({"error": "Krea2 mode runs on Local only."}), 400
        fpath = os.path.join(FRAMES_DIR, body.get("session", ""), body.get("frame", ""))
        if not os.path.exists(fpath):
            return jsonify({"error": "Frame not found."}), 404
    elif mode == "krea2new":
        if target != "local":
            return jsonify({"error": "Krea I2I New mode runs on Local only."}), 400
        fpath = os.path.join(FRAMES_DIR, body.get("session", ""), body.get("frame", ""))
        if not os.path.exists(fpath):
            return jsonify({"error": "Frame not found."}), 404
```

- [ ] **Step 4: Verify by import (no dedicated test suite exists for `app.py` — matches the existing convention, `krea2`'s own `_build_input` branch is untested at this layer too)**

Run: `cd runpod-comfyui/webapp && "/c/Users/jimi/miniconda3/python.exe" -c "import app"`
Expected: no output, exit code 0 (confirms no syntax errors and all imports resolve).

- [ ] **Step 5: Run the full backend test suite to check for regressions**

Run: `cd runpod-comfyui && "/c/Users/jimi/miniconda3/python.exe" -m pytest tests/ -v`
Expected: 31 passed (unchanged from Task 3 — `app.py` has no dedicated tests).

- [ ] **Step 6: Commit**

```bash
git add runpod-comfyui/webapp/app.py
git commit -m "feat(krea2new): wire krea2new mode into app.py request handling"
```

---

### Task 5: Frontend UI wiring (`webapp/index.html`)

**Files:**
- Modify: `runpod-comfyui/webapp/index.html` (mode button, `setMode()`, `_charList()`, `onTargetChange()`, click handler, `refreshGo()`, `$('#go').onclick` body builder)

**Interfaces:**
- Consumes: `S.mode`, `S.krea2Chars` (populated from `/api/config`'s `krea2_characters`, already wired), `S.aspect` (existing global aspect-picker state), `#paneVideo`/`#i2iPromptContainer`/`#i2iDescribeBtn`/`#i2iPrompt` (existing shared frame-picker DOM, unchanged).
- Produces: a fully clickable "Krea I2I New" mode in the SPA that reuses the frame picker, aspect picker, and Krea2 character picker, hidden on Cloud target.

- [ ] **Step 1: Add the mode button**

In `runpod-comfyui/webapp/index.html`, change:
```html
    <button id="mKrea2" data-mode="krea2"><span class="k">k</span>Krea2 I2I</button>
```
to:
```html
    <button id="mKrea2" data-mode="krea2"><span class="k">k</span>Krea2 I2I</button>
    <button id="mKreaNew" data-mode="krea2new"><span class="k">n</span>Krea I2I New</button>
```

- [ ] **Step 2: Extend `setMode()`**

Change:
```javascript
  $('#mKrea2').classList.toggle('on',m==='krea2');
  $('#paneVideo').classList.toggle('hide',m!=='i2i'&&m!=='krea2');   // krea2 reuses the frame-picker pane
```
to:
```javascript
  $('#mKrea2').classList.toggle('on',m==='krea2');
  $('#mKreaNew').classList.toggle('on',m==='krea2new');
  $('#paneVideo').classList.toggle('hide',m!=='i2i'&&m!=='krea2'&&m!=='krea2new');   // krea2/krea2new reuse the frame-picker pane
```

Change:
```javascript
  $$('.stdlora').forEach(el=>el.classList.toggle('hide', m==='adv'||m==='krea2'));
```
to:
```javascript
  $$('.stdlora').forEach(el=>el.classList.toggle('hide', m==='adv'||m==='krea2'||m==='krea2new'));
```

- [ ] **Step 3: Extend `_charList()`**

Change:
```javascript
  if(S.mode==='krea2') return S.krea2Chars||[];
```
to:
```javascript
  if(S.mode==='krea2'||S.mode==='krea2new') return S.krea2Chars||[];
```

- [ ] **Step 4: Extend `onTargetChange()`'s Cloud hide-list**

Change:
```javascript
  $('#mKrea2').classList.toggle('hide', cloudOnly);   // krea2 = local only
```
to:
```javascript
  $('#mKrea2').classList.toggle('hide', cloudOnly);   // krea2 = local only
  $('#mKreaNew').classList.toggle('hide', cloudOnly);   // krea2new = local only
```

- [ ] **Step 5: Wire the click handler**

Change:
```javascript
$('#mAdv').onclick=()=>setMode('adv');$('#mKrea2').onclick=()=>setMode('krea2');
```
to:
```javascript
$('#mAdv').onclick=()=>setMode('adv');$('#mKrea2').onclick=()=>setMode('krea2');
$('#mKreaNew').onclick=()=>setMode('krea2new');
```

- [ ] **Step 6: Extend `refreshGo()`'s frame-required check**

Change:
```javascript
  else if(S.mode==='i2i' || S.mode==='krea2') ok = !!S.frame;
```
to:
```javascript
  else if(S.mode==='i2i' || S.mode==='krea2' || S.mode==='krea2new') ok = !!S.frame;
```

- [ ] **Step 7: Add the `$('#go').onclick` body-building branch**

Change:
```javascript
  else if(S.mode==='krea2'){
    body.session=S.session;
    body.frame=S.frame;
    body.prompt=$('#i2iPrompt').value.trim();
    body.resize_size=+$('#krea2ResizeVal').value||1920;
    body.refine=$('#krea2RefineSw').classList.contains('on');
    body.denoise=+$('#krea2Dn1Val').value||0.71;
    body.refine_denoise=+$('#krea2Dn2Val').value||0.1;
  }
```
to:
```javascript
  else if(S.mode==='krea2'){
    body.session=S.session;
    body.frame=S.frame;
    body.prompt=$('#i2iPrompt').value.trim();
    body.resize_size=+$('#krea2ResizeVal').value||1920;
    body.refine=$('#krea2RefineSw').classList.contains('on');
    body.denoise=+$('#krea2Dn1Val').value||0.71;
    body.refine_denoise=+$('#krea2Dn2Val').value||0.1;
  }
  else if(S.mode==='krea2new'){
    body.session=S.session;
    body.frame=S.frame;
    body.prompt=$('#i2iPrompt').value.trim();
  }
```

- [ ] **Step 8: Static verification — grep for orphaned references**

Run (from `runpod-comfyui/webapp/`):
```bash
grep -c "mKreaNew" index.html
```
Expected: `4` — one `id="mKreaNew"` on the button definition, plus three `$('#mKreaNew')` references (`setMode`'s on-toggle, `onTargetChange`'s hide-toggle, the click handler). If the count is anything else, one of Steps 1/2/4/5 was missed or double-applied — go back and check.

- [ ] **Step 9: Live smoke-test the dev server**

Start the dev server (`.claude/launch.json` config `krea2-webapp`, `python webapp/app.py`, port 8000) and confirm it boots with no Python traceback and `GET /login` returns 200. This catches Flask-side breakage (e.g. a bad edit in `app.py` from Task 4) but does **not** validate the new JS — `index.html`'s script block is served as-is and only fails at parse time in the browser. The authoritative JS check is the browser console, done in Task 6 alongside the full regression pass (this step is just a fast pre-check before that).

- [ ] **Step 10: Commit**

```bash
git add runpod-comfyui/webapp/index.html
git commit -m "feat(krea2new): add Krea I2I New mode UI (button, pane reuse, char/aspect picker wiring)"
```

---

### Task 6: Full regression run, browser smoke-test, and deploy

**Files:** none (verification + deploy only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd runpod-comfyui && "/c/Users/jimi/miniconda3/python.exe" -m pytest tests/ -v`
Expected: 31 passed, 0 failed.

- [ ] **Step 2: Start the dev server and check logs/console**

Use the `krea2-webapp` preview config (port 8000). Confirm:
- Server boots without traceback.
- `preview_logs` shows no 500s on `/`, `/login`, `/api/config`.
- `read_console_messages` shows no new JS errors compared to before this change (the app is login-gated — full interactive verification of "Krea I2I New" end-to-end, including a real depth-controlnet render, needs the user's own login and a local ComfyUI with the Krea2 checkpoint/CLIP/LoRA/control-LoRA files present, per the design doc's "Open items to verify during build").

- [ ] **Step 3: Update HANDOFF.md**

Add a short entry (following the existing session-summary convention at the top of `HANDOFF.md`) noting: Krea I2I New mode added (depth-ControlNet, local-only), not yet live-verified on a real render (needs the Krea2 control-LoRA + DepthAnythingV2 checkpoint present in the local ComfyUI install), leaked OpenRouter key from the source JSON stripped but the key itself still needs rotating (same pending-rotation list as before).

- [ ] **Step 4: Commit HANDOFF.md**

```bash
git add HANDOFF.md
git commit -m "docs: note Krea I2I New mode in HANDOFF"
```

- [ ] **Step 5: Push to deploy**

```bash
git push
```

Then confirm the GitHub Actions `deploy.yml` run for this push succeeds (check via the GitHub API, same as the last deploy — `https://api.github.com/repos/AbulH88/AtelierStudio/actions/workflows/deploy.yml/runs?per_page=1` should show `status: completed, conclusion: success` for this commit's SHA).

- [ ] **Step 6: Hand off to the user for live testing**

Report to the user: mode is live on `https://studio.thecristinaadam.com`, needs a real render to confirm the depth-control chain and character LoRA behave as expected (per the design doc's open items) — ask them to test and report back before further "Krea I2I New" work.

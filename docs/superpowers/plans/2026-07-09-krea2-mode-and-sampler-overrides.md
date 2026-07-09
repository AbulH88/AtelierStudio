# Krea2 I2I Mode + Cross-Mode Sampler Overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 5th local-only generation mode (Krea2 I2I, a true img2img pipeline) and an opt-in cfg/sampler_name/scheduler override usable across every existing mode, without touching any mode's tuned defaults unless a user explicitly turns the override on.

**Architecture:** Follows the existing `comfy_common.py` dispatch pattern (`I2I`/`T2I`/`VIDEO`/`ADV` node maps + `_build_*` functions + `generate()` mode branch). Krea2 reuses the app's existing frame-extraction/reel-picker plumbing (same as WAN I2I) and its existing "Describe with AI" OpenRouter integration — no graph-embedded captioning. The sampler override is one small shared function called from every `_build_*`, gated entirely by presence of `inp["sampler_override"]`.

**Tech Stack:** Python 3 (Flask backend, `comfy_common.py` shared builder), vanilla JS single-page frontend (`webapp/index.html`), pytest for the pure-logic backend tests (no live ComfyUI required for those).

**Design doc:** `docs/superpowers/specs/2026-07-09-krea2-mode-and-sampler-overrides-design.md`

## Global Constraints
- Krea2 mode is **local-only** (cloud stays Motion-only per current architecture) — gate it the same way `adv` is gated in `webapp/app.py`.
- The confirmed on-disk LoRA root for Krea2 is **`Keara2`** (verified against `H:/ConfiuiModels/models/loras/Keara2/{CristinaCosplay,GothNiche}` on the home PC — NOT `Kera2`, which is only used for the base UNET/CLIP checkpoint folders, a different root).
- Never commit a live API key. `workflow_krea2.json` must not contain the string `sk-or-v1` or an `api_key` field anywhere (enforced by a test in Task 1).
- The OpenRouter key that was pasted into this session (`sk-or-v1-2ecfce...`) must be rotated — this is called out again in Task 6; it is independent of the code changes.
- Sampler override default is **off** for every mode; when off, `inp` has no `sampler_override` key and generated graphs are byte-for-byte identical to today's output for T2I/I2I/Video/Advanced.

---

### Task 1: `workflow_krea2.json` — cleaned workflow file + regression guards

**Files:**
- Create: `runpod-comfyui/workflow_krea2.json`
- Test: `runpod-comfyui/tests/test_workflow_krea2_file.py`

**Interfaces:**
- Produces: a ComfyUI API-format graph on disk with node ids `302,303,304,305,310,311,312,313,314,316,317,322,323,324,334,335,336,339`. Task 2 loads this file and calls `_build_krea2()` on it.

- [ ] **Step 1: Write the failing tests**

Create `runpod-comfyui/tests/test_workflow_krea2_file.py`:
```python
import json
import os

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2.json")


def _load():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_no_leaked_api_key_or_openrouter_node():
    with open(WF_PATH, encoding="utf-8") as f:
        raw = f.read()
    assert "sk-or-v1" not in raw
    assert "api_key" not in raw


def test_video_switch_and_debug_nodes_removed():
    graph = _load()
    for nid in ("321", "327", "328", "329", "330", "333", "337", "338"):
        assert nid not in graph, f"node {nid} should have been stripped"


def test_remaining_nodes_present():
    graph = _load()
    expected = {"302", "303", "304", "305", "310", "311", "312", "313",
                "314", "316", "317", "322", "323", "324", "334", "335",
                "336", "339"}
    assert set(graph.keys()) == expected


def test_resize_reads_directly_from_load_image():
    graph = _load()
    assert graph["322"]["inputs"]["image"] == ["316", 0]


def test_positive_prompt_has_no_dangling_link():
    graph = _load()
    # 314.text must be a literal (app sets it at runtime), not a link to the
    # removed ShowText/OpenRouterVLM nodes (321/330).
    assert isinstance(graph["314"]["inputs"]["text"], str)


def test_save_image_defaults_to_base_output():
    graph = _load()
    assert graph["304"]["inputs"]["images"] == ["303", 0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd runpod-comfyui && python -m pytest tests/test_workflow_krea2_file.py -v`
Expected: FAIL — `FileNotFoundError` (the file doesn't exist yet).

- [ ] **Step 3: Create the cleaned workflow file**

Create `runpod-comfyui/workflow_krea2.json`:
```json
{
  "302": {
    "inputs": {
      "seed": 875143778411088,
      "steps": 8,
      "cfg": 1,
      "sampler_name": "er_sde",
      "scheduler": "simple",
      "denoise": 0.6,
      "model": ["313", 0],
      "positive": ["314", 0],
      "negative": ["305", 0],
      "latent_image": ["317", 0]
    },
    "class_type": "KSampler",
    "_meta": {"title": "KSampler"}
  },
  "303": {
    "inputs": {"samples": ["302", 0], "vae": ["312", 0]},
    "class_type": "VAEDecode",
    "_meta": {"title": "VAE Decode"}
  },
  "304": {
    "inputs": {"filename_prefix": "ComfyUI", "images": ["303", 0]},
    "class_type": "SaveImage",
    "_meta": {"title": "Save Image"}
  },
  "305": {
    "inputs": {"conditioning": ["314", 0]},
    "class_type": "ConditioningZeroOut",
    "_meta": {"title": "Negative (Zero Out)"}
  },
  "310": {
    "inputs": {"unet_name": "Kera2\\krea2_turbo_bf16.safetensors", "weight_dtype": "default"},
    "class_type": "UNETLoader",
    "_meta": {"title": "UNET Loader - Krea2 Turbo FP8"}
  },
  "311": {
    "inputs": {"clip_name": "Krea-2\\Huihui-Qwen3-VL-4B-Instruct-abliterated.safetensors", "type": "krea2", "device": "default"},
    "class_type": "CLIPLoader",
    "_meta": {"title": "CLIP Loader - Krea2"}
  },
  "312": {
    "inputs": {"vae_name": "Wan\\Wan2_1_VAE_fp32.safetensors"},
    "class_type": "VAELoader",
    "_meta": {"title": "VAE Loader"}
  },
  "313": {
    "inputs": {"lora_name": "Keara2\\CristinaCosplay\\CosplayGirl_000000600.safetensors", "strength_model": 1, "model": ["310", 0]},
    "class_type": "LoraLoaderModelOnly",
    "_meta": {"title": "Load LoRA"}
  },
  "314": {
    "inputs": {"text": "", "clip": ["311", 0]},
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "Positive Prompt"}
  },
  "316": {
    "inputs": {"image": "Woman_in_black_velvet_dress_202606280259.jpeg"},
    "class_type": "LoadImage",
    "_meta": {"title": "Load Image"}
  },
  "317": {
    "inputs": {"pixels": ["323", 0], "vae": ["312", 0]},
    "class_type": "VAEEncode",
    "_meta": {"title": "VAE Encode"}
  },
  "322": {
    "inputs": {
      "width": ["324", 0],
      "height": ["324", 0],
      "upscale_method": "nearest-exact",
      "keep_proportion": "resize",
      "pad_color": "0, 0, 0",
      "crop_position": "center",
      "divisible_by": 2,
      "device": "cpu",
      "image": ["316", 0]
    },
    "class_type": "ImageResizeKJv2",
    "_meta": {"title": "Resize Image v2"}
  },
  "323": {
    "inputs": {"noise_aug_strength": 0.01, "seed": 292682449859114, "image": ["322", 0]},
    "class_type": "ImageNoiseAugmentation",
    "_meta": {"title": "Image Noise Augmentation"}
  },
  "324": {
    "inputs": {"Number": "1920"},
    "class_type": "Int",
    "_meta": {"title": "Int"}
  },
  "334": {
    "inputs": {"pixels": ["303", 0], "vae": ["312", 0]},
    "class_type": "VAEEncode",
    "_meta": {"title": "VAE Encode"}
  },
  "335": {
    "inputs": {
      "seed": 949413061011777,
      "steps": 4,
      "cfg": 1,
      "sampler_name": "res_6s",
      "scheduler": "beta57",
      "denoise": 0.15,
      "model": ["313", 0],
      "positive": ["339", 0],
      "negative": ["305", 0],
      "latent_image": ["334", 0]
    },
    "class_type": "KSampler",
    "_meta": {"title": "KSampler"}
  },
  "336": {
    "inputs": {"samples": ["335", 0], "vae": ["312", 0]},
    "class_type": "VAEDecode",
    "_meta": {"title": "VAE Decode"}
  },
  "339": {
    "inputs": {"text": "Natural skin textures with visible peach fuzz, natural shadows", "clip": ["311", 0]},
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "Positive Prompt"}
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd runpod-comfyui && python -m pytest tests/test_workflow_krea2_file.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add runpod-comfyui/workflow_krea2.json runpod-comfyui/tests/test_workflow_krea2_file.py
git commit -m "feat(krea2): add cleaned workflow_krea2.json with regression guards"
```

---

### Task 2: `_build_krea2()` — graph builder in `comfy_common.py`

**Files:**
- Modify: `runpod-comfyui/comfy_common.py` (add `KREA2` map after `ADV_STAGES` at line 66; add `_build_krea2()` after `_build_t2i()` at line 292, before the `# --- high level ---` comment at line 295)
- Test: `runpod-comfyui/tests/test_build_krea2.py`

**Interfaces:**
- Consumes: `_prompt_with_trigger(inp)`, `_set_lora(graph, nid, path, strength)` (both already defined in `comfy_common.py`, lines 206-224).
- Produces: `KREA2` dict (node-id map), `_build_krea2(graph, inp, seed, frame_name) -> graph` — same call signature shape as `_build_i2i(graph, inp, seed, frame_name)`. Task 3 adds a call to `_apply_sampler_override` inside this function (stubbed as a no-op passthrough in this task so tests here aren't blocked on Task 3 — see Step 3).

- [ ] **Step 1: Write the failing tests**

Create `runpod-comfyui/tests/test_build_krea2.py`:
```python
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2.json")


def _load_graph():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_build_krea2_sets_image_prompt_seed_lora_resize():
    graph = _load_graph()
    inp = {"prompt": "a woman in a red dress", "trigger": "ing2lorance",
           "character_lora_path": "Keara2/CristinaCosplay/CosplayGirl_000000600.safetensors",
           "character_strength": 0.9, "resize_size": 1536}
    out = cc._build_krea2(graph, inp, seed=12345, frame_name="frame_abc.png")
    assert out["316"]["inputs"]["image"] == "frame_abc.png"
    assert out["314"]["inputs"]["text"] == "ing2lorance, a woman in a red dress"
    assert out["302"]["inputs"]["seed"] == 12345
    assert out["313"]["inputs"]["lora_name"] == inp["character_lora_path"]
    assert out["313"]["inputs"]["strength_model"] == 0.9
    assert out["324"]["inputs"]["Number"] == "1536"


def test_build_krea2_resize_defaults_to_1920():
    graph = _load_graph()
    out = cc._build_krea2(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    assert out["324"]["inputs"]["Number"] == "1920"


def test_build_krea2_refine_off_drops_refine_subgraph_and_saves_base():
    graph = _load_graph()
    out = cc._build_krea2(graph, {"prompt": "x"}, seed=1, frame_name="f.png")
    for nid in ("334", "335", "336", "339"):
        assert nid not in out
    assert out["304"]["inputs"]["images"] == ["303", 0]


def test_build_krea2_refine_on_keeps_refine_subgraph_and_saves_refined():
    graph = _load_graph()
    out = cc._build_krea2(graph, {"prompt": "x", "refine": True}, seed=7, frame_name="f.png")
    for nid in ("334", "335", "336", "339"):
        assert nid in out
    assert out["304"]["inputs"]["images"] == ["336", 0]
    assert out["335"]["inputs"]["seed"] == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd runpod-comfyui && python -m pytest tests/test_build_krea2.py -v`
Expected: FAIL — `AttributeError: module 'comfy_common' has no attribute '_build_krea2'`

- [ ] **Step 3: Add the `KREA2` map**

In `runpod-comfyui/comfy_common.py`, after the `ADV_STAGES` block (ends at line 66 with `"glcm": "537", "grain": "548", "perturb": "533", "compress": "551"}`), insert:
```python

# Krea2 I2I (workflow_krea2.json) — true img2img (VAEEncode of the resized source
# image, denoise 0.6), single character LoraLoaderModelOnly (no Lightning chain,
# unlike WAN i2i/t2i), plus an optional skin-detail refine pass (denoise 0.15,
# fixed prompt at node 339).
KREA2 = {"load_image": "316", "positive": "314", "resize_size": "324",
         "char": "313", "base_ksampler": "302", "save": "304",
         "refine_encode": "334", "refine_ksampler": "335", "refine_decode": "336",
         "refine_prompt": "339"}
```

- [ ] **Step 4: Add `_build_krea2()`**

In `runpod-comfyui/comfy_common.py`, immediately after `_build_t2i()` (ends at line 292 with `    return graph`) and before the `# --- high level ---` comment (line 295), insert:
```python


def _build_krea2(graph, inp, seed, frame_name):
    """Krea2 img2img: VAEEncode(resized source image) -> KSampler(denoise 0.6)
    base pass, optionally followed by a fixed skin-detail refine pass. No
    Lightning/helper-LoRA chain — just the single character LoRA node."""
    nm = KREA2
    graph[nm["load_image"]]["inputs"]["image"] = frame_name
    graph[nm["resize_size"]]["inputs"]["Number"] = str(int(inp.get("resize_size", 1920)))
    graph[nm["positive"]]["inputs"]["text"] = _prompt_with_trigger(inp)
    graph[nm["base_ksampler"]]["inputs"]["seed"] = seed
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    if inp.get("refine"):
        graph[nm["refine_ksampler"]]["inputs"]["seed"] = seed
        graph[nm["save"]]["inputs"]["images"] = [nm["refine_decode"], 0]
    else:
        for nid in (nm["refine_encode"], nm["refine_ksampler"],
                    nm["refine_decode"], nm["refine_prompt"]):
            graph.pop(nid, None)
    return graph
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd runpod-comfyui && python -m pytest tests/test_build_krea2.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add runpod-comfyui/comfy_common.py runpod-comfyui/tests/test_build_krea2.py
git commit -m "feat(krea2): add KREA2 node map and _build_krea2() graph builder"
```

---

### Task 3: `_apply_sampler_override()` + wiring into every mode + `generate()` dispatch

**Files:**
- Modify: `runpod-comfyui/comfy_common.py`
  - Add `_apply_sampler_override()` after `_apply_extra_loras()` (ends at line 254 with `graph[char_id]["inputs"]["model"] = prev`)
  - Add a call to it at the end of `_build_i2i` (before `return graph` at line 274), `_build_t2i` (line 292), `_build_video` (line 328), `_build_adv` (line 412), and `_build_krea2` (added in Task 2)
  - Modify `generate()` (lines 415-469) to add the `mode == "krea2"` branch
- Test: `runpod-comfyui/tests/test_sampler_override.py`, extend `runpod-comfyui/tests/test_build_krea2.py`, new `runpod-comfyui/tests/test_generate_krea2_dispatch.py`

**Interfaces:**
- Produces: `_apply_sampler_override(graph, inp) -> graph`. Called from every `_build_*` function, always as the last mutation before `return graph`.
- Consumes (in `generate()`): `upload_image(base, raw_bytes)`, `run(base, graph, ...)` — both already defined in `comfy_common.py`.

- [ ] **Step 1: Write the failing override tests**

Create `runpod-comfyui/tests/test_sampler_override.py`:
```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc


def test_noop_when_override_absent():
    graph = {"1": {"class_type": "KSampler",
                   "inputs": {"cfg": 1, "sampler_name": "res_2s", "scheduler": "simple"}}}
    out = cc._apply_sampler_override(graph, {})
    assert out["1"]["inputs"] == {"cfg": 1, "sampler_name": "res_2s", "scheduler": "simple"}


def test_broadcasts_to_every_sampler_node_only():
    graph = {
        "1": {"class_type": "KSampler",
              "inputs": {"cfg": 1, "sampler_name": "res_2s", "scheduler": "simple"}},
        "2": {"class_type": "ClownsharKSampler_Beta",
              "inputs": {"cfg": 1, "sampler_name": "exponential/res_2s", "scheduler": "bong_tangent"}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    }
    inp = {"sampler_override": {"cfg": 3.5, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._apply_sampler_override(graph, inp)
    assert out["1"]["inputs"]["cfg"] == 3.5
    assert out["1"]["inputs"]["sampler_name"] == "euler"
    assert out["2"]["inputs"]["scheduler"] == "karras"
    assert out["3"]["inputs"] == {"images": ["1", 0]}


def test_skips_keys_the_node_class_does_not_have():
    graph = {"1": {"class_type": "WanVideoSampler", "inputs": {"cfg": 1, "scheduler": "dpm++_sde"}}}
    inp = {"sampler_override": {"cfg": 2, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._apply_sampler_override(graph, inp)
    assert out["1"]["inputs"]["cfg"] == 2
    assert out["1"]["inputs"]["scheduler"] == "karras"
    assert "sampler_name" not in out["1"]["inputs"]


def test_partial_override_only_touches_given_keys():
    graph = {"1": {"class_type": "KSampler",
                   "inputs": {"cfg": 1, "sampler_name": "res_2s", "scheduler": "simple"}}}
    out = cc._apply_sampler_override(graph, {"sampler_override": {"cfg": 2}})
    assert out["1"]["inputs"]["cfg"] == 2
    assert out["1"]["inputs"]["sampler_name"] == "res_2s"
    assert out["1"]["inputs"]["scheduler"] == "simple"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd runpod-comfyui && python -m pytest tests/test_sampler_override.py -v`
Expected: FAIL — `AttributeError: module 'comfy_common' has no attribute '_apply_sampler_override'`

- [ ] **Step 3: Add `_apply_sampler_override()`**

In `runpod-comfyui/comfy_common.py`, immediately after `_apply_extra_loras()` (ends at line 254) and before the `# --- graph builders ---` comment (line 257), insert:
```python


def _apply_sampler_override(graph, inp):
    """Opt-in broadcast of cfg/sampler_name/scheduler to every sampler node in the
    graph. Only keys present in inp["sampler_override"] AND already defined on a
    given node's inputs are touched (e.g. WanVideoSampler has no sampler_name, so
    that key is silently skipped for it). No-op when the UI toggle is off (no
    "sampler_override" key), so every mode's tuned defaults stay untouched unless
    a user explicitly opts in. [user requirement: broadcasts to EVERY sampler
    node in a mode's graph, including refine/detailer stages, not just the
    primary one.]"""
    override = inp.get("sampler_override")
    if not override:
        return graph
    for node in graph.values():
        if "Sampler" not in node.get("class_type", ""):
            continue
        node_inputs = node.get("inputs", {})
        for key in ("cfg", "sampler_name", "scheduler"):
            if key in override and key in node_inputs:
                node_inputs[key] = override[key]
    return graph
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd runpod-comfyui && python -m pytest tests/test_sampler_override.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Wire the call into every `_build_*` function**

In `runpod-comfyui/comfy_common.py`:

In `_build_i2i`, change:
```python
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    return graph


def _build_t2i(graph, inp, seed):
```
to:
```python
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    _apply_sampler_override(graph, inp)
    return graph


def _build_t2i(graph, inp, seed):
```

In `_build_t2i`, change:
```python
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    return graph


# --- high level ---
```
to:
```python
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    _apply_sampler_override(graph, inp)
    return graph


# --- high level ---
```

In `_build_video`, change:
```python
    graph[nm["sampler"]]["inputs"]["seed"] = seed
    return graph
```
to:
```python
    graph[nm["sampler"]]["inputs"]["seed"] = seed
    _apply_sampler_override(graph, inp)
    return graph
```

In `_build_adv`, change the final two lines:
```python
        if not on and name in ADV_STAGES:
            _bypass_node(graph, ADV_STAGES[name])
    return graph
```
to:
```python
        if not on and name in ADV_STAGES:
            _bypass_node(graph, ADV_STAGES[name])
    _apply_sampler_override(graph, inp)
    return graph
```

In `_build_krea2` (added in Task 2), change:
```python
    else:
        for nid in (nm["refine_encode"], nm["refine_ksampler"],
                    nm["refine_decode"], nm["refine_prompt"]):
            graph.pop(nid, None)
    return graph
```
to:
```python
    else:
        for nid in (nm["refine_encode"], nm["refine_ksampler"],
                    nm["refine_decode"], nm["refine_prompt"]):
            graph.pop(nid, None)
    _apply_sampler_override(graph, inp)
    return graph
```

- [ ] **Step 6: Add sampler-override coverage to the Krea2 builder test**

Append to `runpod-comfyui/tests/test_build_krea2.py`:
```python
def test_build_krea2_applies_sampler_override_to_both_stages():
    graph = _load_graph()
    inp = {"prompt": "x", "refine": True,
           "sampler_override": {"cfg": 4, "sampler_name": "euler", "scheduler": "karras"}}
    out = cc._build_krea2(graph, inp, seed=1, frame_name="f.png")
    assert out["302"]["inputs"]["cfg"] == 4
    assert out["302"]["inputs"]["sampler_name"] == "euler"
    assert out["335"]["inputs"]["scheduler"] == "karras"
```

Run: `cd runpod-comfyui && python -m pytest tests/test_build_krea2.py -v`
Expected: PASS (5 passed).

- [ ] **Step 7: Write the failing `generate()` dispatch test**

Create `runpod-comfyui/tests/test_generate_krea2_dispatch.py`:
```python
import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import comfy_common as cc

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..")


def test_generate_dispatches_krea2_without_network(monkeypatch):
    calls = {}

    def fake_upload_image(base, raw_bytes):
        calls["uploaded"] = raw_bytes
        return "uploaded_frame.png"

    def fake_run(base, graph, timeout=900, client_id=None, out_node=None):
        calls["graph"] = graph
        return ["ZmFrZQ=="]   # base64 "fake"

    monkeypatch.setattr(cc, "upload_image", fake_upload_image)
    monkeypatch.setattr(cc, "run", fake_run)

    inp = {"mode": "krea2", "prompt": "a woman in red",
           "image_b64": base64.b64encode(b"fake-image-bytes").decode(),
           "variations": 1, "seed": 42}
    out = cc.generate("http://fake-comfy", WORKFLOW_DIR, inp)

    assert out == {"images": ["ZmFrZQ=="], "seed": 42}
    assert calls["uploaded"] == b"fake-image-bytes"
    assert calls["graph"]["316"]["inputs"]["image"] == "uploaded_frame.png"
    assert calls["graph"]["314"]["inputs"]["text"] == "ing2lorance, a woman in red"
```

- [ ] **Step 8: Run test to verify it fails**

Run: `cd runpod-comfyui && python -m pytest tests/test_generate_krea2_dispatch.py -v`
Expected: FAIL — `KeyError` or a workflow file `FileNotFoundError` for mode `"krea2"` inside `generate()` (it currently only branches on `i2i`/else-`t2i` in the batching loop).

- [ ] **Step 9: Wire `krea2` into `generate()`**

In `runpod-comfyui/comfy_common.py`, in `generate()`, change:
```python
    frame_name = None
    if mode == "i2i":
        frame_name = upload_image(base, base64.b64decode(inp["image_b64"]))

    images, done = [], 0
    while done < total:
        chunk = min(max_batch, total - done)
        with open(wf_path, encoding="utf-8") as f:
            graph = json.load(f)
        sub = dict(inp, variations=chunk)
        cseed = seed + done   # distinct seed per chunk so variations differ
        graph = (_build_i2i(graph, sub, cseed, frame_name) if mode == "i2i"
                 else _build_t2i(graph, sub, cseed))
        images += run(base, graph, client_id=client_id)
        done += chunk
```
to:
```python
    frame_name = None
    if mode in ("i2i", "krea2"):
        frame_name = upload_image(base, base64.b64decode(inp["image_b64"]))

    images, done = [], 0
    while done < total:
        chunk = min(max_batch, total - done)
        with open(wf_path, encoding="utf-8") as f:
            graph = json.load(f)
        sub = dict(inp, variations=chunk)
        cseed = seed + done   # distinct seed per chunk so variations differ
        if mode == "i2i":
            graph = _build_i2i(graph, sub, cseed, frame_name)
        elif mode == "krea2":
            graph = _build_krea2(graph, sub, cseed, frame_name)
        else:
            graph = _build_t2i(graph, sub, cseed)
        images += run(base, graph, client_id=client_id)
        done += chunk
```

- [ ] **Step 10: Run test to verify it passes**

Run: `cd runpod-comfyui && python -m pytest tests/test_generate_krea2_dispatch.py -v`
Expected: PASS (1 passed).

- [ ] **Step 11: Run the full backend test suite**

Run: `cd runpod-comfyui && python -m pytest tests/ -v`
Expected: PASS (all tests from Tasks 1-3 green, e.g. 16 passed).

- [ ] **Step 12: Commit**

```bash
git add runpod-comfyui/comfy_common.py runpod-comfyui/tests/test_sampler_override.py runpod-comfyui/tests/test_build_krea2.py runpod-comfyui/tests/test_generate_krea2_dispatch.py
git commit -m "feat(sampler-override): add opt-in cfg/sampler_name/scheduler broadcast, wire into every mode + krea2 dispatch"
```

---

### Task 4: `webapp/app.py` — Flask wiring for Krea2 + sampler override passthrough

**Files:**
- Modify: `runpod-comfyui/webapp/app.py`

**Interfaces:**
- Consumes: `comfy_common._auto_characters`/`_auto_characters_fs` (existing, parametrized by `parent`), `comfy_common.generate` (Task 3's krea2 branch).
- Produces: `KREA2_LORA_ROOT` constant, `build_krea2_characters()`, `GET /api/config` response gains `"krea2_characters"`, `_build_input()` gains a `krea2` branch, `POST /api/generate` validates `krea2` mode, `_run_gen_job` auto-describes krea2's empty prompt the same way it does i2i's.

- [ ] **Step 1: Add `KREA2_LORA_ROOT` and `build_krea2_characters()`**

In `runpod-comfyui/webapp/app.py`, immediately after the `CHAR_DEFS` list (ends at line 337 with the closing `]`) and before `_STEP = re.compile(...)` (line 339), insert:
```python

# Krea2 characters live under a separate LoRA root (confirmed on the home PC:
# H:/ConfiuiModels/models/loras/Keara2/{CristinaCosplay,GothNiche}/...), not
# under wan/ like the WAN character LoRAs.
KREA2_LORA_ROOT = "Keara2"
```

Then after `build_characters()` (ends at line 453 with `    return []`), insert:
```python


def build_krea2_characters():
    """Character picker for Krea2 mode: same auto-discovery convention as
    build_characters(), scoped to the Krea2 LoRA root instead of wan/MyLoras."""
    try:
        return _auto_characters(_comfy_loras(), parent=KREA2_LORA_ROOT)
    except Exception:
        pass
    try:
        return _auto_characters_fs(parent=KREA2_LORA_ROOT)
    except Exception:
        pass
    return []
```

- [ ] **Step 2: Expose it from `/api/config`**

In `runpod-comfyui/webapp/app.py`, change:
```python
@app.get("/api/config")
def config():
    return jsonify({"characters": build_characters(),
                    "cloud_characters": build_cloud_characters(), "aspects": ASPECTS,
                    "lightning": {"options": _folder_loras("WanLightning", ".lightning_loras.json"),
                                  "defaults": LIGHTNING_DEFAULTS}})
```
to:
```python
@app.get("/api/config")
def config():
    return jsonify({"characters": build_characters(),
                    "cloud_characters": build_cloud_characters(),
                    "krea2_characters": build_krea2_characters(), "aspects": ASPECTS,
                    "lightning": {"options": _folder_loras("WanLightning", ".lightning_loras.json"),
                                  "defaults": LIGHTNING_DEFAULTS}})
```

- [ ] **Step 3: Add the `krea2` branch + universal `sampler_override` to `_build_input()`**

In `runpod-comfyui/webapp/app.py`, change:
```python
        "prompt": body.get("prompt", "").strip(),
        "trigger": body.get("trigger", "ing2lorance"),
    }
    if inp["mode"] == "i2i":
        session, frame_name = body["session"], body["frame"]
        fpath = os.path.join(FRAMES_DIR, session, frame_name)
        with open(fpath, "rb") as f:
            inp["image_b64"] = base64.b64encode(f.read()).decode()
        inp["denoise"] = float(body.get("denoise", 0.65))
    elif inp["mode"] == "video":   # Wan Animate: driving video + ref photo
```
to:
```python
        "prompt": body.get("prompt", "").strip(),
        "trigger": body.get("trigger", "ing2lorance"),
    }
    override = body.get("sampler_override")
    if isinstance(override, dict) and override:
        inp["sampler_override"] = {k: override[k] for k in ("cfg", "sampler_name", "scheduler")
                                   if k in override and override[k] not in (None, "")}
        if inp["sampler_override"].get("cfg") is not None:
            inp["sampler_override"]["cfg"] = float(inp["sampler_override"]["cfg"])
    if inp["mode"] == "i2i":
        session, frame_name = body["session"], body["frame"]
        fpath = os.path.join(FRAMES_DIR, session, frame_name)
        with open(fpath, "rb") as f:
            inp["image_b64"] = base64.b64encode(f.read()).decode()
        inp["denoise"] = float(body.get("denoise", 0.65))
    elif inp["mode"] == "krea2":
        session, frame_name = body["session"], body["frame"]
        fpath = os.path.join(FRAMES_DIR, session, frame_name)
        with open(fpath, "rb") as f:
            inp["image_b64"] = base64.b64encode(f.read()).decode()
        inp["resize_size"] = int(body.get("resize_size", 1920))
        inp["refine"] = bool(body.get("refine", False))
    elif inp["mode"] == "video":   # Wan Animate: driving video + ref photo
```

- [ ] **Step 4: Validate `krea2` mode and gate it to Local in `/api/generate`**

In `runpod-comfyui/webapp/app.py`, change:
```python
    mode = body.get("mode", "i2i")
    if mode == "i2i":
        fpath = os.path.join(FRAMES_DIR, body.get("session", ""), body.get("frame", ""))
        if not os.path.exists(fpath):
            return jsonify({"error": "Frame not found."}), 404
    elif mode == "video":
```
to:
```python
    mode = body.get("mode", "i2i")
    if mode == "i2i":
        fpath = os.path.join(FRAMES_DIR, body.get("session", ""), body.get("frame", ""))
        if not os.path.exists(fpath):
            return jsonify({"error": "Frame not found."}), 404
    elif mode == "krea2":
        if target != "local":
            return jsonify({"error": "Krea2 mode runs on Local only."}), 400
        fpath = os.path.join(FRAMES_DIR, body.get("session", ""), body.get("frame", ""))
        if not os.path.exists(fpath):
            return jsonify({"error": "Frame not found."}), 404
    elif mode == "video":
```

- [ ] **Step 5: Extend the empty-prompt auto-describe to `krea2`**

In `runpod-comfyui/webapp/app.py`, in `_run_gen_job`, change:
```python
        # i2i with an empty prompt → auto-describe the frame first (OpenRouter)
        if inp["mode"] == "i2i" and not inp.get("prompt"):
            p = _describe_params(body, False)
            inp["prompt"] = describe_image(inp["image_b64"], p, p["model"])
```
to:
```python
        # i2i/krea2 with an empty prompt → auto-describe the frame first (OpenRouter)
        if inp["mode"] in ("i2i", "krea2") and not inp.get("prompt"):
            p = _describe_params(body, False)
            inp["prompt"] = describe_image(inp["image_b64"], p, p["model"])
```

- [ ] **Step 6: Smoke-test the module imports and Flask app boots**

Run: `cd runpod-comfyui/webapp && python -c "import app; print('OK', app.app.url_map)"`
Expected: prints `OK` followed by the Flask URL map, no traceback. (This catches syntax errors and Python-level issues; it does not require a live ComfyUI/R2/OpenRouter connection since `app.py`'s module-level code only wires config from env vars.)

- [ ] **Step 7: Commit**

```bash
git add runpod-comfyui/webapp/app.py
git commit -m "feat(krea2): wire Krea2 mode + sampler_override passthrough into app.py"
```

---

### Task 5: `webapp/index.html` — Krea2 mode UI + Override-Sampler controls (all modes)

**Files:**
- Modify: `runpod-comfyui/webapp/index.html`

**Interfaces:**
- Consumes: `/api/config`'s new `krea2_characters` field (Task 4), `POST /api/generate` body shape `resize_size`/`refine`/`sampler_override` (Task 4).
- Produces: a 5th mode button (`data-mode="krea2"`), reuses the existing `#paneVideo` frame-picker pane, adds Options-rail fields for Krea2 (Resize target, Refine toggle) and a shared Override-Sampler block used by every mode.

- [ ] **Step 1: Add the mode button**

In `runpod-comfyui/webapp/index.html`, change:
```html
    <button id="mVid" class="on" data-mode="i2i"><span class="k">i</span>Frame → Character</button>
    <button id="mTxt" data-mode="t2i"><span class="k">t</span>Text → Character</button>
    <button id="mMotion" data-mode="video"><span class="k">m</span>Motion → Video</button>
    <button id="mAdv" data-mode="adv"><span class="k">a</span>⚡ Advanced</button>
```
to:
```html
    <button id="mVid" class="on" data-mode="i2i"><span class="k">i</span>Frame → Character</button>
    <button id="mTxt" data-mode="t2i"><span class="k">t</span>Text → Character</button>
    <button id="mMotion" data-mode="video"><span class="k">m</span>Motion → Video</button>
    <button id="mAdv" data-mode="adv"><span class="k">a</span>⚡ Advanced</button>
    <button id="mKrea2" data-mode="krea2"><span class="k">k</span>Krea2 I2I</button>
```

- [ ] **Step 2: Add the Krea2-only Options-rail fields (Resize target, Refine toggle)**

In `runpod-comfyui/webapp/index.html`, change:
```html
      <div class="field" id="stepsField">
        <div class="lab">Steps · detail <input type="number" class="numin" id="stVal" min="1" max="60" step="1" value="8"></div>
        <input type="range" id="steps" min="4" max="24" step="1" value="8">
      </div>
      <!-- OpenRouter Vision Settings -->
```
to:
```html
      <div class="field" id="stepsField">
        <div class="lab">Steps · detail <input type="number" class="numin" id="stVal" min="1" max="60" step="1" value="8"></div>
        <input type="range" id="steps" min="4" max="24" step="1" value="8">
      </div>
      <div class="field hide" id="krea2ResizeField">
        <div class="lab">Resize target · px <input type="number" class="numin" id="krea2ResizeVal" min="512" max="4096" step="8" value="1920"></div>
      </div>
      <div class="field hide" id="krea2RefineField">
        <div class="lab">Skin-detail refine pass</div>
        <div class="seedrow" style="margin-top:4px">
          <span class="hint" style="font-size:12px;color:var(--mut)">Extra denoise 0.15 pass for peach-fuzz skin texture</span>
          <div class="sw" id="krea2RefineSw" title="refine"></div>
        </div>
      </div>
      <!-- Sampler Override (all modes) -->
      <div style="margin:18px 0 12px;padding-top:14px;border-top:1px solid var(--line);
        font-family:var(--serif);font-style:italic;font-size:14px;color:var(--amber)">⚙ Override Sampler</div>
      <div class="field">
        <div class="lab">Override cfg / sampler / scheduler</div>
        <div class="seedrow" style="margin-top:4px">
          <span class="hint" style="font-size:12px;color:var(--mut)">Applies to every sampler stage in this mode, including detail/refine passes</span>
          <div class="sw" id="samplerOverrideSw" title="override"></div>
        </div>
      </div>
      <div class="field hide" id="overrideCfgField">
        <div class="lab">cfg <input type="number" class="numin" id="ovCfgVal" min="0" max="15" step="0.1" value="1"></div>
        <input type="range" id="ovCfg" min="0" max="15" step="0.1" value="1">
      </div>
      <div class="field hide" id="overrideSamplerField">
        <div class="lab">sampler_name</div>
        <input list="samplerNameList" id="ovSamplerName" value="res_2s" style="width:100%;box-sizing:border-box;background:var(--ink2);border:1px solid var(--line);color:var(--txt);border-radius:9px;padding:9px 10px;font-family:var(--mono)">
        <datalist id="samplerNameList">
          <option value="res_2s"><option value="res_2m"><option value="res_6s">
          <option value="er_sde"><option value="exponential/res_2s"><option value="dpm++_sde">
        </datalist>
      </div>
      <div class="field hide" id="overrideSchedulerField">
        <div class="lab">scheduler</div>
        <input list="schedulerList" id="ovScheduler" value="simple" style="width:100%;box-sizing:border-box;background:var(--ink2);border:1px solid var(--line);color:var(--txt);border-radius:9px;padding:9px 10px;font-family:var(--mono)">
        <datalist id="schedulerList">
          <option value="simple"><option value="beta57"><option value="bong_tangent">
          <option value="normal"><option value="karras">
        </datalist>
      </div>
      <!-- OpenRouter Vision Settings -->
```

- [ ] **Step 3: Wire the Override-Sampler toggle switch**

In `runpod-comfyui/webapp/index.html`, find the existing `PAIRS` slider-wiring block:
```js
const PAIRS=[['#cstrength','#csVal',2],['#denoise','#dnVal',2],['#steps','#stVal',0]];
PAIRS.forEach(([r,n,dec])=>{const R=$(r),N=$(n);
  R.oninput=()=>{N.value=dec?(+R.value).toFixed(dec):R.value;setRange(R);};
  N.oninput=()=>{const v=+N.value;if(!isNaN(v)){R.value=v;setRange(R);}};
  setRange(R);});
```
and change it to:
```js
const PAIRS=[['#cstrength','#csVal',2],['#denoise','#dnVal',2],['#steps','#stVal',0],['#ovCfg','#ovCfgVal',1]];
PAIRS.forEach(([r,n,dec])=>{const R=$(r),N=$(n);
  R.oninput=()=>{N.value=dec?(+R.value).toFixed(dec):R.value;setRange(R);};
  N.oninput=()=>{const v=+N.value;if(!isNaN(v)){R.value=v;setRange(R);}};
  setRange(R);});

$('#samplerOverrideSw').onclick=()=>{
  const on=!$('#samplerOverrideSw').classList.contains('on');
  $('#samplerOverrideSw').classList.toggle('on',on);
  ['#overrideCfgField','#overrideSamplerField','#overrideSchedulerField'].forEach(s=>$(s).classList.toggle('hide',!on));
};
```

- [ ] **Step 4: Reuse `#paneVideo` for Krea2 and toggle the new fields in `setMode()`**

In `runpod-comfyui/webapp/index.html`, change:
```js
function setMode(m){
  S.mode=m;
  $('#mVid').classList.toggle('on',m==='i2i');$('#mTxt').classList.toggle('on',m==='t2i');
  $('#mMotion').classList.toggle('on',m==='video');
  $('#mAdv').classList.toggle('on',m==='adv');
  $('#paneVideo').classList.toggle('hide',m!=='i2i');
  $('#paneText').classList.toggle('hide',m!=='t2i');
  $('#paneMotion').classList.toggle('hide',m!=='video');
  $('#paneAdv').classList.toggle('hide',m!=='adv');
  // Steps + Denoise only apply to I2I; T2I uses its fixed schedule; video uses its own
  $('#denoiseField').classList.toggle('hide',m!=='i2i');
  $('#stepsField').classList.toggle('hide',m!=='i2i');
  // Lightning + the helper-LoRA / lightning controls are image-only
  $$('.imgonly').forEach(el=>el.classList.toggle('hide', m==='video'));
  $$('.stdlora').forEach(el=>el.classList.toggle('hide', m==='adv'));   // generic lightning/LoRAs hidden in adv
  $$('.advlora').forEach(el=>el.classList.toggle('hide', m!=='adv'));   // two LoRA groups shown only in adv
  // adv has its own aspect + describe in the studio -> hide the rail's (keep Trigger Word)
  $$('.advhide').forEach(el=>el.classList.toggle('hide', m==='adv'));
  ['visionModelField','stylePresetField','bodyTypeField','shotTypeField','detailField','explicitField','clothingNoteField','customInstrField'].forEach(id=>{ const el=$('#'+id); if(el)el.classList.toggle('hide', m==='adv'); });
  applyLightningDefault(m);
  refreshGo();
  if(typeof renderCloudCard==='function') renderCloudCard();
}
$('#mVid').onclick=()=>setMode('i2i');$('#mTxt').onclick=()=>setMode('t2i');$('#mMotion').onclick=()=>setMode('video');
$('#mAdv').onclick=()=>setMode('adv');
```
to:
```js
function setMode(m){
  S.mode=m;
  $('#mVid').classList.toggle('on',m==='i2i');$('#mTxt').classList.toggle('on',m==='t2i');
  $('#mMotion').classList.toggle('on',m==='video');
  $('#mAdv').classList.toggle('on',m==='adv');
  $('#mKrea2').classList.toggle('on',m==='krea2');
  $('#paneVideo').classList.toggle('hide',m!=='i2i'&&m!=='krea2');   // krea2 reuses the frame-picker pane
  $('#paneText').classList.toggle('hide',m!=='t2i');
  $('#paneMotion').classList.toggle('hide',m!=='video');
  $('#paneAdv').classList.toggle('hide',m!=='adv');
  // Steps + Denoise only apply to I2I; T2I uses its fixed schedule; video uses its own
  $('#denoiseField').classList.toggle('hide',m!=='i2i');
  $('#stepsField').classList.toggle('hide',m!=='i2i');
  $('#krea2ResizeField').classList.toggle('hide',m!=='krea2');
  $('#krea2RefineField').classList.toggle('hide',m!=='krea2');
  // Lightning + the helper-LoRA / lightning controls are image-only, and krea2
  // has no Lightning node at all (single character LoRA only)
  $$('.imgonly').forEach(el=>el.classList.toggle('hide', m==='video'));
  $$('.stdlora').forEach(el=>el.classList.toggle('hide', m==='adv'||m==='krea2'));
  $$('.advlora').forEach(el=>el.classList.toggle('hide', m!=='adv'));   // two LoRA groups shown only in adv
  // adv has its own aspect + describe in the studio -> hide the rail's (keep Trigger Word)
  $$('.advhide').forEach(el=>el.classList.toggle('hide', m==='adv'));
  ['visionModelField','stylePresetField','bodyTypeField','shotTypeField','detailField','explicitField','clothingNoteField','customInstrField'].forEach(id=>{ const el=$('#'+id); if(el)el.classList.toggle('hide', m==='adv'); });
  applyLightningDefault(m);
  applyCharList();
  refreshGo();
  if(typeof renderCloudCard==='function') renderCloudCard();
}
$('#mVid').onclick=()=>setMode('i2i');$('#mTxt').onclick=()=>setMode('t2i');$('#mMotion').onclick=()=>setMode('video');
$('#mAdv').onclick=()=>setMode('adv');$('#mKrea2').onclick=()=>setMode('krea2');
```

- [ ] **Step 5: Hide Krea2 on Cloud (local-only, like Advanced)**

In `runpod-comfyui/webapp/index.html`, change:
```js
  const cloudOnly = isCloud();
  $('#mVid').classList.toggle('hide', cloudOnly);
  $('#mTxt').classList.toggle('hide', cloudOnly);
  $('#mAdv').classList.toggle('hide', cloudOnly);   // advanced = local only
  if(cloudOnly && S.mode!=='video') setMode('video');
```
to:
```js
  const cloudOnly = isCloud();
  $('#mVid').classList.toggle('hide', cloudOnly);
  $('#mTxt').classList.toggle('hide', cloudOnly);
  $('#mAdv').classList.toggle('hide', cloudOnly);   // advanced = local only
  $('#mKrea2').classList.toggle('hide', cloudOnly);   // krea2 = local only
  if(cloudOnly && S.mode!=='video') setMode('video');
```

- [ ] **Step 6: Give Krea2 its own character list**

In `runpod-comfyui/webapp/index.html`, change:
```js
function _charList(){
  // Cloud mode -> characters from the volume manifest (every char on the volume,
  // with the volume's real paths). Local -> the live ComfyUI list. Fall back to
  // whichever is non-empty so the picker is never empty.
  if(isCloud() && S.cloudChars && S.cloudChars.length) return S.cloudChars;
  return (S.chars && S.chars.length) ? S.chars : (S.cloudChars||[]);
}
```
to:
```js
function _charList(){
  // Krea2 characters live under a completely different LoRA root -> its own list.
  if(S.mode==='krea2') return S.krea2Chars||[];
  // Cloud mode -> characters from the volume manifest (every char on the volume,
  // with the volume's real paths). Local -> the live ComfyUI list. Fall back to
  // whichever is non-empty so the picker is never empty.
  if(isCloud() && S.cloudChars && S.cloudChars.length) return S.cloudChars;
  return (S.chars && S.chars.length) ? S.chars : (S.cloudChars||[]);
}
```

And in `loadConfig()`, change:
```js
async function loadConfig(){
  const c=await(await fetch('/api/config')).json();
  S.chars=c.characters; S.cloudChars=c.cloud_characters||[];
```
to:
```js
async function loadConfig(){
  const c=await(await fetch('/api/config')).json();
  S.chars=c.characters; S.cloudChars=c.cloud_characters||[]; S.krea2Chars=c.krea2_characters||[];
```

- [ ] **Step 7: Skip the Lightning default for Krea2 (it has no Lightning node)**

In `runpod-comfyui/webapp/index.html`, change:
```js
// set Lightning pick + strength to the safe default for the given mode
function applyLightningDefault(mode){
  if(mode==='adv'){   // group B (low-noise) uses the t2i v2-distill default @0.6
```
to:
```js
// set Lightning pick + strength to the safe default for the given mode
function applyLightningDefault(mode){
  if(mode==='krea2') return;   // krea2 has no Lightning node — single character LoRA only
  if(mode==='adv'){   // group B (low-noise) uses the t2i v2-distill default @0.6
```

- [ ] **Step 8: Include Krea2 in the "Develop" enabled-check**

In `runpod-comfyui/webapp/index.html`, change:
```js
function refreshGo(){
  let ok;
  if(S.mode==='video') ok = !!(S.motionVid && S.motionRef);   // need driving video + ref photo
  else if(S.mode==='adv') ok = !!($('#variant').value && ($('#advScene').value.trim().length>3 || (S.advPrompts&&S.advPrompts.length)));
  else ok = S.mode==='i2i' ? !!S.frame : $('#prompt').value.trim().length>3;
```
to:
```js
function refreshGo(){
  let ok;
  if(S.mode==='video') ok = !!(S.motionVid && S.motionRef);   // need driving video + ref photo
  else if(S.mode==='adv') ok = !!($('#variant').value && ($('#advScene').value.trim().length>3 || (S.advPrompts&&S.advPrompts.length)));
  else if(S.mode==='i2i' || S.mode==='krea2') ok = !!S.frame;
  else ok = $('#prompt').value.trim().length>3;
```

- [ ] **Step 9: Build the `krea2` request body + attach the sampler override to every mode**

In `runpod-comfyui/webapp/index.html`, change:
```js
  if(S.mode==='i2i'){
    body.session=S.session;
    body.frame=S.frame;
    body.denoise=+$('#dnVal').value;
    body.prompt=$('#i2iPrompt').value.trim();
  }
  else if(S.mode==='video'){
```
to:
```js
  if($('#samplerOverrideSw').classList.contains('on')){
    body.sampler_override={cfg:+$('#ovCfgVal').value, sampler_name:$('#ovSamplerName').value.trim(),
                           scheduler:$('#ovScheduler').value.trim()};
  }
  if(S.mode==='i2i'){
    body.session=S.session;
    body.frame=S.frame;
    body.denoise=+$('#dnVal').value;
    body.prompt=$('#i2iPrompt').value.trim();
  }
  else if(S.mode==='krea2'){
    body.session=S.session;
    body.frame=S.frame;
    body.prompt=$('#i2iPrompt').value.trim();
    body.resize_size=+$('#krea2ResizeVal').value||1920;
    body.refine=$('#krea2RefineSw').classList.contains('on');
  }
  else if(S.mode==='video'){
```

- [ ] **Step 10: Start the local dev server and manually verify the UI**

Use the `preview_start`/`preview_*` tools (or run `python webapp/app.py` from `runpod-comfyui/` if a local ComfyUI is reachable) and walk through:
1. Load the app, confirm 5 mode buttons show on Local target: Frame→Character, Text→Character, Motion→Video, Advanced, Krea2 I2I.
2. Switch to Cloud target — confirm Krea2 I2I button hides (same as Advanced).
3. Switch back to Local, click Krea2 I2I — confirm the "Reference video" pane appears (same as Frame→Character), and the Options rail shows "Resize target · px" and "Skin-detail refine pass" fields plus the "⚙ Override Sampler" block.
4. Toggle "⚙ Override Sampler" on — confirm cfg/sampler_name/scheduler fields appear.
5. Open browser devtools console — confirm no JS errors on mode switch between all 5 modes.

Record the result (pass/fail + screenshot if anything looks wrong) before committing.

- [ ] **Step 11: Commit**

```bash
git add runpod-comfyui/webapp/index.html
git commit -m "feat(krea2): add Krea2 I2I mode UI + Override-Sampler controls across all modes"
```

---

### Task 6: Deploy readiness pass

**Files:** none (verification + reminders only)

- [ ] **Step 1: Run the full backend test suite one more time**

Run: `cd runpod-comfyui && python -m pytest tests/ -v`
Expected: PASS, all tests green.

- [ ] **Step 2: Byte-compile every changed Python file**

Run: `cd runpod-comfyui && python -m py_compile comfy_common.py webapp/app.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Confirm no secret strings anywhere in the diff**

Run: `git diff main --stat` then `git diff main | grep -i "sk-or-v1\|api_key.*:.*sk-"`
Expected: the grep returns nothing.

- [ ] **Step 4: Rotate the leaked OpenRouter key (manual, outside this repo)**

The key pasted into this session (`sk-or-v1-2ecfce...`) is not in any file this
plan touches, but it was exposed in conversation. Rotate it in the OpenRouter
dashboard and update the VPS `.env`'s `OPENROUTER_API_KEY` — same class of
follow-up as the HF/RunPod key rotations already noted in `HANDOFF.md`.

- [ ] **Step 5: Hand off for live VPS check**

Per your plan: deploy the changed files (`comfy_common.py`, `workflow_krea2.json`,
`webapp/app.py`, `webapp/index.html`) via the existing manual-deploy tar-over-SSH
command in `HANDOFF.md` ("Manual deploy" section, add `workflow_krea2.json` to the
tar list), then live-check Krea2 I2I mode end-to-end on the real ComfyUI install
(character LoRA renders correctly, resize target behaves as expected, refine
toggle visibly changes skin texture, sampler override actually changes output
when toggled on). Report back anything that doesn't match the design so the
relevant task above can be revisited.

- [ ] **Step 6: Update `HANDOFF.md`**

Add a short section (mirroring the existing "✅ INSTARAW ADVANCED MODE" style)
noting Krea2 I2I mode + the cross-mode sampler override are built, with the
verified `Keara2` LoRA-root fact and the still-open OpenRouter key rotation.
No code template here — write it once the live VPS check in Step 5 confirms
what actually works, so the handoff reflects reality rather than intent.

"""
Shared ComfyUI workflow logic used by BOTH:
  - handler.py        (cloud / RunPod serverless, talks to ComfyUI in the container)
  - webapp/app.py     (local mode, talks to your ComfyUI on 127.0.0.1:8188)

Everything is driven through ComfyUI's HTTP API (upload / prompt / history / view),
so it works the same whether ComfyUI is local or in the cloud.
"""

import base64
import io
import json
import os
import time
import uuid

import requests

# Cloudflare Access service-token headers (set on the VPS so it can reach the
# Access-protected ComfyUI tunnel; empty locally). Read from env at import.
CF_HEADERS = {}
if os.environ.get("CF_ACCESS_CLIENT_ID") and os.environ.get("CF_ACCESS_CLIENT_SECRET"):
    CF_HEADERS = {"CF-Access-Client-Id": os.environ["CF_ACCESS_CLIENT_ID"],
                  "CF-Access-Client-Secret": os.environ["CF_ACCESS_CLIENT_SECRET"]}

NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
            "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
            "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，"
            "杂乱的背景，三条腿，背景人很多，倒着走, censored, sunburnt skin, rashy skin, red cheeks")

FACE_PREFIX = "ing2lorance, "   # trigger word prepended to the description (i2i)

# Both workflows keep a LOCKED Lightning (lightx2v) LoRA baked in — i2i uses the
# 4-step rank64 @1.0, t2i the v2 distill rank128 @0.6 (do NOT change t2i: it must
# match wf2 exactly). User-chosen extra LoRAs are injected as a dynamic chain
# between that locked Lightning node (`lora_after`) and the character node (`char`),
# so any number of LoRAs from the wan/ folder can be stacked in either mode.
I2I = {"load_image": "1", "positive": "5", "negative": "6", "char": "13",
       "resize": "20", "noise_aug": "21", "repeat_latent": "23",
       "ksampler": "30", "lora_after": "11"}

T2I = {"positive": "5", "negative": "6", "char": "12",
       "latent": "20", "ksampler": "30", "lora_after": "11"}


# --- low-level ComfyUI API ----------------------------------------------------
def upload_image(base, raw_bytes):
    """POST to /upload/image, return the stored filename ComfyUI's LoadImage uses."""
    files = {"image": (f"frame_{uuid.uuid4().hex}.png", io.BytesIO(raw_bytes), "image/png")}
    r = requests.post(f"{base}/upload/image", files={"image": files["image"]},
                      data={"overwrite": "true"}, headers=CF_HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    name = j["name"]
    return f"{j['subfolder']}/{name}" if j.get("subfolder") else name


def run(base, graph, timeout=900, client_id=None):
    """Queue a graph, wait, return list of base64 PNGs via the /view API.
    client_id lets a WS listener (the web app) receive progress for this job."""
    pid = requests.post(f"{base}/prompt",
                        json={"prompt": graph, "client_id": client_id or uuid.uuid4().hex},
                        headers=CF_HEADERS, timeout=60).json()["prompt_id"]
    start = time.time()
    while time.time() - start < timeout:
        hist = requests.get(f"{base}/history/{pid}", headers=CF_HEADERS, timeout=30).json()
        if pid in hist:
            imgs = []
            for out in hist[pid].get("outputs", {}).values():
                for im in out.get("images", []):
                    v = requests.get(f"{base}/view", params={
                        "filename": im["filename"], "subfolder": im.get("subfolder", ""),
                        "type": im.get("type", "output")}, headers=CF_HEADERS, timeout=60)
                    imgs.append(base64.b64encode(v.content).decode())
            return imgs
        time.sleep(1)
    raise TimeoutError("ComfyUI timed out")


def _prompt_with_trigger(inp):
    """Prepend the character trigger word to the positive prompt. The UI sends
    `trigger` (default 'ing2lorance', editable per character); fall back to that
    default when absent (e.g. the RunPod handler). Empty trigger = no prefix."""
    trig = inp.get("trigger")
    if trig is None:
        trig = "ing2lorance"
    trig = trig.strip().strip(",").strip()
    body = inp.get("prompt", "") or ""
    return (trig + ", " + body) if trig else body


def _set_lora(graph, nid, path, strength):
    n = graph[nid]["inputs"]
    if path:
        n["lora_name"] = path
        n["strength_model"] = float(strength)
    else:
        n["strength_model"] = 0.0


def _apply_lightning(graph, node_id, lt):
    """Override the (otherwise locked) Lightning lightx2v node from the UI — a
    {"path","strength"} dict. If nothing is sent, the workflow JSON default
    (the mode-correct lightx2v) stays untouched."""
    if lt and (lt.get("path") or "").strip():
        _set_lora(graph, node_id, lt["path"].strip(), lt.get("strength", 1.0))


def _apply_extra_loras(graph, after_id, char_id, loras):
    """Insert a dynamic chain of user-chosen LoRAs between the locked Lightning
    node (`after_id`) and the character node (`char_id`). Each entry is
    {"path": "wan/...safetensors", "strength": float}. Entries without a path are
    skipped. The character node's model input is rewired to the last LoRA (or to
    `after_id` directly when no extra LoRAs are chosen)."""
    prev = [after_id, 0]
    for i, lo in enumerate(loras or []):
        path = (lo.get("path") or "").strip()
        if not path:
            continue
        nid = f"ulora_{i}"
        graph[nid] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": prev, "lora_name": path,
                       "strength_model": float(lo.get("strength", 1.0))},
            "_meta": {"title": f"Extra LoRA {i + 1}"},
        }
        prev = [nid, 0]
    graph[char_id]["inputs"]["model"] = prev


# --- graph builders -----------------------------------------------------------
def _build_i2i(graph, inp, seed, frame_name):
    nm = I2I
    graph[nm["load_image"]]["inputs"]["image"] = frame_name
    graph[nm["resize"]]["inputs"]["width"] = int(inp.get("width", 1080))
    graph[nm["resize"]]["inputs"]["height"] = int(inp.get("height", 1920))
    graph[nm["ksampler"]]["inputs"]["seed"] = seed
    graph[nm["ksampler"]]["inputs"]["denoise"] = float(inp.get("denoise", 0.65))
    graph[nm["ksampler"]]["inputs"]["steps"] = max(4, int(inp.get("steps", 8)))
    graph[nm["noise_aug"]]["inputs"]["seed"] = seed
    graph[nm["repeat_latent"]]["inputs"]["amount"] = max(1, int(inp.get("variations", 1)))
    graph[nm["positive"]]["inputs"]["text"] = _prompt_with_trigger(inp)
    graph[nm["negative"]]["inputs"]["text"] = NEGATIVE
    _apply_lightning(graph, nm["lora_after"], inp.get("lightning"))
    _apply_extra_loras(graph, nm["lora_after"], nm["char"], inp.get("extra_loras", []))
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    return graph


def _build_t2i(graph, inp, seed):
    nm = T2I
    graph[nm["positive"]]["inputs"]["text"] = _prompt_with_trigger(inp)
    graph[nm["negative"]]["inputs"]["text"] = NEGATIVE
    graph[nm["latent"]]["inputs"]["width"] = int(inp.get("width", 1080))
    graph[nm["latent"]]["inputs"]["height"] = int(inp.get("height", 1920))
    graph[nm["latent"]]["inputs"]["batch_size"] = max(1, int(inp.get("variations", 1)))
    graph[nm["ksampler"]]["inputs"]["noise_seed"] = seed
    # sampler schedule is fixed to match wf2 (single low-noise, start@4). Lightning
    # defaults to v2 distill @0.6 but is now tweakable from the UI; extra LoRAs
    # stack after it.
    _apply_lightning(graph, nm["lora_after"], inp.get("lightning"))
    _apply_extra_loras(graph, nm["lora_after"], nm["char"], inp.get("extra_loras", []))
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    return graph


# --- high level ---------------------------------------------------------------
def generate(base, workflow_dir, inp, client_id=None, max_batch=2):
    """Build + run the right workflow against ComfyUI. Large variation counts are
    split into chunks of `max_batch` (looped) to avoid VRAM OOM on big batches.
    Returns {"images": [...b64...], "seed": int}."""
    mode = inp.get("mode", "i2i")
    wf_path = os.path.join(workflow_dir, f"workflow_{mode}.json")
    seed = int(inp.get("seed", 0)) or int.from_bytes(os.urandom(4), "big")
    total = max(1, int(inp.get("variations", 1)))

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

    if not images:
        return {"error": "No image produced — check ComfyUI node errors / model paths."}
    return {"images": images, "seed": seed}

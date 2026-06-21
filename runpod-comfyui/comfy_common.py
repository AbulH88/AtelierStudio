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

FACE_PREFIX = "ing2lorance, "   # trigger word prepended to the QwenVL caption (i2i)


I2I = {"load_image": "1", "positive": "5", "negative": "6",
       "lora_h1": "11", "lora_h2": "12", "lora_char": "13",
       "resize": "20", "noise_aug": "21", "repeat_latent": "23",
       "ksampler": "30"}
I2I_HELPERS = ["lora_h1", "lora_h2"]

T2I = {"positive": "5", "negative": "6", "char": "12",
       "latent": "20", "ksampler": "30"}


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


def _set_lora(graph, nid, path, strength):
    n = graph[nid]["inputs"]
    if path:
        n["lora_name"] = path
        n["strength_model"] = float(strength)
    else:
        n["strength_model"] = 0.0


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
    graph[nm["positive"]]["inputs"]["text"] = FACE_PREFIX + inp.get("prompt", "")
    graph[nm["negative"]]["inputs"]["text"] = NEGATIVE
    _set_lora(graph, nm["lora_char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    helpers = inp.get("helper_loras", [])
    for i, slot in enumerate(I2I_HELPERS):
        h = helpers[i] if i < len(helpers) else None
        _set_lora(graph, nm[slot], h["path"] if h else None, (h or {}).get("strength", 1.0))
    return graph


def _build_t2i(graph, inp, seed):
    nm = T2I
    graph[nm["positive"]]["inputs"]["text"] = inp.get("prompt", "")
    graph[nm["negative"]]["inputs"]["text"] = NEGATIVE
    graph[nm["latent"]]["inputs"]["width"] = int(inp.get("width", 1080))
    graph[nm["latent"]]["inputs"]["height"] = int(inp.get("height", 1920))
    graph[nm["latent"]]["inputs"]["batch_size"] = max(1, int(inp.get("variations", 1)))
    graph[nm["ksampler"]]["inputs"]["noise_seed"] = seed
    # only the character LoRA is injected; lightx2v + sampler schedule are fixed
    # in the workflow to match wf2 exactly (single low-noise sampler, start@4)
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

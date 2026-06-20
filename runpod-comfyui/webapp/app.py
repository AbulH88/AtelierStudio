"""
Web backend for the Atelier character studio (host on your VPS / subdomain, or
just run on your own PC next to ComfyUI).

Two compute targets, chosen by a switch on the page:
  - "local":  talk straight to your ComfyUI on 127.0.0.1:8188 (free, uses the 5090)
  - "cloud":  send the job to your RunPod serverless endpoint

Two generation modes (per request):
  - "i2i": video frame + QwenVL auto-caption + character LoRA
  - "t2i": text prompt + two-stage Wan 2.2 + character LoRA

Run:  python app.py
Optional env: RUNPOD_ENDPOINT_ID, RUNPOD_API_KEY (for cloud),
              LOCAL_COMFY_URL (default http://127.0.0.1:8188)
"""

import base64
import os
import re
import subprocess
import sys
import uuid

import requests
from flask import Flask, request, jsonify, send_from_directory, send_file

# import the shared workflow logic from the repo root (one level up)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comfy_common  # noqa: E402

ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "")
API_KEY = os.environ.get("RUNPOD_API_KEY", "")
RUNPOD_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync"
LOCAL_COMFY = os.environ.get("LOCAL_COMFY_URL", "http://127.0.0.1:8189")  # matches Windows_Run_GPU.bat
WORKFLOW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# So the app can start ComfyUI for you when it's not running.
COMFY_DIR = os.environ.get("COMFY_DIR", "I:/@home/jimi/Documents/ComfyUI_V82")
COMFY_BAT = os.environ.get("COMFY_BAT", "Windows_Run_GPU.bat")

FRAMES_DIR = os.path.join(os.path.dirname(__file__), "frames")
os.makedirs(FRAMES_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)

# Root of your loras folder (used only to LIST checkpoints; paths sent to ComfyUI
# stay relative to this, so they work identically local & cloud).
LORAS_DIR = os.environ.get("LORAS_DIR", "H:/ConfiuiModels/models/loras")

# Each character points at a FOLDER; every .safetensors inside becomes a
# selectable checkpoint in the 2nd menu.
CHAR_DEFS = [
    {"key": "lorance_new", "label": "Lorance · New", "folder": "wan/Own/LoranceNew"},
    {"key": "lorance",     "label": "Lorance",       "folder": "wan/Own/Lorance"},
    {"key": "cristina",    "label": "Cristina",      "folder": "wan/Own/MyMain/Cristina"},
    {"key": "tumpa",       "label": "Tumpa",         "folder": "wan/Own/BunnyGirl/TumpaWan2.1MasterNew"},
    {"key": "skylar",      "label": "Skylar",        "folder": "wan/Own/Client/DD2Skylar_NSFW_2.2_Low"},
    {"key": "client",      "label": "Client",        "folder": "wan/Own/Client"},
    {"key": "gothamy",     "label": "Goth Amy",      "folder": "wan/Own/DD2GothAmyFM_2.2_Low"},
    {"key": "emy",         "label": "Emy",           "folder": "wan/Own/Emy"},
    {"key": "faithcake",   "label": "FaithCake",     "folder": "wan/Own/FaithCake"},
    {"key": "fscvrdd",     "label": "FscvrDD",       "folder": "wan/Own/FscvrDD"},
    {"key": "hazil",       "label": "Hazil",         "folder": "wan/Own/Hazil"},
    {"key": "kiren",       "label": "Kiren",         "folder": "wan/Own/Kiren"},
    {"key": "mastergoth",  "label": "Master Goth",   "folder": "wan/Own/MasterGothGirl"},
    {"key": "cindi",       "label": "Cindi",         "folder": "wan/Own/Shimon"},
    {"key": "sindy",       "label": "Sindy",         "folder": "wan/Own/Sindy"},
    {"key": "olivia",      "label": "Olivia",        "folder": "wan/Own/Olivia"},
    {"key": "newccdd",     "label": "NewCCDD",       "folder": "wan/Own/NewCCDD"},
    {"key": "siren",       "label": "Siren",         "folder": "wan/Own/siren2.2_LowOnly"},
]

_STEP = re.compile(r"step\d+|-\d{6}$", re.I)   # checkpoint-iteration markers


def _list_variants(folder):
    base = os.path.join(LORAS_DIR, folder)
    out = []
    if os.path.isdir(base):
        for root, _, files in os.walk(base):
            if "logs" in root.replace("\\", "/").split("/"):
                continue
            for fn in files:
                if fn.lower().endswith(".safetensors"):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, LORAS_DIR).replace("\\", "/")
                    label = os.path.splitext(os.path.relpath(full, base).replace("\\", "/"))[0]
                    out.append({"label": label or fn, "path": rel})
    # clean "final" exports first, training checkpoints after
    out.sort(key=lambda v: (bool(_STEP.search(v["label"])), v["label"]))
    return out


def build_characters():
    res = []
    for d in CHAR_DEFS:
        variants = _list_variants(d["folder"])
        if variants:
            res.append({"key": d["key"], "label": d["label"], "variants": variants})
    return res
HELPERS = [
    {"key": "lightx2v", "label": "Lightning", "path": "wan/Wan2.2-Lightning/Wan2.1-Distill-Loras/wan2.1_t2v_14b_lora_rank64_lightx2v_4step.safetensors", "default": True, "strength": 1.0},
    {"key": "lenovo",   "label": "Realism",   "path": "wan/WanRealisomLora/Lenovo.safetensors", "default": True, "strength": 1.0},
]
ASPECTS = [
    {"key": "portrait",  "label": "Portrait · 9:16", "width": 1080, "height": 1920},
    {"key": "square",    "label": "Square · 1:1",    "width": 1080, "height": 1080},
    {"key": "landscape", "label": "Landscape · 16:9","width": 1920, "height": 1080},
]


@app.get("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))


@app.get("/api/config")
def config():
    return jsonify({"characters": build_characters(), "helpers": HELPERS, "aspects": ASPECTS})


@app.get("/api/health")
def health():
    """Report which compute targets are available so the UI can auto-pick."""
    local = False
    try:
        requests.get(f"{LOCAL_COMFY}/system_stats", timeout=2)
        local = True
    except Exception:
        pass
    return jsonify({"local": local, "cloud": bool(ENDPOINT_ID and API_KEY)})


@app.post("/api/start-comfy")
def start_comfy():
    """Launch the local ComfyUI (Windows_Run_GPU.bat) if it isn't already up."""
    try:
        requests.get(f"{LOCAL_COMFY}/system_stats", timeout=2)
        return jsonify({"already": True})
    except Exception:
        pass
    bat = os.path.join(COMFY_DIR, COMFY_BAT)
    if not os.path.exists(bat):
        return jsonify({"error": f"Launch script not found: {bat}"}), 500
    try:
        subprocess.Popen(["cmd", "/c", "start", "", COMFY_BAT], cwd=COMFY_DIR)
        return jsonify({"started": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/extract")
def extract():
    video = request.files.get("video")
    every = int(request.form.get("every", 10))
    if not video:
        return jsonify({"error": "No video uploaded."}), 400
    session = uuid.uuid4().hex[:12]
    sdir = os.path.join(FRAMES_DIR, session)
    os.makedirs(sdir, exist_ok=True)
    vpath = os.path.join(sdir, "src" + os.path.splitext(video.filename)[1])
    video.save(vpath)
    cmd = ["ffmpeg", "-y", "-i", vpath,
           "-vf", f"select=not(mod(n\\,{every}))", "-vsync", "vfr",
           "-q:v", "3", os.path.join(sdir, "%04d.jpg")]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return jsonify({"error": "ffmpeg failed", "detail": res.stderr[-400:]}), 500
    frames = sorted(f for f in os.listdir(sdir) if f.endswith(".jpg"))
    return jsonify({"session": session,
                    "frames": [f"/frames/{session}/{f}" for f in frames]})


@app.get("/frames/<session>/<name>")
def frame(session, name):
    return send_from_directory(os.path.join(FRAMES_DIR, session), name)


def _lora_path(key, table):
    return next((x["path"] for x in table if x["key"] == key), None)


def _build_input(body):
    """Translate the UI body into the worker input dict (same shape local & cloud)."""
    inp = {
        "mode": body.get("mode", "i2i"),
        "character_lora_path": body.get("character_lora_path", ""),
        "character_strength": float(body.get("character_strength", 1.0)),
        "helper_loras": [{"path": _lora_path(h["key"], HELPERS), "strength": float(h.get("strength", 1.0))}
                         for h in body.get("helper_loras", []) if _lora_path(h["key"], HELPERS)],
        "variations": int(body.get("variations", 1)),
        "width": int(body.get("width", 1080)),
        "height": int(body.get("height", 1920)),
        "steps": int(body.get("steps", 8)),
        "seed": int(body.get("seed", 0)),
    }
    if inp["mode"] == "i2i":
        session, frame_name = body["session"], body["frame"]
        fpath = os.path.join(FRAMES_DIR, session, frame_name)
        with open(fpath, "rb") as f:
            inp["image_b64"] = base64.b64encode(f.read()).decode()
        inp["denoise"] = float(body.get("denoise", 0.65))
        inp["caption_prompt"] = body.get("caption_prompt", "").strip()
    else:
        inp["prompt"] = body.get("prompt", "").strip()
    return inp


@app.post("/api/generate")
def generate():
    body = request.get_json(force=True)
    target = body.get("target", "local")

    if body.get("mode", "i2i") == "i2i":
        fpath = os.path.join(FRAMES_DIR, body.get("session", ""), body.get("frame", ""))
        if not os.path.exists(fpath):
            return jsonify({"error": "Frame not found."}), 404
    elif not body.get("prompt", "").strip():
        return jsonify({"error": "Type a prompt for text mode."}), 400

    inp = _build_input(body)

    try:
        if target == "local":
            out = comfy_common.generate(LOCAL_COMFY, WORKFLOW_DIR, inp)
        else:
            if not (ENDPOINT_ID and API_KEY):
                return jsonify({"error": "Cloud not configured (set RunPod env vars)."}), 500
            r = requests.post(RUNPOD_URL, json={"input": inp},
                              headers={"Authorization": f"Bearer {API_KEY}"}, timeout=900)
            out = r.json().get("output", {})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

    if not out or "error" in out:
        return jsonify({"error": (out or {}).get("error", "No output from worker.")}), 500
    return jsonify({"images": out.get("images", []), "seed": out.get("seed")})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

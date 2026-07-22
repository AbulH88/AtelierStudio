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
import threading
import time
import uuid

import requests
from functools import wraps
from flask import (Flask, request, jsonify, send_from_directory, send_file, Response,
                   session, redirect)
from werkzeug.security import generate_password_hash, check_password_hash

# import the shared workflow logic from the repo root (one level up)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comfy_common  # noqa: E402


def _load_env():  # tiny .env loader (no extra dependency)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
import r2_store       # noqa: E402  (Cloudflare R2 reel library; reads env above)
import yt_dlp         # noqa: E402  (Instagram reel downloader)

ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "")
API_KEY = os.environ.get("RUNPOD_API_KEY", "")
RUNPOD_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync"
RUNPOD_HEALTH_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/health"
LOCAL_COMFY = os.environ.get("LOCAL_COMFY_URL", "http://127.0.0.1:8189")  # matches Windows_Run_GPU.bat
# Max images generated per ComfyUI run on Local. The 5090 can batch several at
# once, so "Variations: N" runs as ONE batch (fast) instead of N looped runs.
# Lower this if a big batch ever OOMs the GPU at high resolutions.
LOCAL_MAX_BATCH = max(1, int(os.environ.get("LOCAL_MAX_BATCH", "8")))

# Cloud (RunPod) cost + capacity hints. Cost is ESTIMATE-ONLY: the UI multiplies
# price_per_sec by the measured generation seconds — we never call RunPod billing.
RUNPOD_GPU = os.environ.get("RUNPOD_GPU", "L40S")
RUNPOD_REGION = os.environ.get("RUNPOD_REGION", "")
# Approximate RunPod serverless $/sec by GPU (flex rate, 2025). Keys are the GPU
# name upper-cased with spaces/dashes stripped. Override the active GPU's rate
# directly with RUNPOD_PRICE_PER_SEC.
GPU_PRICE_PER_SEC = {
    "L40S": 0.00053, "L40": 0.00053, "A40": 0.00044,
    "RTX4090": 0.00034, "RTX5090": 0.00046, "RTXA6000": 0.00049,
    "A100": 0.00076, "A100SXM": 0.00114, "H100": 0.00155, "H200": 0.00220,
}


def _price_per_sec():
    """$/sec for the active cloud GPU — env override wins, else the table."""
    try:
        v = float(os.environ.get("RUNPOD_PRICE_PER_SEC", "") or 0)
        if v > 0:
            return v
    except ValueError:
        pass
    key = RUNPOD_GPU.upper().replace(" ", "").replace("-", "")
    return GPU_PRICE_PER_SEC.get(key, 0.0005)


# GPUs that can run the 14B fp16 image model (needs >=40GB VRAM), with the RunPod
# REST gpuTypeId + approx serverless flex $/sec. The UI lets the user pick one (or
# "auto" = cheapest-available). Cheapest first.
CLOUD_GPU_OPTIONS = [
    {"id": "NVIDIA GeForce RTX 5090",        "label": "RTX 5090",     "vram": 32,  "price_per_sec": 0.00069},
    {"id": "NVIDIA A40",                     "label": "A40",          "vram": 48,  "price_per_sec": 0.00044},
    {"id": "NVIDIA RTX A6000",               "label": "RTX A6000",    "vram": 48,  "price_per_sec": 0.00049},
    {"id": "NVIDIA L40S",                    "label": "L40S",         "vram": 48,  "price_per_sec": 0.00053},
    {"id": "NVIDIA A100 80GB PCIe",          "label": "A100 80GB",    "vram": 80,  "price_per_sec": 0.00076},
    {"id": "NVIDIA RTX 6000 Ada Generation", "label": "RTX 6000 Ada", "vram": 48,  "price_per_sec": 0.00077},
    {"id": "NVIDIA RTX PRO 6000 Blackwell Server Edition", "label": "RTX PRO 6000 (Blackwell)", "vram": 96, "price_per_sec": 0.00112},
    {"id": "NVIDIA H100 PCIe",               "label": "H100 PCIe",    "vram": 80,  "price_per_sec": 0.00155},
    {"id": "NVIDIA H100 80GB HBM3",          "label": "H100 SXM",     "vram": 80,  "price_per_sec": 0.00169},
    {"id": "NVIDIA B200",                    "label": "B200",         "vram": 180, "price_per_sec": 0.00240},
    {"id": "NVIDIA H200",                    "label": "H200",         "vram": 141, "price_per_sec": 0.00220},
]
RUNPOD_EP_URL = f"https://rest.runpod.io/v1/endpoints/{ENDPOINT_ID}"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "qwen/qwen3-vl-235b-a22b-instruct")
WORKFLOW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# So the app can start ComfyUI for you when it's not running.
COMFY_DIR = os.environ.get("COMFY_DIR", "I:/@home/jimi/Documents/ComfyUI_V82")
COMFY_BAT = os.environ.get("COMFY_BAT", "Windows_Run_GPU.bat")

# Home agent — when set (on the VPS), start/stop go through it instead of a local
# subprocess (the VPS can't launch programs on the home PC directly).
AGENT_URL = os.environ.get("AGENT_URL", "").rstrip("/")
AGENT_SECRET = os.environ.get("AGENT_SECRET", "")

# --- live generation progress ------------------------------------------------
# Shared client id: the VPS submits /prompt with it and the home agent's WS
# listens with it, so ComfyUI routes step-progress to the agent. On the VPS we
# poll the agent's /progress (WS through the tunnel 502s); locally we listen direct.
CLIENT_ID = "atelier-progress"
PROGRESS = {"running": False, "value": 0, "max": 0}


def _ws_loop():
    try:
        import websocket  # websocket-client
    except Exception:
        return
    ws_url = (LOCAL_COMFY.replace("https://", "wss://").replace("http://", "ws://")
              + f"/ws?clientId={CLIENT_ID}")
    while True:
        try:
            conn = websocket.create_connection(ws_url, timeout=40)
            while True:
                msg = conn.recv()
                if not isinstance(msg, str):
                    continue
                d = _json.loads(msg)
                t, data = d.get("type"), d.get("data", {})
                if t == "progress":
                    PROGRESS.update(running=True, value=data.get("value", 0), max=data.get("max", 0))
                elif t == "execution_start":
                    PROGRESS.update(running=True, value=0, max=0)
                elif t == "executing" and data.get("node") is None:
                    PROGRESS.update(running=False, value=0, max=0)
                elif t in ("execution_success", "execution_error", "execution_interrupted"):
                    PROGRESS.update(running=False, value=0, max=0)
        except Exception:
            PROGRESS.update(running=False)
            time.sleep(3)


if not AGENT_URL:   # local dev: listen directly; on the VPS the agent does it
    threading.Thread(target=_ws_loop, daemon=True).start()

FRAMES_DIR = os.path.join(os.path.dirname(__file__), "frames")
os.makedirs(FRAMES_DIR, exist_ok=True)

# Instagram cookies (Netscape cookies.txt) for yt-dlp — lets it download
# account-required reels. Admin-managed, gitignored.
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ig_cookies.txt")

app = Flask(__name__, static_folder=None)

# ----------------------------- auth / login gate ------------------------------
import json as _json  # noqa: E402
HERE = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(HERE, "users.json")
SECRET_FILE = os.path.join(HERE, ".secret")


def _secret():
    s = os.environ.get("FLASK_SECRET")
    if s:
        return s
    if os.path.exists(SECRET_FILE):
        return open(SECRET_FILE).read().strip()
    s = uuid.uuid4().hex + uuid.uuid4().hex
    open(SECRET_FILE, "w").write(s)
    return s


app.secret_key = _secret()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14)


def load_users():
    return _json.load(open(USERS_FILE, encoding="utf-8")) if os.path.exists(USERS_FILE) else {}


def save_users(u):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        _json.dump(u, f, indent=2)


# endpoints reachable without being logged in
OPEN_ENDPOINTS = {"login_page", "api_login", "api_signup"}


@app.before_request
def _gate():
    if request.endpoint in OPEN_ENDPOINTS:
        return
    user = session.get("user")
    users = load_users()
    if not user or user not in users or users[user]["status"] != "active":
        if user:
            session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"error": "auth required"}), 401
        return redirect("/login")


def admin_required(fn):
    @wraps(fn)
    def w(*a, **k):
        u = session.get("user")
        if not u or load_users().get(u, {}).get("role") != "admin":
            return jsonify({"error": "admin only"}), 403
        return fn(*a, **k)
    return w


@app.get("/login")
def login_page():
    return send_file(os.path.join(HERE, "login.html"))


@app.post("/api/login")
def api_login():
    b = request.get_json(force=True)
    u = b.get("username", "").strip().lower()
    users = load_users()
    rec = users.get(u)
    if not rec or not check_password_hash(rec["password"], b.get("password", "")):
        return jsonify({"error": "Invalid username or password."}), 401
    if rec["status"] != "active":
        msg = "Account is pending admin approval." if rec["status"] == "pending" else "Account is disabled."
        return jsonify({"error": msg}), 403
    session.permanent = True
    session["user"] = u
    return jsonify({"ok": True, "role": rec["role"]})


@app.post("/api/signup")
def api_signup():
    b = request.get_json(force=True)
    u = b.get("username", "").strip().lower()
    p = b.get("password", "")
    if not u or not p:
        return jsonify({"error": "Username and password required."}), 400
    users = load_users()
    if u in users:
        return jsonify({"error": "That username is taken."}), 400
    first = len(users) == 0   # the very first account becomes the admin
    users[u] = {"password": generate_password_hash(p),
                "role": "admin" if first else "user",
                "status": "active" if first else "pending"}
    save_users(users)
    return jsonify({"ok": True, "first": first, "status": users[u]["status"]})


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    u = session.get("user")
    return jsonify({"user": u, "role": load_users().get(u, {}).get("role")})


@app.get("/api/users")
@admin_required
def api_users():
    users = load_users()
    return jsonify({"users": [{"username": k, "role": v["role"], "status": v["status"]}
                              for k, v in sorted(users.items())]})


@app.post("/api/users/<name>/<action>")
@admin_required
def api_user_action(name, action):
    users = load_users()
    name = name.lower()
    if name not in users:
        return jsonify({"error": "no such user"}), 404
    admins = sum(1 for v in users.values() if v["role"] == "admin")
    if action == "activate":
        users[name]["status"] = "active"
    elif action == "disable":
        if users[name]["role"] == "admin" and admins <= 1:
            return jsonify({"error": "cannot disable the last admin"}), 400
        users[name]["status"] = "disabled"
    elif action == "make-admin":
        users[name]["role"] = "admin"
    elif action == "delete":
        if users[name]["role"] == "admin" and admins <= 1:
            return jsonify({"error": "cannot delete the last admin"}), 400
        del users[name]
    else:
        return jsonify({"error": "unknown action"}), 400
    save_users(users)
    return jsonify({"ok": True})


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

# Krea2 characters live under a separate LoRA root (confirmed on the home PC:
# H:/ConfiuiModels/models/loras/Keara2/{CristinaCosplay,GothNiche}/...), not
# under wan/ like the WAN character LoRAs.
KREA2_LORA_ROOT = "Keara2"

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


CATALOG_CACHE = os.path.join(HERE, ".catalog.json")


def _comfy_loras():
    """Live LoRA list from ComfyUI (works on the VPS via the tunnel)."""
    r = requests.get(f"{LOCAL_COMFY}/object_info/LoraLoaderModelOnly",
                     headers=comfy_common.CF_HEADERS, timeout=8)
    r.raise_for_status()
    d = r.json()
    return d[list(d.keys())[0]]["input"]["required"]["lora_name"][0]


def _group_characters(loras):
    norm = [l.replace("\\", "/") for l in loras]
    res = []
    for d in CHAR_DEFS:
        folder = d["folder"].rstrip("/") + "/"
        variants = []
        for p in norm:
            if p.lower().startswith(folder.lower()):
                label = os.path.splitext(p[len(folder):])[0] or p.split("/")[-1]
                variants.append({"label": label, "path": p})
        if variants:
            variants.sort(key=lambda v: (bool(_STEP.search(v["label"])), v["label"]))
            res.append({"key": d["key"], "label": d["label"], "variants": variants})
    return res


def _auto_char_key(name):
    return "myl_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _auto_characters(loras, parent="wan/MyLoras"):
    """Auto-discover characters from immediate subfolders of <parent>: each subfolder
    is a character (label = folder name); the .safetensors inside are its checkpoints.
    Lets the user add a character by dropping its folder into MyLoras — no code edits."""
    prefix = (parent.rstrip("/") + "/").lower()
    chars = {}   # subfolder name -> [{label, path}]
    for raw in loras:
        p = raw.replace("\\", "/")
        i = p.lower().find(prefix)
        if i < 0:
            continue
        rest = p[i + len(prefix):]
        if "/" not in rest:        # a loose file directly in MyLoras (no character folder)
            continue
        sub, inner = rest.split("/", 1)
        chars.setdefault(sub, []).append({"label": os.path.splitext(inner)[0], "path": p})
    res = []
    for sub in sorted(chars, key=str.lower):
        variants = sorted(chars[sub], key=lambda v: (bool(_STEP.search(v["label"])), v["label"]))
        res.append({"key": _auto_char_key(sub), "label": sub, "variants": variants})
    return res


def _auto_characters_fs(parent="wan/MyLoras"):
    """Filesystem version of _auto_characters (home dev, where H: is reachable)."""
    base = os.path.join(LORAS_DIR, *parent.split("/"))
    res = []
    if os.path.isdir(base):
        for d in sorted(os.listdir(base), key=str.lower):
            if os.path.isdir(os.path.join(base, d)):
                v = _list_variants(os.path.join(*parent.split("/"), d))
                if v:
                    res.append({"key": _auto_char_key(d), "label": d, "variants": v})
    return res


def build_characters():
    # Characters come ONLY from wan/MyLoras/ subfolders — drop a folder in = a character.
    # (The hardcoded CHAR_DEFS list is no longer shown; it's kept only for gallery grouping.)
    # An empty result is valid (no folders yet) — don't fall back to the old curated list.
    try:
        chars = _auto_characters(_comfy_loras())   # live ComfyUI list; [] is a valid result
        try:
            with open(CATALOG_CACHE, "w", encoding="utf-8") as f:
                _json.dump(chars, f)
        except Exception:
            pass
        return chars
    except Exception:
        pass
    # fallback: local filesystem scan (home dev, where H: is reachable)
    try:
        return _auto_characters_fs()
    except Exception:
        pass
    # last resort: previously cached catalog
    if os.path.exists(CATALOG_CACHE):
        try:
            return _json.load(open(CATALOG_CACHE, encoding="utf-8"))
        except Exception:
            pass
    return []


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


# The realism/technique "helper" LoRAs baked into the krea2hq Power Lora Loader
# (slots 2/3 of node 11). These are the on-by-default set; the UI can toggle them
# off, retune strength, or add more from build_krea2_helper_loras(). Paths are the
# forward-slash form ComfyUI accepts on the local Windows install.
KREA2HQ_DEFAULT_HELPERS = [
    {"path": "Keara2/mix/RealisomHelper/RealisticSnapshotKrea2.safetensors", "strength": 0.6},
    {"path": "Keara2/mix/RealisomHelper/realism_engine_krea2_v3.1.safetensors", "strength": 0.6},
]


def build_krea2_helper_loras():
    """Krea2 helper (non-identity) LoRAs available to the krea2hq picker — every
    .safetensors under the Keara2 'mix' area (live ComfyUI list, filesystem fallback
    at home, cached last resort). The fixed defaults are always included so the
    picker is never empty even when the scan can't reach the models."""
    items = []
    try:
        items = [l.replace("\\", "/") for l in _comfy_loras()
                 if l.replace("\\", "/").lower().startswith("keara2/")
                 and "/mix/" in l.replace("\\", "/").lower()]
    except Exception:
        items = []
    if not items:
        base = os.path.join(LORAS_DIR, "Keara2", "mix")
        if os.path.isdir(base):
            for root, _, files in os.walk(base):
                for fn in files:
                    if fn.lower().endswith(".safetensors"):
                        full = os.path.join(root, fn)
                        items.append(os.path.relpath(full, LORAS_DIR).replace("\\", "/"))
    cache = os.path.join(HERE, ".krea2_helpers.json")
    if items:
        try:
            _json.dump(sorted(set(items)), open(cache, "w", encoding="utf-8"))
        except Exception:
            pass
    elif os.path.exists(cache):
        try:
            items = _json.load(open(cache, encoding="utf-8"))
        except Exception:
            items = []
    for d in KREA2HQ_DEFAULT_HELPERS:      # always selectable, even if the scan missed them
        items.append(d["path"])
    items = sorted(set(items))
    return [{"path": p, "label": os.path.splitext(p.split("/")[-1])[0]} for p in items]


# Curated helper LoRAs for the "Add LoRA" picker. The full wan/ folder is 125+
# LoRAs (a mess to scroll) and most won't exist on the RunPod volume — so the
# picker only offers this short, hand-picked set of LOW-noise realism/style
# helpers (the pipeline is single low-noise). Edit this list to add/remove.
# These stack between the locked Lightning LoRA and the character LoRA.
HELPER_LORAS = [
    {"path": "wan/WanInsta/Lenovo/Lenovo.safetensors", "label": "Lenovo"},
    {"path": "wan/WanInsta/WAN2.2-LowNoise_SmartphoneSnapshotPhotoReality_v3_by-AI_Characters/WAN2.2-LowNoise_SmartphoneSnapshotPhotoReality_v3_by-AI_Characters.safetensors", "label": "Smartphone Snapshot (low)"},
    {"path": "wan/WanInsta/Instagirlv2.5-LOW/Instagirlv2.5-LOW.safetensors", "label": "Instagirl v2.5 (low)"},
    {"path": "wan/WanInsta/Instareal_low/Instareal_low.safetensors", "label": "Instareal (low)"},
    {"path": "wan/WanUtility/DetailEnhancerV1/DetailEnhancerV1.safetensors", "label": "Detail Enhancer"},
]


def _folder_loras(subfolder, cache_name):
    """Every LoRA under wan/<subfolder> — live from ComfyUI, filesystem fallback
    at home, cached file as last resort (the VPS has no H: drive). Used to expose
    a whole folder (e.g. wan/NSFW) as a dedicated group in the LoRA picker."""
    prefix = f"wan/{subfolder}/".lower()
    items = []
    try:
        items = [l.replace("\\", "/") for l in _comfy_loras()
                 if l.replace("\\", "/").lower().startswith(prefix)]
    except Exception:
        items = []
    if not items:
        base = os.path.join(LORAS_DIR, "wan", subfolder)
        if os.path.isdir(base):
            for root, _, files in os.walk(base):
                for fn in files:
                    if fn.lower().endswith(".safetensors"):
                        full = os.path.join(root, fn)
                        items.append(os.path.relpath(full, LORAS_DIR).replace("\\", "/"))
    cache = os.path.join(HERE, cache_name)
    if items:
        items = sorted(set(items))
        try:
            _json.dump(items, open(cache, "w", encoding="utf-8"))
        except Exception:
            pass
    elif os.path.exists(cache):
        try:
            items = _json.load(open(cache, encoding="utf-8"))
        except Exception:
            items = []
    return [{"path": p, "label": os.path.splitext(p.split("/")[-1])[0]} for p in items]


def _folder_groups(subfolder, cache_name, label_prefix):
    """Like _folder_loras, but split into one picker group per immediate subfolder
    so the UI mirrors the folder layout. Files sitting directly in the folder go in
    a root group; each subfolder becomes "<label_prefix> · <subfolder>"."""
    flat = _folder_loras(subfolder, cache_name)   # [{path,label}] (live/fs/cache)
    prefix = f"wan/{subfolder}/".lower()
    root_items, groups = [], {}
    for it in flat:
        low = it["path"].lower()
        i = low.find(prefix)
        rest = it["path"][i + len(prefix):] if i >= 0 else it["path"].split("/")[-1]
        if "/" in rest:                       # lives in a subfolder -> its own group
            groups.setdefault(rest.split("/", 1)[0], []).append(it)
        else:                                 # sits directly in the folder -> root group
            root_items.append(it)
    out = []
    if root_items:
        out.append({"label": label_prefix, "items": root_items})
    for sub in sorted(groups, key=str.lower):
        out.append({"label": f"{label_prefix} · {sub}", "items": groups[sub]})
    return out


# --- Cloud LoRA manifest ------------------------------------------------------
# On Cloud, only LoRAs present on the RunPod network volume will load. This
# manifest lists those relative paths (the same form the picker uses, e.g.
# "wan/WanInsta/.../X.safetensors"). Source: CLOUD_LORAS_FILE env (a JSON list,
# or {"loras":[...]}), else a .cloud_loras.json cache next to app.py. An empty
# manifest means "nothing confirmed on the volume yet" — the UI then shows the
# cloud card in a not-ready state instead of greying every row.
CLOUD_LORAS_FILE = os.environ.get("CLOUD_LORAS_FILE",
                                  os.path.join(HERE, ".cloud_loras.json"))


def _cloud_lora_set():
    """Set of normalized (lowercased, fwd-slash) LoRA paths on the RunPod volume."""
    try:
        data = _json.load(open(CLOUD_LORAS_FILE, encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(data, dict):
        data = data.get("loras", [])
    return {str(p).replace("\\", "/").lower() for p in data if p}


def _cloud_lora_list():
    """Raw (cased) LoRA paths on the volume, from .cloud_loras.json."""
    try:
        data = _json.load(open(CLOUD_LORAS_FILE, encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("loras", [])
    return [str(p).replace("\\", "/") for p in data if p]


def build_cloud_characters():
    """Character picker built straight from the cloud volume manifest, so Cloud mode
    shows EVERY character on the volume regardless of the home ComfyUI being up — and
    with the exact paths the volume has (CHAR_DEFS folders differ from the volume layout).
    Groups each own-character LoRA by its folder under wan/Own/<Name>/."""
    groups = {}
    for p in _cloud_lora_list():
        parts = p.split("/")
        if len(parts) >= 3 and parts[0].lower() == "wan" and parts[1].lower() == "own":
            key = parts[2]
            g = groups.setdefault(key, {"key": key.lower(), "label": key, "variants": []})
            g["variants"].append({"label": os.path.splitext(parts[-1])[0], "path": p})
    res = sorted(groups.values(), key=lambda c: c["label"].lower())
    for c in res:
        c["variants"].sort(key=lambda v: v["label"].lower())
    return res


def _cloud_status():
    """Live RunPod endpoint health (warming / ready / queue). Degrades to
    {configured:False} with no creds, {configured:True, error:...} on failure."""
    if not (ENDPOINT_ID and API_KEY):
        return {"configured": False}
    try:
        r = requests.get(RUNPOD_HEALTH_URL,
                         headers={"Authorization": f"Bearer {API_KEY}"}, timeout=8)
        r.raise_for_status()
        d = r.json() or {}
        w = d.get("workers", {}) or {}
        j = d.get("jobs", {}) or {}
        ready = (w.get("ready", 0) + w.get("running", 0) + w.get("idle", 0)) > 0
        warming = (not ready) and w.get("initializing", 0) > 0
        return {"configured": True, "ready": ready, "warming": warming,
                "workers": w, "queued": j.get("inQueue", 0),
                "in_progress": j.get("inProgress", 0),
                "unhealthy": w.get("unhealthy", 0) + w.get("throttled", 0)}
    except Exception as e:
        return {"configured": True, "error": f"{type(e).__name__}: {e}"}


# Per-mode default Lightning (lightx2v) LoRA — now tweakable from the UI but these
# are the safe defaults baked into the workflows. t2i MUST stay v2-distill @0.6
# (anything else risks confetti noise); i2i uses the 4-step rank64 @1.0.
LIGHTNING_DEFAULTS = {
    "i2i": {"path": "wan/WanLightning/Wan2.1-Distill-Loras/wan2.1_t2v_14b_lora_rank64_lightx2v_4step/wan2.1_t2v_14b_lora_rank64_lightx2v_4step.safetensors", "strength": 1.0},
    "t2i": {"path": "wan/WanLightning/lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank128_bf16/lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank256_bf16.safetensors", "strength": 0.6},
}


# Curated OpenRouter vision models for the "Describe with AI" dropdown. Kept short
# on purpose (the full /models list is 300+). Edit this list to add/remove options;
# the first entry is the default. DeepSeek has no vision model on OpenRouter, so
# Qwen3-VL covers the uncensored/strong slot. OpenAI/Anthropic models refuse even
# non-explicit figure/body-type descriptions of real people (confirmed: refuses
# "curvy hourglass figure" language on a fully clothed, non-nude photo, Explicit
# toggle off) — not just NSFW. Effectively unusable for this app's core describe
# workflow (body type is central to it); kept only for clothing/scene-only use
# with Body Type left blank.
VISION_MODELS = [
    {"id": "qwen/qwen3-vl-235b-a22b-instruct",      "name": "Qwen3-VL 235B (SFW + NSFW · default)"},
    {"id": "qwen/qwen3-vl-32b-instruct",            "name": "Qwen3-VL 32B (both · cheaper)"},
    {"id": "x-ai/grok-4.3",                         "name": "Grok 4.3 (both · least filtered)"},
    {"id": "openai/gpt-4o",                         "name": "GPT-4o (refuses figure/body descriptions — scene-only)"},
    {"id": "anthropic/claude-sonnet-5",              "name": "Claude Sonnet 5 (refuses figure/body descriptions — scene-only)"},
    {"id": "mistralai/mistral-small-3.2-24b-instruct", "name": "Mistral Small 3.2 (both · cheap)"},
    {"id": "z-ai/glm-4.6v",                         "name": "GLM-4.6V (both)"},
    {"id": "google/gemini-2.5-flash",               "name": "Gemini 2.5 Flash (SFW only · fast)"},
    {"id": "nvidia/nemotron-nano-12b-v2-vl:free",   "name": "Nemotron Nano 12B VL (free · SFW)"},
]

ASPECTS = [
    {"key": "portrait",  "label": "Portrait · 9:16", "width": 1080, "height": 1920},
    {"key": "square",    "label": "Square · 1:1",    "width": 1080, "height": 1080},
    {"key": "landscape", "label": "Landscape · 16:9","width": 1920, "height": 1080},
]

# Resolution presets for Krea2 High Quality (mirrors the source ComfyUI workflow's
# in-graph "Empty Latent Image (Res Presets)" dropdown — that node was dropped from
# workflow_krea2hq.json in favor of the app computing width/height itself, same
# pattern as ASPECTS above). Grouped by category for the UI's <optgroup>s.
RES_PRESETS = [
    {"group": "Landscape", "key": "landscape_1k", "label": "Landscape 1K", "width": 1024, "height": 576},
    {"group": "Landscape", "key": "landscape_2k", "label": "Landscape 2K", "width": 1920, "height": 1088},
    {"group": "Landscape", "key": "landscape_3k", "label": "Landscape 3K", "width": 2560, "height": 1440},
    {"group": "Landscape", "key": "landscape_4k", "label": "Landscape 4K", "width": 3840, "height": 2160},
    {"group": "Portrait",  "key": "portrait_1k",  "label": "Portrait 1K",  "width": 768,  "height": 1024},
    {"group": "Portrait",  "key": "portrait_2k",  "label": "Portrait 2K",  "width": 1440, "height": 1920},
    {"group": "Portrait",  "key": "portrait_3k",  "label": "Portrait 3K",  "width": 1920, "height": 2560},
    {"group": "Portrait",  "key": "portrait_4k",  "label": "Portrait 4K",  "width": 2880, "height": 3840},
    {"group": "Full Body", "key": "fullbody_1k",  "label": "Full Body 1K", "width": 576,  "height": 1024},
    {"group": "Full Body", "key": "fullbody_2k",  "label": "Full Body 2K", "width": 1088, "height": 1920},
    {"group": "Full Body", "key": "fullbody_3k",  "label": "Full Body 3K", "width": 1440, "height": 2560},
    {"group": "Full Body", "key": "fullbody_4k",  "label": "Full Body 4K", "width": 2160, "height": 3840},
    {"group": "Square",    "key": "square_1k",    "label": "Square 1K",    "width": 1024, "height": 1024},
    {"group": "Square",    "key": "square_2k",    "label": "Square 2K",    "width": 2048, "height": 2048},
    {"group": "Square",    "key": "square_3k",    "label": "Square 3K",    "width": 3072, "height": 3072},
    {"group": "Square",    "key": "square_4k",    "label": "Square 4K",    "width": 4096, "height": 4096},
]


@app.get("/")
def index():
    # never cache the SPA shell so deploys show up without a manual hard-refresh
    resp = send_file(os.path.join(os.path.dirname(__file__), "index.html"))
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.get("/api/config")
def config():
    return jsonify({"characters": build_characters(),
                    "cloud_characters": build_cloud_characters(),
                    "krea2_characters": build_krea2_characters(), "aspects": ASPECTS,
                    "res_presets": RES_PRESETS,
                    "krea2_helpers": build_krea2_helper_loras(),
                    "krea2hq_default_helpers": KREA2HQ_DEFAULT_HELPERS,
                    "lightning": {"options": _folder_loras("WanLightning", ".lightning_loras.json"),
                                  "defaults": LIGHTNING_DEFAULTS}})


@app.get("/api/loras")
def api_loras():
    """LoRA picker options: curated helpers + whole-folder groups (each its own group).
    'My LoRAs' = anything dropped into loras/wan/MyLoras/ — auto-populates, no config."""
    return jsonify({"groups": _folder_groups("MyLoras", ".my_loras.json", "My LoRAs") + [
        {"label": "Helpers", "items": HELPER_LORAS},
        {"label": "NSFW", "items": _folder_loras("NSFW", ".nsfw_loras.json")},
    ]})


@app.get("/api/characters")
def api_characters():
    """Just the character list (curated + auto-discovered from MyLoras), so the UI
    can refresh the Character dropdown after a folder is added — no page reload."""
    return jsonify({"characters": build_characters()})


@app.get("/api/health")
def health():
    """Report which compute targets are available so the UI can auto-pick."""
    local = False
    try:
        r = requests.get(f"{LOCAL_COMFY}/system_stats", headers=comfy_common.CF_HEADERS,
                         allow_redirects=False, timeout=6)
        local = r.status_code == 200  # 302 (Access login) / 502 (tunnel down) => not ready
    except Exception:
        pass
    return jsonify({"local": local, "cloud": bool(ENDPOINT_ID and API_KEY)})


@app.get("/api/cloud/info")
def cloud_info():
    """Static-ish cloud facts the UI needs once: cost rate, GPU, and the LoRA
    manifest (so the picker can tag what's on the volume). No RunPod call."""
    manifest = sorted(_cloud_lora_set())
    return jsonify({
        "configured": bool(ENDPOINT_ID and API_KEY),
        "gpu": RUNPOD_GPU, "region": RUNPOD_REGION,
        "price_per_sec": _price_per_sec(),
        "manifest": manifest, "manifest_count": len(manifest),
    })


@app.get("/api/cloud/status")
def cloud_status():
    """Live endpoint health for the warming/health strip (polled in cloud mode)."""
    return jsonify(_cloud_status())


def _live_gpus(dc=None):
    """LIVE GPUs from RunPod for the datacenter: >=32GB (fits the 28GB model) and
    in stock, each with the real gpuTypeId + $/sec (from on-demand $/hr). Free
    GraphQL read, no pods. Returns [] on error / no key."""
    if not API_KEY:
        return []
    dc = (RUNPOD_REGION if dc is None else dc) or ""
    q = ("query($dc:String){ gpuTypes { id displayName memoryInGb "
         "lowestPrice(input:{gpuCount:1, dataCenterId:$dc}){ stockStatus uninterruptablePrice } } }")
    try:
        r = requests.post("https://api.runpod.io/graphql",
                          headers={"Authorization": f"Bearer {API_KEY}"},
                          json={"query": q, "variables": {"dc": dc}}, timeout=15)
        types = ((r.json() or {}).get("data") or {}).get("gpuTypes") or []
    except Exception:
        return []
    rank = {"High": 0, "Medium": 1, "Low": 2}
    out = []
    for g in types:
        mem = g.get("memoryInGb") or 0
        lp = g.get("lowestPrice") or {}
        stock = lp.get("stockStatus")
        if mem >= 32 and stock:
            hr = lp.get("uninterruptablePrice") or 0
            out.append({"id": g["id"], "label": g.get("displayName") or g["id"],
                        "vram": mem, "stock": stock, "price_per_sec": round((hr or 0) / 3600.0, 8)})
    out.sort(key=lambda x: (rank.get(x["stock"], 3), x["price_per_sec"] or 9))
    return out


@app.get("/api/cloud/gpus")
def cloud_gpus():
    """LIVE GPU options from RunPod (in-stock, model-capable) + the endpoint's current pick."""
    current = "auto"
    try:
        if ENDPOINT_ID and API_KEY:
            r = requests.get(RUNPOD_EP_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=8)
            ids = (r.json() or {}).get("gpuTypeIds") or []
            if len(ids) == 1:
                current = ids[0]
    except Exception:
        pass
    return jsonify({"options": _live_gpus(), "current": current})


@app.post("/api/cloud/gpu")
@admin_required
def cloud_set_gpu():
    """Reconfigure the shared endpoint's GPU. 'auto' -> every in-stock model-capable
    card; a specific id -> lock to it. Admin-only (changes the endpoint for everyone)."""
    if not (ENDPOINT_ID and API_KEY):
        return jsonify({"error": "cloud not configured"}), 400
    gid = (request.get_json(force=True) or {}).get("gpu", "auto")
    if gid == "auto":
        ids = [g["id"] for g in _live_gpus()] or [g["id"] for g in CLOUD_GPU_OPTIONS]
    else:
        ids = [gid]   # RunPod validates the id on PATCH
    try:
        r = requests.patch(RUNPOD_EP_URL, headers={"Authorization": f"Bearer {API_KEY}"},
                           json={"gpuTypeIds": ids}, timeout=15)
        r.raise_for_status()
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502
    return jsonify({"ok": True, "current": gid})


@app.get("/api/cloud/gpu-availability")
def cloud_gpu_availability():
    """Live GPU stock in the endpoint's datacenter (no pods created — a free
    GraphQL read). Lets the UI show whether a runnable GPU is in stock before a gen."""
    if not API_KEY:
        return jsonify({"configured": False})
    dc = (RUNPOD_REGION or "").strip()
    gpus = _live_gpus(dc)
    return jsonify({"configured": True, "dc": dc or "endpoint default",
                    "any": bool(gpus), "gpus": gpus})


# Wishlist of LoRAs users want pushed to the cloud volume (the "request sync"
# button). We only record the request — nothing auto-syncs. Admin reviews it.
SYNC_FILE = os.path.join(HERE, "cloud_sync_requests.json")
SYNC_LOCK = threading.Lock()


@app.post("/api/cloud/request-sync")
def cloud_request_sync():
    b = request.get_json(force=True) or {}
    path = (b.get("path") or "").replace("\\", "/").strip()
    if not path:
        return jsonify({"error": "no path"}), 400
    entry = {"path": path, "label": (b.get("label") or "").strip(),
             "kind": b.get("kind", "lora"),
             "user": session.get("user", "?"), "ts": int(time.time())}
    with SYNC_LOCK:
        try:
            reqs = _json.load(open(SYNC_FILE, encoding="utf-8"))
        except Exception:
            reqs = []
        if not any(r.get("path") == path for r in reqs):
            reqs.append(entry)
            _json.dump(reqs, open(SYNC_FILE, "w", encoding="utf-8"), indent=2)
    return jsonify({"ok": True})


@app.get("/api/cloud/sync-requests")
@admin_required
def cloud_sync_requests():
    try:
        reqs = _json.load(open(SYNC_FILE, encoding="utf-8"))
    except Exception:
        reqs = []
    reqs.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return jsonify({"requests": reqs})


def _agent(path):
    r = requests.post(f"{AGENT_URL}{path}", headers={"x-agent-secret": AGENT_SECRET}, timeout=30)
    return jsonify(r.json()), r.status_code


@app.post("/api/start-comfy")
def start_comfy():
    """Start ComfyUI — via the home agent on the VPS, or a local subprocess locally."""
    if AGENT_URL:
        try:
            return _agent("/start")
        except Exception as e:
            return jsonify({"error": f"home agent unreachable: {e}"}), 502
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


def _extract_frames(vpath, every):
    """Run ffmpeg on a saved video -> a frames session. Returns (session, urls)."""
    session = uuid.uuid4().hex[:12]
    sdir = os.path.join(FRAMES_DIR, session)
    os.makedirs(sdir, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", vpath,
           "-vf", f"select=not(mod(n\\,{every}))", "-vsync", "vfr",
           "-q:v", "3", os.path.join(sdir, "%04d.jpg")]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr[-400:])
    frames = sorted(f for f in os.listdir(sdir) if f.endswith(".jpg"))
    return session, [f"/frames/{session}/{f}" for f in frames]


@app.post("/api/extract")
def extract():
    video = request.files.get("video")
    every = int(request.form.get("every", 10))
    if not video:
        return jsonify({"error": "No video uploaded."}), 400
    tmp = os.path.join(FRAMES_DIR, "upload_" + uuid.uuid4().hex + os.path.splitext(video.filename)[1])
    video.save(tmp)
    try:
        session, frames = _extract_frames(tmp, every)
    except RuntimeError as e:
        return jsonify({"error": "ffmpeg failed", "detail": str(e)}), 500
    finally:
        os.path.exists(tmp) and os.remove(tmp)
    return jsonify({"session": session, "frames": frames})


# ----------------------------- R2 reel library --------------------------------
@app.get("/api/reels/config")
def reels_config():
    return jsonify({"configured": r2_store.configured(), "bucket": r2_store.BUCKET})


@app.get("/api/reels/folders")
def reels_folders():
    try:
        r2_store.ensure_bucket()
        return jsonify({"folders": r2_store.list_folders()})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.post("/api/reels/folder")
@admin_required
def reels_folder_create():
    name = request.get_json(force=True).get("name", "").strip()
    if not name:
        return jsonify({"error": "Folder name required."}), 400
    r2_store.create_folder(name)
    return jsonify({"ok": True})


@app.post("/api/reels/folder/delete")
@admin_required
def reels_folder_delete():
    folder = request.get_json(force=True).get("folder", "").strip()
    if not folder:
        return jsonify({"error": "Folder required."}), 400
    r2_store.delete_folder(folder)
    return jsonify({"ok": True})


@app.get("/api/reels/cookies/status")
def reels_cookies_status():
    return jsonify({"set": os.path.exists(COOKIES_FILE)})


@app.post("/api/reels/cookies")
@admin_required
def reels_cookies_set():
    text = ""
    if request.files.get("cookies"):
        text = request.files["cookies"].read().decode("utf-8", "replace")
    elif request.is_json:
        text = request.get_json(force=True).get("text", "")
    text = text.strip()
    if "\t" not in text and "instagram" not in text.lower():
        return jsonify({"error": "That doesn't look like a cookies.txt export."}), 400
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return jsonify({"ok": True})


@app.post("/api/reels/cookies/clear")
@admin_required
def reels_cookies_clear():
    if os.path.exists(COOKIES_FILE):
        os.remove(COOKIES_FILE)
    return jsonify({"ok": True})


@app.get("/api/reels/list")
def reels_list():
    folder = request.args.get("folder", "")
    return jsonify({"reels": r2_store.list_reels(folder)})


@app.post("/api/reels/download")
def reels_download():
    body = request.get_json(force=True)
    url, folder = body.get("url", "").strip(), body.get("folder", "").strip()
    if not url:
        return jsonify({"error": "Paste a reel URL."}), 400
    tmpdir = os.path.join(FRAMES_DIR, "dl_" + uuid.uuid4().hex)
    os.makedirs(tmpdir, exist_ok=True)
    try:
        # %(id)s keeps every reel unique so they never overwrite each other
        opts = {"outtmpl": os.path.join(tmpdir, "%(title).50s_%(id)s.%(ext)s"),
                "format": "mp4/bestvideo+bestaudio/best", "merge_output_format": "mp4",
                "quiet": True, "noplaylist": True}
        if os.path.exists(COOKIES_FILE):   # logged-in download for account-required reels
            opts["cookiefile"] = COOKIES_FILE
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        files = [f for f in os.listdir(tmpdir) if not f.startswith(".")]
        if not files:
            return jsonify({"error": "Download produced no file."}), 500
        local = os.path.join(tmpdir, files[0])
        key = (f"{folder}/" if folder else "") + files[0]
        r2_store.upload(local, key)
        return jsonify({"ok": True, "key": key, "name": files[0]})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.post("/api/reels/upload")
def reels_upload():
    """Upload a local video file straight into the reel library (R2)."""
    f = request.files.get("video")
    folder = (request.form.get("folder") or "").strip()
    if not f or not f.filename:
        return jsonify({"error": "No file selected."}), 400
    if not (f.content_type or "").lower().startswith("video/"):
        return jsonify({"error": "That's not a video file."}), 400
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(f.filename)) or "video.mp4"
    key = (f"{folder}/" if folder else "") + name
    try:
        r2_store.upload_bytes(key, f.read())
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    return jsonify({"ok": True, "key": key, "name": name})


@app.get("/api/reels/media")
@app.get("/api/media")
def reels_media():
    """Proxy any R2 object (reel video or gallery image) so the browser can
    preview/download it without ever seeing the Worker secret."""
    key = request.args.get("key", "")
    if not key:
        return jsonify({"error": "no key"}), 400
    up = r2_store.stream(key, request.headers.get("Range"))
    if up.status_code not in (200, 206):
        return ("not found", up.status_code)
    ext = key.lower().rsplit(".", 1)[-1]
    ct = ("video/mp4" if ext in ("mp4", "mov", "webm")
          else "image/png" if ext == "png" else "image/jpeg")
    headers = {"Content-Type": ct, "Accept-Ranges": "bytes"}
    for h in ("Content-Range", "Content-Length"):
        if h in up.headers:
            headers[h] = up.headers[h]
    if request.args.get("download"):
        headers["Content-Disposition"] = f'attachment; filename="{key.split("/")[-1]}"'
    return Response(up.iter_content(65536), status=up.status_code, headers=headers)


@app.get("/api/reels/save-url")
def reels_save_url():
    """Return a same-origin URL that downloads the reel to the user's PC."""
    key = request.args.get("key", "")
    if not key:
        return jsonify({"error": "no key"}), 400
    from urllib.parse import quote
    return jsonify({"url": f"/api/reels/media?key={quote(key)}&download=1"})


@app.post("/api/reels/delete")
def reels_delete():
    key = request.get_json(force=True).get("key", "")
    if key:
        r2_store.delete(key)
    return jsonify({"ok": True})


@app.post("/api/reels/use")
def reels_use():
    """Pull a stored reel from R2 and extract frames so it can be used as the
    reference video in Video->Character mode."""
    body = request.get_json(force=True)
    key, every = body.get("key", ""), int(body.get("every", 1))
    if not key:
        return jsonify({"error": "No reel selected."}), 400
    tmp = os.path.join(FRAMES_DIR, "reel_" + uuid.uuid4().hex + ".mp4")
    try:
        r2_store.download_to(key, tmp)
        session, frames = _extract_frames(tmp, every)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    finally:
        os.path.exists(tmp) and os.remove(tmp)
    return jsonify({"session": session, "frames": frames})


@app.get("/frames/<session>/<name>")
def frame(session, name):
    return send_from_directory(os.path.join(FRAMES_DIR, session), name)


def _build_input(body):
    """Translate the UI body into the worker input dict (same shape local & cloud)."""
    inp = {
        "mode": body.get("mode", "i2i"),
        "character_lora_path": body.get("character_lora_path", ""),
        "character_strength": float(body.get("character_strength", 1.0)),
        "extra_loras": [{"path": l.get("path", ""), "strength": float(l.get("strength", 1.0))}
                        for l in body.get("loras", []) if l.get("path")],
        "lightning": ({"path": body["lightning"]["path"],
                       "strength": float(body["lightning"].get("strength", 1.0))}
                      if isinstance(body.get("lightning"), dict) and body["lightning"].get("path")
                      else None),
        "variations": int(body.get("variations", 1)),
        "width": int(body.get("width", 1080)),
        "height": int(body.get("height", 1920)),
        "steps": int(body.get("steps", 8)),
        "seed": int(body.get("seed", 0)),
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
        inp["denoise"] = float(body.get("denoise", 0.71))
        inp["refine_denoise"] = float(body.get("refine_denoise", 0.1))
    elif inp["mode"] == "krea2new":
        session, frame_name = body["session"], body["frame"]
        fpath = os.path.join(FRAMES_DIR, session, frame_name)
        with open(fpath, "rb") as f:
            inp["image_b64"] = base64.b64encode(f.read()).decode()
    elif inp["mode"] == "krea2hq":
        session, frame_name = body["session"], body["frame"]
        fpath = os.path.join(FRAMES_DIR, session, frame_name)
        with open(fpath, "rb") as f:
            inp["image_b64"] = base64.b64encode(f.read()).decode()
        inp["denoise"] = float(body.get("denoise", 0.8))   # base sampler only; refine is static
        if "helper_loras" in body:   # only override the baked-in helper slots when the UI sent a list
            inp["helper_loras"] = [{"path": l.get("path", ""), "strength": float(l.get("strength", 0.6))}
                                   for l in body.get("helper_loras", []) if l.get("path")]
    elif inp["mode"] == "video":   # Wan Animate: driving video + ref photo
        inp["video_b64"] = body.get("video_b64", "")
        inp["video_filename"] = body.get("video_filename", "driving.mp4")
        inp["ref_b64"] = body.get("ref_b64", "")
        inp["frame_cap"] = int(body.get("frame_cap", 81))
        inp["fps"] = int(body.get("fps", 30))
        inp["upscale"] = bool(body.get("upscale", False))   # RTX super-res + RIFE tail
    elif inp["mode"] == "adv":   # INSTARAW advanced (LOCAL only): t2i + image-guided i2i
        inp["img2img"] = bool(body.get("img2img", False))
        inp["aspect"] = body.get("aspect", "3:4 (Portrait)")
        inp["ref_b64"] = body.get("ref_b64", "")
        inp["loader_batch_data"] = body.get("loader_batch_data")   # i2i source batch (JSON)
        inp["prompt_batch_data"] = body.get("prompt_batch_data")   # resolved prompts (JSON)
        inp["stages"] = body.get("stages") or {}                   # Main Menu: pipeline stage toggles
        inp["interactive"] = bool(body.get("interactive", False))   # popup picker/mask-paint mid-gen
        inp["openrouter_key"] = OPENROUTER_API_KEY                 # injected; never from the browser
        inp["loras_low"] = [{"path": l.get("path", ""), "strength": float(l.get("strength", 0.6))}
                            for l in body.get("loras_low", []) if l.get("path")]
        inp["loras_high"] = [{"path": l.get("path", ""), "strength": float(l.get("strength", 0.6))}
                             for l in body.get("loras_high", []) if l.get("path")]
    return inp


BODY_TYPE_TAGS = {
    "Curvy hourglass": "a curvy hourglass figure with a defined narrow waist, full bust, and wide hips",
    "Slim": "a slim, slender figure",
    "Athletic / toned": "an athletic, toned figure",
    "Petite": "a petite, small frame",
    "Plus / voluptuous": "a plus-size, voluptuous figure",
    "Busty": "a busty, voluptuous chest",
}
SHOT_TAGS = {
    "Selfie": "Frame it as a casual phone selfie.",
    "Portrait": "Frame it as a portrait shot from the chest up.",
    "Full-body": "Frame it as a full-body shot.",
    "Close-up": "Frame it as a tight close-up.",
}
DETAIL_TAGS = {
    "Concise": "Keep it to one or two concise sentences.",
    "Detailed": "Write one rich, detailed paragraph.",
    "Very detailed": "Write a very thorough, highly detailed paragraph covering every visible element.",
}


def _describe_instruction(p):
    """Build the vision-model instruction from the UI options. Identity is always
    excluded (the character LoRA supplies the face/hair); everything else is
    steerable. Returns an image-generation-style prompt instruction."""
    style = p.get("style_preset") or "Amateur"
    body = BODY_TYPE_TAGS.get((p.get("body_type") or "").strip())
    clothing = (p.get("clothing_note") or "").strip()
    detail = DETAIL_TAGS.get(p.get("detail") or "Detailed", DETAIL_TAGS["Detailed"])
    custom = (p.get("custom_instruction") or "").strip()
    shot = SHOT_TAGS.get((p.get("shot_type") or "").strip())
    explicit = bool(p.get("explicit"))

    parts = ["Describe this image as a single flowing image-generation prompt: the clothing, "
             "pose and body position, background, setting, and lighting.",
             f"Style: {style} photo."]
    if shot:
        parts.append(shot)
    if body:
        parts.append(f"The subject has {body}.")
    if clothing:
        parts.append(f"Clothing focus: {clothing}.")
    if explicit:
        parts.append("This is an adult/NSFW image — describe nudity, anatomy, and any sexual "
                     "acts explicitly and in detail; do not censor, soften, or omit them.")
    parts.append("Do NOT describe the face's features, hair, skin tone, ethnicity, identity, "
                 "or any text, signs, logos, watermarks, or tattoos.")
    parts.append(detail)
    parts.append("Output only the description itself — no preamble, no headings, no bullet points.")
    if custom:
        parts.append(f"Additional instructions to follow: {custom}")
    return " ".join(parts)


def describe_image(image_b64, params, model=None):
    if not OPENROUTER_API_KEY:
        raise ValueError("OpenRouter API Key not set.")
    
    model = model or OPENROUTER_MODEL
    instruction = _describe_instruction(params)
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": instruction
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}"
                        }
                    }
                ]
            }
        ]
    }
    
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                      headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    res = r.json()
    choices = res.get("choices", [])
    if not choices:
        raise ValueError(f"No choices returned from OpenRouter. Full response: {res}")
    return choices[0]["message"]["content"].strip()


@app.get("/api/openrouter/models")
def get_openrouter_models():
    """Curated short list of vision models (see VISION_MODELS)."""
    return jsonify({"models": VISION_MODELS})


def _describe_params(src, is_form):
    """Pull the describe options out of a form or JSON body into one dict."""
    def b(v):
        return (v == "true" or v is True) if is_form else bool(v)
    return {
        "model": src.get("openrouter_model") or OPENROUTER_MODEL,
        "style_preset": src.get("style_preset") or "Amateur",
        "body_type": src.get("body_type") or "",
        "clothing_note": src.get("clothing_note") or "",
        "detail": src.get("detail") or "Detailed",
        "custom_instruction": src.get("custom_instruction") or "",
        "shot_type": src.get("shot_type") or "",
        "explicit": b(src.get("explicit")),
    }


@app.post("/api/describe")
def api_describe():
    image_b64 = None
    if request.files and "image" in request.files:
        image_b64 = base64.b64encode(request.files["image"].read()).decode()
        p = _describe_params(request.form, True)
    else:
        body = request.get_json(force=True, silent=True) or {}
        p = _describe_params(body, False)
        session, frame_name = body.get("session"), body.get("frame")
        if session and frame_name:
            fpath = os.path.join(FRAMES_DIR, session, frame_name)
            if not os.path.exists(fpath):
                return jsonify({"error": "Frame not found."}), 404
            with open(fpath, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode()

    if not image_b64:
        return jsonify({"error": "No image file or frame session/name provided."}), 400

    try:
        prompt = describe_image(image_b64, p, p["model"])
        return jsonify({"prompt": prompt})
    except Exception as e:
        return jsonify({"error": f"OpenRouter call failed: {e}"}), 500



@app.get("/api/progress")
def api_progress():
    if AGENT_URL:
        try:
            r = requests.get(f"{AGENT_URL}/progress",
                             headers={"x-agent-secret": AGENT_SECRET}, timeout=8)
            return jsonify(r.json()), r.status_code
        except Exception:
            return jsonify({"running": False, "value": 0, "max": 0})
    return jsonify(PROGRESS)


# --- INSTARAW advanced: interactive popups + prompt-studio proxies (local only) ---
# Popups arrive as a ComfyUI WS event, which the tunnel drops, so the home agent
# captures them; the browser polls /api/interaction and answers via /api/interact.
@app.get("/api/interaction")
def api_interaction():
    if AGENT_URL:
        try:
            r = requests.get(f"{AGENT_URL}/interaction",
                             headers={"x-agent-secret": AGENT_SECRET}, timeout=8)
            return jsonify(r.json()), r.status_code
        except Exception:
            return jsonify({"active": False})
    return jsonify({"active": False})   # local dev w/o agent: no popup relay


@app.post("/api/interact")
def api_interact():
    body = request.get_json(force=True, silent=True) or {}
    if AGENT_URL:
        try:
            r = requests.post(f"{AGENT_URL}/interact", json=body,
                              headers={"x-agent-secret": AGENT_SECRET}, timeout=30)
            return jsonify(r.json()), r.status_code
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 502
    try:   # local dev: post straight to ComfyUI
        resp = {"unique": body.get("unique")}
        for k in ("selection", "masked_data", "masked_image", "special", "extras"):
            if k in body:
                resp[k] = body[k]
        requests.post(f"{LOCAL_COMFY}/instaraw/interactive_message",
                      data={"response": _json.dumps(resp)},
                      headers=comfy_common.CF_HEADERS, timeout=30)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _instaraw_proxy(path, inject_key=False):
    """Forward a JSON POST to the home ComfyUI's /instaraw/* route (HTTP works through
    the tunnel). Injects the server-side OpenRouter key so the browser never holds it."""
    body = request.get_json(force=True, silent=True) or {}
    if inject_key and not body.get("openrouter_api_key"):
        body["openrouter_api_key"] = OPENROUTER_API_KEY
    try:
        r = requests.post(f"{LOCAL_COMFY}/instaraw/{path}", json=body,
                          headers=comfy_common.CF_HEADERS, timeout=120)
        return (r.content, r.status_code,
                {"Content-Type": r.headers.get("Content-Type", "application/json")})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502


@app.post("/api/instaraw/generate_creative_prompts")
def api_ir_prompts():
    return _instaraw_proxy("generate_creative_prompts", inject_key=True)


@app.post("/api/instaraw/generate_character_description")
def api_ir_chardesc():
    return _instaraw_proxy("generate_character_description", inject_key=True)


@app.post("/api/instaraw/get_random_prompts")
def api_ir_random():
    return _instaraw_proxy("get_random_prompts")


@app.post("/api/instaraw/batch_upload")
def api_ir_upload():
    """Forward i2i source images to ComfyUI's INSTARAW image pool (multipart).
    Prefer the home agent — the comfy hostname is behind Cloudflare Access, which
    bounces multipart uploads to an HTML login page; the agent reaches ComfyUI on
    localhost. Falls back to LOCAL_COMFY for local dev (no agent)."""
    files = [("files", (f.filename, f.stream, f.mimetype)) for f in request.files.getlist("files")]
    if AGENT_URL:
        url, hdrs = f"{AGENT_URL}/batch_upload", {"x-agent-secret": AGENT_SECRET}
    else:
        url, hdrs = f"{LOCAL_COMFY}/instaraw/batch_upload", comfy_common.CF_HEADERS
    try:
        r = requests.post(url, files=files or None,
                          data={"node_id": request.form.get("node_id", "atelier")},
                          headers=hdrs, timeout=120)
        return (r.content, r.status_code,
                {"Content-Type": r.headers.get("Content-Type", "application/json")})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502


@app.get("/api/instaraw/view/<path:filename>")
def api_ir_view(filename):
    """Proxy an uploaded source-image thumbnail/preview from ComfyUI's pool."""
    try:
        r = requests.get(f"{LOCAL_COMFY}/instaraw/view/{filename}",
                         headers=comfy_common.CF_HEADERS, timeout=60, allow_redirects=True)
        return (r.content, r.status_code,
                {"Content-Type": r.headers.get("Content-Type", "image/png")})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# The Prompts Library: the 22MB INSTARAW DB lives on S3 (the node fetches it client-side).
# We fetch + parse it server-side once (its tags/prompt/classification are Python-repr
# strings), slim it, and cache in memory. Works even when ComfyUI is down (VPS -> S3).
_PROMPTS_DB = None
PROMPTS_DB_URL = "https://instara.s3.us-east-1.amazonaws.com/prompts.db.json"


def _load_prompts_db():
    """Fetch + parse the 22MB S3 DB once, cache in memory (~2s, the entries' tags/
    prompt/classification are Python-repr strings). Returns the parsed list."""
    global _PROMPTS_DB
    if _PROMPTS_DB is None:
        import ast

        def _lit(v, default):
            if isinstance(v, str):
                try:
                    return ast.literal_eval(v)
                except Exception:
                    return default
            return v if v is not None else default
        raw = requests.get(PROMPTS_DB_URL, timeout=180).json()
        out = []
        for p in raw:
            pr = _lit(p.get("prompt"), {}) or {}
            cl = _lit(p.get("classification"), {}) or {}
            out.append({"id": p.get("id"), "positive": pr.get("positive", ""),
                        "negative": pr.get("negative", ""), "tags": _lit(p.get("tags"), []) or [],
                        "content_type": cl.get("content_type", ""),
                        "safety_level": cl.get("safety_level", ""),
                        "shot_type": cl.get("shot_type", "")})
        _PROMPTS_DB = out
    return _PROMPTS_DB


@app.get("/api/instaraw/prompts_filters")
def api_ir_filters():
    """Filter dropdown values + total (loads the DB on first call)."""
    try:
        db = _load_prompts_db()
    except Exception as e:
        return jsonify({"error": f"could not load library: {e}"}), 502

    def uniq(k):
        return sorted({p[k] for p in db if p[k]})
    return jsonify({"content": uniq("content_type"), "safety": uniq("safety_level"),
                    "shot": uniq("shot_type"), "total": len(db)})


@app.get("/api/instaraw/prompts_db")
def api_ir_promptsdb():
    """Search/filter/paginate the cached library — returns one small page."""
    try:
        db = _load_prompts_db()
    except Exception as e:
        return jsonify({"error": f"could not load library: {e}"}), 502
    q = request.args.get("q", "").strip().lower()
    c, s, sh = request.args.get("content", ""), request.args.get("safety", ""), request.args.get("shot", "")
    favonly = request.args.get("favonly") == "1"
    favs = set(x for x in request.args.get("favs", "").split(",") if x)
    page = max(0, int(request.args.get("page", 0) or 0))
    per = min(48, max(1, int(request.args.get("per", 12) or 12)))
    res = []
    for p in db:
        if c and p["content_type"] != c:
            continue
        if s and p["safety_level"] != s:
            continue
        if sh and p["shot_type"] != sh:
            continue
        if favonly and p["id"] not in favs:
            continue
        if q and q not in (p["positive"] + " " + " ".join(p["tags"]) + " " + (p["id"] or "")).lower():
            continue
        res.append(p)
    total = len(res)
    return jsonify({"prompts": res[page * per:page * per + per], "total": total,
                    "page": page, "per": per})


# --- async generation jobs --------------------------------------------------
# Cloudflare drops any proxied HTTP request that runs longer than ~100s, and a
# multi-variation generation takes minutes. So /api/generate kicks the work off
# in a background thread and returns a job_id immediately; the browser polls
# /api/generate/result (each request is short). Results are still saved to R2.
GEN_JOBS = {}
GEN_JOBS_LOCK = threading.Lock()


def _mux_audio(video_bytes, audio_src_b64):
    """Carry the driving video's audio onto the (silent) Wan Animate mp4. Returns the
    muxed bytes, or the original video if there is no audio / ffmpeg fails. -shortest
    matches the (usually shorter) animated clip length to the driving audio."""
    if not audio_src_b64:
        return video_bytes
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        vp = os.path.join(td, "v.mp4"); ap = os.path.join(td, "a.mp4"); op = os.path.join(td, "o.mp4")
        with open(vp, "wb") as f:
            f.write(video_bytes)
        with open(ap, "wb") as f:
            f.write(base64.b64decode(audio_src_b64))
        try:
            r = subprocess.run(["ffmpeg", "-y", "-i", vp, "-i", ap,
                                "-map", "0:v:0", "-map", "1:a:0?",
                                "-c:v", "copy", "-c:a", "aac", "-shortest", op],
                               capture_output=True, timeout=180)
            if r.returncode == 0 and os.path.exists(op) and os.path.getsize(op) > 1000:
                with open(op, "rb") as f:
                    return f.read()
        except Exception:
            pass
    return video_bytes


def _run_gen_job(job_id, target, inp, body):
    try:
        # i2i/krea2 with an empty prompt → auto-describe the frame first (OpenRouter)
        if inp["mode"] in ("i2i", "krea2", "krea2new", "krea2hq") and not inp.get("prompt"):
            p = _describe_params(body, False)
            inp["prompt"] = describe_image(inp["image_b64"], p, p["model"])

        if target == "local":
            out = comfy_common.generate(LOCAL_COMFY, WORKFLOW_DIR, inp, client_id=CLIENT_ID,
                                        max_batch=LOCAL_MAX_BATCH)
        else:
            if not (ENDPOINT_ID and API_KEY):
                raise RuntimeError("Cloud not configured (set RunPod env vars).")
            # Async submit + poll. /runsync only holds the connection ~90s, but a
            # Wan Animate video gen runs for minutes — runsync would return no output
            # while the worker is still sampling (looks "killed"). /run + /status waits
            # for the real result up to the endpoint's execution timeout.
            hdr = {"Authorization": f"Bearer {API_KEY}"}
            base = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"
            rid = requests.post(f"{base}/run", json={"input": inp},
                                headers=hdr, timeout=60).json().get("id")
            if not rid:
                raise RuntimeError("RunPod did not return a job id.")
            out = {}
            deadline = time.time() + 1200            # 20 min (matches endpoint executionTimeout)
            while time.time() < deadline:
                st = requests.get(f"{base}/status/{rid}", headers=hdr, timeout=30).json()
                s = st.get("status")
                if s == "COMPLETED":
                    out = st.get("output", {}) or {}
                    break
                if s in ("FAILED", "CANCELLED", "TIMED_OUT"):
                    raise RuntimeError(f"RunPod job {s}: {str(st.get('output') or st.get('error') or '')[:300]}")
                time.sleep(3)
            else:
                raise RuntimeError("RunPod job did not finish within 20 min.")

        if not out or "error" in out:
            raise RuntimeError((out or {}).get("error", "No output from worker."))
        if inp["mode"] == "video":                       # Wan Animate -> mp4(s)
            # May be 1 (raw only) or 2 (raw + RTX-upscaled) videos. Carry the driving
            # audio onto each, persist each to R2 under gallery/ (same prefix images
            # use) so motion results show up in the Gallery tab too — /api/gallery/list
            # is a plain prefix scan, and /api/media already content-types .mp4
            # correctly, so no other backend changes are needed for this to appear.
            vids = out.get("videos", []) or []
            urls, muxed = [], []
            try:
                ts = int(time.time())
                group = _gallery_group(inp)
                seed = out.get("seed", 0)
                for i, b64 in enumerate(vids):
                    raw = _mux_audio(base64.b64decode(b64), inp.get("video_b64"))
                    muxed.append(base64.b64encode(raw).decode())
                    key = f"gallery/{group}/{ts}_{seed}_{i}.mp4"
                    r2_store.upload_bytes(key, raw)
                    urls.append(f"/api/media?key={key}")
            except Exception:
                muxed, urls = vids, []          # R2/mux failed -> fall back to base64
            with GEN_JOBS_LOCK:
                GEN_JOBS[job_id] = {"status": "done", "videos": muxed,
                                    "video_urls": urls,
                                    "video_url": (urls[0] if urls else None),   # back-compat
                                    "seed": out.get("seed")}
            return
        images = out.get("images", [])
        keys = _save_to_gallery(inp, images, out.get("seed"))   # -> R2, returns keys
        # Hand the browser lightweight URLs (served from R2 via /api/media), not
        # 30-40MB of inline base64 — keeps the result response tiny so the UI
        # updates instantly and Develop unlocks without hauling blobs to the page.
        result = {"status": "done", "seed": out.get("seed")}
        if keys and len(keys) == len(images):
            from urllib.parse import quote
            result["image_urls"] = [f"/api/media?key={quote(k, safe='')}" for k in keys]
        else:
            result["images"] = images   # R2 save incomplete -> base64 fallback so the UI still works
        with GEN_JOBS_LOCK:
            GEN_JOBS[job_id] = result
    except Exception as e:
        with GEN_JOBS_LOCK:
            GEN_JOBS[job_id] = {"status": "error", "error": f"{type(e).__name__}: {e}"}


@app.post("/api/generate")
def generate():
    body = request.get_json(force=True)
    target = body.get("target", "local")

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
    elif mode == "krea2new":
        if target != "local":
            return jsonify({"error": "Krea I2I New mode runs on Local only."}), 400
        fpath = os.path.join(FRAMES_DIR, body.get("session", ""), body.get("frame", ""))
        if not os.path.exists(fpath):
            return jsonify({"error": "Frame not found."}), 404
    elif mode == "krea2hq":
        if target != "local":
            return jsonify({"error": "Krea2 High Quality mode runs on Local only."}), 400
        fpath = os.path.join(FRAMES_DIR, body.get("session", ""), body.get("frame", ""))
        if not os.path.exists(fpath):
            return jsonify({"error": "Frame not found."}), 404
    elif mode == "video":
        if target != "local":   # heavy Wan2.2 Animate pipeline runs on the home GPU only
            return jsonify({"error": "Motion mode runs on Local only."}), 400
        if not body.get("video_b64"):
            return jsonify({"error": "Upload a driving video."}), 400
        if not body.get("ref_b64"):
            return jsonify({"error": "Upload a reference image."}), 400
    elif mode == "adv":
        if target != "local":
            return jsonify({"error": "Advanced mode runs on Local only."}), 400
        if not body.get("character_lora_path"):
            return jsonify({"error": "Pick a character."}), 400
        if not body.get("prompt_batch_data"):
            return jsonify({"error": "Generate prompts first."}), 400
    elif not body.get("prompt", "").strip():
        return jsonify({"error": "Type a prompt for text mode."}), 400

    inp = _build_input(body)
    job_id = uuid.uuid4().hex[:12]
    with GEN_JOBS_LOCK:
        # keep only the 10 most recent finished jobs so the dict can't grow forever
        done = [k for k, v in GEN_JOBS.items() if v.get("status") in ("done", "error")]
        for k in done[:-10]:
            GEN_JOBS.pop(k, None)
        GEN_JOBS[job_id] = {"status": "running"}
    threading.Thread(target=_run_gen_job, args=(job_id, target, inp, body), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/generate/result")
def generate_result():
    """Poll target for an async generation job (see /api/generate)."""
    with GEN_JOBS_LOCK:
        j = GEN_JOBS.get(request.args.get("job_id", ""))
    if not j:
        return jsonify({"status": "unknown"}), 404
    return jsonify(j)


def _gallery_group(inp):
    p = (inp.get("character_lora_path") or "").replace("\\", "/").lower()
    # MyLoras auto-characters: group by the character subfolder name
    pref = "wan/myloras/"
    if pref in p:
        rest = p.split(pref, 1)[1]
        if "/" in rest:
            return _auto_char_key(rest.split("/", 1)[0])
    for d in CHAR_DEFS:
        if p.startswith(d["folder"].rstrip("/").lower() + "/"):
            return d["key"]
    return "misc"


def _save_to_gallery(inp, images, seed):
    """Persist each generated image to R2. Returns the list of R2 keys written,
    so the result can be served as lightweight URLs instead of base64 blobs."""
    if not images:
        return []
    group = _gallery_group(inp)
    ts = int(time.time())
    keys = []
    for i, b64 in enumerate(images):
        key = f"gallery/{group}/{ts}_{seed}_{i}.png"
        try:
            r2_store.upload_bytes(key, base64.b64decode(b64))
            keys.append(key)
        except Exception:
            pass
    return keys


@app.get("/api/gallery/groups")
def gallery_groups():
    try:
        return jsonify({"groups": r2_store.list_dirs("gallery/")})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}", "groups": []}), 200


@app.get("/api/gallery/list")
def gallery_list():
    group = request.args.get("group", "")
    prefix = f"gallery/{group}/" if group else "gallery/"
    imgs = r2_store.list_objs(prefix)
    imgs.sort(key=lambda x: x["name"], reverse=True)   # newest first
    return jsonify({"images": imgs})


@app.post("/api/gallery/delete")
def gallery_delete():
    key = request.get_json(force=True).get("key", "")
    if key.startswith("gallery/"):
        r2_store.delete(key)
    return jsonify({"ok": True})


@app.post("/api/gallery/bulk-delete")
def gallery_bulk_delete():
    keys = request.get_json(force=True).get("keys", [])
    for key in keys:
        if key.startswith("gallery/"):
            try:
                r2_store.delete(key)
            except Exception:
                pass
    return jsonify({"ok": True})


@app.post("/api/gallery/bulk-download")
def gallery_bulk_download():
    import io
    import zipfile
    keys = request.get_json(force=True).get("keys", [])
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for key in keys:
            if key.startswith("gallery/"):
                try:
                    r = r2_store.stream(key)
                    r.raise_for_status()
                    data = r.content
                    filename = key.split("/")[-1]
                    zip_file.writestr(filename, data)
                except Exception as e:
                    print(f"Error zipping {key}: {e}")
    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="gallery_images.zip"
    )


@app.post("/api/gallery/delete-group")
def gallery_delete_group():
    group = request.get_json(force=True).get("group", "")
    if group:
        try:
            r2_store.delete_folder(f"gallery/{group}")
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# ----------------------------- sticky notes board ----------------------------
# Shared wall: any logged-in user posts text + optional image/video (stored in
# R2). Metadata in notes.json (thread-locked); media served via /api/media.
NOTES_FILE = os.path.join(HERE, "notes.json")
NOTES_LOCK = threading.Lock()
NOTE_COLORS = {"yellow", "amber", "rose", "green", "blue", "purple"}
NOTE_TEXT_MAX = 2000
NOTE_MAX_FILES = 4
NOTE_MAX_BYTES = 50 * 1024 * 1024


def load_notes():
    if os.path.exists(NOTES_FILE):
        try:
            return _json.load(open(NOTES_FILE, encoding="utf-8"))
        except Exception:
            return []
    return []


def save_notes(notes):
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        _json.dump(notes, f, indent=2)


def _note_media_url(key):
    from urllib.parse import quote
    return f"/api/media?key={quote(key, safe='')}"


@app.get("/api/notes")
def notes_list():
    notes = load_notes()
    notes.sort(key=lambda n: n.get("ts", 0), reverse=True)   # newest first
    for n in notes:
        for m in n.get("media", []):
            m["url"] = _note_media_url(m["key"])
    me = session.get("user")
    return jsonify({"notes": notes, "me": me,
                    "is_admin": load_users().get(me, {}).get("role") == "admin"})


@app.post("/api/notes")
def notes_create():
    text = (request.form.get("text") or "").strip()[:NOTE_TEXT_MAX]
    color = request.form.get("color", "yellow")
    if color not in NOTE_COLORS:
        color = "yellow"
    files = [f for f in request.files.getlist("files") if f and f.filename][:NOTE_MAX_FILES]

    if not text and not files:
        return jsonify({"error": "Write something or attach a file."}), 400

    nid = uuid.uuid4().hex[:12]
    media = []
    for f in files:
        ct = (f.content_type or "").lower()
        kind = "image" if ct.startswith("image/") else "video" if ct.startswith("video/") else None
        if not kind:
            return jsonify({"error": f"Unsupported file type: {f.filename} ({ct})."}), 400
        data = f.read()
        if len(data) > NOTE_MAX_BYTES:
            return jsonify({"error": f"{f.filename} is too large (max 50 MB)."}), 400
        if not r2_store.configured():
            return jsonify({"error": "Media storage (R2) is not configured here."}), 500
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(f.filename))[:80] or "file"
        key = f"notes/{nid}/{uuid.uuid4().hex[:6]}_{safe}"
        try:
            r2_store.upload_bytes(key, data)
        except Exception as e:
            return jsonify({"error": f"Upload failed: {type(e).__name__}: {e}"}), 500
        media.append({"key": key, "type": kind, "name": safe})

    note = {"id": nid, "text": text, "color": color, "media": media,
            "author": session.get("user", "?"), "ts": int(time.time())}
    with NOTES_LOCK:
        notes = load_notes()
        notes.append(note)
        save_notes(notes)

    for m in note["media"]:
        m["url"] = _note_media_url(m["key"])
    return jsonify({"note": note})


@app.post("/api/notes/<nid>/delete")
def notes_delete(nid):
    me = session.get("user")
    is_admin = load_users().get(me, {}).get("role") == "admin"
    with NOTES_LOCK:
        notes = load_notes()
        note = next((n for n in notes if n.get("id") == nid), None)
        if not note:
            return jsonify({"error": "Note not found."}), 404
        if note.get("author") != me and not is_admin:
            return jsonify({"error": "You can only delete your own notes."}), 403
        notes = [n for n in notes if n.get("id") != nid]
        save_notes(notes)
    for m in note.get("media", []):
        try:
            r2_store.delete(m["key"])
        except Exception:
            pass
    return jsonify({"ok": True})



@app.post("/api/stop-comfy")
def stop_comfy():
    """Stop ComfyUI — via the home agent on the VPS, or locally via psutil."""
    if AGENT_URL:
        try:
            return _agent("/stop")
        except Exception as e:
            return jsonify({"error": f"home agent unreachable: {e}"}), 502
    import urllib.parse
    import psutil
    try:
        parsed = urllib.parse.urlparse(LOCAL_COMFY)
        port = parsed.port
        if not port:
            return jsonify({"error": "Could not parse port from LOCAL_COMFY_URL"}), 400
        
        pids_killed = []
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.status == 'LISTEN':
                pid = conn.pid
                if pid:
                    try:
                        proc = psutil.Process(pid)
                        for child in proc.children(recursive=True):
                            child.kill()
                        proc.kill()
                        pids_killed.append(pid)
                    except Exception as pe:
                        print(f"Error killing PID {pid}: {pe}")
        
        if pids_killed:
            return jsonify({"ok": True, "killed": pids_killed})
        else:
            return jsonify({"ok": False, "message": "ComfyUI is not running or port is free."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/interrupt")
def interrupt_generation():
    """Cancel / interrupt the current image generation in ComfyUI."""
    target = request.get_json(force=True).get("target", "local")
    if target == "local":
        try:
            r = requests.post(f"{LOCAL_COMFY}/interrupt", timeout=3)
            return jsonify({"ok": True, "status": r.status_code})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        # RunPod sync request doesn't have an interrupt endpoint we can access easily this way,
        # but we return success to allow UI state to reset.
        return jsonify({"ok": True, "message": "Cloud interrupt not supported for sync execution"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)


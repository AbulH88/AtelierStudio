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
import hashlib
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
import tempfile
import uuid

import requests
from functools import wraps
from flask import (Flask, request, jsonify, send_from_directory, send_file, Response,
                   session, redirect)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet, InvalidToken

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
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "qwen/qwen3.8-27b")
# RunningHub Cloud is deliberately independent from RunPod, ComfyUI, and the
# Home Agent. These defaults match the published Scail 2 API workflow; keep
# them overrideable so an exported RunningHub API workflow can change safely.
RUNNINGHUB_BASE_URL = "https://www.runninghub.ai/openapi/v2"
RUNNINGHUB_GLOBAL_API_KEY = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
RUNNINGHUB_GLOBAL_CONCURRENCY = max(1, int(os.environ.get("RUNNINGHUB_CONCURRENCY", "1")))
RUNNINGHUB_WORKFLOW_ID = os.environ.get("RUNNINGHUB_WORKFLOW_ID", "2099782685577601026")
RUNNINGHUB_H3_WORKFLOW_ID = os.environ.get("RUNNINGHUB_H3_WORKFLOW_ID", "2100168430615019522")
# H3 runs successfully on RunningHub Standard in the manually verified workflow.
# Keep infrastructure selection server-side; the Studio UI intentionally has no
# per-user instance selector.
RUNNINGHUB_H3_INSTANCE = os.environ.get("RUNNINGHUB_H3_INSTANCE", "default")
RUNNINGHUB_REFERENCE_NODE_ID = os.environ.get("RUNNINGHUB_REFERENCE_NODE_ID", "58")
RUNNINGHUB_VIDEO_NODE_ID = os.environ.get("RUNNINGHUB_VIDEO_NODE_ID", "113")
RUNNINGHUB_REFERENCE_FIELD = os.environ.get("RUNNINGHUB_REFERENCE_FIELD", "image")
RUNNINGHUB_VIDEO_FIELD = os.environ.get("RUNNINGHUB_VIDEO_FIELD", "video")
RUNNINGHUB_VIDEO_FPS = 24
# Standard Scail 2 on RunningHub has been measured at about ten minutes for a
# short clip. This is only used to label an estimate while the task runs.
RUNNINGHUB_STANDARD_ESTIMATE_SECONDS = 10 * 60
RUNNINGHUB_MAX_IMAGE_BYTES = 25 * 1024 * 1024
RUNNINGHUB_MAX_VIDEO_BYTES = 500 * 1024 * 1024
RUNNINGHUB_MAX_AUDIO_BYTES = 100 * 1024 * 1024
RUNNINGHUB_H3_IMAGE_NODES = (331, 43, 19)
RUNNINGHUB_H3_VIDEO_NODE = 27
RUNNINGHUB_H3_AUDIO_NODES = (48, 14, 15)
RUNNINGHUB_H3_PROMPT_NODE = 263
RUNNINGHUB_H3_ASPECT_NODE = 252
RUNNINGHUB_H3_DURATION_NODE = 259
RUNNINGHUB_H3_TALKING_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_H3_TALKING_WORKFLOW_ID", "2103082156684087297")
RUNNINGHUB_H3_TALKING_INSTANCE = os.environ.get("RUNNINGHUB_H3_TALKING_INSTANCE", "default")
RUNNINGHUB_H3_TALKING_IMAGE_NODE = 9
RUNNINGHUB_H3_TALKING_PROMPT_NODE = 14
RUNNINGHUB_H3_TALKING_DURATION_NODE = 20
RUNNINGHUB_H3_TALKING_MODELS = {
    "openai/gpt-6-luna": "GPT-6 Luna",
    "qwen/qwen3.8-27b": "Qwen 3.8 27B",
}
RUNNINGHUB_H3_TALKING_DEFAULT_MODEL = "openai/gpt-6-luna"
RUNNINGHUB_KREA2_WORKFLOW_ID = os.environ.get("RUNNINGHUB_KREA2_WORKFLOW_ID", "2100309003213901825")
RUNNINGHUB_KREA2_INSTANCE = os.environ.get("RUNNINGHUB_KREA2_INSTANCE", "default")
RUNNINGHUB_KREA2_IMAGE_NODE = 33
RUNNINGHUB_KREA2_PROMPT_NODE = 5
RUNNINGHUB_KREA2_RESIZE_NODE = 13
RUNNINGHUB_KREA2_LORA_NODE = 46
RUNNINGHUB_KREA2_BASE_SAMPLER_NODE = 4
RUNNINGHUB_KREA2_T2I_WORKFLOW_ID = os.environ.get("RUNNINGHUB_KREA2_T2I_WORKFLOW_ID", "2100976623406669826")
RUNNINGHUB_KREA2_T2I_INSTANCE = os.environ.get("RUNNINGHUB_KREA2_T2I_INSTANCE", "default")
RUNNINGHUB_KREA2_T2I_PROMPT_NODE = 6
RUNNINGHUB_KREA2_T2I_LATENT_NODE = 10
RUNNINGHUB_KREA2_T2I_SAMPLER_NODE = 98
RUNNINGHUB_KREA2_T2I_LORA_NODE = 117
# Default entries for the administrator-managed Cloud Krea2 helper registry.
RUNNINGHUB_KREA2_DEFAULT_HELPERS = (
    {"filename": "realism_engine_krea2_v3.1.safetensors", "enabled": True, "strength": 0.60},
    {"filename": "RealisticSnapshotKrea2.safetensors", "enabled": True, "strength": 0.60},
)
WORKFLOW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# So the app can start ComfyUI for you when it's not running (only used when
# AGENT_URL is unset, i.e. running directly on the same dual-boot box as ComfyUI).
_IS_WINDOWS = platform.system() == "Windows"
if _IS_WINDOWS:
    COMFY_DIR = os.environ.get("COMFY_DIR", "G:/ComfyUI_V82")
    COMFY_LAUNCH = os.environ.get("COMFY_BAT", "Windows_Run_GPU_cu132_Auto.bat")
else:
    COMFY_DIR = os.environ.get("COMFY_DIR", "/media/hirokgupta/New Volume/ComfyUI_V82")
    COMFY_LAUNCH = os.environ.get("COMFY_SH", "Linux_Run_GPU.sh")

# Home agent — when set (on the VPS), start/stop go through it instead of a local
# subprocess (the VPS can't launch programs on the home PC directly).
AGENT_URL = os.environ.get("AGENT_URL", "").rstrip("/")
AGENT_SECRET = os.environ.get("AGENT_SECRET", "")

# Every generation mode is local-only (they all run on the owner's home GPU), so
# generation as a whole is gated on the home agent being up — the agent is the
# owner's on/off switch for letting other people use the studio. Browsing, the
# gallery and everything else stay open. Set GEN_REQUIRES_AGENT=0 to disable.
GEN_REQUIRES_AGENT = os.environ.get(
    "GEN_REQUIRES_AGENT", os.environ.get("CLOUD_REQUIRES_AGENT", "1")
) not in ("0", "false", "no")
_AGENT_UP_TTL = 10          # seconds; the UI polls status, don't hammer the tunnel
_agent_up_cache = {"at": 0.0, "up": False}


def _agent_up(force=False):
    """Is the home agent reachable? Cached briefly — this is polled by the UI and
    checked on every cloud generate."""
    if not AGENT_URL:
        # No agent configured (running on the same box as ComfyUI) — nothing to gate.
        return True
    now = time.time()
    if not force and now - _agent_up_cache["at"] < _AGENT_UP_TTL:
        return _agent_up_cache["up"]
    up = False
    try:
        r = requests.get(f"{AGENT_URL}/status",
                         headers={"x-agent-secret": AGENT_SECRET}, timeout=6)
        up = r.status_code == 200
    except Exception:
        pass
    _agent_up_cache.update(at=now, up=up)
    return up

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
RUNNINGHUB_KREA2_T2I_HELPERS_FILE = os.path.join(HERE, "runninghub_krea2_t2i_helpers.json")
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


def _runninghub_fernet():
    """Return the server-only cipher used for stored RunningHub credentials.

    A dedicated RUNNINGHUB_CREDENTIAL_KEY is preferred. Falling back to the
    persistent Flask secret keeps existing self-hosted installs working without
    putting an API key in browser storage or source control.
    """
    material = os.environ.get("RUNNINGHUB_CREDENTIAL_KEY", app.secret_key)
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_runninghub_key(key):
    return _runninghub_fernet().encrypt(key.encode("utf-8")).decode("ascii")


def _decrypt_runninghub_key(ciphertext):
    try:
        return _runninghub_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, AttributeError, ValueError):
        return ""


RUNNINGHUB_GLOBAL_SETTINGS_FILE = os.path.join(HERE, "runninghub_global_settings.json")
RUNNINGHUB_GLOBAL_SETTINGS_LOCK = threading.Lock()


def _load_runninghub_global_settings():
    try:
        with open(RUNNINGHUB_GLOBAL_SETTINGS_FILE, encoding="utf-8") as f:
            data = _json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_runninghub_global_settings(data):
    tmp = RUNNINGHUB_GLOBAL_SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=2)
    os.replace(tmp, RUNNINGHUB_GLOBAL_SETTINGS_FILE)


def _runninghub_global_settings():
    """Admin-managed state overrides the legacy environment fallback."""
    with RUNNINGHUB_GLOBAL_SETTINGS_LOCK:
        state = _load_runninghub_global_settings()
    if state.get("disabled"):
        return {"key": "", "concurrency": RUNNINGHUB_GLOBAL_CONCURRENCY, "source": "none"}
    managed = _decrypt_runninghub_key(state.get("key_enc", ""))
    if managed:
        return {"key": managed, "concurrency": max(1, int(state.get("concurrency", 1) or 1)), "source": "managed"}
    return {"key": RUNNINGHUB_GLOBAL_API_KEY, "concurrency": RUNNINGHUB_GLOBAL_CONCURRENCY,
            "source": "environment" if RUNNINGHUB_GLOBAL_API_KEY else "none"}


def _mask_runninghub_key(key):
    return "••••••••" + key[-4:] if len(key) >= 4 else "••••••••"


def load_users():
    return _json.load(open(USERS_FILE, encoding="utf-8")) if os.path.exists(USERS_FILE) else {}


def save_users(u):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        _json.dump(u, f, indent=2)


# ----------------------------- workflow tab visibility ------------------------
WORKFLOWS_FILE = os.path.join(HERE, "workflows.json")

# (data-mode id, display label) for every tab in the Studio mode bar
WORKFLOW_DEFS = [
    ("i2i", "Wan Image to Image"),
    ("t2i", "Wan Text To Image"),
    ("video", "Wan 2.2 Animate (Wow)"),
    ("ltx25i2v", "LTX 2.5 I2V"),
    ("scail2motion", "High Quality Motion Control Scail 2 · V1.0"),
    ("scail2motionv2", "High Quality Motion Control Scail 2 · V2.0"),
    ("scail2motiondirecttest", "High Quality Motion Control Scail 2 · Direct Resolution Test"),
    ("adv", "Instaraw Advance"),
    ("krea2", "Krea2 Image to Image"),
    ("krea2new", "Krea2 Image to Image new"),
    ("krea2hq", "Krea2 Image to Image High Quality"),
    ("krea2t2ihq", "Krea2 Text to Image High Quality"),
    ("krea2carousel", "Krea2 Carousel Maker"),
]
# krea2new was already hidden in the markup before this setting existed — keep it off by default
WORKFLOW_DEFAULT_DISABLED = {"krea2new"}


def load_workflow_settings():
    saved = _json.load(open(WORKFLOWS_FILE, encoding="utf-8")) if os.path.exists(WORKFLOWS_FILE) else {}
    return {wid: saved.get(wid, wid not in WORKFLOW_DEFAULT_DISABLED) for wid, _label in WORKFLOW_DEFS}


def save_workflow_settings(settings):
    with open(WORKFLOWS_FILE, "w", encoding="utf-8") as f:
        _json.dump(settings, f, indent=2)


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


CLOUD_WORKFLOW_IDS = {"krea2_i2i_hq", "krea2_t2i", "scail", "h3", "h3_talking", "jobs"}


def _cloud_workflows_for(username):
    user = load_users().get(username, {})
    if user.get("role") == "admin":
        return sorted(CLOUD_WORKFLOW_IDS)
    allowed = user.get("cloud_workflows", [])
    return sorted(set(allowed) & CLOUD_WORKFLOW_IDS) if isinstance(allowed, list) else []


def cloud_workflow_required(workflow):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if workflow not in _cloud_workflows_for(session.get("user")):
                return jsonify({"error": "Your administrator has not enabled this Cloud workflow."}), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorate


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
                "status": "active" if first else "pending",
                "runninghub_plus": False}
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
    global_key = _runninghub_global_settings()["key"]
    return jsonify({"users": [{"username": k, "role": v["role"], "status": v["status"],
                                "cloud_workflows": _cloud_workflows_for(k) if v["role"] == "admin" else sorted(set(v.get("cloud_workflows", [])) & CLOUD_WORKFLOW_IDS),
                                "runninghub_plus": bool(v.get("runninghub_plus")),
                                "runninghub_configured": bool(v.get("runninghub_key_enc") or global_key),
                                "runninghub_private": bool(v.get("runninghub_key_enc")),
                                "runninghub_concurrency": max(1, int(v.get("runninghub_concurrency", RUNNINGHUB_GLOBAL_CONCURRENCY) or 1))}
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
    elif action == "set-runninghub-plus":
        enabled = (request.get_json(silent=True) or {}).get("enabled")
        if not isinstance(enabled, bool):
            return jsonify({"error": "enabled must be true or false"}), 400
        users[name]["runninghub_plus"] = enabled
    elif action == "set-cloud-workflows":
        workflows = (request.get_json(silent=True) or {}).get("workflows", [])
        if not isinstance(workflows, list) or any(workflow not in CLOUD_WORKFLOW_IDS for workflow in workflows):
            return jsonify({"error": "Invalid Cloud workflow selection."}), 400
        users[name]["cloud_workflows"] = sorted(set(workflows))
    elif action == "set-runninghub-key":
        body = request.get_json(silent=True) or {}
        key = str(body.get("api_key") or "").strip()
        try:
            concurrency = max(1, min(100, int(body.get("concurrency") or 1)))
        except (TypeError, ValueError):
            return jsonify({"error": "concurrency must be between 1 and 100"}), 400
        if len(key) < 16:
            return jsonify({"error": "Enter a valid RunningHub API key."}), 400
        users[name]["runninghub_key_enc"] = _encrypt_runninghub_key(key)
        users[name]["runninghub_concurrency"] = concurrency
    elif action == "remove-runninghub-key":
        users[name].pop("runninghub_key_enc", None)
        users[name].pop("runninghub_concurrency", None)
    elif action == "delete":
        if users[name]["role"] == "admin" and admins <= 1:
            return jsonify({"error": "cannot delete the last admin"}), 400
        del users[name]
    else:
        return jsonify({"error": "unknown action"}), 400
    save_users(users)
    return jsonify({"ok": True})


@app.get("/api/workflows")
def api_workflows():
    settings = load_workflow_settings()
    return jsonify({"workflows": [{"id": wid, "label": label, "enabled": settings[wid]}
                                   for wid, label in WORKFLOW_DEFS]})


@app.post("/api/workflows/<wid>/toggle")
@admin_required
def api_workflow_toggle(wid):
    settings = load_workflow_settings()
    if wid not in settings:
        return jsonify({"error": "no such workflow"}), 404
    settings[wid] = not settings[wid]
    save_workflow_settings(settings)
    return jsonify({"ok": True, "enabled": settings[wid]})


@app.post("/api/workflows/<wid>/state")
@admin_required
def api_workflow_state(wid):
    """Persist an explicit workflow visibility state.

    Unlike a toggle, this is idempotent: a delayed retry or double request cannot
    accidentally reverse the administrator's intended setting.
    """
    settings = load_workflow_settings()
    if wid not in settings:
        return jsonify({"error": "no such workflow"}), 404
    body = request.get_json(silent=True) or {}
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        return jsonify({"error": "enabled must be true or false"}), 400
    settings[wid] = enabled
    save_workflow_settings(settings)
    return jsonify({"ok": True, "enabled": settings[wid]})


# Root of your loras folder (used only to LIST checkpoints; paths sent to ComfyUI
# stay relative to this, so they work identically local & cloud).
LORAS_DIR = os.environ.get("LORAS_DIR", "G:/ConfiuiModels/models/loras")
DIFFUSION_MODELS_DIR = os.environ.get(
    "DIFFUSION_MODELS_DIR", "G:/ConfiuiModels/models/diffusion_models")

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


def _comfy_unets():
    """Live diffusion-model list from the active ComfyUI instance."""
    r = requests.get(f"{LOCAL_COMFY}/object_info/UNETLoader",
                     headers=comfy_common.CF_HEADERS, timeout=8)
    r.raise_for_status()
    d = r.json()
    return d[list(d.keys())[0]]["input"]["required"]["unet_name"][0]


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
    """Krea2 character picker from the live Keara2 LoRA root.

    Each immediate Keara2 folder is one character and its files are selectable
    checkpoints.  These are the exact paths that ComfyUI reports, so a UI choice
    can be sent straight to the workflow without a stale-folder remap.
    """
    prefix = KREA2_LORA_ROOT.lower() + "/"
    groups = {}
    for item in build_krea2_helper_loras():
        path = item["path"].replace("\\", "/")
        if not path.lower().startswith(prefix):
            continue
        rest = path[len(prefix):]
        folder, _, filename = rest.partition("/")
        if not filename:  # loose file in Keara2: expose it under the root itself
            folder, filename = KREA2_LORA_ROOT, folder
        label = os.path.splitext(filename)[0]
        groups.setdefault(folder, []).append({"label": label, "path": path})
    return [{"key": _auto_char_key(folder), "label": folder,
             "variants": sorted(variants, key=lambda v: (bool(_STEP.search(v["label"])), v["label"]))}
            for folder, variants in sorted(groups.items(), key=lambda entry: entry[0].lower())]


KREA2_MODEL_DEFAULTS = {
    "krea2": "Kera2/krea2_turbo_bf16.safetensors",
    "krea2new": "Kera2/krea2_turbo_bf16.safetensors",
    "krea2hq": "Kera2/krea2_turbo_bf16.safetensors",
    "krea2t2ihq": "Kera2/krea2_turbo_bf16.safetensors",
    "krea2carousel": "Kera2/selforaV21NightFix_selfora21Int8.safetensors",
}


def build_krea2_models():
    """Models shown in the per-workflow Krea2 model picker.

    Only files inside diffusion_models/Kera2 are discovered. Live ComfyUI is the
    primary source so the VPS sees the home machine; local filesystem and cache
    are fallbacks. Workflow defaults are always included.
    """
    prefix = "kera2/"
    items = set()
    try:
        items.update(p.replace("\\", "/") for p in _comfy_unets()
                     if p.replace("\\", "/").lower().startswith(prefix))
    except Exception:
        pass
    base = os.path.join(DIFFUSION_MODELS_DIR, "Kera2")
    if os.path.isdir(base):
        for root, _, files in os.walk(base):
            for fn in files:
                if fn.lower().endswith((".safetensors", ".gguf")):
                    full = os.path.join(root, fn)
                    items.add("Kera2/" + os.path.relpath(full, base).replace("\\", "/"))
    cache = os.path.join(HERE, ".krea2_models.json")
    # Merge the last known inventory even when the live tunnel returns a partial
    # list. The VPS cannot read the Windows G: drive directly, so this cache is
    # also its durable offline inventory.
    if os.path.exists(cache):
        try:
            items.update(_json.load(open(cache, encoding="utf-8")))
        except Exception:
            pass
    if items:
        try:
            with open(cache, "w", encoding="utf-8") as f:
                _json.dump(sorted(items, key=str.lower), f)
        except Exception:
            pass
    items.update(KREA2_MODEL_DEFAULTS.values())
    return [{"path": p, "label": os.path.splitext(p.split("/")[-1])[0]}
            for p in sorted(items, key=str.lower)]


# The realism/technique "helper" LoRAs baked into the krea2hq Power Lora Loader
# (slots 2/3 of node 11). These are the on-by-default set; the UI can toggle them
# off, retune strength, or add more from build_krea2_helper_loras(). Paths are the
# forward-slash form ComfyUI accepts on the local Windows install.
KREA2HQ_DEFAULT_HELPERS = []

# krea2carousel ships a DIFFERENT baked-in helper set (slots 2-4 of node 28 in
# workflow_krea2carousel.json). It needs its own list because the UI always sends
# helper_loras, so seeding the krea2hq set while in carousel mode would silently
# replace this workflow's own LoRAs with krea2hq's. Must stay in sync with the
# workflow file, in the same forward-slash form the picker's options use.
KREA2CAROUSEL_DEFAULT_HELPERS = []


def build_krea2_helper_loras():
    """LoRAs available to Krea2 workflows from ComfyUI's live Keara2 root."""
    items = []
    prefix = KREA2_LORA_ROOT.lower() + "/"
    try:
        items = [l.replace("\\", "/") for l in _comfy_loras()
                 if (l.replace("\\", "/").lower().startswith(prefix)
                     and l.lower().endswith(".safetensors"))]
    except Exception:
        items = []
    if not items:
        base = os.path.join(LORAS_DIR, KREA2_LORA_ROOT)
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
            # Do not revive the former /Shared cache: those paths are not
            # registered in the current ComfyUI instance and would fail at run time.
            items = [p for p in _json.load(open(cache, encoding="utf-8"))
                     if (p.replace("\\", "/").lower().startswith(prefix)
                         and "/shared/" not in p.replace("\\", "/").lower())]
        except Exception:
            items = []
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
# on purpose (the full catalog includes many irrelevant and unstable choices).
# The first entry is the default. Labels describe the intended role of each model;
# provider-side moderation and free-model availability can change independently.
VISION_MODELS = [
    {"id": "qwen/qwen3.8-27b",                  "name": "Qwen 3.8 27B (default · balanced)"},
    {"id": "qwen/qwen3.8-27b:free",             "name": "Qwen 3.8 27B Free (availability varies)"},
    {"id": "x-ai/grok-4.6",                     "name": "Grok 4.6 (premium · less filtered)"},
    {"id": "z-ai/glm-5.3-flash",                "name": "GLM 5.3 Flash (inexpensive)"},
    {"id": "google/gemini-3.8-flash",           "name": "Gemini 3.8 Flash (SFW-focused)"},
    {"id": "deepseek/deepseek-v4.1-flash",      "name": "DeepSeek V4.1 Flash (inexpensive)"},
    {"id": "openai/gpt-5.6-luna",               "name": "GPT-5.6 Luna (SFW · OpenAI)"},
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
                    "krea2_models": build_krea2_models(),
                    "krea2_model_defaults": KREA2_MODEL_DEFAULTS,
                    "krea2_helpers": build_krea2_helper_loras(),
                    "krea2hq_default_helpers": KREA2HQ_DEFAULT_HELPERS,
                    "krea2carousel_default_helpers": KREA2CAROUSEL_DEFAULT_HELPERS,
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
    """Report which compute targets are available so the UI can auto-pick.
    Also reports which OS the home PC is currently booted into (dual-boot box)
    so the UI can warn when a mode's models won't be found on that OS."""
    local = False
    try:
        r = requests.get(f"{LOCAL_COMFY}/system_stats", headers=comfy_common.CF_HEADERS,
                         allow_redirects=False, timeout=6)
        local = r.status_code == 200  # 302 (Access login) / 502 (tunnel down) => not ready
    except Exception:
        pass
    agent_os = None
    if AGENT_URL:
        try:
            r = requests.get(f"{AGENT_URL}/status", headers={"x-agent-secret": AGENT_SECRET}, timeout=6)
            agent_os = r.json().get("os")
        except Exception:
            pass
    else:
        agent_os = "windows" if _IS_WINDOWS else "linux"
    agent_up = _agent_up()
    return jsonify({"local": local,
                    "cloud": bool(ENDPOINT_ID and API_KEY),
                    "agent_os": agent_os,
                    "agent_up": agent_up,
                    # UI greys out Develop while the owner's agent is off
                    "gen_open": agent_up or not GEN_REQUIRES_AGENT,
                    "gen_gated": GEN_REQUIRES_AGENT})


def _enhance_agent(method, path, **kwargs):
    if not AGENT_URL or not AGENT_SECRET:
        raise RuntimeError("Local GPU agent is not configured")
    headers = dict(kwargs.pop("headers", {}))
    headers["x-agent-secret"] = AGENT_SECRET
    return requests.request(method, f"{AGENT_URL}{path}", headers=headers,
                            timeout=kwargs.pop("timeout", 30), **kwargs)


ENHANCE_JOB_OWNERS = {}


def _enhance_owned(job_id):
    return re.fullmatch(r"[0-9a-f]{32}", job_id) and ENHANCE_JOB_OWNERS.get(job_id) == session.get("user")


@app.get("/api/enhance/capabilities")
def enhance_capabilities():
    try:
        r = _enhance_agent("GET", "/enhance/capabilities", timeout=8)
        return Response(r.content, status=r.status_code,
                        content_type=r.headers.get("Content-Type", "application/json"))
    except Exception as exc:
        return jsonify({"online": False, "error": str(exc)}), 503


@app.post("/api/enhance/jobs")
def enhance_submit():
    media = request.files.get("media") or request.files.get("video")
    if not media:
        return jsonify({"error": "Choose an image or video"}), 400
    try:
        files = {"media": (media.filename, media.stream,
                           media.mimetype or "application/octet-stream")}
        r = _enhance_agent("POST", "/enhance/jobs", files=files,
                           data={"options": request.form.get("options", "{}")}, timeout=300)
        if r.status_code in (200, 202):
            job_id = r.json().get("id")
            if job_id:
                ENHANCE_JOB_OWNERS[job_id] = session.get("user")
        return Response(r.content, status=r.status_code,
                        content_type=r.headers.get("Content-Type", "application/json"))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/enhance/jobs/<job_id>")
def enhance_job_status(job_id):
    if not _enhance_owned(job_id):
        return jsonify({"error": "Job not found"}), 404
    try:
        r = _enhance_agent("GET", f"/enhance/jobs/{job_id}", timeout=10)
        return Response(r.content, status=r.status_code,
                        content_type=r.headers.get("Content-Type", "application/json"))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.post("/api/enhance/jobs/<job_id>/cancel")
def enhance_job_cancel(job_id):
    if not _enhance_owned(job_id):
        return jsonify({"error": "Job not found"}), 404
    try:
        r = _enhance_agent("POST", f"/enhance/jobs/{job_id}/cancel", timeout=15)
        return Response(r.content, status=r.status_code,
                        content_type=r.headers.get("Content-Type", "application/json"))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/enhance/jobs/<job_id>/result")
def enhance_job_result(job_id):
    if not _enhance_owned(job_id):
        return jsonify({"error": "Job not found"}), 404
    try:
        upstream = _enhance_agent("GET", f"/enhance/jobs/{job_id}/result",
                                  timeout=300, stream=True)
        if upstream.status_code != 200:
            return Response(upstream.content, status=upstream.status_code,
                            content_type=upstream.headers.get("Content-Type", "application/json"))
        response = Response(
            upstream.iter_content(1024 * 1024),
            content_type=upstream.headers.get("Content-Type", "application/octet-stream"),
        )
        disposition = upstream.headers.get("Content-Disposition")
        response.headers["Content-Disposition"] = (
            disposition or f'inline; filename="enhanced-{job_id[:8]}"'
        )
        return response
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


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
    st = _cloud_status()
    st["agent_up"] = _agent_up()
    st["gated"] = GEN_REQUIRES_AGENT
    st["open"] = st["agent_up"] or not GEN_REQUIRES_AGENT
    return jsonify(st)


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
    script = os.path.join(COMFY_DIR, COMFY_LAUNCH)
    if not os.path.exists(script):
        return jsonify({"error": f"Launch script not found: {script}"}), 500
    try:
        if _IS_WINDOWS:
            subprocess.Popen(["cmd", "/c", "start", "", COMFY_LAUNCH], cwd=COMFY_DIR)
        else:
            log = open(os.path.join(COMFY_DIR, "comfyui_agent.log"), "ab")
            subprocess.Popen(["bash", script], cwd=COMFY_DIR, stdin=subprocess.DEVNULL,
                              stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
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
def reels_folder_create():
    try:
        name = _folder_path(request.get_json(force=True).get("name", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
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
    from urllib.parse import quote
    folder = request.args.get("folder", "")
    reels = r2_store.list_reels(folder)
    for reel in reels:
        stem, _ext = os.path.splitext(reel["key"])
        reel["thumb_url"] = f"/api/reels/media?key={quote('thumbs-reels/' + stem + '.webp', safe='')}"
    return jsonify({"reels": _enrich_media_creator(reels)})


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
        _set_media_creator(key, session.get("user"))
        try:
            with open(local, "rb") as f:
                thumb = _make_video_thumb(f.read())
            if thumb is not None:
                stem, _ext = os.path.splitext(key)
                r2_store.upload_bytes(f"thumbs-reels/{stem}.webp", thumb)
        except Exception:
            pass
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
        raw = f.read()
        r2_store.upload_bytes(key, raw)
        _set_media_creator(key, session.get("user"))
        try:
            thumb = _make_video_thumb(raw)
            if thumb is not None:
                stem, _ext = os.path.splitext(key)
                r2_store.upload_bytes(f"thumbs-reels/{stem}.webp", thumb)
        except Exception:
            pass
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    return jsonify({"ok": True, "key": key, "name": name})


_THUMB_BUILD_LOCK = threading.Lock()
_THUMB_BUILDING = set()


def _ensure_thumb(thumb_key):
    """Build a missing Gallery or Reel thumbnail from its private original.

    Returns the WebP bytes, or None when the original is gone / unreadable.
    Concurrent requests for the same key build once; the losers fall through to
    the normal not-found path and pick it up on the next load."""
    if not thumb_key.startswith(("thumbs/", "thumbs-reels/")) or not thumb_key.endswith(".webp"):
        return None
    if thumb_key.startswith("thumbs/"):
        stem = "gallery/" + thumb_key[len("thumbs/"):-len(".webp")]
    elif thumb_key.startswith("thumbs-reels/"):
        stem = thumb_key[len("thumbs-reels/"):-len(".webp")]
    else:
        return None
    with _THUMB_BUILD_LOCK:
        if thumb_key in _THUMB_BUILDING:
            return None
        _THUMB_BUILDING.add(thumb_key)
    try:
        thumb = None
        for ext in (".png", ".mp4", ".mov", ".webm"):
            src = r2_store.stream(stem + ext, None)
            if src.status_code != 200:
                continue
            thumb = _make_thumb(src.content) if ext == ".png" else _make_video_thumb(src.content)
            if thumb is not None:
                break
        if thumb is None:
            return None
        r2_store.upload_bytes(thumb_key, thumb)
        return thumb
    except Exception:
        return None
    finally:
        with _THUMB_BUILD_LOCK:
            _THUMB_BUILDING.discard(thumb_key)


@app.get("/api/reels/media")
@app.get("/api/media")
def reels_media():
    """Proxy any R2 object (reel video or gallery image) so the browser can
    preview/download it without ever seeing the Worker secret."""
    key = request.args.get("key", "")
    if not key:
        return jsonify({"error": "no key"}), 400
    up = r2_store.stream(key, request.headers.get("Range"))
    if up.status_code not in (200, 206) and key.startswith(("thumbs/", "thumbs-reels/")):
        # Self-heal: any gallery image without a thumbnail yet (everything made
        # before thumbnailing existed) gets one built on first view, then served
        # from R2 forever after. Keeps the grid fast without a bulk migration.
        made = _ensure_thumb(key)
        if made is not None:
            return Response(made, status=200, headers={
                "Content-Type": "image/webp",
                "Content-Length": str(len(made)),
                "Cache-Control": "public, max-age=31536000, immutable"})
    if up.status_code not in (200, 206):
        return ("not found", up.status_code)
    ext = key.lower().rsplit(".", 1)[-1]
    ct = ("video/mp4" if ext in ("mp4", "mov", "webm")
          else "image/png" if ext == "png"
          else "image/webp" if ext == "webp"
          else "image/jpeg")
    headers = {"Content-Type": ct, "Accept-Ranges": "bytes"}
    for h in ("Content-Range", "Content-Length"):
        if h in up.headers:
            headers[h] = up.headers[h]
    # Gallery/thumb keys embed a timestamp+seed and are never overwritten in
    # place, so they're safe to cache "forever" — repeat gallery visits then
    # cost zero network requests instead of re-streaming through the R2 proxy.
    if key.startswith(("gallery/", "thumbs/", "thumbs-reels/")):
        headers["Cache-Control"] = "public, max-age=31536000, immutable"
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
        _delete_media_metadata(key)
    return jsonify({"ok": True})


def _folder_name(value):
    """A single safe user-facing folder segment (the empty string is root)."""
    value = (value or "").strip()
    if not value:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}", value):
        raise ValueError("Folder names may use letters, numbers, spaces, dots, dashes, and underscores.")
    return value


def _folder_path(value):
    """A safe nested folder path; each segment follows _folder_name rules."""
    value = (value or "").strip().strip("/")
    if not value:
        return ""
    parts = value.split("/")
    if any(not _folder_name(part) for part in parts):
        raise ValueError("Folder path contains an invalid segment.")
    return "/".join(parts)


def _move_library_media(key, folder, library, thumbs_prefix):
    """Move one library object and its optional preview sidecar together."""
    folder = _folder_path(folder)
    if not key.startswith(library):
        raise ValueError("That item does not belong to this library.")
    relative = key[len(library):]
    if not relative or "/" in relative.rsplit("/", 1)[-1]:
        raise ValueError("Invalid media key.")
    filename = relative.rsplit("/", 1)[-1]
    destination = library + (folder + "/" if folder else "") + filename
    if key == destination:
        return destination
    r2_store.move(key, destination)
    _move_media_metadata(key, destination)
    source_stem, _ = os.path.splitext(relative)
    destination_stem, _ = os.path.splitext(destination[len(library):])
    source_thumb = thumbs_prefix + source_stem + ".webp"
    destination_thumb = thumbs_prefix + destination_stem + ".webp"
    if r2_store.exists(source_thumb):
        try:
            r2_store.move(source_thumb, destination_thumb)
        except Exception:
            # A missing preview is self-healed on next library view; the media
            # move itself must not be rolled back after it has safely completed.
            pass
    return destination


@app.post("/api/reels/move")
def reels_move():
    body = request.get_json(force=True)
    try:
        source = body.get("key", "")
        if source.startswith(("gallery/", "thumbs/", "thumbs-reels/")):
            raise ValueError("That item does not belong to the Reel library.")
        key = _move_library_media(source, body.get("folder", ""), "", "thumbs-reels/")
        return jsonify({"ok": True, "key": key})
    except (ValueError, FileExistsError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/reels/bulk-move")
def reels_bulk_move():
    body = request.get_json(force=True)
    keys = body.get("keys", [])
    if not isinstance(keys, list) or not keys:
        return jsonify({"error": "Select one or more Reels."}), 400
    try:
        folder = _folder_path(body.get("folder", ""))
        moved = [_move_library_media(key, folder, "", "thumbs-reels/") for key in keys]
        return jsonify({"ok": True, "keys": moved})
    except (ValueError, FileExistsError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    krea_modes = {"krea2", "krea2new", "krea2hq", "krea2t2ihq", "krea2carousel"}
    if inp["mode"] in krea_modes:
        model_name = str(body.get("model_name", "")).replace("\\", "/").strip()
        if model_name:
            if (not model_name.lower().startswith("kera2/") or ".." in model_name
                    or not model_name.lower().endswith((".safetensors", ".gguf"))):
                raise ValueError("Invalid Krea2 model selection.")
            inp["model_name"] = model_name
        if "helper_loras" in body:
            inp["helper_loras"] = [
                {"path": l.get("path", ""), "strength": float(l.get("strength", 0.6))}
                for l in body.get("helper_loras", [])
                if str(l.get("path", "")).replace("\\", "/").lower().startswith("keara2/")
            ]
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
    elif inp["mode"] in ("krea2t2ihq", "krea2carousel"):
        # Pure t2i — no required image. An optional "describe from image" photo may
        # be attached directly as base64 (single-image uploader, not the frame-picker
        # session/frame flow) — it's used ONLY to auto-generate the prompt via
        # OpenRouter when the prompt is left blank, never sent to ComfyUI at all.
        if body.get("image_b64"):
            inp["image_b64"] = body["image_b64"]
    elif inp["mode"] == "video":   # Wan Animate: driving video + ref photo
        inp["video_b64"] = body.get("video_b64", "")
        inp["video_filename"] = body.get("video_filename", "driving.mp4")
        inp["ref_b64"] = body.get("ref_b64", "")
        inp["frame_cap"] = int(body.get("frame_cap", 81))
        inp["fps"] = int(body.get("fps", 30))
        inp["upscale"] = bool(body.get("upscale", False))   # RTX super-res + RIFE tail
    elif inp["mode"] == "ltx25i2v":   # LTX 2.5 image-to-video: first-frame photo + prompt -> mp4
        inp["image_b64"] = body.get("image_b64", "")
        inp["duration"] = int(body.get("duration", 10))
    elif inp["mode"] in ("scail2motion", "scail2motionv2", "scail2motiondirecttest"):   # SCAIL-2: same shape as "video"
        inp["video_b64"] = body.get("video_b64", "")
        inp["video_filename"] = body.get("video_filename", "driving.mp4")
        inp["ref_b64"] = body.get("ref_b64", "")
        inp["frame_cap"] = int(body.get("frame_cap", 81))
        inp["fps"] = int(body.get("fps", 30))
        inp["upscale"] = bool(body.get("upscale", False))   # 2x RTX super-res + RIFE tail
        if inp["mode"] == "scail2motionv2":
            inp["generation_resolution"] = body.get("generation_resolution", "720p")
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


def describe_images(images_b64, params, model=None, instruction=None, mime_type="image/jpeg"):
    if not OPENROUTER_API_KEY:
        raise ValueError("OpenRouter API Key not set.")
    
    model = model or OPENROUTER_MODEL
    instruction = instruction or _describe_instruction(params)
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    
    content = [{"type": "text", "text": instruction}]
    content.extend({"type": "image_url", "image_url": {
        "url": f"data:{mime_type};base64,{image_b64}"}}
        for image_b64 in images_b64)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": content
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


def describe_image(image_b64, params, model=None, instruction=None, mime_type="image/jpeg"):
    return describe_images([image_b64], params, model, instruction, mime_type)


def _face_describe_instruction(note=""):
    instruction = ("Describe only this adult person's visible face identity in one concise "
                   "image-generation paragraph: face shape, skin tone and texture, eye color "
                   "and shape, eyebrows, hair color and style, makeup, lips, and expression. "
                   "Do not describe body, clothing, pose, background, age, ethnicity, or any "
                   "text. Output only the description with no heading or bullet points.")
    if note:
        instruction += f" Follow this additional face direction: {note}"
    return instruction


CHARACTER_SOURCE_OPTIONS = {
    "pose": "pose and body position",
    "expression": "facial expression and body language",
    "outfit": "outfit and accessories",
    "background": "background, setting, and composition",
    "lighting": "lighting, camera angle, lens feel, and photographic style",
    "hair_makeup": "hair styling and makeup only",
}


def _character_locked_describe_instruction(profile, borrow, note=""):
    allowed = [CHARACTER_SOURCE_OPTIONS[key] for key in borrow if key in CHARACTER_SOURCE_OPTIONS]
    borrowed = ", ".join(allowed) if allowed else "no visual attributes"
    instruction = (
        "Write one flowing image-generation prompt. The following selected character profile is "
        "the sole authority for the subject's identity and must be stated naturally at the start "
        f"of the prompt: {profile}. Inspect the source image only to borrow these explicitly "
        f"enabled attributes: {borrowed}. Do not copy, infer, or describe the source person's "
        "face, facial features, identity, age, ethnicity, body identity, skin tone, or hair and "
        "makeup unless hair and makeup is one of the enabled attributes. Do not replace or "
        "contradict the selected character profile. Keep the selected character as the sole person "
        "in the scene. Output only the final prompt with no heading, labels, explanation, or bullets.")
    if note:
        instruction += f" Additional direction: {note}"
    return instruction


def _character_profile_instruction():
    return ("Describe only this adult character's persistent visual identity in one short, "
            "editable image-generation profile: face shape, skin appearance, eye color, hair "
            "color and style, makeup, lips, and signature accessories. Do not describe pose, "
            "clothing, background, lighting, age, ethnicity, or body. Output only the profile, "
            "with no title, heading, or bullets.")


def _parse_h3_talking_duration(value):
    if value is None or str(value).strip() == "":
        raise ValueError("Duration is required.")
    raw = str(value).strip()
    if not re.fullmatch(r"\d+", raw):
        raise ValueError("Duration must be a whole number of seconds.")
    duration = int(raw)
    if not 5 <= duration <= 15:
        raise ValueError("Duration must be from 5 to 15 seconds.")
    return duration


def _h3_talking_instruction(description, script, audio_direction, music, duration):
    return f"""Create one production-ready MiniMax H3 I2VA prompt from the supplied source image and directions.

The target video lasts exactly {duration} seconds. Treat the uploaded image as the actual first frame. Preserve the visible person's identity, face, clothing, composition, objects, lighting, and spatial relationships unless the custom description explicitly requests a change. Prefer one continuous, stable portrait talking shot unless the custom description requests a cut. Fit every action, gesture, delivery beat, and any requested cut inside {duration} seconds.

Use this exact first line:
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

After a blank line, output exactly these three sections in this order:
integrated_multimodal_description: [Shot 1] ...
overall_soundscape: ...
non_diegetic_music: ...

Use the stable speaker ID (S1). Put the dialogue exactly once inside <d>[Language] ...</d>, replacing Language with the spoken language. The spoken script between the language tag and </d> must match the SCRIPT block character-for-character, including punctuation, capitalization, language, and line breaks. Never shorten, paraphrase, translate, correct, or invent dialogue. Put ambient and non-verbal sounds in overall_soundscape without repeating dialogue. Put only audience-facing music in non_diegetic_music; write N/A when no music is requested. Return only the final prompt with no Markdown fence or commentary.

CUSTOM DESCRIPTION:
{description or 'No additional visual direction.'}

SCRIPT — COPY VERBATIM:
{script}

AUDIO DIRECTION:
{audio_direction or 'Natural voice and clean production sound.'}

BACKGROUND MUSIC:
{music or 'N/A'}"""


def _valid_h3_talking_prompt(prompt, script):
    first_line = (prompt.splitlines() or [""])[0]
    expected = ("For the target video, at 0.00 seconds into the target video, "
                "<Picture 1> (from [Shot 1]) is fully referenced.")
    if first_line != expected:
        return False
    section_positions = [prompt.find(name) for name in (
        "integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:")]
    if any(position < 0 for position in section_positions) or section_positions != sorted(section_positions):
        return False
    dialogue = re.compile(r"<d>\[[^\]\r\n]+\]\s*" + re.escape(script) + r"</d>", re.DOTALL)
    return dialogue.search(prompt) is not None


@app.post("/api/runninghub/h3-talking/prompt")
@cloud_workflow_required("h3_talking")
def runninghub_build_h3_talking_prompt():
    image = request.files.get("image")
    if not image or not image.filename:
        return jsonify({"error": "A source image is required."}), 400
    if (image.mimetype or "").lower() not in {"image/png", "image/jpeg", "image/webp"}:
        return jsonify({"error": "Choose a PNG, JPG, or WEBP source image."}), 400
    model = (request.form.get("model") or RUNNINGHUB_H3_TALKING_DEFAULT_MODEL).strip()
    if model not in RUNNINGHUB_H3_TALKING_MODELS:
        return jsonify({"error": "Choose a supported AI model."}), 400
    try:
        duration = _parse_h3_talking_duration(request.form.get("duration"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    script = request.form.get("script") or ""
    if not script.strip():
        return jsonify({"error": "Enter the spoken script."}), 400
    source_bytes = image.read()
    if len(source_bytes) > RUNNINGHUB_MAX_IMAGE_BYTES:
        return jsonify({"error": "Source image exceeds the Cloud upload limit."}), 413
    description = (request.form.get("description") or "").strip()[:4000]
    audio_direction = (request.form.get("audio_direction") or "").strip()[:3000]
    music = (request.form.get("music") or "").strip()[:2000]
    instruction = _h3_talking_instruction(
        description, script, audio_direction, music, duration)
    try:
        prompt = describe_image(
            base64.b64encode(source_bytes).decode(), {}, model, instruction,
            mime_type=image.mimetype.lower())
    except Exception as exc:
        return jsonify({"error": f"H3 prompt generation failed: {exc}"}), 502
    if not _valid_h3_talking_prompt(prompt, script):
        return jsonify({"error": "The AI did not return a valid H3 prompt with the exact script. Try again."}), 502
    return jsonify({"prompt": prompt})


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
        source = request.files["image"]
        if not (source.mimetype or "").lower() in {"image/png", "image/jpeg", "image/webp"}:
            return jsonify({"error": "Choose a PNG, JPG, or WEBP source image."}), 400
        source_bytes = source.read()
        if len(source_bytes) > RUNNINGHUB_MAX_IMAGE_BYTES:
            return jsonify({"error": "Source image exceeds the Cloud upload limit."}), 413
        image_b64 = base64.b64encode(source_bytes).decode()
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
        character_locked = request.form.get("character_locked") == "true" if request.files else False
        if character_locked:
            character = _resolve_runninghub_lora(request.form.get("character_id", ""),
                                                 request.form.get("version_id", ""))
            if not character:
                return jsonify({"error": "Choose an available Cloud character and version first."}), 400
            profile = character.get("identity_profile", "").strip()
            if not profile:
                return jsonify({"error": "This character version has no identity profile yet. Ask an administrator to save one."}), 400
            borrow = [item.strip() for item in request.form.getlist("borrow")]
            prompt = describe_image(image_b64, p, p["model"],
                                    _character_locked_describe_instruction(
                                        profile, borrow,
                                        (request.form.get("custom_instruction") or "").strip()[:1200]))
            return jsonify({"prompt": prompt})

        prompt = describe_image(image_b64, p, p["model"])
        face = request.files.get("face_image") if request.files else None
        if face and face.filename:
            if not (face.mimetype or "").lower() in {"image/png", "image/jpeg", "image/webp"}:
                return jsonify({"error": "Choose a PNG, JPG, or WEBP face image."}), 400
            face_bytes = face.read()
            if len(face_bytes) > RUNNINGHUB_MAX_IMAGE_BYTES:
                return jsonify({"error": "Face image exceeds the Cloud upload limit."}), 413
            face_note = (request.form.get("face_note") or "").strip()[:800]
            face_prompt = describe_image(base64.b64encode(face_bytes).decode(), p, p["model"],
                                         _face_describe_instruction(face_note))
            prompt = f"{prompt}\n\nFace identity: {face_prompt}"
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
        # krea2t2ihq/krea2carousel: same auto-describe, but the image is optional
        # (pure t2i) — only fires if the user actually attached a description photo.
        elif (inp["mode"] in ("krea2t2ihq", "krea2carousel")
              and not inp.get("prompt") and inp.get("image_b64")):
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
        if inp["mode"] in ("video", "ltx25i2v", "scail2motion", "scail2motionv2", "scail2motiondirecttest"):  # -> mp4(s)
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
                    _set_media_creator(key, inp.get("creator"))
                    try:
                        thumb = _make_video_thumb(raw)
                        if thumb is not None:
                            r2_store.upload_bytes(f"thumbs/{group}/{ts}_{seed}_{i}.webp", thumb)
                    except Exception:
                        pass
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

    # Generation uses the owner's GPU, so it only runs while the home agent is
    # up — that's the owner's switch for granting access. Applies to every
    # target: all modes are local-only, so gating Cloud alone would gate nothing.
    if GEN_REQUIRES_AGENT and not _agent_up(force=True):
        return jsonify({"error": "Generation is off right now — the studio host "
                                 "has to start the session first."}), 503

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
    elif mode in ("krea2t2ihq", "krea2carousel"):
        if target != "local":
            label = ("Krea2 Text to Image High Quality" if mode == "krea2t2ihq"
                     else "Krea2 Carousel Maker")
            return jsonify({"error": f"{label} mode runs on Local only."}), 400
        if not body.get("prompt", "").strip() and not body.get("image_b64"):
            return jsonify({"error": "Type a prompt or attach an image to describe."}), 400
    elif mode in ("video", "scail2motion", "scail2motionv2", "scail2motiondirecttest"):
        if target != "local":   # heavy Wan2.2 Animate / SCAIL-2 pipeline runs on the home GPU only
            label = {"video": "Motion", "scail2motion": "High Quality Motion Control Scail 2",
                     "scail2motionv2": "High Quality Motion Control Scail 2 V2.0",
                     "scail2motiondirecttest": "High Quality Motion Control Scail 2 Direct Resolution Test"}[mode]
            return jsonify({"error": f"{label} mode runs on Local only."}), 400
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
    inp["creator"] = session.get("user")
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


# Shared libraries remain visible to all users, but this registry records the
# creator of new media so either library can offer a reliable "My creations"
# organizer without changing immutable R2 object paths.
MEDIA_METADATA_FILE = os.path.join(HERE, "media_metadata.json")
MEDIA_METADATA_LOCK = threading.Lock()


def _load_media_metadata():
    try:
        with open(MEDIA_METADATA_FILE, encoding="utf-8") as f:
            data = _json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_media_metadata(data):
    tmp = MEDIA_METADATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, MEDIA_METADATA_FILE)


def _set_media_creator(key, creator):
    if not key or not creator:
        return
    with MEDIA_METADATA_LOCK:
        data = _load_media_metadata()
        data[key] = {"creator": creator}
        _save_media_metadata(data)


def _move_media_metadata(source, destination):
    with MEDIA_METADATA_LOCK:
        data = _load_media_metadata()
        record = data.pop(source, None)
        if record:
            data[destination] = record
            _save_media_metadata(data)


def _delete_media_metadata(key):
    with MEDIA_METADATA_LOCK:
        data = _load_media_metadata()
        if key in data:
            del data[key]
            _save_media_metadata(data)


def _enrich_media_creator(items):
    data = _load_media_metadata()
    for item in items:
        item["creator"] = data.get(item.get("key", ""), {}).get("creator", "Unknown / legacy")
    return items


def _make_thumb(png_bytes, max_dim=480, quality=72):
    """Small WebP preview of a generated image, for fast gallery-grid loads."""
    from io import BytesIO
    from PIL import Image
    img = Image.open(BytesIO(png_bytes))
    img.thumbnail((max_dim, max_dim), Image.LANCZOS)
    buf = BytesIO()
    img.convert("RGB").save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


def _make_video_thumb(video_bytes, max_width=480, quality=72):
    """Extract one small WebP preview without exposing the private source video."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "source.mp4")
        dst = os.path.join(td, "thumb.webp")
        with open(src, "wb") as f:
            f.write(video_bytes)
        result = subprocess.run([
            "ffmpeg", "-y", "-ss", "0.25", "-i", src, "-frames:v", "1",
            "-vf", f"scale={max_width}:-2", "-c:v", "libwebp", "-q:v", str(quality), dst,
        ], capture_output=True, timeout=45)
        if result.returncode != 0 or not os.path.exists(dst):
            return None
        with open(dst, "rb") as f:
            return f.read()


def _save_to_gallery(inp, images, seed):
    """Persist each generated image to R2. Returns the list of R2 keys written,
    so the result can be served as lightweight URLs instead of base64 blobs.

    Also writes a small WebP thumbnail alongside each full-res PNG (under a
    parallel thumbs/ prefix) so the gallery grid can load previews instead of
    the multi-MB originals; see gallery_list()."""
    if not images:
        return []
    group = _gallery_group(inp)
    ts = int(time.time())
    keys = []
    for i, b64 in enumerate(images):
        raw = base64.b64decode(b64)
        key = f"gallery/{group}/{ts}_{seed}_{i}.png"
        try:
            r2_store.upload_bytes(key, raw)
            _set_media_creator(key, inp.get("creator"))
            keys.append(key)
        except Exception:
            continue
        try:
            thumb = _make_thumb(raw)
            r2_store.upload_bytes(f"thumbs/{group}/{ts}_{seed}_{i}.webp", thumb)
        except Exception:
            pass  # non-fatal; grid just falls back to the full image
    return keys


# ----------------------------- RunningHub Cloud -------------------------------
# Cloud jobs persist on the Studio server. They never travel through the Home
# Agent, so a job continues while the user's PC is off.
RUNNINGHUB_JOBS_FILE = os.path.join(HERE, "runninghub_jobs.json")
RUNNINGHUB_UPLOAD_DIR = os.path.join(HERE, "runninghub_uploads")
RUNNINGHUB_LORAS_FILE = os.path.join(HERE, "runninghub_loras.json")
RUNNINGHUB_KREA2_HELPERS_FILE = os.path.join(HERE, "runninghub_krea2_helpers.json")
RUNNINGHUB_JOBS_LOCK = threading.Lock()
RUNNINGHUB_LORAS_LOCK = threading.Lock()
RUNNINGHUB_KREA2_HELPERS_LOCK = threading.Lock()
RUNNINGHUB_ACTIVE_STATUSES = {"waiting", "uploading", "submitting", "queued", "running", "importing", "cancelling"}
RUNNINGHUB_TERMINAL_STATUSES = {"done", "failed", "cancelled"}
os.makedirs(RUNNINGHUB_UPLOAD_DIR, exist_ok=True)


def _default_runninghub_loras():
    return [{"id": "sophie-joy-talking", "name": "SophieJoyTalking", "enabled": True,
             "preview_url": "", "versions": [
                 {"id": "v1", "label": "V1.0", "filename": "Sophie-step00003000.safetensors",
                  "enabled": True, "default": True, "preview_url": ""}
             ]}]


def _load_runninghub_loras():
    try:
        data = _json.load(open(RUNNINGHUB_LORAS_FILE, encoding="utf-8"))
        return data if isinstance(data, list) else _default_runninghub_loras()
    except (OSError, ValueError, TypeError):
        return _default_runninghub_loras()


def _save_runninghub_loras(data):
    tmp = RUNNINGHUB_LORAS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=2)
    os.replace(tmp, RUNNINGHUB_LORAS_FILE)


def _normalize_runninghub_krea2_helpers(raw):
    if not isinstance(raw, list):
        raise ValueError("Helpers must be a list.")
    clean, seen = [], set()
    for item in raw:
        filename = str((item or {}).get("filename") or "").strip().replace("\\", "/")
        if filename.lower().startswith("models/loras/"):
            filename = filename[len("models/loras/"):]
        if (not filename or "/" in filename or not filename.lower().endswith(".safetensors")
                or filename.lower() in seen):
            raise ValueError("Each helper needs a unique .safetensors filename.")
        try:
            strength = float((item or {}).get("strength", 0.60))
        except (TypeError, ValueError):
            raise ValueError(f"{filename} needs a numeric strength.")
        if not math.isfinite(strength) or not 0 <= strength <= 2:
            raise ValueError(f"{filename} strength must be from 0 to 2.")
        seen.add(filename.lower())
        clean.append({"filename": filename, "enabled": bool((item or {}).get("enabled", True)),
                      "strength": round(strength, 2)})
    return clean


def _load_runninghub_krea2_helpers():
    try:
        raw = _json.load(open(RUNNINGHUB_KREA2_HELPERS_FILE, encoding="utf-8"))
        return _normalize_runninghub_krea2_helpers(raw)
    except (OSError, ValueError, TypeError):
        return [dict(item) for item in RUNNINGHUB_KREA2_DEFAULT_HELPERS]


def _save_runninghub_krea2_helpers(data):
    tmp = RUNNINGHUB_KREA2_HELPERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=2)
    os.replace(tmp, RUNNINGHUB_KREA2_HELPERS_FILE)


def _load_runninghub_krea2_t2i_helpers():
    try:
        return _normalize_runninghub_krea2_helpers(_json.load(open(RUNNINGHUB_KREA2_T2I_HELPERS_FILE, encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return []


def _save_runninghub_krea2_t2i_helpers(data):
    tmp = RUNNINGHUB_KREA2_T2I_HELPERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=2)
    os.replace(tmp, RUNNINGHUB_KREA2_T2I_HELPERS_FILE)


def _normalize_runninghub_loras(raw):
    if not isinstance(raw, list):
        raise ValueError("Characters must be a list.")
    clean, seen_chars = [], set()
    for char in raw:
        name = str((char or {}).get("name") or "").strip()
        char_id = str((char or {}).get("id") or uuid.uuid4().hex).strip()
        if not name or not char_id or char_id in seen_chars:
            raise ValueError("Every character needs a unique ID and display name.")
        seen_chars.add(char_id)
        versions, seen_versions, default_seen = [], set(), False
        for version in (char or {}).get("versions") or []:
            label = str((version or {}).get("label") or "").strip()
            version_id = str((version or {}).get("id") or uuid.uuid4().hex).strip()
            filename = str((version or {}).get("filename") or "").strip().replace("\\", "/")
            if filename.lower().startswith("models/loras/"):
                filename = filename[len("models/loras/"):]
            if not label or not version_id or version_id in seen_versions or not filename.lower().endswith(".safetensors"):
                raise ValueError(f"Every {name} version needs a unique ID, label, and .safetensors filename.")
            seen_versions.add(version_id)
            is_default = bool((version or {}).get("default")) and not default_seen
            default_seen = default_seen or is_default
            identity_profile = str((version or {}).get("identity_profile") or "").strip()
            trigger_words = str((version or {}).get("trigger_words") or "").strip()
            if len(identity_profile) > 2000:
                raise ValueError(f"The identity profile for {name} / {label} is too long.")
            if len(trigger_words) > 800:
                raise ValueError(f"The trigger words for {name} / {label} are too long.")
            versions.append({"id": version_id, "label": label, "filename": filename,
                             "enabled": bool((version or {}).get("enabled", True)), "default": is_default,
                             "preview_url": str((version or {}).get("preview_url") or "").strip(),
                             "identity_profile": identity_profile, "trigger_words": trigger_words})
        if not versions:
            raise ValueError(f"{name} needs at least one version.")
        if not default_seen:
            versions[0]["default"] = True
        clean.append({"id": char_id, "name": name, "enabled": bool((char or {}).get("enabled", True)),
                      "preview_url": str((char or {}).get("preview_url") or "").strip(), "versions": versions})
    return clean


def _resolve_runninghub_lora(character_id, version_id):
    with RUNNINGHUB_LORAS_LOCK:
        data = _load_runninghub_loras()
    character = next((c for c in data if c.get("id") == character_id and c.get("enabled")), None)
    if not character:
        return None
    version = next((v for v in character.get("versions", [])
                    if v.get("id") == version_id and v.get("enabled")), None)
    if not version:
        return None
    return {"character_id": character_id, "character_name": character["name"],
            "version_id": version_id, "version_label": version["label"], "filename": version["filename"],
            "identity_profile": version.get("identity_profile", ""), "trigger_words": version.get("trigger_words", "")}


def _load_runninghub_jobs():
    try:
        data = _json.load(open(RUNNINGHUB_JOBS_FILE, encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


RUNNINGHUB_JOBS = _load_runninghub_jobs()
RUNNINGHUB_USAGE_BACKFILL_LOCK = threading.Lock()
RUNNINGHUB_USAGE_BACKFILL_ACTIVE = set()


def _save_runninghub_jobs():
    tmp = RUNNINGHUB_JOBS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(RUNNINGHUB_JOBS, f, indent=2)
    os.replace(tmp, RUNNINGHUB_JOBS_FILE)


def _runninghub_update(job_id, **changes):
    with RUNNINGHUB_JOBS_LOCK:
        job = RUNNINGHUB_JOBS.get(job_id)
        if not job:
            return None
        job.update(changes)
        job["updated_at"] = int(time.time())
        _save_runninghub_jobs()
        return dict(job)


def _runninghub_user_settings(username):
    rec = load_users().get(username, {})
    private_key = _decrypt_runninghub_key(rec.get("runninghub_key_enc", ""))
    global_settings = _runninghub_global_settings()
    key = private_key or global_settings["key"]
    return {
        "configured": bool(key),
        "plus_allowed": bool(rec.get("runninghub_plus")),
        "source": "private" if private_key else "global" if key else "none",
        "concurrency": max(1, int(rec.get("runninghub_concurrency", 1 if private_key else global_settings["concurrency"]) or 1)),
        "key_enc": _encrypt_runninghub_key(key) if key else "",
        "key_fingerprint": hashlib.sha256(key.encode("utf-8")).hexdigest() if key else "",
    }


def _runninghub_workflow_key(job):
    return job.get("workflow_key") or "scail"


def _runninghub_has_active_locked(username, workflow_key, exclude_id=None):
    return any(
        job_id != exclude_id and job.get("user") == username
        and _runninghub_workflow_key(job) == workflow_key
        and job.get("status") in RUNNINGHUB_ACTIVE_STATUSES
        for job_id, job in RUNNINGHUB_JOBS.items()
    )


def _runninghub_is_cancelled(job_id):
    with RUNNINGHUB_JOBS_LOCK:
        return (RUNNINGHUB_JOBS.get(job_id) or {}).get("status") in {"cancelling", "cancelled"}


def _runninghub_dispatch():
    """Start the oldest waiting jobs while each credential has free capacity."""
    start = []
    active_states = RUNNINGHUB_ACTIVE_STATUSES - {"waiting"}
    with RUNNINGHUB_JOBS_LOCK:
        jobs = list(RUNNINGHUB_JOBS.values())
        active = {}
        limits = {}
        for job in jobs:
            if job.get("status") in active_states | {"waiting"}:
                fp = job.get("key_fingerprint", "")
                value = max(1, int(job.get("key_concurrency", 1) or 1))
                limits[fp] = min(limits.get(fp, value), value)
            if job.get("status") in active_states:
                fp = job.get("key_fingerprint", "")
                active[fp] = active.get(fp, 0) + 1
        for job in sorted(jobs, key=lambda item: item.get("created_at", 0)):
            if job.get("status") != "waiting":
                continue
            fp = job.get("key_fingerprint", "")
            limit = limits.get(fp, 1)
            if active.get(fp, 0) >= limit:
                continue
            job["status"] = "uploading"
            job["message"] = "Preparing cloud upload…"
            job["updated_at"] = int(time.time())
            active[fp] = active.get(fp, 0) + 1
            start.append(job["id"])
        if start:
            _save_runninghub_jobs()
    for job_id in start:
        threading.Thread(target=_runninghub_run, args=(job_id,), daemon=True).start()


def _runninghub_upload(api_key, path, mime_type):
    name = secure_filename(os.path.basename(path)) or "upload.bin"
    with open(path, "rb") as f:
        response = requests.post(
            f"{RUNNINGHUB_BASE_URL}/media/upload/binary",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (name, f, mime_type)}, timeout=900)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok or data.get("code") not in (0, "0", None):
        raise RuntimeError(data.get("message") or data.get("msg") or
                           f"RunningHub upload failed ({response.status_code}).")
    file_name = (data.get("data") or {}).get("fileName")
    if not file_name:
        raise RuntimeError("RunningHub upload did not return a file name.")
    return file_name


def _runninghub_submit(api_key, image_name, video_name, instance_type, clip):
    """Submit Scail 2 with the published VHS_LoadVideo controls on node 113."""
    payload = {
        "addMetadata": True,
        "nodeInfoList": [
            {"nodeId": RUNNINGHUB_REFERENCE_NODE_ID, "fieldName": RUNNINGHUB_REFERENCE_FIELD,
             "fieldValue": image_name},
            {"nodeId": RUNNINGHUB_VIDEO_NODE_ID, "fieldName": RUNNINGHUB_VIDEO_FIELD,
             "fieldValue": video_name},
            {"nodeId": RUNNINGHUB_VIDEO_NODE_ID, "fieldName": "force_rate",
             "fieldValue": str(RUNNINGHUB_VIDEO_FPS)},
            {"nodeId": RUNNINGHUB_VIDEO_NODE_ID, "fieldName": "skip_first_frames",
             "fieldValue": str(clip["skip_first_frames"])},
            {"nodeId": RUNNINGHUB_VIDEO_NODE_ID, "fieldName": "frame_load_cap",
             "fieldValue": str(clip["frame_load_cap"])},
            {"nodeId": RUNNINGHUB_VIDEO_NODE_ID, "fieldName": "select_every_nth",
             "fieldValue": str(clip["select_every_nth"])},
        ],
        "instanceType": instance_type,
        "usePersonalQueue": False,
    }
    response = requests.post(
        f"{RUNNINGHUB_BASE_URL}/run/workflow/{RUNNINGHUB_WORKFLOW_ID}",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload, timeout=90)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok or not data.get("taskId"):
        raise RuntimeError(data.get("errorMessage") or data.get("message") or
                           f"RunningHub did not accept the task ({response.status_code}).")
    return data


def _runninghub_submit_h3(api_key, job, uploads):
    """Submit the published H3 Ref2V workflow using its confirmed connected nodes."""
    refs = job["h3_refs"]
    nodes = []
    for index, node_id in enumerate(RUNNINGHUB_H3_IMAGE_NODES):
        nodes.append({"nodeId": node_id, "fieldName": "image",
                      "fieldValue": uploads["image"][index] if index < len(uploads["image"]) else "None"})
    nodes.append({"nodeId": RUNNINGHUB_H3_VIDEO_NODE, "fieldName": "video",
                  "fieldValue": uploads["video"][0] if uploads["video"] else ""})
    for index, node_id in enumerate(RUNNINGHUB_H3_AUDIO_NODES):
        nodes.append({"nodeId": node_id, "fieldName": "audio",
                      "fieldValue": uploads["audio"][index] if index < len(uploads["audio"]) else "None"})
    aspect_map = {
        "9:16": "9:16 (Portrait Widescreen)", "16:9": "16:9 (Landscape Widescreen)",
        "1:1": "1:1 (Square)", "4:3": "4:3 (Landscape)", "3:4": "3:4 (Portrait)",
    }
    nodes.extend([
        {"nodeId": RUNNINGHUB_H3_PROMPT_NODE, "fieldName": "text", "fieldValue": job["h3_prompt"]},
        {"nodeId": RUNNINGHUB_H3_ASPECT_NODE, "fieldName": "aspect_ratio",
         "fieldValue": aspect_map.get(job["h3_aspect"], aspect_map["9:16"])},
        {"nodeId": RUNNINGHUB_H3_DURATION_NODE, "fieldName": "value", "fieldValue": str(job["h3_duration"])}
    ])
    response = requests.post(
        f"{RUNNINGHUB_BASE_URL}/run/workflow/{RUNNINGHUB_H3_WORKFLOW_ID}",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"addMetadata": True, "nodeInfoList": nodes, "instanceType": RUNNINGHUB_H3_INSTANCE,
              "usePersonalQueue": False}, timeout=90)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok or not data.get("taskId"):
        raise RuntimeError(data.get("errorMessage") or data.get("message") or
                           f"RunningHub did not accept the H3 task ({response.status_code}).")
    return data


def _runninghub_submit_h3_talking(api_key, job, image_name):
    """Submit the fixed portrait talking workflow with only its three user inputs."""
    nodes = [
        {"nodeId": RUNNINGHUB_H3_TALKING_IMAGE_NODE, "fieldName": "image", "fieldValue": image_name},
        {"nodeId": RUNNINGHUB_H3_TALKING_PROMPT_NODE, "fieldName": "value",
         "fieldValue": job["talking_prompt"]},
        {"nodeId": RUNNINGHUB_H3_TALKING_DURATION_NODE, "fieldName": "value",
         "fieldValue": str(job["talking_duration"])},
    ]
    response = requests.post(
        f"{RUNNINGHUB_BASE_URL}/run/workflow/{RUNNINGHUB_H3_TALKING_WORKFLOW_ID}",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"addMetadata": True, "nodeInfoList": nodes,
              "instanceType": RUNNINGHUB_H3_TALKING_INSTANCE, "usePersonalQueue": False},
        timeout=90)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok or not data.get("taskId"):
        raise RuntimeError(data.get("errorMessage") or data.get("message") or
                           f"RunningHub did not accept the H3 Talking task ({response.status_code}).")
    return data


def _runninghub_submit_krea2(api_key, job, image_name):
    loras = [{"name": job["krea_lora_filename"], "on": True, "sm": 1, "sc": 1, "triggers": []}]
    helpers = job.get("krea_helpers")
    # Preserve a queued job from the previous one-switch release if one exists.
    if helpers is None and job.get("krea_realism_helpers", True):
        helpers = [dict(item) for item in RUNNINGHUB_KREA2_DEFAULT_HELPERS]
    for helper in helpers or []:
        loras.append({"name": helper["filename"], "on": True,
                      "sm": helper["strength"], "sc": helper["strength"], "triggers": []})
    lora_state = _json.dumps({"version": 1, "sep": ", ", "cacheMode": "last", "loras": loras},
                             separators=(",", ":"))
    nodes = [
        {"nodeId": RUNNINGHUB_KREA2_IMAGE_NODE, "fieldName": "image", "fieldValue": image_name},
        {"nodeId": RUNNINGHUB_KREA2_PROMPT_NODE, "fieldName": "text", "fieldValue": job["krea_prompt"]},
        {"nodeId": RUNNINGHUB_KREA2_RESIZE_NODE, "fieldName": "width", "fieldValue": str(job["krea_width"])},
        {"nodeId": RUNNINGHUB_KREA2_RESIZE_NODE, "fieldName": "height", "fieldValue": str(job["krea_height"])},
        {"nodeId": RUNNINGHUB_KREA2_LORA_NODE, "fieldName": "lora_name",
         "fieldValue": job["krea_lora_filename"]},
        {"nodeId": RUNNINGHUB_KREA2_LORA_NODE, "fieldName": "LoraLoaderState", "fieldValue": lora_state},
        {"nodeId": RUNNINGHUB_KREA2_BASE_SAMPLER_NODE, "fieldName": "denoise",
         "fieldValue": f"{job['krea_denoise']:.2f}"},
    ]
    response = requests.post(
        f"{RUNNINGHUB_BASE_URL}/run/workflow/{RUNNINGHUB_KREA2_WORKFLOW_ID}",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"addMetadata": True, "nodeInfoList": nodes, "instanceType": RUNNINGHUB_KREA2_INSTANCE,
              "usePersonalQueue": False}, timeout=90)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok or not data.get("taskId"):
        raise RuntimeError(data.get("errorMessage") or data.get("message") or
                           f"RunningHub did not accept the Krea2 task ({response.status_code}).")
    return data


def _runninghub_submit_krea2_t2i(api_key, job):
    loras = [{"id": "character", "name": job["krea_lora_filename"], "on": True,
              "sm": 1, "sc": 1, "triggers": [], "custom": []}]
    for index, helper in enumerate(job.get("krea_helpers") or [], 1):
        loras.append({"id": f"helper-{index}", "name": helper["filename"], "on": True,
                      "sm": helper["strength"], "sc": helper["strength"], "triggers": [], "custom": []})
    lora_state = _json.dumps({"version": 1, "sep": ", ", "step": 0.05, "defStrength": 1,
                              "linkStrength": True, "civitai": True, "thumbs": True, "hideExt": True,
                              "accent": None, "cacheMode": "last", "loras": loras}, separators=(",", ":"))
    nodes = [
        {"nodeId": RUNNINGHUB_KREA2_T2I_PROMPT_NODE, "fieldName": "text", "fieldValue": job["krea_prompt"]},
        {"nodeId": RUNNINGHUB_KREA2_T2I_LATENT_NODE, "fieldName": "width", "fieldValue": str(job["krea_width"])},
        {"nodeId": RUNNINGHUB_KREA2_T2I_LATENT_NODE, "fieldName": "height", "fieldValue": str(job["krea_height"])},
        {"nodeId": RUNNINGHUB_KREA2_T2I_LATENT_NODE, "fieldName": "batch_size", "fieldValue": str(job["krea_batch_size"])},
        {"nodeId": RUNNINGHUB_KREA2_T2I_SAMPLER_NODE, "fieldName": "seed", "fieldValue": str(job["krea_seed"])},
        {"nodeId": RUNNINGHUB_KREA2_T2I_LORA_NODE, "fieldName": "lora_name", "fieldValue": job["krea_lora_filename"]},
        {"nodeId": RUNNINGHUB_KREA2_T2I_LORA_NODE, "fieldName": "LoraLoaderState", "fieldValue": lora_state},
    ]
    response = requests.post(f"{RUNNINGHUB_BASE_URL}/run/workflow/{RUNNINGHUB_KREA2_T2I_WORKFLOW_ID}",
                             headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                             json={"addMetadata": True, "nodeInfoList": nodes,
                                   "instanceType": RUNNINGHUB_KREA2_T2I_INSTANCE, "usePersonalQueue": False}, timeout=90)
    data = response.json()
    if not response.ok or not data.get("taskId"):
        raise RuntimeError(data.get("errorMessage") or data.get("message") or "RunningHub did not accept the Krea2 Turbo T2I task.")
    return data


def _runninghub_query(api_key, task_id):
    response = requests.post(
        f"{RUNNINGHUB_BASE_URL}/query",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"taskId": task_id}, timeout=60)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok:
        raise RuntimeError(data.get("errorMessage") or f"RunningHub status check failed ({response.status_code}).")
    return data


def _runninghub_usage_changes(result):
    """Return only real usage values reported by RunningHub."""
    usage = result.get("usage") or {}
    changes = {}
    coins = usage.get("consumeCoins")
    runtime = usage.get("taskCostTime")
    if coins not in (None, ""):
        changes["rh_coins"] = coins
    if runtime not in (None, ""):
        changes["runtime"] = runtime
    return changes


def _runninghub_backfill_usage(job_id):
    """Read missing terminal usage once; never resubmit or mutate a provider task."""
    try:
        with RUNNINGHUB_JOBS_LOCK:
            job = dict(RUNNINGHUB_JOBS.get(job_id) or {})
        if (not job or job.get("status") not in RUNNINGHUB_TERMINAL_STATUSES
                or not job.get("task_id") or job.get("rh_coins") not in (None, "")):
            return
        api_key = _decrypt_runninghub_key(job.get("key_enc", ""))
        if not api_key:
            return
        changes = _runninghub_usage_changes(_runninghub_query(api_key, job["task_id"]))
        if changes:
            _runninghub_update(job_id, **changes)
    except Exception:
        # Usage backfill is best effort; the persisted job must remain visible.
        pass
    finally:
        with RUNNINGHUB_USAGE_BACKFILL_LOCK:
            RUNNINGHUB_USAGE_BACKFILL_ACTIVE.discard(job_id)


def _schedule_runninghub_usage_backfill(jobs, limit=5):
    scheduled = []
    with RUNNINGHUB_USAGE_BACKFILL_LOCK:
        for job in jobs:
            job_id = job.get("id")
            if (len(scheduled) >= limit or not job_id or job_id in RUNNINGHUB_USAGE_BACKFILL_ACTIVE
                    or job.get("status") not in RUNNINGHUB_TERMINAL_STATUSES
                    or not job.get("task_id") or job.get("rh_coins") not in (None, "")):
                continue
            RUNNINGHUB_USAGE_BACKFILL_ACTIVE.add(job_id)
            scheduled.append(job_id)
    for job_id in scheduled:
        threading.Thread(target=_runninghub_backfill_usage, args=(job_id,), daemon=True).start()


def _runninghub_cancel(api_key, task_id):
    response = requests.post(
        "https://www.runninghub.ai/task/openapi/cancel",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"apiKey": api_key, "taskId": str(task_id)}, timeout=60)
    try:
        data = response.json()
    except ValueError:
        data = {}
    code = data.get("code")
    if code not in (807, "807") and (not response.ok or code not in (0, "0", None)):
        raise RuntimeError(data.get("message") or data.get("msg") or
                           f"RunningHub cancellation failed ({response.status_code}).")
    return data


def _runninghub_normalize_talking_video(path):
    """Guarantee the delivered Talking MP4 when a workflow revision rounds 1 MP differently."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", path],
        capture_output=True, text=True, timeout=60, check=True)
    streams = _json.loads(probe.stdout).get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not video:
        raise RuntimeError("RunningHub returned a video file without a video stream.")
    if not any(item.get("codec_type") == "audio" for item in streams):
        raise RuntimeError("RunningHub returned a Talking video without generated audio.")
    if (path.lower().endswith(".mp4") and video.get("width") == 720
            and video.get("height") == 1280 and video.get("avg_frame_rate") == "24/1"
            and video.get("codec_name") == "h264"):
        return path
    normalized = os.path.join(os.path.dirname(path), "talking-720x1280.mp4")
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", path,
        "-map", "0:v:0", "-map", "0:a:0", "-vf",
        "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=24",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", normalized,
    ], capture_output=True, text=True, timeout=900)
    if result.returncode != 0 or not os.path.exists(normalized):
        raise RuntimeError("Could not prepare the 720 × 1280 Talking video for Gallery.")
    return normalized


def _runninghub_import_result(job, result):
    outputs = result.get("results") or []
    wanted = ("png", "jpg", "jpeg", "webp") if _runninghub_workflow_key(job) in {"krea2_i2i_hq", "krea2_t2i"} else ("mp4", "mov", "webm")
    matching = [o for o in outputs if str(o.get("outputType", "")).lower() in wanted and o.get("url")]
    if not matching:
        raise RuntimeError("RunningHub finished but returned no downloadable result.")
    if job.get("workflow_key") == "krea2_t2i":
        character = re.sub(r'[\\/:*?"<>|]+', "-", str(job.get("krea_character_name") or "Character")).strip(" .")
        stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(job.get("created_at") or time.time()))
        folder = f"{character or 'Character'} · {stamp}"
        r2_store.create_folder(f"gallery/{folder}")
        keys = []
        with tempfile.TemporaryDirectory(prefix="atelier-rh-") as td:
            for index, output in enumerate(matching, 1):
                extension = str(output.get("outputType", "png")).lower()
                dst = os.path.join(td, f"cloud-result-{index}.{extension}")
                response = requests.get(output["url"], stream=True, timeout=900)
                response.raise_for_status()
                with open(dst, "wb") as f:
                    for chunk in response.iter_content(65536):
                        if chunk:
                            f.write(chunk)
                if os.path.getsize(dst) < 1024:
                    raise RuntimeError("RunningHub returned an empty result file.")
                key = f"gallery/{folder}/{index:02d}.{extension}"
                r2_store.upload(dst, key)
                _set_media_creator(key, job.get("user"))
                keys.append(key)
        return {"gallery_key": keys[0], "gallery_keys": keys, "gallery_folder": folder}
    output = matching[0]
    with tempfile.TemporaryDirectory(prefix="atelier-rh-") as td:
        extension = str(output.get("outputType", wanted[0])).lower()
        dst = os.path.join(td, "cloud-result." + extension)
        response = requests.get(output["url"], stream=True, timeout=900)
        response.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in response.iter_content(65536):
                if chunk:
                    f.write(chunk)
        if os.path.getsize(dst) < 1024:
            raise RuntimeError("RunningHub returned an empty result file.")
        # Gallery streams cloud media and lazily builds previews.
        if _runninghub_workflow_key(job) == "h3_talking":
            dst = _runninghub_normalize_talking_video(dst)
            extension = "mp4"
        key = f"gallery/cloud/{int(time.time())}_{job['id']}.{extension}"
        r2_store.upload(dst, key)
        _set_media_creator(key, job.get("user"))
    return {"gallery_key": key}


def _runninghub_cleanup_uploads(job):
    paths = [job.get("reference_path"), job.get("video_path"), job.get("krea_image_path"),
             job.get("talking_image_path")]
    for items in (job.get("h3_refs") or {}).values():
        paths.extend(item.get("path") for item in items)
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    try:
        directory = os.path.dirname(job.get("reference_path") or next((p for p in paths if p), ""))
        if directory and os.path.isdir(directory):
            os.rmdir(directory)
    except OSError:
        pass


def _runninghub_run(job_id):
    """Upload, submit, poll, and import one persisted RunningHub job."""
    try:
        with RUNNINGHUB_JOBS_LOCK:
            job = dict(RUNNINGHUB_JOBS.get(job_id) or {})
        if not job:
            return
        api_key = _decrypt_runninghub_key(job.get("key_enc", ""))
        if not api_key:
            raise RuntimeError("The RunningHub key is unavailable for this job.")
        task_id = job.get("task_id")
        if not task_id:
            if job.get("workflow_key") == "krea2_t2i":
                _runninghub_update(job_id, status="submitting", message="Submitting Krea2 Turbo Text-to-Image…")
                submitted = _runninghub_submit_krea2_t2i(api_key, job)
            elif job.get("workflow_key") == "krea2_i2i_hq":
                _runninghub_update(job_id, status="uploading", message="Uploading Krea2 source image…")
                image_name = _runninghub_upload(api_key, job["krea_image_path"], job.get("krea_image_type") or "image/png")
                if _runninghub_is_cancelled(job_id):
                    return
                _runninghub_update(job_id, status="submitting", message="Submitting Krea2 Image HQ to RunningHub…")
                submitted = _runninghub_submit_krea2(api_key, job, image_name)
            elif job.get("workflow_key") == "h3":
                uploads = {"image": [], "video": [], "audio": []}
                for media_type, items in job["h3_refs"].items():
                    for item in items:
                        if _runninghub_is_cancelled(job_id):
                            return
                        _runninghub_update(job_id, status="uploading", message=f"Uploading H3 {media_type} reference…")
                        uploads[media_type].append(_runninghub_upload(api_key, item["path"], item["type"]))
                if _runninghub_is_cancelled(job_id):
                    return
                _runninghub_update(job_id, status="submitting", message="Submitting MiniMax H3 to RunningHub…")
                submitted = _runninghub_submit_h3(api_key, job, uploads)
            elif job.get("workflow_key") == "h3_talking":
                _runninghub_update(job_id, status="uploading", message="Uploading Talking source image…")
                image_name = _runninghub_upload(
                    api_key, job["talking_image_path"], job.get("talking_image_type") or "image/png")
                if _runninghub_is_cancelled(job_id):
                    return
                _runninghub_update(job_id, status="submitting",
                                   message="Submitting H3 Optimized for Talking to RunningHub…")
                submitted = _runninghub_submit_h3_talking(api_key, job, image_name)
            else:
                _runninghub_update(job_id, status="uploading", message="Uploading reference image to RunningHub…")
                image_name = _runninghub_upload(api_key, job["reference_path"], job.get("reference_type") or "image/png")
                _runninghub_update(job_id, status="uploading", message="Uploading driving video to RunningHub…")
                video_name = _runninghub_upload(api_key, job["video_path"], job.get("video_type") or "video/mp4")
                _runninghub_update(job_id, status="submitting", message="Submitting Scail 2 to RunningHub…")
                clip = job.get("clip") or {"skip_first_frames": 0, "frame_load_cap": 0,
                                            "select_every_nth": 1}
                submitted = _runninghub_submit(api_key, image_name, video_name, job["instance_type"], clip)
            task_id = str(submitted["taskId"])
            if _runninghub_is_cancelled(job_id):
                _runninghub_cancel(api_key, task_id)
                _runninghub_update(job_id, task_id=task_id, status="cancelled", message="Cloud job cancelled.")
                return
            _runninghub_update(job_id, task_id=task_id, status="queued", message="Queued on RunningHub.")
            _runninghub_cleanup_uploads(job)

        deadline = time.time() + 45 * 60
        while time.time() < deadline:
            if _runninghub_is_cancelled(job_id):
                return
            result = _runninghub_query(api_key, task_id)
            state = str(result.get("status") or "").upper()
            changes = _runninghub_usage_changes(result)
            if state in ("QUEUED", "PENDING"):
                _runninghub_update(job_id, status="queued", message="Queued on RunningHub.", **changes)
            elif state in ("RUNNING", "PROCESSING"):
                _runninghub_update(job_id, status="running", message="Generating on RunningHub…", **changes)
            elif state == "SUCCESS":
                _runninghub_update(job_id, status="importing", message="Saving completed video to Gallery…", **changes)
                with RUNNINGHUB_JOBS_LOCK:
                    completed_job = dict(RUNNINGHUB_JOBS[job_id])
                imported = _runninghub_import_result(completed_job, result)
                _runninghub_update(job_id, status="done", message="Saved to Gallery.", **imported, **changes)
                return
            elif state in ("CANCEL", "CANCELLED", "CANCELED"):
                _runninghub_update(job_id, status="cancelled", message="Cloud job cancelled.", **changes)
                return
            elif state in ("FAILED", "ERROR"):
                reason = result.get("errorMessage") or result.get("failedReason") or "RunningHub task failed."
                _runninghub_update(job_id, status="failed", message="Cloud generation failed.", error=str(reason)[:1000], **changes)
                return
            time.sleep(5)
        raise RuntimeError("RunningHub task did not finish within 45 minutes.")
    except Exception as e:
        _runninghub_update(job_id, status="failed", message="Cloud generation failed.",
                           error=f"{type(e).__name__}: {e}")
    finally:
        with RUNNINGHUB_JOBS_LOCK:
            existing = dict(RUNNINGHUB_JOBS.get(job_id) or {})
        _runninghub_cleanup_uploads(existing)
        _runninghub_dispatch()


def _resume_runninghub_jobs():
    """Resume polling confirmed tasks after a Studio restart without re-submitting."""
    for job_id, job in list(RUNNINGHUB_JOBS.items()):
        if job.get("task_id") and job.get("status") in {"queued", "running", "importing"}:
            threading.Thread(target=_runninghub_run, args=(job_id,), daemon=True).start()
        elif job.get("status") in {"uploading", "submitting"}:
            # A restart here leaves task creation uncertain. Never submit again:
            # the user can check RunningHub and retry safely if needed.
            _runninghub_update(job_id, status="failed", message="Cloud job needs review.",
                               error="Studio restarted before RunningHub task confirmation; check RunningHub before retrying.")
    _runninghub_dispatch()


_resume_runninghub_jobs()


@app.get("/api/runninghub/loras")
def runninghub_loras():
    with RUNNINGHUB_LORAS_LOCK:
        data = _load_runninghub_loras()
    is_admin = load_users().get(session["user"], {}).get("role") == "admin"
    if is_admin:
        return jsonify({"characters": data})
    public = []
    for character in data:
        if not character.get("enabled"):
            continue
        versions = [v for v in character.get("versions", []) if v.get("enabled")]
        if versions:
            public.append({**character, "versions": versions})
    return jsonify({"characters": public})


@app.get("/api/runninghub/krea2/helpers")
def runninghub_krea2_helpers():
    with RUNNINGHUB_KREA2_HELPERS_LOCK:
        helpers = _load_runninghub_krea2_helpers()
    return jsonify({"helpers": [item for item in helpers if item["enabled"]]})


@app.get("/api/admin/runninghub/krea2/helpers")
@admin_required
def runninghub_krea2_helpers_admin():
    with RUNNINGHUB_KREA2_HELPERS_LOCK:
        return jsonify({"helpers": _load_runninghub_krea2_helpers()})


@app.put("/api/admin/runninghub/krea2/helpers")
@admin_required
def runninghub_krea2_helpers_save():
    try:
        helpers = _normalize_runninghub_krea2_helpers((request.get_json(force=True) or {}).get("helpers"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with RUNNINGHUB_KREA2_HELPERS_LOCK:
        _save_runninghub_krea2_helpers(helpers)
    return jsonify({"helpers": helpers})


@app.get("/api/runninghub/krea2-t2i/helpers")
def runninghub_krea2_t2i_helpers():
    with RUNNINGHUB_KREA2_HELPERS_LOCK:
        helpers = _load_runninghub_krea2_t2i_helpers()
    return jsonify({"helpers": [item for item in helpers if item["enabled"]]})


@app.get("/api/admin/runninghub/krea2-t2i/helpers")
@admin_required
def runninghub_krea2_t2i_helpers_admin():
    with RUNNINGHUB_KREA2_HELPERS_LOCK:
        return jsonify({"helpers": _load_runninghub_krea2_t2i_helpers()})


@app.put("/api/admin/runninghub/krea2-t2i/helpers")
@admin_required
def runninghub_krea2_t2i_helpers_save():
    try:
        helpers = _normalize_runninghub_krea2_helpers((request.get_json(force=True) or {}).get("helpers"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with RUNNINGHUB_KREA2_HELPERS_LOCK:
        _save_runninghub_krea2_t2i_helpers(helpers)
    return jsonify({"helpers": helpers})


@app.put("/api/runninghub/loras")
@admin_required
def runninghub_save_loras():
    try:
        data = _normalize_runninghub_loras((request.get_json(silent=True) or {}).get("characters"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with RUNNINGHUB_LORAS_LOCK:
        _save_runninghub_loras(data)
    return jsonify({"ok": True, "characters": data})


@app.post("/api/admin/runninghub/loras/identity-profile")
@admin_required
def runninghub_generate_identity_profile():
    face = request.files.get("image")
    if not face or not face.filename:
        return jsonify({"error": "Add a face reference image first."}), 400
    if (face.mimetype or "").lower() not in {"image/png", "image/jpeg", "image/webp"}:
        return jsonify({"error": "Choose a PNG, JPG, or WEBP face reference."}), 400
    image_bytes = face.read()
    if len(image_bytes) > RUNNINGHUB_MAX_IMAGE_BYTES:
        return jsonify({"error": "Face reference exceeds the Cloud upload limit."}), 413
    try:
        params = _describe_params(request.form, True)
        profile = describe_image(base64.b64encode(image_bytes).decode(), params, params["model"],
                                 _character_profile_instruction())
        return jsonify({"identity_profile": profile})
    except Exception as e:
        return jsonify({"error": f"OpenRouter call failed: {e}"}), 500


@app.get("/api/runninghub/settings")
def runninghub_settings():
    username = session["user"]
    settings = _runninghub_user_settings(username)
    return jsonify({"configured": settings["configured"], "plus_allowed": settings["plus_allowed"], "cloud_workflows": _cloud_workflows_for(username),
                    "concurrency": settings["concurrency"], "workflow_id": RUNNINGHUB_WORKFLOW_ID,
                    "standard": "default", "plus": "plus"})


@app.put("/api/runninghub/settings")
@admin_required
def runninghub_save_settings():
    key = (request.get_json(force=True).get("api_key") or "").strip()
    if len(key) < 16:
        return jsonify({"error": "Enter a valid RunningHub API key."}), 400
    users = load_users()
    users[session["user"]]["runninghub_key_enc"] = _encrypt_runninghub_key(key)
    save_users(users)
    return jsonify({"ok": True, **_runninghub_user_settings(session["user"])})


@app.delete("/api/runninghub/settings")
@admin_required
def runninghub_delete_settings():
    users = load_users()
    users[session["user"]].pop("runninghub_key_enc", None)
    save_users(users)
    return jsonify({"ok": True})


@app.get("/api/runninghub/global-key")
@admin_required
def runninghub_global_key_status():
    settings = _runninghub_global_settings()
    key = settings["key"]
    return jsonify({"configured": bool(key), "masked": _mask_runninghub_key(key) if key else "",
                    "concurrency": settings["concurrency"], "source": settings["source"]})


@app.put("/api/runninghub/global-key")
@admin_required
def runninghub_global_key_set():
    body = request.get_json(force=True)
    key = str(body.get("api_key") or "").strip()
    try:
        concurrency = max(1, min(100, int(body.get("concurrency") or 1)))
    except (TypeError, ValueError):
        return jsonify({"error": "Concurrency must be between 1 and 100."}), 400
    if len(key) < 16:
        return jsonify({"error": "Enter a valid RunningHub API key."}), 400
    with RUNNINGHUB_GLOBAL_SETTINGS_LOCK:
        _save_runninghub_global_settings({"key_enc": _encrypt_runninghub_key(key), "concurrency": concurrency})
    return jsonify({"ok": True, "configured": True, "masked": _mask_runninghub_key(key), "concurrency": concurrency})


@app.delete("/api/runninghub/global-key")
@admin_required
def runninghub_global_key_delete():
    with RUNNINGHUB_GLOBAL_SETTINGS_LOCK:
        _save_runninghub_global_settings({"disabled": True})
    return jsonify({"ok": True, "configured": False})


@app.post("/api/runninghub/jobs")
@cloud_workflow_required("scail")
def runninghub_create_job():
    username = session["user"]
    settings = _runninghub_user_settings(username)
    if not settings["configured"]:
        return jsonify({"error": "Save your RunningHub API key before starting a cloud job."}), 400
    with RUNNINGHUB_JOBS_LOCK:
        if _runninghub_has_active_locked(username, "scail"):
            return jsonify({"error": "A Scail 2 cloud job is already active. Wait for it or cancel it first."}), 409
    reference, video = request.files.get("reference"), request.files.get("video")
    if not reference or not video or not reference.filename or not video.filename:
        return jsonify({"error": "A reference image and driving video are required."}), 400
    if (request.content_length or 0) > RUNNINGHUB_MAX_IMAGE_BYTES + RUNNINGHUB_MAX_VIDEO_BYTES + 1024 * 1024:
        return jsonify({"error": "Files are too large for Cloud upload."}), 413
    requested = (request.form.get("instance_type") or "default").strip().lower()
    if requested not in ("default", "plus"):
        return jsonify({"error": "Unsupported RunningHub instance."}), 400
    if requested == "plus" and not settings["plus_allowed"]:
        return jsonify({"error": "Plus is not enabled for your account."}), 403
    try:
        start_seconds = int(request.form.get("start_seconds") or 0)
        duration_value = (request.form.get("duration_seconds") or "full").strip().lower()
        select_every_nth = int(request.form.get("select_every_nth") or 1)
    except (TypeError, ValueError):
        return jsonify({"error": "Cloud clip controls must be valid numbers."}), 400
    if start_seconds < 0 or start_seconds > 600:
        return jsonify({"error": "Start time must be between 0 and 600 seconds."}), 400
    if duration_value == "full":
        frame_load_cap = 0
        duration_seconds = None
    else:
        try:
            duration_seconds = int(duration_value)
        except ValueError:
            return jsonify({"error": "Choose Full clip or a valid duration."}), 400
        if duration_seconds not in (3, 5, 8, 10):
            return jsonify({"error": "Choose 3, 5, 8, 10 seconds, or Full clip."}), 400
        frame_load_cap = duration_seconds * RUNNINGHUB_VIDEO_FPS
    if select_every_nth not in (1, 2, 3):
        return jsonify({"error": "Frame sampling must be every 1, 2, or 3 frames."}), 400
    clip = {"start_seconds": start_seconds, "duration_seconds": duration_seconds,
            "force_rate": RUNNINGHUB_VIDEO_FPS,
            "skip_first_frames": start_seconds * RUNNINGHUB_VIDEO_FPS,
            "frame_load_cap": frame_load_cap, "select_every_nth": select_every_nth}
    job_id = uuid.uuid4().hex
    job_dir = os.path.join(RUNNINGHUB_UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=False)
    reference_path = os.path.join(job_dir, "reference_" + (secure_filename(reference.filename) or "image.png"))
    video_path = os.path.join(job_dir, "driving_" + (secure_filename(video.filename) or "video.mp4"))
    reference.save(reference_path)
    video.save(video_path)
    if os.path.getsize(reference_path) > RUNNINGHUB_MAX_IMAGE_BYTES or os.path.getsize(video_path) > RUNNINGHUB_MAX_VIDEO_BYTES:
        _runninghub_cleanup_uploads({"reference_path": reference_path, "video_path": video_path})
        return jsonify({"error": "Reference image or driving video exceeds the Cloud upload limit."}), 413
    job = {"id": job_id, "user": username, "workflow_key": "scail", "status": "waiting", "message": "Waiting for a cloud slot…",
           "created_at": int(time.time()), "updated_at": int(time.time()), "instance_type": requested,
           "workflow_id": RUNNINGHUB_WORKFLOW_ID, "key_enc": settings["key_enc"],
           "key_fingerprint": settings["key_fingerprint"], "key_concurrency": settings["concurrency"],
           "reference_path": reference_path, "reference_type": reference.mimetype,
           "video_path": video_path, "video_type": video.mimetype, "clip": clip,
           "estimated_total_seconds": RUNNINGHUB_STANDARD_ESTIMATE_SECONDS if requested == "default" else None}
    with RUNNINGHUB_JOBS_LOCK:
        if _runninghub_has_active_locked(username, "scail"):
            _runninghub_cleanup_uploads(job)
            return jsonify({"error": "A Scail 2 cloud job is already active. Wait for it or cancel it first."}), 409
        RUNNINGHUB_JOBS[job_id] = job
        _save_runninghub_jobs()
    _runninghub_dispatch()
    return jsonify({"id": job_id, "status": "waiting"}), 202


@app.post("/api/runninghub/h3/jobs")
@cloud_workflow_required("h3")
def runninghub_create_h3_job():
    username = session["user"]
    settings = _runninghub_user_settings(username)
    if not settings["configured"]:
        return jsonify({"error": "Cloud access has not been assigned by an administrator."}), 403
    with RUNNINGHUB_JOBS_LOCK:
        if _runninghub_has_active_locked(username, "h3"):
            return jsonify({"error": "A MiniMax H3 cloud job is already active. Wait for it or cancel it first."}), 409
    images = [f for f in request.files.getlist("images") if f and f.filename]
    videos = [f for f in request.files.getlist("videos") if f and f.filename]
    audios = [f for f in request.files.getlist("audio") if f and f.filename]
    if not 1 <= len(images) <= len(RUNNINGHUB_H3_IMAGE_NODES):
        return jsonify({"error": "This published H3 workflow supports one to three images."}), 400
    if len(videos) > 1:
        return jsonify({"error": "This published H3 workflow supports one optional video reference."}), 400
    if len(audios) > len(RUNNINGHUB_H3_AUDIO_NODES):
        return jsonify({"error": "H3 supports up to three audio references."}), 400
    prompt = (request.form.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Enter a prompt for MiniMax H3."}), 400
    aspect = (request.form.get("aspect") or "9:16").strip()
    if aspect not in {"9:16", "16:9", "1:1", "4:3", "3:4"}:
        return jsonify({"error": "Choose a supported aspect ratio."}), 400
    try:
        duration = int(request.form.get("duration") or 10)
    except ValueError:
        return jsonify({"error": "Choose a valid duration."}), 400
    if duration not in {5, 10, 15}:
        return jsonify({"error": "H3 duration must be 5, 10, or 15 seconds."}), 400
    groups = {"image": images, "video": videos, "audio": audios}
    limits = {"image": RUNNINGHUB_MAX_IMAGE_BYTES, "video": RUNNINGHUB_MAX_VIDEO_BYTES,
              "audio": RUNNINGHUB_MAX_AUDIO_BYTES}
    job_id = uuid.uuid4().hex
    job_dir = os.path.join(RUNNINGHUB_UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=False)
    refs = {"image": [], "video": [], "audio": []}
    try:
        for kind, files in groups.items():
            for index, upload in enumerate(files, 1):
                safe_name = secure_filename(upload.filename) or f"{kind}-{index}"
                path = os.path.join(job_dir, f"{kind}_{index}_{safe_name}")
                upload.save(path)
                if os.path.getsize(path) > limits[kind]:
                    raise ValueError(f"{kind.title()} {index} exceeds the Cloud upload limit.")
                refs[kind].append({"path": path, "type": upload.mimetype or "application/octet-stream"})
    except Exception as e:
        _runninghub_cleanup_uploads({"h3_refs": refs})
        return jsonify({"error": str(e)}), 413 if isinstance(e, ValueError) else 400
    job = {"id": job_id, "user": username, "workflow_key": "h3", "status": "waiting",
           "message": "Waiting for a cloud slot…", "created_at": int(time.time()),
           "updated_at": int(time.time()), "instance_type": RUNNINGHUB_H3_INSTANCE,
           "workflow_id": RUNNINGHUB_H3_WORKFLOW_ID, "key_enc": settings["key_enc"],
           "key_fingerprint": settings["key_fingerprint"], "key_concurrency": settings["concurrency"],
           "h3_refs": refs, "h3_prompt": prompt, "h3_aspect": aspect, "h3_duration": duration,
           "estimated_total_seconds": None}
    with RUNNINGHUB_JOBS_LOCK:
        if _runninghub_has_active_locked(username, "h3"):
            _runninghub_cleanup_uploads(job)
            return jsonify({"error": "A MiniMax H3 cloud job is already active. Wait for it or cancel it first."}), 409
        RUNNINGHUB_JOBS[job_id] = job
        _save_runninghub_jobs()
    _runninghub_dispatch()
    return jsonify({"id": job_id, "status": "waiting"}), 202


@app.post("/api/runninghub/h3-talking/jobs")
@cloud_workflow_required("h3_talking")
def runninghub_create_h3_talking_job():
    username = session["user"]
    settings = _runninghub_user_settings(username)
    if not settings["configured"]:
        return jsonify({"error": "Cloud access has not been assigned by an administrator."}), 403
    with RUNNINGHUB_JOBS_LOCK:
        if _runninghub_has_active_locked(username, "h3_talking"):
            return jsonify({"error": "An H3 Optimized for Talking job is already active. Wait for it or cancel it first."}), 409
    image = request.files.get("image")
    if not image or not image.filename:
        return jsonify({"error": "A source image is required."}), 400
    if (image.mimetype or "").lower() not in {"image/png", "image/jpeg", "image/webp"}:
        return jsonify({"error": "Choose a PNG, JPG, or WEBP source image."}), 400
    prompt = request.form.get("prompt") or ""
    if not prompt.strip():
        return jsonify({"error": "Generate or enter the final H3 prompt."}), 400
    try:
        duration = _parse_h3_talking_duration(request.form.get("duration"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    job_id = uuid.uuid4().hex
    job_dir = os.path.join(RUNNINGHUB_UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=False)
    image_path = os.path.join(job_dir, "talking_" + (secure_filename(image.filename) or "source.png"))
    try:
        image.save(image_path)
        if os.path.getsize(image_path) > RUNNINGHUB_MAX_IMAGE_BYTES:
            raise ValueError("Source image exceeds the Cloud upload limit.")
    except Exception as exc:
        _runninghub_cleanup_uploads({"talking_image_path": image_path})
        return jsonify({"error": str(exc)}), 413 if isinstance(exc, ValueError) else 400
    job = {
        "id": job_id, "user": username, "workflow_key": "h3_talking", "status": "waiting",
        "message": "Waiting for a cloud slot…", "created_at": int(time.time()),
        "updated_at": int(time.time()), "instance_type": RUNNINGHUB_H3_TALKING_INSTANCE,
        "workflow_id": RUNNINGHUB_H3_TALKING_WORKFLOW_ID, "key_enc": settings["key_enc"],
        "key_fingerprint": settings["key_fingerprint"], "key_concurrency": settings["concurrency"],
        "talking_image_path": image_path, "talking_image_type": image.mimetype or "image/png",
        "talking_prompt": prompt, "talking_duration": duration, "estimated_total_seconds": None,
    }
    with RUNNINGHUB_JOBS_LOCK:
        if _runninghub_has_active_locked(username, "h3_talking"):
            _runninghub_cleanup_uploads(job)
            return jsonify({"error": "An H3 Optimized for Talking job is already active. Wait for it or cancel it first."}), 409
        RUNNINGHUB_JOBS[job_id] = job
        _save_runninghub_jobs()
    _runninghub_dispatch()
    return jsonify({"id": job_id, "status": "waiting"}), 202


@app.post("/api/runninghub/krea2/jobs")
@cloud_workflow_required("krea2_i2i_hq")
def runninghub_create_krea2_job():
    username = session["user"]
    settings = _runninghub_user_settings(username)
    if not settings["configured"]:
        return jsonify({"error": "Cloud access has not been assigned by an administrator."}), 403
    with RUNNINGHUB_JOBS_LOCK:
        if _runninghub_has_active_locked(username, "krea2_i2i_hq"):
            return jsonify({"error": "A Krea2 Image HQ cloud job is already active. Wait for it or cancel it first."}), 409
    image = request.files.get("image")
    prompt = (request.form.get("prompt") or "").strip()
    preset_key = (request.form.get("resolution_key") or "").strip()
    try:
        denoise = float(request.form.get("denoise", "0.60"))
    except (TypeError, ValueError):
        return jsonify({"error": "Denoise must be a number from 0 to 1."}), 400
    if not math.isfinite(denoise) or denoise < 0 or denoise > 1:
        return jsonify({"error": "Denoise must be a number from 0 to 1."}), 400
    if not image or not image.filename:
        return jsonify({"error": "A source image is required."}), 400
    if not prompt:
        return jsonify({"error": "Enter or generate a prompt."}), 400
    preset = next((p for p in RES_PRESETS if p["key"] == preset_key), None)
    if not preset:
        return jsonify({"error": "Choose a supported Krea2 resolution."}), 400
    try:
        submitted_helpers = _json.loads(request.form.get("helpers", "[]"))
    except (TypeError, ValueError):
        return jsonify({"error": "Helper LoRAs must be valid data."}), 400
    if not isinstance(submitted_helpers, list):
        return jsonify({"error": "Helper LoRAs must be a list."}), 400
    with RUNNINGHUB_KREA2_HELPERS_LOCK:
        available_helpers = {item["filename"].lower(): item
                             for item in _load_runninghub_krea2_helpers() if item["enabled"]}
    helpers = []
    for raw in submitted_helpers:
        filename = str((raw or {}).get("filename") or "").strip()
        if not filename or not bool((raw or {}).get("enabled", True)):
            continue
        managed = available_helpers.get(filename.lower())
        if not managed:
            return jsonify({"error": "A selected helper LoRA is no longer available."}), 400
        try:
            strength = float((raw or {}).get("strength", managed["strength"]))
        except (TypeError, ValueError):
            return jsonify({"error": f"{managed['filename']} needs a numeric strength."}), 400
        if not math.isfinite(strength) or not 0 <= strength <= 2:
            return jsonify({"error": f"{managed['filename']} strength must be from 0 to 2."}), 400
        helpers.append({"filename": managed["filename"], "strength": round(strength, 2)})
    lora = _resolve_runninghub_lora((request.form.get("character_id") or "").strip(),
                                    (request.form.get("version_id") or "").strip())
    if not lora:
        return jsonify({"error": "Choose an available Cloud character and version."}), 400
    trigger_words = lora.get("trigger_words", "").strip()
    if trigger_words:
        prompt = f"{trigger_words}, {prompt}"
    job_id = uuid.uuid4().hex
    job_dir = os.path.join(RUNNINGHUB_UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=False)
    image_path = os.path.join(job_dir, "source_" + (secure_filename(image.filename) or "image.png"))
    image.save(image_path)
    if os.path.getsize(image_path) > RUNNINGHUB_MAX_IMAGE_BYTES:
        _runninghub_cleanup_uploads({"krea_image_path": image_path})
        return jsonify({"error": "Source image exceeds the Cloud upload limit."}), 413
    job = {"id": job_id, "user": username, "workflow_key": "krea2_i2i_hq", "status": "waiting",
           "message": "Waiting for a cloud slot…", "created_at": int(time.time()), "updated_at": int(time.time()),
           "instance_type": RUNNINGHUB_KREA2_INSTANCE, "workflow_id": RUNNINGHUB_KREA2_WORKFLOW_ID,
           "key_enc": settings["key_enc"], "key_fingerprint": settings["key_fingerprint"],
           "key_concurrency": settings["concurrency"], "krea_image_path": image_path,
           "krea_image_type": image.mimetype, "krea_prompt": prompt, "krea_resolution_key": preset_key,
           "krea_width": preset["width"], "krea_height": preset["height"], "krea_denoise": denoise,
           "krea_helpers": helpers,
           "krea_character_id": lora["character_id"], "krea_character_name": lora["character_name"],
           "krea_version_id": lora["version_id"], "krea_version_label": lora["version_label"],
           "krea_lora_filename": lora["filename"], "estimated_total_seconds": None}
    with RUNNINGHUB_JOBS_LOCK:
        if _runninghub_has_active_locked(username, "krea2_i2i_hq"):
            _runninghub_cleanup_uploads(job)
            return jsonify({"error": "A Krea2 Image HQ cloud job is already active. Wait for it or cancel it first."}), 409
        RUNNINGHUB_JOBS[job_id] = job
        _save_runninghub_jobs()
    _runninghub_dispatch()
    return jsonify({"id": job_id, "status": "waiting"}), 202


@app.post("/api/runninghub/krea2-t2i/jobs")
@cloud_workflow_required("krea2_t2i")
def runninghub_create_krea2_t2i_job():
    username = session["user"]
    settings = _runninghub_user_settings(username)
    prompt = (request.form.get("prompt") or "").strip()
    preset = next((p for p in RES_PRESETS if p["key"] == (request.form.get("resolution_key") or "").strip()), None)
    if not settings["configured"]:
        return jsonify({"error": "Cloud access has not been assigned by an administrator."}), 403
    if not prompt or not preset:
        return jsonify({"error": "Enter a prompt and choose a supported resolution."}), 400
    try:
        batch_size, seed = int(request.form.get("batch_size", "1")), int(request.form.get("seed", "0"))
        submitted_helpers = _json.loads(request.form.get("helpers", "[]"))
    except (TypeError, ValueError):
        return jsonify({"error": "Batch, seed, or helper LoRAs are invalid."}), 400
    if not 1 <= batch_size <= 16 or seed < 0:
        return jsonify({"error": "Batch must be from 1 to 16 and seed must be positive."}), 400
    lora = _resolve_runninghub_lora((request.form.get("character_id") or "").strip(),
                                    (request.form.get("version_id") or "").strip())
    if not lora:
        return jsonify({"error": "Choose an available Cloud character and version."}), 400
    with RUNNINGHUB_KREA2_HELPERS_LOCK:
        available = {item["filename"].lower(): item for item in _load_runninghub_krea2_t2i_helpers() if item["enabled"]}
    helpers = []
    for raw in submitted_helpers if isinstance(submitted_helpers, list) else []:
        if not bool((raw or {}).get("enabled", True)):
            continue
        managed = available.get(str((raw or {}).get("filename") or "").lower())
        if not managed:
            return jsonify({"error": "A selected T2I helper LoRA is no longer available."}), 400
        try:
            strength = round(float((raw or {}).get("strength", managed["strength"])), 2)
        except (TypeError, ValueError):
            return jsonify({"error": "T2I helper strength must be numeric."}), 400
        if not 0 <= strength <= 2:
            return jsonify({"error": "T2I helper strength must be from 0 to 2."}), 400
        helpers.append({"filename": managed["filename"], "strength": strength})
    final_prompt = f"{lora.get('trigger_words', '').strip()}, {prompt}".strip(", ")
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "user": username, "workflow_key": "krea2_t2i", "status": "waiting",
           "message": "Waiting for a cloud slot…", "created_at": int(time.time()), "updated_at": int(time.time()),
           "instance_type": RUNNINGHUB_KREA2_T2I_INSTANCE, "workflow_id": RUNNINGHUB_KREA2_T2I_WORKFLOW_ID,
           "key_enc": settings["key_enc"], "key_fingerprint": settings["key_fingerprint"], "key_concurrency": settings["concurrency"],
           "krea_prompt": final_prompt, "krea_width": preset["width"], "krea_height": preset["height"],
           "krea_batch_size": batch_size, "krea_seed": seed, "krea_helpers": helpers,
           "krea_character_id": lora["character_id"], "krea_character_name": lora["character_name"],
           "krea_version_id": lora["version_id"], "krea_version_label": lora["version_label"],
           "krea_lora_filename": lora["filename"], "estimated_total_seconds": None}
    with RUNNINGHUB_JOBS_LOCK:
        if _runninghub_has_active_locked(username, "krea2_t2i"):
            return jsonify({"error": "A Krea2 Turbo Text-to-Image job is already active."}), 409
        RUNNINGHUB_JOBS[job_id] = job
        _save_runninghub_jobs()
    _runninghub_dispatch()
    return jsonify({"id": job_id, "status": "waiting"}), 202


def _runninghub_public_job(job):
    safe = {k: v for k, v in job.items() if k not in {"key_enc", "key_fingerprint", "key_concurrency", "reference_path", "video_path", "h3_refs", "krea_image_path", "talking_image_path", "talking_prompt"}}
    elapsed = max(0, int(time.time()) - int(safe.get("created_at") or time.time()))
    safe["elapsed_seconds"] = elapsed
    if safe.get("status") in {"uploading", "submitting", "running", "importing"} and safe.get("estimated_total_seconds"):
        safe["estimated_remaining_seconds"] = max(0, safe["estimated_total_seconds"] - elapsed)
    if safe.get("gallery_key"):
        from urllib.parse import quote
        url_key = quote(safe["gallery_key"], safe="")
        safe["gallery_url"] = f"/api/media?key={url_key}"
        safe["download_url"] = f"/api/media?key={url_key}&download=1"
    return safe


def _runninghub_coin_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


@app.get("/api/runninghub/jobs")
@cloud_workflow_required("jobs")
def runninghub_list_jobs():
    username = session["user"]
    with RUNNINGHUB_JOBS_LOCK:
        all_jobs = [dict(j) for j in RUNNINGHUB_JOBS.values()]
    view = (request.args.get("view") or "rail").strip().lower()
    if view not in {"rail", "history"}:
        return jsonify({"error": "View must be rail or history."}), 400
    if view == "history":
        scope = (request.args.get("scope") or "my").strip().lower()
        if scope not in {"my", "all"}:
            return jsonify({"error": "Scope must be my or all."}), 400
        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 20))
        except (TypeError, ValueError):
            return jsonify({"error": "Page values must be whole numbers."}), 400
        if page < 1 or per_page < 1 or per_page > 100:
            return jsonify({"error": "Page must be positive and per_page must be from 1 to 100."}), 400
        workflow = (request.args.get("workflow") or "").strip()
        status = (request.args.get("status") or "").strip().lower()
        query = (request.args.get("q") or "").strip().lower()
        if workflow and workflow not in {"scail", "h3", "h3_talking", "krea2_i2i_hq", "krea2_t2i"}:
            return jsonify({"error": "Unknown Cloud workflow filter."}), 400
        jobs = all_jobs if scope == "all" else [j for j in all_jobs if j.get("user") == username]
        if workflow:
            jobs = [j for j in jobs if _runninghub_workflow_key(j) == workflow]
        if status:
            if status == "active":
                jobs = [j for j in jobs if j.get("status") in RUNNINGHUB_ACTIVE_STATUSES]
            elif status == "completed":
                jobs = [j for j in jobs if j.get("status") == "done"]
            elif status in {"failed", "cancelled"}:
                jobs = [j for j in jobs if j.get("status") == status]
            else:
                return jsonify({"error": "Unknown Cloud job status filter."}), 400
        if query:
            jobs = [j for j in jobs if query in " ".join(str(j.get(k) or "").lower()
                    for k in ("id", "task_id", "user"))]
        jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
        total = len(jobs)
        known_coins = [_runninghub_coin_number(j.get("rh_coins")) for j in jobs]
        known_coin_total = round(sum(v for v in known_coins if v is not None), 4)
        start = (page - 1) * per_page
        page_jobs = jobs[start:start + per_page]
        _schedule_runninghub_usage_backfill(page_jobs)
        return jsonify({"jobs": [_runninghub_public_job(j) for j in page_jobs], "page": page,
                        "per_page": per_page, "total": total,
                        "total_pages": math.ceil(total / per_page) if total else 0,
                        "known_coin_total": known_coin_total})

    user_jobs = [j for j in all_jobs if j.get("user") == username]
    user_jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    # Cloud is a live work surface, not an archive. Keep every active task
    # visible plus a compact recent history for the queue rail.
    active = [j for j in user_jobs if j.get("status") in RUNNINGHUB_ACTIVE_STATUSES]
    recent = [j for j in user_jobs if j.get("status") in RUNNINGHUB_TERMINAL_STATUSES][:5]
    jobs = active + recent
    jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    return jsonify({"jobs": [_runninghub_public_job(j) for j in jobs]})


@app.get("/api/runninghub/jobs/<job_id>")
@cloud_workflow_required("jobs")
def runninghub_get_job(job_id):
    with RUNNINGHUB_JOBS_LOCK:
        job = dict(RUNNINGHUB_JOBS.get(job_id) or {})
    if not job or job.get("user") != session["user"]:
        return jsonify({"error": "Cloud job not found."}), 404
    return jsonify(_runninghub_public_job(job))


@app.post("/api/runninghub/jobs/<job_id>/cancel")
@cloud_workflow_required("jobs")
def runninghub_cancel_job(job_id):
    username = session["user"]
    with RUNNINGHUB_JOBS_LOCK:
        job = dict(RUNNINGHUB_JOBS.get(job_id) or {})
    if not job or job.get("user") != username:
        return jsonify({"error": "Cloud job not found."}), 404
    if job.get("status") in RUNNINGHUB_TERMINAL_STATUSES:
        return jsonify(_runninghub_public_job(job))

    task_id = job.get("task_id")
    if not task_id:
        cancelled = _runninghub_update(job_id, status="cancelled", message="Cloud job cancelled.")
        _runninghub_cleanup_uploads(cancelled or job)
        _runninghub_dispatch()
        return jsonify(_runninghub_public_job(cancelled or job))

    previous_status, previous_message = job.get("status"), job.get("message")
    _runninghub_update(job_id, status="cancelling", message="Cancelling on RunningHub…")
    try:
        api_key = _decrypt_runninghub_key(job.get("key_enc", ""))
        if not api_key:
            raise RuntimeError("The RunningHub key is unavailable for this job.")
        _runninghub_cancel(api_key, task_id)
    except Exception as e:
        _runninghub_update(job_id, status=previous_status, message=previous_message,
                           error=f"Cancellation failed: {e}")
        return jsonify({"error": str(e)}), 502
    cancelled = _runninghub_update(job_id, status="cancelled", message="Cloud job cancelled.")
    _runninghub_cleanup_uploads(cancelled or job)
    _runninghub_dispatch()
    return jsonify(_runninghub_public_job(cancelled or job))


@app.get("/api/gallery/groups")
def gallery_groups():
    try:
        return jsonify({"groups": r2_store.list_dirs("gallery/")})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}", "groups": []}), 200


_GALLERY_BATCH_RE = re.compile(
    r"^(?P<character>.+?)\s+·\s+(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2})$")


def _gallery_batch_parts(folder):
    """Return the character and sortable timestamp encoded in a cloud batch folder."""
    match = _GALLERY_BATCH_RE.fullmatch(folder or "")
    if not match:
        return None
    stamp = match.group("stamp")
    return {"character": match.group("character"), "stamp": stamp,
            "sort_key": stamp.replace("-", "").replace(" ", "").replace(":", "")}


def _gallery_item_sort_key(item):
    """Use R2 time where available, otherwise the batch-folder timestamp."""
    created = item.get("created_at")
    if created is not None:
        return str(created)
    folder = item.get("key", "")[len("gallery/"):].split("/", 1)[0]
    batch = _gallery_batch_parts(folder)
    return batch["sort_key"] if batch else ""


def _gallery_batch_job_index():
    """Completed cloud-job metadata supplies previews/counts without R2 scans."""
    with RUNNINGHUB_JOBS_LOCK:
        jobs = [dict(job) for job in RUNNINGHUB_JOBS.values()]
    index = {}
    for job in jobs:
        folder = job.get("gallery_folder")
        if not folder:
            continue
        keys = job.get("gallery_keys") or ([job["gallery_key"]] if job.get("gallery_key") else [])
        index[folder] = {"count": len(keys), "preview_key": keys[0] if keys else ""}
    return index


@app.get("/api/gallery/characters")
def gallery_characters():
    """Lightweight character navigation from direct Gallery folder prefixes."""
    try:
        characters = {}
        for folder in r2_store.list_dirs("gallery/"):
            batch = _gallery_batch_parts(folder) or {"character": folder, "sort_key": ""}
            rec = characters.setdefault(batch["character"], {"name": batch["character"],
                                                              "batch_count": 0, "latest": ""})
            rec["batch_count"] += 1
            rec["latest"] = max(rec["latest"], batch["sort_key"])
        return jsonify({"characters": sorted(characters.values(),
                                               key=lambda item: (item["latest"], item["name"].lower()),
                                               reverse=True)})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}", "characters": []}), 200


@app.get("/api/gallery/batches")
def gallery_batches():
    """List one character's batch folders without loading their images."""
    from urllib.parse import quote
    character = (request.args.get("character") or "").strip()
    if not character:
        return jsonify({"error": "Character required.", "batches": []}), 400
    try:
        job_index = _gallery_batch_job_index()
        batches = []
        for folder in r2_store.list_dirs("gallery/"):
            parsed = _gallery_batch_parts(folder)
            if (parsed["character"] if parsed else folder) != character:
                continue
            meta = job_index.get(folder, {})
            preview_key = meta.get("preview_key", "")
            batches.append({
                "folder": folder,
                "label": parsed["stamp"] if parsed else folder,
                "sort_key": parsed["sort_key"] if parsed else "",
                "count": meta.get("count"),
                "preview_url": f"/api/media?key={quote(preview_key, safe='')}" if preview_key else "",
            })
        batches.sort(key=lambda item: (item["sort_key"], item["folder"].lower()), reverse=True)
        return jsonify({"batches": batches})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}", "batches": []}), 200


@app.get("/api/gallery/list")
def gallery_list():
    from urllib.parse import quote
    group = request.args.get("group", "")
    prefix = f"gallery/{group}/" if group else "gallery/"
    imgs = r2_store.list_objs(prefix)
    # Every supported Gallery media type gets a thumb_url. Missing previews heal
    # on their first view, including older videos, so the grid never preloads MP4s.
    for im in imgs:
        if im["key"].lower().endswith((".png", ".mp4", ".mov", ".webm")):
            stem, _ext = os.path.splitext(im["key"][len("gallery/"):])
            thumb_key = "thumbs/" + stem + ".webp"
            im["thumb_url"] = f"/api/media?key={quote(thumb_key, safe='')}"
    imgs.sort(key=lambda x: (_gallery_item_sort_key(x), x["name"]), reverse=True)
    return jsonify({"images": _enrich_media_creator(imgs)})


@app.post("/api/gallery/delete")
def gallery_delete():
    key = request.get_json(force=True).get("key", "")
    if key.startswith("gallery/"):
        r2_store.delete(key)
        _delete_media_metadata(key)
    return jsonify({"ok": True})


@app.post("/api/gallery/folder")
@admin_required
def gallery_folder_create():
    try:
        folder = _folder_name(request.get_json(force=True).get("name", ""))
        if not folder:
            raise ValueError("Folder name required.")
        r2_store.create_folder(f"gallery/{folder}")
        return jsonify({"ok": True, "folder": folder})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/gallery/move")
@admin_required
def gallery_move():
    body = request.get_json(force=True)
    try:
        key = _move_library_media(body.get("key", ""), body.get("folder", ""), "gallery/", "thumbs/")
        return jsonify({"ok": True, "key": key})
    except (ValueError, FileExistsError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


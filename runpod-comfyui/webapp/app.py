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
LOCAL_COMFY = os.environ.get("LOCAL_COMFY_URL", "http://127.0.0.1:8189")  # matches Windows_Run_GPU.bat
WORKFLOW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# So the app can start ComfyUI for you when it's not running.
COMFY_DIR = os.environ.get("COMFY_DIR", "I:/@home/jimi/Documents/ComfyUI_V82")
COMFY_BAT = os.environ.get("COMFY_BAT", "Windows_Run_GPU.bat")

# Home agent — when set (on the VPS), start/stop go through it instead of a local
# subprocess (the VPS can't launch programs on the home PC directly).
AGENT_URL = os.environ.get("AGENT_URL", "").rstrip("/")
AGENT_SECRET = os.environ.get("AGENT_SECRET", "")

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
        r = requests.get(f"{LOCAL_COMFY}/system_stats", headers=comfy_common.CF_HEADERS,
                         allow_redirects=False, timeout=6)
        local = r.status_code == 200  # 302 (Access login) / 502 (tunnel down) => not ready
    except Exception:
        pass
    return jsonify({"local": local, "cloud": bool(ENDPOINT_ID and API_KEY)})


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


@app.get("/api/reels/media")
def reels_media():
    """Proxy a reel from the R2 Worker so the browser can preview/download it
    without ever seeing the Worker secret."""
    key = request.args.get("key", "")
    if not key:
        return jsonify({"error": "no key"}), 400
    up = r2_store.stream(key)
    if up.status_code != 200:
        return ("not found", up.status_code)
    headers = {"Content-Type": "video/mp4"}
    if request.args.get("download"):
        headers["Content-Disposition"] = f'attachment; filename="{key.split("/")[-1]}"'
    return Response(up.iter_content(65536), headers=headers)


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


"""
Home agent — a tiny always-on helper on the PC with the 5090.

The VPS-hosted studio can't launch programs on your home machine, so this agent
does it: it exposes start / stop / status for ComfyUI on localhost:8190, which
cloudflared publishes at https://agent.thecristinaadam.com (behind a secret).

Run via Start_Agent.bat (which sets AGENT_SECRET). Binds to 127.0.0.1 only —
the outside world reaches it solely through the Cloudflare tunnel + the secret.
"""

import base64
import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from flask import Flask, request, jsonify

SECRET = os.environ.get("AGENT_SECRET", "")
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8189")
COMFY_DIR = os.environ.get("COMFY_DIR", r"I:\@home\jimi\Documents\ComfyUI_V82")
COMFY_BAT = os.environ.get("COMFY_BAT", "Windows_Run_GPU.bat")
COMFY_PORT = "8189"

app = Flask(__name__)


def authed():
    return bool(SECRET) and request.headers.get("x-agent-secret") == SECRET


def comfy_up():
    try:
        urllib.request.urlopen(COMFY_URL + "/system_stats", timeout=3)
        return True
    except Exception:
        return False


# --- live progress: listen to ComfyUI's WS locally with the shared client id ---
CLIENT_ID = "atelier-progress"
PROGRESS = {"running": False, "value": 0, "max": 0}

# --- interactive popups (INSTARAW image picker / mask editor) -----------------
# ComfyUI broadcasts 'instaraw-interactive-images' over the WS when a workflow pauses
# for user input. The VPS can't receive WS through the tunnel, so we capture it here
# (local to ComfyUI), expose it via /interaction, and relay the user's answer back to
# ComfyUI locally via /interact -> POST /instaraw/interactive_message.
PENDING = {"active": False}


def _fetch_view_b64(meta):
    """Fetch one preview image from local ComfyUI /view and return it base64."""
    try:
        q = urllib.parse.urlencode({"filename": meta.get("filename", ""),
                                    "subfolder": meta.get("subfolder", ""),
                                    "type": meta.get("type", "temp")})
        with urllib.request.urlopen(f"{COMFY_URL}/view?{q}", timeout=20) as r:
            return base64.b64encode(r.read()).decode()
    except Exception as e:
        print(f"[agent] interactive view fetch failed: {e}")
        return None


def _capture_interactive(data):
    """Handle an 'instaraw-interactive-images' WS payload: a popup request (has urls)
    or a timeout. Ticks are ignored."""
    if data.get("urls"):
        imgs = [b for b in (_fetch_view_b64(u) for u in data["urls"]) if b]
        PENDING.clear()
        PENDING.update(active=True, unique=str(data.get("unique")), uid=str(data.get("uid")),
                       maskedit=bool(data.get("maskedit")), allsame=bool(data.get("allsame")),
                       tip=data.get("tip", ""), images=imgs)
        print(f"[agent] popup captured: {'mask' if PENDING['maskedit'] else 'picker'} "
              f"unique={PENDING['unique']} previews={len(imgs)}")
    elif data.get("timeout"):
        PENDING.update(active=False)


def _ws_loop():
    try:
        import websocket  # websocket-client
    except Exception:
        return
    url = COMFY_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={CLIENT_ID}"
    while True:
        try:
            conn = websocket.create_connection(url, timeout=40)
            while True:
                m = conn.recv()
                if not isinstance(m, str):
                    continue
                d = json.loads(m)
                t, data = d.get("type"), d.get("data", {})
                if t == "progress":
                    PROGRESS.update(running=True, value=data.get("value", 0), max=data.get("max", 0))
                elif t == "execution_start":
                    PROGRESS.update(running=True, value=0, max=0)
                elif t == "executing" and data.get("node") is None:
                    PROGRESS.update(running=False, value=0, max=0)
                elif t == "instaraw-interactive-images" and isinstance(data, dict):
                    if data.get("tick") is None:   # don't spam the 0.5s countdown ticks
                        print(f"[agent] WS instaraw-interactive-images: keys={list(data.keys())} "
                              f"uid={data.get('uid')!r} unique={data.get('unique')!r} "
                              f"maskedit={data.get('maskedit')} urls={data.get('urls')!r}")
                    _capture_interactive(data)
                elif t in ("execution_success", "execution_error", "execution_interrupted"):
                    PROGRESS.update(running=False, value=0, max=0)
                    PENDING.update(active=False)
        except Exception:
            PROGRESS.update(running=False)
            time.sleep(3)


threading.Thread(target=_ws_loop, daemon=True).start()


@app.get("/progress")
def progress():
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(PROGRESS)


@app.get("/interaction")
def interaction():
    """Return the pending interactive popup (image picker / mask editor), if any."""
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(PENDING if PENDING.get("active") else {"active": False})


@app.post("/interact")
def interact():
    """Relay the user's answer back to ComfyUI: {unique, selection|masked_data|special}."""
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(force=True, silent=True) or {}
    resp = {"unique": body.get("unique") or PENDING.get("unique")}
    for k in ("selection", "masked_data", "masked_image", "special", "extras"):
        if k in body:
            resp[k] = body[k]
    try:
        data = urllib.parse.urlencode({"response": json.dumps(resp)}).encode()
        req = urllib.request.Request(f"{COMFY_URL}/instaraw/interactive_message", data=data)
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        PENDING.update(active=False)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/batch_upload")
def batch_upload():
    """Relay an i2i source-image multipart upload to local ComfyUI's INSTARAW pool.
    The VPS can't reach comfy directly (Cloudflare Access bounces multipart uploads
    to a login page), so it forwards here and we POST to ComfyUI on localhost."""
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    import requests as _rq
    files = [("files", (f.filename, f.stream, f.mimetype)) for f in request.files.getlist("files")]
    try:
        r = _rq.post(f"{COMFY_URL}/instaraw/batch_upload", files=files or None,
                     data={"node_id": request.form.get("node_id", "atelier")}, timeout=120)
        return (r.content, r.status_code,
                {"Content-Type": r.headers.get("Content-Type", "application/json")})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502


@app.get("/status")
def status():
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"ok": True, "running": comfy_up()})


@app.post("/start")
def start():
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    if comfy_up():
        return jsonify({"ok": True, "already": True})
    bat = os.path.join(COMFY_DIR, COMFY_BAT)
    if not os.path.exists(bat):
        return jsonify({"error": f"launch script not found: {bat}"}), 500
    subprocess.Popen(["cmd", "/c", "start", "", COMFY_BAT], cwd=COMFY_DIR)
    return jsonify({"ok": True, "started": True})


@app.post("/stop")
def stop():
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    out = subprocess.run("netstat -ano", shell=True, capture_output=True, text=True).stdout
    pids = {ln.split()[-1] for ln in out.splitlines()
            if f":{COMFY_PORT}" in ln and "LISTENING" in ln}
    for pid in pids:
        subprocess.run(f"taskkill /F /PID {pid}", shell=True)
    return jsonify({"ok": True, "stopped": True, "killed": list(pids),
                    "message": "Stopped." if pids else "ComfyUI was not running."})


if __name__ == "__main__":
    if not SECRET:
        print("WARNING: AGENT_SECRET not set — all requests will be rejected.")
    app.run(host="127.0.0.1", port=8190)

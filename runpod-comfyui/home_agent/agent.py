"""
Home agent — a tiny always-on helper on the PC with the 5090.

The VPS-hosted studio can't launch programs on your home machine, so this agent
does it: it exposes start / stop / status for ComfyUI on localhost:8190, which
cloudflared publishes at https://agent.thecristinaadam.com (behind a secret).

Run via Start_Agent.bat (which sets AGENT_SECRET). Binds to 127.0.0.1 only —
the outside world reaches it solely through the Cloudflare tunnel + the secret.
"""

import json
import os
import subprocess
import threading
import time
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
                elif t in ("execution_success", "execution_error", "execution_interrupted"):
                    PROGRESS.update(running=False, value=0, max=0)
        except Exception:
            PROGRESS.update(running=False)
            time.sleep(3)


threading.Thread(target=_ws_loop, daemon=True).start()


@app.get("/progress")
def progress():
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(PROGRESS)


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

"""Single-job local video enhancement service for the Home Agent."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("ATELIER_ENHANCE_DATA", r"C:\AtelierStudio\enhance_jobs"))
RUNNER = Path(__file__).with_name("enhance_runner.py")
LOCK = threading.Lock()
JOBS: dict[str, dict] = {}
ACTIVE: dict[str, object | None] = {"process": None, "job": None}
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
ALLOWED_RIFE = {"rife47.pth", "rife49.pth", "rife417.pth", "rife426.pth",
                "sudo_rife4_269.662_testV1_scale1.pth"}


def _comfy_root() -> Path:
    return Path(os.environ.get("ATELIER_COMFY_ROOT", r"G:\ComfyUI_V82\ComfyUI"))


def _enhancer_root() -> Path:
    return Path(os.environ.get("ATELIER_ENHANCER_ROOT", r"C:\AtelierStudio\enhancer_runtime"))


def _runner_python() -> str:
    configured = os.environ.get("ATELIER_ENHANCER_PYTHON")
    if configured:
        return configured
    root = _enhancer_root() / "bin"
    candidates = sorted(root.glob("python-*-embed-amd64/python.exe")) if root.is_dir() else []
    return str(candidates[-1]) if candidates else sys.executable


def _models() -> list[str]:
    folder = _comfy_root() / "custom_nodes" / "ComfyUI-Frame-Interpolation" / "ckpts" / "rife"
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.glob("*.pth") if p.name in ALLOWED_RIFE)


def capabilities() -> dict:
    enhancer = _enhancer_root()
    models = _models()
    return {
        "online": os.name == "nt",
        "gpu": os.environ.get("ATELIER_GPU_LABEL", "NVIDIA RTX 5090"),
        "rife": {"available": bool(models), "models": models,
                 "default": "rife49.pth" if "rife49.pth" in models else (models[0] if models else None)},
        "dlssg": {"available": (enhancer / "src" / "frame_interpolation").is_dir(),
                  "note": "At least 640 pixels on the source short side"},
        "dlss": {"available": (enhancer / "src" / "neural_rendering").is_dir()},
        "rtx_vsr": {"available": (enhancer / "src" / "upscale" / "video").is_dir()},
        "busy": bool(ACTIVE["job"]),
    }


def validate_options(raw: dict) -> dict:
    interpolation = str(raw.get("interpolation", "off"))
    upscaler = str(raw.get("upscaler", "off"))
    if interpolation not in {"off", "rife", "dlssg"}:
        raise ValueError("Unknown interpolation engine")
    if upscaler not in {"off", "dlss", "rtx_vsr"}:
        raise ValueError("Unknown upscale engine")
    model = str(raw.get("rife_model", "rife49.pth"))
    if model not in ALLOWED_RIFE:
        raise ValueError("Unknown RIFE model")
    multiplier = int(raw.get("multiplier", 2))
    fps, scale, quality = str(raw.get("fps", "60")), float(raw.get("scale", 2)), int(raw.get("quality", 3))
    if multiplier not in {2, 4} or fps not in {"50", "60"} or scale not in {1, 1.5, 2, 3, 4} or quality not in {1, 2, 3, 4}:
        raise ValueError("Unsupported enhancement setting")
    if interpolation == "off" and upscaler == "off":
        raise ValueError("Enable interpolation or upscaling")
    return {"interpolation": interpolation, "upscaler": upscaler, "rife_model": model,
            "multiplier": multiplier, "fps": fps, "scale": scale, "quality": quality}


def create_job(upload, options: dict) -> dict:
    with LOCK:
        if ACTIVE["job"]:
            raise RuntimeError("Local GPU is busy with another enhancement")
        available = capabilities()
        for engine in (options["interpolation"], options["upscaler"]):
            if engine != "off" and not available[engine]["available"]:
                raise ValueError(f"{engine} is not available on this Home Agent")
        if options["interpolation"] == "rife" and options["rife_model"] not in _models():
            raise ValueError("Selected RIFE checkpoint is not installed")
        suffix = Path(upload.filename or "video.mp4").suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise ValueError("Unsupported video format")
        job_id = uuid.uuid4().hex
        folder = ROOT / job_id
        folder.mkdir(parents=True, exist_ok=False)
        source = folder / ("source" + suffix)
        upload.save(source)
        job = {"id": job_id, "status": "queued", "progress": 0.0, "message": "Queued",
               "created": time.time(), "options": options, "source": str(source), "result": None,
               "error": None}
        JOBS[job_id] = job
        ACTIVE["job"] = job_id
        threading.Thread(target=_run, args=(job,), daemon=True).start()
        return public_job(job)


def _run(job: dict) -> None:
    folder = Path(job["source"]).parent
    opts = job["options"]
    cmd = [_runner_python(), str(RUNNER), "--input", job["source"], "--output-dir", str(folder),
           "--interpolation", opts["interpolation"], "--rife-model", opts["rife_model"],
           "--multiplier", str(opts["multiplier"]), "--fps", opts["fps"],
           "--upscaler", opts["upscaler"], "--scale", str(opts["scale"]),
           "--quality", str(opts["quality"])]
    try:
        if job["status"] == "cancelled":
            return
        job.update(status="running", message="Starting local GPU", progress=.01)
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        with LOCK:
            ACTIVE["process"] = process
        assert process.stdout
        recent_lines = []
        second_stage = False
        two_stages = opts["interpolation"] != "off" and opts["upscaler"] != "off"
        for line in process.stdout:
            recent_lines.append(line.strip())
            recent_lines = recent_lines[-12:]
            try:
                event = json.loads(line)
            except Exception:
                continue
            if "result" in event:
                job["result"] = event["result"]
            if str(event.get("message", "")).startswith(("Starting RTX VSR", "Starting DLSS enhancement")):
                second_stage = True
            if "progress" in event:
                value = float(event["progress"])
                if two_stages and event.get("message") != "Complete":
                    value = (.5 + value * .5) if second_stage else (value * .5)
                job["progress"] = max(job["progress"], min(1.0, value))
            if event.get("message"):
                job["message"] = str(event["message"])
        code = process.wait()
        if job["status"] == "cancelled":
            return
        result = Path(job["result"] or "")
        if code or not result.is_file() or result.parent != folder:
            raise RuntimeError("Enhancement processor failed: " + " | ".join(recent_lines[-5:])[-1200:])
        job.update(status="done", progress=1.0, message="Complete")
    except Exception as exc:
        job.update(status="failed", error=str(exc), message="Enhancement failed")
    finally:
        with LOCK:
            ACTIVE["process"] = None
            ACTIVE["job"] = None


def public_job(job: dict) -> dict:
    return {k: job.get(k) for k in ("id", "status", "progress", "message", "created", "options", "error")}


def get_job(job_id: str) -> dict | None:
    return JOBS.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = JOBS.get(job_id)
    if not job or job["status"] not in {"queued", "running"}:
        return False
    process = ACTIVE["process"]
    if process and process.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    job.update(status="cancelled", message="Cancelled", error=None)
    return True

"""Single-job local video enhancement service for the Home Agent."""
from __future__ import annotations

import json
import math
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
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".tif", ".tiff"}
ALLOWED_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS
ALLOWED_RIFE = {"rife47.pth", "rife49.pth", "rife417.pth", "rife426.pth",
                "sudo_rife4_269.662_testV1_scale1.pth"}
NR_STYLES = {"Default", "Natural", "Cinematic"}
DLSS_SCALES = {0.25, 0.5, 0.75, 1.0}
MULTIPASS_LIMITS = {
    2: (0.70, 1.00, 0.35),
    3: (0.55, 0.90, 0.50),
    4: (0.45, 0.80, 0.60),
}


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


def _number(raw: dict, name: str, default: float, minimum: float, maximum: float) -> float:
    value = raw.get(name, default)
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name}") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"Invalid {name}")
    return number


def _integer(raw: dict, name: str, default: int, minimum: int, maximum: int) -> int:
    value = raw.get(name, default)
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name}") from exc
    if number != value and str(number) != str(value):
        raise ValueError(f"Invalid {name}")
    if not minimum <= number <= maximum:
        raise ValueError(f"Invalid {name}")
    return number


def media_kind(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    raise ValueError("Unsupported media format")


def validate_options(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Enhancement options must be an object")
    interpolation = str(raw.get("interpolation", "off"))
    if interpolation not in {"off", "rife", "dlssg"}:
        raise ValueError("Unknown interpolation engine")
    legacy_upscaler = str(raw.get("upscaler", "off"))
    if legacy_upscaler not in {"off", "dlss", "rtx_vsr"}:
        raise ValueError("Unknown upscale engine")
    if "dlss_enabled" in raw or "rtx_vsr_enabled" in raw:
        dlss_enabled = raw.get("dlss_enabled", False)
        rtx_vsr_enabled = raw.get("rtx_vsr_enabled", False)
        if not isinstance(dlss_enabled, bool) or not isinstance(rtx_vsr_enabled, bool):
            raise ValueError("Invalid enhancement stage toggle")
    else:
        dlss_enabled = legacy_upscaler == "dlss"
        rtx_vsr_enabled = legacy_upscaler == "rtx_vsr"
    model = str(raw.get("rife_model", "rife49.pth"))
    if model not in ALLOWED_RIFE:
        raise ValueError("Unknown RIFE model")
    multiplier = int(raw.get("multiplier", 2))
    fps, scale, quality = str(raw.get("fps", "60")), float(raw.get("scale", 2)), int(raw.get("quality", 3))
    if multiplier not in {2, 4} or fps not in {"50", "60"} or scale not in {1, 1.5, 2, 3, 4} or quality not in {1, 2, 3, 4}:
        raise ValueError("Unsupported enhancement setting")
    if interpolation == "off" and not dlss_enabled and not rtx_vsr_enabled:
        raise ValueError("Enable interpolation or upscaling")
    nr_style = str(raw.get("nr_style", "Default"))
    if nr_style not in NR_STYLES:
        raise ValueError("Unknown DLSS5 style")
    nr_passes = _integer(raw, "nr_passes", 1, 1, 4)
    mask_feather = _integer(raw, "mask_feather", 0, 0, 128)
    automatic_mask = raw.get("automatic_mask", False)
    if not isinstance(automatic_mask, bool):
        raise ValueError("Invalid automatic_mask")
    multipass_protection = raw.get("multipass_protection", True)
    if not isinstance(multipass_protection, bool):
        raise ValueError("Invalid multipass_protection")
    dlss_scale = _number(raw, "dlss_scale", 1.0, 0.25, 1.0)
    if dlss_scale not in DLSS_SCALES:
        raise ValueError("Unsupported DLSS5 output scale")
    options = {
        "interpolation": interpolation,
        "dlss_enabled": dlss_enabled, "rtx_vsr_enabled": rtx_vsr_enabled,
        "upscaler": ("both" if dlss_enabled and rtx_vsr_enabled else
                     "dlss" if dlss_enabled else "rtx_vsr" if rtx_vsr_enabled else "off"),
        "rife_model": model, "multiplier": multiplier, "fps": fps,
        "scale": scale, "quality": quality, "nr_passes": nr_passes,
        "multipass_protection": multipass_protection,
        "nr_style": nr_style,
        "nr_intensity": _number(raw, "nr_intensity", 1.0, 0.0, 2.0),
        "local_tone_strength": _number(raw, "local_tone_strength", 1.0, 0.0, 2.0),
        "local_structure_strength": _number(raw, "local_structure_strength", 1.5, 0.0, 2.0),
        "skin_structure_strength": _number(raw, "skin_structure_strength", -1.0, -1.0, 2.0),
        "automatic_mask": automatic_mask,
        "nr_color_strength": _number(raw, "nr_color_strength", 1.0, 0.0, 1.0),
        "tone_preservation": _number(raw, "tone_preservation", 0.0, 0.0, 1.0),
        "face_skin_protection": _number(raw, "face_skin_protection", 0.0, 0.0, 1.0),
        "grain_preservation": _number(raw, "grain_preservation", 0.0, 0.0, 1.0),
        "mask_feather": mask_feather, "dlss_scale": dlss_scale,
    }
    return apply_multipass_protection(options)


def apply_multipass_protection(options: dict) -> dict:
    """Add the effective shared settings sent to the native multipass cascade."""
    protected = dict(options)
    intensity = float(options["nr_intensity"])
    structure = float(options["local_structure_strength"])
    face = float(options["face_skin_protection"])
    if options.get("multipass_protection") and int(options["nr_passes"]) > 1:
        intensity_cap, structure_cap, face_floor = MULTIPASS_LIMITS[int(options["nr_passes"])]
        intensity = min(intensity, intensity_cap)
        structure = min(structure, structure_cap)
        face = max(face, face_floor)
    protected.update(
        effective_nr_intensity=intensity,
        effective_local_structure_strength=structure,
        effective_face_skin_protection=face,
    )
    return protected


def validate_media_options(kind: str, options: dict) -> None:
    if kind == "image" and options["interpolation"] != "off":
        raise ValueError("Frame interpolation is available only for videos")
    if kind == "image" and options["rtx_vsr_enabled"]:
        raise ValueError("RTX Super Resolution is available only for videos")
    if kind == "image" and not options["dlss_enabled"]:
        raise ValueError("Images currently require DLSS5 Neural Rendering")


def create_job(upload, options: dict) -> dict:
    with LOCK:
        if ACTIVE["job"]:
            raise RuntimeError("Local GPU is busy with another enhancement")
        available = capabilities()
        engines = [options["interpolation"]]
        if options["dlss_enabled"]:
            engines.append("dlss")
        if options["rtx_vsr_enabled"]:
            engines.append("rtx_vsr")
        for engine in engines:
            if engine != "off" and not available[engine]["available"]:
                raise ValueError(f"{engine} is not available on this Home Agent")
        if options["interpolation"] == "rife" and options["rife_model"] not in _models():
            raise ValueError("Selected RIFE checkpoint is not installed")
        kind = media_kind(upload.filename or "")
        validate_media_options(kind, options)
        suffix = Path(upload.filename or "media").suffix.lower()
        job_id = uuid.uuid4().hex
        folder = ROOT / job_id
        folder.mkdir(parents=True, exist_ok=False)
        source = folder / ("source" + suffix)
        upload.save(source)
        options = {**options, "media_kind": kind}
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
           "--media-kind", opts["media_kind"],
           "--interpolation", opts["interpolation"], "--rife-model", opts["rife_model"],
           "--multiplier", str(opts["multiplier"]), "--fps", opts["fps"],
           "--dlss-enabled", "1" if opts["dlss_enabled"] else "0",
           "--rtx-vsr-enabled", "1" if opts["rtx_vsr_enabled"] else "0",
           "--scale", str(opts["scale"]),
           "--quality", str(opts["quality"]), "--nr-passes", str(opts["nr_passes"]),
           "--nr-style", opts["nr_style"],
           "--nr-intensity", str(opts["effective_nr_intensity"]),
           "--local-tone-strength", str(opts["local_tone_strength"]),
           "--local-structure-strength", str(opts["effective_local_structure_strength"]),
           "--skin-structure-strength", str(opts["skin_structure_strength"]),
           "--automatic-mask", "1" if opts["automatic_mask"] else "0",
           "--nr-color-strength", str(opts["nr_color_strength"]),
           "--tone-preservation", str(opts["tone_preservation"]),
           "--face-skin-protection", str(opts["effective_face_skin_protection"]),
           "--grain-preservation", str(opts["grain_preservation"]),
           "--mask-feather", str(opts["mask_feather"]),
           "--dlss-scale", str(opts["dlss_scale"])]
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
        stage_count = (int(opts["interpolation"] != "off") + int(opts["dlss_enabled"]) +
                       int(opts["rtx_vsr_enabled"]))
        stage_index = -1
        last_stage = ""
        for line in process.stdout:
            recent_lines.append(line.strip())
            recent_lines = recent_lines[-12:]
            try:
                event = json.loads(line)
            except Exception:
                continue
            if "result" in event:
                job["result"] = event["result"]
            message = str(event.get("message", ""))
            if message.startswith(("Starting RIFE", "Starting DLSSG", "Starting DLSS5", "Starting RTX VSR")):
                if message != last_stage:
                    stage_index += 1
                    last_stage = message
            if "progress" in event:
                value = float(event["progress"])
                if stage_count > 1 and message != "Complete":
                    value = (max(0, stage_index) + value) / stage_count
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
        error = str(exc)
        for private in (str(folder), str(_enhancer_root()), str(_comfy_root())):
            error = error.replace(private, "[local runtime]")
        job.update(status="failed", error=error[-1600:], message="Enhancement failed")
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
    source = Path(job["source"])
    for path in source.parent.iterdir():
        if path != source and path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
    return True

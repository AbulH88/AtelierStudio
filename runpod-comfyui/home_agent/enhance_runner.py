"""Isolated local-GPU runner used by the Atelier Home Agent.

This process deliberately imports the copied DLSS Visual Enhancer runtime only
after argument validation.  Keeping native NVIDIA DLLs out of the long-running
Flask process makes crashes recoverable and cancellation reliable.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def progress(value: float, message: str) -> None:
    print(json.dumps({"progress": max(0, min(1, float(value))), "message": message}), flush=True)


def enhancer_root() -> Path:
    root = Path(os.environ.get("ATELIER_ENHANCER_ROOT", r"C:\AtelierStudio\enhancer_runtime"))
    if not (root / "src").is_dir():
        raise RuntimeError(f"Enhancer runtime is not installed: {root}")
    sys.path.insert(0, str(root))
    return root


def run_dlssg(source: Path, output_dir: Path, fps: str) -> Path:
    root = enhancer_root()
    import subprocess
    ffprobe = root / "bin" / "ffmpeg" / "bin" / "ffprobe.exe"
    probe = subprocess.run([str(ffprobe), "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "json", str(source)],
                           capture_output=True, text=True, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    if min(int(stream["width"]), int(stream["height"])) < 640:
        raise ValueError("Native DLSSG needs a video at least 640 px on its short side; use RIFE for smaller clips")
    from src.frame_interpolation.models import FrameInterpolationOptions
    from src.frame_interpolation.processor import interpolate_video

    options = FrameInterpolationOptions(
        target_fps=fps, engine="Auto", codec="H.264 (NVIDIA NVENC)",
        container="MP4", quality="Auto (Default)", rename_mode="Custom",
        custom_suffix="_DLSSG",
    )
    result = interpolate_video(source, options, progress=progress, output_dir=output_dir)
    return Path(result.output_path)


def run_rtx_vsr(source: Path, output_dir: Path, scale: float, quality: int) -> Path:
    enhancer_root()
    from src.upscale.video.models import UpscaleOptions
    from src.upscale.video.processor import upscale_video

    options = UpscaleOptions(
        vsr_enabled=True, vsr_quality=quality, size_mode="Scale factor",
        scale_factor=scale, codec="H.264 (NVIDIA NVENC)", container="MP4",
        quality="Auto (Default)", rename_mode="Custom", custom_suffix="_RTX_VSR",
    )
    result = upscale_video(source, options, progress=progress, output_dir=output_dir)
    return Path(result.output_path)


def _neural_kwargs(args: argparse.Namespace) -> dict:
    return {
        "nr_style": args.nr_style,
        "nr_intensity": args.nr_intensity,
        "nr_passes": args.nr_passes,
        "local_tone_strength": args.local_tone_strength,
        "local_structure_strength": args.local_structure_strength,
        "skin_structure_strength": args.skin_structure_strength,
        "nr_color_strength": args.nr_color_strength,
        "tone_preservation": args.tone_preservation,
        "face_skin_protection": args.face_skin_protection,
        "grain_preservation": args.grain_preservation,
        "mask_feather": args.mask_feather,
        "automatic_mask": bool(args.automatic_mask),
        "upscaling_factor": args.dlss_scale,
    }


def _require_feature_evidence(result, requested_passes: int) -> None:
    status = getattr(result, "bridge_status", None) or {}
    try:
        applied_passes = int(status.get("nr_passes", 0))
        evaluations = int(status.get("feature_evaluations", 0))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("DLSS5 returned malformed feature-18 diagnostics") from exc
    if applied_passes != requested_passes or evaluations < requested_passes:
        raise RuntimeError(
            "DLSS5 completed without verified feature-18 multipass evidence "
            f"(requested {requested_passes}, applied {applied_passes}, evaluations {evaluations})"
        )
    count = getattr(result, "nr_count_evidence", None)
    if count is not None and int(count) < 1:
        raise RuntimeError("DLSS5 returned no feature-18 frame evidence")


def run_dlss_video(source: Path, output_dir: Path, args: argparse.Namespace) -> Path:
    enhancer_root()
    from src.neural_rendering.video.batch import convert_videos
    from src.neural_rendering.video.models import ConversionOptions

    options = ConversionOptions(
        **_neural_kwargs(args),
        codec="H.264 (NVIDIA NVENC)", container="MP4",
        quality="Auto (Default)", rename_mode="Custom", custom_suffix="_DLSS",
    )
    result = convert_videos([str(source)], options, progress=progress, output_dir=output_dir)
    if not result.successes:
        detail = result.failures[0].error if result.failures else "DLSS produced no output"
        raise RuntimeError(detail)
    converted = result.successes[0].result
    _require_feature_evidence(converted, args.nr_passes)
    return Path(converted.output_path)


def run_dlss_image(source: Path, output_dir: Path, args: argparse.Namespace) -> Path:
    enhancer_root()
    from src.neural_rendering.image.batch import convert_images
    from src.neural_rendering.image.models import ImageConversionOptions

    options = ImageConversionOptions(
        **_neural_kwargs(args), output_format="PNG", quality=95,
        preserve_metadata=True, rename_mode="Custom", custom_suffix="_DLSS5",
    )
    result = convert_images(
        [str(source)], options, progress=progress, output_dir=output_dir,
        generate_previews=False, create_zip=False,
    )
    if not result.successes:
        detail = result.failures[0].error if result.failures else "DLSS5 produced no output"
        raise RuntimeError(detail)
    converted = result.successes[0]
    _require_feature_evidence(converted, args.nr_passes)
    return Path(converted.output_path)


def run_rife(source: Path, output_dir: Path, model: str, multiplier: int) -> Path:
    """Run the installed ComfyUI RIFE implementation without starting ComfyUI."""
    comfy = Path(os.environ.get("ATELIER_COMFY_ROOT", r"G:\ComfyUI_V82\ComfyUI"))
    node_root = comfy / "custom_nodes" / "ComfyUI-Frame-Interpolation"
    model_path = node_root / "ckpts" / "rife" / model
    if not node_root.is_dir() or not model_path.is_file():
        raise RuntimeError(f"RIFE model/runtime unavailable: {model}")
    # A dedicated helper owns frame decoding/encoding because the Comfy node API
    # accepts image tensors, not video files. It runs under the Comfy Python but
    # does not start the ComfyUI server.
    helper = Path(__file__).with_name("rife_video.py")
    python = Path(os.environ.get("ATELIER_COMFY_PYTHON", str(comfy / "venv" / "Scripts" / "python.exe")))
    if not python.is_file():
        python = Path(sys.executable)
    target = output_dir / f"{source.stem}_RIFE_{multiplier}x.mp4"
    import subprocess
    cmd = [str(python), str(helper), "--comfy", str(comfy), "--input", str(source),
           "--output", str(target), "--model", model, "--multiplier", str(multiplier)]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
    assert process.stdout
    for line in process.stdout:
        print(line.rstrip(), flush=True)
    if process.wait() or not target.is_file():
        raise RuntimeError("Standalone RIFE failed")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--media-kind", choices=("image", "video"), default="video")
    parser.add_argument("--interpolation", choices=("off", "rife", "dlssg"), default="off")
    parser.add_argument("--rife-model", default="rife49.pth")
    parser.add_argument("--multiplier", type=int, choices=(2, 4), default=2)
    parser.add_argument("--fps", choices=("50", "60"), default="60")
    parser.add_argument("--dlss-enabled", type=int, choices=(0, 1), default=0)
    parser.add_argument("--rtx-vsr-enabled", type=int, choices=(0, 1), default=0)
    parser.add_argument("--scale", type=float, choices=(1.0, 1.5, 2.0, 3.0, 4.0), default=2.0)
    parser.add_argument("--quality", type=int, choices=(1, 2, 3, 4), default=3)
    parser.add_argument("--nr-passes", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--nr-style", choices=("Default", "Natural", "Cinematic"), default="Default")
    parser.add_argument("--nr-intensity", type=float, default=1.0)
    parser.add_argument("--local-tone-strength", type=float, default=1.0)
    parser.add_argument("--local-structure-strength", type=float, default=1.5)
    parser.add_argument("--skin-structure-strength", type=float, default=-1.0)
    parser.add_argument("--automatic-mask", type=int, choices=(0, 1), default=0)
    parser.add_argument("--nr-color-strength", type=float, default=1.0)
    parser.add_argument("--tone-preservation", type=float, default=0.0)
    parser.add_argument("--face-skin-protection", type=float, default=0.0)
    parser.add_argument("--grain-preservation", type=float, default=0.0)
    parser.add_argument("--mask-feather", type=int, default=0)
    parser.add_argument("--dlss-scale", type=float, choices=(0.25, 0.5, 0.75, 1.0), default=1.0)
    args = parser.parse_args()
    source, output_dir = Path(args.input).resolve(), Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    current = source
    if args.media_kind == "image" and args.interpolation != "off":
        raise ValueError("Frame interpolation is available only for videos")
    if args.media_kind == "image" and args.rtx_vsr_enabled:
        raise ValueError("RTX Super Resolution is available only for videos")
    if args.media_kind == "image" and not args.dlss_enabled:
        raise ValueError("Images currently require DLSS5 Neural Rendering")
    if args.interpolation == "rife":
        progress(.01, "Starting RIFE")
        current = run_rife(current, output_dir, args.rife_model, args.multiplier)
    elif args.interpolation == "dlssg":
        progress(.01, "Starting DLSSG")
        current = run_dlssg(current, output_dir, args.fps)
    if args.dlss_enabled:
        progress(.01, f"Starting DLSS5 ({args.nr_passes} neural passes)")
        current = (run_dlss_image if args.media_kind == "image" else run_dlss_video)(
            current, output_dir, args
        )
    if args.rtx_vsr_enabled:
        progress(.01, "Starting RTX VSR")
        current = run_rtx_vsr(current, output_dir, args.scale, args.quality)
    if current == source:
        target = output_dir / f"{source.stem}_enhanced{source.suffix}"
        shutil.copy2(source, target)
        current = target
    progress(1, "Complete")
    print(json.dumps({"result": str(current)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

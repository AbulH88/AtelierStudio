"""Standalone video bridge for ComfyUI-Frame-Interpolation's RIFE models.

The ComfyUI server is not started. We reuse the installed MIT-licensed model
implementation and the Comfy Python environment, decode frames with OpenCV,
then stream the interpolated frames to ffmpeg and remux the original audio.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _ffmpeg(comfy: Path) -> str:
    configured = os.environ.get("ATELIER_FFMPEG", "")
    candidates = [configured, str(Path(os.environ.get("ATELIER_ENHANCER_ROOT", r"C:\AtelierStudio\enhancer_runtime")) / "bin" / "ffmpeg" / "bin" / "ffmpeg.exe"), shutil.which("ffmpeg"),
                  str(comfy.parent / "ffmpeg" / "bin" / "ffmpeg.exe")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("ffmpeg was not found; set ATELIER_FFMPEG")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--multiplier", type=int, choices=(2, 4), default=2)
    args = parser.parse_args()

    comfy = Path(args.comfy).resolve()
    source, target = Path(args.input).resolve(), Path(args.output).resolve()
    node_root = comfy / "custom_nodes" / "ComfyUI-Frame-Interpolation"
    sys.path[:0] = [str(comfy), str(node_root)]

    import cv2
    import numpy as np
    import torch
    from vfi_models.rife import RIFE_VFI, CKPT_NAME_VER_DICT

    if args.model not in CKPT_NAME_VER_DICT:
        raise ValueError(f"Unsupported RIFE model: {args.model}")
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot decode {source.name}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 24.0)
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if len(frames) % 24 == 0:
            print(f'{{"message":"Decoding frames","frames":{len(frames)}}}', flush=True)
    capture.release()
    if len(frames) < 2:
        raise RuntimeError("RIFE requires at least two decoded frames")

    tensor = torch.from_numpy(np.stack(frames)).float().div_(255.0)
    del frames
    result = RIFE_VFI().vfi(
        args.model, tensor, clear_cache_after_n_frames=10,
        multiplier=args.multiplier, fast_mode=True, ensemble=True,
        scale_factor=1.0, dtype="float16", torch_compile=False,
        batch_size=1,
    )[0]
    count, height, width, _ = result.shape
    output_fps = fps * args.multiplier
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg(comfy)
    with tempfile.TemporaryDirectory(prefix="atelier-rife-") as temp:
        silent = Path(temp) / "silent.mp4"
        encode = subprocess.Popen([
            ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}", "-r", f"{output_fps:.8f}", "-i", "-",
            "-an", "-c:v", "h264_nvenc", "-preset", "p6", "-cq", "18",
            "-pix_fmt", "yuv420p", str(silent),
        ], stdin=subprocess.PIPE)
        assert encode.stdin
        for index in range(count):
            pixels = result[index].clamp(0, 1).mul(255).byte().numpy()
            encode.stdin.write(pixels.tobytes())
            if index % 24 == 0:
                print(f'{{"progress":{index / count:.6f},"message":"Encoding RIFE"}}', flush=True)
        encode.stdin.close()
        if encode.wait() != 0:
            raise RuntimeError("RIFE NVENC export failed")
        mux = subprocess.run([
            ffmpeg, "-y", "-i", str(silent), "-i", str(source),
            "-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", "-c:a", "aac",
            "-shortest", str(target),
        ], capture_output=True, text=True)
        if mux.returncode:
            raise RuntimeError("RIFE audio mux failed: " + mux.stderr[-1200:])
    print(f'{{"progress":1,"message":"RIFE complete","frames":{count}}}', flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

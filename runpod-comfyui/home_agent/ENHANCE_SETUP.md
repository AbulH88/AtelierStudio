# Atelier Enhance on the local GPU

The Studio Enhance page uses the Home Agent, not RunningHub. The copied
DLSS Visual Enhancer runtime is installed separately and never committed to
the repository. Run `Install_Enhancer_Runtime.ps1` on the Windows GPU PC;
the tested source package is under the user's Desktop and the default target
is `C:\AtelierStudio\enhancer_runtime`. Its original MIT license is copied
alongside the code. The native NVIDIA runtime keeps its bundled notices.

RIFE reuses the existing `G:\ComfyUI_V82\ComfyUI\custom_nodes\ComfyUI-Frame-Interpolation`
code and `ckpts\rife\*.pth` models through the Comfy virtual environment.
ComfyUI itself does not need to be running for RIFE. Only models physically
present in that directory appear in the selector.

Optional overrides for the Home Agent process:

- `ATELIER_ENHANCER_ROOT` — copied runtime directory.
- `ATELIER_ENHANCER_PYTHON` — copied embedded Python executable.
- `ATELIER_COMFY_ROOT` — existing ComfyUI directory.
- `ATELIER_COMFY_PYTHON` — Comfy virtual environment Python executable.
- `ATELIER_ENHANCE_DATA` — scratch directory for job inputs and results.
- `ATELIER_FFMPEG` — ffmpeg executable for standalone RIFE.

Restart the Home Agent after updating these files. The Studio VPS deployment
ships `webapp/app.py` and `webapp/index.html` through the existing deploy
workflow. Keep `AGENT_SECRET` private; browser clients never receive it.

DLSS neural rendering in this package is a source-resolution detail pass,
not a 2× scaler. RTX VSR is the actual 1–4× upscale choice. RIFE is
standalone interpolation and DLSSG is native NVIDIA frame generation. A
single local job runs at a time; the user's finished video remains on the
Home Agent until manually cleaned up.

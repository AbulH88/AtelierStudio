"""Populate the 50 GB motion volume (atelier-motion) for the Wan Animate workflow.
Runs on a RunPod pod with the volume mounted at /workspace.

Sources:
  - Base models: PUBLIC HF (verified paths) -> Animate fp8, umt5-fp8, clip_vision_h, vae.
  - LoRAs (5 motion + 6 own character) + detection ONNX/bin: PRIVATE repo orthoraj21/atelier-loras
    (motion files uploaded by _upload_video.py; char LoRAs already there).
  - DWPose (yolox_l, dw-ll_ucoco) + RIFE (flownet.pkl): NOT placed here — controlnet_aux and
    ComfyUI-Frame-Interpolation auto-download them at runtime (~350 MB, once per fresh worker).
    They were also uploaded to the private repo under dwpose/ and rife/ as insurance.

Env: HF_TOKEN (read access to the private repo). HF_HUB_ENABLE_HF_TRANSFER=1 for speed.
"""
import os, json, time, shutil
from huggingface_hub import hf_hub_download, list_repo_files, HfApi

MODELS = "/workspace/models"
STAGE = "/workspace/.stage"
TOK = os.environ.get("HF_TOKEN")
LORA_REPO = "orthoraj21/atelier-loras"
os.makedirs(MODELS, exist_ok=True)
os.makedirs(STAGE, exist_ok=True)

# (public repo, file in repo, target under models/)
BASE = [
    ("Kijai/WanVideo_comfy_fp8_scaled",
     "Wan22Animate/Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors",
     "diffusion_models/WAN/Kijai Collection/Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors"),
    ("Comfy-Org/Wan_2.1_ComfyUI_repackaged",
     "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
     "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    ("Comfy-Org/Wan_2.1_ComfyUI_repackaged",
     "split_files/clip_vision/clip_vision_h.safetensors",
     "clip_vision/clip_vision_h.safetensors"),
    ("Comfy-Org/Wan_2.1_ComfyUI_repackaged",
     "split_files/vae/wan_2.1_vae.safetensors",
     "vae/wan_2.1_vae.safetensors"),
]

results = []


def grab(repo, fn, target, token=None):
    dst = os.path.join(MODELS, target)
    if os.path.exists(dst) and os.path.getsize(dst) > 100_000:
        results.append({"target": target, "size": os.path.getsize(dst), "ok": True, "skip": True})
        print("SKIP (exists)", target, flush=True)
        return
    try:
        local = hf_hub_download(repo_id=repo, filename=fn, local_dir=STAGE, token=token)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(local, dst)  # same filesystem -> instant move
        sz = os.path.getsize(dst)
        results.append({"target": target, "size": sz, "ok": True})
        print(f"OK {target}  ({sz/1e9:.2f} GB)", flush=True)
    except Exception as e:
        results.append({"target": target, "ok": False, "error": str(e)[:200]})
        print("FAIL", target, repr(e)[:200], flush=True)


def hardlink(target, alt):
    src = os.path.join(MODELS, target)
    dst = os.path.join(MODELS, alt)
    if not os.path.exists(src) or os.path.exists(dst):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.link(src, dst)
    except Exception:
        shutil.copy(src, dst)


# 1) public base models
for repo, fn, target in BASE:
    grab(repo, fn, target)

# CLIPLoader resolves "text_encoders" (and "clip"); hardlink so either convention finds umt5.
hardlink("text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
         "clip/umt5_xxl_fp8_e4m3fn_scaled.safetensors")

# 2) private repo: LoRAs + detection models.
#    - motion LoRAs are stored as  loras/wan/WanLightning/...  (from _upload_video.py)
#    - character LoRAs are stored as  wan/Own/...  (from the older _upload_loras.py, no prefix)
#    Both must land at models/loras/<rel>. Skip the old image lightning LoRAs (wan/WanLightning/*)
#    — the motion workflow brings its own lightning stack.
for f in list_repo_files(LORA_REPO, token=TOK):
    if f.endswith(".safetensors") and f.startswith("loras/"):
        grab(LORA_REPO, f, f, token=TOK)                      # -> models/loras/<rel>
    elif f.endswith(".safetensors") and f.startswith("wan/Own/"):
        grab(LORA_REPO, f, "loras/" + f, token=TOK)           # char LoRA -> models/loras/wan/Own/<rel>
    elif f.startswith("detection/"):
        grab(LORA_REPO, f, "detection/" + os.path.basename(f), token=TOK)  # -> models/detection/<file>

shutil.rmtree(STAGE, ignore_errors=True)

manifest = {
    "done_at": int(time.time()),
    "loras": sorted(r["target"][len("loras/"):] for r in results if r["ok"] and r["target"].startswith("loras/")),
    "results": results,
    "all_ok": all(r["ok"] for r in results),
}
mp = os.path.join(MODELS, "_motion_manifest.json")
open(mp, "w").write(json.dumps(manifest, indent=2))
try:
    HfApi(token=TOK).upload_file(path_or_fileobj=mp, path_in_repo="_motion_manifest.json",
                                 repo_id=LORA_REPO, repo_type="model")
    print("MANIFEST UPLOADED  all_ok=", manifest["all_ok"], flush=True)
except Exception as e:
    print("manifest upload failed:", e, flush=True)

print("POPULATE MOTION DONE", flush=True)

"""Runs on a RunPod pod with the network volume mounted at /workspace.
Downloads the base models (public Comfy-Org repos) + the private character/lightning
LoRAs into ComfyUI's models/ tree, then uploads a manifest back to the private HF
repo so the orchestrator can confirm completion (no SSH needed).

Env: HF_TOKEN (read access to orthoraj21/atelier-loras). Enable hf_transfer via
HF_HUB_ENABLE_HF_TRANSFER=1 for fast downloads.
"""
import os, json, time, shutil
from huggingface_hub import hf_hub_download, list_repo_files, HfApi

MODELS = "/workspace/models"
STAGE = "/workspace/.stage"
TOK = os.environ.get("HF_TOKEN")
LORA_REPO = "orthoraj21/atelier-loras"
os.makedirs(MODELS, exist_ok=True)
os.makedirs(STAGE, exist_ok=True)

# (public repo, file in repo, target path under models/)
BASE = [
    ("Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
     "split_files/diffusion_models/wan2.2_t2v_low_noise_14B_fp16.safetensors",
     "diffusion_models/WAN/Wan2.2/Text/low_noise_model/wan2.2_t2v_low_noise_14B_fp16.safetensors"),
    ("Comfy-Org/Wan_2.1_ComfyUI_repackaged",
     "split_files/text_encoders/umt5_xxl_fp16.safetensors",
     "text_encoders/Wan/umt5_xxl_fp16.safetensors"),
    ("Kijai/WanVideo_comfy",
     "Wan2_1_VAE_fp32.safetensors",
     "vae/Wan/Wan2_1_VAE_fp32.safetensors"),
]

results = []


def grab(repo, fn, target, token=None):
    dst = os.path.join(MODELS, target)
    if os.path.exists(dst) and os.path.getsize(dst) > 1_000_000:
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


# base models
for repo, fn, target in BASE:
    grab(repo, fn, target)

# UNETLoader resolves "diffusion_models" (covers models/unet too); CLIPLoader
# resolves "text_encoders" (covers models/clip). Hardlink into the legacy dirs
# so either ComfyUI folder convention finds the files (zero extra disk).
hardlink("diffusion_models/WAN/Wan2.2/Text/low_noise_model/wan2.2_t2v_low_noise_14B_fp16.safetensors",
         "unet/WAN/Wan2.2/Text/low_noise_model/wan2.2_t2v_low_noise_14B_fp16.safetensors")
hardlink("text_encoders/Wan/umt5_xxl_fp16.safetensors", "clip/Wan/umt5_xxl_fp16.safetensors")

# private LoRAs -> models/loras/<same rel path>
for f in list_repo_files(LORA_REPO, token=TOK):
    if f.endswith(".safetensors"):
        grab(LORA_REPO, f, "loras/" + f, token=TOK)

shutil.rmtree(STAGE, ignore_errors=True)

manifest = {
    "done_at": int(time.time()),
    "loras": sorted(r["target"][len("loras/"):] for r in results if r["ok"] and r["target"].startswith("loras/")),
    "results": results,
    "all_ok": all(r["ok"] for r in results),
}
mp = os.path.join(MODELS, "_volume_manifest.json")
open(mp, "w").write(json.dumps(manifest, indent=2))
try:
    HfApi(token=TOK).upload_file(path_or_fileobj=mp, path_in_repo="_volume_manifest.json",
                                 repo_id=LORA_REPO, repo_type="model")
    print("MANIFEST UPLOADED  all_ok=", manifest["all_ok"], flush=True)
except Exception as e:
    print("manifest upload failed:", e, flush=True)

print("POPULATE DONE", flush=True)

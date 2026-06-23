"""One-shot cloud debug: runs the t2i workflow against the volume models on a pod,
captures the real ComfyUI node error + log tail, uploads to the private HF repo.
Fetched + run by a debug pod; reports to HF so no inbound pod access is needed."""
import os, time, json, sys, subprocess
import requests

sys.path.insert(0, "/")
COMFY = "http://127.0.0.1:8188"

# wait for ComfyUI to answer
up = False
for _ in range(150):
    try:
        if requests.get(COMFY + "/", timeout=3).status_code == 200:
            up = True; break
    except Exception:
        pass
    time.sleep(2)

out = {"comfy_up": up}
try:
    import comfy_common
    inp = {"mode": "t2i", "prompt": "a woman, editorial photo, soft light",
           "trigger": "ing2lorance",
           "character_lora_path": "wan/Own/LoranceNew/LoranceNew.safetensors", "character_strength": 0.8,
           "lightning": {"path": "wan/WanLightning/lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank128_bf16/lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank128_bf16.safetensors", "strength": 0.6},
           "width": 1080, "height": 1920, "steps": 8, "seed": 1, "variations": 1}
    r = comfy_common.generate(COMFY, "/", inp)
    out["result"] = {"keys": list(r.keys()), "n_images": len(r.get("images", [])), "error": r.get("error")}
except Exception as e:
    out["exception"] = f"{type(e).__name__}: {e}"

# what's actually on the volume + which custom nodes loaded
try:
    out["models_tree"] = subprocess.run(["bash", "-lc", "find /comfyui/models -maxdepth 5 -name '*.safetensors' | sort"],
                                        capture_output=True, text=True, timeout=30).stdout[:3000]
except Exception as e:
    out["models_tree_err"] = str(e)
try:
    out["comfy_log_tail"] = open("/comfyui.log").read()[-3500:]
except Exception:
    pass

from huggingface_hub import HfApi
open("/debug_result.json", "w").write(json.dumps(out, indent=2))
HfApi(token=os.environ["HF_TOKEN"]).upload_file(
    path_or_fileobj="/debug_result.json", path_in_repo="_debug_result.json",
    repo_id="orthoraj21/atelier-loras", repo_type="model")
print("DEBUG UPLOADED", flush=True)

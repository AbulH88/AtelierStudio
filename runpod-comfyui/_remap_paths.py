"""One-shot: remap stale model paths in workflow_adv.json to the actually-installed
files (the loras folder was reorganized after this workflow was exported)."""
import json, os, requests

BASE = "http://127.0.0.1:8189"
BS = chr(92)  # backslash, avoid literal-escape headaches


def norm(p):
    return p.replace(BS, "/")


def enum(cls, field):
    try:
        inp = requests.get(f"{BASE}/object_info/{cls}", timeout=10).json()[cls]["input"]
        for sec in ("required", "optional"):
            if field in inp.get(sec, {}):
                return inp[sec][field][0]
    except Exception as e:
        print("enum fail", cls, field, e)
    return []


LISTS = {
    "loras": enum("LoraLoader", "lora_name"),
    "unet": enum("UNETLoader", "unet_name"),
    "clip": enum("CLIPLoader", "clip_name"),
    "vae": enum("VAELoader", "vae_name"),
    "ckpt": enum("CheckpointLoaderSimple", "ckpt_name"),
    "upscale": enum("UpscaleModelLoader", "model_name"),
    "ultra": enum("UltralyticsDetectorProvider", "model_name"),
    "sam": enum("SAMLoader", "model_name"),
}


def bmap(lst):
    m = {}
    for p in lst:
        m.setdefault(os.path.basename(norm(p)).lower(), []).append(p)
    return m


BMAPS = {k: bmap(v) for k, v in LISTS.items()}

FIELD = {
    ("Lora Loader Stack (rgthree)", "lora_01"): "loras",
    ("Lora Loader Stack (rgthree)", "lora_02"): "loras",
    ("Lora Loader Stack (rgthree)", "lora_03"): "loras",
    ("Lora Loader Stack (rgthree)", "lora_04"): "loras",
    ("LoraLoader", "lora_name"): "loras",
    ("LoraLoaderModelOnly", "lora_name"): "loras",
    ("UNETLoader", "unet_name"): "unet",
    ("CLIPLoader", "clip_name"): "clip",
    ("VAELoader", "vae_name"): "vae",
    ("CheckpointLoaderSimple", "ckpt_name"): "ckpt",
    ("UpscaleModelLoader", "model_name"): "upscale",
    ("UltralyticsDetectorProvider", "model_name"): "ultra",
    ("SAMLoader", "model_name"): "sam",
}

g = json.load(open("workflow_adv.json", encoding="utf-8"))
changes, unresolved = [], []
for nid, n in g.items():
    cls = n.get("class_type")
    for f, v in list((n.get("inputs") or {}).items()):
        key = (cls, f)
        if key not in FIELD or not isinstance(v, str) or v in ("", "None"):
            continue
        lst = LISTS[FIELD[key]]
        if v in lst:
            continue
        cand = BMAPS[FIELD[key]].get(os.path.basename(norm(v)).lower(), [])
        if len(cand) == 1:
            n["inputs"][f] = cand[0]
            changes.append((nid, f, v, cand[0]))
        else:
            unresolved.append((nid, cls, f, v, len(cand)))

json.dump(g, open("workflow_adv.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"REMAPPED {len(changes)} path(s):")
for nid, f, old, new in changes:
    print(f"  {nid} {f}: {old}  ->  {new}")
print(f"\nUNRESOLVED {len(unresolved)}:")
for nid, cls, f, v, c in unresolved:
    print(f"  {nid} {cls}.{f} = {v}  ({c} matches)")

"""
Shared ComfyUI workflow logic used by BOTH:
  - handler.py        (cloud / RunPod serverless, talks to ComfyUI in the container)
  - webapp/app.py     (local mode, talks to your ComfyUI on 127.0.0.1:8188)

Everything is driven through ComfyUI's HTTP API (upload / prompt / history / view),
so it works the same whether ComfyUI is local or in the cloud.
"""

import base64
import io
import json
import os
import time
import uuid

import requests

# Cloudflare Access service-token headers (set on the VPS so it can reach the
# Access-protected ComfyUI tunnel; empty locally). Read from env at import.
CF_HEADERS = {}
if os.environ.get("CF_ACCESS_CLIENT_ID") and os.environ.get("CF_ACCESS_CLIENT_SECRET"):
    CF_HEADERS = {"CF-Access-Client-Id": os.environ["CF_ACCESS_CLIENT_ID"],
                  "CF-Access-Client-Secret": os.environ["CF_ACCESS_CLIENT_SECRET"]}

NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
            "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
            "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，"
            "杂乱的背景，三条腿，背景人很多，倒着走, censored, sunburnt skin, rashy skin, red cheeks")

FACE_PREFIX = "ing2lorance, "   # trigger word prepended to the description (i2i)

# Both workflows keep a LOCKED Lightning (lightx2v) LoRA baked in — i2i uses the
# 4-step rank64 @1.0, t2i the v2 distill rank128 @0.6 (do NOT change t2i: it must
# match wf2 exactly). User-chosen extra LoRAs are injected as a dynamic chain
# between that locked Lightning node (`lora_after`) and the character node (`char`),
# so any number of LoRAs from the wan/ folder can be stacked in either mode.
I2I = {"load_image": "1", "positive": "5", "negative": "6", "char": "13",
       "resize": "20", "noise_aug": "21", "repeat_latent": "23",
       "ksampler": "30", "lora_after": "11"}

T2I = {"positive": "5", "negative": "6", "char": "12",
       "latent": "20", "ksampler": "30", "lora_after": "11"}

# Wan Animate motion-transfer (workflow_video.json). Driving video + ref photo ->
# animated character mp4. char LoRA is WanVideoLoraSelect (lora/strength, not the
# image LoraLoaderModelOnly). Final mp4 is node 319 (save_output) under /history "gifs".
VIDEO = {"load_video": "75", "ref_image": "515", "prompt": "549",
         "char": "544", "sampler": "273", "output": "319"}

# INSTARAW advanced (workflow_adv.json) — LOCAL ONLY. One graph does t2i + image-guided
# "i2i" via the 576 toggle. Generation is ALWAYS txt2img on the empty latent (407); there
# is no real img2img (verified) — uploaded images only steer the in-workflow LLM prompt
# generator (584). Character LoRA goes into slot 1 of BOTH rgthree stacks (287 low / 256
# high). Interactive popups (344 picker / 285 mask) stay active, surfaced in the app.
# Final image = node 402 (authenticity-processed, saved w/ EXIF).
ADV = {"toggle": "576", "aspect": "523", "char_ref": "581", "loader": "583",
       "prompt_gen": "584", "lora_low": "287", "lora_high": "256", "or_key": "580",
       "latent_switch": "406", "empty_latent": "407", "img_picker": "344",
       "mask_filter": "285", "output": "402"}

# Main Menu: pipeline stages the UI can toggle off. Each is a clean image->image node;
# disabling = bypass (rewire its consumers to its image input, then drop it).
ADV_STAGES = {"face": "127", "eyes": "501", "hands": "141", "pussy": "147",
              "nipples": "140", "feet": "142", "lips": "171", "color": "543",
              "glcm": "537", "grain": "548", "perturb": "533", "compress": "551"}

# Krea2 I2I (workflow_krea2.json) — true img2img (VAEEncode of the resized source
# image, denoise 0.6), single character LoraLoaderModelOnly (no Lightning chain,
# unlike WAN i2i/t2i), plus an optional skin-detail refine pass (denoise 0.15,
# fixed prompt at node 339).
KREA2 = {"load_image": "316", "positive": "314", "resize_size": "324",
         "char": "313", "base_ksampler": "302", "base_save": "346",
         "refine_encode": "334", "refine_ksampler": "335", "refine_decode": "336",
         "refine_prompt": "339", "refine_save": "345"}

# Krea I2I New (workflow_krea2new.json) — depth-ControlNet guided generation:
# DepthAnythingV2 map of the source photo drives a Krea2ControlLoRA + Apply
# chain that conditions a full (denoise 1) KSampler pass from an empty latent.
# NOT img2img (unlike KREA2 above) — no VAEEncode of the source pixels.
KREA2NEW = {"load_image": "32", "positive": "6", "latent": "10",
            "base_ksampler": "2", "char": "38"}

# Krea2 I2I High Quality (workflow_krea2hq.json) — img2img like KREA2, but always
# runs a fixed two-stage ClownsharKSampler_Beta pipeline (base pass denoise 0.8 ->
# quality-refine pass denoise 0.27, both always on, no optional-refine toggle like
# KREA2). Character LoRA sits in slot 1 of an rgthree "Power Lora Loader" node
# alongside two fixed realism-helper LoRAs (technique LoRAs, not user-selectable —
# same treatment as KREA2NEW's control-LoRA).
KREA2HQ = {"load_image": "16", "positive": "5", "resize": "13",
           "noise_aug": "14", "seed_gen": "2", "char": "11"}


def _bypass_node(graph, nid, in_key="image"):
    """Bypass an image->image node: rewire every consumer of its output to its image
    input (incl. the preview/comparer nodes so nothing dangles), then remove it."""
    if nid not in graph:
        return
    src = graph[nid]["inputs"].get(in_key)
    if isinstance(src, list):
        for n in graph.values():
            for k, v in (n.get("inputs") or {}).items():
                if isinstance(v, list) and len(v) == 2 and str(v[0]) == str(nid):
                    n["inputs"][k] = src
    graph.pop(nid, None)


# --- low-level ComfyUI API ----------------------------------------------------
def upload_image(base, raw_bytes):
    """POST to /upload/image, return the stored filename ComfyUI's LoadImage uses."""
    files = {"image": (f"frame_{uuid.uuid4().hex}.png", io.BytesIO(raw_bytes), "image/png")}
    r = requests.post(f"{base}/upload/image", files={"image": files["image"]},
                      data={"overwrite": "true"}, headers=CF_HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    name = j["name"]
    return f"{j['subfolder']}/{name}" if j.get("subfolder") else name


def upload_video(base, raw_bytes, filename="driving.mp4"):
    """Upload a driving video to ComfyUI's input folder (VHS_LoadVideo reads it by
    name). /upload/image accepts videos too. Returns the stored name."""
    safe = "drv_" + uuid.uuid4().hex + "_" + os.path.basename(filename or "driving.mp4")
    r = requests.post(f"{base}/upload/image",
                      files={"image": (safe, io.BytesIO(raw_bytes), "video/mp4")},
                      data={"overwrite": "true"}, headers=CF_HEADERS, timeout=600)
    r.raise_for_status()
    j = r.json()
    return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]


def run(base, graph, timeout=900, client_id=None, out_node=None):
    """Queue a graph, wait, return list of base64 PNGs via the /view API.
    client_id lets a WS listener (the web app) receive progress for this job.
    out_node: if set, return ONLY that node's images (e.g. the final save node in a
    graph full of preview/comparer nodes, like the INSTARAW advanced workflow)."""
    pid = requests.post(f"{base}/prompt",
                        json={"prompt": graph, "client_id": client_id or uuid.uuid4().hex},
                        headers=CF_HEADERS, timeout=60).json()["prompt_id"]
    start = time.time()
    while time.time() - start < timeout:
        hist = requests.get(f"{base}/history/{pid}", headers=CF_HEADERS, timeout=30).json()
        if pid in hist:
            h = hist[pid]
            outs = h.get("outputs", {}) or {}
            if out_node and out_node not in outs:
                # The named save node didn't produce output (it errored, was bypassed,
                # or never ran). Do NOT fall back to every output node — in graphs full
                # of preview/comparer nodes (like adv) that floods the gallery with
                # dozens of intermediate images. Surface the real failure instead.
                err = _history_error(h.get("status", {}) or {})
                raise RuntimeError("ComfyUI: save node %s produced no image%s"
                                   % (out_node, (" — " + err) if err else
                                      " (it may have been bypassed or failed upstream)."))
            sel = {out_node: outs[out_node]} if out_node else outs
            imgs = []
            for out in sel.values():
                for im in out.get("images", []):
                    v = requests.get(f"{base}/view", params={
                        "filename": im["filename"], "subfolder": im.get("subfolder", ""),
                        "type": im.get("type", "output")}, headers=CF_HEADERS, timeout=60)
                    imgs.append(base64.b64encode(v.content).decode())
            if imgs:
                return imgs
            # No images: surface ComfyUI's actual node error instead of a generic
            # "no image" so model-path / node failures are debuggable.
            err = _history_error(h.get("status", {}) or {})
            if err:
                raise RuntimeError("ComfyUI node error — " + err)
            return imgs
        time.sleep(1)
    raise TimeoutError("ComfyUI timed out")


def _history_error(status):
    """Extract the node error from a /history entry's status.messages, if any."""
    if status.get("status_str") == "success":
        return ""
    for m in status.get("messages", []):
        if isinstance(m, (list, tuple)) and len(m) == 2 and m[0] == "execution_error":
            d = m[1] or {}
            return (f"{d.get('node_type', '?')}#{d.get('node_id', '?')}: "
                    f"{d.get('exception_type', '')}: {d.get('exception_message', '')}")[:500]
    return "execution did not complete (no node output)" if status.get("status_str") == "error" else ""


def run_video(base, graph, out_node="319", timeout=1800, client_id=None):
    """Queue the motion graph, wait, return the final mp4 as base64. VHS_VideoCombine
    output lands under a 'gifs' key in /history (not 'images'). Prefer the final
    output node; surface ComfyUI node errors if it produces nothing."""
    pid = requests.post(f"{base}/prompt",
                        json={"prompt": graph, "client_id": client_id or uuid.uuid4().hex},
                        headers=CF_HEADERS, timeout=60).json()["prompt_id"]
    start = time.time()
    while time.time() - start < timeout:
        hist = requests.get(f"{base}/history/{pid}", headers=CF_HEADERS, timeout=30).json()
        if pid in hist:
            h = hist[pid]
            outs = h.get("outputs", {}) or {}
            # Return the final SAVED character video only. The pose preview
            # (node 117, save_output=false) lands as type "temp" — never return it.
            # Try the designated final node first, then any other saved-output node.
            order = ([out_node] if out_node in outs else []) + [k for k in outs if k != out_node]
            for nid in order:
                vids = []
                for g in outs.get(nid, {}).get("gifs", []):
                    fn = str(g.get("filename", "")).lower()
                    if not fn.endswith((".mp4", ".webm", ".mov")):
                        continue
                    if g.get("type") == "temp":      # skip pose/preview temp clips
                        continue
                    v = requests.get(f"{base}/view", params={
                        "filename": g["filename"], "subfolder": g.get("subfolder", ""),
                        "type": g.get("type", "output")}, headers=CF_HEADERS, timeout=300)
                    vids.append(base64.b64encode(v.content).decode())
                if vids:
                    return vids
            err = _history_error(h.get("status", {}) or {})
            if err:
                raise RuntimeError("ComfyUI node error — " + err)
            # No saved video — report what each node produced so we can see why the
            # final node (319) is missing (filename + type per node).
            diag = {nid: [(g.get("filename"), g.get("type")) for g in o.get("gifs", [])]
                    for nid, o in outs.items() if o.get("gifs")}
            raise RuntimeError("No saved output video (final node #%s missing). Nodes that produced clips: %s"
                               % (out_node, json.dumps(diag)))
        time.sleep(2)
    raise TimeoutError("ComfyUI timed out (video)")


def _prompt_with_trigger(inp):
    """Prepend the character trigger word to the positive prompt. The UI sends
    `trigger` (default 'ing2lorance', editable per character); fall back to that
    default when absent (e.g. the RunPod handler). Empty trigger = no prefix."""
    trig = inp.get("trigger")
    if trig is None:
        trig = "ing2lorance"
    trig = trig.strip().strip(",").strip()
    body = inp.get("prompt", "") or ""
    return (trig + ", " + body) if trig else body


def _set_lora(graph, nid, path, strength):
    n = graph[nid]["inputs"]
    if path:
        n["lora_name"] = path
        n["strength_model"] = float(strength)
    else:
        n["strength_model"] = 0.0


def _set_power_lora_slot(graph, nid, slot, path, strength):
    """Set one slot of an rgthree 'Power Lora Loader' node — a nested
    {"on","lora","strength"} dict per slot key (lora_1, lora_2, ...), unlike the
    flat lora_name/strength_model of LoraLoaderModelOnly or the lora_0N/strength_0N
    pairs of the 'Lora Loader Stack' node. Empty path -> slot toggled off."""
    key = f"lora_{slot}"
    n = dict(graph[nid]["inputs"].get(key) or {})
    if path:
        n["on"] = True
        n["lora"] = path
        n["strength"] = float(strength)
    else:
        n["on"] = False
    graph[nid]["inputs"][key] = n


def _apply_lightning(graph, node_id, lt):
    """Override the (otherwise locked) Lightning lightx2v node from the UI — a
    {"path","strength"} dict. If nothing is sent, the workflow JSON default
    (the mode-correct lightx2v) stays untouched."""
    if lt and (lt.get("path") or "").strip():
        _set_lora(graph, node_id, lt["path"].strip(), lt.get("strength", 1.0))


def _apply_extra_loras(graph, after_id, char_id, loras):
    """Insert a dynamic chain of user-chosen LoRAs between the locked Lightning
    node (`after_id`) and the character node (`char_id`). Each entry is
    {"path": "wan/...safetensors", "strength": float}. Entries without a path are
    skipped. The character node's model input is rewired to the last LoRA (or to
    `after_id` directly when no extra LoRAs are chosen)."""
    prev = [after_id, 0]
    for i, lo in enumerate(loras or []):
        path = (lo.get("path") or "").strip()
        if not path:
            continue
        nid = f"ulora_{i}"
        graph[nid] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": prev, "lora_name": path,
                       "strength_model": float(lo.get("strength", 1.0))},
            "_meta": {"title": f"Extra LoRA {i + 1}"},
        }
        prev = [nid, 0]
    graph[char_id]["inputs"]["model"] = prev


def _apply_sampler_override(graph, inp):
    """Opt-in broadcast of cfg/sampler_name/scheduler to every sampler node in the
    graph. Only keys present in inp["sampler_override"] AND already defined on a
    given node's inputs are touched (e.g. WanVideoSampler has no sampler_name, so
    that key is silently skipped for it). No-op when the UI toggle is off (no
    "sampler_override" key), so every mode's tuned defaults stay untouched unless
    a user explicitly opts in. [user requirement: broadcasts to EVERY sampler
    node in a mode's graph, including refine/detailer stages, not just the
    primary one.]"""
    override = inp.get("sampler_override")
    if not override:
        return graph
    for node in graph.values():
        if "Sampler" not in node.get("class_type", ""):
            continue
        node_inputs = node.get("inputs", {})
        for key in ("cfg", "sampler_name", "scheduler"):
            if key in override and key in node_inputs:
                node_inputs[key] = override[key]
    return graph


# --- graph builders -----------------------------------------------------------
def _build_i2i(graph, inp, seed, frame_name):
    nm = I2I
    graph[nm["load_image"]]["inputs"]["image"] = frame_name
    graph[nm["resize"]]["inputs"]["width"] = int(inp.get("width", 1080))
    graph[nm["resize"]]["inputs"]["height"] = int(inp.get("height", 1920))
    graph[nm["ksampler"]]["inputs"]["seed"] = seed
    graph[nm["ksampler"]]["inputs"]["denoise"] = float(inp.get("denoise", 0.65))
    graph[nm["ksampler"]]["inputs"]["steps"] = max(4, int(inp.get("steps", 8)))
    graph[nm["noise_aug"]]["inputs"]["seed"] = seed
    graph[nm["repeat_latent"]]["inputs"]["amount"] = max(1, int(inp.get("variations", 1)))
    graph[nm["positive"]]["inputs"]["text"] = _prompt_with_trigger(inp)
    graph[nm["negative"]]["inputs"]["text"] = NEGATIVE
    _apply_lightning(graph, nm["lora_after"], inp.get("lightning"))
    _apply_extra_loras(graph, nm["lora_after"], nm["char"], inp.get("extra_loras", []))
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    _apply_sampler_override(graph, inp)
    return graph


def _build_t2i(graph, inp, seed):
    nm = T2I
    graph[nm["positive"]]["inputs"]["text"] = _prompt_with_trigger(inp)
    graph[nm["negative"]]["inputs"]["text"] = NEGATIVE
    graph[nm["latent"]]["inputs"]["width"] = int(inp.get("width", 1080))
    graph[nm["latent"]]["inputs"]["height"] = int(inp.get("height", 1920))
    graph[nm["latent"]]["inputs"]["batch_size"] = max(1, int(inp.get("variations", 1)))
    graph[nm["ksampler"]]["inputs"]["noise_seed"] = seed
    # sampler schedule is fixed to match wf2 (single low-noise, start@4). Lightning
    # defaults to v2 distill @0.6 but is now tweakable from the UI; extra LoRAs
    # stack after it.
    _apply_lightning(graph, nm["lora_after"], inp.get("lightning"))
    _apply_extra_loras(graph, nm["lora_after"], nm["char"], inp.get("extra_loras", []))
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    _apply_sampler_override(graph, inp)
    return graph


def _build_krea2(graph, inp, seed, frame_name):
    """Krea2 img2img: VAEEncode(resized source image) -> KSampler base pass
    (always saved via base_save/346), optionally followed by a fixed
    skin-detail refine pass (saved separately via refine_save/345, so a
    refine run returns BOTH images). No Lightning/helper-LoRA chain — just
    the single character LoRA node."""
    nm = KREA2
    graph[nm["load_image"]]["inputs"]["image"] = frame_name
    graph[nm["resize_size"]]["inputs"]["Number"] = str(int(inp.get("resize_size", 1920)))
    graph[nm["positive"]]["inputs"]["text"] = _prompt_with_trigger(inp)
    graph[nm["base_ksampler"]]["inputs"]["seed"] = seed
    graph[nm["base_ksampler"]]["inputs"]["denoise"] = float(inp.get("denoise", 0.71))
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    if inp.get("refine"):
        graph[nm["refine_ksampler"]]["inputs"]["seed"] = seed
        graph[nm["refine_ksampler"]]["inputs"]["denoise"] = float(inp.get("refine_denoise", 0.1))
        # base_save (346) and refine_save (345) both stay in the graph, so run()
        # returns both the pre-refine and refined image for this generation.
    else:
        for nid in (nm["refine_encode"], nm["refine_ksampler"],
                    nm["refine_decode"], nm["refine_prompt"], nm["refine_save"]):
            graph.pop(nid, None)
    _apply_sampler_override(graph, inp)
    return graph


def _build_krea2new(graph, inp, seed, frame_name):
    """Krea I2I New: depth-ControlNet guided generation. The source photo drives
    a DepthAnythingV2 map -> Krea2ControlLoRA/Apply chain that conditions a
    full-denoise KSampler pass from an empty latent sized by the app's aspect
    picker (same width/height convention as _build_t2i). Single character
    LoRA, no Lightning/helper-LoRA chain, no refine pass."""
    nm = KREA2NEW
    graph[nm["load_image"]]["inputs"]["image"] = frame_name
    graph[nm["latent"]]["inputs"]["width"] = int(inp.get("width", 1080))
    graph[nm["latent"]]["inputs"]["height"] = int(inp.get("height", 1920))
    graph[nm["positive"]]["inputs"]["text"] = _prompt_with_trigger(inp)
    graph[nm["base_ksampler"]]["inputs"]["seed"] = seed
    _set_lora(graph, nm["char"], inp.get("character_lora_path"),
              inp.get("character_strength", 1.0))
    _apply_sampler_override(graph, inp)
    return graph


def _build_krea2hq(graph, inp, seed, frame_name):
    """Krea2 I2I High Quality: resize+noise-augment the source image, VAEEncode it,
    then always run BOTH ClownsharKSampler_Beta stages (base denoise 0.8 -> quality
    refine denoise 0.27) — unlike KREA2's optional refine pass, this mode has no
    toggle, the second stage is the point of "High Quality". Single SaveImage of
    the refined result. Resolution comes from the app's resolution-preset picker
    (plain width/height ints, same convention as _build_t2i/_build_krea2new) —
    the source workflow's in-graph resolution-preset dropdown node was dropped."""
    nm = KREA2HQ
    graph[nm["load_image"]]["inputs"]["image"] = frame_name
    graph[nm["resize"]]["inputs"]["width"] = int(inp.get("width", 1080))
    graph[nm["resize"]]["inputs"]["height"] = int(inp.get("height", 1920))
    graph[nm["noise_aug"]]["inputs"]["seed"] = seed
    graph[nm["positive"]]["inputs"]["text"] = _prompt_with_trigger(inp)
    graph[nm["seed_gen"]]["inputs"]["seed"] = seed
    _set_power_lora_slot(graph, nm["char"], 1, inp.get("character_lora_path"),
                         inp.get("character_strength", 1.0))
    _apply_sampler_override(graph, inp)
    return graph


# --- high level ---------------------------------------------------------------
_MODEL_EXT = (".safetensors", ".onnx", ".pkl", ".pth", ".ckpt", ".pt", ".bin", ".sft")


def _normalize_model_paths(graph):
    """Windows-exported workflows use backslash path separators ('wan\\WanLightning\\..'),
    but the Linux worker lists models with forward slashes, so ComfyUI rejects them
    ('Value not in list'). Convert backslashes to '/' in any model-path-like input."""
    for node in graph.values():
        for k, v in (node.get("inputs") or {}).items():
            if isinstance(v, str) and "\\" in v and v.lower().endswith(_MODEL_EXT):
                node["inputs"][k] = v.replace("\\", "/")


def _build_video(graph, inp, seed, video_name, ref_name):
    """Inject the dynamic inputs into the Wan Animate graph. Everything else
    (5-LoRA stack, sampler, pose-rig, block-swap) stays as the workflow defines it."""
    _normalize_model_paths(graph)            # heal Windows-exported backslash paths
    nm = VIDEO
    graph[nm["load_video"]]["inputs"]["video"] = video_name
    if inp.get("frame_cap"):
        graph[nm["load_video"]]["inputs"]["frame_load_cap"] = max(1, int(inp["frame_cap"]))
    if inp.get("fps"):                       # resample input + final output to this fps
        fps = max(1, int(inp["fps"]))
        graph[nm["load_video"]]["inputs"]["force_rate"] = fps
        if nm["output"] in graph:
            graph[nm["output"]]["inputs"]["frame_rate"] = fps
    graph[nm["ref_image"]]["inputs"]["image"] = ref_name
    graph[nm["prompt"]]["inputs"]["text"] = _prompt_with_trigger(inp)
    if inp.get("character_lora_path"):   # WanVideoLoraSelect: lora + strength
        graph[nm["char"]]["inputs"]["lora"] = inp["character_lora_path"]
        graph[nm["char"]]["inputs"]["strength"] = float(inp.get("character_strength", 1.0))
    graph[nm["sampler"]]["inputs"]["seed"] = seed
    _apply_sampler_override(graph, inp)
    return graph


def _set_stack_slot(node, slot, path, strength=0.6):
    """Set one slot of an rgthree 'Lora Loader Stack' (lora_01..04 / strength_01..04).
    Empty path -> 'None' (the pack's no-op sentinel)."""
    node["inputs"][f"lora_0{slot}"] = path or "None"
    if path:
        node["inputs"][f"strength_0{slot}"] = float(strength)


def _build_adv(graph, inp, seed, ref_name=None):
    """INSTARAW advanced pipeline (t2i + image-guided 'i2i'), LOCAL only. Generation is
    always txt2img on the empty latent; uploaded images steer the in-workflow prompt
    generator (584). Drives aspect, character ref, the resolved prompt batch, the
    OpenRouter key (from env — never stored in the file), and the two rgthree LoRA stacks
    (character synced to slot 1 of both; lightning -> low stack slot 2; helpers per group)."""
    nm = ADV
    if inp.get("aspect"):
        graph[nm["aspect"]]["inputs"]["aspect_ratio"] = inp["aspect"]
    # The 576 toggle only affects prompt-from-image. Keep the sampler latent on the empty
    # latent either way (406.input_true is otherwise unwired -> None when toggled on).
    graph[nm["toggle"]]["inputs"]["value"] = bool(inp.get("img2img", False))
    graph[nm["latent_switch"]]["inputs"]["input_true"] = [nm["empty_latent"], 0]
    graph[nm["loader"]]["inputs"]["enable_img2img"] = bool(inp.get("img2img", False))
    if inp.get("loader_batch_data") is not None:
        bd = inp["loader_batch_data"]
        graph[nm["loader"]]["inputs"]["batch_data"] = bd if isinstance(bd, str) else json.dumps(bd)

    if ref_name:
        graph[nm["char_ref"]]["inputs"]["image"] = ref_name

    pg = graph[nm["prompt_gen"]]["inputs"]
    if inp.get("prompt_batch_data") is not None:
        pbd = inp["prompt_batch_data"]
        pg["prompt_batch_data"] = pbd if isinstance(pbd, str) else json.dumps(pbd)
    if inp.get("trigger") is not None:
        pg["trigger_word"] = inp["trigger"]

    key = inp.get("openrouter_key") or os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        graph[nm["or_key"]]["inputs"]["value"] = key

    # character LoRA -> slot 1 of BOTH stacks (synced); lightning -> low stack slot 2
    cp = inp.get("character_lora_path")
    if cp:
        for sid in (nm["lora_low"], nm["lora_high"]):
            _set_stack_slot(graph[sid], 1, cp, inp.get("character_strength", 1.0))
    lt = inp.get("lightning") or {}
    if (lt.get("path") or "").strip():
        _set_stack_slot(graph[nm["lora_low"]], 2, lt["path"].strip(), lt.get("strength", 0.6))

    # helper LoRAs per group: low stack fills free slots 3-4, high stack fills 2-4
    for sid, list_key, start in ((nm["lora_low"], "loras_low", 3), (nm["lora_high"], "loras_high", 2)):
        slot = start
        for lo in (inp.get(list_key) or []):
            if slot > 4:
                break
            p = (lo.get("path") or "").strip()
            if not p:
                continue
            _set_stack_slot(graph[sid], slot, p, lo.get("strength", 0.6))
            slot += 1

    # Interactive popups: when inp["interactive"] is set, keep the picker/mask nodes
    # active so the app's modals can drive them. Otherwise auto-resolve (keep all
    # generated images, use the automatic person-mask) so a gen completes unattended.
    if inp.get("interactive"):
        if nm["img_picker"] in graph:
            graph[nm["img_picker"]]["inputs"]["cache_behavior"] = "Run selector normally"
        if nm["mask_filter"] in graph:
            graph[nm["mask_filter"]]["inputs"]["enabled"] = True
            graph[nm["mask_filter"]]["inputs"]["cache_behavior"] = "Run editor normally"
            graph[nm["mask_filter"]]["inputs"]["if_no_mask"] = "send blank"   # skip -> blank, never cancel
    else:
        n = max(1, int(inp.get("variations", 1)))
        if nm["img_picker"] in graph:
            graph[nm["img_picker"]]["inputs"]["pick_list"] = ",".join(str(i) for i in range(n))
        if nm["mask_filter"] in graph:
            graph[nm["mask_filter"]]["inputs"]["enabled"] = False
    # Main Menu: bypass any pipeline stage the UI turned off
    for name, on in (inp.get("stages") or {}).items():
        if not on and name in ADV_STAGES:
            _bypass_node(graph, ADV_STAGES[name])
    _apply_sampler_override(graph, inp)
    return graph


def generate(base, workflow_dir, inp, client_id=None, max_batch=2):
    """Build + run the right workflow against ComfyUI. Large variation counts are
    split into chunks of `max_batch` (looped) to avoid VRAM OOM on big batches.
    Returns {"images": [...b64...], "seed": int}."""
    mode = inp.get("mode", "i2i")
    wf_path = os.path.join(workflow_dir, f"workflow_{mode}.json")
    seed = int(inp.get("seed", 0)) or int.from_bytes(os.urandom(4), "big")
    total = max(1, int(inp.get("variations", 1)))

    # Wan Animate motion-transfer: driving video + ref photo -> one mp4 (no batching).
    if mode == "video":
        video_name = upload_video(base, base64.b64decode(inp["video_b64"]),
                                  inp.get("video_filename", "driving.mp4"))
        ref_name = upload_image(base, base64.b64decode(inp["ref_b64"]))
        with open(wf_path, encoding="utf-8") as f:
            graph = json.load(f)
        graph = _build_video(graph, inp, seed, video_name, ref_name)
        vids = run_video(base, graph, out_node=VIDEO["output"], client_id=client_id)
        if not vids:
            return {"error": "No video produced — check ComfyUI node errors / model paths."}
        return {"videos": vids, "seed": seed}

    # INSTARAW advanced (local only): one heavy graph; return ONLY the final image
    # (node 402), not the many preview/comparer nodes. Interactive popups handled live.
    if mode == "adv":
        ref_name = None
        if inp.get("ref_b64"):
            ref_name = upload_image(base, base64.b64decode(inp["ref_b64"]))
        with open(wf_path, encoding="utf-8") as f:
            graph = json.load(f)
        graph = _build_adv(graph, inp, seed, ref_name=ref_name)
        images = run(base, graph, client_id=client_id, out_node=ADV["output"], timeout=1800)
        if not images:
            return {"error": "No image produced — check ComfyUI node errors / model paths."}
        return {"images": images, "seed": seed}

    frame_name = None
    if mode in ("i2i", "krea2", "krea2new", "krea2hq"):
        frame_name = upload_image(base, base64.b64decode(inp["image_b64"]))

    images, done = [], 0
    while done < total:
        chunk = min(max_batch, total - done)
        with open(wf_path, encoding="utf-8") as f:
            graph = json.load(f)
        sub = dict(inp, variations=chunk)
        cseed = seed + done   # distinct seed per chunk so variations differ
        if mode == "i2i":
            graph = _build_i2i(graph, sub, cseed, frame_name)
        elif mode == "krea2":
            graph = _build_krea2(graph, sub, cseed, frame_name)
        elif mode == "krea2new":
            graph = _build_krea2new(graph, sub, cseed, frame_name)
        elif mode == "krea2hq":
            graph = _build_krea2hq(graph, sub, cseed, frame_name)
        else:
            graph = _build_t2i(graph, sub, cseed)
        images += run(base, graph, client_id=client_id)
        done += chunk

    if not images:
        return {"error": "No image produced — check ComfyUI node errors / model paths."}
    return {"images": images, "seed": seed}

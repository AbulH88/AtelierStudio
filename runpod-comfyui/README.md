# RunPod Serverless — Wan 2.2 Character I2I (Lorance)

Turn a chosen video frame into your character (Lorance) on RunPod Serverless.
Pay only per generation. Three people trigger it from a web page; nobody touches
the local 5090.

## The two-stage flow

```
STEP 1 — Upload & split  (runs on your cheap web server, NO GPU)
  Upload a reference video  ->  split into frames  ->  show frame grid
        |
        v  user clicks the good frame
STEP 2 — Generate character  (RunPod Serverless GPU)
  chosen frame -> Wan 2.2 I2I + QwenVL auto-caption + Lorance LoRA
        -> final character image returned
```

Frame extraction is plain ffmpeg and needs no GPU, so the paid GPU only runs for
the actual generation (Step 2).

## What the GPU job does (Step 2)

Derived from `I2I_WAN2.2_Instagirl_Controlnet`. Clean, headless version — all
interactive / UI-only nodes removed (Image Filter, video loader, switches,
preview/compare, easy-cleanGPU, JPS/was/crystools utilities).

Pipeline:
1. Load the chosen frame (passed in by the handler).
2. QwenVL (`AILab_QwenVL_Advanced`, Qwen3-VL-4B) auto-describes the frame.
3. Positive prompt = fixed `ing2lorance` face description + QwenVL description.
4. Load Wan 2.2 low-noise 14B (fp16) UNet.
5. Sage attention patch (`PathchSageAttentionKJ`).
6. Apply LoRAs in order: lightx2v 4step -> Lenovo realism -> **LoranceNew (char)**.
7. Resize frame (`ImageResizeKJv2`) -> noise-aug (`ImageNoiseAugmentation`)
   -> VAE encode -> KSampler (res_2s / bong_tangent, steps 8, cfg 1, denoise 0.65)
   -> VAE decode -> SaveImage.

## Models (on the RunPod Network Volume — NOT baked in)

| ComfyUI folder | File | Size |
|---|---|---|
| diffusion_models | WAN/Wan2.2/Text/low_noise_model/wan2.2_t2v_low_noise_14B_fp16.safetensors | 27 GB |
| text_encoders/clip | Wan/umt5_xxl_fp16.safetensors | 11 GB |
| vae | Wan/Wan2_1_VAE_fp32.safetensors | 1 GB |
| loras | wan/Wan2.2-Lightning/Wan2.1-Distill-Loras/wan2.1_t2v_14b_lora_rank64_lightx2v_4step.safetensors | 1 GB |
| loras | wan/WanRealisomLora/Lenovo.safetensors | 1 GB |
| loras | wan/Own/LoranceNew/LoranceNew.safetensors (CHARACTER IP) | 2 GB |
| LLM | Qwen-VL/Huihui-Qwen3-VL-4B-Instruct-abliterated/ | ~9 GB |

Total ~52 GB. Volume cost ~$0.07/GB/mo => ~$4/mo.
Source on local machine: `H:/ConfiuiModels/models/...`

## Custom nodes (cloned in the image)

- ComfyUI-KJNodes      (PathchSageAttentionKJ, ImageResizeKJv2, ImageNoiseAugmentation)
- ComfyUI-QwenVL-Mod   (AILab_QwenVL_Advanced) — repo: huchukato/ComfyUI-QwenVL-Mod
- RES4LYF              (res_2s sampler, bong_tangent scheduler)
- runpod (pip)

## Handler input contract

```json
{
  "input": {
    "image_b64": "<base64 of the chosen frame>",
    "prompt": "",                 // optional override; empty => QwenVL auto-caption
    "seed": 0,                    // 0 => random
    "width": 1920,
    "height": 1920,
    "denoise": 0.65
  }
}
```
Returns base64 PNG of the generated character image.

## Node-ID map (handler injects params here — set after API export)

| Param | Node ID | Field |
|---|---|---|
| chosen frame (LoadImage) | TBD | image |
| seed (KSampler) | TBD | seed |
| denoise (KSampler) | TBD | denoise |
| width/height (resize) | TBD | width/height |
| prompt override (positive) | TBD | text |

> Fill these IDs from `workflow_api.json` once exported. See `handler.py` NODE_MAP.

## Build / deploy order

1. Create RunPod Network Volume (same region as endpoint), upload models above.
2. `docker build` locally, test with `python handler.py` + `test_input.json`.
3. Confirm output matches a local 5090 generation.
4. Push image to Docker Hub (private).
5. Create Serverless endpoint: RTX 5090 (32GB) or A6000 (48GB), attach volume,
   active workers = 0, max workers = 2-3.
6. Wire the web page (upload -> frames -> pick -> call endpoint -> show result).

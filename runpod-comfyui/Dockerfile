# Wan 2.2 ComfyUI serverless worker.
# Base: CUDA 12.4 + Python. Models are NOT baked in — they mount from the
# RunPod network volume at runtime (see start.sh).
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl ffmpeg python3 python3-pip python3-venv \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# PyTorch (CUDA 12.4 wheels).
RUN pip install --upgrade pip && \
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# ComfyUI core.
WORKDIR /
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /comfyui
RUN pip install -r /comfyui/requirements.txt

# Custom nodes used by the stripped Lorance I2I workflow.
WORKDIR /comfyui/custom_nodes
RUN git clone https://github.com/kijai/ComfyUI-KJNodes.git && \
    pip install -r ComfyUI-KJNodes/requirements.txt || true
RUN git clone https://github.com/ClownsharkBatwing/RES4LYF.git && \
    pip install -r RES4LYF/requirements.txt || true
RUN git clone https://github.com/huchukato/ComfyUI-QwenVL-Mod.git && \
    pip install -r ComfyUI-QwenVL-Mod/requirements.txt || true

# Sage attention (PathchSageAttentionKJ). May take a while to build.
RUN pip install sageattention || echo "WARN: sageattention install failed; set node to auto/off"

# RunPod SDK + handler deps.
RUN pip install runpod requests websocket-client Pillow

# App files.
COPY handler.py /handler.py
COPY comfy_common.py /comfy_common.py
COPY workflow_i2i.json /workflow_i2i.json
COPY workflow_t2i.json /workflow_t2i.json
COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]

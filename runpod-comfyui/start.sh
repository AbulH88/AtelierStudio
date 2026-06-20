#!/usr/bin/env bash
set -e

# Point ComfyUI at the network volume models (mounted at /runpod-volume on
# serverless, or /workspace when testing on a pod). Symlink so ComfyUI's default
# models/ dir resolves to the volume.
VOLUME="/runpod-volume"
[ -d "$VOLUME" ] || VOLUME="/workspace"

if [ -d "$VOLUME/models" ]; then
  echo "Linking models from $VOLUME/models"
  rm -rf /comfyui/models
  ln -s "$VOLUME/models" /comfyui/models
fi

# Launch ComfyUI headless in the background.
echo "Starting ComfyUI..."
python /comfyui/main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch &

# Wait for the ComfyUI API to answer before starting the handler.
echo "Waiting for ComfyUI API..."
until curl -s http://127.0.0.1:8188/ >/dev/null 2>&1; do
  sleep 1
done
echo "ComfyUI is up."

# Start the RunPod serverless handler.
python -u /handler.py

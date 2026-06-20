"""
RunPod serverless handler — Wan 2.2 character studio (cloud path).

Thin wrapper: all workflow logic lives in comfy_common.py so the cloud worker and
the local web app behave identically. ComfyUI runs inside this container.
"""

import comfy_common
import runpod

COMFY = "http://127.0.0.1:8188"
WORKFLOW_DIR = "/"


def handler(event):
    try:
        return comfy_common.generate(COMFY, WORKFLOW_DIR, event["input"])
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


runpod.serverless.start({"handler": handler})

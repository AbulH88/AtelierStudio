"""
R2 reel library — talks to the Cloudflare Worker proxy (reels-proxy) instead of
the S3 API. (R2's per-account S3 endpoint has a broken TLS cert; the Worker reads
/writes the bucket via an internal binding and is served on a valid workers.dev
cert.) The Worker authenticates with the x-auth secret.

Folders are key prefixes; an empty folder keeps a `.keep` marker.
"""

import os
from urllib.parse import quote

import requests

PROXY_URL = os.environ.get("R2_PROXY_URL", "").rstrip("/")
PROXY_SECRET = os.environ.get("R2_PROXY_SECRET", "")
H = {"x-auth": PROXY_SECRET}
BUCKET = "reels"  # for the /api/reels/config display


def configured():
    return bool(PROXY_URL and PROXY_SECRET)


def ensure_bucket():
    pass  # bucket exists; managed by the Worker binding


def _k(key):
    return quote(key, safe="/")


def list_folders():
    r = requests.get(f"{PROXY_URL}/?list&delimiter=/", headers=H, timeout=30)
    r.raise_for_status()
    return sorted(p.rstrip("/") for p in r.json().get("prefixes", []))


def create_folder(name):
    name = name.strip().strip("/")
    if name:
        requests.put(f"{PROXY_URL}/{_k(name)}/.keep", headers=H, data=b"", timeout=30).raise_for_status()


def list_reels(folder):
    prefix = f"{folder.strip('/')}/" if folder else ""
    r = requests.get(f"{PROXY_URL}/?list&prefix={quote(prefix, safe='/')}", headers=H, timeout=30)
    r.raise_for_status()
    items = []
    for o in r.json().get("objects", []):
        key = o["key"]
        if key.endswith("/.keep"):
            continue
        items.append({"key": key, "name": key.split("/")[-1],
                      "size_mb": round(o["size"] / 1e6, 1),
                      "url": f"/api/reels/media?key={quote(key, safe='')}"})
    return sorted(items, key=lambda x: x["name"])


def upload(local_path, key):
    with open(local_path, "rb") as f:
        requests.put(f"{PROXY_URL}/{_k(key)}", headers=H, data=f, timeout=900).raise_for_status()


def delete(key):
    requests.delete(f"{PROXY_URL}/{_k(key)}", headers=H, timeout=30).raise_for_status()


def stream(key):
    """Return a streaming requests.Response for the object (app proxies it)."""
    return requests.get(f"{PROXY_URL}/{_k(key)}", headers=H, stream=True, timeout=900)


def download_to(key, local_path):
    with requests.get(f"{PROXY_URL}/{_k(key)}", headers=H, stream=True, timeout=900) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)

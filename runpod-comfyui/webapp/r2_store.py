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
_INTERNAL_REEL_PREFIXES = ("gallery/", "thumbs/", "thumbs-reels/")

# A fresh `requests.get/put()` call opens a brand-new TLS connection every time —
# measured ~1s of pure handshake overhead per call to the Worker, vs ~100ms with
# keep-alive. Every function below reuses this one Session so connections to the
# Worker's host are pooled: the very first call still pays the handshake, every
# call after it on the same process is fast. This matters a lot here — a single
# Gallery grid load fires off one stream() per thumbnail.
_SESSION = requests.Session()


def configured():
    return bool(PROXY_URL and PROXY_SECRET)


def ensure_bucket():
    pass  # bucket exists; managed by the Worker binding


def _k(key):
    return quote(key, safe="/")


def list_folders():
    r = _SESSION.get(f"{PROXY_URL}/?list&delimiter=/", headers=H, timeout=30)
    r.raise_for_status()
    return sorted(p.rstrip("/") for p in r.json().get("prefixes", [])
                  if p not in _INTERNAL_REEL_PREFIXES)


def create_folder(name):
    name = name.strip().strip("/")
    if name:
        _SESSION.put(f"{PROXY_URL}/{_k(name)}/.keep", headers=H, data=b"", timeout=30).raise_for_status()


def list_reels(folder):
    prefix = f"{folder.strip('/')}/" if folder else ""
    r = _SESSION.get(f"{PROXY_URL}/?list&prefix={quote(prefix, safe='/')}", headers=H, timeout=30)
    r.raise_for_status()
    items = []
    for o in r.json().get("objects", []):
        key = o["key"]
        if key.endswith("/.keep") or key.startswith(_INTERNAL_REEL_PREFIXES):
            continue
        items.append({"key": key, "name": key.split("/")[-1],
                      "size_mb": round(o["size"] / 1e6, 1),
                      "url": f"/api/reels/media?key={quote(key, safe='')}"})
    return sorted(items, key=lambda x: x["name"])


def upload(local_path, key):
    with open(local_path, "rb") as f:
        _SESSION.put(f"{PROXY_URL}/{_k(key)}", headers=H, data=f, timeout=900).raise_for_status()


def upload_bytes(key, data):
    _SESSION.put(f"{PROXY_URL}/{_k(key)}", headers=H, data=data, timeout=300).raise_for_status()


def list_dirs(prefix):
    """Sub-'folders' (common prefixes) directly under `prefix`."""
    r = _SESSION.get(f"{PROXY_URL}/?list&prefix={quote(prefix, safe='/')}&delimiter=/",
                     headers=H, timeout=30)
    r.raise_for_status()
    return sorted(p.rstrip("/").split("/")[-1] for p in r.json().get("prefixes", []))


def list_objs(prefix, media_route="/api/media"):
    """Objects under `prefix` with a same-origin media URL."""
    r = _SESSION.get(f"{PROXY_URL}/?list&prefix={quote(prefix, safe='/')}", headers=H, timeout=30)
    r.raise_for_status()
    out = []
    for o in r.json().get("objects", []):
        key = o["key"]
        if key.endswith("/.keep"):
            continue
        item = {"key": key, "name": key.split("/")[-1],
                "size_mb": round(o["size"] / 1e6, 2),
                "url": f"{media_route}?key={quote(key, safe='')}"}
        # Worker versions expose this under different names. Preserve it when
        # present so callers can sort real media chronologically.
        for field in ("uploaded", "lastModified", "last_modified", "created_at"):
            if o.get(field) is not None:
                item["created_at"] = o[field]
                break
        out.append(item)
    return out


def delete(key):
    _SESSION.delete(f"{PROXY_URL}/{_k(key)}", headers=H, timeout=30).raise_for_status()


def exists(key):
    """Whether an object exists, without downloading its full body."""
    response = _SESSION.get(f"{PROXY_URL}/{_k(key)}", headers=H, stream=True, timeout=30)
    try:
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True
    finally:
        response.close()


def move(source_key, destination_key):
    """Copy an R2 object to a new key, then remove its source after success."""
    if source_key == destination_key:
        return
    if exists(destination_key):
        raise FileExistsError("An item with that name already exists in the destination folder.")
    response = _SESSION.get(f"{PROXY_URL}/{_k(source_key)}", headers=H, stream=True, timeout=900)
    try:
        response.raise_for_status()
        _SESSION.put(f"{PROXY_URL}/{_k(destination_key)}", headers=H,
                     data=response.raw, timeout=900).raise_for_status()
    finally:
        response.close()
    delete(source_key)


def delete_folder(folder):
    """Delete every object under a folder prefix (incl. the .keep marker)."""
    folder = folder.strip("/")
    if not folder:
        return
    prefix = f"{folder}/"
    r = _SESSION.get(f"{PROXY_URL}/?list&prefix={quote(prefix, safe='/')}", headers=H, timeout=30)
    r.raise_for_status()
    for o in r.json().get("objects", []):
        delete(o["key"])


def stream(key, range_header=None):
    """Return a streaming requests.Response for the object (app proxies it)."""
    headers = dict(H)
    if range_header:
        headers["Range"] = range_header
    return _SESSION.get(f"{PROXY_URL}/{_k(key)}", headers=headers, stream=True, timeout=900)


def download_to(key, local_path):
    with _SESSION.get(f"{PROXY_URL}/{_k(key)}", headers=H, stream=True, timeout=900) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)

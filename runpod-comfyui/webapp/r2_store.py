"""
Cloudflare R2 helper for the reel library (S3-compatible via boto3).

Folders are just key prefixes inside one bucket. An empty folder is kept alive
with a tiny `.keep` marker object so it still shows in the dropdown.
"""

import os
import boto3
from botocore.config import Config

ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
ACCESS_KEY = os.environ.get("R2_ACCESS_KEY_ID", "")
SECRET_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
BUCKET = os.environ.get("R2_BUCKET", "reels")
ENDPOINT = os.environ.get("R2_ENDPOINT") or f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com"

_client = None


def client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3", endpoint_url=ENDPOINT,
            aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY,
            region_name="auto", config=Config(signature_version="s3v4"))
    return _client


def configured():
    return bool(ACCOUNT_ID and ACCESS_KEY and SECRET_KEY)


def ensure_bucket():
    c = client()
    try:
        c.head_bucket(Bucket=BUCKET)
    except Exception:
        c.create_bucket(Bucket=BUCKET)


def list_folders():
    c = client()
    res = c.list_objects_v2(Bucket=BUCKET, Delimiter="/")
    out = [p["Prefix"].rstrip("/") for p in res.get("CommonPrefixes", [])]
    return sorted(out)


def create_folder(name):
    name = name.strip().strip("/")
    if not name:
        return
    client().put_object(Bucket=BUCKET, Key=f"{name}/.keep", Body=b"")


def list_reels(folder):
    c = client()
    prefix = f"{folder.strip('/')}/" if folder else ""
    res = c.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    items = []
    for o in res.get("Contents", []):
        key = o["Key"]
        if key.endswith("/.keep"):
            continue
        items.append({"key": key, "name": key.split("/")[-1],
                      "size_mb": round(o["Size"] / 1e6, 1),
                      "url": presign(key)})
    return sorted(items, key=lambda x: x["name"])


def upload(local_path, key):
    client().upload_file(local_path, BUCKET, key,
                         ExtraArgs={"ContentType": "video/mp4"})


def delete(key):
    client().delete_object(Bucket=BUCKET, Key=key)


def presign(key, expires=3600, download_name=None):
    params = {"Bucket": BUCKET, "Key": key}
    if download_name:  # force a "save to PC" download with the right filename
        params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
    return client().generate_presigned_url("get_object", Params=params, ExpiresIn=expires)


def download_to(key, local_path):
    client().download_file(BUCKET, key, local_path)

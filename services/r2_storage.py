"""Cloudflare R2 object storage for tailoring photos.

R2 speaks the S3 API, so boto3's S3 client works against it by pointing the
endpoint at the account's R2 URL. Storage is entirely optional: if the R2_*
env vars are not set, is_configured() returns False and callers fall back to
saving photos on local disk exactly as before — so local dev, tests, and a
deployment that hasn't set up R2 yet all keep working unchanged.
"""
import os
import boto3
from botocore.exceptions import BotoCoreError, ClientError

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "").strip()
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "").strip()
# Public base URL for the bucket (r2.dev subdomain or a connected custom
# domain) — e.g. https://pub-xxxxxxxx.r2.dev or https://photos.example.com
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").strip().rstrip("/")

_client = None


def is_configured():
    return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY
                and R2_BUCKET_NAME and R2_PUBLIC_URL)


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
    return _client


def upload_bytes(data, key, content_type="image/jpeg"):
    """Upload raw bytes to the bucket under `key`. Returns True on success,
    False on any storage error (caller should fall back to local disk)."""
    try:
        _get_client().put_object(
            Bucket=R2_BUCKET_NAME, Key=key, Body=data, ContentType=content_type,
        )
        return True
    except (BotoCoreError, ClientError):
        return False


def delete_object(key):
    """Best-effort delete; failures are not fatal (object may not exist)."""
    try:
        _get_client().delete_object(Bucket=R2_BUCKET_NAME, Key=key)
    except (BotoCoreError, ClientError):
        pass


def public_url(key):
    return f"{R2_PUBLIC_URL}/{key}"

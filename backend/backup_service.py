"""Nightly encrypted MongoDB backup → Backblaze B2 with 30-day Object Lock retention.

Design principles:
- Ransomware-proof: Object Lock in Compliance mode means backups can't be deleted for 30 days,
  even if attackers get the B2 keys.
- Encrypted at rest: dump is encrypted with Fernet (AES-128-CBC + HMAC) before upload.
- Encryption key derived from JWT_SECRET (already in env; if it changes, you can still recover
  by keeping the old JWT_SECRET around).
- Simple: no external scheduler — an async task in the FastAPI event loop runs the backup nightly.

Restore procedure documented in /app/BACKUP_RESTORE.md.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional

import boto3
from botocore.client import Config
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


def _fernet_key() -> bytes:
    """Derive a stable 32-byte Fernet key from JWT_SECRET so ops can restore without a separate key."""
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is required for backup encryption")
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def _b2_client():
    key_id = os.environ.get("B2_KEY_ID", "").strip()
    app_key = os.environ.get("B2_APPLICATION_KEY", "").strip()
    endpoint = os.environ.get("B2_ENDPOINT", "").strip()
    if not (key_id and app_key and endpoint):
        raise RuntimeError("Backblaze B2 credentials missing")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{endpoint}",
        aws_access_key_id=key_id,
        aws_secret_access_key=app_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def _dump_mongo() -> bytes:
    """Run mongodump against the configured Mongo URL, return the archive bytes."""
    mongo_url = os.environ.get("MONGO_URL", "").strip('"')
    db_name = os.environ.get("DB_NAME", "").strip('"')
    if not (mongo_url and db_name):
        raise RuntimeError("MONGO_URL / DB_NAME missing")
    result = subprocess.run(
        ["mongodump", f"--uri={mongo_url}", f"--db={db_name}", "--archive", "--gzip"],
        capture_output=True, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mongodump failed: {result.stderr.decode('utf-8', errors='ignore')[:500]}")
    return result.stdout


def _encrypt(data: bytes) -> bytes:
    return Fernet(_fernet_key()).encrypt(data)


def _decrypt(data: bytes) -> bytes:
    return Fernet(_fernet_key()).decrypt(data)


def _upload(data: bytes, key: str, retention_days: int = 30) -> dict:
    """Upload to B2 with Object Lock retention. Returns S3 response headers."""
    client = _b2_client()
    bucket = os.environ.get("B2_BUCKET_NAME", "").strip()
    retain_until = datetime.now(timezone.utc) + timedelta(days=retention_days)
    # Compliance mode + retention date makes the object immutable until that date.
    resp = client.put_object(
        Bucket=bucket, Key=key, Body=data,
        ContentType="application/octet-stream",
        ObjectLockMode="COMPLIANCE",
        ObjectLockRetainUntilDate=retain_until,
        ServerSideEncryption="AES256",  # ignored by B2 SSE-B2, but harmless
    )
    return {"etag": resp.get("ETag"), "retain_until": retain_until.isoformat(), "size": len(data)}


def run_backup_sync(retention_days: int = 30) -> dict:
    """End-to-end: dump → encrypt → upload. Returns metadata dict for DB record."""
    started_at = datetime.now(timezone.utc)
    dump = _dump_mongo()
    dump_size = len(dump)
    encrypted = _encrypt(dump)
    ts = started_at.strftime("%Y-%m-%dT%H-%M-%SZ")
    key = f"byrd-mongo-{ts}.archive.gz.enc"
    up = _upload(encrypted, key, retention_days=retention_days)
    finished_at = datetime.now(timezone.utc)
    return {
        "key": key,
        "bucket": os.environ.get("B2_BUCKET_NAME", "").strip(),
        "endpoint": os.environ.get("B2_ENDPOINT", "").strip(),
        "encrypted_size": len(encrypted),
        "dump_size": dump_size,
        "retain_until": up["retain_until"],
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": (finished_at - started_at).total_seconds(),
        "status": "ok",
    }


async def run_backup_async(retention_days: int = 30) -> dict:
    """Run backup off the event loop so mongodump/upload don't block API traffic."""
    return await asyncio.get_event_loop().run_in_executor(None, run_backup_sync, retention_days)


async def scheduled_backup_loop(db):
    """Fire once at startup after a 5-min warmup, then every 24h. Records each run in db.backup_log."""
    await asyncio.sleep(300)  # 5-min warmup so app fully boots
    while True:
        try:
            meta = await run_backup_async(retention_days=30)
            await db.backup_log.insert_one(meta)
            logger.info("Backup complete: %s (%s bytes)", meta["key"], meta["encrypted_size"])
        except Exception as e:
            logger.exception("Backup failed: %s", e)
            try:
                await db.backup_log.insert_one({
                    "status": "error", "error": str(e)[:500],
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                pass
        await asyncio.sleep(24 * 60 * 60)  # 24 hours


def list_recent_backups_b2(limit: int = 20) -> list:
    """Direct list from B2 (source of truth). Returns [{key, size, last_modified, retain_until_iso}]."""
    client = _b2_client()
    bucket = os.environ.get("B2_BUCKET_NAME", "").strip()
    resp = client.list_objects_v2(Bucket=bucket, MaxKeys=limit)
    out = []
    for obj in resp.get("Contents", []):
        # Fetch retention on each file (best-effort — permission may vary)
        retain_until = None
        try:
            r = client.get_object_retention(Bucket=bucket, Key=obj["Key"])
            retain_until = r.get("Retention", {}).get("RetainUntilDate")
            if hasattr(retain_until, "isoformat"):
                retain_until = retain_until.isoformat()
        except Exception:
            pass
        out.append({
            "key": obj["Key"], "size": obj["Size"],
            "last_modified": obj["LastModified"].isoformat() if hasattr(obj["LastModified"], "isoformat") else str(obj["LastModified"]),
            "retain_until": retain_until,
        })
    out.sort(key=lambda x: x["key"], reverse=True)
    return out


def download_backup_bytes(key: str) -> bytes:
    """Fetch encrypted archive from B2. For restore use only."""
    client = _b2_client()
    bucket = os.environ.get("B2_BUCKET_NAME", "").strip()
    buf = io.BytesIO()
    client.download_fileobj(bucket, key, buf)
    return buf.getvalue()


def decrypt_backup_bytes(encrypted: bytes) -> bytes:
    return _decrypt(encrypted)

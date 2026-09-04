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
import gzip
import hashlib
import io
import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional

import boto3
from botocore.client import Config
from bson import json_util
from cryptography.fernet import Fernet
from pymongo import MongoClient

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
    """Dump the configured MongoDB database to a gzipped JSON-lines archive.

    Format (per collection block):
        {"__collection__": "<name>", "count": N}\n
        <bson-json doc 1>\n
        <bson-json doc 2>\n
        ...

    This is a pure-Python dump — no `mongodump` binary required — so the
    backup works identically in any container image (preview, prod, local).

    BSON types (ObjectId, datetime, Binary) are preserved via bson.json_util's
    canonical extended-JSON encoding, so restore is lossless."""
    mongo_url = os.environ.get("MONGO_URL", "").strip('"')
    db_name = os.environ.get("DB_NAME", "").strip('"')
    if not (mongo_url and db_name):
        raise RuntimeError("MONGO_URL / DB_NAME missing")
    # Prefer pymongo (pure Python). We keep mongodump as an optional fast-path
    # if the binary is present on this container AND BYRD_BACKUP_USE_MONGODUMP=1
    # is set; otherwise use the portable Python dump.
    use_mongodump = (
        os.environ.get("BYRD_BACKUP_USE_MONGODUMP", "").strip() in ("1", "true", "yes")
    )
    if use_mongodump:
        try:
            result = subprocess.run(
                ["mongodump", f"--uri={mongo_url}", f"--db={db_name}", "--archive", "--gzip"],
                capture_output=True, timeout=180,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"mongodump failed: {result.stderr.decode('utf-8', errors='ignore')[:500]}"
                )
            return result.stdout
        except FileNotFoundError:
            # mongodump binary not installed — fall through to the Python dump.
            logger.warning("mongodump binary not found; falling back to PyMongo dump")

    return _dump_mongo_python(mongo_url, db_name)


def _dump_mongo_python(mongo_url: str, db_name: str) -> bytes:
    """PyMongo-based dump. Iterates every non-system collection, streams docs
    to a gzip buffer as canonical extended JSON, and returns the bytes."""
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=15000)
    try:
        db = client[db_name]
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
            collections = sorted([
                n for n in db.list_collection_names()
                if not n.startswith("system.")
            ])
            for name in collections:
                coll = db[name]
                count = coll.estimated_document_count()
                header = json.dumps({"__collection__": name, "count": count})
                gz.write((header + "\n").encode("utf-8"))
                for doc in coll.find({}):
                    gz.write((json_util.dumps(doc) + "\n").encode("utf-8"))
        return buf.getvalue()
    finally:
        client.close()


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
    # Suffix distinguishes the internal encoding so restore picks the right
    # decoder. Legacy backups (mongodump archive) used `.archive.gz.enc`.
    key = f"byrd-mongo-{ts}.jsonl.gz.enc"
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
    """Fire once at startup after a 5-min warmup, then every 6h. Records each run in db.backup_log."""
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
        await asyncio.sleep(6 * 60 * 60)  # 6 hours


def list_recent_backups_b2(limit: int = 30) -> list:
    """Direct list from B2 (source of truth). Returns [{key, size, last_modified, retain_until}]."""
    client = _b2_client()
    bucket = os.environ.get("B2_BUCKET_NAME", "").strip()
    # B2 list is unbounded — cap at `limit` after sorting because we want the
    # newest files, which by our ISO-key naming come last alphabetically.
    resp = client.list_objects_v2(Bucket=bucket, MaxKeys=1000)
    files = list(resp.get("Contents", []))
    # Newest first — filename is `byrd-mongo-YYYY-MM-DDTHH-MM-SSZ...` so key
    # sort DESC = time sort DESC.
    files.sort(key=lambda o: o["Key"], reverse=True)
    files = files[:limit]
    out = []
    for obj in files:
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

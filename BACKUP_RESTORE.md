# Byrd & CO — Backup & Restore Runbook

## What gets backed up

Every 24 hours, the app runs `mongodump --gzip --archive` on the entire MongoDB (all collections: users, scenarios, client_docs, client_files, contacts, loan_quotes, term_sheets, everything). The archive is **encrypted with AES-128 (Fernet)** using a key derived from `JWT_SECRET`, then uploaded to Backblaze B2 with a **30-day Object Lock** in Compliance mode.

**Ransomware protection:** Object Lock in Compliance mode means backups **cannot be deleted or overwritten for 30 days** — even by an attacker with the B2 credentials. Even Backblaze support cannot override this. The lock is enforced by Backblaze themselves.

## Location

- Bucket: `byrd-co-backups`
- Endpoint: `s3.us-east-005.backblazeb2.com`
- Key format: `byrd-mongo-YYYY-MM-DDTHH-MM-SSZ.archive.gz.enc`

## How to verify backups are running

From the admin API:
```
GET /api/admin/security/backup/list
GET /api/admin/security/backup/list?from_b2=true   # source of truth
```

Or log into Backblaze → Buckets → byrd-co-backups → files. You should see a new file every 24h.

## How to restore

**Prerequisites:**
- The current `JWT_SECRET` from `backend/.env` (same one that was active when the backup was made — Fernet key is derived from this).
- A machine with Python 3.10+ and MongoDB tools (`mongorestore`).
- Backblaze B2 credentials (keyID + applicationKey) with read access to the bucket.

**Steps:**

1. **Pick the backup you want to restore from.**
   ```
   curl -H "Authorization: Bearer <ADMIN_TOKEN>" \
        "https://byrd-co.com/api/admin/security/backup/list?from_b2=true"
   ```
   Note the `key` of the file you want (e.g., `byrd-mongo-2026-02-05T04-00-00Z.archive.gz.enc`).

2. **Download the encrypted archive.**
   From Python:
   ```python
   import os
   os.environ["B2_KEY_ID"] = "..."
   os.environ["B2_APPLICATION_KEY"] = "..."
   os.environ["B2_ENDPOINT"] = "s3.us-east-005.backblazeb2.com"
   os.environ["B2_BUCKET_NAME"] = "byrd-co-backups"
   os.environ["JWT_SECRET"] = "..."  # SAME secret that was active at backup time!

   from backup_service import download_backup_bytes, decrypt_backup_bytes
   enc = download_backup_bytes("byrd-mongo-2026-02-05T04-00-00Z.archive.gz.enc")
   archive = decrypt_backup_bytes(enc)
   open("/tmp/restore.archive", "wb").write(archive)
   ```

3. **Restore to a fresh Mongo instance.**
   ```
   mongorestore --uri="mongodb://..." --gzip --archive=/tmp/restore.archive --drop
   ```
   The `--drop` flag replaces existing collections; **omit it if you're restoring into a live DB and only want to add missing docs.**

4. **Restart the app.**

## Key rotation

If you ever rotate `JWT_SECRET`:
- **Keep the old value archived somewhere safe** (e.g., 1Password). Backups made under the old secret can only be decrypted with the old secret.
- Or run one final backup, then rotate.

## Retention

- **30 days** — automated. After 30 days, older backups become deletable but are not automatically deleted (Backblaze's file lifecycle handles that if configured).
- To manually clean up backups older than 30 days, use the Backblaze UI or `aws s3 rm` after their retain-until date passes.

## Cost expectation

At current data volume, encrypted backups are well under 100 MB each. Storing 30 daily copies + monthly archives ≈ 5 GB total. Backblaze B2 charges $6/TB/month, so this is ~**$0.03/month**.

"""
Byrd & CO — Audit Log service.

Records every security-relevant event (logins, document access, uploads, deletes,
scenario/term-sheet lifecycle, admin actions) with actor, timestamp, and IP so
brokers can prove chain-of-custody on sensitive borrower documents.

Design:
- Fire-and-forget inserts (never block the request path on audit write failure)
- Indexed by (timestamp DESC), event_type, user_id, resource_id, ip
- No TTL: audit logs are retained indefinitely for compliance
"""
from __future__ import annotations

import csv
import io
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from fastapi import Request

logger = logging.getLogger("byrdco.audit")


# --- Event type catalog (keep in sync with the admin UI filter) ---
EVENT_TYPES: dict[str, str] = {
    # Auth
    "auth.login.success":           "Login success",
    "auth.login.password_ok":       "Password OK (awaiting 2FA)",
    "auth.login.failure":           "Login failed",
    "auth.2fa.challenge.success":   "2FA verified",
    "auth.2fa.challenge.failure":   "2FA failed",
    "auth.password_reset.request":  "Password reset requested",
    "auth.password_reset.complete": "Password reset completed",
    "auth.invite.accepted":         "Invite accepted",
    "auth.2fa.reset":               "Admin reset user 2FA",
    "auth.2fa.enrolled":            "2FA enrolled",
    "auth.2fa.disabled":            "2FA disabled",
    # Documents
    "document.view":                "Document viewed",
    "document.download":            "Document downloaded",
    "document.upload":              "Document uploaded",
    "document.delete":              "Document deleted",
    # Term sheets
    "term_sheet.submit":            "Term sheet submitted",
    "term_sheet.status_change":     "Term sheet status changed",
    "term_sheet.delete":            "Term sheet deleted",
    "term_sheet.view":              "Term sheet document viewed",
    # Scenarios / deal packages
    "scenario.create":              "Scenario created",
    "scenario.update":              "Scenario updated",
    "scenario.delete":              "Scenario deleted",
    # Admin actions
    "admin.invite.sent":            "Admin sent invite",
}


def get_client_ip(request: Optional[Request]) -> str:
    """Extract the real client IP from the request, respecting X-Forwarded-For
    (which the Emergent ingress sets to the true origin IP)."""
    if request is None:
        return "unknown"
    # X-Forwarded-For is a comma-separated list; the first entry is the client
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    xrip = request.headers.get("x-real-ip") or request.headers.get("X-Real-IP")
    if xrip:
        return xrip.strip()
    try:
        return request.client.host if request.client else "unknown"
    except Exception:
        return "unknown"


def _short_ua(ua: str) -> str:
    """Compact the user-agent so the audit log stays readable."""
    if not ua:
        return ""
    ua = ua[:400]
    # Very rough platform/browser signature — enough for a human to eyeball
    for key in ("Firefox/", "Chrome/", "Safari/", "Edg/", "OPR/"):
        if key in ua:
            i = ua.index(key)
            return ua[i:i + 60].strip()
    return ua[:80].strip()


async def log_event(
    db,
    *,
    event_type: str,
    request: Optional[Request] = None,
    user: Optional[dict] = None,
    actor_email: Optional[str] = None,  # for failed logins where user is None
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    resource_name: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    result: str = "success",
) -> None:
    """Insert a single audit event. Swallows all errors — audit MUST NEVER
    break the request path."""
    try:
        doc = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc),
            "event_type": event_type,
            "user_id": (user or {}).get("id"),
            "user_email": (user or {}).get("email") or actor_email,
            "user_name": (user or {}).get("name"),
            "user_role": (user or {}).get("role"),
            "ip": get_client_ip(request),
            "user_agent": _short_ua((request.headers.get("user-agent") if request else "") or ""),
            "resource_type": resource_type,
            "resource_id": resource_id,
            "resource_name": resource_name,
            "metadata": metadata or {},
            "result": result,
        }
        await db.audit_log.insert_one(doc)
    except Exception as e:
        logger.warning("audit log insert failed for %s: %s", event_type, e)


async def query_events(
    db,
    *,
    event_type: Optional[str] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    hard_cap: int = 500,
) -> dict:
    """Filter + paginate audit events for the admin UI.

    `hard_cap` bounds page_size — 500 by default (UI listing), higher for CSV export.
    Response includes `applied_page_size` so callers can detect truncation.
    """
    filt: dict[str, Any] = {}
    if event_type:
        filt["event_type"] = event_type
    if user_id:
        filt["user_id"] = user_id
    if user_email:
        filt["user_email"] = user_email.lower()
    if resource_id:
        filt["resource_id"] = resource_id
    if ip:
        filt["ip"] = ip
    if date_from or date_to:
        filt["timestamp"] = {}
        if date_from:
            filt["timestamp"]["$gte"] = date_from
        if date_to:
            filt["timestamp"]["$lte"] = date_to
    if q:
        # Case-insensitive substring on the human-visible fields. re.escape so users
        # can safely search for e.g. "(" or "+" without breaking the query.
        rx = {"$regex": re.escape(q), "$options": "i"}
        filt["$or"] = [
            {"user_email": rx}, {"user_name": rx},
            {"resource_name": rx}, {"resource_id": rx}, {"ip": rx},
        ]
    total = await db.audit_log.count_documents(filt)
    page = max(1, page)
    page_size = max(1, min(page_size, hard_cap))
    cursor = (
        db.audit_log.find(filt, {"_id": 0})
        .sort("timestamp", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    events = await cursor.to_list(page_size)
    for e in events:
        if isinstance(e.get("timestamp"), datetime):
            e["timestamp"] = e["timestamp"].isoformat()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "applied_page_size": page_size,
        "events": events,
    }


def export_csv(events: Iterable[dict]) -> bytes:
    """Serialize a list of audit events (already dict-ified) to CSV bytes."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "timestamp_utc", "event_type", "event_label", "result",
        "user_email", "user_name", "user_role", "user_id",
        "ip", "user_agent",
        "resource_type", "resource_id", "resource_name", "metadata",
    ])
    for e in events:
        writer.writerow([
            e.get("timestamp"),
            e.get("event_type"),
            EVENT_TYPES.get(e.get("event_type") or "", ""),
            e.get("result"),
            e.get("user_email") or "",
            e.get("user_name") or "",
            e.get("user_role") or "",
            e.get("user_id") or "",
            e.get("ip") or "",
            e.get("user_agent") or "",
            e.get("resource_type") or "",
            e.get("resource_id") or "",
            e.get("resource_name") or "",
            (str(e.get("metadata")) if e.get("metadata") else ""),
        ])
    return buf.getvalue().encode("utf-8")

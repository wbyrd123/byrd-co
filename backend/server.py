"""
Byrd & CO backend — FastAPI + MongoDB.
Powers:
  * Public marketing site (quote requests, testimonials)
  * Client document portal (invite-based, per-client checklists, uploads with status)
  * Admin/broker portal (manage clients, review docs, view quotes)
  * AdsCopilot internal tool (Claude Sonnet 4.5) — kept from prior iteration
"""
from fastapi import FastAPI, APIRouter, HTTPException, Depends, BackgroundTasks, Request
from fastapi.responses import StreamingResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import hashlib
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import base64
import logging
import asyncio
import random
import uuid
import json
import bcrypt
import httpx
import jwt as pyjwt
import pyotp
import qrcode
import secrets as _secrets
from io import BytesIO
import re
import time
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Literal, Dict
from datetime import datetime, timezone, timedelta

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
from email_service import (
    send_email, broker_emails, public_base_url,
    tmpl_quote, tmpl_invite, tmpl_lender_activity,
    tmpl_lender_application_received, tmpl_lender_approved, tmpl_lender_invite,
    tmpl_term_sheet_submitted, tmpl_term_sheet_status_change,
    tmpl_password_reset, tmpl_2fa_code, friendly_delivery_error,
    tmpl_client_doc_upload, tmpl_lender_application_broker_alert,
)
import audit_service
from audit_service import log_event as audit_log

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ['DB_NAME']]

EMERGENT_LLM_KEY = os.environ['EMERGENT_LLM_KEY']
JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGO = "HS256"
JWT_EXPIRY_HOURS = 24 * 14

MAX_FILE_MB = 15
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

# Current active version of the Lender Confidentiality Acknowledgement — shown at the
# lender-view gate the first time a lender opens a specific borrower's deal package.
# Kept intentionally lightweight (no non-circumvention clause, no signature) so it doesn't
# force bank employees to escalate to legal before they can view a deal.
LENDER_TERMS_VERSION = "1.0"
LENDER_TERMS_EFFECTIVE_DATE = "2026-02-01"
LENDER_TERMS_TITLE = "Byrd & CO Deal Package Confidentiality Acknowledgement"
LENDER_TERMS_TEXT = """\
By opening this deal package, I acknowledge:

1. Confidential Information. The borrower information provided in this package — including financial statements, tax returns, entity documents, personal identifiers, and property information — is confidential and provided by Byrd & CO for the sole purpose of evaluating financing for the specific transaction presented in this package.

2. Purpose Limitation. I will use this information only to underwrite and price the financing being requested. I will not use it for any other purpose or share it with any third party outside my own institution's underwriting team without Byrd & CO's written consent.

3. Byrd & CO Introduction. This borrower is a Byrd & CO client. Any future financing conversations with the borrower — including this transaction — should be conducted through Byrd & CO.

4. Contact. Questions about this deal or the borrower go through Byrd & CO first, not directly to the borrower.
"""

app = FastAPI(title="Byrd & CO API")
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("byrdco")


# ================ Helpers ================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_pw(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))


async def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)):
    if not creds:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = pyjwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload["sub"]
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


async def require_client(user=Depends(get_current_user)):
    if user.get("role") != "client":
        raise HTTPException(status_code=403, detail="Client only")
    return user


async def require_lender(user=Depends(get_current_user)):
    if user.get("role") != "lender":
        raise HTTPException(status_code=403, detail="Lender only")
    return user


async def require_studio_user(user=Depends(get_current_user)):
    """Admin OR a client-role user who has been explicitly granted Loan Quote
    Studio access. Used by all endpoints under /admin/marketing/quote* so listing
    agents can build quotes for their own listings."""
    role = user.get("role")
    if role == "admin":
        return user
    if role == "client" and user.get("quote_studio_access") is True:
        return user
    raise HTTPException(status_code=403, detail="No Loan Quote Studio access")


def sanitize_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "email": u["email"],
        "name": u["name"],
        "role": u.get("role", "client"),
        "phone": u.get("phone"),
        "company": u.get("company"),
        "totp_enabled": bool(u.get("totp_enabled")),
        "two_fa_method": u.get("two_fa_method") or ("totp" if u.get("totp_enabled") else None),
        "quote_studio_access": bool(u.get("quote_studio_access")),
    }


# ================ 2FA (TOTP + Email fallback + Backup codes) ================
# TOTP secret is stored as a base32 string on the user document. It is only useful
# with the user's account context; JWT_SECRET compromise does NOT expose TOTP secrets
# (they are stored plaintext-in-DB because the user themselves needs the raw value
# only during initial enrollment, from which point the server uses it to VERIFY 6-digit
# codes without ever needing to display it again). Backup codes are stored bcrypt-hashed.

TWO_FA_ISSUER = "Byrd & CO"
TWO_FA_CHALLENGE_TTL_MINUTES = 5
TWO_FA_EMAIL_CODE_TTL_MINUTES = 10
TWO_FA_MAX_ATTEMPTS = 5


def make_2fa_challenge_token(user_id: str) -> str:
    """Short-lived JWT issued after password success, before 2FA is verified."""
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=TWO_FA_CHALLENGE_TTL_MINUTES),
        "iat": datetime.now(timezone.utc),
        "aud": "2fa-challenge",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_2fa_challenge_token(token: str) -> str:
    """Return user_id from a valid challenge token; raise 401 otherwise."""
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO], audience="2fa-challenge")
        return payload["sub"]
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="2FA challenge expired. Please sign in again.")


def _hash_backup_code(code: str) -> str:
    # bcrypt hashing so a DB dump doesn't expose backup codes
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_backup_code(code: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(code.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def generate_backup_codes(count: int = 10) -> list[str]:
    """Generate 10 human-friendly single-use backup codes (formatted xxxx-xxxx)."""
    codes = []
    for _ in range(count):
        raw = _secrets.token_hex(4)  # 8 hex chars
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def _totp_provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TWO_FA_ISSUER)


def _qr_data_url(uri: str) -> str:
    """Render a QR code PNG for the given otpauth:// URI and return a data URL."""
    img = qrcode.make(uri)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


async def _consume_backup_code(user: dict, code: str) -> bool:
    """If `code` matches one of the user's stored bcrypt-hashed backup codes,
    remove that hash from the list (single-use) and return True."""
    stored = list(user.get("backup_codes") or [])
    normalized = code.strip().lower().replace(" ", "")
    for h in stored:
        if _check_backup_code(normalized, h):
            stored.remove(h)
            await db.users.update_one({"id": user["id"]}, {"$set": {"backup_codes": stored}})
            return True
    return False


# ================ Startup: seed admins & default doc template ================
# ---------- Document checklist templates (per-scenario) ----------
# Each template seeds a new scenario's document folder. The broker picks one at scenario creation.
# Keep labels short and clear — brokers can rename or add lines after seeding.

_PERSONAL_CORE = [
    {"label": "Personal Financial Statement", "category": "Personal", "required": True},
    {"label": "Personal Tax Returns — Year 1", "category": "Personal", "required": True},
    {"label": "Personal Tax Returns — Year 2", "category": "Personal", "required": True},
    {"label": "Personal Tax Returns — Year 3", "category": "Personal", "required": True},
    {"label": "Resume / Bio", "category": "Personal", "required": True},
    {"label": "Government-Issued ID", "category": "Personal", "required": True},
]

_BUSINESS_CORE = [
    {"label": "Entity Docs (LLC / EIN)", "category": "Business", "required": True},
    {"label": "Business Tax Returns — Year 1", "category": "Business", "required": True},
    {"label": "Business Tax Returns — Year 2", "category": "Business", "required": True},
    {"label": "Business Tax Returns — Year 3", "category": "Business", "required": True},
    {"label": "Bank Statements (3 months)", "category": "Financial", "required": True},
]

DOC_TEMPLATES: Dict[str, dict] = {
    "purchase": {
        "label": "Purchase — Standard",
        "description": "Personal + business + property basics + purchase contract.",
        "items": _PERSONAL_CORE + _BUSINESS_CORE + [
            {"label": "Purchase Contract / LOI", "category": "Property", "required": True},
            {"label": "Rent Roll (if any)", "category": "Property", "required": False},
            {"label": "Trailing 12-Month P&L (T-12)", "category": "Property", "required": True},
            {"label": "Property Photos", "category": "Property", "required": False},
            {"label": "Environmental Report / Phase I", "category": "Property", "required": False},
            {"label": "Insurance Quote", "category": "Property", "required": False},
        ],
    },
    "refinance": {
        "label": "Refinance — Standard",
        "description": "Personal + business + rent roll + T-12 + existing loan payoff.",
        "items": _PERSONAL_CORE + _BUSINESS_CORE + [
            {"label": "Current Rent Roll", "category": "Property", "required": True},
            {"label": "Trailing 12-Month P&L (T-12)", "category": "Property", "required": True},
            {"label": "Existing Loan Statement / Payoff Quote", "category": "Property", "required": True},
            {"label": "Recent Appraisal (if available)", "category": "Property", "required": False},
            {"label": "Property Photos", "category": "Property", "required": False},
            {"label": "Insurance Certificate", "category": "Property", "required": False},
        ],
    },
    "construction": {
        "label": "Construction — Standard",
        "description": "Personal + business + budget + plans + GC docs + land contract.",
        "items": _PERSONAL_CORE + _BUSINESS_CORE + [
            {"label": "Land Purchase Contract / Deed", "category": "Property", "required": True},
            {"label": "Detailed Construction Budget", "category": "Property", "required": True},
            {"label": "Architectural Plans & Specs", "category": "Property", "required": True},
            {"label": "GC Agreement / Bid", "category": "Property", "required": True},
            {"label": "GC Resume / License", "category": "Property", "required": True},
            {"label": "Pro Forma (Stabilized)", "category": "Property", "required": True},
            {"label": "Feasibility / Market Study", "category": "Property", "required": False},
            {"label": "Environmental Report / Phase I", "category": "Property", "required": False},
        ],
    },
    "bridge": {
        "label": "Bridge / Value-Add",
        "description": "Personal + business + business plan + T-12 + capex plan.",
        "items": _PERSONAL_CORE + _BUSINESS_CORE + [
            {"label": "Business Plan / Investment Memo", "category": "Property", "required": True},
            {"label": "Current Rent Roll", "category": "Property", "required": True},
            {"label": "Trailing 12-Month P&L (T-12)", "category": "Property", "required": True},
            {"label": "Capex / Renovation Budget", "category": "Property", "required": True},
            {"label": "Pro Forma (Stabilized)", "category": "Property", "required": True},
            {"label": "Purchase Contract (if acquiring)", "category": "Property", "required": False},
            {"label": "Property Photos", "category": "Property", "required": False},
        ],
    },
    "sba": {
        "label": "SBA 7(a) / 504",
        "description": "Personal + business + 3-yr financials + SBA-specific forms.",
        "items": _PERSONAL_CORE + _BUSINESS_CORE + [
            {"label": "Year-to-Date P&L and Balance Sheet", "category": "Business", "required": True},
            {"label": "Business Debt Schedule", "category": "Business", "required": True},
            {"label": "SBA Form 1919 — Borrower Info", "category": "Business", "required": True},
            {"label": "SBA Form 413 — Personal Financial Statement", "category": "Personal", "required": True},
            {"label": "Purchase Contract / LOI (if applicable)", "category": "Property", "required": False},
            {"label": "Business Plan", "category": "Business", "required": True},
            {"label": "Property Appraisal (if owner-occ)", "category": "Property", "required": False},
        ],
    },
    "blank": {
        "label": "Blank — start empty",
        "description": "No lines seeded. Add each item manually.",
        "items": [],
    },
}

# Kept for the invite endpoint's backward-compat signature (no longer seeds anything).
DEFAULT_DOC_TEMPLATE: List[dict] = []
DEFAULT_SCENARIO_TEMPLATE_KEY = "purchase"


@app.on_event("startup")
async def seed():
    # TTL index on login_attempts — auto-purge records older than 30 minutes.
    try:
        await db.login_attempts.create_index("attempted_at", expireAfterSeconds=1800)
    except Exception as e:
        logger.warning("login_attempts TTL index setup failed: %s", e)

    # TTL indexes for 2FA collections — email codes expire, and attempts age out.
    try:
        await db.two_fa_email_codes.create_index("expires_at", expireAfterSeconds=0)
        await db.two_fa_email_codes.create_index([("user_id", 1), ("purpose", 1), ("used", 1), ("created_at", -1)])
        await db.two_fa_attempts.create_index("attempted_at", expireAfterSeconds=1800)
    except Exception as e:
        logger.warning("2FA index setup failed: %s", e)

    # Audit log indexes — no TTL (compliance retention). Timestamp DESC is the
    # dominant sort; add secondary indexes for common filters.
    try:
        await db.audit_log.create_index([("timestamp", -1)])
        await db.audit_log.create_index([("event_type", 1), ("timestamp", -1)])
        await db.audit_log.create_index([("user_id", 1), ("timestamp", -1)])
        await db.audit_log.create_index([("resource_id", 1), ("timestamp", -1)])
        await db.audit_log.create_index([("ip", 1), ("timestamp", -1)])
    except Exception as e:
        logger.warning("audit_log index setup failed: %s", e)

    # Scenario notes — fast lookup by scenario + doc, sorted by creation time.
    try:
        await db.scenario_notes.create_index([("scenario_id", 1), ("doc_id", 1), ("created_at", 1)])
        await db.scenario_notes.create_index([("author_id", 1)])
    except Exception as e:
        logger.warning("scenario_notes index setup failed: %s", e)

    # Nightly encrypted backup to Backblaze B2 (only if B2 creds are configured).
    if os.environ.get("B2_KEY_ID") and os.environ.get("B2_APPLICATION_KEY"):
        try:
            from backup_service import scheduled_backup_loop
            asyncio.create_task(scheduled_backup_loop(db))
            logger.info("Scheduled backup task started (every 6h)")
        except Exception as e:
            logger.warning("Backup scheduler failed to start: %s", e)

    seeds = [
        {"email": "wayne@byrd-co.com", "name": "Wayne Byrd", "phone": "832-813-9802"},
        {"email": "caleb@byrd-co.com", "name": "Caleb Byrd", "phone": "832-661-4390"},
    ]
    for s in seeds:
        existing = await db.users.find_one({"email": s["email"]})
        if not existing:
            await db.users.insert_one({
                "id": str(uuid.uuid4()),
                "email": s["email"],
                "name": s["name"],
                "phone": s["phone"],
                "role": "admin",
                "password_hash": hash_pw("byrdco2026"),
                "created_at": now_iso(),
            })
            logger.info(f"Seeded admin {s['email']}")
        else:
            # Ensure role is admin (idempotent)
            if existing.get("role") != "admin":
                await db.users.update_one({"id": existing["id"]}, {"$set": {"role": "admin"}})

    # One-time migration: docs moved from client to scenario. Wipe legacy client-level docs
    # and any scenario references to them so we start fresh.
    flag = await db.system_flags.find_one({"key": "docs_scenario_migration_v1"})
    if not flag:
        del_docs = await db.client_docs.delete_many({})
        del_files = await db.client_files.delete_many({})
        # Clear stale doc-attachment fields on scenarios and shares
        await db.scenarios.update_many({}, {"$set": {"attached_docs": []}})
        await db.scenario_shares.update_many({}, {"$set": {"doc_grants": [], "doc_overrides": {}}})
        await db.system_flags.insert_one({
            "key": "docs_scenario_migration_v1",
            "applied_at": now_iso(),
            "deleted_client_docs": del_docs.deleted_count,
            "deleted_client_files": del_files.deleted_count,
        })
        logger.info(
            "Scenario-docs migration applied: dropped %s client_docs and %s client_files",
            del_docs.deleted_count, del_files.deleted_count,
        )


# ================ Models ================
class LoginInput(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: Optional[str] = None
    user: Optional[dict] = None
    # 2FA challenge flow: when a user with 2FA enabled logs in, we return
    # requires_2fa=True + a short-lived challenge_token instead of a full JWT.
    requires_2fa: bool = False
    challenge_token: Optional[str] = None
    # Which 2FA channels are available for this user (for the UI)
    totp_available: bool = False
    email_available: bool = False
    # Primary method this user enrolled with — "totp" or "email"
    primary_method: Optional[str] = None


class TwoFAVerifySetup(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class TwoFAChallengeBody(BaseModel):
    challenge_token: str
    code: str
    method: Literal["totp", "email", "backup"] = "totp"


class TwoFAEmailRequestBody(BaseModel):
    challenge_token: str


class TwoFADisableBody(BaseModel):
    password: str
    code: str  # TOTP or backup code


class InviteCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1)
    company: Optional[str] = None
    phone: Optional[str] = None
    doc_template: Optional[List[dict]] = None


class InviteAccept(BaseModel):
    password: str = Field(min_length=6)


class DocCreate(BaseModel):
    label: str
    category: Optional[str] = "Other"
    required: bool = True
    sponsor_id: Optional[str] = None   # null = shared (property/business); set = scoped to sponsor


class DocUpdate(BaseModel):
    label: Optional[str] = None
    status: Optional[Literal["pending", "uploaded", "reviewed", "rejected"]] = None
    notes: Optional[str] = None
    sponsor_id: Optional[str] = None   # pass empty string "" to clear to null
    category: Optional[str] = None
    required: Optional[bool] = None
    lender_visibility: Optional[Literal["included", "on_request", "hidden"]] = None


class DocUploadInput(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"
    data_b64: str  # base64 encoded file contents


class QuoteRequest(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = ""
    loan_type: Optional[str] = ""
    loan_amount: Optional[str] = ""
    property_type: Optional[str] = ""
    message: Optional[str] = ""


# ================ Public routes ================
@api.post("/public/quote")
async def submit_quote(body: QuoteRequest, background: BackgroundTasks):
    doc = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "read": False,
        "created_at": now_iso(),
    }
    await db.quotes.insert_one(doc)
    doc.pop("_id", None)
    logger.info(f"New quote request from {body.email}")
    subj, html, text = tmpl_quote(doc)
    for r in broker_emails():
        background.add_task(send_email, r, subj, html, text, "quote")
    return {"ok": True, "id": doc["id"]}


@api.get("/public/testimonials")
async def testimonials():
    """Public list — only published testimonials, in the admin-defined order."""
    docs = await db.testimonials.find(
        {"published": True}, {"_id": 0}
    ).sort("order", 1).to_list(200)
    if docs:
        return docs
    # Fallback if the collection is empty for any reason
    return await _seed_testimonials_if_empty(return_docs=True)


async def _seed_testimonials_if_empty(return_docs: bool = False):
    """Ensures the 4 legacy testimonials exist in DB so nothing disappears from the site."""
    if await db.testimonials.count_documents({}) > 0:
        if return_docs:
            return await db.testimonials.find({"published": True}, {"_id": 0}).sort("order", 1).to_list(200)
        return None
    seed = [
        {
            "id": "t1",
            "name": "Marcus Reyes",
            "title": "Multifamily Investor · Houston, TX",
            "quote": "Byrd & CO closed our 42-unit refi in 21 days. Every question got a same-day answer, and the terms beat the two other quotes we ran.",
            "rating": 5,
            "avatar": "https://images.unsplash.com/photo-1560250097-0b93528c311a?w=200&h=200&fit=crop",
        },
        {
            "id": "t2",
            "name": "Priya Anand",
            "title": "Hotel Operator · Sugar Land",
            "quote": "Wayne walked us through the SBA path when two other lenders had passed. The construction draws were seamless.",
            "rating": 5,
            "avatar": "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?w=200&h=200&fit=crop",
        },
        {
            "id": "t3",
            "name": "David Whitfield",
            "title": "Condo Developer · Galveston",
            "quote": "The document portal alone saved us a week. Everyone on our side knew exactly what was outstanding.",
            "rating": 5,
            "avatar": "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=200&h=200&fit=crop",
        },
        {
            "id": "t4",
            "name": "Jasmine Cole",
            "title": "SFR Portfolio Owner · The Woodlands",
            "quote": "Caleb structured a portfolio loan across 11 rentals that let us pull real cash out. Fast, direct, and above board.",
            "rating": 5,
            "avatar": "https://images.unsplash.com/photo-1580489944761-15a19d654956?w=200&h=200&fit=crop",
        },
    ]
    now = now_iso()
    for i, s in enumerate(seed):
        await db.testimonials.insert_one({**s, "order": i, "published": True, "created_at": now, "updated_at": now})
    if return_docs:
        return await db.testimonials.find({"published": True}, {"_id": 0}).sort("order", 1).to_list(200)
    return None


class TestimonialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    title: Optional[str] = ""
    quote: str = Field(min_length=1, max_length=1000)
    rating: int = Field(default=5, ge=1, le=5)
    avatar: Optional[str] = ""
    published: bool = True


class TestimonialUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    quote: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    avatar: Optional[str] = None
    published: Optional[bool] = None
    order: Optional[int] = None


class TestimonialReorder(BaseModel):
    order: List[str]  # ordered list of testimonial ids


@api.get("/admin/testimonials")
async def admin_list_testimonials(admin=Depends(require_admin)):
    await _seed_testimonials_if_empty()
    docs = await db.testimonials.find({}, {"_id": 0}).sort("order", 1).to_list(200)
    return docs


@api.post("/admin/testimonials")
async def admin_create_testimonial(body: TestimonialCreate, admin=Depends(require_admin)):
    now = now_iso()
    # Put new items at the end
    last = await db.testimonials.find({}, {"order": 1}).sort("order", -1).limit(1).to_list(1)
    next_order = (last[0].get("order", -1) + 1) if last else 0
    doc = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "order": next_order,
        "created_at": now,
        "updated_at": now,
    }
    await db.testimonials.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.patch("/admin/testimonials/{tid}")
async def admin_update_testimonial(tid: str, body: TestimonialUpdate, admin=Depends(require_admin)):
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = now_iso()
    res = await db.testimonials.update_one({"id": tid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Testimonial not found")
    doc = await db.testimonials.find_one({"id": tid}, {"_id": 0})
    return doc


@api.delete("/admin/testimonials/{tid}")
async def admin_delete_testimonial(tid: str, admin=Depends(require_admin)):
    res = await db.testimonials.delete_one({"id": tid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Testimonial not found")
    return {"ok": True}


@api.post("/admin/testimonials/reorder")
async def admin_reorder_testimonials(body: TestimonialReorder, admin=Depends(require_admin)):
    for i, tid in enumerate(body.order):
        await db.testimonials.update_one({"id": tid}, {"$set": {"order": i, "updated_at": now_iso()}})
    return {"ok": True}


# ================ Contacts CRM (shared team address book) ================
class ContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = ""
    contact_type: List[Literal["email", "phone", "text"]] = Field(default_factory=list)
    notes: Optional[str] = ""
    tags: List[str] = Field(default_factory=list)


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    contact_type: Optional[List[Literal["email", "phone", "text"]]] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    last_contact_at: Optional[str] = None
    last_contact_channel: Optional[Literal["email", "phone", "text"]] = None


class ContactCSVImport(BaseModel):
    csv_text: str = Field(min_length=1, max_length=200000)


class EmailTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


class EmailTemplateUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None


class ContactBulkEmail(BaseModel):
    contact_ids: List[str] = Field(min_length=1)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


_SEEDED_TEMPLATES = [
    {
        "name": "New Product Announcement",
        "subject": "New commercial loan product from Byrd & CO",
        "body": "Hi {{first_name}},\n\nWanted to give you an early heads-up on a new product we're now placing — quick summary, terms, and a link to the details below.\n\n[YOUR ANNOUNCEMENT HERE]\n\nHappy to hop on a call if it might fit anything on your desk.\n\nBest,\n{{admin_first_name}}",
    },
    {
        "name": "Rate Update This Week",
        "subject": "This week's commercial rates — Byrd & CO",
        "body": "Hi {{first_name}},\n\nQuick rate snapshot for this week — feel free to forward or ping me with a scenario.\n\n[RATES]\n\nBest,\n{{admin_first_name}}",
    },
    {
        "name": "Quarterly Check-In",
        "subject": "Checking in — anything I can help with?",
        "body": "Hi {{first_name}},\n\nJust a quarterly note — hope things are going well. Let me know if there's anything I can look at for you on the debt side (refi, acquisition, construction, bridge).\n\nBest,\n{{admin_first_name}}",
    },
    {
        "name": "Referral Thank-You",
        "subject": "Thanks for the introduction",
        "body": "Hi {{first_name}},\n\nJust wanted to say thanks for the introduction — I'll take great care of them. I'll keep you posted on how it goes.\n\nBest,\n{{admin_first_name}}",
    },
]


async def _seed_templates_if_empty():
    if await db.email_templates.count_documents({}) > 0:
        return
    now = now_iso()
    for t in _SEEDED_TEMPLATES:
        await db.email_templates.insert_one({
            "id": str(uuid.uuid4()),
            **t,
            "created_at": now,
            "updated_at": now,
        })


def _first_name(full: Optional[str]) -> str:
    if not full:
        return ""
    return full.strip().split(" ")[0]


@api.get("/admin/contacts")
async def contacts_list(admin=Depends(require_admin)):
    docs = await db.contacts.find({}, {"_id": 0}).sort("name", 1).to_list(2000)
    # Also enrich with suppression status
    suppressed = {u["email"].lower() for u in await db.contact_unsubscribes.find({}, {"email": 1}).to_list(2000) if u.get("email")}
    for c in docs:
        c["unsubscribed"] = bool(c.get("email") and c["email"].lower() in suppressed)
    return docs


@api.post("/admin/contacts")
async def contacts_create(body: ContactCreate, admin=Depends(require_admin)):
    now = now_iso()
    doc = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "created_by_admin_id": admin["id"],
        "last_contact_at": None,
        "last_contact_channel": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.contacts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.patch("/admin/contacts/{cid}")
async def contacts_update(cid: str, body: ContactUpdate, admin=Depends(require_admin)):
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = now_iso()
    res = await db.contacts.update_one({"id": cid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    doc = await db.contacts.find_one({"id": cid}, {"_id": 0})
    return doc


@api.delete("/admin/contacts/{cid}")
async def contacts_delete(cid: str, admin=Depends(require_admin)):
    res = await db.contacts.delete_one({"id": cid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"ok": True}


@api.post("/admin/contacts/{cid}/promote-to-client")
async def contacts_promote_to_client(cid: str, request: Request, admin=Depends(require_admin)):
    """Convert a Contact (CRM entry) into a Client user + generate a portal invite token.
    Does NOT send the invite email — admin sends it manually later once fee agreement +
    docs list are staged. Stamps client_user_id back on the contact so we can render a
    `→ CLIENT` chip and prevent double-promotion."""
    contact = await db.contacts.find_one({"id": cid}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if contact.get("client_user_id"):
        # Verify the linked user still exists; if it was deleted, allow re-promotion.
        linked = await db.users.find_one({"id": contact["client_user_id"]}, {"_id": 0, "id": 1})
        if linked:
            raise HTTPException(status_code=400,
                                detail="Contact is already linked to a client")
    email = (contact.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400,
                            detail="Contact needs an email address to become a client")
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400,
                            detail="A user with this email already exists")

    user_id = str(uuid.uuid4())
    token = uuid.uuid4().hex + uuid.uuid4().hex
    now = now_iso()
    await db.users.insert_one({
        "id": user_id,
        "email": email,
        "name": contact.get("name") or email,
        "phone": contact.get("phone") or None,
        "company": contact.get("company") or None,
        "role": "client",
        "password_hash": None,
        "pending": True,
        "created_by": admin["id"],
        "created_at": now,
        "promoted_from_contact_id": cid,
    })
    await db.invites.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "token": token,
        "created_by": admin["id"],
        "created_at": now,
        "used_at": None,
    })
    await db.contacts.update_one(
        {"id": cid},
        {"$set": {"client_user_id": user_id, "promoted_at": now, "updated_at": now}},
    )
    await audit_log(db, event_type="admin.invite.sent", request=request, user=admin,
                    resource_type="user", resource_id=user_id,
                    resource_name=email,
                    metadata={"invitee_name": contact.get("name"),
                              "invitee_company": contact.get("company"),
                              "promoted_from_contact_id": cid,
                              "email_sent": False, "reason": "promote_from_contact"})
    return {
        "token": token,
        "invite_url_path": f"/portal/invite/{token}",
        "user": {
            "id": user_id, "email": email, "name": contact.get("name") or email,
            "company": contact.get("company"), "phone": contact.get("phone"),
        },
    }


@api.post("/admin/contacts/import-csv")
async def contacts_import_csv(body: ContactCSVImport, admin=Depends(require_admin)):
    """Import contacts from a CSV. Expected headers (any subset, any order):
    name, email, phone, contact_type, tags, notes.
    contact_type + tags can be comma-or-pipe-separated within their cell."""
    import csv, io
    reader = csv.DictReader(io.StringIO(body.csv_text))
    # Normalize headers to lowercase
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no header row")
    header_map = {h: (h or "").strip().lower() for h in reader.fieldnames}
    created = 0
    skipped = 0
    now = now_iso()
    for row in reader:
        norm = {header_map[k]: (v or "").strip() for k, v in row.items() if k}
        name = norm.get("name") or norm.get("full name") or norm.get("contact") or ""
        if not name:
            skipped += 1
            continue
        email_val = norm.get("email") or None
        phone_val = norm.get("phone") or ""
        raw_types = norm.get("contact_type") or norm.get("preferred contact") or ""
        types = [t.strip().lower() for t in re.split(r"[|,]", raw_types) if t.strip()]
        types = [t for t in types if t in ("email", "phone", "text")]
        raw_tags = norm.get("tags") or ""
        tags = [t.strip() for t in re.split(r"[|,]", raw_tags) if t.strip()]
        notes = norm.get("notes") or ""
        await db.contacts.insert_one({
            "id": str(uuid.uuid4()),
            "name": name,
            "email": email_val,
            "phone": phone_val,
            "contact_type": types,
            "tags": tags,
            "notes": notes,
            "created_by_admin_id": admin["id"],
            "last_contact_at": None,
            "last_contact_channel": None,
            "created_at": now,
            "updated_at": now,
        })
        created += 1
    return {"ok": True, "created": created, "skipped": skipped}


@api.get("/admin/email-templates")
async def templates_list(admin=Depends(require_admin)):
    await _seed_templates_if_empty()
    docs = await db.email_templates.find({}, {"_id": 0}).sort("name", 1).to_list(200)
    return docs


@api.post("/admin/email-templates")
async def templates_create(body: EmailTemplateCreate, admin=Depends(require_admin)):
    now = now_iso()
    doc = {"id": str(uuid.uuid4()), **body.model_dump(), "created_at": now, "updated_at": now}
    await db.email_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.patch("/admin/email-templates/{tid}")
async def templates_update(tid: str, body: EmailTemplateUpdate, admin=Depends(require_admin)):
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = now_iso()
    res = await db.email_templates.update_one({"id": tid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    doc = await db.email_templates.find_one({"id": tid}, {"_id": 0})
    return doc


@api.delete("/admin/email-templates/{tid}")
async def templates_delete(tid: str, admin=Depends(require_admin)):
    res = await db.email_templates.delete_one({"id": tid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}


@api.post("/admin/contacts/bulk-email")
async def contacts_bulk_email(body: ContactBulkEmail, admin=Depends(require_admin)):
    """Send a marketing email to N contacts. Personalizes {{first_name}} and {{admin_first_name}}.
    Suppresses unsubscribed emails. Adds a compliant unsubscribe footer. Runs synchronously so
    Postmark errors surface immediately."""
    contacts = await db.contacts.find({"id": {"$in": body.contact_ids}}, {"_id": 0}).to_list(1000)
    if not contacts:
        raise HTTPException(status_code=404, detail="No contacts found for those IDs")
    admin_email = admin.get("email") or ""
    admin_name = admin.get("name") or "Byrd & CO"
    admin_first = _first_name(admin_name)
    # Load suppression set once
    suppressed = {u["email"].lower() async for u in db.contact_unsubscribes.find({}, {"email": 1}) if u.get("email")}
    base_url = os.environ.get("APP_PUBLIC_BASE_URL") or "https://byrd-co.com"

    sent = 0
    failed = 0
    skipped_no_email = 0
    skipped_unsubscribed = 0
    errors: List[str] = []

    for c in contacts:
        if not c.get("email"):
            skipped_no_email += 1
            continue
        email_lower = c["email"].lower()
        if email_lower in suppressed:
            skipped_unsubscribed += 1
            continue

        first = _first_name(c.get("name"))
        subject = body.subject.replace("{{first_name}}", first).replace("{{admin_first_name}}", admin_first)
        rendered = body.body.replace("{{first_name}}", first).replace("{{admin_first_name}}", admin_first)
        # Build unsubscribe token (contact id + email)
        unsub_token = pyjwt.encode(
            {"email": c["email"], "cid": c["id"], "iat": int(time.time())},
            JWT_SECRET, algorithm="HS256",
        )
        unsubscribe_url = f"{base_url.rstrip('/')}/unsubscribe?t={unsub_token}"
        safe_body = rendered.replace("<", "&lt;").replace(">", "&gt;")
        html = (
            "<div style=\"font-family:Georgia,serif;max-width:640px;margin:auto;color:#1A1A1A;\">"
            f"<div style=\"white-space:pre-wrap;font-family:Arial,sans-serif;font-size:14px;line-height:1.55;\">{safe_body}</div>"
            "<hr style=\"margin:24px 0;border:none;border-top:1px solid #E4DFD1;\"/>"
            f"<div style=\"font-family:Arial,sans-serif;font-size:12px;color:#6B6558;\">{admin_name}<br/>Byrd &amp; CO Commercial Real Estate Lending<br/>"
            f"<a href=\"mailto:{admin_email}\" style=\"color:#6B6558;\">{admin_email}</a></div>"
            f"<div style=\"font-family:Arial,sans-serif;font-size:11px;color:#8A8477;margin-top:12px;\">"
            f"You're receiving this because we're in touch professionally. "
            f"<a href=\"{unsubscribe_url}\" style=\"color:#8A8477;\">Unsubscribe from marketing emails</a>."
            "</div></div>"
        )
        text_footer = f"\n\n---\n{admin_name}\nByrd & CO Commercial Real Estate Lending\n{admin_email}\n\nUnsubscribe from marketing: {unsubscribe_url}"
        result = send_email(
            c["email"], subject, html, rendered + text_footer, "marketing",
            None, f"{admin_name} · Byrd & CO", admin_email or None,
        )
        status_v = "sent" if result.get("ok") else "failed"
        if result.get("ok"):
            sent += 1
            await db.contacts.update_one(
                {"id": c["id"]},
                {"$set": {"last_contact_at": now_iso(), "last_contact_channel": "email"}},
            )
        else:
            failed += 1
            if result.get("error"):
                errors.append(f"{c['email']}: {result['error']}")

        await db.assistant_emails.insert_one({
            "id": str(uuid.uuid4()),
            "admin_id": admin["id"],
            "from_email": os.environ.get("POSTMARK_FROM", ""),
            "reply_to": admin_email,
            "to": c["email"],
            "subject": subject,
            "body": rendered,
            "status": status_v,
            "error": result.get("error") or "",
            "tag": "marketing",
            "contact_id": c["id"],
            "sent_at": now_iso(),
        })

    return {
        "ok": True,
        "sent": sent,
        "failed": failed,
        "skipped_no_email": skipped_no_email,
        "skipped_unsubscribed": skipped_unsubscribed,
        "errors": errors[:20],
    }


@api.get("/public/unsubscribe")
async def public_unsubscribe(t: str):
    """Public unsubscribe endpoint. Records the email into contact_unsubscribes."""
    try:
        payload = pyjwt.decode(t, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    email = (payload.get("email") or "").lower()
    if not email:
        raise HTTPException(status_code=400, detail="Invalid link")
    await db.contact_unsubscribes.update_one(
        {"email": email},
        {"$set": {"email": email, "unsubscribed_at": now_iso(), "contact_id": payload.get("cid")}},
        upsert=True,
    )
    return {"ok": True, "email": email}





@api.get("/public/principals")
async def principals():
    return [
        {
            "id": "wayne",
            "name": "Wayne Byrd",
            "title": "Principal",
            "phone": "832-813-9802",
            "email": "wayne@byrd-co.com",
            "bio": "Two decades structuring commercial real estate debt across multifamily, hospitality and mixed-use.",
        },
        {
            "id": "caleb",
            "name": "Caleb Byrd",
            "title": "Principal",
            "phone": "832-661-4390",
            "email": "caleb@byrd-co.com",
            "bio": "Focuses on portfolio, construction and value-add loans for owner-operators and developers.",
        },
    ]


# ================ Auth ================
# ---- Login rate limiting ----
# 5 failed attempts per email within 15 minutes → 15-minute cooldown before more tries.
# Tracked in db.login_attempts with a MongoDB TTL index that auto-purges after 30 min.
LOGIN_ATTEMPT_WINDOW_SECONDS = 15 * 60
LOGIN_ATTEMPT_MAX = 5


async def _login_lockout_status(email: str) -> Optional[str]:
    """Return an error string if this email is currently locked out, else None."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=LOGIN_ATTEMPT_WINDOW_SECONDS)
    fails = await db.login_attempts.count_documents({
        "email": email, "success": False, "attempted_at": {"$gte": cutoff},
    })
    if fails < LOGIN_ATTEMPT_MAX:
        return None
    # Find earliest failure in window → cooldown ends 15 min after that
    earliest = await db.login_attempts.find_one(
        {"email": email, "success": False, "attempted_at": {"$gte": cutoff}},
        sort=[("attempted_at", 1)],
    )
    if not earliest:
        return None
    ea = earliest["attempted_at"]
    if ea.tzinfo is None:
        ea = ea.replace(tzinfo=timezone.utc)
    unlock_at = ea + timedelta(seconds=LOGIN_ATTEMPT_WINDOW_SECONDS)
    mins = max(1, int((unlock_at - datetime.now(timezone.utc)).total_seconds() / 60))
    return f"Too many failed sign-in attempts. Try again in about {mins} minute{'s' if mins != 1 else ''}."


async def _record_login_attempt(email: str, success: bool):
    await db.login_attempts.insert_one({
        "email": email, "success": success,
        "attempted_at": datetime.now(timezone.utc),
    })
    if success:
        # Clear failed attempts for this email on a successful login
        await db.login_attempts.delete_many({"email": email, "success": False})


@api.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginInput, request: Request):
    email = body.email.lower()
    locked = await _login_lockout_status(email)
    if locked:
        await audit_log(db, event_type="auth.login.failure", request=request,
                        actor_email=email, metadata={"reason": "locked"}, result="failure")
        raise HTTPException(status_code=429, detail=locked)
    user = await db.users.find_one({"email": email})
    if not user or not check_pw(body.password, user["password_hash"]):
        await _record_login_attempt(email, success=False)
        await audit_log(db, event_type="auth.login.failure", request=request,
                        actor_email=email,
                        metadata={"reason": "bad_credentials"}, result="failure")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    await _record_login_attempt(email, success=True)
    # If 2FA is enabled, require a second factor before issuing the full JWT.
    if user.get("totp_enabled"):
        method = user.get("two_fa_method") or "totp"
        # Distinct event — password succeeded but 2FA is still pending. The real
        # `auth.login.success` only fires after /auth/2fa/challenge passes.
        await audit_log(db, event_type="auth.login.password_ok", request=request, user=user,
                        metadata={"method": method})
        return {
            "requires_2fa": True,
            "challenge_token": make_2fa_challenge_token(user["id"]),
            "totp_available": bool(user.get("totp_secret")),
            "email_available": True,
            "primary_method": method,
        }
    await audit_log(db, event_type="auth.login.success", request=request, user=user,
                    metadata={"stage": "password_only"})
    return {"token": make_token(user["id"]), "user": sanitize_user(user)}


@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return sanitize_user(user)


# ================ 2FA endpoints ================
# Enrollment: user must be authenticated with a full JWT (already logged in).
# Challenge: user has a short-lived challenge_token from the login endpoint.

@api.get("/auth/2fa/status")
async def two_fa_status(user=Depends(get_current_user)):
    """Current 2FA state for the logged-in user."""
    full = await db.users.find_one({"id": user["id"]}, {"_id": 0, "backup_codes": 1, "totp_enabled": 1, "totp_enrolled_at": 1, "two_fa_method": 1})
    return {
        "enabled": bool(full and full.get("totp_enabled")),
        "enrolled_at": (full or {}).get("totp_enrolled_at"),
        "backup_codes_remaining": len((full or {}).get("backup_codes") or []),
        "method": (full or {}).get("two_fa_method") or ("totp" if (full or {}).get("totp_enabled") else None),
    }


@api.post("/auth/2fa/setup")
async def two_fa_setup(user=Depends(get_current_user)):
    """Begin 2FA enrollment. Returns a fresh TOTP secret + QR data URL. The secret
    is stored on the user as `pending_totp_secret` and is only promoted to `totp_secret`
    once the user proves possession by submitting a valid TOTP code via /verify-setup."""
    full = await db.users.find_one({"id": user["id"]})
    if full and full.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="2FA is already enabled. Disable it first to re-enroll.")
    secret = pyotp.random_base32()
    await db.users.update_one({"id": user["id"]}, {"$set": {"pending_totp_secret": secret}})
    uri = _totp_provisioning_uri(secret, user["email"])
    return {
        "secret": secret,  # shown to user for manual entry
        "otpauth_uri": uri,
        "qr_data_url": _qr_data_url(uri),
        "issuer": TWO_FA_ISSUER,
        "account": user["email"],
    }


@api.post("/auth/2fa/verify-setup")
async def two_fa_verify_setup(body: TwoFAVerifySetup, request: Request, user=Depends(get_current_user)):
    """Confirm the TOTP secret. On success: enable 2FA, generate & return 10 backup codes."""
    full = await db.users.find_one({"id": user["id"]})
    pending = (full or {}).get("pending_totp_secret")
    if not pending:
        raise HTTPException(status_code=400, detail="No pending 2FA setup. Call /auth/2fa/setup first.")
    if not _verify_totp(pending, body.code):
        raise HTTPException(status_code=400, detail="That code didn't match. Check your authenticator app and try again.")
    codes = generate_backup_codes(10)
    hashed = [_hash_backup_code(c.lower()) for c in codes]
    await db.users.update_one({"id": user["id"]}, {
        "$set": {
            "totp_secret": pending,
            "totp_enabled": True,
            "two_fa_method": "totp",
            "totp_enrolled_at": now_iso(),
            "backup_codes": hashed,
        },
        "$unset": {"pending_totp_secret": ""},
    })
    await audit_log(db, event_type="auth.2fa.enrolled", request=request, user=user,
                    metadata={"method": "totp"})
    return {
        "ok": True,
        "backup_codes": codes,
        "method": "totp",
        "message": "2FA is now active. Save these 10 backup codes somewhere safe — each works once.",
    }


# ---- Email-only 2FA enrollment (alternative to TOTP) ----

async def _send_email_verification_code(user_id: str, email: str, name: str, purpose: str,
                                        background: BackgroundTasks) -> dict:
    """Send a 6-digit email code for `purpose` (setup, disable, regenerate) and store its hash.

    Sends SYNCHRONOUSLY (via to_thread) so we can surface a friendly delivery error to the
    caller if Postmark rejects the recipient (inactive, hard-bounced, etc). If the send fails,
    we raise a 502 with `friendly_delivery_error` message instead of storing the code — so the
    user isn't left staring at "code sent" when nothing arrived.
    """
    import asyncio
    code = f"{_secrets.randbelow(1_000_000):06d}"
    subj, html, text = tmpl_2fa_code(name or "there", code)
    # BLOCKING send in a threadpool — we need the result for delivery confirmation
    result = await asyncio.to_thread(send_email, email, subj, html, text, f"2fa_{purpose}")
    if not result.get("ok"):
        # Do NOT store the code — nothing to verify against.
        friendly = friendly_delivery_error(result)
        # Log the raw postmark error server-side for debugging (audit_log will pick up upstream)
        logger.warning("2FA email send failed: purpose=%s email=%s postmark_code=%s err=%s",
                       purpose, email, result.get("error_code"), result.get("error"))
        # Use 400 (not 502) so Cloudflare/ingress doesn't replace our friendly body with its 5xx page.
        raise HTTPException(status_code=400, detail=friendly)
    # Only persist the code when the send succeeded
    await db.two_fa_email_codes.insert_one({
        "user_id": user_id,
        "purpose": purpose,
        "code_hash": _hash_backup_code(code),
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=TWO_FA_EMAIL_CODE_TTL_MINUTES),
        "used": False,
    })
    masked = email[0] + "***@" + email.split("@", 1)[-1]
    return {"sent_to_masked": masked, "expires_in_minutes": TWO_FA_EMAIL_CODE_TTL_MINUTES}


async def _consume_email_verification_code(user_id: str, code: str, purpose: str) -> bool:
    cutoff = datetime.now(timezone.utc)
    doc = await db.two_fa_email_codes.find_one(
        {"user_id": user_id, "purpose": purpose, "used": False, "expires_at": {"$gte": cutoff}},
        sort=[("created_at", -1)],
    )
    if not doc or not _check_backup_code(code.strip(), doc["code_hash"]):
        return False
    await db.two_fa_email_codes.update_one({"_id": doc["_id"]}, {"$set": {"used": True}})
    return True


@api.post("/auth/2fa/email/setup")
async def two_fa_email_setup(background: BackgroundTasks, user=Depends(get_current_user)):
    """Begin email-only 2FA enrollment. Sends a 6-digit verification code to the user's email."""
    full = await db.users.find_one({"id": user["id"]})
    if full and full.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="2FA is already enabled. Disable it first to re-enroll.")
    info = await _send_email_verification_code(user["id"], user["email"], user.get("name"), "setup", background)
    return {"ok": True, **info}


@api.post("/auth/2fa/email/verify-setup")
async def two_fa_email_verify_setup(body: TwoFAVerifySetup, request: Request, user=Depends(get_current_user)):
    """Confirm email-only 2FA enrollment. On success, enables 2FA (method='email') + 10 backup codes."""
    full = await db.users.find_one({"id": user["id"]})
    if full and full.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="2FA is already enabled.")
    ok = await _consume_email_verification_code(user["id"], body.code, "setup")
    if not ok:
        raise HTTPException(status_code=400, detail="Code is invalid or expired. Send a fresh one and try again.")
    codes = generate_backup_codes(10)
    hashed = [_hash_backup_code(c.lower()) for c in codes]
    await db.users.update_one({"id": user["id"]}, {
        "$set": {
            "totp_enabled": True,
            "two_fa_method": "email",
            "totp_enrolled_at": now_iso(),
            "backup_codes": hashed,
        },
        "$unset": {"pending_totp_secret": "", "totp_secret": ""},
    })
    await audit_log(db, event_type="auth.2fa.enrolled", request=request, user=user,
                    metadata={"method": "email"})
    return {
        "ok": True,
        "backup_codes": codes,
        "method": "email",
        "message": "Email-based 2FA is now active. Save these 10 backup codes somewhere safe — each works once.",
    }


@api.post("/auth/2fa/email/send-verification")
async def two_fa_email_send_verification(background: BackgroundTasks, user=Depends(get_current_user)):
    """Send a 6-digit email code to confirm sensitive actions (disable / regenerate).
    Used for email-only 2FA users who don't have an authenticator app."""
    full = await db.users.find_one({"id": user["id"]})
    if not full or not full.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="2FA is not enabled on this account.")
    info = await _send_email_verification_code(user["id"], user["email"], user.get("name"), "verify", background)
    return {"ok": True, **info}


@api.post("/auth/2fa/disable")
async def two_fa_disable(body: TwoFADisableBody, request: Request, user=Depends(get_current_user)):
    """Disable 2FA. Requires current password AND ONE of:
    - Valid TOTP code (for TOTP users)
    - Valid backup code (any user)
    - Valid email verification code (send one first via /auth/2fa/email/send-verification)
    """
    full = await db.users.find_one({"id": user["id"]})
    if not full or not full.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="2FA is not enabled on this account.")
    if not check_pw(body.password, full["password_hash"]):
        raise HTTPException(status_code=401, detail="Password is incorrect.")
    secret = full.get("totp_secret")
    code_ok = (
        (secret and _verify_totp(secret, body.code))
        or await _consume_backup_code(full, body.code.lower())
        or await _consume_email_verification_code(user["id"], body.code, "verify")
    )
    if not code_ok:
        raise HTTPException(status_code=400, detail="Verification code is invalid.")
    await db.users.update_one({"id": user["id"]}, {
        "$set": {"totp_enabled": False, "backup_codes": [], "two_fa_method": None},
        "$unset": {"totp_secret": "", "pending_totp_secret": "", "totp_enrolled_at": ""},
    })
    await audit_log(db, event_type="auth.2fa.disabled", request=request, user=user)
    return {"ok": True}


@api.post("/auth/2fa/regenerate-backup-codes")
async def two_fa_regenerate_backup_codes(body: TwoFAVerifySetup, user=Depends(get_current_user)):
    """Regenerate the 10 backup codes. Accepts TOTP (TOTP users) or email verification code (email users)."""
    full = await db.users.find_one({"id": user["id"]})
    if not full or not full.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="2FA is not enabled on this account.")
    secret = full.get("totp_secret")
    code_ok = (
        (secret and _verify_totp(secret, body.code))
        or await _consume_email_verification_code(user["id"], body.code, "verify")
    )
    if not code_ok:
        raise HTTPException(status_code=400, detail="That code didn't match. Try again.")
    codes = generate_backup_codes(10)
    hashed = [_hash_backup_code(c.lower()) for c in codes]
    await db.users.update_one({"id": user["id"]}, {"$set": {"backup_codes": hashed}})
    return {"backup_codes": codes}


# ---- 2FA challenge (post-password, pre-JWT) ----

async def _record_2fa_attempt(user_id: str, success: bool):
    await db.two_fa_attempts.insert_one({
        "user_id": user_id, "success": success,
        "attempted_at": datetime.now(timezone.utc),
    })
    if success:
        await db.two_fa_attempts.delete_many({"user_id": user_id, "success": False})


async def _two_fa_lockout(user_id: str) -> Optional[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    fails = await db.two_fa_attempts.count_documents({
        "user_id": user_id, "success": False, "attempted_at": {"$gte": cutoff},
    })
    if fails < TWO_FA_MAX_ATTEMPTS:
        return None
    return "Too many failed 2FA attempts. Please sign in again in a few minutes."


@api.post("/auth/2fa/send-email-code")
async def two_fa_send_email_code(body: TwoFAEmailRequestBody, background: BackgroundTasks):
    """Send a 6-digit email fallback code to the user identified by the challenge token."""
    user_id = verify_2fa_challenge_token(body.challenge_token)
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")
    info = await _send_email_verification_code(user_id, user["email"], user.get("name"), "login", background)
    return {"ok": True, **info}


@api.post("/auth/2fa/challenge", response_model=AuthResponse)
async def two_fa_challenge(body: TwoFAChallengeBody, request: Request):
    """Verify the second factor and issue a full JWT."""
    user_id = verify_2fa_challenge_token(body.challenge_token)
    lock = await _two_fa_lockout(user_id)
    if lock:
        raise HTTPException(status_code=429, detail=lock)
    user = await db.users.find_one({"id": user_id})
    if not user or not user.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="2FA is not active on this account.")
    ok = False
    if body.method == "totp":
        ok = _verify_totp(user.get("totp_secret"), body.code)
    elif body.method == "backup":
        ok = await _consume_backup_code(user, body.code.lower())
    elif body.method == "email":
        if await _consume_email_verification_code(user_id, body.code, "login"):
            ok = True
    await _record_2fa_attempt(user_id, success=ok)
    if not ok:
        await audit_log(db, event_type="auth.2fa.challenge.failure", request=request, user=user,
                        metadata={"method": body.method}, result="failure")
        raise HTTPException(status_code=400, detail="Verification code is invalid or expired.")
    await audit_log(db, event_type="auth.2fa.challenge.success", request=request, user=user,
                    metadata={"method": body.method})
    # Also emit the final login success — this is the moment a fully-authenticated
    # JWT is issued for a 2FA-enabled user.
    await audit_log(db, event_type="auth.login.success", request=request, user=user,
                    metadata={"factor": body.method})
    return {"token": make_token(user["id"]), "user": sanitize_user(user)}


# ---- Admin: reset another user's 2FA (in case they lose their device) ----

@api.post("/admin/users/{uid}/2fa/reset")
async def admin_reset_two_fa(uid: str, request: Request, admin=Depends(require_admin)):
    """Disable 2FA on a user's account. Used when a user loses access to their
    authenticator app AND their backup codes. Post-reset the user should re-enroll."""
    target = await db.users.find_one({"id": uid})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one({"id": uid}, {
        "$set": {"totp_enabled": False, "backup_codes": [], "two_fa_method": None},
        "$unset": {"totp_secret": "", "pending_totp_secret": "", "totp_enrolled_at": ""},
    })
    await audit_log(db, event_type="auth.2fa.reset", request=request, user=admin,
                    resource_type="user", resource_id=uid,
                    resource_name=target.get("email"), metadata={"target_email": target.get("email")})
    return {"ok": True, "user_id": uid}


# ================ Invites ================
@api.post("/admin/invites")
async def create_invite(body: InviteCreate, background: BackgroundTasks, request: Request, admin=Depends(require_admin)):
    # If user already exists, error out; otherwise create pending user + invite token
    existing = await db.users.find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="A user with this email already exists")
    user_id = str(uuid.uuid4())
    token = uuid.uuid4().hex + uuid.uuid4().hex
    now = now_iso()
    await db.users.insert_one({
        "id": user_id,
        "email": body.email.lower(),
        "name": body.name,
        "phone": body.phone,
        "company": body.company,
        "role": "client",
        "password_hash": None,
        "pending": True,
        "created_by": admin["id"],
        "created_at": now,
    })
    await db.invites.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "token": token,
        "created_by": admin["id"],
        "created_at": now,
        "used_at": None,
    })
    await audit_log(db, event_type="admin.invite.sent", request=request, user=admin,
                    resource_type="user", resource_id=user_id,
                    resource_name=body.email.lower(),
                    metadata={"invitee_name": body.name, "invitee_company": body.company,
                              "email_sent": False, "reason": "create_only"})
    # Document checklists now live on each SCENARIO (not the client). Nothing to seed here.
    # NOTE: No email is sent automatically. Broker triggers via /admin/users/{uid}/send-invite
    # once documents/fee agreement are ready.
    return {
        "token": token,
        "invite_url_path": f"/portal/invite/{token}",
        "user": {
            "id": user_id, "email": body.email.lower(), "name": body.name,
            "company": body.company, "phone": body.phone,
        },
    }


@api.post("/admin/users/{uid}/send-invite")
async def send_invite_email(uid: str, background: BackgroundTasks, request: Request, admin=Depends(require_admin)):
    """Manually trigger (or resend) the portal invite email for a client."""
    user = await db.users.find_one({"id": uid}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.get("role") != "client":
        raise HTTPException(status_code=400, detail="Can only send invites to client users")
    # Find latest unused invite; if none exists (or already used), create a new token
    inv = await db.invites.find_one(
        {"user_id": uid, "used_at": None},
        sort=[("created_at", -1)],
    )
    if not inv:
        token = uuid.uuid4().hex + uuid.uuid4().hex
        await db.invites.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": uid,
            "token": token,
            "created_by": admin["id"],
            "created_at": now_iso(),
            "used_at": None,
        })
    else:
        token = inv["token"]
    invite_url = f"{public_base_url()}/portal/invite/{token}" if public_base_url() else f"/portal/invite/{token}"
    subj, html, text = tmpl_invite({"name": user.get("name"), "email": user.get("email")}, invite_url)
    background.add_task(send_email, user["email"], subj, html, text, "invite")
    await audit_log(db, event_type="admin.invite.sent", request=request, user=admin,
                    resource_type="user", resource_id=uid,
                    resource_name=user.get("email"),
                    metadata={"invitee_name": user.get("name"), "email_sent": True,
                              "reason": "resend" if inv else "first_send"})
    return {"ok": True, "invite_url_path": f"/portal/invite/{token}", "sent_to": user["email"]}


@api.get("/invites/{token}")
async def get_invite(token: str):
    inv = await db.invites.find_one({"token": token}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")
    if inv.get("used_at"):
        raise HTTPException(status_code=410, detail="Invite already used")
    user = await db.users.find_one({"id": inv["user_id"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Invite invalid")
    return {
        "email": user["email"],
        "name": user["name"],
        "company": user.get("company"),
    }


@api.post("/invites/{token}/accept", response_model=AuthResponse)
async def accept_invite(token: str, body: InviteAccept, request: Request):
    inv = await db.invites.find_one({"token": token})
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")
    if inv.get("used_at"):
        raise HTTPException(status_code=410, detail="Invite already used")
    user = await db.users.find_one({"id": inv["user_id"]})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "password_hash": hash_pw(body.password),
            "pending": False,
            "activated_at": now_iso(),
        }},
    )
    await db.invites.update_one({"id": inv["id"]}, {"$set": {"used_at": now_iso()}})
    await audit_log(db, event_type="auth.invite.accepted", request=request, user=user,
                    resource_type="user", resource_id=user["id"],
                    resource_name=user.get("email"))
    return {"token": make_token(user["id"]), "user": sanitize_user({**user, "role": "client"})}


# ================ Admin: clients ================
async def _client_summary(client_id: str) -> dict:
    """Aggregate doc-status counts across every scenario belonging to this client."""
    docs = await db.client_docs.find({"client_id": client_id}, {"_id": 0}).to_list(2000)
    total = len(docs)
    counts = {"pending": 0, "uploaded": 0, "reviewed": 0, "rejected": 0}
    for d in docs:
        counts[d.get("status", "pending")] = counts.get(d.get("status", "pending"), 0) + 1
    return {"total": total, **counts}


@api.get("/admin/clients")
async def admin_list_clients(admin=Depends(require_admin)):
    users = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(500)
    # Batch-fetch scenarios per client so the roster can show a scenario count / latest type
    scen_by_client: Dict[str, list] = {}
    async for s in db.scenarios.find(
        {"client_id": {"$in": [u["id"] for u in users]}},
        {"_id": 0, "id": 1, "client_id": 1, "name": 1, "status": 1, "loan_request": 1, "updated_at": 1},
    ):
        scen_by_client.setdefault(s["client_id"], []).append(s)
    result = []
    for u in users:
        s = await _client_summary(u["id"])
        u["doc_summary"] = s
        scens = sorted(scen_by_client.get(u["id"], []), key=lambda x: x.get("updated_at") or "", reverse=True)
        u["scenario_count"] = len(scens)
        u["latest_scenario"] = None
        if scens:
            top = scens[0]
            u["latest_scenario"] = {
                "id": top["id"],
                "name": top.get("name"),
                "status": top.get("status"),
                "loan_type": (top.get("loan_request") or {}).get("loan_type"),
            }
        # Legacy: strip loan_type from user payload if it was set by an older invite
        u.pop("loan_type", None)
        result.append(u)
    return result


@api.get("/admin/clients/{client_id}")
async def admin_get_client(client_id: str, admin=Depends(require_admin)):
    u = await db.users.find_one({"id": client_id, "role": "client"}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Client not found")
    u.pop("loan_type", None)  # legacy — loan_type now lives on each scenario
    invite = await db.invites.find_one({"user_id": client_id}, {"_id": 0})
    scenarios = await db.scenarios.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "status": 1, "loan_request": 1, "updated_at": 1, "created_at": 1},
    ).sort("updated_at", -1).to_list(200)
    scen_ids = [s["id"] for s in scenarios]
    doc_counts_by_scen: Dict[str, dict] = {sid: {"total": 0, "uploaded": 0, "reviewed": 0} for sid in scen_ids}
    if scen_ids:
        async for d in db.client_docs.find({"scenario_id": {"$in": scen_ids}}, {"_id": 0, "scenario_id": 1, "status": 1}):
            b = doc_counts_by_scen.setdefault(d["scenario_id"], {"total": 0, "uploaded": 0, "reviewed": 0})
            b["total"] += 1
            if d.get("status") == "uploaded":
                b["uploaded"] += 1
            elif d.get("status") == "reviewed":
                b["reviewed"] += 1
    for s in scenarios:
        lr = s.pop("loan_request", None) or {}
        s["loan_type"] = lr.get("loan_type")
        s["loan_amount"] = lr.get("loan_amount")
        s["doc_counts"] = doc_counts_by_scen.get(s["id"], {"total": 0, "uploaded": 0, "reviewed": 0})
    return {"client": u, "invite": invite, "scenarios": scenarios}


@api.delete("/admin/clients/{client_id}")
async def admin_delete_client(client_id: str, admin=Depends(require_admin)):
    """Delete a client. BLOCKS if any scenarios exist — broker must archive/delete those first."""
    u = await db.users.find_one({"id": client_id, "role": "client"})
    if not u:
        raise HTTPException(status_code=404, detail="Client not found")
    scen_count = await db.scenarios.count_documents({"client_id": client_id})
    if scen_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"This client has {scen_count} loan scenario{'s' if scen_count != 1 else ''}. Delete or reassign them first, then delete the client.",
        )
    orphan_docs = await db.client_docs.find(
        {"client_id": client_id}, {"_id": 0, "file_id": 1, "files": 1},
    ).to_list(2000)
    file_ids = set()
    for d in orphan_docs:
        if d.get("file_id"):
            file_ids.add(d["file_id"])
        for m in (d.get("files") or []):
            if m.get("file_id"):
                file_ids.add(m["file_id"])
    if file_ids:
        await db.client_files.delete_many({"id": {"$in": list(file_ids)}})
    await db.client_docs.delete_many({"client_id": client_id})
    await db.invites.delete_many({"user_id": client_id})
    await db.users.delete_one({"id": client_id})
    return {"ok": True}


class QuoteStudioAccessBody(BaseModel):
    enabled: bool


@api.patch("/admin/clients/{client_id}/quote-studio-access")
async def admin_toggle_quote_studio_access(client_id: str, body: QuoteStudioAccessBody,
                                            request: Request, admin=Depends(require_admin)):
    """Grant or revoke Loan Quote Studio access on a client user. Enables the
    /client/quote-studio route and unlocks the studio API endpoints for that user.
    Admin-only. Emits an audit event so the toggle history is traceable."""
    u = await db.users.find_one({"id": client_id, "role": "client"})
    if not u:
        raise HTTPException(status_code=404, detail="Client not found")
    await db.users.update_one(
        {"id": client_id},
        {"$set": {"quote_studio_access": bool(body.enabled), "updated_at": now_iso()}},
    )
    await audit_log(db, event_type="admin.quote_studio_access", request=request, user=admin,
                    resource_type="user", resource_id=client_id,
                    resource_name=u.get("email") or "",
                    metadata={"enabled": bool(body.enabled)})
    return {"ok": True, "quote_studio_access": bool(body.enabled)}



# ================ Password Reset (all roles) ================

class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    password: str = Field(min_length=8, max_length=200)


@api.post("/public/password-reset/request")
async def password_reset_request(body: PasswordResetRequest, background: BackgroundTasks, request: Request):
    """Send a password-reset email to any user (admin/client/lender). Always returns 200 to
    avoid disclosing whether an email is registered."""
    email = body.email.lower()
    user = await db.users.find_one({"email": email})
    # Only actually send if we found a user with a password set (i.e., activated account)
    if user and user.get("password_hash"):
        token = uuid.uuid4().hex + uuid.uuid4().hex
        # Expire in 60 minutes
        expires_at_dt = datetime.now(timezone.utc) + timedelta(minutes=60)
        await db.password_reset_tokens.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "token": token,
            "created_at": now_iso(),
            "expires_at": expires_at_dt.isoformat(),
            "used_at": None,
        })
        reset_url = (f"{public_base_url()}/portal/reset-password/{token}"
                     if public_base_url() else f"/portal/reset-password/{token}")
        subj, html, text = tmpl_password_reset(user.get("name") or "there", reset_url)
        background.add_task(send_email, email, subj, html, text, "password_reset")
        await audit_log(db, event_type="auth.password_reset.request", request=request, user=user)
    else:
        await audit_log(db, event_type="auth.password_reset.request", request=request,
                        actor_email=email, result="failure",
                        metadata={"reason": "no_active_account"})
    # Uniform response
    return {"ok": True}


@api.get("/public/password-reset/{token}")
async def password_reset_check(token: str):
    """Verify a reset token is still valid. Returns the associated email (masked)."""
    tok = await db.password_reset_tokens.find_one({"token": token})
    if not tok:
        raise HTTPException(status_code=404, detail="Reset link invalid")
    if tok.get("used_at"):
        raise HTTPException(status_code=410, detail="Reset link already used")
    try:
        exp = datetime.fromisoformat(tok["expires_at"])
    except (ValueError, TypeError):
        exp = datetime.now(timezone.utc)
    if datetime.now(timezone.utc) > exp:
        raise HTTPException(status_code=410, detail="Reset link expired")
    user = await db.users.find_one({"id": tok["user_id"]}, {"_id": 0, "email": 1, "name": 1})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Mask the email
    email = user.get("email") or ""
    local, _, domain = email.partition("@")
    masked = (local[:2] + "***" + "@" + domain) if local else email
    return {"email_masked": masked, "name": user.get("name")}


@api.post("/public/password-reset/{token}", response_model=AuthResponse)
async def password_reset_confirm(token: str, body: PasswordResetConfirm, request: Request):
    tok = await db.password_reset_tokens.find_one({"token": token})
    if not tok:
        raise HTTPException(status_code=404, detail="Reset link invalid")
    if tok.get("used_at"):
        raise HTTPException(status_code=410, detail="Reset link already used")
    try:
        exp = datetime.fromisoformat(tok["expires_at"])
    except (ValueError, TypeError):
        exp = datetime.now(timezone.utc)
    if datetime.now(timezone.utc) > exp:
        raise HTTPException(status_code=410, detail="Reset link expired")
    user = await db.users.find_one({"id": tok["user_id"]})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"password_hash": hash_pw(body.password), "password_updated_at": now_iso()}},
    )
    await db.password_reset_tokens.update_one({"id": tok["id"]},
                                              {"$set": {"used_at": now_iso()}})
    # Invalidate any OTHER unused reset tokens for this user
    await db.password_reset_tokens.update_many(
        {"user_id": user["id"], "used_at": None, "id": {"$ne": tok["id"]}},
        {"$set": {"used_at": now_iso()}},
    )
    await audit_log(db, event_type="auth.password_reset.complete", request=request, user=user)
    return {"token": make_token(user["id"]), "user": sanitize_user(user)}




# ================ Client portal ================
@api.get("/client/me")
async def client_me(user=Depends(require_client)):
    """Borrower view — docs grouped by scenario. A user can see a scenario if:
      • they are the primary client (scen.client_id == user.id) — legacy behavior, OR
      • they are linked to one of the scenario's sponsors (scen.sponsors[].client_user_id == user.id)
    Within each scenario, they only see: shared docs (sponsor_id null) + docs scoped to their linked sponsor."""
    # Find all scenarios where the user is either primary client OR a linked sponsor
    scen_cursor = db.scenarios.find(
        {"$or": [
            {"client_id": user["id"]},
            {"sponsors.client_user_id": user["id"]},
        ]},
        {"_id": 0},
    ).sort("created_at", 1)
    scenarios_raw = await scen_cursor.to_list(200)
    # For each scenario, figure out which sponsor(s) this user represents
    my_sponsor_ids_by_scen: Dict[str, set] = {}
    for s in scenarios_raw:
        sponsors = _ensure_sponsors_array(s)
        my_ids = {sp["id"] for sp in sponsors if sp.get("client_user_id") == user["id"]}
        my_sponsor_ids_by_scen[s["id"]] = my_ids
    scen_ids = [s["id"] for s in scenarios_raw]
    docs_by_scen: Dict[str, list] = {sid: [] for sid in scen_ids}
    if scen_ids:
        docs = await db.client_docs.find(
            {"scenario_id": {"$in": scen_ids}}, {"_id": 0},
        ).sort("order", 1).to_list(5000)
        # Fetch pending fee agreements FOR THIS USER (matched by sponsor_id or legacy scenario-level)
        pending_by_key: Dict[str, str] = {}
        async for fa in db.fee_agreements.find(
            {"scenario_id": {"$in": scen_ids}, "status": "sent"},
            {"_id": 0, "scenario_id": 1, "token": 1, "sponsor_id": 1},
        ):
            # Only surface if this fee agreement is for a sponsor this user represents
            # (or if no sponsor_id set — legacy scenario-level agreement for primary client)
            fa_sponsor = fa.get("sponsor_id")
            my_ids = my_sponsor_ids_by_scen.get(fa["scenario_id"], set())
            if (fa_sponsor is None) or (fa_sponsor in my_ids):
                pending_by_key[(fa["scenario_id"], fa_sponsor)] = fa["token"]
        # Filter first (respect sponsor scoping), then attach files metadata in bulk
        visible_docs: list[dict] = []
        for d in docs:
            sid = d["scenario_id"]
            doc_sponsor = d.get("sponsor_id")
            my_ids = my_sponsor_ids_by_scen.get(sid, set())
            if doc_sponsor and doc_sponsor not in my_ids:
                continue
            visible_docs.append(d)
        await _populate_doc_files(visible_docs)
        for d in visible_docs:
            sid = d["scenario_id"]
            doc_sponsor = d.get("sponsor_id")
            # Expose the signing token ONLY on this user's own pinned fee-agreement line
            if d.get("label") == FEE_AGREEMENT_DOC_LABEL:
                tok = pending_by_key.get((sid, doc_sponsor)) or pending_by_key.get((sid, None))
                if tok:
                    d["pending_sign_token"] = tok
            docs_by_scen.setdefault(sid, []).append(d)
    out_scenarios = []
    for s in scenarios_raw:
        lr = s.get("loan_request") or {}
        prop = s.get("property_info") or {}
        location = ""
        if prop.get("city") and prop.get("state"):
            location = f"{prop['city']}, {prop['state']}"
        out_scenarios.append({
            "id": s["id"],
            "name": s.get("name") or "Scenario",
            "status": s.get("status"),
            "loan_type": lr.get("loan_type"),
            "loan_amount": lr.get("loan_amount"),
            "property_type": prop.get("property_type"),
            "location": location,
            "docs": docs_by_scen.get(s["id"], []),
        })
    return {"user": user, "scenarios": out_scenarios}


async def _resolve_client_doc_for_user(doc_id: str, user: dict) -> dict:
    """Fetch a doc the user is authorized to modify — either as primary client_id
    OR as a linked sponsor on the scenario. Raises 404 if unavailable."""
    d = await db.client_docs.find_one({"id": doc_id})
    if not d:
        raise HTTPException(status_code=404, detail="Doc not found")
    # Primary client match
    if d.get("client_id") == user["id"]:
        return d
    # Linked-sponsor match: user must be a linked sponsor on this scenario, AND
    # the doc must be either shared (no sponsor_id) or scoped to this user's sponsor.
    scen = await db.scenarios.find_one(
        {"id": d.get("scenario_id")}, {"_id": 0, "sponsors": 1, "client_id": 1},
    )
    if not scen:
        raise HTTPException(status_code=404, detail="Doc not found")
    my_sponsor_ids = {sp["id"] for sp in (scen.get("sponsors") or []) if sp.get("client_user_id") == user["id"]}
    if not my_sponsor_ids:
        raise HTTPException(status_code=404, detail="Doc not found")
    doc_sponsor = d.get("sponsor_id")
    if doc_sponsor and doc_sponsor not in my_sponsor_ids:
        raise HTTPException(status_code=404, detail="Doc not found")
    return d


# =========== Deal Contacts (title / RE broker / mortgage / insurance / custom) ===========
# Small per-scenario rolodex of the outside parties on a deal. Editable by admin +
# the borrowing client(s). Read-only for lenders. Embedded on the scenarios doc.

DEAL_CONTACT_TYPES = {"title", "re_broker", "mortgage", "insurance", "custom"}


class DealContactInput(BaseModel):
    type: str = Field(default="custom")
    custom_type: Optional[str] = None  # only used when type == "custom"
    company_name: Optional[str] = ""
    contact_person: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    loan_number: Optional[str] = ""  # only meaningful when type == "mortgage"
    notes: Optional[str] = ""


async def _scenario_or_404(sid: str) -> dict:
    scen = await db.scenarios.find_one({"id": sid})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scen


def _client_can_access_scenario(scen: dict, user: dict) -> bool:
    """A client can access a scenario if they are the primary client_id OR a linked sponsor."""
    if scen.get("client_id") == user["id"]:
        return True
    for sp in (scen.get("sponsors") or []):
        if sp.get("client_user_id") == user["id"]:
            return True
    return False


async def _lender_can_access_scenario(sid: str, user: dict) -> bool:
    """A lender has access if their institution has an active share for this scenario."""
    try:
        lender = await _resolve_lender_for_user(user)
    except Exception:
        return False
    if not lender:
        return False
    share = await db.scenario_shares.find_one({"scenario_id": sid, "lender_id": lender["id"]})
    return share is not None


def _sanitize_contact(c: dict) -> dict:
    """Strip internals + normalize keys for the API surface."""
    return {
        "id": c.get("id"),
        "type": c.get("type", "custom"),
        "custom_type": c.get("custom_type"),
        "company_name": c.get("company_name") or "",
        "contact_person": c.get("contact_person") or "",
        "email": c.get("email") or "",
        "phone": c.get("phone") or "",
        "loan_number": c.get("loan_number") or "",
        "notes": c.get("notes") or "",
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
    }


@api.get("/scenarios/{sid}/deal-contacts")
async def list_deal_contacts(sid: str, user=Depends(get_current_user)):
    """Return the deal contacts for a scenario. Admin + owning client + invited
    lender can read. Everyone else 403."""
    scen = await _scenario_or_404(sid)
    role = user.get("role")
    ok = (
        role == "admin"
        or (role == "client" and _client_can_access_scenario(scen, user))
        or (role == "lender" and await _lender_can_access_scenario(sid, user))
    )
    if not ok:
        raise HTTPException(status_code=403, detail="Not authorized")
    return {
        "scenario_id": sid,
        "editable": role in ("admin", "client"),
        "contacts": [_sanitize_contact(c) for c in (scen.get("deal_contacts") or [])],
    }


@api.post("/scenarios/{sid}/deal-contacts")
async def create_deal_contact(sid: str, body: DealContactInput, request: Request,
                              user=Depends(get_current_user)):
    """Admin OR the owning client (primary/sponsor) can add a contact."""
    scen = await _scenario_or_404(sid)
    role = user.get("role")
    if not (role == "admin" or (role == "client" and _client_can_access_scenario(scen, user))):
        raise HTTPException(status_code=403, detail="Only admins and the borrower can add contacts")
    if body.type not in DEAL_CONTACT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported contact type '{body.type}'")
    ctype = body.type
    if ctype == "custom" and not (body.custom_type or "").strip():
        raise HTTPException(status_code=400, detail="Please provide a label for the custom contact type")
    now = now_iso()
    contact = {
        "id": str(uuid.uuid4()),
        "type": ctype,
        "custom_type": (body.custom_type or "").strip() if ctype == "custom" else None,
        "company_name": (body.company_name or "").strip(),
        "contact_person": (body.contact_person or "").strip(),
        "email": (body.email or "").strip().lower(),
        "phone": (body.phone or "").strip(),
        "loan_number": (body.loan_number or "").strip() if ctype == "mortgage" else "",
        "notes": (body.notes or "").strip(),
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
    }
    await db.scenarios.update_one(
        {"id": sid},
        {"$push": {"deal_contacts": contact}, "$set": {"updated_at": now}},
    )
    await audit_log(db, event_type="scenario.update", request=request, user=user,
                    resource_type="scenario", resource_id=sid,
                    resource_name=scen.get("name"),
                    metadata={"fields": ["deal_contacts"], "action": "contact_added",
                              "contact_type": ctype, "contact_id": contact["id"]})
    return _sanitize_contact(contact)


@api.patch("/scenarios/{sid}/deal-contacts/{cid}")
async def update_deal_contact(sid: str, cid: str, body: DealContactInput, request: Request,
                              user=Depends(get_current_user)):
    scen = await _scenario_or_404(sid)
    role = user.get("role")
    if not (role == "admin" or (role == "client" and _client_can_access_scenario(scen, user))):
        raise HTTPException(status_code=403, detail="Only admins and the borrower can edit contacts")
    if body.type not in DEAL_CONTACT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported contact type '{body.type}'")
    ctype = body.type
    if ctype == "custom" and not (body.custom_type or "").strip():
        raise HTTPException(status_code=400, detail="Please provide a label for the custom contact type")
    now = now_iso()
    updates = {
        "deal_contacts.$.type": ctype,
        "deal_contacts.$.custom_type": (body.custom_type or "").strip() if ctype == "custom" else None,
        "deal_contacts.$.company_name": (body.company_name or "").strip(),
        "deal_contacts.$.contact_person": (body.contact_person or "").strip(),
        "deal_contacts.$.email": (body.email or "").strip().lower(),
        "deal_contacts.$.phone": (body.phone or "").strip(),
        "deal_contacts.$.loan_number": (body.loan_number or "").strip() if ctype == "mortgage" else "",
        "deal_contacts.$.notes": (body.notes or "").strip(),
        "deal_contacts.$.updated_at": now,
        "updated_at": now,
    }
    # Atomic positional update — no read-modify-write race window
    res = await db.scenarios.update_one(
        {"id": sid, "deal_contacts.id": cid},
        {"$set": updates},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    scen_after = await db.scenarios.find_one({"id": sid}, {"_id": 0, "name": 1, "deal_contacts": 1})
    updated = next((c for c in (scen_after.get("deal_contacts") or []) if c.get("id") == cid), None)
    await audit_log(db, event_type="scenario.update", request=request, user=user,
                    resource_type="scenario", resource_id=sid,
                    resource_name=scen_after.get("name"),
                    metadata={"fields": ["deal_contacts"], "action": "contact_updated",
                              "contact_id": cid, "contact_type": ctype})
    return _sanitize_contact(updated or {})


@api.delete("/scenarios/{sid}/deal-contacts/{cid}")
async def delete_deal_contact(sid: str, cid: str, request: Request,
                              user=Depends(get_current_user)):
    scen = await _scenario_or_404(sid)
    role = user.get("role")
    if not (role == "admin" or (role == "client" and _client_can_access_scenario(scen, user))):
        raise HTTPException(status_code=403, detail="Only admins and the borrower can remove contacts")
    # Atomic $pull — no read-modify-write race window
    res = await db.scenarios.update_one(
        {"id": sid, "deal_contacts.id": cid},
        {"$pull": {"deal_contacts": {"id": cid}}, "$set": {"updated_at": now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    await audit_log(db, event_type="scenario.update", request=request, user=user,
                    resource_type="scenario", resource_id=sid,
                    resource_name=scen.get("name"),
                    metadata={"fields": ["deal_contacts"], "action": "contact_removed",
                              "contact_id": cid})
    return {"ok": True}


# Token-gated Lender View exposure — read-only. Requires the same session gate
# used by every other /lender-view endpoint so PII isn't leaked via link only.
@api.get("/lender-view/{token}/deal-contacts")
async def lender_view_deal_contacts(token: str, session_token: Optional[str] = None):
    share, session = await _require_view_session(token, session_token)
    scen = await db.scenarios.find_one({"id": share["scenario_id"]},
                                       {"_id": 0, "deal_contacts": 1})
    if not scen:
        raise HTTPException(status_code=404, detail="Deal not found")
    await _log_view(share["scenario_id"], share["id"], session, "view_deal_contacts")
    return {"contacts": [_sanitize_contact(c) for c in (scen.get("deal_contacts") or [])]}


# ========== Deal Notes (per-scenario + per-document) ==========
# Shared conversation trail visible to admin + owning client + invited lender for a scenario.
# Two flavours: general (doc_id=null) and per-document. All parties can add; author (or admin)
# can edit or delete their own. Also readable via token-gated LenderView.

class NoteInput(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    doc_id: Optional[str] = None  # null / omitted = general scenario note


def _sanitize_note(n: dict) -> dict:
    return {
        "id": n.get("id"),
        "scenario_id": n.get("scenario_id"),
        "doc_id": n.get("doc_id"),
        "body": n.get("body") or "",
        "author_role": n.get("author_role"),
        "author_id": n.get("author_id"),
        "author_name": n.get("author_name"),
        "hidden_from_lenders": bool(n.get("hidden_from_lenders")),
        "created_at": n.get("created_at"),
        "updated_at": n.get("updated_at"),
    }


async def _user_can_access_scenario_notes(scen: dict, user: dict) -> bool:
    role = user.get("role")
    if role == "admin":
        return True
    if role == "client":
        return _client_can_access_scenario(scen, user)
    if role == "lender":
        return await _lender_can_access_scenario(scen["id"], user)
    return False


@api.get("/scenarios/{sid}/notes")
async def list_scenario_notes(sid: str, doc_id: Optional[str] = None,
                              user=Depends(get_current_user)):
    """List notes for a scenario. `doc_id=null` (default) returns general notes; passing
    `doc_id=<id>` returns notes for that document. `doc_id=all` returns everything.

    Lenders never see notes marked hidden_from_lenders — that's how admin can suppress
    borrower notes from third-party underwriting eyes."""
    scen = await _scenario_or_404(sid)
    if not await _user_can_access_scenario_notes(scen, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    q: dict = {"scenario_id": sid}
    if doc_id == "all":
        pass
    elif doc_id is None or doc_id == "":
        q["doc_id"] = None
    else:
        q["doc_id"] = doc_id
    if user.get("role") == "lender":
        q["$or"] = [{"hidden_from_lenders": {"$exists": False}}, {"hidden_from_lenders": False}]
    rows = await db.scenario_notes.find(q, {"_id": 0}).sort("created_at", 1).to_list(500)
    return {
        "editable": user.get("role") in ("admin", "client", "lender"),
        "current_user_id": user["id"],
        "current_user_role": user.get("role"),
        "notes": [_sanitize_note(n) for n in rows],
    }


@api.post("/scenarios/{sid}/notes")
async def create_scenario_note(sid: str, body: NoteInput, request: Request,
                               user=Depends(get_current_user)):
    scen = await _scenario_or_404(sid)
    if not await _user_can_access_scenario_notes(scen, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    if body.doc_id:
        # Validate doc actually belongs to this scenario
        exists = await db.client_docs.count_documents({"id": body.doc_id, "scenario_id": sid})
        if not exists:
            raise HTTPException(status_code=404, detail="Document not found on this scenario")
    now = now_iso()
    note = {
        "id": str(uuid.uuid4()),
        "scenario_id": sid,
        "doc_id": body.doc_id or None,
        "body": body.body.strip(),
        "author_role": user.get("role"),
        "author_id": user["id"],
        "author_name": user.get("name") or user.get("email"),
        "author_email": user.get("email"),
        "created_at": now,
        "updated_at": now,
    }
    await db.scenario_notes.insert_one(note)
    await audit_log(db, event_type="scenario.update", request=request, user=user,
                    resource_type="scenario", resource_id=sid,
                    resource_name=scen.get("name"),
                    metadata={"fields": ["notes"], "action": "note_added",
                              "note_id": note["id"], "doc_id": body.doc_id or None})
    return _sanitize_note(note)


@api.patch("/scenarios/{sid}/notes/{nid}")
async def update_scenario_note(sid: str, nid: str, body: NoteInput, request: Request,
                               user=Depends(get_current_user)):
    scen = await _scenario_or_404(sid)
    if not await _user_can_access_scenario_notes(scen, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    note = await db.scenario_notes.find_one({"id": nid, "scenario_id": sid})
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    # Only the author OR admin may edit
    if user.get("role") != "admin" and note.get("author_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Only the author or an admin can edit this note")
    now = now_iso()
    await db.scenario_notes.update_one(
        {"id": nid},
        {"$set": {"body": body.body.strip(), "updated_at": now}},
    )
    updated = await db.scenario_notes.find_one({"id": nid}, {"_id": 0})
    await audit_log(db, event_type="scenario.update", request=request, user=user,
                    resource_type="scenario", resource_id=sid,
                    resource_name=scen.get("name"),
                    metadata={"fields": ["notes"], "action": "note_updated", "note_id": nid,
                              "doc_id": note.get("doc_id")})
    return _sanitize_note(updated)


@api.delete("/scenarios/{sid}/notes/{nid}")
async def delete_scenario_note(sid: str, nid: str, request: Request,
                               user=Depends(get_current_user)):
    scen = await _scenario_or_404(sid)
    if not await _user_can_access_scenario_notes(scen, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    note = await db.scenario_notes.find_one({"id": nid, "scenario_id": sid})
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if user.get("role") != "admin" and note.get("author_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Only the author or an admin can remove this note")
    await db.scenario_notes.delete_one({"id": nid})
    await audit_log(db, event_type="scenario.update", request=request, user=user,
                    resource_type="scenario", resource_id=sid,
                    resource_name=scen.get("name"),
                    metadata={"fields": ["notes"], "action": "note_removed", "note_id": nid,
                              "doc_id": note.get("doc_id")})
    return {"ok": True}


@api.get("/scenarios/{sid}/notes/doc-counts")
async def scenario_doc_note_counts(sid: str, user=Depends(get_current_user)):
    """Return a map of {doc_id: count} for badge indicators on the docs list.
    Lenders' counts exclude admin-hidden notes."""
    scen = await _scenario_or_404(sid)
    if not await _user_can_access_scenario_notes(scen, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    match: dict = {"scenario_id": sid, "doc_id": {"$ne": None}}
    if user.get("role") == "lender":
        match["$or"] = [{"hidden_from_lenders": {"$exists": False}}, {"hidden_from_lenders": False}]
    counts = {}
    async for row in db.scenario_notes.aggregate([
        {"$match": match}, {"$group": {"_id": "$doc_id", "count": {"$sum": 1}}},
    ]):
        counts[row["_id"]] = row["count"]
    return {"counts": counts}


class NoteVisibilityBody(BaseModel):
    hidden_from_lenders: bool


@api.patch("/scenarios/{sid}/notes/{nid}/visibility")
async def admin_toggle_note_visibility(sid: str, nid: str, body: NoteVisibilityBody,
                                        request: Request, admin=Depends(require_admin)):
    """Admin-only: hide a note from lender eyes (borrower privacy) or un-hide it.
    Borrower + admin still see the note in their own portals."""
    note = await db.scenario_notes.find_one({"id": nid, "scenario_id": sid})
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.scenario_notes.update_one(
        {"id": nid},
        {"$set": {"hidden_from_lenders": bool(body.hidden_from_lenders), "updated_at": now_iso()}},
    )
    await audit_log(db, event_type="scenario.update", request=request, user=admin,
                    resource_type="scenario", resource_id=sid,
                    metadata={"fields": ["notes"], "action": "note_visibility_changed",
                              "note_id": nid, "hidden_from_lenders": bool(body.hidden_from_lenders)})
    updated = await db.scenario_notes.find_one({"id": nid}, {"_id": 0})
    return _sanitize_note(updated)


# Token-gated LenderView — read-only view of general + per-doc notes.
@api.get("/lender-view/{token}/notes")
async def lender_view_notes(token: str, session_token: Optional[str] = None,
                            doc_id: Optional[str] = None):
    share, session = await _require_view_session(token, session_token)
    q: dict = {"scenario_id": share["scenario_id"],
               "$or": [{"hidden_from_lenders": {"$exists": False}}, {"hidden_from_lenders": False}]}
    if doc_id == "all":
        pass
    elif doc_id is None or doc_id == "":
        q["doc_id"] = None
    else:
        q["doc_id"] = doc_id
    rows = await db.scenario_notes.find(q, {"_id": 0}).sort("created_at", 1).to_list(500)
    return {"notes": [_sanitize_note(n) for n in rows]}


@api.get("/lender-view/{token}/notes/doc-counts")
async def lender_view_note_counts(token: str, session_token: Optional[str] = None):
    share, session = await _require_view_session(token, session_token)
    match = {"scenario_id": share["scenario_id"], "doc_id": {"$ne": None},
             "$or": [{"hidden_from_lenders": {"$exists": False}}, {"hidden_from_lenders": False}]}
    counts = {}
    async for row in db.scenario_notes.aggregate([
        {"$match": match}, {"$group": {"_id": "$doc_id", "count": {"$sum": 1}}},
    ]):
        counts[row["_id"]] = row["count"]
    return {"counts": counts}


@api.post("/client/docs/{doc_id}/upload")
async def client_upload(doc_id: str, body: DocUploadInput, request: Request,
                        background: BackgroundTasks, user=Depends(require_client)):
    """Append a new file to a doc line. A single line can hold many files
    (e.g., 3 years of tax returns, multi-page entity docs). Marks status='uploaded'.
    Works for both the primary client and any linked sponsor on the scenario."""
    d = await _resolve_client_doc_for_user(doc_id, user)
    if d.get("system"):
        raise HTTPException(status_code=400, detail="This line is managed by Byrd & CO and can't be uploaded to directly.")
    meta = await _append_file_to_doc(d, body.data_b64, body.filename, body.content_type,
                                     uploaded_by="client")
    await audit_log(db, event_type="document.upload", request=request, user=user,
                    resource_type="client_doc", resource_id=doc_id,
                    resource_name=body.filename,
                    metadata={"file_id": meta["file_id"], "doc_label": d.get("label"),
                              "scenario_id": d.get("scenario_id"), "size_b64": len(body.data_b64 or "")})
    # Notify broker(s) that the borrower dropped a file. We don't want a bulk-upload of
    # 20 files to spam the inbox 20 times, so we throttle in-process (see helper below).
    try:
        await _maybe_notify_broker_of_upload(user, d, body.filename, background)
    except Exception:
        logger.exception("client_upload notify failed doc=%s file=%s", doc_id, body.filename)
    return {"ok": True, "file_id": meta["file_id"]}


# In-memory throttle table: key = (scenario_id, uploader_user_id) -> last-sent monotonic ts.
# We coalesce burst uploads (drag-and-drop of many files) into ONE notification per bucket
# within the throttle window. If a broker wants per-file granularity later, drop the window
# to 0 in env. Cleared on server restart which is fine — worst case we send one extra email.
_UPLOAD_NOTIFY_STATE: dict = {}


async def _maybe_notify_broker_of_upload(user: dict, doc: dict, filename: str,
                                          background: BackgroundTasks) -> None:
    brokers = broker_emails()
    if not brokers:
        return
    if str(os.environ.get("NOTIFY_BROKER_ON_UPLOAD", "true")).lower() in ("0", "false", "no", "off"):
        return
    try:
        window = float(os.environ.get("UPLOAD_NOTIFY_WINDOW_SECONDS", "120"))
    except (TypeError, ValueError):
        window = 120.0
    import time as _time
    sid = doc.get("scenario_id")
    key = (sid, user.get("id"))
    now_ts = _time.monotonic()
    last = _UPLOAD_NOTIFY_STATE.get(key)
    if last is not None and (now_ts - last) < window:
        # Within the coalesce window — skip. The doc list itself already reflects
        # the new file; the broker can see everything on their next open.
        return
    _UPLOAD_NOTIFY_STATE[key] = now_ts
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0, "name": 1, "client_id": 1})
    client = None
    if scen and scen.get("client_id"):
        client = await db.users.find_one({"id": scen["client_id"]}, {"_id": 0, "name": 1, "email": 1})
    files_on_line = len(doc.get("files") or []) + 1  # include the file we just appended
    subj, html, text = tmpl_client_doc_upload(
        uploader_name=user.get("name") or "",
        uploader_email=user.get("email") or "",
        client_name=(client or {}).get("name") or "",
        scenario_name=(scen or {}).get("name") or "(untitled scenario)",
        scenario_id=sid or "",
        doc_label=doc.get("label") or "Untitled Doc",
        filename=filename,
        files_on_line=files_on_line,
    )
    for r in brokers:
        background.add_task(send_email, r, subj, html, text, "client_upload")


@api.delete("/client/docs/{doc_id}/files/{file_id}")
async def client_delete_doc_file(doc_id: str, file_id: str, request: Request, user=Depends(require_client)):
    """Borrower removes one specific file from a doc line without wiping the whole line."""
    d = await _resolve_client_doc_for_user(doc_id, user)
    if d.get("system"):
        raise HTTPException(status_code=400, detail="This line is managed by Byrd & CO.")
    # Grab filename for the audit log before deletion
    file_meta = next((fm for fm in (d.get("files") or []) if fm.get("file_id") == file_id), None)
    updated = await _remove_file_from_doc(d, file_id)
    if updated:
        updated.pop("_id", None)
    await audit_log(db, event_type="document.delete", request=request, user=user,
                    resource_type="client_doc", resource_id=doc_id,
                    resource_name=(file_meta or {}).get("filename"),
                    metadata={"file_id": file_id, "doc_label": d.get("label"),
                              "scenario_id": d.get("scenario_id")})
    return {"ok": True, "doc": updated}


@api.get("/files/{file_id}")
async def get_file(file_id: str, request: Request, download: int = 0, user=Depends(get_current_user)):
    f = await db.client_files.find_one({"id": file_id})
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    # Access control: admins can access anything; clients only their own
    if user.get("role") != "admin" and f.get("client_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    raw = base64.b64decode(f["data_b64"])
    is_download = bool(download)
    await audit_log(
        db,
        event_type=("document.download" if is_download else "document.view"),
        request=request, user=user,
        resource_type="client_file", resource_id=file_id,
        resource_name=f.get("filename"),
        metadata={"scenario_id": f.get("scenario_id"), "doc_id": f.get("doc_id"),
                  "content_type": f.get("content_type"), "size_bytes": len(raw)},
    )
    disposition = f'{"attachment" if is_download else "inline"}; filename="{f["filename"]}"'
    return Response(
        content=raw,
        media_type=f.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": disposition},
    )


# ================ Admin: quotes ================
@api.get("/admin/quotes")
async def admin_list_quotes(admin=Depends(require_admin)):
    q = await db.quotes.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return q


@api.patch("/admin/quotes/{qid}")
async def admin_update_quote(qid: str, body: dict, admin=Depends(require_admin)):
    allowed = {k: v for k, v in body.items() if k in ("read",)}
    if not allowed:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.quotes.update_one({"id": qid}, {"$set": allowed})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {"ok": True}


@api.delete("/admin/quotes/{qid}")
async def admin_delete_quote(qid: str, admin=Depends(require_admin)):
    res = await db.quotes.delete_one({"id": qid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {"ok": True}


# ================================================================
# Deal Engine — Scenarios, Lenders, Lender Shares (Phase 1 + 2)
# ================================================================
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)
from reportlab.pdfgen import canvas as pdf_canvas

BYRD_GOLD = colors.HexColor("#C89434")
BYRD_INK = colors.HexColor("#1A1A1A")
BYRD_IVORY = colors.HexColor("#FBF8F1")
BYRD_MUTED = colors.HexColor("#6B6558")
BYRD_LINE = colors.HexColor("#E4DFD1")


# ---------- Models ----------
class SponsorInfo(BaseModel):
    """Legacy single-sponsor shape — kept for backward compatibility in API bodies.
    New code should use the `Sponsor` model + `sponsors[]` array on the scenario."""
    name: Optional[str] = ""
    entity: Optional[str] = ""
    credit_score: Optional[int] = None
    liquidity: Optional[float] = None
    net_worth: Optional[float] = None


class Sponsor(BaseModel):
    id: Optional[str] = None                    # server-assigned uuid on save
    name: str = ""
    entity: Optional[str] = ""
    credit_score: Optional[int] = None
    liquidity: Optional[float] = None
    net_worth: Optional[float] = None
    ownership_pct: Optional[float] = None       # 0-100; drives is_guarantor auto-flag
    role: Literal["managing", "guarantor", "passive"] = "guarantor"
    is_guarantor: bool = True                   # derived from ownership_pct >= 20 by default; overridable
    client_user_id: Optional[str] = None        # linked client account (grants portal access to their docs)


class PropertyInfo(BaseModel):
    address: Optional[str] = ""
    city: Optional[str] = ""
    state: Optional[str] = ""
    zip: Optional[str] = ""
    property_type: Optional[str] = ""
    property_subtype: Optional[str] = ""
    year_built: Optional[int] = None
    units: Optional[int] = None
    sqft: Optional[float] = None
    purchase_price: Optional[float] = None
    current_value: Optional[float] = None
    occupancy_pct: Optional[float] = None
    occupancy_type: Optional[Literal["owner_occupied", "non_owner_occupied"]] = None
    leasehold: Optional[bool] = None
    short_term_rental: Optional[bool] = None


class LoanRequest(BaseModel):
    loan_amount: Optional[float] = None
    loan_type: Optional[str] = ""            # Purchase / Refi / Cash-Out / Construction / Bridge / Portfolio
    term_months: Optional[int] = None
    amort_months: Optional[int] = None
    requested_rate_pct: Optional[float] = None
    recourse: Optional[str] = ""             # recourse / non-recourse / partial
    estimated_closing_date: Optional[str] = None   # ISO date "YYYY-MM-DD"


class Financials(BaseModel):
    gross_income: Optional[float] = None
    vacancy_pct: Optional[float] = None
    operating_expenses: Optional[float] = None
    capex_reserves: Optional[float] = None
    override_noi: Optional[float] = None     # if borrower provides NOI directly


# --- Financial Periods (multi-year Tax Return / P&L / Pro Forma comparison) ---
class FinancialPeriodIncome(BaseModel):
    gross_potential_rent: Optional[float] = None
    vacancy_loss: Optional[float] = None          # dollar amount, typically negative or shown as positive-then-subtracted
    other_income: Optional[float] = None


class FinancialPeriodExpenses(BaseModel):
    taxes: Optional[float] = None
    insurance: Optional[float] = None
    utilities: Optional[float] = None
    repairs_maintenance: Optional[float] = None
    management: Optional[float] = None
    payroll: Optional[float] = None
    marketing: Optional[float] = None
    reserves_capex: Optional[float] = None
    general_admin: Optional[float] = None
    other_expense: Optional[float] = None


class FinancialPeriod(BaseModel):
    id: Optional[str] = None
    label: str = Field(min_length=1)                  # e.g., "2024 Tax Return", "2025 P&L", "Year 1 Pro Forma"
    doc_type: Literal["tax_return", "p_and_l", "pro_forma", "manual"] = "manual"
    year: Optional[int] = None
    is_pro_forma: bool = False
    include_reserves_in_opex: bool = True             # per-column toggle
    source_doc_id: Optional[str] = None               # optional link to uploaded doc that seeded this
    source_filename: Optional[str] = None
    income: FinancialPeriodIncome = Field(default_factory=FinancialPeriodIncome)
    expenses: FinancialPeriodExpenses = Field(default_factory=FinancialPeriodExpenses)
    notes: Optional[str] = ""


class UWAssumptions(BaseModel):
    rate_pct: Optional[float] = None                  # broker-set underwriting rate (not the borrower's target rate)
    amort_months: Optional[int] = None
    term_months: Optional[int] = None


class FinancialsExpandedPatch(BaseModel):
    # Partial-update payload for /admin/scenarios/{sid}/financials
    uw_assumptions: Optional[UWAssumptions] = None
    selected_period_id: Optional[str] = None


class FinancialPeriodCreate(FinancialPeriod):
    pass


class FinancialPeriodUpdate(BaseModel):
    label: Optional[str] = None
    doc_type: Optional[Literal["tax_return", "p_and_l", "pro_forma", "manual"]] = None
    year: Optional[int] = None
    is_pro_forma: Optional[bool] = None
    include_reserves_in_opex: Optional[bool] = None
    income: Optional[FinancialPeriodIncome] = None
    expenses: Optional[FinancialPeriodExpenses] = None
    notes: Optional[str] = None


class ConstructionBudget(BaseModel):
    total_project_cost: Optional[float] = None
    land_cost: Optional[float] = None
    hard_costs: Optional[float] = None
    soft_costs: Optional[float] = None
    contingency: Optional[float] = None


# ---------- LENDER PROSPECTS (outreach engine) ----------
class ProspectDiscoverBody(BaseModel):
    state: str = Field(min_length=2, max_length=40)


class ProspectManualBody(BaseModel):
    institution: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=2, max_length=40)
    website: Optional[str] = ""
    hq_city: Optional[str] = ""
    contact_name: Optional[str] = ""
    contact_title: Optional[str] = ""
    contact_email: Optional[str] = ""
    contact_phone: Optional[str] = ""
    notes: Optional[str] = ""


class ProspectUpdateBody(BaseModel):
    status: Optional[Literal["sourced", "queued", "drafted",
                              "approved", "sent", "replied",
                              "converted", "opted_out", "bounced"]] = None
    institution: Optional[str] = None
    state: Optional[str] = None
    website: Optional[str] = None
    hq_city: Optional[str] = None
    contact_name: Optional[str] = None
    contact_title: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    draft_subject: Optional[str] = None
    draft_body: Optional[str] = None


class SUItem(BaseModel):
    label: str
    amount: float
    category: Literal["source", "use"]


class AttachedDoc(BaseModel):
    doc_id: str
    visibility: Literal["included", "on_request"] = "on_request"


class ScenarioCreate(BaseModel):
    name: str
    client_id: Optional[str] = None
    sponsor: Optional[SponsorInfo] = None       # legacy single-sponsor (still accepted, auto-migrated)
    sponsors: List[Sponsor] = Field(default_factory=list)
    property_info: PropertyInfo = Field(default_factory=PropertyInfo)
    loan_request: LoanRequest = Field(default_factory=LoanRequest)
    financials: Financials = Field(default_factory=Financials)
    construction: Optional[ConstructionBudget] = None
    sources_uses: List[SUItem] = Field(default_factory=list)
    attached_docs: List[AttachedDoc] = Field(default_factory=list)
    notes: Optional[str] = ""
    business_plan: Optional[str] = ""
    doc_template: Optional[str] = None


class ScenarioDocCopy(BaseModel):
    source_scenario_id: str
    doc_ids: List[str] = Field(min_length=1)


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[Literal["draft", "shopping", "term_sheet", "closed", "lost"]] = None
    client_id: Optional[str] = None
    sponsor: Optional[SponsorInfo] = None                # legacy
    sponsors: Optional[List[Sponsor]] = None
    property_info: Optional[PropertyInfo] = None
    loan_request: Optional[LoanRequest] = None
    financials: Optional[Financials] = None
    construction: Optional[ConstructionBudget] = None
    sources_uses: Optional[List[SUItem]] = None
    attached_docs: Optional[List[AttachedDoc]] = None
    notes: Optional[str] = None
    business_plan: Optional[str] = None
    broker_fee_pct: Optional[float] = None  # e.g. 1.0 = 1%


class LenderContact(BaseModel):
    name: str
    title: Optional[str] = ""
    phone: Optional[str] = ""
    email: Optional[str] = ""


class LenderCreate(BaseModel):
    name: str
    institution_type: Optional[str] = "bank"   # bank / credit_union / private / agency / bridge / hard_money / other
    contacts: List[LenderContact] = Field(default_factory=list)
    property_types: List[str] = Field(default_factory=list)
    property_subtypes: List[str] = Field(default_factory=list)
    min_loan: Optional[float] = None
    max_loan: Optional[float] = None
    max_ltv: Optional[float] = None
    max_ltc: Optional[float] = None
    min_dscr: Optional[float] = None
    min_debt_yield: Optional[float] = None
    geography: List[str] = Field(default_factory=list)   # states or "nationwide"
    rate_min: Optional[float] = None
    rate_max: Optional[float] = None
    typical_term_months: Optional[int] = None
    recourse_preference: Optional[str] = ""    # recourse / non-recourse / either
    decision_speed_days: Optional[int] = None
    typical_fees: Optional[str] = ""
    notes: Optional[str] = ""
    status: Optional[Literal["active", "passive", "dormant"]] = "active"


class LenderUpdate(LenderCreate):
    name: Optional[str] = None                 # allow partial updates
    institution_type: Optional[str] = None


class ShareCreate(BaseModel):
    lender_id: Optional[str] = None
    recipient_name: Optional[str] = ""         # if not from directory
    recipient_email: Optional[EmailStr] = None
    recipient_institution: Optional[str] = ""
    note: Optional[str] = ""
    # Per-doc visibility override for this specific share, keyed by doc_id.
    # Falls back to scenario-level visibility if omitted.
    doc_overrides: Optional[Dict[str, Literal["include", "on_request", "hidden"]]] = None


class ShareOverridesUpdate(BaseModel):
    doc_overrides: Dict[str, Literal["include", "on_request", "hidden"]]


class LenderGate(BaseModel):
    viewer_name: str = Field(min_length=1)
    viewer_email: EmailStr
    viewer_institution: str = Field(min_length=1)
    # Lightweight confidentiality acknowledgement — required. Captured on every session
    # (a lender opening the same deal in a new browser must acknowledge again).
    acknowledged: bool = False
    acknowledged_version: Optional[str] = None


class LenderDocAccessAction(BaseModel):
    action: Literal["approve", "revoke"]


# ---------- Sizing engine ----------
def _period_totals(period: dict) -> dict:
    """Compute EGI, total OpEx, NOI from a single financial period dict."""
    inc = period.get("income") or {}
    exp = period.get("expenses") or {}
    gpr = float(inc.get("gross_potential_rent") or 0)
    vac = float(inc.get("vacancy_loss") or 0)   # dollars
    oth = float(inc.get("other_income") or 0)
    egi = gpr - abs(vac) + oth
    exp_keys = ("taxes", "insurance", "utilities", "repairs_maintenance", "management",
                "payroll", "marketing", "general_admin", "other_expense")
    opex = sum(float(exp.get(k) or 0) for k in exp_keys)
    if period.get("include_reserves_in_opex", True):
        opex += float(exp.get("reserves_capex") or 0)
    noi = egi - opex
    return {"egi": round(egi, 2), "total_expenses": round(opex, 2), "noi": round(noi, 2)}


def _period_computed(period: dict) -> dict:
    """Return the period doc with its computed totals attached (for API responses)."""
    p = dict(period)
    p["_computed"] = _period_totals(p)
    return p


def _selected_period(scen: dict) -> Optional[dict]:
    """Return the currently-selected period (with _computed attached), or None."""
    fin = scen.get("financials") or {}
    periods = fin.get("periods") or []
    if not periods:
        return None
    sel_id = fin.get("selected_period_id")
    match = next((p for p in periods if p.get("id") == sel_id), None)
    if not match:
        match = periods[0]
    return _period_computed(match)


def _calc_noi(fin: dict) -> Optional[float]:
    if not fin:
        return None
    if fin.get("override_noi") is not None:
        return float(fin["override_noi"])
    gross = fin.get("gross_income")
    if gross is None:
        return None
    vac = float(fin.get("vacancy_pct") or 0) / 100.0
    opex = float(fin.get("operating_expenses") or 0)
    reserves = float(fin.get("capex_reserves") or 0)
    return round(float(gross) * (1 - vac) - opex - reserves, 2)


def _monthly_payment(loan_amount: float, annual_rate_pct: float, amort_months: int) -> Optional[float]:
    if not loan_amount or not amort_months:
        return None
    r = (annual_rate_pct or 0) / 100.0 / 12.0
    n = amort_months
    if r == 0:
        return round(loan_amount / n, 2)
    pmt = loan_amount * r * (1 + r) ** n / ((1 + r) ** n - 1)
    return round(pmt, 2)


def _property_value(prop: dict) -> Optional[float]:
    if not prop:
        return None
    pv = prop.get("purchase_price")
    cv = prop.get("current_value")
    if pv and cv:
        return max(float(pv), float(cv))
    return float(pv or cv or 0) or None


def _total_project_cost(prop: dict, con: dict) -> Optional[float]:
    if con:
        tpc = con.get("total_project_cost")
        if tpc:
            return float(tpc)
        parts = [con.get("land_cost"), con.get("hard_costs"), con.get("soft_costs"), con.get("contingency")]
        if any(p is not None for p in parts):
            return round(sum(float(p or 0) for p in parts), 2)
    return _property_value(prop)


def compute_scenario_metrics(scen: dict) -> dict:
    prop = scen.get("property_info") or {}
    loan = scen.get("loan_request") or {}
    fin = scen.get("financials") or {}
    con = scen.get("construction") or {}
    su = scen.get("sources_uses") or []

    loan_amount = float(loan.get("loan_amount") or 0) or None

    # UW rate/amort/term: prefer explicit UW assumptions on financials (broker-set for lender review).
    # Falls back to the borrower's target on loan_request for backward-compat only.
    uw = fin.get("uw_assumptions") or {}
    rate = float(uw.get("rate_pct") or loan.get("requested_rate_pct") or 0) or None
    amort = int(uw.get("amort_months") or loan.get("amort_months") or 0) or None
    uw_source = "uw" if uw.get("rate_pct") else ("loan_request" if loan.get("requested_rate_pct") else None)

    property_value = _property_value(prop)
    tpc = _total_project_cost(prop, con)

    # NOI: prefer the selected financial period; fall back to legacy Financials block.
    sel = _selected_period(scen)
    if sel:
        noi = sel["_computed"]["noi"]
        noi_source = {
            "period_id": sel.get("id"),
            "label": sel.get("label"),
            "is_pro_forma": bool(sel.get("is_pro_forma")),
            "doc_type": sel.get("doc_type"),
        }
    else:
        noi = _calc_noi(fin)
        noi_source = {"legacy": True} if noi is not None else None

    monthly_pmt = _monthly_payment(loan_amount, rate, amort) if (loan_amount and rate and amort) else None
    annual_ds = round(monthly_pmt * 12, 2) if monthly_pmt else None

    ltv = round(loan_amount / property_value * 100, 2) if (loan_amount and property_value) else None
    ltc = round(loan_amount / tpc * 100, 2) if (loan_amount and tpc) else None
    dscr = round(noi / annual_ds, 2) if (noi is not None and annual_ds) else None
    debt_yield = round(noi / loan_amount * 100, 2) if (noi is not None and loan_amount) else None

    sources_total = round(sum(float(x.get("amount") or 0) for x in su if x.get("category") == "source"), 2)
    uses_total = round(sum(float(x.get("amount") or 0) for x in su if x.get("category") == "use"), 2)
    su_balanced = abs(sources_total - uses_total) < 1.0

    # Cash-on-cash: NOI - annual_ds divided by equity (uses_total - loan_amount) if available
    equity = None
    if uses_total and loan_amount:
        equity = round(uses_total - loan_amount, 2)
    coc = None
    if noi is not None and annual_ds and equity and equity > 0:
        annual_cf = noi - annual_ds
        coc = round(annual_cf / equity * 100, 2)

    return {
        "property_value": property_value,
        "total_project_cost": tpc,
        "noi": noi,
        "noi_source": noi_source,
        "monthly_payment": monthly_pmt,
        "annual_debt_service": annual_ds,
        "uw_rate_pct": rate,
        "uw_amort_months": amort,
        "uw_source": uw_source,
        "ltv_pct": ltv,
        "ltc_pct": ltc,
        "dscr": dscr,
        "debt_yield_pct": debt_yield,
        "cash_on_cash_pct": coc,
        "sources_total": sources_total,
        "uses_total": uses_total,
        "sources_uses_balanced": su_balanced,
        "equity_required": equity,
    }


# Lender-side vocabulary sometimes uses slightly different labels than the deal-side
# (legacy: "Hospitality", "Self-storage", "Mixed-use"). Normalise before matching so we
# don't drop a fit for a cosmetic label difference. Mirror `canonicalPropertyType` in
# `/app/frontend/src/byrd/dealData.js`.
_PROPERTY_TYPE_ALIASES = {
    "hospitality": "hotel",
    "self-storage": "self storage",
    "mixed-use": "multifamily",
    "mixed use": "multifamily",
    "medical office": "office",
}
def _canon_ptype(raw: str) -> str:
    if not raw:
        return ""
    key = raw.strip().lower()
    return _PROPERTY_TYPE_ALIASES.get(key, key)


def match_lenders(scen: dict, lenders: List[dict]) -> List[dict]:
    prop = scen.get("property_info") or {}
    loan = scen.get("loan_request") or {}
    metrics = compute_scenario_metrics(scen)
    loan_amount = float(loan.get("loan_amount") or 0) or None
    ptype = _canon_ptype(prop.get("property_type") or "")
    psub = (prop.get("property_subtype") or "").lower()
    state = (prop.get("state") or "").upper()
    ltv = metrics.get("ltv_pct")
    dscr = metrics.get("dscr")
    dy = metrics.get("debt_yield_pct")

    results = []
    for l in lenders:
        reasons_fit = []
        reasons_miss = []
        # property type
        pt_list = [_canon_ptype(p) for p in (l.get("property_types") or [])]
        sub_list = [s.lower() for s in (l.get("property_subtypes") or [])]
        if pt_list and ptype:
            if ptype in pt_list or "other" in pt_list:
                reasons_fit.append(f"lends on {prop.get('property_type')}")
                # Refine on sub-type when both sides have declared one — a specialist
                # gets an EXTRA "specializes in" fit so they outrank a generic top-level
                # lender for the same deal.
                if psub and sub_list:
                    if psub in sub_list:
                        reasons_fit.append(f"specializes in {prop.get('property_subtype')}")
                    else:
                        reasons_miss.append(f"doesn't specialize in {prop.get('property_subtype')}")
            else:
                reasons_miss.append(f"doesn't lend on {prop.get('property_type')}")
        # size
        if loan_amount:
            mn, mx = l.get("min_loan"), l.get("max_loan")
            if mn and loan_amount < mn:
                reasons_miss.append(f"below min ${int(mn):,}")
            elif mx and loan_amount > mx:
                reasons_miss.append(f"above max ${int(mx):,}")
            elif mn or mx:
                reasons_fit.append("size fits")
        # LTV
        if ltv is not None and l.get("max_ltv") is not None:
            if ltv <= l["max_ltv"]:
                reasons_fit.append(f"LTV {ltv}% ≤ {l['max_ltv']}%")
            else:
                reasons_miss.append(f"LTV {ltv}% > {l['max_ltv']}%")
        # DSCR
        if dscr is not None and l.get("min_dscr") is not None:
            if dscr >= l["min_dscr"]:
                reasons_fit.append(f"DSCR {dscr} ≥ {l['min_dscr']}")
            else:
                reasons_miss.append(f"DSCR {dscr} < {l['min_dscr']}")
        # Debt yield
        if dy is not None and l.get("min_debt_yield") is not None:
            if dy >= l["min_debt_yield"]:
                reasons_fit.append(f"DY {dy}% ≥ {l['min_debt_yield']}%")
            else:
                reasons_miss.append(f"DY {dy}% < {l['min_debt_yield']}%")
        # geography
        geo = [g.upper() for g in (l.get("geography") or [])]
        if geo and state:
            if state in geo or "NATIONWIDE" in geo:
                reasons_fit.append(f"lends in {state}")
            else:
                reasons_miss.append(f"not in {state}")

        score = len(reasons_fit) - len(reasons_miss) * 2
        results.append({
            "lender": l,
            "score": score,
            "fits": reasons_fit,
            "misses": reasons_miss,
            "verdict": "fit" if len(reasons_miss) == 0 and reasons_fit else ("partial" if reasons_fit else "miss"),
        })
    results.sort(key=lambda x: (-x["score"], x["lender"].get("name", "")))
    return results


# ---------- PDF generation ----------
def _watermark_canvas(watermark_text: str):
    """Returns a function suitable for onPage callback."""
    def draw(canv: pdf_canvas.Canvas, doc):
        if not watermark_text:
            return
        canv.saveState()
        canv.translate(4.25 * inch, 5.5 * inch)
        canv.rotate(30)
        canv.setFillColor(colors.Color(0.75, 0.55, 0.15, alpha=0.10))
        canv.setFont("Helvetica-Bold", 60)
        canv.drawCentredString(0, 0, watermark_text.upper())
        canv.restoreState()

        # Footer stamp
        canv.saveState()
        canv.setFillColor(BYRD_MUTED)
        canv.setFont("Helvetica", 8)
        canv.drawString(0.75 * inch, 0.5 * inch,
                        f"Confidential — prepared for {watermark_text} · Byrd & CO Commercial RE Lending")
        canv.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}")
        canv.restoreState()
    return draw


def _fmt_money(v):
    if v is None or v == "":
        return "—"
    try:
        return f"${float(v):,.0f}"
    except Exception:
        return str(v)


def _fmt_pct(v, digits=2):
    if v is None or v == "":
        return "—"
    return f"{float(v):.{digits}f}%"


def _fmt_num(v):
    if v is None or v == "":
        return "—"
    return f"{v}"


def render_scenario_pdf(scen: dict, client: Optional[dict], metrics: dict, watermark_text: str = "") -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.85 * inch, bottomMargin=0.85 * inch,
                            title=f"Byrd & CO — {scen.get('name', 'Loan Package')}")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                        fontSize=22, leading=26, textColor=BYRD_INK, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                        fontSize=13, leading=16, textColor=BYRD_INK, spaceBefore=12, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=10, leading=14, textColor=BYRD_INK)
    small = ParagraphStyle("small", parent=styles["BodyText"], fontName="Helvetica",
                           fontSize=8, leading=11, textColor=BYRD_MUTED)

    elements = []
    # Header block
    elements.append(Paragraph("BYRD &amp; CO", ParagraphStyle("brand", fontName="Helvetica-Bold",
                                                              fontSize=10, textColor=BYRD_GOLD, spaceAfter=2)))
    elements.append(Paragraph("Commercial Real Estate Lending", small))
    elements.append(Spacer(1, 14))
    elements.append(Paragraph(scen.get("name") or "Loan Package", h1))
    prop = scen.get("property_info") or {}
    loan = scen.get("loan_request") or {}
    addr_bits = [prop.get("address"), prop.get("city"), prop.get("state"), prop.get("zip")]
    addr = ", ".join([b for b in addr_bits if b])
    if addr:
        elements.append(Paragraph(addr, body))
    if loan.get("loan_type") or loan.get("loan_amount"):
        elements.append(Paragraph(
            f"<b>{loan.get('loan_type') or 'Loan'}</b> · {_fmt_money(loan.get('loan_amount'))} requested",
            body,
        ))

    # Executive Numbers
    elements.append(Paragraph("Executive Summary", h2))
    def cell(label, val):
        return [Paragraph(f"<font color='#6B6558' size=8>{label}</font>", small),
                Paragraph(f"<b>{val}</b>", body)]
    grid = [
        [Paragraph("<b>Loan Amount</b>", body), _fmt_money(loan.get("loan_amount")),
         Paragraph("<b>Property Value</b>", body), _fmt_money(metrics.get("property_value"))],
        [Paragraph("<b>LTV</b>", body), _fmt_pct(metrics.get("ltv_pct")),
         Paragraph("<b>LTC</b>", body), _fmt_pct(metrics.get("ltc_pct"))],
        [Paragraph("<b>NOI</b>", body), _fmt_money(metrics.get("noi")),
         Paragraph("<b>Debt Yield</b>", body), _fmt_pct(metrics.get("debt_yield_pct"))],
        [Paragraph("<b>DSCR</b>", body), _fmt_num(metrics.get("dscr")),
         Paragraph("<b>Cash-on-Cash</b>", body), _fmt_pct(metrics.get("cash_on_cash_pct"))],
        [Paragraph("<b>Monthly P&amp;I</b>", body), _fmt_money(metrics.get("monthly_payment")),
         Paragraph("<b>Annual Debt Service</b>", body), _fmt_money(metrics.get("annual_debt_service"))],
    ]
    t = Table(grid, colWidths=[1.5 * inch, 1.6 * inch, 1.5 * inch, 1.6 * inch])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, BYRD_LINE),
        ("BACKGROUND", (0, 0), (0, -1), BYRD_IVORY),
        ("BACKGROUND", (2, 0), (2, -1), BYRD_IVORY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t)

    # Property & Sponsor
    elements.append(Paragraph("Property", h2))
    prop_rows = [
        ["Type", prop.get("property_type") or "—", "Year Built", _fmt_num(prop.get("year_built"))],
        ["Units", _fmt_num(prop.get("units")), "Sq Ft", _fmt_num(prop.get("sqft"))],
        ["Purchase Price", _fmt_money(prop.get("purchase_price")),
         "Current Value", _fmt_money(prop.get("current_value"))],
        ["Occupancy", _fmt_pct(prop.get("occupancy_pct"), 1), "", ""],
    ]
    t2 = Table(prop_rows, colWidths=[1.5 * inch, 1.6 * inch, 1.5 * inch, 1.6 * inch])
    _kv_style = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, BYRD_LINE),
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("BACKGROUND", (0, 0), (0, -1), BYRD_IVORY),
        ("BACKGROUND", (2, 0), (2, -1), BYRD_IVORY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ])
    t2.setStyle(_kv_style)
    elements.append(t2)

    sponsor = scen.get("sponsor") or {}
    if any(sponsor.values()):
        elements.append(Paragraph("Sponsor", h2))
        sp_rows = [
            ["Name", sponsor.get("name") or "—", "Entity", sponsor.get("entity") or "—"],
            ["FICO", _fmt_num(sponsor.get("credit_score")), "Liquidity", _fmt_money(sponsor.get("liquidity"))],
            ["Net Worth", _fmt_money(sponsor.get("net_worth")), "", ""],
        ]
        t3 = Table(sp_rows, colWidths=[1.5 * inch, 1.6 * inch, 1.5 * inch, 1.6 * inch])
        t3.setStyle(_kv_style)
        elements.append(t3)

    # Loan Request detail
    elements.append(Paragraph("Loan Request", h2))
    lr_rows = [
        ["Type", loan.get("loan_type") or "—", "Amount", _fmt_money(loan.get("loan_amount"))],
        ["Requested Rate", _fmt_pct(loan.get("requested_rate_pct"), 3),
         "Amortization", _fmt_num(loan.get("amort_months")) + (" mo" if loan.get("amort_months") else "")],
        ["Term", _fmt_num(loan.get("term_months")) + (" mo" if loan.get("term_months") else ""),
         "Recourse", loan.get("recourse") or "—"],
    ]
    t4 = Table(lr_rows, colWidths=[1.5 * inch, 1.6 * inch, 1.5 * inch, 1.6 * inch])
    t4.setStyle(_kv_style)
    elements.append(t4)

    # Sources & Uses
    su = scen.get("sources_uses") or []
    if su:
        elements.append(Paragraph("Sources &amp; Uses", h2))
        sources = [x for x in su if x.get("category") == "source"]
        uses = [x for x in su if x.get("category") == "use"]

        def su_table(items, header):
            rows = [[header, "Amount"]]
            for it in items:
                rows.append([it.get("label", ""), _fmt_money(it.get("amount"))])
            total = sum(float(it.get("amount") or 0) for it in items)
            rows.append(["Total", _fmt_money(total)])
            tt = Table(rows, colWidths=[3.2 * inch, 3.0 * inch])
            tt.setStyle(TableStyle([
                ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
                ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 10),
                ("BACKGROUND", (0, 0), (-1, 0), BYRD_INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, -1), (-1, -1), BYRD_IVORY),
                ("GRID", (0, 0), (-1, -1), 0.5, BYRD_LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            return tt

        if sources:
            elements.append(su_table(sources, "Sources"))
            elements.append(Spacer(1, 6))
        if uses:
            elements.append(su_table(uses, "Uses"))

    # Business plan (Notes are broker-internal — never rendered on the lender-facing PDF)
    if scen.get("business_plan"):
        elements.append(Paragraph("Business Plan", h2))
        elements.append(Paragraph(scen["business_plan"].replace("\n", "<br/>"), body))

    doc.build(elements, onFirstPage=_watermark_canvas(watermark_text), onLaterPages=_watermark_canvas(watermark_text))
    return buf.getvalue()


# ---------- SCENARIOS: admin routes ----------
def _clean_scenario(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


def _ensure_sponsors_array(scen: dict) -> list:
    """Backward-compat: if scenario has legacy `sponsor` (single obj) but no `sponsors[]`,
    convert on-the-fly. Assigns an id to each sponsor. Also auto-flags is_guarantor for
    ownership >= 20% when explicit flag missing."""
    sponsors = scen.get("sponsors")
    if not isinstance(sponsors, list) or not sponsors:
        legacy = scen.get("sponsor") or {}
        if any(v not in (None, "", 0) for v in legacy.values()):
            sponsors = [{
                "id": str(uuid.uuid4()),
                "name": legacy.get("name") or "",
                "entity": legacy.get("entity") or "",
                "credit_score": legacy.get("credit_score"),
                "liquidity": legacy.get("liquidity"),
                "net_worth": legacy.get("net_worth"),
                "ownership_pct": 100,
                "role": "managing",
                "is_guarantor": True,
                "client_user_id": scen.get("client_id"),
            }]
        else:
            sponsors = []
    # Fill missing ids + auto-flag guarantors
    for s in sponsors:
        if not s.get("id"):
            s["id"] = str(uuid.uuid4())
        if s.get("is_guarantor") is None:
            op = s.get("ownership_pct")
            s["is_guarantor"] = bool(op is not None and op >= 20)
        s.setdefault("role", "guarantor")
    return sponsors


async def _hydrate_sponsors(sponsors: list) -> list:
    """Attach {client:{name,email}} to each sponsor with a client_user_id."""
    out = []
    for s in sponsors:
        s2 = dict(s)
        if s2.get("client_user_id"):
            u = await db.users.find_one({"id": s2["client_user_id"]},
                                       {"_id": 0, "name": 1, "email": 1, "id": 1})
            if u:
                s2["client"] = u
        out.append(s2)
    return out


# ---------- MULTI-FILE UPLOADS PER DOC LINE ----------
# A client_docs row can hold many attached files (e.g., 3 years of tax returns
# on a single "Tax Returns" line). Storage stays in `client_files`. Each doc row
# tracks a `files: []` audit list. Legacy `file_id` remains the "latest" pointer
# for backward compat with older code paths.

def _ensure_doc_files_meta(doc: dict) -> list[dict]:
    """Return the list of file-meta dicts attached to a doc row.
    Migrates legacy `file_id`-only rows into a 1-item array on read."""
    files = doc.get("files")
    if isinstance(files, list) and files:
        return files
    if doc.get("file_id"):
        return [{
            "file_id": doc["file_id"],
            "filename": doc.get("filename") or "document",
            "content_type": doc.get("content_type"),
            "size": doc.get("size"),
            "uploaded_at": doc.get("updated_at") or doc.get("created_at"),
            "uploaded_by": "client",
        }]
    return []


async def _populate_doc_files(docs: list[dict]) -> None:
    """Attach a `files` array of {id, filename, content_type, size, uploaded_at, uploaded_by}
    to each doc, hydrated from the client_files collection. Never includes file bytes.
    Also keeps the legacy `file` object (latest single file) so old UIs still work."""
    all_file_ids = set()
    per_doc_metas = []
    for d in docs:
        metas = _ensure_doc_files_meta(d)
        per_doc_metas.append(metas)
        for m in metas:
            if m.get("file_id"):
                all_file_ids.add(m["file_id"])
    files_by_id: dict[str, dict] = {}
    if all_file_ids:
        async for f in db.client_files.find(
            {"id": {"$in": list(all_file_ids)}}, {"_id": 0, "data_b64": 0},
        ):
            files_by_id[f["id"]] = f
    for d, metas in zip(docs, per_doc_metas):
        out = []
        for m in metas:
            f = files_by_id.get(m.get("file_id")) or {}
            out.append({
                "id": m.get("file_id"),
                "filename": m.get("filename") or f.get("filename") or "document",
                "content_type": m.get("content_type") or f.get("content_type"),
                "size": m.get("size") if m.get("size") is not None else f.get("size"),
                "uploaded_at": m.get("uploaded_at") or f.get("uploaded_at"),
                "uploaded_by": m.get("uploaded_by") or "client",
            })
        d["files"] = out
        # Legacy `file` mirror = latest file (for older UI paths)
        if out and d.get("file_id"):
            latest = files_by_id.get(d["file_id"])
            if latest:
                d["file"] = latest


async def _append_file_to_doc(doc: dict, data_b64: str, filename: str, content_type: str,
                              uploaded_by: str = "client") -> dict:
    """Insert a client_files row and append meta to doc.files[]. Also updates the
    legacy file_id/filename/size fields to point to the latest file so older code
    that reads them still works. Sets status to 'uploaded' when at least one file exists.
    Returns the meta dict of the newly added file."""
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_FILE_MB}MB limit")
    file_id = str(uuid.uuid4())
    now = now_iso()
    await db.client_files.insert_one({
        "id": file_id,
        "doc_id": doc["id"],
        "client_id": doc.get("client_id"),
        "scenario_id": doc.get("scenario_id"),
        "filename": filename,
        "content_type": content_type,
        "size": len(raw),
        "data_b64": data_b64,
        "uploaded_at": now,
        "uploaded_by": uploaded_by,
    })
    meta = {
        "file_id": file_id,
        "filename": filename,
        "content_type": content_type,
        "size": len(raw),
        "uploaded_at": now,
        "uploaded_by": uploaded_by,
    }
    # Migrate legacy row: if `files` doesn't exist yet, seed from current file_id.
    existing_files = _ensure_doc_files_meta(doc)
    new_files = list(existing_files) + [meta]
    # De-dupe against the case where legacy meta already points to same file_id
    # (shouldn't happen for a new upload — new id is uuid — but guard anyway):
    seen = set()
    deduped = []
    for m in new_files:
        fid = m.get("file_id")
        if fid in seen:
            continue
        seen.add(fid)
        deduped.append(m)
    await db.client_docs.update_one(
        {"id": doc["id"]},
        {"$set": {
            "files": deduped,
            "file_id": file_id,  # legacy: latest file
            "filename": filename,
            "content_type": content_type,
            "size": len(raw),
            "status": "uploaded",
            "updated_at": now,
        }},
    )
    return meta


async def _remove_file_from_doc(doc: dict, file_id: str) -> dict:
    """Remove one file (by file_id) from a doc line. Deletes the underlying blob.
    If no files remain, resets status back to 'pending' and clears legacy pointers.
    Returns the refreshed doc."""
    metas = _ensure_doc_files_meta(doc)
    remaining = [m for m in metas if m.get("file_id") != file_id]
    if len(remaining) == len(metas):
        raise HTTPException(status_code=404, detail="File not attached to this doc")
    # Delete the underlying blob (only if not referenced elsewhere)
    other_ref = await db.client_docs.find_one(
        {"id": {"$ne": doc["id"]}, "files.file_id": file_id},
        {"_id": 0, "id": 1},
    )
    if not other_ref:
        legacy_ref = await db.client_docs.find_one(
            {"id": {"$ne": doc["id"]}, "file_id": file_id},
            {"_id": 0, "id": 1},
        )
        if not legacy_ref:
            await db.client_files.delete_one({"id": file_id})
    # Recompute latest pointer
    now = now_iso()
    if remaining:
        latest = remaining[-1]
        set_fields = {
            "files": remaining,
            "file_id": latest.get("file_id"),
            "filename": latest.get("filename"),
            "content_type": latest.get("content_type"),
            "size": latest.get("size"),
            "status": "uploaded",
            "updated_at": now,
        }
        await db.client_docs.update_one({"id": doc["id"]}, {"$set": set_fields})
    else:
        await db.client_docs.update_one(
            {"id": doc["id"]},
            {"$set": {"files": [], "status": "pending", "updated_at": now},
             "$unset": {"file_id": "", "filename": "", "content_type": "", "size": ""}},
        )
    return await db.client_docs.find_one({"id": doc["id"]}, {"_id": 0})


@api.get("/admin/scenarios/doc-templates")
async def list_doc_templates(admin=Depends(require_admin)):
    """Preset checklists a broker can pick when starting a new scenario."""
    return [
        {"key": k, "label": v["label"], "description": v["description"], "item_count": len(v["items"])}
        for k, v in DOC_TEMPLATES.items()
    ]


@api.post("/admin/scenarios")
async def create_scenario(body: ScenarioCreate, request: Request, admin=Depends(require_admin)):
    if body.client_id:
        client = await db.users.find_one({"id": body.client_id, "role": "client"})
        if not client:
            raise HTTPException(status_code=400, detail="Client not found")
    payload = body.model_dump()
    # Merge legacy `sponsor` into `sponsors[]` if provided that way
    legacy = payload.pop("sponsor", None)
    sponsors = payload.pop("sponsors", []) or []
    if legacy and any(v not in (None, "", 0) for v in (legacy or {}).values()) and not sponsors:
        sponsors = [{
            "id": str(uuid.uuid4()),
            "name": legacy.get("name") or "",
            "entity": legacy.get("entity") or "",
            "credit_score": legacy.get("credit_score"),
            "liquidity": legacy.get("liquidity"),
            "net_worth": legacy.get("net_worth"),
            "ownership_pct": 100,
            "role": "managing",
            "is_guarantor": True,
            "client_user_id": body.client_id,
        }]
    # Ensure every sponsor has an id + auto-flag guarantors + at least one "managing"
    has_managing = False
    for s in sponsors:
        if not s.get("id"):
            s["id"] = str(uuid.uuid4())
        if s.get("is_guarantor") is None:
            op = s.get("ownership_pct")
            s["is_guarantor"] = bool(op is not None and op >= 20)
        if s.get("role") == "managing":
            has_managing = True
    if sponsors and not has_managing:
        sponsors[0]["role"] = "managing"
    template_key = payload.pop("doc_template", None) or DEFAULT_SCENARIO_TEMPLATE_KEY
    if template_key not in DOC_TEMPLATES:
        template_key = DEFAULT_SCENARIO_TEMPLATE_KEY
    sid = str(uuid.uuid4())
    now = now_iso()
    doc = {
        "id": sid,
        "broker_id": admin["id"],
        "status": "draft",
        **payload,
        "sponsors": sponsors,
        "doc_template": template_key,
        "created_at": now,
        "updated_at": now,
    }
    await db.scenarios.insert_one(doc)
    # Seed scenario doc checklist from the chosen template
    # Personal-category docs auto-scope to the Managing sponsor. Others = shared (sponsor_id=None).
    managing = next((s for s in sponsors if s.get("role") == "managing"), None)
    managing_id = managing["id"] if managing else None
    template_items = DOC_TEMPLATES[template_key]["items"]
    PERSONAL_CATEGORIES = {"Personal", "Personal Financial"}
    for i, item in enumerate(template_items):
        cat = item.get("category", "Other")
        is_personal = cat in PERSONAL_CATEGORIES or "PFS" in item.get("label", "") or "Tax Return" in item.get("label", "")
        await db.client_docs.insert_one({
            "id": str(uuid.uuid4()),
            "scenario_id": sid,
            "client_id": body.client_id,
            "sponsor_id": managing_id if is_personal else None,
            "label": item.get("label", "Document"),
            "category": cat,
            "required": item.get("required", True),
            "status": "pending",
            "notes": "",
            "file_id": None,
            "order": i,
            "created_at": now,
            "updated_at": now,
        })
    await audit_log(db, event_type="scenario.create", request=request, user=admin,
                    resource_type="scenario", resource_id=sid,
                    resource_name=doc.get("name"),
                    metadata={"client_id": body.client_id, "template": template_key})
    return _clean_scenario(doc)


@api.get("/admin/scenarios")
async def list_scenarios(admin=Depends(require_admin)):
    docs = await db.scenarios.find({}, {"_id": 0}).sort("updated_at", -1).to_list(500)
    for d in docs:
        d["metrics"] = compute_scenario_metrics(d)
        d["share_count"] = await db.scenario_shares.count_documents({"scenario_id": d["id"]})
        if d.get("client_id"):
            client = await db.users.find_one({"id": d["client_id"]}, {"_id": 0, "name": 1, "email": 1})
            d["client"] = client
    return docs


@api.get("/admin/scenarios/{sid}")
async def get_scenario(sid: str, admin=Depends(require_admin)):
    d = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    d["metrics"] = compute_scenario_metrics(d)
    if d.get("client_id"):
        client = await db.users.find_one({"id": d["client_id"]}, {"_id": 0, "password_hash": 0})
        d["client"] = client
    # Ensure sponsors[] exists (auto-migrate from legacy sponsor)
    sponsors = _ensure_sponsors_array(d)
    d["sponsors"] = await _hydrate_sponsors(sponsors)
    docs = await db.client_docs.find({"scenario_id": sid}, {"_id": 0}).sort("order", 1).to_list(500)
    await _populate_doc_files(docs)
    d["docs"] = docs
    d["client_docs"] = docs
    d["shares"] = await db.scenario_shares.find({"scenario_id": sid}, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Fee agreements per sponsor
    fas = await db.fee_agreements.find({"scenario_id": sid}, {"_id": 0}).sort("created_at", -1).to_list(50)
    d["fee_agreements"] = fas
    return d


@api.patch("/admin/scenarios/{sid}")
async def update_scenario(sid: str, body: ScenarioUpdate, request: Request, admin=Depends(require_admin)):
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    # If caller supplied sponsors[] — normalize (ensure ids, enforce single 'managing')
    if "sponsors" in update:
        sponsors = update["sponsors"] or []
        managing_indices = []
        for i, s in enumerate(sponsors):
            if not s.get("id"):
                s["id"] = str(uuid.uuid4())
            if s.get("role") == "managing":
                managing_indices.append(i)
        if len(managing_indices) > 1:
            # Multiple managings after normalization — keep the LAST one, demote the rest
            keeper = managing_indices[-1]
            for i in managing_indices[:-1]:
                sponsors[i]["role"] = "guarantor"
        elif not managing_indices and sponsors:
            sponsors[0]["role"] = "managing"
        update["sponsors"] = sponsors
        # Drop legacy sponsor if we're moving to array shape
        update["sponsor"] = None
    update["updated_at"] = now_iso()
    res = await db.scenarios.update_one({"id": sid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    d = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    d["metrics"] = compute_scenario_metrics(d)
    await audit_log(db, event_type="scenario.update", request=request, user=admin,
                    resource_type="scenario", resource_id=sid,
                    resource_name=d.get("name"),
                    metadata={"fields": sorted([k for k in update.keys() if k != "updated_at"])})
    return d


@api.delete("/admin/scenarios/{sid}")
async def delete_scenario(sid: str, request: Request, admin=Depends(require_admin)):
    scen_before = await db.scenarios.find_one({"id": sid}, {"_id": 0, "name": 1, "client_id": 1})
    res = await db.scenarios.delete_one({"id": sid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    # Cascade: drop scenario docs + their files + share metadata
    docs = await db.client_docs.find(
        {"scenario_id": sid}, {"_id": 0, "file_id": 1, "files": 1},
    ).to_list(2000)
    file_ids = set()
    for d in docs:
        if d.get("file_id"):
            file_ids.add(d["file_id"])
        for m in (d.get("files") or []):
            if m.get("file_id"):
                file_ids.add(m["file_id"])
    if file_ids:
        await db.client_files.delete_many({"id": {"$in": list(file_ids)}})
    await db.client_docs.delete_many({"scenario_id": sid})
    await db.scenario_shares.delete_many({"scenario_id": sid})
    await db.share_views.delete_many({"scenario_id": sid})
    await audit_log(db, event_type="scenario.delete", request=request, user=admin,
                    resource_type="scenario", resource_id=sid,
                    resource_name=(scen_before or {}).get("name"),
                    metadata={"cascaded_files": len(file_ids), "cascaded_docs": len(docs)})
    return {"ok": True}


# ---------- Scenario document checklist ----------
@api.post("/admin/scenarios/{sid}/docs")
async def scenario_add_doc(sid: str, body: DocCreate, admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0, "client_id": 1})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    last = await db.client_docs.find({"scenario_id": sid}).sort("order", -1).to_list(1)
    next_order = (last[0]["order"] + 1) if last else 0
    now = now_iso()
    doc = {
        "id": str(uuid.uuid4()),
        "scenario_id": sid,
        "client_id": scen.get("client_id"),
        "sponsor_id": body.sponsor_id or None,
        "label": body.label,
        "category": body.category or "Other",
        "required": body.required,
        "status": "pending",
        "notes": "",
        "file_id": None,
        "files": [],
        "order": next_order,
        "created_at": now,
        "updated_at": now,
    }
    await db.client_docs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.patch("/admin/scenarios/{sid}/docs/{doc_id}")
async def scenario_update_doc(sid: str, doc_id: str, body: DocUpdate, admin=Depends(require_admin)):
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    # Empty-string sponsor_id => clear to None
    if update.get("sponsor_id") == "":
        update["sponsor_id"] = None
    update["updated_at"] = now_iso()
    res = await db.client_docs.update_one({"id": doc_id, "scenario_id": sid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Doc not found")
    d = await db.client_docs.find_one({"id": doc_id}, {"_id": 0})
    return d


@api.delete("/admin/scenarios/{sid}/docs/{doc_id}")
async def scenario_delete_doc(sid: str, doc_id: str, request: Request, admin=Depends(require_admin)):
    d = await db.client_docs.find_one({"id": doc_id, "scenario_id": sid})
    if not d:
        raise HTTPException(status_code=404, detail="Doc not found")
    if d.get("system"):
        raise HTTPException(status_code=400, detail="This document line is system-managed and can't be deleted here.")
    # Delete every file attached to this line (both legacy file_id + new files[])
    file_ids = {m.get("file_id") for m in _ensure_doc_files_meta(d) if m.get("file_id")}
    if file_ids:
        await db.client_files.delete_many({"id": {"$in": list(file_ids)}})
    await db.client_docs.delete_one({"id": doc_id})
    # Clean up any share overrides that pointed to this doc
    await db.scenario_shares.update_many(
        {"scenario_id": sid},
        {"$unset": {f"doc_overrides.{doc_id}": ""}, "$pull": {"doc_grants": doc_id}},
    )
    await audit_log(db, event_type="document.delete", request=request, user=admin,
                    resource_type="client_doc", resource_id=doc_id,
                    resource_name=d.get("label"),
                    metadata={"scenario_id": sid, "file_ids": list(file_ids), "reason": "line_delete"})
    return {"ok": True}


@api.post("/admin/scenarios/{sid}/docs/{doc_id}/upload")
async def admin_upload_doc_file(sid: str, doc_id: str, body: DocUploadInput,
                                request: Request, admin=Depends(require_admin)):
    """Broker uploads a file into a borrower's doc line on their behalf.
    Common when borrowers email documents directly to the broker."""
    d = await db.client_docs.find_one({"id": doc_id, "scenario_id": sid})
    if not d:
        raise HTTPException(status_code=404, detail="Doc not found")
    if d.get("system"):
        raise HTTPException(status_code=400, detail="This document line is system-managed.")
    meta = await _append_file_to_doc(d, body.data_b64, body.filename, body.content_type,
                                     uploaded_by="broker")
    await audit_log(db, event_type="document.upload", request=request, user=admin,
                    resource_type="client_doc", resource_id=doc_id,
                    resource_name=body.filename,
                    metadata={"file_id": meta["file_id"], "scenario_id": sid,
                              "doc_label": d.get("label"), "uploaded_by": "broker"})
    return {"ok": True, "file_id": meta["file_id"]}


@api.delete("/admin/scenarios/{sid}/docs/{doc_id}/files/{file_id}")
async def admin_delete_doc_file(sid: str, doc_id: str, file_id: str,
                                request: Request, admin=Depends(require_admin)):
    """Broker removes one specific file from a doc line (e.g., borrower sent a wrong page)."""
    d = await db.client_docs.find_one({"id": doc_id, "scenario_id": sid})
    if not d:
        raise HTTPException(status_code=404, detail="Doc not found")
    file_meta = next((fm for fm in (d.get("files") or []) if fm.get("file_id") == file_id), None)
    updated = await _remove_file_from_doc(d, file_id)
    if updated:
        updated.pop("_id", None)
    await audit_log(db, event_type="document.delete", request=request, user=admin,
                    resource_type="client_doc", resource_id=doc_id,
                    resource_name=(file_meta or {}).get("filename"),
                    metadata={"file_id": file_id, "scenario_id": sid,
                              "doc_label": d.get("label"), "reason": "file_delete"})
    return {"ok": True, "doc": updated}


@api.get("/admin/scenarios/{sid}/docs/copy-source")
async def scenario_docs_copy_source(sid: str, admin=Depends(require_admin)):
    """List sibling scenarios (same client) whose docs can be copied into this scenario."""
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0, "client_id": 1})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if not scen.get("client_id"):
        return []
    siblings = await db.scenarios.find(
        {"client_id": scen["client_id"], "id": {"$ne": sid}},
        {"_id": 0, "id": 1, "name": 1, "loan_request": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(200)
    result = []
    for s in siblings:
        docs = await db.client_docs.find(
            {"scenario_id": s["id"]}, {"_id": 0},
        ).sort("order", 1).to_list(500)
        await _populate_doc_files(docs)
        if not docs:
            continue
        result.append({
            "scenario_id": s["id"],
            "scenario_name": s.get("name") or "Untitled",
            "loan_type": (s.get("loan_request") or {}).get("loan_type"),
            "docs": docs,
        })
    return result


@api.post("/admin/scenarios/{sid}/docs/copy")
async def scenario_docs_copy(sid: str, body: ScenarioDocCopy, admin=Depends(require_admin)):
    """Copy selected doc lines from another scenario into this one. Duplicates the file too
    (each scenario keeps its own audit trail so re-uploading in one doesn't affect the other)."""
    dest = await db.scenarios.find_one({"id": sid}, {"_id": 0, "client_id": 1})
    if not dest:
        raise HTTPException(status_code=404, detail="Scenario not found")
    source = await db.scenarios.find_one({"id": body.source_scenario_id}, {"_id": 0, "client_id": 1})
    if not source:
        raise HTTPException(status_code=404, detail="Source scenario not found")
    if source.get("client_id") != dest.get("client_id"):
        raise HTTPException(status_code=400, detail="Can only copy docs between scenarios for the same client")
    source_docs = await db.client_docs.find(
        {"scenario_id": body.source_scenario_id, "id": {"$in": body.doc_ids}}, {"_id": 0},
    ).to_list(500)
    if not source_docs:
        raise HTTPException(status_code=404, detail="No matching docs to copy")
    # Compute next order for this scenario
    last = await db.client_docs.find({"scenario_id": sid}).sort("order", -1).to_list(1)
    next_order = (last[0]["order"] + 1) if last else 0
    now = now_iso()
    copied = []
    for sd in source_docs:
        new_doc_id = str(uuid.uuid4())
        # Deep-copy every attached file so each scenario is self-contained.
        src_metas = _ensure_doc_files_meta(sd)
        new_metas: list[dict] = []
        latest_new_file_id: Optional[str] = None
        latest_filename = None
        latest_ct = None
        latest_size = None
        for sm in src_metas:
            src_fid = sm.get("file_id")
            if not src_fid:
                continue
            f = await db.client_files.find_one({"id": src_fid}, {"_id": 0})
            if not f:
                continue
            new_fid = str(uuid.uuid4())
            await db.client_files.insert_one({
                "id": new_fid,
                "doc_id": new_doc_id,
                "client_id": dest.get("client_id"),
                "scenario_id": sid,
                "filename": f.get("filename"),
                "content_type": f.get("content_type"),
                "size": f.get("size"),
                "data_b64": f.get("data_b64"),
                "uploaded_at": now,
                "uploaded_by": sm.get("uploaded_by") or "client",
                "copied_from_doc_id": sd["id"],
                "copied_from_file_id": src_fid,
            })
            meta = {
                "file_id": new_fid,
                "filename": f.get("filename") or sm.get("filename"),
                "content_type": f.get("content_type") or sm.get("content_type"),
                "size": f.get("size") if f.get("size") is not None else sm.get("size"),
                "uploaded_at": now,
                "uploaded_by": sm.get("uploaded_by") or "client",
            }
            new_metas.append(meta)
            latest_new_file_id = new_fid
            latest_filename = meta["filename"]
            latest_ct = meta["content_type"]
            latest_size = meta["size"]
        new_doc = {
            "id": new_doc_id,
            "scenario_id": sid,
            "client_id": dest.get("client_id"),
            "label": sd.get("label", "Document"),
            "category": sd.get("category", "Other"),
            "required": sd.get("required", True),
            "status": "uploaded" if new_metas else "pending",
            "notes": sd.get("notes", ""),
            "files": new_metas,
            "file_id": latest_new_file_id,
            "filename": latest_filename,
            "content_type": latest_ct,
            "size": latest_size,
            "order": next_order,
            "created_at": now,
            "updated_at": now,
            "copied_from_doc_id": sd["id"],
        }
        next_order += 1
        await db.client_docs.insert_one(new_doc)
        new_doc.pop("_id", None)
        copied.append(new_doc)
    return {"ok": True, "copied": copied, "count": len(copied)}


@api.get("/admin/scenarios/{sid}/pdf")
async def scenario_pdf(sid: str, admin=Depends(require_admin)):
    d = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    metrics = compute_scenario_metrics(d)
    client = None
    if d.get("client_id"):
        client = await db.users.find_one({"id": d["client_id"]}, {"_id": 0, "password_hash": 0})
    pdf_bytes = render_scenario_pdf(d, client, metrics, watermark_text="Byrd & CO — Internal Copy")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="byrd-scenario-{sid[:8]}.pdf"'},
    )


# ================ Admin Backups (encrypted MongoDB dumps to Backblaze B2) ================
@api.post("/admin/security/backup/run")
async def admin_run_backup(admin=Depends(require_admin)):
    """Kick off an on-demand backup. Runs off the event loop so the request returns quickly."""
    try:
        from backup_service import run_backup_async
        meta = await run_backup_async(retention_days=30)
        await db.backup_log.insert_one(dict(meta))  # copy so insert_one's _id mutation doesn't leak into response
        return {"ok": True, **meta}
    except Exception as e:
        logger.exception("Manual backup failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)[:400]}")


@api.get("/admin/security/backup/list")
async def admin_list_backups(admin=Depends(require_admin), from_b2: bool = False):
    """List recent backups. `from_b2=true` reads directly from Backblaze (source of truth)."""
    if from_b2:
        try:
            from backup_service import list_recent_backups_b2
            return {"source": "b2", "backups": list_recent_backups_b2(limit=30)}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"B2 list failed: {str(e)[:300]}")
    logs = await db.backup_log.find({}, {"_id": 0}).sort("started_at", -1).to_list(30)
    return {"source": "log", "backups": logs}


# ================ Admin: Audit Log (compliance chain-of-custody) ================

@api.get("/admin/audit-log/event-types")
async def admin_audit_event_types(admin=Depends(require_admin)):
    """Human-readable labels for every audit event type — powers the UI filter dropdown."""
    return {"types": [{"key": k, "label": v} for k, v in audit_service.EVENT_TYPES.items()]}


def _parse_iso_ts(s: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept "2026-02-28", "2026-02-28T12:00:00Z", "2026-02-28T12:00:00+00:00"
        raw = s
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        # If the user passed a bare YYYY-MM-DD, treat "to" bounds as end-of-day
        # so filtering by "to = today" INCLUDES today's events.
        if end_of_day and len(raw) == 10 and "T" not in raw:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999_000)
        # Normalize naive -> UTC (BSON timestamps are stored as UTC-aware datetimes)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


@api.get("/admin/audit-log")
async def admin_audit_log(
    admin=Depends(require_admin),
    event_type: Optional[str] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    """Filtered, paginated audit-log listing for admins."""
    return await audit_service.query_events(
        db,
        event_type=event_type, user_id=user_id, user_email=user_email,
        resource_id=resource_id, ip=ip,
        date_from=_parse_iso_ts(date_from), date_to=_parse_iso_ts(date_to, end_of_day=True),
        q=q, page=page, page_size=page_size,
    )


@api.get("/admin/audit-log/export.csv")
async def admin_audit_log_export_csv(
    admin=Depends(require_admin),
    event_type: Optional[str] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 10000,
):
    """CSV export of the same filtered query — capped at 50k rows to keep this cheap
    and to force auditors to add date filters for larger pulls."""
    limit = max(1, min(limit, 50000))
    res = await audit_service.query_events(
        db,
        event_type=event_type, user_id=user_id, user_email=user_email,
        resource_id=resource_id, ip=ip,
        date_from=_parse_iso_ts(date_from), date_to=_parse_iso_ts(date_to, end_of_day=True),
        q=q, page=1, page_size=limit, hard_cap=50000,
    )
    csv_bytes = audit_service.export_csv(res.get("events") or [])
    filename = f"byrd-audit-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ================ Financial Periods (multi-year NOI/DSCR calculator) ================
# Purpose: brokers build a per-period income/expense table (Tax Return, P&L, Pro Forma columns)
# that feeds the lender-facing package + Executive Summary PDF. Underwriting rate is broker-set
# here (independent from the borrower's target rate on the loan_request) so DSCR is defensible.

def _default_financials_expanded() -> dict:
    return {"periods": [], "selected_period_id": None,
            "uw_assumptions": {"rate_pct": None, "amort_months": None, "term_months": None}}


def _ensure_financials_expanded(scen: dict) -> dict:
    fin = scen.get("financials") or {}
    if "periods" not in fin:
        fin["periods"] = []
    if "selected_period_id" not in fin:
        fin["selected_period_id"] = None
    if "uw_assumptions" not in fin or not isinstance(fin.get("uw_assumptions"), dict):
        fin["uw_assumptions"] = {"rate_pct": None, "amort_months": None, "term_months": None}
    scen["financials"] = fin
    return fin


@api.get("/admin/scenarios/{sid}/financials")
async def admin_get_financials(sid: str, admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    fin = _ensure_financials_expanded(scen)
    periods_out = [_period_computed(p) for p in fin.get("periods", [])]
    return {
        "periods": periods_out,
        "selected_period_id": fin.get("selected_period_id"),
        "uw_assumptions": fin.get("uw_assumptions") or {},
        "metrics": compute_scenario_metrics(scen),
    }


@api.post("/admin/scenarios/{sid}/financials/periods")
async def admin_add_financial_period(sid: str, body: FinancialPeriodCreate,
                                     admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    fin = _ensure_financials_expanded(scen)
    period = body.model_dump()
    period["id"] = period.get("id") or str(uuid.uuid4())
    period["created_at"] = now_iso()
    fin["periods"].append(period)
    # Auto-select if first period
    if not fin.get("selected_period_id"):
        fin["selected_period_id"] = period["id"]
    await db.scenarios.update_one({"id": sid}, {"$set": {"financials": fin, "updated_at": now_iso()}})
    return _period_computed(period)


@api.patch("/admin/scenarios/{sid}/financials/periods/{pid}")
async def admin_update_financial_period(sid: str, pid: str, body: FinancialPeriodUpdate,
                                        admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    fin = _ensure_financials_expanded(scen)
    period = next((p for p in fin["periods"] if p.get("id") == pid), None)
    if not period:
        raise HTTPException(status_code=404, detail="Period not found")
    updates = body.model_dump(exclude_none=True)
    # Merge nested income/expenses partially
    if "income" in updates:
        period["income"] = {**(period.get("income") or {}), **(updates.pop("income") or {})}
    if "expenses" in updates:
        period["expenses"] = {**(period.get("expenses") or {}), **(updates.pop("expenses") or {})}
    period.update(updates)
    period["updated_at"] = now_iso()
    await db.scenarios.update_one({"id": sid}, {"$set": {"financials": fin, "updated_at": now_iso()}})
    return _period_computed(period)


@api.delete("/admin/scenarios/{sid}/financials/periods/{pid}")
async def admin_delete_financial_period(sid: str, pid: str, admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    fin = _ensure_financials_expanded(scen)
    before = len(fin["periods"])
    fin["periods"] = [p for p in fin["periods"] if p.get("id") != pid]
    if len(fin["periods"]) == before:
        raise HTTPException(status_code=404, detail="Period not found")
    if fin.get("selected_period_id") == pid:
        fin["selected_period_id"] = fin["periods"][0]["id"] if fin["periods"] else None
    await db.scenarios.update_one({"id": sid}, {"$set": {"financials": fin, "updated_at": now_iso()}})
    return {"ok": True}


@api.post("/admin/scenarios/{sid}/financials/select")
async def admin_select_financial_period(sid: str, body: dict, admin=Depends(require_admin)):
    pid = (body or {}).get("period_id")
    if not pid:
        raise HTTPException(status_code=400, detail="period_id required")
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    fin = _ensure_financials_expanded(scen)
    if not any(p.get("id") == pid for p in fin["periods"]):
        raise HTTPException(status_code=404, detail="Period not found")
    fin["selected_period_id"] = pid
    await db.scenarios.update_one({"id": sid}, {"$set": {"financials": fin, "updated_at": now_iso()}})
    return {"ok": True, "selected_period_id": pid}


@api.patch("/admin/scenarios/{sid}/financials/assumptions")
async def admin_patch_uw_assumptions(sid: str, body: UWAssumptions,
                                     admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    fin = _ensure_financials_expanded(scen)
    fin["uw_assumptions"] = {**(fin.get("uw_assumptions") or {}), **body.model_dump(exclude_none=True)}
    await db.scenarios.update_one({"id": sid}, {"$set": {"financials": fin, "updated_at": now_iso()}})
    return {"ok": True, "uw_assumptions": fin["uw_assumptions"]}


# --- Ada: parse a tax return or P&L into a proposed financial period ---
class FinancialsParseBody(BaseModel):
    file_id: str            # id of an existing client_files row (tax return / P&L PDF)
    doc_type: Literal["tax_return", "p_and_l"] = "tax_return"


FINANCIALS_PARSE_SYSTEM = """You extract commercial real estate operating financials from a document (tax return Schedule E, business P&L, or trailing operating statement). Return ONLY compact JSON with these keys (omit or null if unclear):

detected_doc_type ("tax_return"|"p_and_l"|"operating_statement"|"unknown"),
year (integer, the tax year or the period year, if stated),
label (short human label like "2024 Tax Return" or "2024 T-12 P&L"),
income: { gross_potential_rent, vacancy_loss, other_income },
expenses: { taxes, insurance, utilities, repairs_maintenance, management, payroll, marketing, reserves_capex, general_admin, other_expense },
adjustments_note (short string describing add-backs applied, e.g., "Added back depreciation $18,400 and mortgage interest $52,100"),
confidence ("high"|"medium"|"low")

CRITICAL RULES:
- ALWAYS add back these tax-return-only items (do NOT include them as operating expenses):
  * Depreciation
  * Amortization
  * Mortgage interest / any interest expense
- If the document shows total rents received (Schedule E line 3) without a separate GPR/vacancy breakdown, treat that number as gross_potential_rent and leave vacancy_loss null.
- Property Management, Legal & Professional, and similar go into "management" (or "general_admin" if clearly office overhead not property mgmt).
- All expense values are POSITIVE numbers (dollars of expense).
- vacancy_loss is a POSITIVE number (dollars of loss); the app subtracts it from GPR.
- If a line is not present or is $0, omit the key.
- Never invent numbers. If it's not clearly readable from the document, omit.
- Return raw JSON only, no markdown fences."""


@api.post("/admin/scenarios/{sid}/financials/parse-doc")
async def admin_parse_financials_doc(sid: str, body: FinancialsParseBody,
                                     admin=Depends(require_admin)):
    """Ada reads a tax return or P&L and proposes a financial period. Broker reviews before saving."""
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    f = await db.client_files.find_one({"id": body.file_id}, {"_id": 0})
    if not f:
        raise HTTPException(status_code=404, detail="Uploaded file not found")
    ct = (f.get("content_type") or "").lower()
    raw = base64.b64decode(f["data_b64"])
    text = ""
    if "pdf" in ct or f.get("filename", "").lower().endswith(".pdf"):
        text = _extract_pdf_text(raw)
    else:
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
    if not text or len(text.strip()) < 30:
        raise HTTPException(status_code=422,
                            detail="Couldn't read enough text from this document. It may be a scanned image — please enter the numbers manually.")
    text = text[:22000]
    session_id = f"fin-parse-{body.file_id[:8]}"
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id, system_message=FINANCIALS_PARSE_SYSTEM)
    chat.with_model("anthropic", "claude-sonnet-4-5-20250929")
    try:
        reply = await chat.send_message(UserMessage(
            text=f"Document type hint: {body.doc_type}\n\nExtract fields from this document:\n\n{text}"
        ))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ada parse failed: {e}")
    txt = (reply or "").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:].strip()
    try:
        parsed = json.loads(txt)
        if not isinstance(parsed, dict):
            raise ValueError("not object")
    except Exception:
        raise HTTPException(status_code=502, detail="Couldn't parse Ada's output — please enter manually.")
    # Return the raw parsed output as a proposed period (broker reviews before saving via POST /periods)
    proposal = {
        "label": parsed.get("label") or (f"{parsed.get('year') or ''} {body.doc_type.replace('_', ' ').title()}".strip() or "New Period"),
        "doc_type": body.doc_type,
        "year": parsed.get("year"),
        "is_pro_forma": False,
        "include_reserves_in_opex": True,
        "source_doc_id": body.file_id,
        "source_filename": f.get("filename"),
        "income": (parsed.get("income") or {}),
        "expenses": (parsed.get("expenses") or {}),
        "notes": (parsed.get("adjustments_note") or ""),
        "confidence": parsed.get("confidence") or "medium",
    }
    return {"ok": True, "proposal": proposal, "raw": parsed}


# ================ Executive Summary (Loan Summary PDF) ================
# Broker-generated 1-2 page branded PDF pulling selected-period financials, sponsor snapshot,
# property photos, an OpenStreetMap image, U.S. Census demographics, and a broker narrative.

import urllib.parse as _urlparse
import urllib.request as _urlreq

class SummaryPhotoUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content_type: str = Field(min_length=1, max_length=100)
    data_b64: str = Field(min_length=1)


class ExecutiveSummaryPatch(BaseModel):
    narrative: Optional[str] = None
    include_map: Optional[bool] = None
    include_census: Optional[bool] = None
    include_photos: Optional[bool] = None
    include_sponsor_snapshot: Optional[bool] = None


class SaveSummaryToPortalBody(BaseModel):
    label: Optional[str] = "Loan Executive Summary"


def _ensure_summary_cfg(scen: dict) -> dict:
    cfg = scen.get("executive_summary") or {}
    cfg.setdefault("narrative", "")
    cfg.setdefault("include_map", True)
    cfg.setdefault("include_census", True)
    cfg.setdefault("include_photos", True)
    cfg.setdefault("include_sponsor_snapshot", True)
    cfg.setdefault("photo_file_ids", [])
    scen["executive_summary"] = cfg
    return cfg


def _http_get_json(url: str, timeout: float = 6.0) -> Optional[dict]:
    try:
        req = _urlreq.Request(url, headers={"User-Agent": "Byrd-CO-Loan-Summary/1.0"})
        with _urlreq.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _http_get_bytes(url: str, timeout: float = 8.0) -> Optional[bytes]:
    try:
        req = _urlreq.Request(url, headers={"User-Agent": "Byrd-CO-Loan-Summary/1.0"})
        with _urlreq.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def _geocode_address(prop: dict) -> Optional[dict]:
    """Nominatim geocoding (free, no key). Returns {lat, lon, display} or None."""
    parts = [prop.get("address"), prop.get("city"), prop.get("state"), prop.get("zip")]
    q = ", ".join([p for p in parts if p])
    if not q:
        return None
    url = "https://nominatim.openstreetmap.org/search?" + _urlparse.urlencode(
        {"format": "json", "q": q, "limit": 1, "addressdetails": 1}
    )
    data = _http_get_json(url)
    if not data or not isinstance(data, list):
        return None
    hit = data[0]
    return {"lat": float(hit["lat"]), "lon": float(hit["lon"]), "display": hit.get("display_name") or q}


def _static_map_bytes(lat: float, lon: float, zoom: int = 15) -> Optional[bytes]:
    """OSM static map (free, no key). Returns PNG bytes or None."""
    url = ("https://staticmap.openstreetmap.de/staticmap.php?"
           + _urlparse.urlencode({
               "center": f"{lat},{lon}", "zoom": zoom, "size": "600x360",
               "maptype": "mapnik", "markers": f"{lat},{lon},red-pushpin",
           }))
    return _http_get_bytes(url)


def _census_demographics(lat: float, lon: float) -> Optional[dict]:
    """Fetch ACS 5-year demographics at the census tract for (lat, lon). No key required."""
    # Step 1: reverse-geocode to state/county/tract via Census Geocoder
    url1 = ("https://geocoding.geo.census.gov/geocoder/geographies/coordinates?"
            + _urlparse.urlencode({"x": lon, "y": lat, "benchmark": "Public_AR_Current",
                                    "vintage": "Current_Current", "format": "json"}))
    g = _http_get_json(url1)
    try:
        tract = g["result"]["geographies"]["Census Tracts"][0]
        state, county, tr = tract["STATE"], tract["COUNTY"], tract["TRACT"]
        tract_name = tract.get("NAME") or f"Tract {tr}"
    except Exception:
        return None
    # Step 2: pull ACS 5-year vars for tract:
    #   B01003_001E = Total population
    #   B19013_001E = Median household income
    #   B25077_001E = Median home value
    #   B25064_001E = Median gross rent
    #   B25010_001E = Avg household size
    fields = "NAME,B01003_001E,B19013_001E,B25077_001E,B25064_001E,B25010_001E"
    url2 = ("https://api.census.gov/data/2022/acs/acs5?"
            + _urlparse.urlencode({"get": fields, "for": f"tract:{tr}",
                                    "in": f"state:{state} county:{county}"}))
    d = _http_get_json(url2)
    if not d or not isinstance(d, list) or len(d) < 2:
        return None
    headers, values = d[0], d[1]
    row = dict(zip(headers, values))
    def _n(v):
        try:
            n = float(v)
            return n if n >= 0 else None
        except (TypeError, ValueError):
            return None
    return {
        "tract_name": tract_name,
        "population": _n(row.get("B01003_001E")),
        "median_household_income": _n(row.get("B19013_001E")),
        "median_home_value": _n(row.get("B25077_001E")),
        "median_gross_rent": _n(row.get("B25064_001E")),
        "avg_household_size": _n(row.get("B25010_001E")),
    }


def render_executive_summary_pdf(scen: dict, metrics: dict, cfg: dict,
                                 photos: list, geo: Optional[dict],
                                 map_png: Optional[bytes], census: Optional[dict],
                                 selected_period: Optional[dict]) -> bytes:
    """Byrd-branded 1-2 page Executive Loan Summary PDF."""
    from reportlab.platypus import Image as RImage
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            title=f"Byrd & CO — Loan Summary — {scen.get('name', '')}")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                        fontSize=20, leading=24, textColor=BYRD_INK, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                        fontSize=11, leading=14, textColor=BYRD_INK, spaceBefore=10, spaceAfter=3)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=9, leading=12, textColor=BYRD_INK)
    small = ParagraphStyle("small", parent=styles["BodyText"], fontName="Helvetica",
                           fontSize=8, leading=10, textColor=BYRD_MUTED)
    elements = []

    prop = scen.get("property_info") or {}
    loan = scen.get("loan_request") or {}
    addr = ", ".join([b for b in [prop.get("address"), prop.get("city"),
                                    prop.get("state"), prop.get("zip")] if b])

    # Header
    elements.append(Paragraph("BYRD &amp; CO", ParagraphStyle(
        "brand", fontName="Helvetica-Bold", fontSize=10, textColor=BYRD_GOLD, spaceAfter=1)))
    elements.append(Paragraph("Commercial Real Estate Lending &nbsp;&middot;&nbsp; Loan Executive Summary", small))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(scen.get("name") or "Loan Package", h1))
    if addr:
        elements.append(Paragraph(addr, body))
    tags = []
    ot = prop.get("occupancy_type")
    if ot:
        tags.append(f"<b>{'Owner-Occupied' if ot == 'owner_occupied' else 'Non-Owner-Occupied'}</b>")
    if loan.get("loan_type"):
        tags.append(loan['loan_type'])
    if selected_period and selected_period.get("is_pro_forma"):
        tags.append("<b>Pro Forma Underwriting</b>")
    if loan.get("estimated_closing_date"):
        tags.append(f"Est. Close: {loan['estimated_closing_date']}")
    if tags:
        elements.append(Paragraph(" &nbsp;·&nbsp; ".join(tags), small))
    elements.append(Spacer(1, 6))

    # Photos row (up to 4 thumbs)
    if cfg.get("include_photos") and photos:
        thumbs = []
        for p in photos[:4]:
            try:
                img = RImage(BytesIO(p["bytes"]), width=1.7 * inch, height=1.15 * inch)
                thumbs.append(img)
            except Exception:
                continue
        if thumbs:
            row = [thumbs + [""] * (4 - len(thumbs))]
            t = Table(row, colWidths=[1.75 * inch] * 4)
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            elements.append(t)
            elements.append(Spacer(1, 6))

    # Key Metrics grid — facts only (rate-independent where possible; DSCR labeled with UW rate)
    def _fmt_money_local(v):
        return _fmt_money(v)
    def _fmt_pct_local(v, d=1):
        return _fmt_pct(v, d)
    grid = [
        [Paragraph("<b>Loan Requested</b>", body), _fmt_money_local(loan.get("loan_amount")),
         Paragraph("<b>Purchase</b>", body), _fmt_money_local(prop.get("purchase_price"))],
        [Paragraph("<b>Property Value</b>", body), _fmt_money_local(metrics.get("property_value")),
         Paragraph("<b>LTV / LTC</b>", body),
         f"{_fmt_pct_local(metrics.get('ltv_pct'))}  /  {_fmt_pct_local(metrics.get('ltc_pct'))}"],
        [Paragraph("<b>NOI</b>", body), _fmt_money_local(metrics.get("noi")),
         Paragraph("<b>Debt Yield</b>", body), _fmt_pct_local(metrics.get("debt_yield_pct"), 2)],
        [Paragraph("<b>DSCR</b>", body), _fmt_num(metrics.get("dscr")) + "x" if metrics.get("dscr") else "—",
         Paragraph("<b>UW Rate / Amort</b>", body),
         (f"{metrics.get('uw_rate_pct'):.2f}% / {metrics.get('uw_amort_months') or '—'} mo"
          if metrics.get("uw_rate_pct") else "—")],
    ]
    t = Table(grid, colWidths=[1.3 * inch, 1.55 * inch, 1.3 * inch, 1.85 * inch])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, BYRD_LINE),
        ("BACKGROUND", (0, 0), (0, -1), BYRD_IVORY),
        ("BACKGROUND", (2, 0), (2, -1), BYRD_IVORY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(t)
    # DSCR/NOI source note
    src_bits = []
    if selected_period:
        tag = selected_period.get("label") or "Selected period"
        if selected_period.get("is_pro_forma"):
            src_bits.append(f"NOI/Debt Yield based on <b>{tag}</b> (projected)")
        else:
            src_bits.append(f"NOI/Debt Yield based on <b>{tag}</b>")
    if metrics.get("uw_rate_pct"):
        src_bits.append(f"DSCR assumes {metrics['uw_rate_pct']:.2f}% underwriting rate")
    if src_bits:
        elements.append(Paragraph(" · ".join(src_bits), small))

    # Property Details + Map side by side
    prop_rows = [
        ["Type", prop.get("property_type") or "—", "Units", _fmt_num(prop.get("units"))],
        ["Sq Ft", _fmt_num(prop.get("sqft")), "Year Built", _fmt_num(prop.get("year_built"))],
        ["Occupancy", _fmt_pct_local(prop.get("occupancy_pct")), "Current Value", _fmt_money_local(prop.get("current_value"))],
    ]
    pt = Table(prop_rows, colWidths=[0.9 * inch, 1.3 * inch, 0.9 * inch, 1.3 * inch])
    pt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), BYRD_IVORY),
        ("BACKGROUND", (2, 0), (2, -1), BYRD_IVORY),
        ("GRID", (0, 0), (-1, -1), 0.5, BYRD_LINE),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    map_flow = None
    if cfg.get("include_map") and map_png:
        try:
            map_flow = RImage(BytesIO(map_png), width=3.4 * inch, height=2.0 * inch)
        except Exception:
            map_flow = None

    elements.append(Paragraph("Property Details &amp; Location", h2))
    if map_flow:
        two_col = Table([[pt, map_flow]], colWidths=[4.5 * inch, 3.6 * inch])
        two_col.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(two_col)
    else:
        elements.append(pt)

    # Census / demographics
    if cfg.get("include_census") and census:
        elements.append(Paragraph("Neighborhood Demographics", h2))
        c = census
        c_rows = [
            ["Census Tract", c.get("tract_name") or "—",
             "Population", _fmt_num(c.get("population"))],
            ["Median HH Income", _fmt_money_local(c.get("median_household_income")),
             "Median Home Value", _fmt_money_local(c.get("median_home_value"))],
            ["Median Gross Rent", _fmt_money_local(c.get("median_gross_rent")),
             "Avg HH Size", _fmt_num(c.get("avg_household_size"))],
        ]
        ct = Table(c_rows, colWidths=[1.4 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch])
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BYRD_IVORY),
            ("BACKGROUND", (2, 0), (2, -1), BYRD_IVORY),
            ("GRID", (0, 0), (-1, -1), 0.5, BYRD_LINE),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(ct)
        elements.append(Paragraph("<i>Source: U.S. Census Bureau, ACS 5-Year 2022</i>", small))

    # Sponsor snapshot
    sponsors = scen.get("sponsors") or []
    if cfg.get("include_sponsor_snapshot") and sponsors:
        elements.append(Paragraph("Sponsor Snapshot", h2))
        sp_rows = [["Sponsor", "Role", "Ownership", "FICO", "Liquidity", "Net Worth"]]
        for sp in sponsors:
            role_bits = [sp.get("role") or ""]
            if sp.get("is_guarantor") and (sp.get("role") or "") != "managing":
                role_bits.append("Guarantor")
            sp_rows.append([
                sp.get("name") or "—",
                " · ".join([r for r in role_bits if r]) or "—",
                f"{sp.get('ownership_pct')}%" if sp.get("ownership_pct") is not None else "—",
                str(sp.get("credit_score") or "—"),
                _fmt_money_local(sp.get("liquidity")),
                _fmt_money_local(sp.get("net_worth")),
            ])
        spt = Table(sp_rows, colWidths=[1.6 * inch, 1.3 * inch, 0.8 * inch, 0.7 * inch, 1.1 * inch, 1.1 * inch])
        spt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BYRD_IVORY),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, BYRD_LINE),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(spt)

    # Narrative — falls back to scenario.business_plan if the summary-specific narrative is empty.
    effective_narrative = (cfg.get("narrative") or "").strip() or (scen.get("business_plan") or "").strip()
    if effective_narrative:
        elements.append(Paragraph("Deal Narrative", h2))
        narrative_html = effective_narrative.replace("\n", "<br/>")
        elements.append(Paragraph(narrative_html, body))

    # Contact + disclaimer
    elements.append(Spacer(1, 10))
    contact = Table([[
        Paragraph("<b>Wayne Byrd</b><br/>832-813-9802<br/>wayne@byrd-co.com", body),
        Paragraph("<b>Caleb Byrd</b><br/>832-661-4390<br/>caleb@byrd-co.com", body),
    ]], colWidths=[3.7 * inch, 3.7 * inch])
    contact.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BYRD_IVORY),
        ("BOX", (0, 0), (-1, -1), 0.5, BYRD_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(contact)
    elements.append(Paragraph(
        "<i>This Loan Executive Summary is provided by Byrd &amp; Co. for informational purposes only. "
        "Financials shown reflect the currently-selected underwriting period"
        + (" — projected numbers where noted." if selected_period and selected_period.get("is_pro_forma") else ".")
        + " Final terms are subject to lender approval, appraisal, and due diligence.</i>",
        small,
    ))

    doc.build(elements)
    return buf.getvalue()


# --- Photo storage (separate collection to keep marketing images out of client_docs) ---
MAX_SUMMARY_PHOTOS = 4


@api.get("/admin/scenarios/{sid}/summary")
async def admin_get_summary_config(sid: str, admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    cfg = _ensure_summary_cfg(scen)
    photos = await db.summary_photos.find(
        {"scenario_id": sid}, {"_id": 0, "data_b64": 0},
    ).sort("uploaded_at", 1).to_list(20)
    return {"config": {k: cfg[k] for k in cfg if k != "photo_file_ids"},
            "photos": photos}


@api.patch("/admin/scenarios/{sid}/summary")
async def admin_patch_summary_config(sid: str, body: ExecutiveSummaryPatch,
                                     admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    cfg = _ensure_summary_cfg(scen)
    for k, v in body.model_dump(exclude_none=True).items():
        cfg[k] = v
    await db.scenarios.update_one({"id": sid},
                                  {"$set": {"executive_summary": cfg, "updated_at": now_iso()}})
    return {"ok": True, "config": {k: cfg[k] for k in cfg if k != "photo_file_ids"}}


@api.post("/admin/scenarios/{sid}/summary/photos")
async def admin_upload_summary_photo(sid: str, body: SummaryPhotoUpload,
                                     admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    count = await db.summary_photos.count_documents({"scenario_id": sid})
    if count >= MAX_SUMMARY_PHOTOS:
        raise HTTPException(status_code=400,
                            detail=f"Max {MAX_SUMMARY_PHOTOS} photos per summary. Delete one first.")
    try:
        raw = base64.b64decode(body.data_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"Photo exceeds {MAX_FILE_MB}MB")
    pid = str(uuid.uuid4())
    now = now_iso()
    await db.summary_photos.insert_one({
        "id": pid, "scenario_id": sid, "filename": body.filename,
        "content_type": body.content_type, "size": len(raw), "data_b64": body.data_b64,
        "uploaded_at": now, "uploaded_by": admin["id"],
    })
    return {"id": pid, "filename": body.filename, "size": len(raw), "uploaded_at": now}


@api.delete("/admin/scenarios/{sid}/summary/photos/{pid}")
async def admin_delete_summary_photo(sid: str, pid: str, admin=Depends(require_admin)):
    res = await db.summary_photos.delete_one({"id": pid, "scenario_id": sid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Photo not found")
    return {"ok": True}


@api.get("/admin/scenarios/{sid}/summary/photos/{pid}")
async def admin_get_summary_photo(sid: str, pid: str, admin=Depends(require_admin)):
    ph = await db.summary_photos.find_one({"id": pid, "scenario_id": sid})
    if not ph:
        raise HTTPException(status_code=404, detail="Photo not found")
    return Response(content=base64.b64decode(ph["data_b64"]),
                    media_type=ph.get("content_type") or "image/jpeg")


async def _load_photos_for_summary(sid: str) -> list:
    """Return list of {bytes, filename} for the scenario's summary photos, ordered by uploaded_at."""
    docs = await db.summary_photos.find({"scenario_id": sid}).sort("uploaded_at", 1).to_list(MAX_SUMMARY_PHOTOS)
    out = []
    for d in docs:
        try:
            out.append({"bytes": base64.b64decode(d["data_b64"]), "filename": d.get("filename")})
        except Exception:
            continue
    return out


@api.post("/admin/scenarios/{sid}/summary/generate")
async def admin_generate_summary(sid: str, admin=Depends(require_admin)):
    """Generates the Executive Summary PDF on-demand. Also caches map+census on the scenario for reuse."""
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    _ensure_financials_expanded(scen)
    cfg = _ensure_summary_cfg(scen)
    metrics = compute_scenario_metrics(scen)
    sel = _selected_period(scen)
    photos = await _load_photos_for_summary(sid) if cfg.get("include_photos") else []
    geo = None
    map_png = None
    census = None
    prop = scen.get("property_info") or {}
    if (cfg.get("include_map") or cfg.get("include_census")) and prop.get("address"):
        geo = _geocode_address(prop)
        if geo:
            if cfg.get("include_map"):
                map_png = _static_map_bytes(geo["lat"], geo["lon"])
            if cfg.get("include_census"):
                census = _census_demographics(geo["lat"], geo["lon"])
    pdf_bytes = render_executive_summary_pdf(scen, metrics, cfg, photos, geo, map_png, census, sel)
    fname = f"byrd-loan-summary-{sid[:8]}.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


LOAN_SUMMARY_DOC_LABEL = "Loan Executive Summary"


# --- Ada: draft a Business Plan narrative from deal facts ---
NARRATIVE_DRAFT_SYSTEM = """You are a senior commercial real estate broker at Byrd & Co writing a Business Plan for a lender's Executive Loan Summary. Your output must be:

- 4 short paragraphs (or bullet-block style if that fits better)
- Lender-facing tone: confident, factual, punchy — NOT marketing fluff
- ~140-220 words total (this goes on a 1-page PDF)
- Structured as: (1) Deal one-liner, (2) Strategy / value creation, (3) Sponsor snapshot, (4) Financials + exit
- Use the FACTS provided. Never invent numbers, tenant names, comp rents, or sponsor track record you weren't given.
- If a fact is unknown, write in generalities (e.g., "experienced sponsor" instead of naming prior deals).
- Never mention specific interest rates or DSCR/LTV that you weren't given.
- End with a one-line exit strategy.

Return ONLY the narrative text. No preamble, no headings, no markdown fences."""


class AdaDraftNarrativeBody(BaseModel):
    replace_existing: bool = True


@api.post("/admin/scenarios/{sid}/summary/ada-draft-narrative")
async def admin_ada_draft_narrative(sid: str, body: AdaDraftNarrativeBody = AdaDraftNarrativeBody(),
                                    admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    prop = scen.get("property_info") or {}
    loan = scen.get("loan_request") or {}
    con = scen.get("construction") or {}
    sponsors = scen.get("sponsors") or []
    _ensure_financials_expanded(scen)
    sel = _selected_period(scen)
    metrics = compute_scenario_metrics(scen)

    def _yn(v):
        return "yes" if v else "no"

    # Assemble a compact FACT SHEET for Ada — she only gets what we know.
    facts = ["FACT SHEET (use these; do not invent):"]
    if scen.get("name"):
        facts.append(f"- Deal name: {scen['name']}")
    if prop.get("property_type"):
        facts.append(f"- Property type: {prop['property_type']}")
    if prop.get("units"):
        facts.append(f"- Units: {prop['units']}")
    if prop.get("sqft"):
        facts.append(f"- Sq ft: {prop['sqft']:,}")
    if prop.get("year_built"):
        facts.append(f"- Year built: {prop['year_built']}")
    addr = ", ".join(x for x in [prop.get("address"), prop.get("city"), prop.get("state"), prop.get("zip")] if x)
    if addr:
        facts.append(f"- Address: {addr}")
    if prop.get("occupancy_type"):
        facts.append(f"- Occupancy type: {'Owner-Occupied' if prop['occupancy_type'] == 'owner_occupied' else 'Non-Owner-Occupied'}")
    if prop.get("occupancy_pct") is not None:
        facts.append(f"- Current occupancy: {prop['occupancy_pct']}%")
    if prop.get("purchase_price"):
        facts.append(f"- Purchase price: ${prop['purchase_price']:,.0f}")
    if prop.get("current_value"):
        facts.append(f"- Property value: ${prop['current_value']:,.0f}")
    if loan.get("loan_type"):
        facts.append(f"- Loan type: {loan['loan_type']}")
    if loan.get("loan_amount"):
        facts.append(f"- Loan amount requested: ${loan['loan_amount']:,.0f}")
    if loan.get("term_months"):
        facts.append(f"- Term (months): {loan['term_months']}")
    if loan.get("amort_months"):
        facts.append(f"- Amortization (months): {loan['amort_months']}")
    if loan.get("recourse"):
        facts.append(f"- Recourse: {loan['recourse']}")
    if loan.get("estimated_closing_date"):
        facts.append(f"- Estimated closing: {loan['estimated_closing_date']}")
    if metrics.get("ltv_pct") is not None:
        facts.append(f"- LTV: {metrics['ltv_pct']:.1f}%")
    if metrics.get("ltc_pct") is not None:
        facts.append(f"- LTC: {metrics['ltc_pct']:.1f}%")
    if metrics.get("noi") is not None:
        facts.append(f"- NOI: ${metrics['noi']:,.0f}")
    if metrics.get("dscr") is not None:
        facts.append(f"- DSCR (at broker underwriting rate): {metrics['dscr']}")
    if metrics.get("debt_yield_pct") is not None:
        facts.append(f"- Debt Yield: {metrics['debt_yield_pct']}%")
    if sel:
        facts.append(f"- Financials basis: {sel.get('label')}"
                     + (" (Pro Forma / projected)" if sel.get("is_pro_forma") else " (historical)"))
    if con and (con.get("total_hard_cost") or con.get("total_soft_cost")):
        facts.append(f"- Renovation/CapEx budget: hard ${con.get('total_hard_cost', 0):,.0f}, soft ${con.get('total_soft_cost', 0):,.0f}")
    if sponsors:
        sp_lines = []
        for s in sponsors:
            bits = [s.get("name") or ""]
            if s.get("ownership_pct") is not None:
                bits.append(f"{s['ownership_pct']}%")
            if s.get("role"):
                bits.append(s["role"])
            if s.get("is_guarantor"):
                bits.append("guarantor")
            sp_lines.append(" / ".join(b for b in bits if b))
        facts.append("- Sponsors: " + "; ".join(sp_lines))

    fact_sheet = "\n".join(facts)
    session_id = f"narrative-{sid[:8]}"
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id, system_message=NARRATIVE_DRAFT_SYSTEM)
    chat.with_model("anthropic", "claude-sonnet-4-5-20250929")
    try:
        reply = await chat.send_message(UserMessage(
            text=f"{fact_sheet}\n\nWrite the Business Plan narrative now."
        ))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ada draft failed: {e}")
    text = (reply or "").strip()
    return {"ok": True, "narrative": text}


@api.post("/admin/scenarios/{sid}/summary/save-to-portal")
async def admin_save_summary_to_portal(sid: str, body: SaveSummaryToPortalBody,
                                       admin=Depends(require_admin)):
    """Regenerates the PDF and pins it as the top document in the portal (visible to borrower,
    lender, and admin). If a row already exists it replaces its file; otherwise creates a new row
    with order=-1000 so it always sorts first."""
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    _ensure_financials_expanded(scen)
    cfg = _ensure_summary_cfg(scen)
    metrics = compute_scenario_metrics(scen)
    sel = _selected_period(scen)
    photos = await _load_photos_for_summary(sid) if cfg.get("include_photos") else []
    geo = None
    map_png = None
    census = None
    prop = scen.get("property_info") or {}
    if (cfg.get("include_map") or cfg.get("include_census")) and prop.get("address"):
        geo = _geocode_address(prop)
        if geo:
            if cfg.get("include_map"):
                map_png = _static_map_bytes(geo["lat"], geo["lon"])
            if cfg.get("include_census"):
                census = _census_demographics(geo["lat"], geo["lon"])
    pdf_bytes = render_executive_summary_pdf(scen, metrics, cfg, photos, geo, map_png, census, sel)
    data_b64 = base64.b64encode(pdf_bytes).decode("ascii")

    # Locate an existing summary doc row (unique per scenario by label match)
    label = (body.label or LOAN_SUMMARY_DOC_LABEL).strip() or LOAN_SUMMARY_DOC_LABEL
    existing = await db.client_docs.find_one({"scenario_id": sid, "label": LOAN_SUMMARY_DOC_LABEL}, {"_id": 0})
    now = now_iso()
    filename = f"loan-summary-{sid[:8]}-{now[:10]}.pdf"
    file_id = str(uuid.uuid4())
    # Insert the file blob
    await db.client_files.insert_one({
        "id": file_id, "doc_id": existing["id"] if existing else None,
        "client_id": scen.get("client_id"), "scenario_id": sid,
        "filename": filename, "content_type": "application/pdf",
        "size": len(pdf_bytes), "data_b64": data_b64, "uploaded_at": now,
        "uploaded_by": "system",
    })
    file_meta = {
        "file_id": file_id, "filename": filename, "content_type": "application/pdf",
        "size": len(pdf_bytes), "uploaded_at": now, "uploaded_by": "system",
    }
    if existing:
        # Replace files with a single-item history of the newest
        # Cleanup: delete previous blobs for this doc row (keep single latest)
        prev_ids = [f.get("file_id") for f in (existing.get("files") or []) if f.get("file_id")]
        if existing.get("file_id"):
            prev_ids.append(existing["file_id"])
        prev_ids = [pid for pid in prev_ids if pid and pid != file_id]
        if prev_ids:
            await db.client_files.delete_many({"id": {"$in": prev_ids}})
        await db.client_docs.update_one(
            {"id": existing["id"]},
            {"$set": {"file_id": file_id, "files": [file_meta],
                      "label": label, "status": "uploaded",
                      "order": -1000, "updated_at": now}},
        )
        doc_id = existing["id"]
    else:
        doc_id = str(uuid.uuid4())
        # Also update the file blob's doc_id
        await db.client_files.update_one({"id": file_id}, {"$set": {"doc_id": doc_id}})
        await db.client_docs.insert_one({
            "id": doc_id, "scenario_id": sid, "client_id": scen.get("client_id"),
            "label": label, "category": "Loan Summary",
            "required": False, "status": "uploaded",
            "notes": "Auto-generated by Byrd & Co. — updates each time the broker regenerates it.",
            "file_id": file_id, "files": [file_meta],
            "sponsor_id": None,   # shared across all sponsors + lenders
            "order": -1000,        # pins to top (default doc orders are >= 0)
            "lender_visibility": "included",
            "created_at": now, "updated_at": now,
        })
    return {"ok": True, "doc_id": doc_id, "file_id": file_id, "filename": filename}


# ================ Fee Agreement (e-signature) ================
FEE_AGREEMENT_DOC_LABEL = "Signed Fee Agreement"





def render_fee_agreement_pdf(
    scen: dict,
    client: dict,
    admin_signer: dict,
    fee_pct: Optional[float],
    agreement_date: str,          # ISO date string
    signatures: Optional[dict] = None,  # {"borrower_name": str, "borrower_signed_at": iso, "broker_name": str, "broker_signed_at": iso}
) -> bytes:
    """Render the Byrd & CO Commercial Loan Broker Fee Agreement.
    If `signatures` is provided, the signature block is filled in (fully executed copy).
    Otherwise it renders as a draft with the signature lines empty."""
    from io import BytesIO
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        title="Byrd & CO — Commercial Loan Broker Fee Agreement",
    )
    ss = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=ss["Heading1"], fontName="Helvetica-Bold",
                                 fontSize=14, alignment=1, spaceAfter=14, textColor=colors.HexColor("#1A1A1A"))
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                        fontSize=10.5, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1A1A1A"))
    body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica",
                          fontSize=9.5, leading=13, spaceAfter=4, textColor=colors.HexColor("#1A1A1A"))
    small_lbl = ParagraphStyle("small", parent=ss["BodyText"], fontName="Helvetica-Bold",
                               fontSize=9, leading=11, textColor=colors.HexColor("#6B6558"))

    story: list = []

    # Title
    story.append(Paragraph("COMMERCIAL LOAN BROKER FEE AGREEMENT", title_style))

    # Date + parties
    date_str = agreement_date or datetime.now(timezone.utc).date().isoformat()
    story.append(Paragraph(
        f'This Agreement (&ldquo;Agreement&rdquo;) is entered into as of <b>{date_str}</b>, '
        f'by and between:', body,
    ))
    story.append(Spacer(1, 8))

    # Broker block
    broker_first = (admin_signer.get("name") or "").split(" ")[0] or "Wayne"
    broker_name_full = admin_signer.get("name") or "Wayne Byrd"
    broker_email = admin_signer.get("email") or "wayne@byrd-co.com"
    broker_phone = admin_signer.get("phone") or "832-813-9802"
    parties_data = [
        [
            Paragraph("<b>Broker:</b><br/>Byrd &amp; CO<br/>(&ldquo;Broker&rdquo;)<br/>"
                      f"Email: {broker_email} &nbsp; Phone: {broker_phone}", body),
            Paragraph("<b>Borrower:</b><br/>"
                      f"{client.get('name') or '_______________________'}<br/>"
                      f"({client.get('company') or '&ldquo;Borrower&rdquo;'})<br/>"
                      f"Email: {client.get('email') or '_______________________'}", body),
        ]
    ]
    t = Table(parties_data, colWidths=[3.35 * inch, 3.35 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4DFD1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4DFD1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)

    # Section 1
    prop = scen.get("property_info") or {}
    prop_addr_parts = [prop.get("address"), prop.get("city"), prop.get("state"), prop.get("zip_code")]
    prop_addr = ", ".join([p for p in prop_addr_parts if p]) or "_______________________"
    prop_type = prop.get("property_type") or "_______________________"
    lr = scen.get("loan_request") or {}
    purpose_label = (lr.get("loan_type") or "purchase / refinance / rehab / construction").lower()

    story.append(Paragraph("<b>1. PURPOSE</b>", h2))
    story.append(Paragraph(
        f'Borrower hereby engages Broker to arrange, negotiate, or assist in obtaining a commercial loan '
        f'(&ldquo;Loan&rdquo;) for the purpose of <b>{purpose_label}</b> on the following property:',
        body,
    ))
    story.append(Spacer(1, 4))
    prop_data = [
        [Paragraph("<b>Property Address:</b>", small_lbl), Paragraph(prop_addr, body)],
        [Paragraph("<b>Type of Property:</b>", small_lbl), Paragraph(prop_type, body)],
    ]
    pt = Table(prop_data, colWidths=[1.4 * inch, 5.3 * inch])
    pt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4DFD1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4DFD1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(pt)

    # Section 2
    fee_str = f"{fee_pct:g}" if fee_pct is not None else "_____"
    story.append(Paragraph("<b>2. BROKER COMPENSATION</b>", h2))
    story.append(Paragraph("Broker shall be compensated as follows:", body))
    story.append(Paragraph(
        f'<b>Fee: {fee_str}% of the total loan amount</b> &ndash; This fee shall be paid upon successful closing. '
        f"Broker's fee shall be paid directly through escrow at funding.", body,
    ))

    # Section 3
    story.append(Paragraph("<b>3. EXCLUSIVITY</b>", h2))
    story.append(Paragraph(
        "Borrower agrees to provide Broker thirty (30) days of exclusivity to source financing for the "
        "property referenced above. During this period, Borrower shall not engage any other mortgage broker, "
        "commercial lender, or intermediary to obtain financing for the same property or loan request.", body,
    ))
    story.append(Paragraph(
        "If Broker presents a lender offering acceptable financing terms during this period, Borrower agrees "
        "that the loan will be processed through the Broker, and the Broker shall be entitled to the agreed "
        "fee upon closing.", body,
    ))
    story.append(Paragraph(
        "After the 45-day period, the Agreement will automatically convert to a non-exclusive basis if Broker "
        "is unable to provide financing, unless otherwise terminated in writing by either party.", body,
    ))

    # Section 4
    story.append(Paragraph("<b>4. NON-CIRCUMVENTION</b>", h2))
    story.append(Paragraph(
        "Borrower agrees that all lenders introduced by Broker are proprietary contacts of the Broker. "
        "Borrower shall not, directly or indirectly, contact, negotiate, or close financing with such lenders "
        "without Broker's written consent. Any violation will result in the Broker being entitled to the "
        "full agreed-upon fee.", body,
    ))

    # Section 5
    story.append(Paragraph("<b>5. TERM OF AGREEMENT</b>", h2))
    story.append(Paragraph(
        "This Agreement shall remain in effect for six (6) months from the date hereof, unless terminated "
        "earlier in writing by either party.", body,
    ))
    story.append(Paragraph(
        "Termination shall not affect Broker's right to compensation for any loan originated, negotiated, or "
        "closed during the term or within 12 months thereafter with a lender introduced by Broker.", body,
    ))

    # Section 6
    story.append(Paragraph("<b>6. REPRESENTATIONS</b>", h2))
    story.append(Paragraph(
        "Borrower warrants that all information and documentation provided to Broker are true and accurate. "
        "Broker is not a lender and makes no representations or warranties regarding loan approval or funding.", body,
    ))

    # Section 7
    story.append(Paragraph("<b>7. CONFIDENTIALITY</b>", h2))
    story.append(Paragraph(
        "Both parties agree to maintain confidentiality regarding all loan information, borrower financials, "
        "and lender relationships.", body,
    ))

    # Section 8
    story.append(Paragraph("<b>8. GOVERNING LAW</b>", h2))
    story.append(Paragraph(
        "This Agreement shall be governed by and construed in accordance with the laws of the State of Texas.", body,
    ))

    # Section 9
    story.append(Paragraph("<b>9. ENTIRE AGREEMENT</b>", h2))
    story.append(Paragraph(
        "This Agreement constitutes the entire understanding between the parties and may only be modified in "
        "writing signed by both parties.", body,
    ))

    # Section 10 — SIGNATURES
    story.append(Paragraph("<b>10. SIGNATURES</b>", h2))

    if signatures and signatures.get("borrower_name") and signatures.get("broker_name"):
        # Fully executed copy — render the recorded typed signatures in italic cursive-ish font
        borrower_sig = signatures["borrower_name"]
        borrower_when = signatures.get("borrower_signed_at", "")
        broker_sig = signatures["broker_name"]
        broker_when = signatures.get("broker_signed_at", "")
        sig_data = [
            [
                Paragraph(
                    "<b>Broker:</b><br/><br/>"
                    f"<font name='Helvetica-Oblique' size='13'>{broker_sig}</font><br/>"
                    f"<font size='9' color='#6B6558'>Electronic signature</font><br/>"
                    f"{broker_name_full}, Byrd &amp; CO<br/>"
                    f"Date: {broker_when.split('T')[0] if broker_when else ''}",
                    body,
                ),
                Paragraph(
                    "<b>Borrower:</b><br/><br/>"
                    f"<font name='Helvetica-Oblique' size='13'>{borrower_sig}</font><br/>"
                    f"<font size='9' color='#6B6558'>Electronic signature</font><br/>"
                    f"Name: {client.get('name') or ''}<br/>"
                    f"Date: {borrower_when.split('T')[0] if borrower_when else ''}",
                    body,
                ),
            ]
        ]
    else:
        sig_data = [
            [
                Paragraph(
                    "<b>Broker:</b><br/><br/>"
                    "________________________________<br/>"
                    f"{broker_name_full}, Byrd &amp; CO<br/>"
                    "Date: ______________________", body,
                ),
                Paragraph(
                    "<b>Borrower:</b><br/><br/>"
                    "________________________________<br/>"
                    "Name: ______________________<br/>"
                    "Date: ______________________", body,
                ),
            ]
        ]
    sig_t = Table(sig_data, colWidths=[3.35 * inch, 3.35 * inch])
    sig_t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4DFD1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4DFD1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(Spacer(1, 4))
    story.append(sig_t)

    # Certificate of Completion — appended only for the fully-executed copy
    if signatures and signatures.get("borrower_name") and signatures.get("broker_name"):
        from reportlab.platypus import PageBreak
        story.append(PageBreak())
        cert_h = ParagraphStyle("cert_h", parent=ss["Heading1"], fontName="Helvetica-Bold",
                                fontSize=13, alignment=1, spaceAfter=6, textColor=colors.HexColor("#1A1A1A"))
        cert_sub = ParagraphStyle("cert_sub", parent=ss["BodyText"], fontName="Helvetica",
                                  fontSize=9, alignment=1, leading=12, textColor=colors.HexColor("#6B6558"),
                                  spaceAfter=14)
        cert_lbl = ParagraphStyle("cert_lbl", parent=ss["BodyText"], fontName="Helvetica-Bold",
                                  fontSize=9, leading=11, textColor=colors.HexColor("#6B6558"))
        cert_val = ParagraphStyle("cert_val", parent=ss["BodyText"], fontName="Helvetica",
                                  fontSize=9.5, leading=12, textColor=colors.HexColor("#1A1A1A"))

        story.append(Paragraph("CERTIFICATE OF COMPLETION", cert_h))
        story.append(Paragraph(
            f"Electronic Signature Audit &middot; Byrd &amp; CO &middot; Generated "
            f"{datetime.now(timezone.utc).strftime('%B %d, %Y at %H:%M:%S UTC')}",
            cert_sub,
        ))

        doc_title = signatures.get("document_title") or "Byrd & CO Fee Agreement"
        header_rows = [
            [Paragraph("<b>Document</b>", cert_lbl), Paragraph(doc_title, cert_val)],
            [Paragraph("<b>Agreement Date</b>", cert_lbl), Paragraph(agreement_date or "", cert_val)],
            [Paragraph("<b>Broker Fee</b>", cert_lbl),
             Paragraph(f"{fee_pct:g}% of total loan amount" if fee_pct is not None else "—", cert_val)],
            [Paragraph("<b>Broker</b>", cert_lbl),
             Paragraph(f"Byrd &amp; CO ({admin_signer.get('email') or ''})", cert_val)],
            [Paragraph("<b>Borrower</b>", cert_lbl),
             Paragraph(f"{client.get('name') or ''} ({client.get('email') or ''})", cert_val)],
        ]
        ht = Table(header_rows, colWidths=[1.6 * inch, 5.1 * inch])
        ht.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#E4DFD1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#EFE9DA")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(ht)
        story.append(Spacer(1, 12))

        # Borrower signature event
        story.append(Paragraph("<b>Borrower — Signature Event</b>",
                               ParagraphStyle("bh", parent=ss["Heading3"], fontName="Helvetica-Bold",
                                              fontSize=10.5, textColor=colors.HexColor("#1A1A1A"), spaceAfter=4)))
        borrower_rows = [
            [Paragraph("<b>Typed Name</b>", cert_lbl), Paragraph(signatures.get("borrower_name") or "", cert_val)],
            [Paragraph("<b>Email</b>", cert_lbl), Paragraph(signatures.get("borrower_email") or client.get("email") or "", cert_val)],
            [Paragraph("<b>Signed At (UTC)</b>", cert_lbl), Paragraph(signatures.get("borrower_signed_at") or "", cert_val)],
            [Paragraph("<b>IP Address</b>", cert_lbl), Paragraph(signatures.get("borrower_signed_ip") or "—", cert_val)],
            [Paragraph("<b>Browser / Device</b>", cert_lbl),
             Paragraph((signatures.get("borrower_signed_user_agent") or "—")[:200], cert_val)],
            [Paragraph("<b>Method</b>", cert_lbl),
             Paragraph("Byrd &amp; CO web portal — typed-name electronic signature with express affirmative consent.", cert_val)],
        ]
        bt = Table(borrower_rows, colWidths=[1.6 * inch, 5.1 * inch])
        bt.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#E4DFD1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#EFE9DA")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(bt)
        story.append(Spacer(1, 12))

        # Broker signature event
        story.append(Paragraph("<b>Broker — Signature Event</b>",
                               ParagraphStyle("bh2", parent=ss["Heading3"], fontName="Helvetica-Bold",
                                              fontSize=10.5, textColor=colors.HexColor("#1A1A1A"), spaceAfter=4)))
        broker_rows = [
            [Paragraph("<b>Signed On Behalf Of</b>", cert_lbl), Paragraph("Byrd &amp; CO", cert_val)],
            [Paragraph("<b>Signer</b>", cert_lbl),
             Paragraph(f"{signatures.get('broker_name','')} ({signatures.get('broker_email') or admin_signer.get('email') or ''})", cert_val)],
            [Paragraph("<b>Signed At (UTC)</b>", cert_lbl), Paragraph(signatures.get("broker_signed_at") or "", cert_val)],
            [Paragraph("<b>Method</b>", cert_lbl),
             Paragraph("Countersigned automatically by Byrd &amp; CO upon receipt of borrower's affirmative electronic signature.", cert_val)],
        ]
        bkt = Table(broker_rows, colWidths=[1.6 * inch, 5.1 * inch])
        bkt.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#E4DFD1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#EFE9DA")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(bkt)
        story.append(Spacer(1, 14))

        story.append(Paragraph(
            "<font size='8' color='#6B6558'>This Certificate of Completion is issued by Byrd &amp; CO as evidence "
            "that both parties executed the foregoing Commercial Loan Broker Fee Agreement electronically. "
            "The typed-name electronic signatures captured above satisfy the requirements of the U.S. ESIGN Act "
            "(15 U.S.C. &sect;7001 et seq.) and the Texas Uniform Electronic Transactions Act (Tex. Bus. &amp; Com. "
            "Code Ann. Ch. 322), and carry the same legal effect as a handwritten (&ldquo;wet&rdquo;) signature.</font>",
            cert_val,
        ))

    doc.build(story)
    return buf.getvalue()


def _fee_agreement_email_body(client_name: str, sender_first: str, sign_url: str, fee_pct: Optional[float], scen_name: str) -> tuple[str, str, str]:
    fee_note = f"{fee_pct:g}% of the total loan amount" if fee_pct is not None else "a broker fee to be confirmed"
    subject = f"Sign your Fee Agreement — {scen_name}"
    html = f"""
    <div style="font-family:Helvetica,Arial,sans-serif;color:#1A1A1A;line-height:1.55;font-size:14px;">
      <p>Hi {client_name.split(' ')[0] if client_name else 'there'},</p>
      <p>Before we start shopping your loan, I need you to sign the Byrd &amp; CO commercial loan broker
      fee agreement for <b>{scen_name}</b>. The broker fee is <b>{fee_note}</b>, paid at closing directly
      through escrow.</p>
      <p>Please review and sign here:</p>
      <p><a href="{sign_url}" style="background:#1A1A1A;color:#FBF8F1;text-decoration:none;padding:12px 18px;border-radius:6px;font-weight:600;display:inline-block;">Review &amp; Sign</a></p>
      <p style="font-size:12px;color:#6B6558;">The link opens a page where you'll see the full agreement, type your name, and click Agree. I'll countersign on my end and email you a copy.</p>
      <p>Thanks,<br/>{sender_first}<br/>Byrd &amp; CO</p>
    </div>
    """
    text = (
        f"Hi {client_name.split(' ')[0] if client_name else 'there'},\n\n"
        f"Before we start shopping your loan, I need you to sign the Byrd & CO commercial loan broker fee "
        f"agreement for {scen_name}. The broker fee is {fee_note}, paid at closing directly through escrow.\n\n"
        f"Please review and sign here:\n{sign_url}\n\nThanks,\n{sender_first}\nByrd & CO\n"
    )
    return subject, html, text


def _fee_agreement_signed_email(client_name: str, sender_first: str, scen_name: str) -> tuple[str, str, str]:
    subject = f"Fee Agreement executed — {scen_name}"
    html = f"""
    <div style="font-family:Helvetica,Arial,sans-serif;color:#1A1A1A;line-height:1.55;font-size:14px;">
      <p>Hi {client_name.split(' ')[0] if client_name else 'there'},</p>
      <p>Thanks for signing. The Byrd &amp; CO fee agreement for <b>{scen_name}</b> is now fully executed by both sides,
      and a signed copy is on file in your portal. I'll get to work shopping your loan.</p>
      <p>Thanks,<br/>{sender_first}<br/>Byrd &amp; CO</p>
    </div>
    """
    text = (
        f"Hi {client_name.split(' ')[0] if client_name else 'there'},\n\n"
        f"Thanks for signing. The Byrd & CO fee agreement for {scen_name} is fully executed and a signed copy "
        f"is in your portal. I'll get to work shopping your loan.\n\n"
        f"Thanks,\n{sender_first}\nByrd & CO\n"
    )
    return subject, html, text


async def _ensure_fee_agreement_doc_line(scenario_id: str, client_id: Optional[str],
                                          sponsor_id: Optional[str] = None) -> str:
    """Get or create a pinned 'Signed Fee Agreement' doc line per SPONSOR (or scenario-level
    when no sponsor is passed). Returns its doc_id."""
    q: dict = {"scenario_id": scenario_id, "label": FEE_AGREEMENT_DOC_LABEL}
    if sponsor_id:
        q["sponsor_id"] = sponsor_id
    else:
        q["sponsor_id"] = None
    existing = await db.client_docs.find_one(q, {"_id": 0})
    if existing:
        return existing["id"]
    now = now_iso()
    doc_id = str(uuid.uuid4())
    await db.client_docs.insert_one({
        "id": doc_id,
        "scenario_id": scenario_id,
        "client_id": client_id,
        "sponsor_id": sponsor_id,
        "label": FEE_AGREEMENT_DOC_LABEL,
        "category": "Fee Agreement",
        "required": True,
        "status": "pending",
        "notes": "Signed automatically once the sponsor and Byrd & CO countersign the fee agreement.",
        "file_id": None,
        "order": -1000,  # pinned to the top
        "lender_visibility": "hidden",
        "created_at": now,
        "updated_at": now,
        "system": True,
    })
    return doc_id


@api.get("/admin/scenarios/{sid}/fee-agreement/preview.pdf")
async def scenario_fee_agreement_preview(sid: str, admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    client = None
    if scen.get("client_id"):
        client = await db.users.find_one({"id": scen["client_id"]}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(status_code=400, detail="Link a client to this scenario before drafting the fee agreement")
    fee_pct = scen.get("broker_fee_pct")
    pdf = render_fee_agreement_pdf(
        scen, client, admin, fee_pct,
        agreement_date=datetime.now(timezone.utc).date().isoformat(),
        signatures=None,
    )
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="byrd-fee-agreement-draft.pdf"'},
    )


class FeeAgreementSend(BaseModel):
    broker_fee_pct: Optional[float] = None
    sponsor_id: Optional[str] = None   # NEW: which sponsor is signing. Required if scenario has sponsors[]


@api.post("/admin/scenarios/{sid}/fee-agreement/send")
async def scenario_fee_agreement_send(sid: str, body: FeeAgreementSend, background: BackgroundTasks, admin=Depends(require_admin)):
    """Send the fee agreement to a specific sponsor for e-signature. If the scenario has sponsors[],
    the caller must pass sponsor_id. Falls back to primary client for legacy scenarios."""
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    # Resolve who's signing: sponsor lookup > primary client
    signer_user_id: Optional[str] = None
    signer_sponsor_id: Optional[str] = body.sponsor_id
    sponsors = _ensure_sponsors_array(scen)
    if body.sponsor_id:
        sp = next((s for s in sponsors if s["id"] == body.sponsor_id), None)
        if not sp:
            raise HTTPException(status_code=404, detail="Sponsor not found on this scenario")
        signer_user_id = sp.get("client_user_id")
        if not signer_user_id:
            raise HTTPException(status_code=400, detail="This sponsor is not linked to a client account — link them first so they can sign.")
    elif sponsors:
        # No explicit sponsor_id passed; if there's a managing sponsor with a client, use them
        managing = next((s for s in sponsors if s.get("role") == "managing" and s.get("client_user_id")), None)
        if managing:
            signer_user_id = managing["client_user_id"]
            signer_sponsor_id = managing["id"]
        else:
            raise HTTPException(status_code=400, detail="Pick a sponsor to send this fee agreement to")
    else:
        # Legacy: no sponsors array — fall back to scenario.client_id
        signer_user_id = scen.get("client_id")
        if not signer_user_id:
            raise HTTPException(status_code=400, detail="Link a client (or a sponsor) to this scenario first")
    client = await db.users.find_one({"id": signer_user_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Signer user not found")
    if not client.get("email"):
        raise HTTPException(status_code=400, detail="Signer has no email on file")

    now = now_iso()
    if body.broker_fee_pct is not None:
        if body.broker_fee_pct <= 0 or body.broker_fee_pct > 10:
            raise HTTPException(status_code=400, detail="Fee must be between 0 and 10")
        await db.scenarios.update_one({"id": sid}, {"$set": {"broker_fee_pct": body.broker_fee_pct, "updated_at": now}})
        scen["broker_fee_pct"] = body.broker_fee_pct
    if scen.get("broker_fee_pct") is None:
        raise HTTPException(status_code=400, detail="Enter the broker fee percentage first")

    doc_id = await _ensure_fee_agreement_doc_line(sid, client["id"], sponsor_id=signer_sponsor_id)
    token = uuid.uuid4().hex + uuid.uuid4().hex

    # Supersede any pending prior request FOR THE SAME SPONSOR
    prior_q = {"scenario_id": sid, "status": "sent"}
    if signer_sponsor_id:
        prior_q["sponsor_id"] = signer_sponsor_id
    else:
        prior_q["sponsor_id"] = None
    await db.fee_agreements.update_many(prior_q, {"$set": {"status": "superseded", "superseded_at": now}})

    fa = {
        "id": str(uuid.uuid4()),
        "scenario_id": sid,
        "client_id": client["id"],
        "sponsor_id": signer_sponsor_id,
        "doc_id": doc_id,
        "token": token,
        "broker_fee_pct": scen["broker_fee_pct"],
        "sent_by_admin_id": admin["id"],
        "sent_by_admin_name": admin.get("name") or admin.get("email"),
        "sent_by_admin_email": admin.get("email"),
        "sent_by_admin_phone": admin.get("phone"),
        "borrower_email_at_send": client["email"],
        "borrower_name_at_send": client.get("name"),
        "agreement_date": datetime.now(timezone.utc).date().isoformat(),
        "status": "sent",
        "created_at": now,
        "signed_at": None,
        "borrower_signed_name": None,
        "borrower_signed_at": None,
        "borrower_signed_ip": None,
        "broker_signed_name": None,
        "broker_signed_at": None,
        "signed_file_id": None,
    }
    await db.fee_agreements.insert_one(fa)

    await db.client_docs.update_one(
        {"id": doc_id},
        {"$set": {"status": "pending", "notes": "Sent to signer for signature.", "updated_at": now}},
    )

    sender_first = (admin.get("name") or "Byrd").split(" ")[0]
    sign_url = f"{public_base_url()}/fee-agreement/{token}" if public_base_url() else f"/fee-agreement/{token}"
    subj, html, text = _fee_agreement_email_body(
        client.get("name") or "there", sender_first, sign_url, scen["broker_fee_pct"], scen.get("name") or "your loan",
    )
    background.add_task(send_email, client["email"], subj, html, text, "fee_agreement")

    fa.pop("_id", None)
    return fa


@api.get("/admin/scenarios/{sid}/fee-agreement")
async def scenario_fee_agreement_status(sid: str, admin=Depends(require_admin)):
    fa = await db.fee_agreements.find_one(
        {"scenario_id": sid, "status": {"$in": ["sent", "signed"]}}, {"_id": 0},
        sort=[("created_at", -1)],
    )
    return {"fee_agreement": fa}


@api.post("/admin/scenarios/{sid}/fee-agreement/cancel")
async def scenario_fee_agreement_cancel(sid: str, admin=Depends(require_admin)):
    fa = await db.fee_agreements.find_one({"scenario_id": sid, "status": "sent"}, {"_id": 0})
    if not fa:
        raise HTTPException(status_code=404, detail="No pending fee agreement to cancel")
    now = now_iso()
    await db.fee_agreements.update_one(
        {"id": fa["id"]},
        {"$set": {"status": "canceled", "canceled_at": now, "canceled_by_admin_id": admin["id"]}},
    )
    # Cascade to the client_docs row so the client portal reflects reality.
    # If the pinned Fee Agreement doc line is unsigned (no file, status != 'reviewed'),
    # delete it entirely — cleanest UX for the borrower (they no longer see a stale line).
    # If it's already signed (has files or reviewed), just annotate the note; don't blow away audit.
    doc_id = fa.get("doc_id")
    if doc_id:
        dl = await db.client_docs.find_one({"id": doc_id}, {"_id": 0})
        if dl:
            has_files = bool(_ensure_doc_files_meta(dl)) or bool(dl.get("file_id"))
            if not has_files and dl.get("status") != "reviewed":
                await db.client_docs.delete_one({"id": doc_id})
            else:
                await db.client_docs.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "notes": f"Broker canceled this fee agreement on {now.split('T')[0]}.",
                        "updated_at": now,
                    }},
                )
    return {"ok": True}


# ---- Public signing endpoints (token-gated, no auth) ----
@api.get("/fee-agreement/{token}")
async def public_fee_agreement_get(token: str):
    fa = await db.fee_agreements.find_one({"token": token}, {"_id": 0})
    if not fa:
        raise HTTPException(status_code=404, detail="Invalid or expired link")
    scen = await db.scenarios.find_one({"id": fa["scenario_id"]}, {"_id": 0, "id": 1, "name": 1, "property_info": 1, "loan_request": 1, "client_id": 1})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    client = await db.users.find_one({"id": fa["client_id"]}, {"_id": 0, "id": 1, "name": 1, "email": 1, "company": 1})
    prop = scen.get("property_info") or {}
    prop_addr = ", ".join([p for p in [prop.get("address"), prop.get("city"), prop.get("state"), prop.get("zip_code")] if p]) or "—"
    return {
        "status": fa["status"],  # 'sent' | 'signed' | 'superseded' | 'canceled'
        "signed_at": fa.get("signed_at"),
        "agreement_date": fa["agreement_date"],
        "broker_fee_pct": fa["broker_fee_pct"],
        "scenario": {
            "id": scen["id"],
            "name": scen.get("name"),
            "property_address": prop_addr,
            "property_type": prop.get("property_type"),
            "loan_type": (scen.get("loan_request") or {}).get("loan_type"),
        },
        "client": {
            "name": client.get("name"),
            "email": client.get("email"),
            "company": client.get("company"),
        },
        "broker": {
            "name": fa.get("sent_by_admin_name") or "Wayne Byrd",
            "email": fa.get("sent_by_admin_email"),
            "phone": fa.get("sent_by_admin_phone"),
        },
    }


@api.get("/fee-agreement/{token}/preview.pdf")
async def public_fee_agreement_pdf(token: str):
    fa = await db.fee_agreements.find_one({"token": token})
    if not fa:
        raise HTTPException(status_code=404, detail="Invalid link")
    scen = await db.scenarios.find_one({"id": fa["scenario_id"]}, {"_id": 0})
    client = await db.users.find_one({"id": fa["client_id"]}, {"_id": 0, "password_hash": 0})
    admin_signer = await db.users.find_one({"id": fa.get("sent_by_admin_id")}, {"_id": 0, "password_hash": 0}) or {"name": "Wayne Byrd", "email": "wayne@byrd-co.com"}
    # If signed, render the fully-executed version
    signatures = None
    if fa.get("status") == "signed":
        signatures = {
            "borrower_name": fa.get("borrower_signed_name"),
            "borrower_signed_at": fa.get("borrower_signed_at"),
            "borrower_signed_ip": fa.get("borrower_signed_ip"),
            "borrower_signed_user_agent": fa.get("borrower_signed_user_agent"),
            "borrower_email": fa.get("borrower_email_at_send"),
            "broker_name": fa.get("broker_signed_name"),
            "broker_signed_at": fa.get("broker_signed_at"),
            "broker_email": fa.get("sent_by_admin_email"),
            "document_title": f"Byrd & CO Fee Agreement — {scen.get('name') or ''}",
        }
    pdf = render_fee_agreement_pdf(
        scen, client, admin_signer, fa["broker_fee_pct"],
        agreement_date=fa["agreement_date"],
        signatures=signatures,
    )
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="byrd-fee-agreement.pdf"'},
    )


class PublicSignBody(BaseModel):
    typed_name: str = Field(min_length=2, max_length=200)
    agree: bool


@api.post("/fee-agreement/{token}/sign")
async def public_fee_agreement_sign(token: str, body: PublicSignBody, request: Request, background: BackgroundTasks):
    if not body.agree:
        raise HTTPException(status_code=400, detail="You must confirm the acceptance checkbox to sign")
    fa = await db.fee_agreements.find_one({"token": token}, {"_id": 0})
    if not fa:
        raise HTTPException(status_code=404, detail="Invalid link")
    if fa["status"] != "sent":
        raise HTTPException(status_code=409, detail=f"This agreement is already {fa['status']}")

    scen = await db.scenarios.find_one({"id": fa["scenario_id"]}, {"_id": 0})
    client = await db.users.find_one({"id": fa["client_id"]}, {"_id": 0, "password_hash": 0})
    admin_signer = await db.users.find_one({"id": fa.get("sent_by_admin_id")}, {"_id": 0, "password_hash": 0}) or {}

    now = datetime.now(timezone.utc).isoformat()
    ip = (request.client.host if request.client else "") or ""
    user_agent = request.headers.get("user-agent", "")[:400]
    signatures = {
        "borrower_name": body.typed_name.strip(),
        "borrower_signed_at": now,
        "borrower_signed_ip": ip,
        "borrower_signed_user_agent": user_agent,
        "borrower_email": client.get("email"),
        "broker_name": admin_signer.get("name") or "Wayne Byrd",
        "broker_signed_at": now,
        "broker_email": admin_signer.get("email"),
        "document_title": f"Byrd & CO Fee Agreement — {scen.get('name') or ''}",
    }
    # Render the fully-executed PDF (Certificate of Completion appended)
    pdf_bytes = render_fee_agreement_pdf(
        scen, client, admin_signer, fa["broker_fee_pct"],
        agreement_date=fa["agreement_date"], signatures=signatures,
    )
    # Delete any prior signed file(s) on the doc line to avoid stale copies (fee agreements pin ONE signed PDF)
    old = await db.client_docs.find_one({"id": fa["doc_id"]}, {"_id": 0, "file_id": 1, "files": 1})
    old_fids = set()
    if old:
        if old.get("file_id"):
            old_fids.add(old["file_id"])
        for m in (old.get("files") or []):
            if m.get("file_id"):
                old_fids.add(m["file_id"])
    if old_fids:
        await db.client_files.delete_many({"id": {"$in": list(old_fids)}})
    file_id = str(uuid.uuid4())
    await db.client_files.insert_one({
        "id": file_id,
        "doc_id": fa["doc_id"],
        "client_id": fa["client_id"],
        "scenario_id": fa["scenario_id"],
        "filename": "Byrd & CO — Fee Agreement (Signed).pdf",
        "content_type": "application/pdf",
        "size": len(pdf_bytes),
        "data_b64": base64.b64encode(pdf_bytes).decode(),
        "uploaded_at": now,
        "system": True,
    })
    await db.client_docs.update_one(
        {"id": fa["doc_id"]},
        {"$set": {
            "file_id": file_id,
            "files": [{
                "file_id": file_id,
                "filename": "Byrd & CO — Fee Agreement (Signed).pdf",
                "content_type": "application/pdf",
                "size": len(pdf_bytes),
                "uploaded_at": now,
                "uploaded_by": "system",
            }],
            "status": "reviewed",
            "notes": f"Signed by {signatures['borrower_name']} and countersigned by {signatures['broker_name']} on {now.split('T')[0]}.",
            "updated_at": now,
        }},
    )
    await db.fee_agreements.update_one(
        {"id": fa["id"]},
        {"$set": {
            "status": "signed",
            "signed_at": now,
            "borrower_signed_name": signatures["borrower_name"],
            "borrower_signed_at": signatures["borrower_signed_at"],
            "borrower_signed_ip": ip,
            "borrower_signed_user_agent": user_agent,
            "broker_signed_name": signatures["broker_name"],
            "broker_signed_at": signatures["broker_signed_at"],
            "signed_file_id": file_id,
            "signed_pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        }},
    )

    # Confirmation emails to both borrower and the admin who sent it
    sender_first = (admin_signer.get("name") or "Wayne").split(" ")[0]
    scen_name = scen.get("name") or "your loan"
    subj_c, html_c, text_c = _fee_agreement_signed_email(client.get("name") or "there", sender_first, scen_name)
    if client.get("email"):
        background.add_task(send_email, client["email"], subj_c, html_c, text_c, "fee_agreement_signed")
    if admin_signer.get("email"):
        subj_a = f"[Fee Agreement signed] {scen_name} — {client.get('name', 'client')}"
        html_a = (
            f"<p>Heads up — <b>{client.get('name') or 'the borrower'}</b> just signed the fee agreement for "
            f"<b>{scen_name}</b>. It's countersigned on your behalf and stored on the scenario.</p>"
        )
        background.add_task(send_email, admin_signer["email"], subj_a, html_a, "", "fee_agreement_signed")

    return {"ok": True, "status": "signed", "signed_at": now}


@api.get("/admin/scenarios/{sid}/docs.zip")
async def admin_scenario_docs_zip(sid: str, admin=Depends(require_admin)):
    """Bundle every uploaded document on this scenario into a single ZIP (all files across all lines)."""
    import zipfile
    from io import BytesIO
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    docs = await db.client_docs.find(
        {"scenario_id": sid}, {"_id": 0},
    ).sort("order", 1).to_list(500)
    docs = [d for d in docs if _ensure_doc_files_meta(d)]
    if not docs:
        raise HTTPException(status_code=404, detail="No documents uploaded yet")
    buf = BytesIO()
    used_names = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cd in docs:
            label = (cd.get("label") or "document").replace("/", "-").replace("\\", "-").strip()
            for m in _ensure_doc_files_meta(cd):
                fid = m.get("file_id")
                if not fid:
                    continue
                f = await db.client_files.find_one({"id": fid})
                if not f:
                    continue
                raw = base64.b64decode(f["data_b64"])
                base_name = f.get("filename") or m.get("filename") or "file"
                name = f"{label} - {base_name}"
                n, i = name, 1
                while n in used_names:
                    stem, dot, ext = name.rpartition(".")
                    n = f"{stem} ({i}).{ext}" if dot else f"{name} ({i})"
                    i += 1
                used_names.add(n)
                zf.writestr(n, raw)
    buf.seek(0)
    safe_name = "".join(c if ord(c) < 128 and c not in '\\/:*?"<>|' else "_" for c in (scen.get('name') or 'scenario'))
    fname = f"byrd-{safe_name.replace(' ', '_')}-{sid[:8]}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.get("/admin/scenarios/{sid}/match")
async def match(sid: str, admin=Depends(require_admin)):
    d = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    lenders = await db.lenders.find({}, {"_id": 0}).to_list(500)
    return match_lenders(d, lenders)


# ---------- LENDERS: admin routes ----------
@api.post("/admin/lenders")
async def create_lender(body: LenderCreate, admin=Depends(require_admin)):
    doc = {
        "id": str(uuid.uuid4()),
        "broker_id": admin["id"],
        **body.model_dump(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.lenders.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.get("/admin/lenders")
async def list_lenders(admin=Depends(require_admin)):
    return await db.lenders.find({}, {"_id": 0}).sort("name", 1).to_list(1000)


@api.get("/admin/lenders/{lid}")
async def get_lender(lid: str, admin=Depends(require_admin)):
    d = await db.lenders.find_one({"id": lid}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return d


@api.patch("/admin/lenders/{lid}")
async def update_lender(lid: str, body: LenderUpdate, admin=Depends(require_admin)):
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = now_iso()
    res = await db.lenders.update_one({"id": lid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    d = await db.lenders.find_one({"id": lid}, {"_id": 0})
    return d


@api.delete("/admin/lenders/{lid}")
async def delete_lender(lid: str, admin=Depends(require_admin)):
    res = await db.lenders.delete_one({"id": lid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ---------- SCENARIO SHARES ----------
@api.post("/admin/scenarios/{sid}/shares")
async def create_share(sid: str, body: ShareCreate, admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    lender = None
    if body.lender_id:
        lender = await db.lenders.find_one({"id": body.lender_id}, {"_id": 0})
        if not lender:
            raise HTTPException(status_code=400, detail="Lender not found")
    token = uuid.uuid4().hex + uuid.uuid4().hex
    now = now_iso()
    share = {
        "id": str(uuid.uuid4()),
        "scenario_id": sid,
        "token": token,
        "lender_id": body.lender_id,
        "lender_name": (lender or {}).get("name") or body.recipient_institution or "Lender",
        "recipient_name": body.recipient_name or ((lender or {}).get("contacts") or [{}])[0].get("name", ""),
        "recipient_email": body.recipient_email or ((lender or {}).get("contacts") or [{}])[0].get("email", ""),
        "recipient_institution": body.recipient_institution or (lender or {}).get("name", ""),
        "note": body.note or "",
        "doc_grants": [],
        "doc_overrides": body.doc_overrides or {},
        "requested_at": None,
        "created_at": now,
    }
    if scen.get("status") == "draft":
        await db.scenarios.update_one({"id": sid}, {"$set": {"status": "shopping", "updated_at": now}})
    await db.scenario_shares.insert_one(share)
    share.pop("_id", None)
    return share


@api.get("/admin/scenarios/{sid}/shares/{share_id}/views")
async def share_views(sid: str, share_id: str, admin=Depends(require_admin)):
    views = await db.share_views.find(
        {"scenario_id": sid, "share_id": share_id}, {"_id": 0}
    ).sort("viewed_at", -1).to_list(200)
    return views


@api.get("/admin/scenarios/{sid}/shares/activity-summary")
async def share_activity_summary(sid: str, admin=Depends(require_admin)):
    """Return one row per share with view counts + last activity timestamp."""
    shares = await db.scenario_shares.find(
        {"scenario_id": sid}, {"_id": 0, "id": 1},
    ).to_list(500)
    out = {}
    for sh in shares:
        views = await db.share_views.find(
            {"scenario_id": sid, "share_id": sh["id"]}, {"_id": 0, "action": 1, "viewed_at": 1}
        ).sort("viewed_at", -1).to_list(500)
        opened = sum(1 for v in views if v.get("action") == "view_scenario")
        downloads = sum(1 for v in views if v.get("action") in ("view_doc", "download_pdf", "download_zip"))
        last_ts = views[0].get("viewed_at") if views else None
        out[sh["id"]] = {"scenario_opens": opened, "doc_downloads": downloads, "last_activity_at": last_ts}
    return out


class ShareNoteUpdate(BaseModel):
    note: str = Field(default="", max_length=2000)


@api.patch("/admin/scenarios/{sid}/shares/{share_id}/note")
async def update_share_note(sid: str, share_id: str, body: ShareNoteUpdate, admin=Depends(require_admin)):
    res = await db.scenario_shares.update_one(
        {"id": share_id, "scenario_id": sid},
        {"$set": {"note": body.note, "updated_at": now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Share not found")
    return {"ok": True, "note": body.note}


@api.post("/admin/scenarios/{sid}/shares/{share_id}/grant/{doc_id}")
async def grant_doc_access(sid: str, share_id: str, doc_id: str, admin=Depends(require_admin)):
    share = await db.scenario_shares.find_one({"id": share_id, "scenario_id": sid})
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    grants = set(share.get("doc_grants") or [])
    grants.add(doc_id)
    await db.scenario_shares.update_one({"id": share_id}, {"$set": {"doc_grants": list(grants)}})
    return {"ok": True, "doc_grants": list(grants)}


@api.delete("/admin/scenarios/{sid}/shares/{share_id}/grant/{doc_id}")
async def revoke_doc_access(sid: str, share_id: str, doc_id: str, admin=Depends(require_admin)):
    share = await db.scenario_shares.find_one({"id": share_id, "scenario_id": sid})
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    grants = [g for g in (share.get("doc_grants") or []) if g != doc_id]
    await db.scenario_shares.update_one({"id": share_id}, {"$set": {"doc_grants": grants}})
    return {"ok": True, "doc_grants": grants}


@api.patch("/admin/scenarios/{sid}/shares/{share_id}/overrides")
async def update_share_overrides(sid: str, share_id: str, body: ShareOverridesUpdate, admin=Depends(require_admin)):
    """Set per-doc visibility overrides for a specific lender share.
    Values: 'include' | 'on_request' | 'hidden'. Missing doc_ids fall back to scenario default."""
    share = await db.scenario_shares.find_one({"id": share_id, "scenario_id": sid})
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    # Whenever overrides are updated we clear legacy per-doc grants to keep one source of truth
    await db.scenario_shares.update_one(
        {"id": share_id},
        {"$set": {"doc_overrides": body.doc_overrides, "doc_grants": []}},
    )
    return {"ok": True, "doc_overrides": body.doc_overrides}


@api.delete("/admin/scenarios/{sid}/shares/{share_id}")
async def revoke_share(sid: str, share_id: str, admin=Depends(require_admin)):
    res = await db.scenario_shares.delete_one({"id": share_id, "scenario_id": sid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ---------- Public lender-view endpoints (token-gated, no login) ----------
def _make_view_session(share_id: str, viewer: dict) -> str:
    payload = {
        "share_id": share_id,
        "viewer_name": viewer["viewer_name"],
        "viewer_email": viewer["viewer_email"],
        "viewer_institution": viewer["viewer_institution"],
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        "aud": "lender-view",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _decode_view_session(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    try:
        return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO], audience="lender-view")
    except pyjwt.PyJWTError:
        return None


async def _log_view(scenario_id: str, share_id: str, session: dict, action: str, extra: Optional[dict] = None):
    await db.share_views.insert_one({
        "id": str(uuid.uuid4()),
        "scenario_id": scenario_id,
        "share_id": share_id,
        "action": action,
        "viewer_name": session.get("viewer_name"),
        "viewer_email": session.get("viewer_email"),
        "viewer_institution": session.get("viewer_institution"),
        "extra": extra or {},
        "viewed_at": now_iso(),
    })


@api.get("/lender-view/{token}/preflight")
async def lender_preflight(token: str):
    """Check if a token is valid before the lender enters the gate."""
    share = await db.scenario_shares.find_one({"token": token}, {"_id": 0})
    if not share:
        raise HTTPException(status_code=404, detail="Link not found or revoked")
    scen = await db.scenarios.find_one({"id": share["scenario_id"]}, {"_id": 0, "name": 1})
    return {"ok": True, "scenario_name": scen.get("name") if scen else "Loan Package",
            "recipient_institution": share.get("recipient_institution", "")}


@api.post("/lender-view/{token}/gate")
async def lender_gate(token: str, body: LenderGate, request: Request):
    share = await db.scenario_shares.find_one({"token": token})
    if not share:
        raise HTTPException(status_code=404, detail="Link not found or revoked")
    if not body.acknowledged:
        raise HTTPException(
            status_code=400,
            detail="Please acknowledge the confidentiality notice to view this deal package.",
        )
    payload = body.model_dump()
    # Record which acknowledgement version + when + from where — lightweight audit trail
    payload["acknowledged_version"] = payload.get("acknowledged_version") or LENDER_TERMS_VERSION
    payload["acknowledged_at"] = now_iso()
    payload["acknowledged_ip"] = request.client.host if request and request.client else None
    payload["acknowledged_user_agent"] = request.headers.get("user-agent") if request else None
    session_token = _make_view_session(share["id"], payload)
    await _log_view(share["scenario_id"], share["id"], payload, "gate")
    return {"session_token": session_token, "share_id": share["id"]}


class LenderAckGate(BaseModel):
    """Authenticated lenders only need to acknowledge the confidentiality notice.
    Identity is pulled from their user + lender profile — no re-typing."""
    acknowledged: bool = False
    acknowledged_version: Optional[str] = None


@api.post("/lender-view/{token}/gate-authenticated")
async def lender_gate_authenticated(token: str, body: LenderAckGate,
                                    request: Request, user=Depends(require_lender)):
    """Skip the name/email/institution form for logged-in lenders. Requires the
    lender to own the share (share.lender_id matches their lender record)."""
    share = await db.scenario_shares.find_one({"token": token})
    if not share:
        raise HTTPException(status_code=404, detail="Link not found or revoked")
    if not body.acknowledged:
        raise HTTPException(
            status_code=400,
            detail="Please acknowledge the confidentiality notice to view this deal package.",
        )
    # Verify this lender owns this share (or their institution does)
    lender = await _resolve_lender_for_user(user)
    if share.get("lender_id") != lender["id"]:
        raise HTTPException(status_code=403, detail="This deal package isn't shared with your institution.")
    payload = {
        "viewer_name": user.get("name") or lender.get("name") or user.get("email"),
        "viewer_email": user.get("email"),
        "viewer_institution": lender.get("name") or "",
        "viewer_title": user.get("title") or "",
        "viewer_phone": user.get("phone") or "",
        "acknowledged": True,
        "acknowledged_version": (body.acknowledged_version or LENDER_TERMS_VERSION),
        "acknowledged_at": now_iso(),
        "acknowledged_ip": request.client.host if request and request.client else None,
        "acknowledged_user_agent": request.headers.get("user-agent") if request else None,
        "authenticated_user_id": user["id"],
        "authenticated_lender_id": lender["id"],
    }
    session_token = _make_view_session(share["id"], payload)
    await _log_view(share["scenario_id"], share["id"], payload, "gate_authenticated")
    return {"session_token": session_token, "share_id": share["id"]}


async def _require_view_session(token: str, session_token: Optional[str]):
    share = await db.scenario_shares.find_one({"token": token})
    if not share:
        raise HTTPException(status_code=404, detail="Link not found or revoked")
    session = _decode_view_session(session_token)
    if not session or session.get("share_id") != share["id"]:
        raise HTTPException(status_code=401, detail="Please enter your details to view this package")
    return share, session


def _effective_doc_visibility(share: dict, attach_map: dict, doc_id: str) -> str:
    """Return effective visibility for a single doc on a specific share.
    Returns one of: 'included', 'on_request', 'hidden'.
    Priority: per-share override > legacy per-share grant > scenario doc default (on_request)."""
    overrides = share.get("doc_overrides") or {}
    if doc_id in overrides:
        v = overrides[doc_id]
        return {"include": "included", "on_request": "on_request", "hidden": "hidden"}.get(v, "on_request")
    grants = share.get("doc_grants") or []
    if doc_id in grants:
        return "included"
    # Default: doc's own lender_visibility field; fall back to on_request. Honor all three states.
    scen_v = (attach_map.get(doc_id) or {}).get("lender_visibility", "on_request")
    if scen_v == "hidden":
        return "hidden"
    if scen_v == "included":
        return "included"
    return "on_request"


@api.get("/lender-view/{token}")
async def lender_get_package(token: str, session_token: Optional[str] = None):
    share, session = await _require_view_session(token, session_token)
    scen = await db.scenarios.find_one({"id": share["scenario_id"]}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    metrics = compute_scenario_metrics(scen)
    # Log activity — lender opened the deal package
    await _log_view(share["scenario_id"], share["id"], session, "view_scenario")

    # Every scenario doc is a candidate; the doc's own lender_visibility drives the default,
    # and per-share overrides can flip individual docs to included/on_request/hidden.
    scen_docs = await db.client_docs.find({"scenario_id": share["scenario_id"]}, {"_id": 0}).sort("order", 1).to_list(500)
    await _populate_doc_files(scen_docs)
    doc_map = {d["id"]: d for d in scen_docs}

    docs_out = []
    for cd in scen_docs:
        eff = _effective_doc_visibility(share, doc_map, cd["id"])
        if eff == "hidden":
            continue
        files_meta = cd.get("files") or []
        has_file = bool(files_meta) or bool(cd.get("file_id"))
        viewable = has_file and eff == "included"
        # Only expose file list when actually included; otherwise just show count
        lender_files = []
        if viewable:
            for fm in files_meta:
                lender_files.append({
                    "id": fm.get("id"),
                    "filename": fm.get("filename"),
                    "size": fm.get("size"),
                    "content_type": fm.get("content_type"),
                })
        docs_out.append({
            "id": cd["id"],
            "label": cd["label"],
            "category": cd.get("category"),
            "visibility": cd.get("lender_visibility", "on_request"),
            "has_file": has_file,
            "file_count": len(files_meta),
            "files": lender_files,
            "viewable": viewable,
            "requires_request": eff == "on_request",
        })

    await _log_view(scen["id"], share["id"], session, "view_scenario")

    # Strip client PII from the outer payload
    watermark = f"{session.get('viewer_institution')} — {session.get('viewer_name')}"

    # Sanitize sponsors for lender view — drop client account ids + PII flags
    sponsors_out = []
    for sp in _ensure_sponsors_array(scen):
        sponsors_out.append({
            "name": sp.get("name") or "—",
            "entity": sp.get("entity"),
            "ownership_pct": sp.get("ownership_pct"),
            "role": sp.get("role"),
            "is_guarantor": sp.get("is_guarantor"),
            "credit_score": sp.get("credit_score"),
            "liquidity": sp.get("liquidity"),
            "net_worth": sp.get("net_worth"),
        })
    return {
        "name": scen.get("name"),
        "status": scen.get("status"),
        "sponsor": scen.get("sponsor"),         # legacy field kept for backward compat
        "sponsors": sponsors_out,               # new: array of all sponsors
        "property_info": scen.get("property_info"),
        "loan_request": scen.get("loan_request"),
        "financials": scen.get("financials"),
        "construction": scen.get("construction"),
        "sources_uses": scen.get("sources_uses"),
        "notes": scen.get("notes"),
        "business_plan": scen.get("business_plan"),
        "metrics": metrics,
        "docs": docs_out,
        "watermark": watermark,
        "share_note": share.get("note"),
    }


@api.get("/lender-view/{token}/doc/{doc_id}")
async def lender_get_doc(token: str, doc_id: str,
                         session_token: Optional[str] = None,
                         file_id: Optional[str] = None):
    """Fetch one file from a doc line. `file_id` picks a specific attachment
    (defaults to the first/only file for backwards compat)."""
    share, session = await _require_view_session(token, session_token)
    scen = await db.scenarios.find_one({"id": share["scenario_id"]})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    # Doc must belong to this scenario
    cd = await db.client_docs.find_one({"id": doc_id, "scenario_id": share["scenario_id"]})
    if not cd:
        raise HTTPException(status_code=404, detail="Doc not part of this package")
    attach_map = {doc_id: cd}
    eff = _effective_doc_visibility(share, attach_map, doc_id)
    if eff == "hidden":
        raise HTTPException(status_code=404, detail="Doc not part of this package")
    if eff != "included":
        raise HTTPException(status_code=403, detail="Access not granted for this document yet")
    metas = _ensure_doc_files_meta(cd)
    if not metas:
        raise HTTPException(status_code=404, detail="Document not uploaded")
    # Verify file_id belongs to this doc line (prevents ID guessing across lines)
    if file_id:
        allowed = {m.get("file_id") for m in metas}
        if file_id not in allowed:
            raise HTTPException(status_code=404, detail="File not part of this document")
        target_id = file_id
    else:
        target_id = metas[0].get("file_id")
    f = await db.client_files.find_one({"id": target_id})
    if not f:
        raise HTTPException(status_code=404, detail="File missing")
    await _log_view(scen["id"], share["id"], session, "view_doc",
                    extra={"doc_id": doc_id, "doc_label": cd.get("label"),
                           "file_id": target_id, "filename": f.get("filename")})
    raw = base64.b64decode(f["data_b64"])
    return Response(
        content=raw,
        media_type=f.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{f["filename"]}"'},
    )


@api.get("/lender-view/{token}/doc/{doc_id}/zip")
async def lender_get_doc_zip(token: str, doc_id: str, session_token: Optional[str] = None):
    """Bundle all files attached to ONE doc line into a zip (e.g., all tax returns)."""
    import zipfile
    from io import BytesIO
    share, session = await _require_view_session(token, session_token)
    scen = await db.scenarios.find_one({"id": share["scenario_id"]})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    cd = await db.client_docs.find_one({"id": doc_id, "scenario_id": share["scenario_id"]})
    if not cd:
        raise HTTPException(status_code=404, detail="Doc not part of this package")
    attach_map = {doc_id: cd}
    eff = _effective_doc_visibility(share, attach_map, doc_id)
    if eff != "included":
        raise HTTPException(status_code=403, detail="Access not granted for this document yet")
    metas = _ensure_doc_files_meta(cd)
    if not metas:
        raise HTTPException(status_code=404, detail="Document not uploaded")
    buf = BytesIO()
    used = set()
    included = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for m in metas:
            fid = m.get("file_id")
            if not fid:
                continue
            f = await db.client_files.find_one({"id": fid})
            if not f:
                continue
            base_name = f.get("filename") or "file"
            name, i = base_name, 1
            while name in used:
                stem, dot, ext = base_name.rpartition(".")
                name = f"{stem} ({i}).{ext}" if dot else f"{base_name} ({i})"
                i += 1
            used.add(name)
            included.append(name)
            zf.writestr(name, base64.b64decode(f["data_b64"]))
    if not included:
        raise HTTPException(status_code=404, detail="No files to download")
    buf.seek(0)
    await _log_view(scen["id"], share["id"], session, "download_doc_zip",
                    extra={"doc_id": doc_id, "doc_label": cd.get("label"),
                           "file_count": len(included), "files": included})
    label = (cd.get("label") or "document").replace("/", "-").replace("\\", "-").strip()
    safe = "".join(c if ord(c) < 128 and c not in '\\/:*?"<>|' else "_" for c in label)
    fname = f"byrd-{safe.replace(' ', '_')}-{share['id'][:8]}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.post("/lender-view/{token}/request-docs")
async def lender_request_docs(token: str, background: BackgroundTasks, session_token: Optional[str] = None):
    share, session = await _require_view_session(token, session_token)
    await db.scenario_shares.update_one({"id": share["id"]}, {"$set": {"requested_at": now_iso()}})
    await _log_view(share["scenario_id"], share["id"], session, "request_docs")
    scen = await db.scenarios.find_one({"id": share["scenario_id"]}, {"_id": 0, "name": 1})
    scen_name = (scen or {}).get("name", "Loan Package")
    subj, html, text = tmpl_lender_activity("request_docs", share, session, scen_name)
    for r in broker_emails():
        background.add_task(send_email, r, subj, html, text, "lender-request")
    return {"ok": True}


@api.get("/lender-view/{token}/pdf")
async def lender_get_pdf(token: str, session_token: Optional[str] = None):
    share, session = await _require_view_session(token, session_token)
    scen = await db.scenarios.find_one({"id": share["scenario_id"]}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    metrics = compute_scenario_metrics(scen)
    watermark = f"{session.get('viewer_institution')} — {session.get('viewer_name')}"
    pdf_bytes = render_scenario_pdf(scen, None, metrics, watermark_text=watermark)
    await _log_view(scen["id"], share["id"], session, "download_pdf")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="byrd-package-{share["id"][:8]}.pdf"'},
    )


@api.get("/lender-view/{token}/docs.zip")
async def lender_docs_zip(token: str, session_token: Optional[str] = None):
    """Bundle every currently viewable document into a ZIP for the lender.
    Respects per-share visibility overrides and logs the download in the audit trail."""
    import zipfile
    from io import BytesIO
    share, session = await _require_view_session(token, session_token)
    scen = await db.scenarios.find_one({"id": share["scenario_id"]})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    scen_docs = await db.client_docs.find(
        {"scenario_id": share["scenario_id"]}, {"_id": 0},
    ).sort("order", 1).to_list(500)
    attach_map = {d["id"]: d for d in scen_docs}
    allowed_ids = [
        did for did in attach_map
        if _effective_doc_visibility(share, attach_map, did) == "included"
    ]
    if not allowed_ids:
        raise HTTPException(status_code=404, detail="No documents available to download")
    docs = [d for d in scen_docs if d["id"] in allowed_ids]
    buf = BytesIO()
    used_names = set()
    included_names = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cd in docs:
            metas = _ensure_doc_files_meta(cd)
            if not metas:
                continue
            label = (cd.get("label") or "document").replace("/", "-").replace("\\", "-").strip()
            for m in metas:
                fid = m.get("file_id")
                if not fid:
                    continue
                f = await db.client_files.find_one({"id": fid})
                if not f:
                    continue
                raw = base64.b64decode(f["data_b64"])
                base_name = f.get("filename") or m.get("filename") or "file"
                name = f"{label} - {base_name}"
                n, i = name, 1
                while n in used_names:
                    stem, dot, ext = name.rpartition(".")
                    n = f"{stem} ({i}).{ext}" if dot else f"{name} ({i})"
                    i += 1
                used_names.add(n)
                included_names.append(n)
                zf.writestr(n, raw)
    if not included_names:
        raise HTTPException(status_code=404, detail="No files to download")
    buf.seek(0)
    await _log_view(scen["id"], share["id"], session, "download_zip",
                    extra={"file_count": len(included_names), "files": included_names})
    safe_name = "".join(c if ord(c) < 128 and c not in '\\/:*?"<>|' else "_" for c in (scen.get('name') or 'package'))
    fname = f"byrd-{safe_name.replace(' ', '_')}-{share['id'][:8]}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )



# ================ Lender Marketplace ================
# Self-registration flow, per-lender portal (invites + credit box + term sheets),
# structured term-sheet submission, admin approval + auto-match invites.


class LenderApplyBody(BaseModel):
    # Company + primary contact
    lender_name: str = Field(min_length=2, max_length=200)
    institution_type: str = "bank"   # bank / credit_union / private / agency / bridge / hard_money / other
    contact_name: str = Field(min_length=1, max_length=200)
    contact_title: str = Field(default="", max_length=120)
    contact_email: EmailStr
    contact_phone: str = Field(default="", max_length=40)
    website: str = Field(default="", max_length=200)
    # Credit box (all optional at apply time)
    property_types: List[str] = Field(default_factory=list)
    # Optional specialties within a top-level property type (e.g. Industrial ->
    # ["Manufacturing Heavy Industrial", "Warehouse Cold Storage"]). When empty for a
    # given top-level, the lender is treated as "open to all sub-types" of that type.
    property_subtypes: List[str] = Field(default_factory=list)
    geography: List[str] = Field(default_factory=list)
    min_loan: Optional[float] = None
    max_loan: Optional[float] = None
    max_ltv: Optional[float] = None
    max_ltc: Optional[float] = None
    min_dscr: Optional[float] = None
    min_debt_yield: Optional[float] = None
    rate_min: Optional[float] = None
    rate_max: Optional[float] = None
    typical_term_months: Optional[int] = None
    recourse_preference: str = ""
    decision_speed_days: Optional[int] = None
    typical_fees: str = ""
    notes: str = ""
    # Kept for optional forward-compatibility if we ever bring the full agreement back.
    # No longer required or enforced at registration time.
    terms_accepted: Optional[bool] = None
    terms_signature_name: Optional[str] = Field(default=None, max_length=200)
    terms_version: Optional[str] = Field(default=None, max_length=20)


class LenderApproveBody(BaseModel):
    lender_id: str


class LenderActivateBody(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class CreditBoxUpdate(BaseModel):
    lender_name: Optional[str] = None
    institution_type: Optional[str] = None
    property_types: Optional[List[str]] = None
    property_subtypes: Optional[List[str]] = None
    geography: Optional[List[str]] = None
    min_loan: Optional[float] = None
    max_loan: Optional[float] = None
    max_ltv: Optional[float] = None
    max_ltc: Optional[float] = None
    min_dscr: Optional[float] = None
    min_debt_yield: Optional[float] = None
    rate_min: Optional[float] = None
    rate_max: Optional[float] = None
    typical_term_months: Optional[int] = None
    recourse_preference: Optional[str] = None
    decision_speed_days: Optional[int] = None
    typical_fees: Optional[str] = None
    notes: Optional[str] = None


class TermSheetBody(BaseModel):
    # Core (mostly optional; broker only needs enough to compare)
    rate_type: Optional[Literal["fixed", "floating", "hybrid"]] = None
    interest_rate_pct: Optional[float] = None
    floating_index: Optional[str] = None       # e.g., "SOFR", "Prime"
    floating_spread_bps: Optional[float] = None
    loan_amount: Optional[float] = None
    ltv_pct: Optional[float] = None
    ltc_pct: Optional[float] = None
    amortization_years: Optional[int] = None
    term_months: Optional[int] = None
    io_months: Optional[int] = None            # interest-only period
    # Hybrid ARM fields (e.g., a 5/20 ARM at 20-yr amort has fixed_period_months=60, term_months=240, amortization_years=20)
    fixed_period_months: Optional[int] = None   # length of the initial fixed-rate period
    rate_adjustment_notes: Optional[str] = None # freeform for reset frequency + caps (e.g., "Annual reset after fixed period, 2/2/5 caps")
    recourse: Optional[Literal["full", "partial", "non-recourse"]] = None
    prepay: Optional[str] = None               # freeform, e.g. "3-2-1"
    origination_fee_pct: Optional[float] = None
    exit_fee_pct: Optional[float] = None
    expiration_date: Optional[str] = None      # ISO date
    contingencies: Optional[str] = None
    notes: Optional[str] = None
    pdf_file_id: Optional[str] = None          # file uploaded separately via /admin/files


class TermSheetStatusBody(BaseModel):
    status: Literal["accepted", "countered", "passed"]
    broker_note: str = Field(default="", max_length=4000)


class LenderInviteBody(BaseModel):
    lender_ids: List[str] = Field(min_length=1)
    note: str = Field(default="", max_length=2000)


# --- Utility helpers ---

def _sanitize_lender_public(lender: dict) -> dict:
    """Strip fields lenders shouldn't see about themselves (e.g. internal broker notes)."""
    if not lender:
        return {}
    out = {k: v for k, v in lender.items() if k not in ("broker_id",)}
    return out


async def _make_lender_activation_token(lender_id: str, user_id: str) -> str:
    tok = uuid.uuid4().hex + uuid.uuid4().hex
    await db.lender_activation_tokens.insert_one({
        "id": str(uuid.uuid4()),
        "token": tok,
        "lender_id": lender_id,
        "user_id": user_id,
        "created_at": now_iso(),
        "used_at": None,
    })
    return tok


async def _resolve_lender_for_user(user: dict) -> dict:
    """Get the lender record owned by this lender-role user."""
    lender = await db.lenders.find_one({"owner_user_id": user["id"]}, {"_id": 0})
    if not lender:
        raise HTTPException(status_code=404, detail="No lender record linked to this account")
    return lender


# --- 1. PUBLIC: self-register (apply) ---

@api.get("/public/lender/terms")
async def lender_terms_public():
    """Public: return the current Non-Circumvention Agreement so the apply form
    and the /lenders/terms page render the same authoritative text."""
    return {
        "version": LENDER_TERMS_VERSION,
        "title": LENDER_TERMS_TITLE,
        "effective_date": LENDER_TERMS_EFFECTIVE_DATE,
        "text": LENDER_TERMS_TEXT,
    }


@api.post("/public/lender/apply")
async def lender_apply(body: LenderApplyBody, background: BackgroundTasks, request: Request):
    email = body.contact_email.lower()
    # Reject if any user with this email already exists in ANY role
    existing_user = await db.users.find_one({"email": email})
    if existing_user:
        raise HTTPException(status_code=400,
                            detail="An account with this email already exists. Log in instead.")
    # Reject if the lender is already applied/approved
    existing_lender = await db.lenders.find_one({
        "$or": [
            {"contacts.email": email},
            {"apply_email": email},
        ]
    }, {"_id": 0, "id": 1, "status": 1})
    if existing_lender:
        raise HTTPException(status_code=400,
                            detail="An application from this email is already on file.")
    now = now_iso()
    lender_id = str(uuid.uuid4())
    doc = {
        "id": lender_id,
        "name": body.lender_name,
        "institution_type": body.institution_type,
        "contacts": [{
            "name": body.contact_name, "title": body.contact_title,
            "phone": body.contact_phone, "email": email,
        }],
        "property_types": body.property_types,
        "property_subtypes": body.property_subtypes,
        "geography": [g.upper() for g in body.geography if g],
        "min_loan": body.min_loan, "max_loan": body.max_loan,
        "max_ltv": body.max_ltv, "max_ltc": body.max_ltc,
        "min_dscr": body.min_dscr, "min_debt_yield": body.min_debt_yield,
        "rate_min": body.rate_min, "rate_max": body.rate_max,
        "typical_term_months": body.typical_term_months,
        "recourse_preference": body.recourse_preference,
        "decision_speed_days": body.decision_speed_days,
        "typical_fees": body.typical_fees,
        "notes": body.notes,
        "website": body.website,
        "status": "active",              # match filter status
        "approval_status": "pending",    # NEW: pending / approved / rejected
        "self_registered": True,
        "apply_email": email,
        "owner_user_id": None,           # set on approval
        "created_at": now,
        "updated_at": now,
    }
    await db.lenders.insert_one(doc)
    subj, html, text = tmpl_lender_application_received(body.lender_name, email)
    background.add_task(send_email, email, subj, html, text, "lender_application")
    # Also notify all brokers so they can triage from the inbox — same pattern as
    # client-upload alerts (opt-out via NOTIFY_BROKER_ON_LENDER_APPLY=false).
    brokers = broker_emails()
    if brokers and str(os.environ.get("NOTIFY_BROKER_ON_LENDER_APPLY", "true")).lower() not in ("0", "false", "no", "off"):
        b_subj, b_html, b_text = tmpl_lender_application_broker_alert(
            lender_name=body.lender_name,
            contact_name=body.contact_name,
            contact_email=email,
            contact_phone=body.contact_phone or "",
            institution_type=body.institution_type or "",
            property_types=body.property_types or [],
            property_subtypes=body.property_subtypes or [],
            geography=[g.upper() for g in (body.geography or []) if g],
            min_loan=body.min_loan, max_loan=body.max_loan,
            notes=body.notes or "",
        )
        for r in brokers:
            background.add_task(send_email, r, b_subj, b_html, b_text, "lender_application_alert")
    return {"ok": True, "id": lender_id}


# --- 2. ADMIN: pending / approve / reject ---

@api.get("/admin/marketplace/pending-lenders")
async def admin_list_pending_lenders(admin=Depends(require_admin)):
    return await db.lenders.find(
        {"approval_status": "pending", "self_registered": True},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)


@api.post("/admin/marketplace/lenders/{lid}/approve")
async def admin_approve_lender(lid: str, background: BackgroundTasks, admin=Depends(require_admin)):
    lender = await db.lenders.find_one({"id": lid})
    if not lender:
        raise HTTPException(status_code=404, detail="Lender not found")
    if lender.get("approval_status") == "approved":
        raise HTTPException(status_code=400, detail="Already approved")
    email = (lender.get("apply_email") or "").lower()
    contact_name = (lender.get("contacts") or [{}])[0].get("name") or lender.get("name")
    if not email:
        raise HTTPException(status_code=400, detail="No contact email on record")
    # Check user doesn't already exist
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="A user with this email already exists")
    user_id = str(uuid.uuid4())
    await db.users.insert_one({
        "id": user_id,
        "email": email,
        "name": contact_name,
        "role": "lender",
        "password_hash": None,
        "pending": True,
        "created_by": admin["id"],
        "created_at": now_iso(),
    })
    tok = await _make_lender_activation_token(lid, user_id)
    await db.lenders.update_one(
        {"id": lid},
        {"$set": {
            "approval_status": "approved",
            "owner_user_id": user_id,
            "approved_at": now_iso(),
            "approved_by_admin_id": admin["id"],
            "updated_at": now_iso(),
        }},
    )
    activate_url = (f"{public_base_url()}/lender/activate/{tok}"
                    if public_base_url() else f"/lender/activate/{tok}")
    subj, html, text = tmpl_lender_approved(lender.get("name") or contact_name, activate_url)
    background.add_task(send_email, email, subj, html, text, "lender_approved")
    return {"ok": True, "activate_url": activate_url}


@api.post("/admin/marketplace/lenders/{lid}/reject")
async def admin_reject_lender(lid: str, admin=Depends(require_admin)):
    lender = await db.lenders.find_one({"id": lid})
    if not lender:
        raise HTTPException(status_code=404, detail="Lender not found")
    await db.lenders.update_one(
        {"id": lid},
        {"$set": {"approval_status": "rejected", "updated_at": now_iso(),
                  "rejected_at": now_iso(), "rejected_by_admin_id": admin["id"]}},
    )
    return {"ok": True}


# --- 3. LENDER: activate + get me + credit box ---

@api.get("/lender/activate/{token}")
async def get_lender_activation(token: str):
    tok = await db.lender_activation_tokens.find_one({"token": token}, {"_id": 0})
    if not tok:
        raise HTTPException(status_code=404, detail="Activation link not found")
    if tok.get("used_at"):
        raise HTTPException(status_code=410, detail="Link already used")
    lender = await db.lenders.find_one({"id": tok["lender_id"]}, {"_id": 0, "name": 1})
    user = await db.users.find_one({"id": tok["user_id"]}, {"_id": 0, "email": 1, "name": 1})
    return {
        "lender_name": lender.get("name") if lender else "",
        "email": user.get("email") if user else "",
        "contact_name": user.get("name") if user else "",
    }


@api.post("/lender/activate/{token}", response_model=AuthResponse)
async def lender_activate(token: str, body: LenderActivateBody):
    tok = await db.lender_activation_tokens.find_one({"token": token})
    if not tok:
        raise HTTPException(status_code=404, detail="Activation link not found")
    if tok.get("used_at"):
        raise HTTPException(status_code=410, detail="Link already used")
    user = await db.users.find_one({"id": tok["user_id"]})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"password_hash": hash_pw(body.password), "pending": False,
                  "activated_at": now_iso()}},
    )
    await db.lender_activation_tokens.update_one({"id": tok["id"]},
                                                 {"$set": {"used_at": now_iso()}})
    return {"token": make_token(user["id"]), "user": sanitize_user({**user, "role": "lender"})}


@api.get("/lender/me")
async def lender_me(user=Depends(require_lender)):
    lender = await _resolve_lender_for_user(user)
    return _sanitize_lender_public(lender)


@api.patch("/lender/me/credit-box")
async def lender_update_credit_box(body: CreditBoxUpdate, user=Depends(require_lender)):
    lender = await _resolve_lender_for_user(user)
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if "lender_name" in update:
        update["name"] = update.pop("lender_name")
    if "geography" in update and update["geography"] is not None:
        update["geography"] = [g.upper() for g in update["geography"]]
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = now_iso()
    await db.lenders.update_one({"id": lender["id"]}, {"$set": update})
    updated = await db.lenders.find_one({"id": lender["id"]}, {"_id": 0})
    return _sanitize_lender_public(updated)


# --- 4. LENDER: invites list (scenarios shared with me) ---

@api.get("/lender/invites")
async def lender_list_invites(user=Depends(require_lender)):
    lender = await _resolve_lender_for_user(user)
    shares = await db.scenario_shares.find(
        {"lender_id": lender["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    out = []
    for sh in shares:
        scen = await db.scenarios.find_one(
            {"id": sh["scenario_id"]},
            {"_id": 0, "id": 1, "name": 1, "property_info": 1, "loan_request": 1, "status": 1},
        )
        if not scen:
            continue
        # Has this lender already submitted a term sheet on this scenario?
        ts = await db.term_sheets.find_one(
            {"scenario_id": sh["scenario_id"], "lender_id": lender["id"]},
            {"_id": 0, "id": 1, "status": 1, "submitted_at": 1},
        )
        out.append({
            "share_id": sh["id"],
            "token": sh["token"],
            "invited_at": sh.get("created_at"),
            "broker_note": sh.get("note", ""),
            "scenario": {
                "id": scen["id"],
                "name": scen.get("name"),
                "status": scen.get("status"),
                "property_type": (scen.get("property_info") or {}).get("property_type"),
                "location": ", ".join(x for x in [(scen.get("property_info") or {}).get("city"),
                                                  (scen.get("property_info") or {}).get("state")] if x),
                "loan_amount": (scen.get("loan_request") or {}).get("loan_amount"),
                "loan_type": (scen.get("loan_request") or {}).get("loan_type"),
            },
            "term_sheet": ts,
        })
    return out


# --- 5. LENDER: term sheet CRUD ---

@api.get("/lender/term-sheets")
async def lender_list_term_sheets(user=Depends(require_lender)):
    lender = await _resolve_lender_for_user(user)
    sheets = await db.term_sheets.find(
        {"lender_id": lender["id"]}, {"_id": 0}
    ).sort("submitted_at", -1).to_list(500)
    # Enrich with scenario name
    for s in sheets:
        scen = await db.scenarios.find_one({"id": s.get("scenario_id")},
                                          {"_id": 0, "name": 1, "id": 1})
        s["scenario_name"] = scen.get("name") if scen else "(deleted deal)"
    await _hydrate_ts_docs(sheets)
    return sheets


@api.post("/lender/scenarios/{sid}/term-sheet/upload")
async def lender_upload_term_sheet_doc(sid: str, body: DocUploadInput,
                                       request: Request, user=Depends(require_lender)):
    """Lender uploads their own term-sheet document (PDF / Word / etc.) in lieu of or
    alongside the structured form. Returns a file_id to pass to POST /term-sheet as pdf_file_id."""
    lender = await _resolve_lender_for_user(user)
    share = await db.scenario_shares.find_one({"scenario_id": sid, "lender_id": lender["id"]})
    if not share:
        raise HTTPException(status_code=403, detail="You have not been invited to this deal")
    # Reuse the standard base64 validation & size cap from _append_file_to_doc semantics
    try:
        raw = base64.b64decode(body.data_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_FILE_MB}MB limit")
    file_id = str(uuid.uuid4())
    now = now_iso()
    await db.term_sheet_files.insert_one({
        "id": file_id,
        "scenario_id": sid,
        "lender_id": lender["id"],
        "uploaded_by_user_id": user["id"],
        "filename": body.filename,
        "content_type": body.content_type,
        "size": len(raw),
        "data_b64": body.data_b64,
        "uploaded_at": now,
    })
    await audit_log(db, event_type="document.upload", request=request, user=user,
                    resource_type="term_sheet_file", resource_id=file_id,
                    resource_name=body.filename,
                    metadata={"scenario_id": sid, "lender_id": lender["id"],
                              "size_bytes": len(raw), "content_type": body.content_type})
    return {"ok": True, "file_id": file_id, "filename": body.filename, "size": len(raw)}


class TermSheetParseBody(BaseModel):
    pdf_file_id: str


def _extract_pdf_text(raw_bytes: bytes) -> str:
    """Best-effort text extraction from a PDF. Returns empty string on failure."""
    try:
        from pypdf import PdfReader
        from io import BytesIO
        reader = PdfReader(BytesIO(raw_bytes))
        pages = []
        for p in reader.pages[:20]:  # cap to first 20 pages to control token cost
            try:
                pages.append(p.extract_text() or "")
            except Exception:
                pages.append("")
        return "\n\n".join(pages).strip()
    except Exception:
        return ""


TERM_SHEET_PARSE_SYSTEM = """\
You extract structured loan term-sheet data from lender documents. Return ONLY compact JSON with these keys (all optional — omit or set null if not clearly stated):
rate_type ("fixed"|"floating"|"hybrid"), interest_rate_pct (number, percent), floating_index (string), floating_spread_bps (number), loan_amount (number, USD),
ltv_pct (number), ltc_pct (number), amortization_years (integer), term_months (integer), io_months (integer), fixed_period_months (integer),
rate_adjustment_notes (string), recourse ("full"|"partial"|"non-recourse"), prepay (string), origination_fee_pct (number), exit_fee_pct (number),
expiration_date (YYYY-MM-DD), contingencies (string, semicolon-separated bullets), notes (string).

Rules:
- Never invent values. If not clearly stated, omit the key.
- Convert years→months for term_months, months→years for amortization_years.
- "5/20 ARM" means fixed_period_months=60 and term_months=240.
- "2/2/5 caps" is rate_adjustment_notes content, not a numeric field.
- Return raw JSON only, no markdown fences, no commentary."""


@api.post("/lender/scenarios/{sid}/term-sheet/parse-doc")
async def lender_parse_term_sheet_doc(sid: str, body: TermSheetParseBody,
                                      user=Depends(require_lender)):
    """Read an uploaded term-sheet document, extract structured fields with Claude,
    return a plain dict the client can drop into the form. Lender-facing UI calls this
    "Auto-fill term sheet from document" — no reference to Ada by name."""
    lender = await _resolve_lender_for_user(user)
    f = await db.term_sheet_files.find_one(
        {"id": body.pdf_file_id, "scenario_id": sid, "lender_id": lender["id"]},
        {"_id": 0},
    )
    if not f:
        raise HTTPException(status_code=404, detail="Uploaded document not found or not owned by you")
    ct = (f.get("content_type") or "").lower()
    raw = base64.b64decode(f["data_b64"])
    text = ""
    if "pdf" in ct or f.get("filename", "").lower().endswith(".pdf"):
        text = _extract_pdf_text(raw)
    else:
        # Non-PDFs (Word, images) — try naive utf-8 decode; if it fails, fall back to Claude vision (skipped for now)
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
    if not text or len(text.strip()) < 30:
        raise HTTPException(status_code=422,
                            detail="Couldn't read enough text from this document to auto-fill. It may be a scanned image — please fill the form manually.")
    # Cap text sent to LLM (protect token budget)
    text = text[:18000]
    session_id = f"ts-parse-{body.pdf_file_id[:8]}"
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id, system_message=TERM_SHEET_PARSE_SYSTEM)
    chat.with_model("anthropic", "claude-sonnet-4-5-20250929")
    try:
        reply = await chat.send_message(UserMessage(text=f"Extract term sheet fields from this document text:\n\n{text}"))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Auto-fill service failed: {e}")
    # Robustly parse the LLM's JSON reply
    txt = (reply or "").strip()
    if txt.startswith("```"):
        # strip any accidental fences
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:].strip()
    try:
        parsed = json.loads(txt)
        if not isinstance(parsed, dict):
            raise ValueError("not an object")
    except Exception:
        raise HTTPException(status_code=502,
                            detail="Couldn't parse auto-fill output — please fill the form manually.")
    # Whitelist keys to avoid injection into unexpected fields
    allowed = {
        "rate_type", "interest_rate_pct", "floating_index", "floating_spread_bps",
        "loan_amount", "ltv_pct", "ltc_pct", "amortization_years", "term_months",
        "io_months", "fixed_period_months", "rate_adjustment_notes", "recourse",
        "prepay", "origination_fee_pct", "exit_fee_pct", "expiration_date",
        "contingencies", "notes",
    }
    clean = {k: v for k, v in parsed.items() if k in allowed and v not in (None, "", [], {})}
    return {"ok": True, "extracted": clean, "field_count": len(clean)}


@api.get("/term-sheets/{ts_id}/document")
async def download_term_sheet_document(ts_id: str, request: Request, download: int = 0,
                                        user=Depends(get_current_user)):
    """Download the term-sheet attachment. Allowed for: (a) any admin, (b) the submitting
    lender / same-institution lender, (c) the borrower client(s) for the scenario."""
    ts = await db.term_sheets.find_one({"id": ts_id}, {"_id": 0})
    if not ts:
        raise HTTPException(status_code=404, detail="Term sheet not found")
    file_id = ts.get("pdf_file_id")
    if not file_id:
        raise HTTPException(status_code=404, detail="No document attached to this term sheet")
    # Auth check
    ok = False
    if user.get("role") == "admin":
        ok = True
    elif user.get("role") == "lender":
        # Same-institution lender
        try:
            lender = await _resolve_lender_for_user(user)
            if lender and lender["id"] == ts.get("lender_id"):
                ok = True
        except Exception:
            pass
    elif user.get("role") == "client":
        # Client must be linked to the scenario (primary or as a sponsor)
        scen = await db.scenarios.find_one(
            {"id": ts.get("scenario_id")}, {"_id": 0, "client_id": 1, "sponsors": 1},
        )
        if scen:
            if scen.get("client_id") == user["id"]:
                ok = True
            else:
                for sp in (scen.get("sponsors") or []):
                    if sp.get("client_user_id") == user["id"]:
                        ok = True
                        break
    if not ok:
        raise HTTPException(status_code=403, detail="Not authorized")
    f = await db.term_sheet_files.find_one({"id": file_id})
    if not f:
        raise HTTPException(status_code=404, detail="File missing")
    raw = base64.b64decode(f["data_b64"])
    is_download = bool(download)
    await audit_log(
        db,
        event_type=("document.download" if is_download else "term_sheet.view"),
        request=request, user=user,
        resource_type="term_sheet", resource_id=ts_id,
        resource_name=f.get("filename"),
        metadata={"scenario_id": ts.get("scenario_id"), "lender_id": ts.get("lender_id"),
                  "size_bytes": len(raw)},
    )
    disposition = f'{"attachment" if is_download else "inline"}; filename="{f["filename"]}"'
    return Response(
        content=raw,
        media_type=f.get("content_type") or "application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@api.post("/lender/scenarios/{sid}/term-sheet")
async def lender_submit_term_sheet(sid: str, body: TermSheetBody, background: BackgroundTasks,
                                    request: Request, user=Depends(require_lender)):
    lender = await _resolve_lender_for_user(user)
    # Must have a share for this scenario
    share = await db.scenario_shares.find_one({"scenario_id": sid, "lender_id": lender["id"]})
    if not share:
        raise HTTPException(status_code=403, detail="You have not been invited to this deal")
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    # If a pdf_file_id was provided, verify it belongs to this lender + scenario
    if body.pdf_file_id:
        f = await db.term_sheet_files.find_one(
            {"id": body.pdf_file_id, "scenario_id": sid, "lender_id": lender["id"]},
            {"_id": 0, "id": 1},
        )
        if not f:
            raise HTTPException(status_code=400, detail="Uploaded document not found or not owned by you")
    # A submission is only valid if EITHER the structured form has enough info OR a document is attached
    has_form = any(getattr(body, k, None) is not None for k in
                   ("interest_rate_pct", "loan_amount", "term_months", "amortization_years"))
    if not body.pdf_file_id and not has_form:
        raise HTTPException(
            status_code=400,
            detail="Please either upload a term-sheet document or fill in at least one of: rate, loan amount, term, or amortization.",
        )
    # One active term sheet per (scenario, lender) — if one exists in state 'submitted', update it
    existing = await db.term_sheets.find_one({"scenario_id": sid, "lender_id": lender["id"],
                                             "status": {"$in": ["submitted", "countered"]}})
    now = now_iso()
    doc = {
        **body.model_dump(exclude_none=True),
        "scenario_id": sid,
        "lender_id": lender["id"],
        "lender_name": lender.get("name"),
        "submitted_by_user_id": user["id"],
        "status": "submitted",
        "broker_note": "",
        "updated_at": now,
    }
    if existing:
        doc["id"] = existing["id"]
        doc["submitted_at"] = existing.get("submitted_at") or now
        await db.term_sheets.update_one({"id": existing["id"]}, {"$set": doc})
        ts_id = existing["id"]
    else:
        doc["id"] = str(uuid.uuid4())
        doc["submitted_at"] = now
        await db.term_sheets.insert_one(doc)
        ts_id = doc["id"]
    # Notify brokers via Postmark + create task for the primary broker (Wayne if exists)
    admins = await db.users.find({"role": "admin"}, {"_id": 0, "id": 1, "name": 1, "email": 1}).to_list(20)
    admin_url = (f"{public_base_url()}/admin/scenarios/{sid}"
                 if public_base_url() else f"/admin/scenarios/{sid}")
    rate_str = (f"{doc.get('interest_rate_pct'):.2f}%" if doc.get('interest_rate_pct') is not None else "—")
    la = doc.get("loan_amount")
    la_str = f"${la:,.0f}" if la else "—"
    ltv = doc.get("ltv_pct")
    ltv_str = f"{ltv:.1f}%" if ltv is not None else "—"
    for a in admins:
        subj, html, text = tmpl_term_sheet_submitted(a.get("name") or "there",
                                                      lender.get("name"),
                                                      scen.get("name"),
                                                      rate_str, ltv_str, la_str, admin_url)
        background.add_task(send_email, a["email"], subj, html, text, "term_sheet_submitted")
        # Task on their Personal Assistant
        await db.assistant_tasks.insert_one({
            "id": str(uuid.uuid4()),
            "admin_id": a["id"],
            "title": f"Review term sheet from {lender.get('name')} on {scen.get('name')}",
            "notes": f"Rate {rate_str}, Loan {la_str}, LTV {ltv_str}. Open the scenario to compare.",
            "due_date": None,
            "related_name": lender.get("name"),
            "assigned_by_name": None,
            "status": "open",
            "source": "term_sheet_submitted",
            "created_at": now,
            "updated_at": now,
        })
    await audit_log(db, event_type="term_sheet.submit", request=request, user=user,
                    resource_type="term_sheet", resource_id=ts_id,
                    resource_name=(lender or {}).get("name"),
                    metadata={"scenario_id": sid, "scenario_name": scen.get("name"),
                              "lender_id": lender["id"],
                              "interest_rate_pct": doc.get("interest_rate_pct"),
                              "loan_amount": doc.get("loan_amount"),
                              "updated_existing": bool(existing)})
    return {"ok": True, "id": ts_id}


def _has_summary_pdf(ts: dict) -> bool:
    """True when a term sheet has a downloadable lender-uploaded document."""
    return bool(ts.get("pdf_file_id"))


@api.delete("/lender/term-sheets/{tid}")
async def lender_withdraw_term_sheet(tid: str, request: Request, user=Depends(require_lender)):
    lender = await _resolve_lender_for_user(user)
    ts = await db.term_sheets.find_one({"id": tid, "lender_id": lender["id"]})
    if not ts:
        raise HTTPException(status_code=404, detail="Term sheet not found")
    if ts.get("status") == "accepted":
        raise HTTPException(status_code=400, detail="Cannot withdraw an accepted term sheet — call your broker")
    await db.term_sheets.update_one({"id": tid},
                                    {"$set": {"status": "withdrawn", "updated_at": now_iso()}})
    await audit_log(db, event_type="term_sheet.delete", request=request, user=user,
                    resource_type="term_sheet", resource_id=tid,
                    resource_name=lender.get("name"),
                    metadata={"reason": "lender_withdraw", "scenario_id": ts.get("scenario_id")})
    return {"ok": True}


async def _hydrate_ts_docs(sheets: list[dict]) -> list[dict]:
    """For each term sheet with pdf_file_id, attach a shallow {document: {filename, size}}
    lookup so the UI can show 'Download NameOfDoc.pdf (52kB)'. No file bytes returned."""
    ids = [s["pdf_file_id"] for s in sheets if s.get("pdf_file_id")]
    if not ids:
        return sheets
    by_id: dict[str, dict] = {}
    async for f in db.term_sheet_files.find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "filename": 1, "size": 1, "content_type": 1},
    ):
        by_id[f["id"]] = f
    for s in sheets:
        fid = s.get("pdf_file_id")
        if fid and fid in by_id:
            s["document"] = by_id[fid]
    return sheets


# --- 6. ADMIN: view term sheets on a scenario + change status ---

@api.get("/admin/scenarios/{sid}/term-sheets")
async def admin_list_term_sheets(sid: str, admin=Depends(require_admin)):
    sheets = await db.term_sheets.find(
        {"scenario_id": sid}, {"_id": 0}
    ).sort("submitted_at", -1).to_list(200)
    await _hydrate_ts_docs(sheets)
    return sheets


@api.delete("/admin/term-sheets/{tid}")
async def admin_delete_term_sheet(tid: str, request: Request, admin=Depends(require_admin)):
    """Hard-delete a term sheet + its attached file. Removes it from both admin and borrower views."""
    ts = await db.term_sheets.find_one({"id": tid}, {"_id": 0})
    if not ts:
        raise HTTPException(status_code=404, detail="Term sheet not found")
    if ts.get("pdf_file_id"):
        await db.term_sheet_files.delete_one({"id": ts["pdf_file_id"]})
    await db.term_sheets.delete_one({"id": tid})
    await audit_log(db, event_type="term_sheet.delete", request=request, user=admin,
                    resource_type="term_sheet", resource_id=tid,
                    resource_name=ts.get("lender_name"),
                    metadata={"reason": "admin_delete", "scenario_id": ts.get("scenario_id"),
                              "lender_id": ts.get("lender_id")})
    return {"ok": True}


@api.patch("/admin/term-sheets/{tid}")
async def admin_set_term_sheet_status(tid: str, body: TermSheetStatusBody,
                                       background: BackgroundTasks, request: Request,
                                       admin=Depends(require_admin)):
    ts = await db.term_sheets.find_one({"id": tid})
    if not ts:
        raise HTTPException(status_code=404, detail="Term sheet not found")
    prev_status = ts.get("status")
    await db.term_sheets.update_one(
        {"id": tid},
        {"$set": {"status": body.status, "broker_note": body.broker_note,
                  "acted_by_admin_id": admin["id"], "acted_at": now_iso(),
                  "updated_at": now_iso()}},
    )
    await audit_log(db, event_type="term_sheet.status_change", request=request, user=admin,
                    resource_type="term_sheet", resource_id=tid,
                    resource_name=ts.get("lender_name"),
                    metadata={"from": prev_status, "to": body.status,
                              "scenario_id": ts.get("scenario_id"),
                              "lender_id": ts.get("lender_id"),
                              "has_broker_note": bool(body.broker_note)})
    # Notify the lender's owner user
    lender = await db.lenders.find_one({"id": ts.get("lender_id")}, {"_id": 0})
    scen = await db.scenarios.find_one({"id": ts.get("scenario_id")}, {"_id": 0, "name": 1})
    if lender and lender.get("owner_user_id"):
        owner = await db.users.find_one({"id": lender["owner_user_id"]},
                                       {"_id": 0, "email": 1, "name": 1})
        if owner and owner.get("email"):
            subj, html, text = tmpl_term_sheet_status_change(
                lender.get("name") or owner.get("name") or "there",
                (scen or {}).get("name") or "your deal",
                body.status, body.broker_note,
            )
            background.add_task(send_email, owner["email"], subj, html, text, f"term_sheet_{body.status}")
    return {"ok": True}


# --- 7. ADMIN: auto-match suggestions + bulk invite ---

@api.get("/admin/scenarios/{sid}/match-suggestions")
async def admin_match_suggestions(sid: str, admin=Depends(require_admin)):
    """Return APPROVED, self-registered lenders that match this scenario AND haven't been invited yet."""
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    # Only self-reg + approved lenders eligible for auto-invite
    lenders = await db.lenders.find(
        {"approval_status": "approved", "self_registered": True},
        {"_id": 0},
    ).to_list(500)
    already = {sh["lender_id"] async for sh in db.scenario_shares.find(
        {"scenario_id": sid, "lender_id": {"$ne": None}}, {"_id": 0, "lender_id": 1})
        if sh.get("lender_id")}
    eligible = [l for l in lenders if l["id"] not in already]
    matches = match_lenders(scen, eligible)
    # Only return fit/partial
    return [m for m in matches if m.get("verdict") in ("fit", "partial")]


@api.post("/admin/scenarios/{sid}/invite-lenders")
async def admin_invite_lenders(sid: str, body: LenderInviteBody, background: BackgroundTasks,
                                admin=Depends(require_admin)):
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    invited: list[dict] = []
    for lid in body.lender_ids:
        lender = await db.lenders.find_one({"id": lid}, {"_id": 0})
        if not lender:
            continue
        # Idempotent: skip if already invited
        existing = await db.scenario_shares.find_one({"scenario_id": sid, "lender_id": lid})
        if existing:
            invited.append({"lender_id": lid, "share_id": existing["id"], "already": True})
            continue
        primary_contact = (lender.get("contacts") or [{}])[0]
        share_id = str(uuid.uuid4())
        tok = uuid.uuid4().hex + uuid.uuid4().hex
        await db.scenario_shares.insert_one({
            "id": share_id,
            "scenario_id": sid,
            "lender_id": lid,
            "lender_name": lender.get("name"),
            "recipient_name": primary_contact.get("name", ""),
            "recipient_email": (primary_contact.get("email") or "").lower(),
            "recipient_institution": lender.get("name"),
            "note": body.note,
            "token": tok,
            "doc_overrides": {},
            "doc_grants": [],
            "created_by": admin["id"],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        # Email the owner if self-registered, otherwise the contact email
        target_email = None
        if lender.get("owner_user_id"):
            owner = await db.users.find_one({"id": lender["owner_user_id"]},
                                           {"_id": 0, "email": 1})
            if owner:
                target_email = owner.get("email")
        target_email = target_email or (primary_contact.get("email") or "").lower()
        if target_email:
            portal_url = (f"{public_base_url()}/lender/portal"
                          if public_base_url() else "/lender/portal")
            subj, html, text = tmpl_lender_invite(lender.get("name"),
                                                   scen.get("name"),
                                                   portal_url,
                                                   body.note)
            background.add_task(send_email, target_email, subj, html, text, "lender_invite")
        invited.append({"lender_id": lid, "share_id": share_id, "already": False})
    return {"invited": invited}


# --- 8. CLIENT: view term sheets on their scenarios (read-only) ---

@api.get("/client/scenarios/{sid}/term-sheets")
async def client_list_term_sheets(sid: str, user=Depends(require_client)):
    scen = await db.scenarios.find_one({"id": sid, "client_id": user["id"]},
                                       {"_id": 0, "id": 1})
    if not scen:
        raise HTTPException(status_code=403, detail="Not your scenario")
    sheets = await db.term_sheets.find(
        {"scenario_id": sid, "status": {"$ne": "withdrawn"}}, {"_id": 0}
    ).sort("submitted_at", -1).to_list(200)
    await _hydrate_ts_docs(sheets)
    return sheets




# ================ Scenario AI Assistant (Claude Sonnet 4.5) ================
AI_MODES = Literal["interview", "parse", "analyst"]


class AIChatRequest(BaseModel):
    mode: AI_MODES = "interview"
    message: str = Field(min_length=1, max_length=20000)


class AIChatResetRequest(BaseModel):
    keep_intro: bool = False


def _make_scenario_ai_chat(session_id: str, system_message: str) -> LlmChat:
    """Same model as AdsCopilot for consistency; Emergent Universal Key."""
    return (
        LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id, system_message=system_message)
        .with_model("anthropic", "claude-sonnet-4-5-20250929")
    )


def _lender_summary_for_ai(l: dict) -> dict:
    """Compact lender record so we don't blow the context window."""
    return {
        "name": l.get("name"),
        "type": l.get("institution_type"),
        "property_types": l.get("property_types") or [],
        "property_subtypes": l.get("property_subtypes") or [],
        "min_loan": l.get("min_loan"),
        "max_loan": l.get("max_loan"),
        "max_ltv": l.get("max_ltv"),
        "min_dscr": l.get("min_dscr"),
        "geography": l.get("geography") or [],
        "rate_range": [l.get("rate_min"), l.get("rate_max")],
        "recourse": l.get("recourse_preference"),
        "status": l.get("status"),
    }


def _scenario_snapshot(scen: dict, metrics: dict) -> dict:
    """Scoped view of the scenario that the model can safely read + reason over."""
    return {
        "name": scen.get("name"),
        "status": scen.get("status"),
        "sponsor": scen.get("sponsor"),
        "property_info": scen.get("property_info"),
        "loan_request": scen.get("loan_request"),
        "financials": scen.get("financials"),
        "construction": scen.get("construction"),
        "sources_uses": scen.get("sources_uses"),
        "notes": scen.get("notes"),
        "business_plan": scen.get("business_plan"),
        "metrics": metrics,
    }


AI_SYSTEM_PROMPT = """You are Byrd & CO's commercial real estate Deal Engine assistant.
You help Wayne and Caleb Byrd (commercial mortgage brokers) build, review, and shop loan scenarios.

You always operate on ONE scenario at a time. The current scenario JSON and the broker's lender directory
are provided to you at the start of every turn. Use them faithfully — never invent lender names or numbers.

# Modes
- **interview**: Ask ONE focused question at a time to gather missing scenario fields. Keep questions
  short and specific to CRE debt. Never ask for personal SSN, DOB, or non-relevant PII.
- **parse**: The user pasted an offering memo, term sheet, email, or notes. Extract structured fields.
  Be conservative — don't guess. Leave fields null if uncertain.
- **analyst**: The scenario is mostly complete. Review it. Flag issues (DSCR < 1.20, LTV over lender
  caps, missing NOI, wrong recourse defaults). Recommend concrete fixes and which lenders in the
  directory fit best.

# CRE domain rules
- DSCR below 1.20 is risky, below 1.00 is un-financeable for permanent debt.
- Debt yield below 8% is aggressive for perm debt.
- Multifamily = "multifamily". Class B office is common. Retail can be single-tenant or multi-tenant.
- Loan types: acquisition, refinance, construction, bridge, permanent, cash-out-refi.
- Amortization is usually 300 or 360 months. Term 60/84/120 months typical.
- Recourse options: recourse, non-recourse, partial.

# Response format
Write your reply in natural, warm broker-professional English. Then, if and only if you want to
propose changes or lender picks, append fenced blocks at the very END of your message.

Use these exact block markers:

```updates
{ ...JSON object with scenario field updates... }
```

```lenders
[ {"name":"Frost Bank","reason":"in-market, DSCR fits, size range OK"}, ... ]
```

Rules for the ```updates``` block:
- Only include fields you're proposing to change or set.
- Use the exact nested shape of the scenario:
  { "name": "...", "sponsor": {...}, "property_info": {...}, "loan_request": {...},
    "financials": {...}, "notes": "...", "business_plan": "..." }
- Never emit metrics — those are computed server-side.
- Numbers must be numbers (not strings). Percentages are numbers like 6.5 (meaning 6.5%).

Rules for the ```lenders``` block:
- Only include names that appear verbatim in the provided lender directory.
- Keep 1–5 recommendations, best fit first.
- Each entry: { "name": "exact directory name", "reason": "one short sentence" }.

Do NOT include either block if you have no changes/picks. Keep normal chat clean — no code fences
unless you're using them for updates/lenders.
"""


def _build_turn_context(scen: dict, metrics: dict, lenders: List[dict], mode: str) -> str:
    """Injected before the user's own message so the model always sees fresh state."""
    lender_slim = [_lender_summary_for_ai(l) for l in lenders if l.get("status") != "dormant"]
    payload = {
        "mode": mode,
        "current_scenario": _scenario_snapshot(scen, metrics),
        "lender_directory": lender_slim,
    }
    return (
        "Here is the current scenario state and lender directory (READ ONLY — do not echo this back):\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```\n\n"
        "Now respond to the broker."
    )


def _extract_fenced_block(text: str, marker: str) -> Optional[str]:
    """Find ```<marker>\n...\n``` in text and return the inner payload, or None."""
    needle = f"```{marker}"
    start = text.find(needle)
    if start < 0:
        return None
    body_start = text.find("\n", start)
    if body_start < 0:
        return None
    end = text.find("```", body_start + 1)
    if end < 0:
        return None
    return text[body_start + 1:end].strip()


def _split_ai_response(full_text: str) -> dict:
    """Parse Claude's response into (chat_text, updates, lender_recs)."""
    updates_raw = _extract_fenced_block(full_text, "updates")
    lenders_raw = _extract_fenced_block(full_text, "lenders")

    updates = None
    if updates_raw:
        try:
            parsed = json.loads(updates_raw)
            if isinstance(parsed, dict) and parsed:
                updates = parsed
        except Exception:
            pass

    lender_recs = None
    if lenders_raw:
        try:
            parsed = json.loads(lenders_raw)
            if isinstance(parsed, list):
                lender_recs = [
                    {"name": x.get("name"), "reason": x.get("reason", "")}
                    for x in parsed if isinstance(x, dict) and x.get("name")
                ][:5]
        except Exception:
            pass

    # Strip the fenced blocks from the visible chat text
    chat_text = full_text
    for marker in ("updates", "lenders"):
        needle = f"```{marker}"
        idx = chat_text.find(needle)
        if idx >= 0:
            end = chat_text.find("```", idx + len(needle))
            if end >= 0:
                chat_text = chat_text[:idx] + chat_text[end + 3:]
    return {"text": chat_text.strip(), "updates": updates, "lender_recs": lender_recs}


@api.post("/admin/scenarios/{sid}/ai/chat")
async def scenario_ai_chat(sid: str, body: AIChatRequest, admin=Depends(require_admin)):
    """SSE streaming chat with Claude, aware of scenario + lender directory."""
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    metrics = compute_scenario_metrics(scen)
    lenders = await db.lenders.find({}, {"_id": 0}).to_list(500)

    # Session is one per (scenario, admin). Persistent history in DB is used only to
    # rehydrate chat history on the client; LlmChat itself gets a fresh instance per call
    # but we still hand it prior messages by writing them in as we go (the library keeps
    # its own per-session store keyed by session_id, which lives inside the module).
    session_id = f"scenario-ai::{sid}::{admin['id']}"
    system_message = AI_SYSTEM_PROMPT
    chat = _make_scenario_ai_chat(session_id, system_message)

    turn_context = _build_turn_context(scen, metrics, lenders, body.mode)
    user_text = f"{turn_context}\n\nBroker message ({body.mode} mode):\n{body.message}"

    async def event_gen():
        buf: List[str] = []
        # Persist the user's own message first (without the injected context)
        user_msg_id = str(uuid.uuid4())
        await db.scenario_ai_messages.insert_one({
            "id": user_msg_id,
            "scenario_id": sid,
            "admin_id": admin["id"],
            "role": "user",
            "mode": body.mode,
            "content": body.message,
            "created_at": now_iso(),
        })
        try:
            async for ev in chat.stream_message(UserMessage(text=user_text)):
                if isinstance(ev, TextDelta):
                    buf.append(ev.content)
                    payload = json.dumps({"type": "token", "content": ev.content})
                    yield f"data: {payload}\n\n"
                elif isinstance(ev, StreamDone):
                    break
        except Exception as e:
            err = json.dumps({"type": "error", "message": str(e)[:400]})
            yield f"data: {err}\n\n"
            return

        full_text = "".join(buf)
        parsed = _split_ai_response(full_text)

        # Persist the assistant reply
        assistant_msg_id = str(uuid.uuid4())
        await db.scenario_ai_messages.insert_one({
            "id": assistant_msg_id,
            "scenario_id": sid,
            "admin_id": admin["id"],
            "role": "assistant",
            "mode": body.mode,
            "content": parsed["text"],
            "updates": parsed["updates"],
            "lender_recs": parsed["lender_recs"],
            "created_at": now_iso(),
        })

        done = json.dumps({
            "type": "done",
            "message_id": assistant_msg_id,
            "text": parsed["text"],
            "updates": parsed["updates"],
            "lender_recs": parsed["lender_recs"],
        })
        yield f"data: {done}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/admin/scenarios/{sid}/ai/messages")
async def scenario_ai_messages(sid: str, admin=Depends(require_admin)):
    """Return the persisted AI chat history for this scenario + admin."""
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0, "id": 1})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    msgs = await db.scenario_ai_messages.find(
        {"scenario_id": sid, "admin_id": admin["id"]},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    return msgs


@api.post("/admin/scenarios/{sid}/ai/reset")
async def scenario_ai_reset(sid: str, admin=Depends(require_admin)):
    """Clear chat history for this scenario + admin so the assistant starts fresh."""
    await db.scenario_ai_messages.delete_many({"scenario_id": sid, "admin_id": admin["id"]})
    return {"ok": True}



# ================ Personal Assistant (per-admin Claude bot + tasks + email drafts) ================
class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class AssistantTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    notes: Optional[str] = ""
    due_date: Optional[str] = None  # ISO date string YYYY-MM-DD
    related_client_id: Optional[str] = None
    related_name: Optional[str] = ""


class AssistantTaskUpdate(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[Literal["open", "done", "dismissed"]] = None


class AssistantEmailSend(BaseModel):
    to: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    related_task_id: Optional[str] = None


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def _crm_snapshot_for_assistant() -> dict:
    """Compact CRM state for the personal assistant prompt.
    Returns totals, tag counts, unsubscribed count, days_since_last_marketing,
    and up to 15 stale contacts (never contacted OR contacted >60d ago, must have email,
    must not be unsubscribed).
    """
    now = datetime.now(timezone.utc)
    suppressed = {u["email"].lower() async for u in db.contact_unsubscribes.find({}, {"email": 1}) if u.get("email")}
    contacts = await db.contacts.find({}, {"_id": 0}).to_list(5000)
    total = len(contacts)
    unsub_count = 0
    tag_counts: dict[str, int] = {}
    stale: list[dict] = []
    for c in contacts:
        em = (c.get("email") or "").lower()
        is_unsub = bool(em and em in suppressed)
        if is_unsub:
            unsub_count += 1
        for t in c.get("tags") or []:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        if not em or is_unsub:
            continue
        lca = c.get("last_contact_at")
        days_since: Optional[int] = None
        if lca:
            try:
                dt = datetime.fromisoformat(lca.replace("Z", "+00:00")) if isinstance(lca, str) else lca
                days_since = (now - dt).days
            except Exception:
                days_since = None
        if days_since is None or days_since >= 60:
            stale.append({
                "name": c.get("name"),
                "email": c.get("email"),
                "tags": c.get("tags") or [],
                "days_since_contact": days_since,  # None = never
                "last_contact_channel": c.get("last_contact_channel"),
            })
    # Sort: never-contacted first, then oldest first
    stale.sort(key=lambda x: (-1 if x["days_since_contact"] is None else -x["days_since_contact"]), reverse=True)
    stale = stale[:15]

    # Last marketing send (global — shared rolodex)
    last_mkt = await db.assistant_emails.find_one(
        {"tag": "marketing", "status": "sent"}, {"_id": 0}, sort=[("sent_at", -1)]
    )
    days_since_last: Optional[int] = None
    last_mkt_summary: Optional[dict] = None
    if last_mkt:
        try:
            dt = datetime.fromisoformat(last_mkt["sent_at"].replace("Z", "+00:00"))
            days_since_last = (now - dt).days
        except Exception:
            pass
        last_mkt_summary = {
            "subject": last_mkt.get("subject"),
            "sent_at": last_mkt.get("sent_at"),
            "days_ago": days_since_last,
        }

    return {
        "contacts_stats": {
            "total": total,
            "unsubscribed": unsub_count,
            "tag_counts": tag_counts,
            "days_since_last_marketing": days_since_last,  # None = never
            "last_marketing": last_mkt_summary,
        },
        "stale_contacts": stale,
        # Compact index Claude uses to dedupe when the broker mentions a new person.
        # Cap at 200 rows; contacts_stats.total tells Claude if there are more.
        "contacts_index": [
            {"id": c.get("id"),
             "name": c.get("name"),
             "email": (c.get("email") or "").lower() or None,
             "tags": c.get("tags") or []}
            for c in contacts[:200] if c.get("name")
        ],
    }


STALLED_STATUSES = ("draft", "shopping")
STALLED_DAYS_THRESHOLD = 7
STALLED_DOC_PCT_THRESHOLD = 30  # <30% uploaded
STALLED_SNOOZE_DAYS = 7


def _iso_days_ago(iso: Optional[str], now: datetime) -> Optional[int]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")) if isinstance(iso, str) else iso
        return (now - dt).days
    except Exception:
        return None


async def _stalled_scenarios_for_admin(admin_id: str) -> list[dict]:
    """Return scenarios that look silently stuck for THIS admin's dashboard.
    Criteria (all must hold):
      - status in draft/shopping
      - last activity (max of scenario.updated_at and latest doc.updated_at) is >= 7 days ago
      - upload pct < 30% (0 counts as 0% — never uploaded)
      - not snoozed by this admin
    Sorted by days_since_activity descending (most stuck first)."""
    now = datetime.now(timezone.utc)
    scens = await db.scenarios.find(
        {"status": {"$in": list(STALLED_STATUSES)}},
        {"_id": 0, "id": 1, "name": 1, "status": 1, "client_id": 1, "loan_request": 1, "updated_at": 1},
    ).to_list(500)
    if not scens:
        return []
    scen_ids = [s["id"] for s in scens]

    # Roll up doc counts per scenario in one pass
    doc_stats: dict[str, dict] = {sid: {"total": 0, "uploaded": 0, "last_activity": None} for sid in scen_ids}
    async for d in db.client_docs.find(
        {"scenario_id": {"$in": scen_ids}},
        {"_id": 0, "scenario_id": 1, "status": 1, "updated_at": 1},
    ):
        b = doc_stats[d["scenario_id"]]
        b["total"] += 1
        if d.get("status") in ("uploaded", "reviewed"):
            b["uploaded"] += 1
        ua = d.get("updated_at")
        if ua and (b["last_activity"] is None or ua > b["last_activity"]):
            b["last_activity"] = ua

    # Load client names for enrichment
    client_ids = list({s.get("client_id") for s in scens if s.get("client_id")})
    clients_by_id: dict[str, dict] = {}
    if client_ids:
        async for u in db.users.find({"id": {"$in": client_ids}}, {"_id": 0, "id": 1, "name": 1, "email": 1}):
            clients_by_id[u["id"]] = u

    # Per-admin snoozes
    snooze_map: dict[str, str] = {}
    async for sd in db.scenario_snoozes.find({"admin_id": admin_id}, {"_id": 0, "scenario_id": 1, "snoozed_until": 1}):
        snooze_map[sd["scenario_id"]] = sd.get("snoozed_until", "")

    stalled: list[dict] = []
    for s in scens:
        # Effective last activity = max(scenario.updated_at, latest doc.updated_at)
        d_stats = doc_stats.get(s["id"], {"total": 0, "uploaded": 0, "last_activity": None})
        last_scen = s.get("updated_at")
        last_doc = d_stats["last_activity"]
        candidates = [x for x in [last_scen, last_doc] if x]
        latest = max(candidates) if candidates else None
        days_since = _iso_days_ago(latest, now)
        if days_since is None or days_since < STALLED_DAYS_THRESHOLD:
            continue
        total = d_stats["total"]
        uploaded = d_stats["uploaded"]
        pct = int(round((uploaded / total) * 100)) if total else 0
        if pct >= STALLED_DOC_PCT_THRESHOLD:
            continue
        # Honor snooze
        snoozed_until = snooze_map.get(s["id"])
        if snoozed_until:
            days_left = _iso_days_ago(snoozed_until, now)
            if days_left is not None and days_left < 0:
                # snoozed_until is in the future → skip
                continue
        client = clients_by_id.get(s.get("client_id") or "") if s.get("client_id") else None
        stalled.append({
            "scenario_id": s["id"],
            "scenario_name": s.get("name") or "Untitled",
            "status": s.get("status"),
            "loan_type": (s.get("loan_request") or {}).get("loan_type"),
            "client_id": s.get("client_id"),
            "client_name": (client or {}).get("name"),
            "client_email": (client or {}).get("email"),
            "days_since_activity": days_since,
            "doc_total": total,
            "doc_uploaded": uploaded,
            "doc_pct": pct,
        })
    stalled.sort(key=lambda x: x["days_since_activity"], reverse=True)
    return stalled


ASSISTANT_SYSTEM_PROMPT = """You are **Ada**, the personal assistant to a commercial real estate broker at Byrd & CO.
Your name is Ada. When the broker asks "what's your name?" or "who are you?", you say you're Ada —
their personal assistant at Byrd & CO. You are warm, concise, and proactive. You address the broker
by first name.

(Note: You are the SAME Ada who also assists Byrd & CO borrowers inside their client portal. The
broker knows this. Just refer to yourself as "Ada" — you don't need to explain the two-hat setup
unless asked.)

At the top of every turn you receive:
- The broker's identity (name, email)
- Today's date + local weekday
- The broker's CURRENT open task list (with due dates and any linked client)
- The broker's client roster (name + email, for quick recognition)
- The broker's teammates (other admins on the account) — you can hand tasks off to them by name
- A snapshot of the shared **Contacts CRM** (rolodex): total, tag breakdown, unsubscribed count,
  and up to 15 STALE contacts (haven't been contacted in 60+ days, with valid emails). You also
  see when the last marketing email went out (days_since_last_marketing).
- A list of **STALLED SCENARIOS** — active deals (draft/shopping) that haven't moved in 7+ days
  AND have less than 30% docs uploaded. This is where deals silently die.

# What you do
1. Have a natural conversation. Keep responses short and friendly.
2. Extract commitments the broker makes and turn them into structured tasks.
3. If a due date is mentioned (e.g. "check with me on July 21st", "next Tuesday"), compute the
   real ISO date given today's date and put it on the task.
4. If the broker mentions a person who is NOT in the client roster, offer to add them as a client
   (name only — never fabricate emails or phone numbers).
5. If the broker asks you to email someone, DRAFT the email in the structured block below —
   do not send it. The user will review and send.
6. If the broker asks you to "tell", "let ... know", "hand off to", or otherwise route work to a
   TEAMMATE (e.g. "tell Caleb here's Rod's number, call him and interview him"), OR if the message
   STARTS with `@<teammate_first_name>` (e.g. "@caleb call Rod at 555-1234"), use the `handoffs`
   block. The message will show up in that teammate's private assistant as a task from the current
   broker — with the full context they need. For @-mention shortcuts, strip the "@name " prefix
   when writing the handoff title/note; the recipient will see who it's from automatically.
7. When the broker tells you something is done, mark the matching open task complete.
8. Never expose task IDs in visible chat — only in the structured blocks.
9. **Marketing awareness.** Look at `days_since_last_marketing` in the CRM snapshot. If it's been
   30+ days (or `null` = never sent), gently mention that in your reply the FIRST time you notice it
   in a conversation, and offer to draft a marketing email. Do NOT nag repeatedly.
10. **Answer CRM questions from the snapshot.** If the broker asks "who haven't I contacted in 60
    days?" or "who's overdue for outreach?" — use the `stale_contacts` list. If they ask about
    someone by name and they're in `stale_contacts` or `contacts_stats.tag_counts`, use that.
11. **Drafting a marketing email.** If the broker asks you to draft a marketing/newsletter/blast
    email (or accepts your offer to draft one), emit a `marketing_suggestion` block — NOT an
    `email_draft`. Marketing sends go through the Contacts CRM (which handles unsubscribe footers
    and bulk sending); the broker will review and send from there. Pick a `target_tags` filter
    when it fits (e.g. `["referral"]` or `["past sponsor"]`); use `[]` to target everyone with
    a valid email.
12. **Pipeline coaching (stalled deals).** Look at `stalled_scenarios`. If any exist, the FIRST time
    in a conversation, mention them in ONE gentle line — pick the top 1-2 by days_since_activity
    (e.g. "Also — Rod's MF Refi hasn't moved in 12 days and only 2/17 docs are up. Want me to draft
    a follow-up to him?"). Do NOT list all of them. Do NOT repeat the reminder every turn.
    If the broker says yes to a follow-up, DRAFT an `email_draft` addressed to `client_email` with
    a warm, one-paragraph nudge — not pushy — asking if they need help getting the remaining docs
    uploaded. If the broker says "snooze it" or "not now", acknowledge without emitting any block
    (the UI has a snooze button for that).
13. **Adding NEW contacts to the CRM.** Whenever the broker mentions a NEW person you haven't seen before
    in the current `contacts_index` OR `clients` roster — a referral source, a lender rep, a
    prospective borrower, someone they met — automatically emit a `new_contacts` block. Also emit
    one when the broker explicitly asks you to add contacts ("add John, Sarah and Mike from
    Marcus & Millichap"). If the broker says "add my existing clients Rod, Jose, and Breona to the
    CRM", pull their name+email straight from the `clients` roster and emit `new_contacts` with them
    — you don't need to ask the broker to re-supply details. Rules:
    - Match on `name` (case-insensitive) OR `email`. If either matches an existing entry in
      `contacts_index`, DO NOT re-add — say "already in the CRM" instead.
    - Always include `name`. Include `email` and `phone` only if the broker gave them or they're
      obviously derivable (e.g. from the `clients` roster) — never fabricate.
    - Pick sensible `tags` from what's already in `contacts_stats.tag_counts` when they fit
      (e.g. `["referral"]`, `["lender"]`, `["past sponsor"]`). If the broker says the person is a
      "borrower", "client", "referral", etc., use that as a tag. Otherwise leave `tags` empty.
    - `notes` field: short context ("Met at MBA conference Feb 2026", "Refi lead from Rod").
    - Confirm in your visible chat what was added ("Added Sarah Chen and Mike Torres to the CRM").
14. **UPDATING existing contacts (tags, notes).** To add tags to a contact that is ALREADY in
    `contacts_index`, or to update their notes, emit a `contact_updates` block. Reference the
    contact by their `id` from `contacts_index` (preferred) or by exact `name`/`email` match.
    `add_tags` is additive — existing tags are preserved. Use `set_tags` if the broker asks to
    REPLACE the tag set entirely. `set_notes` overwrites notes; `append_notes` appends with a
    newline. Rules:
    - NEVER emit `contact_updates` for a person who is not in `contacts_index`. If they're only in
      `clients`, add them to the CRM first via `new_contacts`.
    - If the broker says something like "tag Rod, Jose, and Breona as borrower", first check each
      is in `contacts_index`. For any that ARE in the index, emit a `contact_updates` entry. For any
      that are NOT, emit `new_contacts` for them (with the tag set) in the SAME response. Explain
      both in your chat reply.
    - Confirm in visible chat what was tagged/updated.

# Response format
Write your natural-language reply first. Then, ONLY IF you have structured actions to take,
append fenced blocks at the end of your message:

```new_tasks
[
  {
    "title": "Start purchase loan process for Rod Literral — home in Tennessee",
    "notes": "optional detail",
    "due_date": "2026-07-21",
    "related_name": "Rod Literral"
  }
]
```

```complete_tasks
["<task_id_from_open_tasks_list>"]
```

```email_draft
{
  "to": "rod@example.com",
  "subject": "Follow-up on document request",
  "body": "Hi Rod,\\n\\nJust checking in to see..."
}
```

```suggest_client
{"name": "Rod Literral", "hint": "purchase loan Tennessee"}
```

```handoffs
[
  {
    "to_name": "Caleb",
    "title": "Call Rod Literral and interview him for the Ohio mixed-use loan",
    "note": "Wayne wanted me to give you Rod's number: 555-123-4567. He requested that you call him and interview him for the mixed-use property loan in Ohio.",
    "related_name": "Rod Literral",
    "due_date": "2026-07-22"
  }
]
```

```marketing_suggestion
{
  "subject": "Q1 rate snapshot — a quick note",
  "body": "Hi {{first_name}},\\n\\nQuick update on the commercial debt market...\\n\\nBest,\\n{{admin_first_name}}",
  "target_tags": ["referral"],
  "rationale": "It's been 34 days since the last send; referral sources typically expect a quarterly rate note."
}
```

```new_contacts
[
  {
    "name": "Sarah Chen",
    "email": "sarah@wellsfargo.com",
    "phone": "555-123-4567",
    "tags": ["lender"],
    "notes": "Wells Fargo commercial banker — hotel and multifamily focus."
  }
]
```

```contact_updates
[
  {
    "id": "<contact id from contacts_index>",
    "add_tags": ["borrower"],
    "set_tags": null,
    "append_notes": null,
    "set_notes": null
  }
]
```

Rules:
- Only include blocks you're actually proposing. Never emit empty ones.
- **CRITICAL — NO CONFABULATION.** NEVER claim you added, tagged, updated, sent, emailed, completed,
  handed off, or created anything unless you emit the corresponding fenced block in the SAME reply.
  If you write "Done — I tagged Rod as borrower" or "Perfect, I've added them", you MUST emit the
  matching `contact_updates` / `new_contacts` block. If you cannot emit the block (e.g. the contact
  isn't in `contacts_index`), tell the broker what's blocking you instead — do NOT pretend the
  action happened. This applies to every block: `new_tasks`, `complete_tasks`, `email_draft`,
  `handoffs`, `new_contacts`, `contact_updates`, `marketing_suggestion`.
- Never emit `complete_tasks` unless you're matching a task from the "OPEN TASKS" list.
- Never emit `email_draft` unless the broker asked you to email someone.
- Never emit `email_draft` for a MARKETING/BLAST email — use `marketing_suggestion` instead.
- `handoffs.to_name` MUST match a first name from the teammates list exactly.
- `handoffs.note` should be a complete, self-contained message the teammate can read cold —
   include phone numbers, addresses, deal specifics the broker mentioned.
- Dates in `due_date` MUST be ISO format YYYY-MM-DD.
- `marketing_suggestion.body` MUST include the `{{first_name}}` merge tag at least once and sign
   off with `{{admin_first_name}}` — the CRM will personalize per recipient.
- `marketing_suggestion.target_tags` — use tags that actually appear in the CRM `tag_counts`.
   Use `[]` to target the whole rolodex (any contact with a valid email).
- Keep quotes/apostrophes safe in JSON (escape with \\").
"""


def _assistant_turn_context(admin: dict, open_tasks: List[dict], clients: List[dict], teammates: List[dict], crm: dict, stalled: List[dict]) -> str:
    today = datetime.now(timezone.utc)
    slim_tasks = [
        {
            "id": t["id"],
            "title": t["title"],
            "due_date": t.get("due_date"),
            "notes": t.get("notes", ""),
            "related_name": t.get("related_name") or "",
            "from_teammate": t.get("assigned_by_name") or "",
        }
        for t in open_tasks
    ]
    slim_clients = [
        {"id": c["id"], "name": c.get("name"), "email": c.get("email"), "company": c.get("company")}
        for c in clients
    ]
    slim_teammates = [
        {"first_name": (t.get("name") or t.get("email", "").split("@")[0]).split(" ")[0], "full_name": t.get("name"), "email": t.get("email")}
        for t in teammates
    ]
    payload = {
        "broker": {
            "id": admin["id"],
            "name": admin.get("name") or admin.get("email", "").split("@")[0],
            "email": admin.get("email"),
        },
        "today": today.date().isoformat(),
        "weekday": today.strftime("%A"),
        "utc_now": today.isoformat(),
        "open_tasks": slim_tasks,
        "clients": slim_clients,
        "teammates": slim_teammates,
        "contacts_stats": crm.get("contacts_stats", {}),
        "stale_contacts": crm.get("stale_contacts", []),
        "contacts_index": crm.get("contacts_index", []),
        "stalled_scenarios": stalled[:8],  # cap to keep prompt lean
    }
    return (
        "Here is the current state (READ ONLY — do not echo this back):\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```\n\n"
        "Now respond to the broker."
    )


def _split_assistant_response(full_text: str) -> dict:
    """Parse Claude's response into visible chat_text plus structured actions."""
    def _grab(marker: str):
        needle = f"```{marker}"
        start = full_text.find(needle)
        if start < 0:
            return None
        body_start = full_text.find("\n", start)
        if body_start < 0:
            return None
        end = full_text.find("```", body_start + 1)
        if end < 0:
            return None
        return full_text[body_start + 1:end].strip()

    raw_new = _grab("new_tasks")
    raw_done = _grab("complete_tasks")
    raw_email = _grab("email_draft")
    raw_client = _grab("suggest_client")
    raw_handoffs = _grab("handoffs")
    raw_marketing = _grab("marketing_suggestion")
    raw_contacts = _grab("new_contacts")
    raw_contact_updates = _grab("contact_updates")

    new_tasks = None
    if raw_new:
        try:
            parsed = json.loads(raw_new)
            if isinstance(parsed, list):
                new_tasks = [
                    {
                        "title": (x.get("title") or "").strip(),
                        "notes": x.get("notes") or "",
                        "due_date": x.get("due_date"),
                        "related_name": x.get("related_name") or "",
                    }
                    for x in parsed if isinstance(x, dict) and x.get("title")
                ]
                if not new_tasks:
                    new_tasks = None
        except Exception:
            pass

    complete_tasks = None
    if raw_done:
        try:
            parsed = json.loads(raw_done)
            if isinstance(parsed, list):
                complete_tasks = [str(x) for x in parsed if x]
                if not complete_tasks:
                    complete_tasks = None
        except Exception:
            pass

    email_draft = None
    if raw_email:
        try:
            parsed = json.loads(raw_email)
            if isinstance(parsed, dict) and parsed.get("to") and parsed.get("subject") and parsed.get("body"):
                email_draft = {
                    "to": parsed["to"],
                    "subject": parsed["subject"],
                    "body": parsed["body"],
                }
        except Exception:
            pass

    suggest_client = None
    if raw_client:
        try:
            parsed = json.loads(raw_client)
            if isinstance(parsed, dict) and parsed.get("name"):
                suggest_client = {
                    "name": parsed["name"],
                    "hint": parsed.get("hint", ""),
                }
        except Exception:
            pass

    handoffs = None
    if raw_handoffs:
        try:
            parsed = json.loads(raw_handoffs)
            if isinstance(parsed, list):
                handoffs = [
                    {
                        "to_name": (x.get("to_name") or "").strip(),
                        "title": (x.get("title") or "").strip(),
                        "note": (x.get("note") or "").strip(),
                        "related_name": x.get("related_name") or "",
                        "due_date": x.get("due_date"),
                    }
                    for x in parsed if isinstance(x, dict) and x.get("to_name") and x.get("title")
                ]
                if not handoffs:
                    handoffs = None
        except Exception:
            pass

    marketing_suggestion = None
    if raw_marketing:
        try:
            parsed = json.loads(raw_marketing)
            if isinstance(parsed, dict) and parsed.get("subject") and parsed.get("body"):
                tt = parsed.get("target_tags") or []
                if not isinstance(tt, list):
                    tt = []
                marketing_suggestion = {
                    "subject": str(parsed["subject"])[:200],
                    "body": str(parsed["body"])[:20000],
                    "target_tags": [str(t) for t in tt if str(t).strip()],
                    "rationale": (parsed.get("rationale") or "")[:800],
                }
        except Exception:
            pass

    new_contacts = None
    if raw_contacts:
        try:
            parsed = json.loads(raw_contacts)
            if isinstance(parsed, list):
                new_contacts = []
                for x in parsed:
                    if not isinstance(x, dict) or not (x.get("name") or "").strip():
                        continue
                    tags = x.get("tags") or []
                    if not isinstance(tags, list):
                        tags = []
                    new_contacts.append({
                        "name": str(x["name"]).strip()[:200],
                        "email": (str(x.get("email") or "").strip().lower() or None),
                        "phone": (str(x.get("phone") or "").strip() or ""),
                        "tags": [str(t).strip() for t in tags if str(t).strip()][:8],
                        "notes": (str(x.get("notes") or "").strip())[:1000],
                    })
                if not new_contacts:
                    new_contacts = None
        except Exception:
            pass

    contact_updates = None
    if raw_contact_updates:
        try:
            parsed = json.loads(raw_contact_updates)
            if isinstance(parsed, list):
                contact_updates = []
                for x in parsed:
                    if not isinstance(x, dict):
                        continue
                    # Need at least one identifier
                    ident_id = (x.get("id") or "").strip()
                    ident_name = (x.get("name") or "").strip()
                    ident_email = (x.get("email") or "").strip().lower()
                    if not (ident_id or ident_name or ident_email):
                        continue
                    add_tags = x.get("add_tags") or []
                    set_tags = x.get("set_tags")
                    if not isinstance(add_tags, list):
                        add_tags = []
                    if set_tags is not None and not isinstance(set_tags, list):
                        set_tags = None
                    contact_updates.append({
                        "id": ident_id or None,
                        "name": ident_name or None,
                        "email": ident_email or None,
                        "add_tags": [str(t).strip() for t in add_tags if str(t).strip()][:16],
                        "set_tags": ([str(t).strip() for t in set_tags if str(t).strip()][:16]
                                    if isinstance(set_tags, list) else None),
                        "append_notes": (str(x.get("append_notes") or "").strip() or None),
                        "set_notes": (str(x.get("set_notes") or "").strip() or None),
                    })
                if not contact_updates:
                    contact_updates = None
        except Exception:
            pass

    chat_text = full_text
    for marker in ("new_tasks", "complete_tasks", "email_draft", "suggest_client", "handoffs", "marketing_suggestion", "new_contacts", "contact_updates"):
        needle = f"```{marker}"
        idx = chat_text.find(needle)
        if idx >= 0:
            end = chat_text.find("```", idx + len(needle))
            if end >= 0:
                chat_text = chat_text[:idx] + chat_text[end + 3:]
    return {
        "text": chat_text.strip(),
        "new_tasks": new_tasks,
        "complete_tasks": complete_tasks,
        "email_draft": email_draft,
        "suggest_client": suggest_client,
        "handoffs": handoffs,
        "marketing_suggestion": marketing_suggestion,
        "new_contacts": new_contacts,
        "contact_updates": contact_updates,
    }


async def _apply_assistant_actions(admin: dict, parsed: dict) -> dict:
    """Persist any tasks Claude proposed / completed / handed off. Returns the applied deltas."""
    admin_id = admin["id"]
    applied_new = []
    if parsed.get("new_tasks"):
        for t in parsed["new_tasks"]:
            tid = str(uuid.uuid4())
            doc = {
                "id": tid,
                "admin_id": admin_id,
                "title": t["title"],
                "notes": t.get("notes", ""),
                "due_date": t.get("due_date"),
                "related_name": t.get("related_name", ""),
                "related_client_id": None,
                "status": "open",
                "source": "assistant",
                "assigned_by_admin_id": None,
                "assigned_by_name": "",
                "handoff_note": "",
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "completed_at": None,
            }
            await db.assistant_tasks.insert_one(doc)
            doc.pop("_id", None)
            applied_new.append(doc)

    applied_complete = []
    if parsed.get("complete_tasks"):
        for tid in parsed["complete_tasks"]:
            res = await db.assistant_tasks.update_one(
                {"id": tid, "admin_id": admin_id, "status": "open"},
                {"$set": {"status": "done", "completed_at": now_iso(), "updated_at": now_iso()}},
            )
            if res.modified_count:
                applied_complete.append(tid)

    applied_handoffs = []
    if parsed.get("handoffs"):
        # Match teammate by first-name (case-insensitive) among other admins
        others = await db.users.find(
            {"role": "admin", "id": {"$ne": admin_id}},
            {"_id": 0, "id": 1, "name": 1, "email": 1},
        ).to_list(50)
        by_first = {(u.get("name") or "").split(" ")[0].lower(): u for u in others if u.get("name")}
        from_name = admin.get("name") or admin.get("email", "").split("@")[0]
        for h in parsed["handoffs"]:
            teammate = by_first.get((h.get("to_name") or "").strip().lower())
            if not teammate:
                # Skip silently — Claude was told to only use valid names
                continue
            tid = str(uuid.uuid4())
            doc = {
                "id": tid,
                "admin_id": teammate["id"],  # target owns the task
                "title": h["title"],
                "notes": "",
                "due_date": h.get("due_date"),
                "related_name": h.get("related_name", ""),
                "related_client_id": None,
                "status": "open",
                "source": "handoff",
                "assigned_by_admin_id": admin_id,
                "assigned_by_name": from_name,
                "handoff_note": h.get("note", ""),
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "completed_at": None,
            }
            await db.assistant_tasks.insert_one(doc)
            doc.pop("_id", None)
            applied_handoffs.append({
                "task_id": tid,
                "to_admin_id": teammate["id"],
                "to_name": teammate.get("name") or h["to_name"],
                "title": h["title"],
                "note": h.get("note", ""),
                "due_date": h.get("due_date"),
            })

    return {"created": applied_new, "completed": applied_complete, "handoffs": applied_handoffs, "marketing_suggestion": None, "new_contacts": []}


async def _apply_contact_updates(parsed_updates: list[dict], admin_id: str) -> list[dict]:
    """Apply tag / note updates to existing contacts. Returns list of {contact_id, name, tags,
    added_tags, notes_updated} for each contact actually updated. Skips silently if the contact
    can't be resolved."""
    if not parsed_updates:
        return []
    now = now_iso()
    updated: list[dict] = []
    for u in parsed_updates:
        # Resolve contact by id > email > name (case-insensitive)
        query = None
        if u.get("id"):
            query = {"id": u["id"]}
        elif u.get("email"):
            query = {"email": u["email"]}
        elif u.get("name"):
            query = {"name": {"$regex": f"^{re.escape(u['name'])}$", "$options": "i"}}
        if not query:
            continue
        contact = await db.contacts.find_one(query, {"_id": 0})
        if not contact:
            continue
        # Compute new tags
        current_tags = list(contact.get("tags") or [])
        added: list[str] = []
        if u.get("set_tags") is not None:
            new_tags = [t for t in u["set_tags"] if t]
        else:
            new_tags = current_tags[:]
            for t in (u.get("add_tags") or []):
                if t and t not in new_tags:
                    new_tags.append(t)
                    added.append(t)
        # Compute new notes
        current_notes = contact.get("notes") or ""
        if u.get("set_notes") is not None:
            new_notes = u["set_notes"]
        elif u.get("append_notes"):
            new_notes = (current_notes + ("\n" if current_notes else "") + u["append_notes"]).strip()
        else:
            new_notes = current_notes
        # Only write if something actually changed
        changed = (new_tags != current_tags) or (new_notes != current_notes)
        if not changed:
            continue
        await db.contacts.update_one(
            {"id": contact["id"]},
            {"$set": {"tags": new_tags, "notes": new_notes, "updated_at": now}},
        )
        updated.append({
            "contact_id": contact["id"],
            "name": contact.get("name"),
            "email": contact.get("email"),
            "tags": new_tags,
            "added_tags": added,
            "notes_updated": (new_notes != current_notes),
        })
    return updated


async def _apply_new_contacts(parsed_contacts: list[dict], admin_id: str) -> list[dict]:
    """Insert contacts Claude proposed. Dedupe by (case-insensitive name) OR email.
    Returns the list of contacts actually created (skipping duplicates)."""
    if not parsed_contacts:
        return []
    # Preload existing names + emails for dedupe (kept short)
    existing_names: set[str] = set()
    existing_emails: set[str] = set()
    async for c in db.contacts.find({}, {"_id": 0, "name": 1, "email": 1}):
        n = (c.get("name") or "").strip().lower()
        e = (c.get("email") or "").strip().lower()
        if n:
            existing_names.add(n)
        if e:
            existing_emails.add(e)
    now = now_iso()
    created: list[dict] = []
    for nc in parsed_contacts:
        name = (nc.get("name") or "").strip()
        email = (nc.get("email") or "").strip().lower() or None
        if not name:
            continue
        # Dedupe
        if name.lower() in existing_names:
            continue
        if email and email in existing_emails:
            continue
        # Contact_type: infer from what's provided
        channels: list[str] = []
        if email: channels.append("email")
        if nc.get("phone"): channels.append("phone")
        doc = {
            "id": str(uuid.uuid4()),
            "name": name,
            "email": email,
            "phone": nc.get("phone") or "",
            "contact_type": channels,
            "tags": nc.get("tags") or [],
            "notes": nc.get("notes") or "",
            "last_contact_at": None,
            "last_contact_channel": None,
            "created_by_admin_id": admin_id,
            "created_via": "assistant",
            "created_at": now,
            "updated_at": now,
        }
        await db.contacts.insert_one(doc)
        existing_names.add(name.lower())
        if email:
            existing_emails.add(email)
        doc.pop("_id", None)
        created.append(doc)
    return created


async def _persist_marketing_suggestion(admin_id: str, sug: dict, source: str) -> dict:
    """Store a Claude-generated marketing suggestion. Supersedes any older pending ones
    (there should only be one pending at a time — regenerate replaces)."""
    now = now_iso()
    await db.marketing_suggestions.update_many(
        {"status": "pending"},
        {"$set": {"status": "superseded", "superseded_at": now}},
    )
    doc = {
        "id": str(uuid.uuid4()),
        "admin_id": admin_id,
        "subject": sug["subject"],
        "body": sug["body"],
        "target_tags": sug.get("target_tags") or [],
        "rationale": sug.get("rationale") or "",
        "status": "pending",
        "source": source,
        "created_at": now,
        "dismissed_at": None,
        "accepted_at": None,
    }
    await db.marketing_suggestions.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.post("/admin/assistant/chat")
async def assistant_chat(body: AssistantChatRequest, admin=Depends(require_admin)):
    """SSE streaming chat with the personal assistant, per-admin private."""
    open_tasks = await db.assistant_tasks.find(
        {"admin_id": admin["id"], "status": "open"}, {"_id": 0}
    ).sort("due_date", 1).to_list(200)
    clients = await db.users.find(
        {"role": "client"}, {"_id": 0, "id": 1, "name": 1, "email": 1, "company": 1}
    ).to_list(500)
    teammates = await db.users.find(
        {"role": "admin", "id": {"$ne": admin["id"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1},
    ).to_list(50)
    crm = await _crm_snapshot_for_assistant()
    stalled = await _stalled_scenarios_for_admin(admin["id"])

    session_id = f"assistant::{admin['id']}"
    chat = _make_scenario_ai_chat(session_id, ASSISTANT_SYSTEM_PROMPT)
    turn_context = _assistant_turn_context(admin, open_tasks, clients, teammates, crm, stalled)
    # Load recent conversation history so the assistant keeps memory across process restarts
    # and worker cycles (LlmChat's internal store is ephemeral). Cap at 24 messages.
    recent_msgs = await db.assistant_messages.find(
        {"admin_id": admin["id"]}, {"_id": 0, "role": 1, "content": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(24)
    recent_msgs.reverse()
    transcript_lines = []
    for m in recent_msgs:
        role_lbl = "Broker" if m.get("role") == "user" else "Assistant"
        c = (m.get("content") or "").strip()
        if c:
            transcript_lines.append(f"{role_lbl}: {c}")
    transcript = "\n\n".join(transcript_lines)
    if transcript:
        turn_context = (
            f"{turn_context}\n\n"
            "## Recent conversation (use this to maintain continuity):\n\n"
            f"{transcript}"
        )
    user_text = f"{turn_context}\n\nBroker message:\n{body.message}"

    async def event_gen():
        buf: List[str] = []
        # Persist user's own message (without injected context)
        await db.assistant_messages.insert_one({
            "id": str(uuid.uuid4()),
            "admin_id": admin["id"],
            "role": "user",
            "content": body.message,
            "created_at": now_iso(),
        })
        try:
            async for ev in chat.stream_message(UserMessage(text=user_text)):
                if isinstance(ev, TextDelta):
                    buf.append(ev.content)
                    yield f"data: {json.dumps({'type': 'token', 'content': ev.content})}\n\n"
                elif isinstance(ev, StreamDone):
                    break
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:400]})}\n\n"
            return

        full_text = "".join(buf)
        parsed = _split_assistant_response(full_text)
        applied = await _apply_assistant_actions(admin, parsed)
        if parsed.get("marketing_suggestion"):
            applied["marketing_suggestion"] = await _persist_marketing_suggestion(
                admin["id"], parsed["marketing_suggestion"], "assistant_chat"
            )
        if parsed.get("new_contacts"):
            applied["new_contacts"] = await _apply_new_contacts(parsed["new_contacts"], admin["id"])
        if parsed.get("contact_updates"):
            applied["contact_updates"] = await _apply_contact_updates(parsed["contact_updates"], admin["id"])

        assistant_msg_id = str(uuid.uuid4())
        await db.assistant_messages.insert_one({
            "id": assistant_msg_id,
            "admin_id": admin["id"],
            "role": "assistant",
            "content": parsed["text"],
            "email_draft": parsed.get("email_draft"),
            "suggest_client": parsed.get("suggest_client"),
            "created_tasks": applied["created"],
            "completed_task_ids": applied["completed"],
            "handoffs_sent": applied["handoffs"],
            "marketing_suggestion": applied.get("marketing_suggestion"),
            "new_contacts": applied.get("new_contacts", []),
            "contact_updates": applied.get("contact_updates", []),
            "created_at": now_iso(),
        })

        done_payload = {
            "type": "done",
            "message_id": assistant_msg_id,
            "text": parsed["text"],
            "email_draft": parsed.get("email_draft"),
            "suggest_client": parsed.get("suggest_client"),
            "created_tasks": applied["created"],
            "completed_task_ids": applied["completed"],
            "handoffs_sent": applied["handoffs"],
            "marketing_suggestion": applied.get("marketing_suggestion"),
            "new_contacts": applied.get("new_contacts", []),
            "contact_updates": applied.get("contact_updates", []),
        }
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/admin/assistant/messages")
async def assistant_messages(admin=Depends(require_admin)):
    msgs = await db.assistant_messages.find(
        {"admin_id": admin["id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(500)
    return msgs


@api.post("/admin/assistant/reset")
async def assistant_reset(admin=Depends(require_admin)):
    await db.assistant_messages.delete_many({"admin_id": admin["id"]})
    return {"ok": True}


# ----- Marketing reminders / suggestions -----

MARKETING_INTERVAL_DAYS = 30
DISMISS_QUIET_DAYS = 7  # after dismiss, don't nag for a week


async def _latest_pending_suggestion() -> Optional[dict]:
    doc = await db.marketing_suggestions.find_one(
        {"status": "pending"}, {"_id": 0}, sort=[("created_at", -1)]
    )
    return doc


async def _recent_dismissal_active() -> bool:
    """True if a dismissal happened within DISMISS_QUIET_DAYS — suppresses new auto-nudges."""
    doc = await db.marketing_suggestions.find_one(
        {"status": "dismissed"}, {"_id": 0, "dismissed_at": 1}, sort=[("dismissed_at", -1)]
    )
    if not doc or not doc.get("dismissed_at"):
        return False
    try:
        dt = datetime.fromisoformat(doc["dismissed_at"].replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days < DISMISS_QUIET_DAYS
    except Exception:
        return False


@api.get("/admin/assistant/marketing-status")
async def assistant_marketing_status(admin=Depends(require_admin)):
    crm = await _crm_snapshot_for_assistant()
    stats = crm["contacts_stats"]
    days_since = stats.get("days_since_last_marketing")
    quiet = await _recent_dismissal_active()
    # Nudge if never sent OR 30+ days ago, unless a fresh dismissal is still in the quiet window
    needs_suggestion = (days_since is None or days_since >= MARKETING_INTERVAL_DAYS) and not quiet
    pending = await _latest_pending_suggestion()
    return {
        "days_since_last_marketing": days_since,
        "last_marketing": stats.get("last_marketing"),
        "needs_suggestion": needs_suggestion,
        "interval_days": MARKETING_INTERVAL_DAYS,
        "quiet_until_next_nudge": quiet,
        "total_contacts": stats.get("total", 0),
        "tag_counts": stats.get("tag_counts", {}),
        "pending_suggestion": pending,
    }


@api.post("/admin/assistant/marketing-suggestion/generate")
async def assistant_marketing_generate(admin=Depends(require_admin)):
    """Ask Claude for a fresh marketing email draft based on current CRM state.
    Non-streaming, one-shot. Supersedes any prior pending suggestion."""
    crm = await _crm_snapshot_for_assistant()
    stats = crm["contacts_stats"]
    admin_first = (admin.get("name") or admin.get("email", "").split("@")[0]).split(" ")[0]
    today = datetime.now(timezone.utc)
    month_name = today.strftime("%B")
    days_since = stats.get("days_since_last_marketing")
    last_subject = (stats.get("last_marketing") or {}).get("subject") or "none"

    prompt_ctx = {
        "today": today.date().isoformat(),
        "month": month_name,
        "admin_first_name": admin_first,
        "days_since_last_marketing": days_since,
        "last_marketing_subject": last_subject,
        "total_contacts": stats.get("total", 0),
        "tag_counts": stats.get("tag_counts", {}),
        "stale_contact_count": len(crm.get("stale_contacts", [])),
    }
    system = (
        "You draft marketing emails for a boutique commercial real estate brokerage (Byrd & CO). "
        "Wayne and Caleb Byrd are the brokers. Tone: warm, brief, professional — like a personal note "
        "from a trusted broker, NOT a marketing blast. No emoji. No superlatives. 120–180 words max in "
        "the body. Sign off with the merge tag {{admin_first_name}}. Always include the {{first_name}} "
        "merge tag in the salutation.\n\n"
        "You MUST respond with a single JSON object and nothing else. Schema:\n"
        '{ "subject": "...", "body": "...", "target_tags": ["..."], "rationale": "..." }\n\n'
        "Rules:\n"
        "- `subject` under 60 chars, no ALL CAPS, no clickbait.\n"
        "- `body` MUST contain {{first_name}} and {{admin_first_name}}. Use \\n for newlines.\n"
        "- `target_tags` should be a subset of the CRM tag_counts provided (or [] for everyone).\n"
        "- `rationale` = one sentence explaining why this angle, given the current month/season and "
        "how long it's been since the last send.\n"
        "- Do NOT reuse the exact previous subject line.\n"
    )
    user = (
        "Current CRM state:\n"
        f"```json\n{json.dumps(prompt_ctx, indent=2)}\n```\n\n"
        "Draft one marketing email now."
    )
    chat = _make_scenario_ai_chat(
        f"mkt-suggest::{admin['id']}::{uuid.uuid4()}", system
    )
    try:
        buf: list[str] = []
        async for ev in chat.stream_message(UserMessage(text=user)):
            if isinstance(ev, TextDelta):
                buf.append(ev.content)
            elif isinstance(ev, StreamDone):
                break
        raw = "".join(buf).strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Draft generation failed: {str(e)[:200]}")

    # Robust JSON extraction — Claude sometimes wraps in ```json fences
    text = raw
    if "```" in text:
        # Grab the inside of the first fenced block
        start = text.find("```")
        after = text.find("\n", start)
        end = text.find("```", after + 1)
        if after >= 0 and end > 0:
            text = text[after + 1:end].strip()
    try:
        parsed = json.loads(text)
    except Exception:
        # Last resort: find the first {...} block
        s = text.find("{")
        e = text.rfind("}")
        if s < 0 or e < 0:
            raise HTTPException(status_code=502, detail="AI returned no parsable JSON")
        try:
            parsed = json.loads(text[s:e + 1])
        except Exception:
            raise HTTPException(status_code=502, detail="AI returned invalid JSON")

    subj = (parsed.get("subject") or "").strip()
    body = (parsed.get("body") or "").strip()
    if not subj or not body:
        raise HTTPException(status_code=502, detail="AI draft missing subject or body")
    tags_val = parsed.get("target_tags") or []
    if not isinstance(tags_val, list):
        tags_val = []

    stored = await _persist_marketing_suggestion(
        admin["id"],
        {
            "subject": subj[:200],
            "body": body[:20000],
            "target_tags": [str(t) for t in tags_val if str(t).strip()],
            "rationale": (parsed.get("rationale") or "")[:800],
        },
        "auto_generate",
    )
    return stored


@api.post("/admin/assistant/marketing-suggestion/{sid}/dismiss")
async def assistant_marketing_dismiss(sid: str, admin=Depends(require_admin)):
    res = await db.marketing_suggestions.update_one(
        {"id": sid, "status": "pending"},
        {"$set": {"status": "dismissed", "dismissed_at": now_iso(), "dismissed_by_admin_id": admin["id"]}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Suggestion not found or already handled")
    return {"ok": True}


@api.post("/admin/assistant/marketing-suggestion/{sid}/accept")
async def assistant_marketing_accept(sid: str, admin=Depends(require_admin)):
    """Marks a suggestion accepted so it won't show again. Returns the draft so the caller
    can route the user to the CRM composer to pick recipients + send."""
    doc = await db.marketing_suggestions.find_one({"id": sid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if doc.get("status") == "pending":
        await db.marketing_suggestions.update_one(
            {"id": sid},
            {"$set": {"status": "accepted", "accepted_at": now_iso(), "accepted_by_admin_id": admin["id"]}},
        )
        doc["status"] = "accepted"
    return doc


# ---------- Stalled scenarios (pipeline coach) ----------
@api.get("/admin/assistant/stalled-scenarios")
async def assistant_stalled_scenarios(admin=Depends(require_admin)):
    """Deals in draft/shopping status with 7+ days of inactivity AND <30% docs uploaded.
    Per-admin snoozes are respected. Sorted worst-first."""
    scens = await _stalled_scenarios_for_admin(admin["id"])
    return {"scenarios": scens, "count": len(scens)}


@api.post("/admin/assistant/stalled-scenarios/{scenario_id}/snooze")
async def assistant_stalled_snooze(scenario_id: str, admin=Depends(require_admin)):
    """Silence this scenario in the stalled banner for 7 days (per admin)."""
    scen = await db.scenarios.find_one({"id": scenario_id}, {"_id": 0, "id": 1})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    until = (datetime.now(timezone.utc) + timedelta(days=STALLED_SNOOZE_DAYS)).isoformat()
    await db.scenario_snoozes.update_one(
        {"admin_id": admin["id"], "scenario_id": scenario_id},
        {"$set": {
            "admin_id": admin["id"],
            "scenario_id": scenario_id,
            "snoozed_until": until,
            "snoozed_at": now_iso(),
        }},
        upsert=True,
    )
    return {"ok": True, "snoozed_until": until}



class EmailTestRequest(BaseModel):
    to: EmailStr


@api.get("/admin/settings/email/status")
async def email_status(admin=Depends(require_admin)):
    """Compact Postmark health snapshot for the dashboard widget."""
    token_present = bool(os.environ.get("POSTMARK_TOKEN"))
    from_email = os.environ.get("POSTMARK_FROM", "")
    from_name = os.environ.get("POSTMARK_FROM_NAME", "")
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    sent = await db.assistant_emails.count_documents({"status": "sent", "sent_at": {"$gte": since}})
    failed = await db.assistant_emails.count_documents({"status": "failed", "sent_at": {"$gte": since}})
    last_failure = await db.assistant_emails.find_one(
        {"status": "failed"}, {"_id": 0}, sort=[("sent_at", -1)]
    )
    last_success = await db.assistant_emails.find_one(
        {"status": "sent"}, {"_id": 0}, sort=[("sent_at", -1)]
    )
    return {
        "configured": token_present,
        "from_email": from_email,
        "from_name": from_name,
        "sent_30d": sent,
        "failed_30d": failed,
        "last_success_at": (last_success or {}).get("sent_at"),
        "last_failure_at": (last_failure or {}).get("sent_at"),
        "last_failure_error": (last_failure or {}).get("error"),
        "last_failure_to": (last_failure or {}).get("to"),
    }


@api.post("/admin/settings/email/test")
async def email_test(body: EmailTestRequest, admin=Depends(require_admin)):
    """Fire a canary email via Postmark, synchronously, so we can surface the exact
    Postmark response back to the operator."""
    admin_email = admin.get("email") or ""
    admin_name = admin.get("name") or "Byrd & CO"
    now = datetime.now(timezone.utc).isoformat()
    html = (
        "<div style=\"font-family:Georgia,serif;max-width:640px;margin:auto;color:#1A1A1A;\">"
        "<h2 style=\"font-family:Georgia,serif;\">Byrd &amp; CO — Email Test</h2>"
        f"<p>This is a test email from your Byrd &amp; CO admin dashboard, sent at {now} UTC.</p>"
        f"<p>Triggered by: <b>{admin_name}</b> ({admin_email})</p>"
        "<p>If you received this, Postmark is properly configured and delivering to this address.</p>"
        "<hr style=\"margin:24px 0;border:none;border-top:1px solid #E4DFD1;\"/>"
        "<div style=\"font-family:Arial,sans-serif;font-size:12px;color:#6B6558;\">Byrd &amp; CO Commercial Real Estate Lending</div>"
        "</div>"
    )
    text = f"Byrd & CO — Email Test\n\nSent at {now} UTC by {admin_name} ({admin_email}).\nIf you received this, Postmark is delivering."
    result = send_email(
        body.to, "Byrd & CO — Email Test", html, text, "email-test",
        None, f"{admin_name} · Byrd & CO", admin_email or None,
    )
    # Log this test send too, so the status widget stays accurate
    await db.assistant_emails.insert_one({
        "id": str(uuid.uuid4()),
        "admin_id": admin["id"],
        "from_email": os.environ.get("POSTMARK_FROM", ""),
        "reply_to": admin_email,
        "to": body.to,
        "subject": "Byrd & CO — Email Test",
        "body": text,
        "related_task_id": None,
        "status": "sent" if result.get("ok") else "failed",
        "error": result.get("error") or "",
        "sent_at": now_iso(),
        "tag": "email-test",
    })
    if not result.get("ok"):
        err = result.get("error") or "Unknown error"
        low = err.lower()
        detail = err
        if "pending approval" in low or "[412]" in err:
            detail = (
                "Postmark account is still in trial mode. Request approval in the "
                "Postmark dashboard (Servers → your server → Request approval). Raw: " + err
            )
        elif "sender signature" in low:
            detail = "Sender signature not verified in Postmark. Raw: " + err
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True, "sent_to": body.to, "from": os.environ.get("POSTMARK_FROM")}



@api.get("/admin/assistant/teammates")
async def assistant_teammates(admin=Depends(require_admin)):
    """Return other admin users so the client can offer @mention autocomplete."""
    others = await db.users.find(
        {"role": "admin", "id": {"$ne": admin["id"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1},
    ).sort("name", 1).to_list(50)
    result = []
    for u in others:
        full = u.get("name") or u.get("email", "").split("@")[0]
        first = full.split(" ")[0]
        result.append({
            "id": u["id"],
            "full_name": full,
            "first_name": first,
            "email": u.get("email"),
        })
    return result


@api.get("/admin/assistant/tasks")
async def assistant_list_tasks(admin=Depends(require_admin)):
    """Returns tasks bucketed for the UI."""
    tasks = await db.assistant_tasks.find(
        {"admin_id": admin["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    today = _today_iso()
    overdue, due_today, upcoming, done, dismissed = [], [], [], [], []
    for t in tasks:
        if t["status"] == "done":
            done.append(t)
            continue
        if t["status"] == "dismissed":
            dismissed.append(t)
            continue
        due = t.get("due_date")
        if not due:
            upcoming.append(t)
        elif due < today:
            overdue.append(t)
        elif due == today:
            due_today.append(t)
        else:
            upcoming.append(t)
    return {
        "overdue": overdue,
        "due_today": due_today,
        "upcoming": upcoming,
        "done": done[:20],
        "dismissed": dismissed[:10],
    }


@api.post("/admin/assistant/tasks")
async def assistant_create_task(body: AssistantTaskCreate, admin=Depends(require_admin)):
    doc = {
        "id": str(uuid.uuid4()),
        "admin_id": admin["id"],
        "title": body.title,
        "notes": body.notes or "",
        "due_date": body.due_date,
        "related_name": body.related_name or "",
        "related_client_id": body.related_client_id,
        "status": "open",
        "source": "manual",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "completed_at": None,
    }
    await db.assistant_tasks.insert_one(doc)
    doc.pop("_id", None)
    return doc


class AssistantTaskReply(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    mark_done: bool = False


@api.patch("/admin/assistant/tasks/{tid}")
async def assistant_update_task(tid: str, body: AssistantTaskUpdate, admin=Depends(require_admin)):
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = now_iso()
    if update.get("status") == "done":
        update["completed_at"] = now_iso()
    res = await db.assistant_tasks.update_one(
        {"id": tid, "admin_id": admin["id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    doc = await db.assistant_tasks.find_one({"id": tid}, {"_id": 0})
    return doc


@api.delete("/admin/assistant/tasks/{tid}")
async def assistant_delete_task(tid: str, admin=Depends(require_admin)):
    res = await db.assistant_tasks.delete_one({"id": tid, "admin_id": admin["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


@api.post("/admin/assistant/tasks/{tid}/reply")
async def assistant_reply_to_handoff(tid: str, body: AssistantTaskReply, admin=Depends(require_admin)):
    """Send a reply on a handoff task. Creates a new task in the ORIGINAL sender's list
    (with a 'From Caleb' badge and the reply as the note). Optionally marks the current task done."""
    task = await db.assistant_tasks.find_one({"id": tid, "admin_id": admin["id"]})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.get("assigned_by_admin_id"):
        raise HTTPException(status_code=400, detail="This isn't a handoff task — nothing to reply to")

    sender_id = task["assigned_by_admin_id"]
    sender = await db.users.find_one({"id": sender_id, "role": "admin"}, {"_id": 0, "id": 1, "name": 1, "email": 1})
    if not sender:
        raise HTTPException(status_code=404, detail="Original sender no longer exists")

    from_name = admin.get("name") or admin.get("email", "").split("@")[0]
    reply_id = str(uuid.uuid4())
    reply_doc = {
        "id": reply_id,
        "admin_id": sender_id,
        "title": f"Reply from {from_name.split(' ')[0]} on: {task['title']}",
        "notes": "",
        "due_date": None,
        "related_name": task.get("related_name", ""),
        "related_client_id": task.get("related_client_id"),
        "status": "open",
        "source": "reply",
        "assigned_by_admin_id": admin["id"],
        "assigned_by_name": from_name,
        "handoff_note": body.message,
        "parent_task_id": tid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "completed_at": None,
    }
    await db.assistant_tasks.insert_one(reply_doc)

    if body.mark_done:
        await db.assistant_tasks.update_one(
            {"id": tid, "admin_id": admin["id"]},
            {"$set": {"status": "done", "completed_at": now_iso(), "updated_at": now_iso()}},
        )

    reply_doc.pop("_id", None)
    return {"ok": True, "reply": reply_doc, "task_marked_done": body.mark_done}


@api.post("/admin/assistant/email/send")
async def assistant_send_email(body: AssistantEmailSend, admin=Depends(require_admin)):
    """Send an email on behalf of the admin via Postmark, and log it.
    Uses the verified Postmark sender signature as the From address (only that address is
    authorized to send in this account) and puts the admin's personal email in Reply-To so
    replies still route to Wayne/Caleb naturally.
    Runs synchronously so we can surface Postmark errors (e.g. pending-approval, invalid domain)
    directly in the UI instead of silently failing in a background task."""
    admin_email = admin.get("email")
    if not admin_email:
        raise HTTPException(status_code=400, detail="Admin has no email on file")
    admin_name = admin.get("name") or "Byrd & CO"
    # Wrap the body in a lightweight branded template so it doesn't look like a system email
    safe_body = body.body.replace("<", "&lt;").replace(">", "&gt;")
    html = (
        "<div style=\"font-family:Georgia,serif;max-width:640px;margin:auto;color:#1A1A1A;\">"
        f"<div style=\"white-space:pre-wrap;font-family:Arial,sans-serif;font-size:14px;line-height:1.55;\">{safe_body}</div>"
        f"<hr style=\"margin:24px 0;border:none;border-top:1px solid #E4DFD1;\"/>"
        f"<div style=\"font-family:Arial,sans-serif;font-size:12px;color:#6B6558;\">{admin_name}<br/>Byrd &amp; CO Commercial Real Estate Lending<br/>"
        f"<a href=\"mailto:{admin_email}\" style=\"color:#6B6558;\">{admin_email}</a></div>"
        "</div>"
    )
    # Synchronous send. From MUST be the verified POSTMARK_FROM sender signature
    # (admin.email is not a Postmark sender signature and would be rejected).
    # We set From-Name to include the admin's name so recipients still see who it's from,
    # and put admin.email in Reply-To so replies land in the broker's normal inbox.
    friendly_from_name = f"{admin_name} · Byrd & CO"
    result = send_email(
        body.to, body.subject, html, body.body, "assistant-outbound",
        None,  # use POSTMARK_FROM (the verified sender signature)
        friendly_from_name,
        admin_email,  # reply_to
    )
    log_id = str(uuid.uuid4())
    status = "sent" if result.get("ok") else "failed"
    error_msg = result.get("error") or ""
    await db.assistant_emails.insert_one({
        "id": log_id,
        "admin_id": admin["id"],
        "from_email": admin_email,
        "reply_to": admin_email,
        "to": body.to,
        "subject": body.subject,
        "body": body.body,
        "related_task_id": body.related_task_id,
        "status": status,
        "error": error_msg,
        "sent_at": now_iso(),
    })
    if not result.get("ok"):
        detail = error_msg or "Email failed to send"
        low = error_msg.lower()
        if "pending approval" in low or "[412]" in error_msg:
            detail = (
                "Postmark account is still in trial/pending-approval mode. While in trial, "
                "it will only send to recipients that share the exact domain of the sender. "
                "Two ways to fix: (a) request approval in the Postmark dashboard (Servers → "
                "your server → Request approval), OR (b) add an @byrd-co.com Sender Signature "
                "(bare domain, not the mail. subdomain) and update POSTMARK_FROM to use it. "
                "Raw error: " + error_msg
            )
        elif "sender signature" in low:
            detail = (
                "The sender address isn't verified in Postmark. Add it as a Sender Signature "
                "in the Postmark dashboard or update POSTMARK_FROM. Raw error: " + error_msg
            )
        # Use 400 (not 502) so Cloudflare passes the JSON body through unchanged
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True, "id": log_id, "status": status}


# ================ Marketing — Loan Quote Studio (listing agent) ================
# Ada-driven builder for a 1-page Loan Quote PDF that brokers give to commercial listing
# agents. Uses Perplexity Sonar for LIVE web research on current market rates, then Claude
# to synthesize three financing option columns (Bank / Agency / Credit Union).

PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY", "").strip()


class LoanQuoteProperty(BaseModel):
    name: Optional[str] = None
    property_type: Optional[str] = None       # Multifamily, Office, Retail, Industrial, Hotel, Mixed-Use, ...
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    estimated_value: Optional[float] = None
    noi: Optional[float] = None
    cap_rate_pct: Optional[float] = None      # NOI/value * 100
    occupancy_type: Optional[Literal["owner_occupied", "non_owner_occupied"]] = None


class LoanQuoteListingAgent(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None                  # validated when we actually email (future feature)
    phone: Optional[str] = None
    brokerage: Optional[str] = None
    photo_b64: Optional[str] = None              # inline base64 headshot (jpg/png)
    photo_content_type: Optional[str] = None


class LoanQuoteOption(BaseModel):
    label: str = "Bank"                       # Bank / Agency / Credit Union
    ltv_pct: Optional[float] = None
    loan_amount: Optional[float] = None
    loan_program: Optional[str] = None        # "7yr fixed / 30yr amort"
    interest_rate_pct: Optional[float] = None
    monthly_payment: Optional[float] = None
    recourse: Optional[Literal["Yes", "No", "Partial"]] = None
    notes: Optional[str] = None


class LoanQuoteState(BaseModel):
    property_info: LoanQuoteProperty = Field(default_factory=LoanQuoteProperty)
    listing_agent: LoanQuoteListingAgent = Field(default_factory=LoanQuoteListingAgent)
    options: List[LoanQuoteOption] = Field(default_factory=list)
    research_note: Optional[str] = None       # Perplexity synthesis text (informational)
    research_citations: List[str] = Field(default_factory=list)


class LoanQuoteChatBody(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(min_length=1)
    state: LoanQuoteState = Field(default_factory=LoanQuoteState)


class LoanQuoteResearchBody(BaseModel):
    state: LoanQuoteState


class LoanQuoteGenerateBody(BaseModel):
    state: LoanQuoteState
    add_listing_agent_to_crm: bool = True


def _cap_rate_math(prop: dict) -> dict:
    """Fill in cap_rate_pct from NOI+value, or NOI from value+cap_rate, if any is missing."""
    v = prop.get("estimated_value")
    noi = prop.get("noi")
    cr = prop.get("cap_rate_pct")
    if v and noi and not cr:
        prop["cap_rate_pct"] = round(float(noi) / float(v) * 100, 2)
    elif v and cr and not noi:
        prop["noi"] = round(float(v) * float(cr) / 100.0, 2)
    return prop


LOAN_QUOTE_CHAT_SYSTEM = """You are Ada, a warm and efficient senior commercial real estate broker assistant at Byrd & Co. You help brokers build a 1-page Loan Quote for a commercial listing agent to share with a prospective buyer.

You gather two groups of info, IN THIS ORDER:

GROUP A — Property info (ask first):
- name (optional — if the broker doesn't have a distinct property/deal name, reuse the street address as the name)
- property_type (Multifamily / Office / Retail / Industrial / Hotel / Mixed-Use / Self-Storage / Medical Office / Special Purpose)
- address, city, state
- estimated_value
- noi OR cap_rate_pct (either — the app auto-calculates the other)
- occupancy_type ("owner_occupied" | "non_owner_occupied")

GROUP B — Listing agent (ask AFTER property info is complete, BEFORE proposing rates):
- name, email, phone, brokerage

Behavior:
- Ask ONE or TWO fields at a time in a friendly conversation. Never bulk-request 8 fields.
- Confirm as you go ("Got it — $3M value.")
- If the broker's first message looks like a street address (contains a number + street word like St/Ave/Blvd/Rd, OR a comma-separated "street, city, ST"), extract it as `address` AND set `name` to the same value unless a separate name is obviously being given. Then ask for `property_type` next — DO NOT re-ask for the property name.
- Try to parse `city` and `state` out of any comma-separated address the broker gives (e.g., "2290 North St, Beaumont, TX" → address="2290 North St", city="Beaumont", state="TX"). Don't ask for city/state again if you already parsed them.
- If broker gives NOI or cap rate but not both, don't ask for the other.
- Once Group A is complete, transition with something like: "Great — I have the property. Now who's the listing agent? What's their name?" Then walk through agent name → brokerage → email → phone.
- If the broker asks you to look up the agent's contact info online (email/phone), set `lookup_agent: true` (see CRITICAL below).
- ONLY after BOTH Group A is complete AND you have at minimum the agent's name + email, prompt: "Ready for me to research current market rates and propose 3 financing options?" — and set `ready_for_rates: true` when the broker agrees.
- NEVER set `ready_for_rates: true` if the listing agent's name or email is still blank.

Return ONLY valid JSON in this exact schema:
{
  "reply": "your chat message to the broker (natural language, warm, short)",
  "updates": {
    "property_info": { ...only the fields you extracted from THIS broker message, omit others... },
    "listing_agent": { ...only fields extracted this turn... }
  },
  "ready_for_rates": false,
  "lookup_agent": false
}

CRITICAL:
- "updates" contains ONLY fields you learned this turn. Never repeat known fields.
- For property_type, use exact case: "Multifamily", "Office", "Retail", etc.
- For occupancy_type, use exact strings: "owner_occupied" or "non_owner_occupied".
- Numbers as raw numbers (not strings, no dollar signs or commas).
- Never invent info the broker didn't provide.
- If broker asks you to search / look up / find the listing agent's email or phone online, set "lookup_agent": true and in your "reply" say briefly "Let me look that up..." (do NOT claim you found anything — the app will do the actual search and post the results back).
- Return raw JSON. No markdown fences. No text before or after."""


LOAN_QUOTE_PROPOSAL_SYSTEM = """You are Ada synthesizing 3 loan option columns for a Loan Quote PDF Byrd & Co gives a commercial listing agent.

You will receive:
- The property facts (type, value, NOI, cap rate, occupancy)
- Live web research from Perplexity about CURRENT commercial real estate loan rates and typical structures

Produce EXACTLY 3 columns: Bank, Agency, Credit Union.

For each column, decide values that fit the property type + occupancy:
- Multifamily → Agency (Fannie/Freddie DUS/Optigo) fits well, Bank + CU also
- Office / Retail / Industrial → Bank + CU; use "SBA 504" instead of "Agency" ONLY if occupancy is owner_occupied
- Hotel → Bank + CU + Bridge (label the third column "Bank" if bridge doesn't fit)
- Owner-occupied deals of any commercial type → include SBA 7(a) or 504 as one column (label it "SBA" instead of "Agency")

Fill for each column:
- label: "Bank" | "Agency" | "Credit Union" | "SBA" | "Bridge"
- ltv_pct: percent (65, 70, 75, 80, etc)
- loan_amount: round to nearest $1,000 (value × LTV)
- loan_program: e.g., "7yr fixed / 30yr amort", "10yr fixed / 30yr amort", "5yr fixed / 25yr amort", "SBA 504 25yr", etc.
- interest_rate_pct: your best estimate from the research (label with a chip in the app)
- monthly_payment: standard amortization payment
- recourse: "Yes" | "No" | "Partial"

CRITICAL: return VALID JSON in this exact schema and NOTHING ELSE (no markdown fences, no prose):
{
  "options": [
    {"label": "Bank", "ltv_pct": 65, "loan_amount": 1950000, "loan_program": "7yr fixed / 30yr amort", "interest_rate_pct": 6.75, "monthly_payment": 12648, "recourse": "Yes"},
    {"label": "Agency", "ltv_pct": 75, "loan_amount": 2250000, "loan_program": "10yr fixed / 30yr amort", "interest_rate_pct": 5.95, "monthly_payment": 13400, "recourse": "No"},
    {"label": "Credit Union", "ltv_pct": 65, "loan_amount": 1950000, "loan_program": "5yr fixed / 25yr amort", "interest_rate_pct": 6.50, "monthly_payment": 13100, "recourse": "Yes"}
  ],
  "note": "Short one-line qualifier, e.g., 'Rates indicative Jan 2026 — verify with lender.'"
}"""


async def _perplexity_query(query: str, max_tokens: int = 700) -> Optional[dict]:
    """Generic Perplexity Sonar call. Returns {'content', 'citations'} or None."""
    if not PERPLEXITY_API_KEY:
        return None
    payload = {
        "model": "sonar-pro",
        "messages": [{"role": "user", "content": query}],
        "temperature": 0.1, "max_tokens": max_tokens, "return_citations": True,
    }
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post("https://api.perplexity.ai/chat/completions",
                                  json=payload, headers=headers)
            if r.status_code >= 400:
                logger.warning("Perplexity %s: %s", r.status_code, r.text[:300])
                return None
            data = r.json()
    except Exception as e:
        logger.warning("Perplexity request failed: %s", e)
        return None
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return None
    citations = data.get("citations") or data.get("search_results") or []
    if isinstance(citations, list) and citations and isinstance(citations[0], dict):
        citations = [c.get("url") or c.get("link") for c in citations if c.get("url") or c.get("link")]
    return {"content": content, "citations": [c for c in citations if c][:6]}


async def _perplexity_rate_search(prop: dict) -> Optional[dict]:
    """Query Perplexity Sonar for current CRE loan rates + typical structures for this property."""
    if not PERPLEXITY_API_KEY:
        return None
    ptype = (prop.get("property_type") or "commercial real estate").lower()
    occ = prop.get("occupancy_type")
    occ_hint = "owner-occupied" if occ == "owner_occupied" else ("investment" if occ == "non_owner_occupied" else "")
    today = datetime.now(timezone.utc).strftime("%B %Y")
    query = (
        f"Current commercial real estate loan interest rates {today} for {occ_hint} {ptype} property in the United States. "
        f"Include typical Bank rates, Agency (Fannie Mae Freddie Mac) rates for multifamily, SBA 504 and 7(a) for owner-occupied, "
        f"and Credit Union rates. For each: rate range, typical LTV, typical amortization, typical fixed period, recourse. "
        f"Cite lender or industry sources with recent publication dates. Do not invent numbers."
    )
    payload = {
        "model": "sonar-pro",
        "messages": [{"role": "user", "content": query}],
        "temperature": 0.1,
        "max_tokens": 900,
        "return_citations": True,
    }
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post("https://api.perplexity.ai/chat/completions",
                                  json=payload, headers=headers)
            if r.status_code >= 400:
                logger.warning("Perplexity %s: %s", r.status_code, r.text[:300])
                return None
            data = r.json()
    except Exception as e:
        logger.warning("Perplexity request failed: %s", e)
        return None
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return None
    citations = data.get("citations") or data.get("search_results") or []
    if isinstance(citations, list) and citations and isinstance(citations[0], dict):
        citations = [c.get("url") or c.get("link") for c in citations if c.get("url") or c.get("link")]
    return {"content": content, "citations": [c for c in citations if c][:6]}


def _clean_json_output(txt: str) -> str:
    """Strip markdown fences and extract the first {...} block."""
    t = (txt or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:].strip()
    lb = t.find("{")
    rb = t.rfind("}")
    if lb >= 0 and rb > lb:
        return t[lb:rb + 1]
    return t


class LoanQuoteAgentLookupBody(BaseModel):
    name: str = Field(min_length=1)
    brokerage: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None


@api.post("/admin/marketing/agent-lookup")
async def admin_agent_lookup(body: LoanQuoteAgentLookupBody, user=Depends(require_studio_user)):
    """Perplexity search for a commercial listing agent's publicly-listed email + phone.
    Only returns hits that appear in official brokerage websites or licensing directories."""
    if not PERPLEXITY_API_KEY:
        raise HTTPException(status_code=400, detail="Perplexity API not configured on this environment")
    parts = [f"Find the professional email address and phone number for commercial real estate listing agent {body.name}"]
    if body.brokerage:
        parts.append(f"at {body.brokerage}")
    if body.city:
        loc = body.city + (f", {body.state}" if body.state else "")
        parts.append(f"in {loc}")
    query = " ".join(parts) + (
        ". Return ONLY publicly available contact info from their brokerage website, LinkedIn profile, "
        "or real estate license lookup. If you find multiple candidates, list up to 3 with the source URL. "
        "If you cannot confidently find their contact info, say so explicitly. Do NOT invent email addresses."
    )
    result = await _perplexity_query(query, max_tokens=600)
    if not result:
        raise HTTPException(status_code=502, detail="Perplexity search failed")
    content = result.get("content") or ""
    citations = result.get("citations") or []
    # Extract emails + phones from the synthesized text
    email_re = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
    phone_re = re.compile(r"\(?\b\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b")
    emails = sorted({e.strip(".,;:") for e in email_re.findall(content)})
    phones = sorted({p for p in phone_re.findall(content)})
    # Filter out obvious placeholders
    banned = ("example.com", "domain.com", "email.com", "test.com")
    emails = [e for e in emails if not any(b in e.lower() for b in banned)][:4]
    phones = phones[:4]
    return {
        "found": bool(emails or phones),
        "emails": emails,
        "phones": phones,
        "summary": content,
        "citations": citations,
    }


@api.post("/admin/marketing/quote/chat")
async def admin_loanquote_chat(body: LoanQuoteChatBody, admin=Depends(require_studio_user)):
    """Turn-by-turn Ada conversation. Broker asks; Ada fills in the state via natural dialogue."""
    # Auto-fill cap_rate <-> NOI when possible (idempotent)
    prop = _cap_rate_math(body.state.property_info.model_dump())
    sid = body.session_id or f"lq-{uuid.uuid4().hex[:10]}"
    # Assemble a compact CURRENT_STATE block so Ada knows what she already has
    state_dict = body.state.model_dump()
    state_dict["property_info"] = prop
    context = ("CURRENT_STATE (what we already know — do NOT re-ask filled fields):\n"
               f"{json.dumps(state_dict, indent=2)}\n")
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=sid,
                   system_message=LOAN_QUOTE_CHAT_SYSTEM)
    chat.with_model("anthropic", "claude-sonnet-4-5-20250929")
    try:
        reply = await chat.send_message(UserMessage(text=f"{context}\nBroker just said: {body.message}"))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ada chat failed: {e}")
    raw = (reply or "").strip()
    try:
        parsed = json.loads(_clean_json_output(raw))
    except Exception:
        # Fallback — treat entire response as chat reply, no state updates
        parsed = {"reply": raw, "updates": {}, "ready_for_rates": False}
    reply_text = (parsed.get("reply") or "").strip()
    updates = parsed.get("updates") or {}
    # Merge updates into state (only non-empty values)
    new_state = body.state.model_dump()
    new_state["property_info"] = prop  # start from cap-rate-normalized
    for section in ("property_info", "listing_agent"):
        sec_updates = updates.get(section) or {}
        for k, v in sec_updates.items():
            if v in (None, "", []):
                continue
            new_state[section][k] = v
    # Re-run cap-rate math after updates in case value/NOI/cap arrived this turn
    new_state["property_info"] = _cap_rate_math(new_state["property_info"])
    # Hard guardrail: never allow ready_for_rates to fire without the listing agent's
    # name + email. Ada's system prompt covers this, but LLM outputs drift; we enforce
    # it deterministically so the frontend can't auto-launch rate research early.
    _agent = new_state.get("listing_agent") or {}
    _ready = bool(parsed.get("ready_for_rates"))
    if _ready and (not (_agent.get("name") or "").strip()
                   or not (_agent.get("email") or "").strip()):
        _ready = False
        # Nudge the reply if Ada tried to skip the agent step
        if reply_text and "listing agent" not in reply_text.lower():
            reply_text += ("\n\nBefore I research rates — who's the listing agent? "
                           "I need at minimum their name and email.")
    return {"session_id": sid, "reply": reply_text,
            "ready_for_rates": _ready,
            "lookup_agent": bool(parsed.get("lookup_agent")),
            "state": new_state}


@api.post("/admin/marketing/quote/propose-options")
async def admin_loanquote_propose(body: LoanQuoteResearchBody, admin=Depends(require_studio_user)):
    """Perplexity → Claude synthesis → 3 financing option columns. Admin-only."""
    prop = _cap_rate_math(body.state.property_info.model_dump())
    if not prop.get("estimated_value"):
        raise HTTPException(status_code=400, detail="Estimated value required before proposing options")
    if not (prop.get("noi") or prop.get("cap_rate_pct")):
        raise HTTPException(status_code=400, detail="NOI or cap rate required")

    research = await _perplexity_rate_search(prop)
    research_content = (research or {}).get("content") or ""
    citations = (research or {}).get("citations") or []

    # Feed research + property to Claude
    facts = ["PROPERTY FACTS:"]
    for k, v in prop.items():
        if v is not None and v != "":
            facts.append(f"- {k}: {v}")
    facts_block = "\n".join(facts)
    research_block = ("LIVE MARKET RESEARCH (from Perplexity Sonar; treat as dated market context, not a lender commitment):\n"
                      + research_content) if research_content else "LIVE MARKET RESEARCH: (none available — use industry-typical ranges)"
    sid = f"lq-propose-{uuid.uuid4().hex[:10]}"
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=sid,
                   system_message=LOAN_QUOTE_PROPOSAL_SYSTEM)
    chat.with_model("anthropic", "claude-sonnet-4-5-20250929")
    try:
        reply = await chat.send_message(UserMessage(text=f"{facts_block}\n\n{research_block}\n\nProduce the JSON now."))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ada proposal failed: {e}")
    try:
        parsed = json.loads(_clean_json_output(reply or ""))
    except Exception:
        raise HTTPException(status_code=502, detail="Ada returned invalid JSON — click Propose again.")
    options = parsed.get("options") or []
    # Ensure exactly 3, coerce & clean
    normalized = []
    for opt in options[:3]:
        try:
            normalized.append(LoanQuoteOption(**opt).model_dump())
        except Exception:
            continue
    while len(normalized) < 3:
        normalized.append(LoanQuoteOption(label=["Bank", "Agency", "Credit Union"][len(normalized)]).model_dump())
    return {
        "options": normalized,
        "note": parsed.get("note") or "",
        "research_note": research_content,
        "research_citations": citations,
    }


def _byrd_watermark(canvas, doc):
    """Diagonal light-gray 'BYRD & CO' repeated across the page. Rendered UNDER the
    content so the type stays readable but a screenshot / crop that removes the
    footer still visibly retains Byrd branding.

    Also stamps a small footer link on every page ("Byrd & CO · byrd-co.com") that
    the request-a-quote button reinforces on the last page."""
    canvas.saveState()
    page_w, page_h = letter
    canvas.setFont("Helvetica-Bold", 44)
    canvas.setFillColorRGB(0.78, 0.78, 0.78)
    try:
        canvas.setFillAlpha(0.13)
    except Exception:
        pass
    canvas.translate(page_w / 2, page_h / 2)
    canvas.rotate(30)
    # Tile the text along a diagonal so any cropped section still shows the brand.
    for row in range(-2, 3):
        for col in range(-2, 3):
            canvas.drawCentredString(col * 260, row * 130, "BYRD & CO")
    canvas.restoreState()
    # Tiny persistent footer stamp on every page — very subtle, greyed
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColorRGB(0.55, 0.53, 0.47)
    canvas.drawRightString(page_w - 0.35 * inch, 0.28 * inch,
                           "Byrd & CO · Commercial Real Estate Lending · byrd-co.com")
    canvas.restoreState()


def render_loan_quote_pdf(state: dict, quote_id: str = None,
                           request_url: str = None) -> bytes:
    """Byrd-branded 1-page Loan Quote PDF for a commercial listing agent.
    * quote_id / request_url — when provided, embeds a "Request a Live Quote" button
      at the bottom of the PDF that links to a public form."""
    from reportlab.platypus import Image as RImage
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=0.55 * inch, rightMargin=0.55 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            title="Byrd & Co Loan Quote")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                        fontSize=22, leading=26, textColor=BYRD_INK, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                        fontSize=10, leading=12, textColor=BYRD_INK, spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=9, leading=12, textColor=BYRD_INK)
    small = ParagraphStyle("small", parent=styles["BodyText"], fontName="Helvetica",
                           fontSize=8, leading=10, textColor=BYRD_MUTED)
    money = lambda v: _fmt_money(v)
    pct = lambda v, d=2: _fmt_pct(v, d)

    prop = state.get("property_info") or {}
    options = state.get("options") or []

    els = []
    els.append(Paragraph("BYRD &amp; CO", ParagraphStyle(
        "brand", fontName="Helvetica-Bold", fontSize=10, textColor=BYRD_GOLD, spaceAfter=1)))
    els.append(Paragraph("Commercial Real Estate Lending", small))
    els.append(Spacer(1, 4))
    els.append(Paragraph("Loan Quote", h1))
    els.append(Spacer(1, 4))

    # Property Details — 2 column key/value block
    addr = ", ".join(x for x in [prop.get("address"), prop.get("city"), prop.get("state")] if x)
    left_rows = [
        [Paragraph("<b>Property Name</b>", body), prop.get("name") or "—"],
        [Paragraph("<b>Property Type</b>", body), prop.get("property_type") or "—"],
        [Paragraph("<b>Address</b>", body), addr or "—"],
    ]
    if prop.get("occupancy_type"):
        left_rows.append([Paragraph("<b>Occupancy</b>", body),
                          "Owner-Occupied" if prop["occupancy_type"] == "owner_occupied" else "Non-Owner-Occupied"])
    right_rows = [
        [Paragraph("<b>Estimated Value</b>", body), money(prop.get("estimated_value"))],
        [Paragraph("<b>NOI</b>", body), money(prop.get("noi"))],
        [Paragraph("<b>Cap Rate</b>", body), pct(prop.get("cap_rate_pct"))],
    ]
    # pad shorter side so both tables have the same # rows
    while len(right_rows) < len(left_rows):
        right_rows.append(["", ""])
    while len(left_rows) < len(right_rows):
        left_rows.append(["", ""])
    lt = Table(left_rows, colWidths=[1.15 * inch, 2.3 * inch])
    rt = Table(right_rows, colWidths=[1.1 * inch, 1.6 * inch])
    for tbl in (lt, rt):
        tbl.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
    els.append(Paragraph("PROPERTY DETAILS", h2))
    els.append(Table([[lt, rt]], colWidths=[3.5 * inch, 2.8 * inch]))
    els.append(Spacer(1, 8))

    # Financing options — 3 column comparison
    els.append(Paragraph("FINANCING OPTIONS", h2))
    col_hdr_style = ParagraphStyle(
        "col_hdr", fontName="Helvetica-Bold", fontSize=11, textColor=BYRD_GOLD, alignment=1)
    # Table has 4 columns: [row-label | Bank | Agency | Credit Union]. The header row must
    # start with an empty cell so labels sit ABOVE their data columns.
    hdr = [""] + [Paragraph(f"<b>{o.get('label', '—')}</b>", col_hdr_style) for o in options[:3]]
    while len(hdr) < 4:
        hdr.append(Paragraph("—", body))
    rows = [hdr]

    def _pay(v):
        return money(v)

    fields = [
        ("Estimated Value", lambda o: money(prop.get("estimated_value"))),
        ("Loan To Value", lambda o: pct(o.get("ltv_pct"), 0) if o.get("ltv_pct") is not None else "—"),
        ("Loan Amount", lambda o: money(o.get("loan_amount"))),
        ("Loan Program", lambda o: o.get("loan_program") or "—"),
        ("Interest Rate", lambda o: pct(o.get("interest_rate_pct"), 2) if o.get("interest_rate_pct") is not None else "—"),
        ("Monthly Payment", lambda o: _pay(o.get("monthly_payment"))),
        ("Recourse", lambda o: o.get("recourse") or "—"),
    ]
    for label, fn in fields:
        row = [Paragraph(f"<b>{label}</b>", small)]
        for o in options[:3]:
            row.append(Paragraph(str(fn(o)), body))
        while len(row) < 4:
            row.append("—")
        rows.append(row)

    ot = Table(rows, colWidths=[1.35 * inch, 2.0 * inch, 2.0 * inch, 2.0 * inch])
    ot.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BYRD_IVORY),
        ("GRID", (0, 0), (-1, -1), 0.4, BYRD_LINE),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("BACKGROUND", (0, 1), (0, -1), BYRD_IVORY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    els.append(ot)

    # Disclaimer
    els.append(Spacer(1, 8))
    els.append(Paragraph(
        "<i>Byrd &amp; Co is providing this quote for informational purposes only. "
        "Rates and terms are indicative market estimates as of the quote date, "
        "subject to lender approval, appraisal, and full underwriting.</i>", small))

    # Listing Agent branding band — photo + contact block if we have any info
    agent = state.get("listing_agent") or {}
    agent_has_any = any(agent.get(k) for k in ("name", "phone", "email", "brokerage", "photo_b64"))
    if agent_has_any:
        els.append(Spacer(1, 14))
        els.append(Paragraph("PRESENTED BY", h2))
        photo_cell = ""
        if agent.get("photo_b64"):
            try:
                photo_bytes = base64.b64decode(agent["photo_b64"])
                photo_cell = RImage(BytesIO(photo_bytes), width=1.1 * inch, height=1.35 * inch, kind="proportional")
            except Exception:
                photo_cell = ""
        info_lines = []
        if agent.get("name"):
            info_lines.append(f"<b><font size='11'>{agent['name']}</font></b>")
        if agent.get("brokerage"):
            info_lines.append(f"<font color='#6B6558'>{agent['brokerage']}</font>")
        if agent.get("phone"):
            info_lines.append(agent["phone"])
        if agent.get("email"):
            info_lines.append(agent["email"])
        info_para = Paragraph("<br/>".join(info_lines), body)
        band = Table([[photo_cell, info_para]], colWidths=[1.3 * inch, 6.0 * inch])
        band.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BYRD_IVORY),
            ("BOX", (0, 0), (-1, -1), 0.5, BYRD_LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        els.append(band)

    # Byrd contact block
    els.append(Spacer(1, 10))
    contact = Table([[
        Paragraph("<b>Wayne Byrd</b><br/>832-813-9802<br/>wayne@byrd-co.com", body),
        Paragraph("<b>Caleb Byrd</b><br/>832-661-4390<br/>caleb@byrd-co.com", body),
    ]], colWidths=[3.65 * inch, 3.65 * inch])
    contact.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BYRD_IVORY),
        ("BOX", (0, 0), (-1, -1), 0.5, BYRD_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    els.append(contact)

    # Optional live "Request a Quote" CTA — always render when we know the public URL,
    # so any recipient (agent, listing agent's client, cold PDF forward) can convert.
    if request_url:
        els.append(Spacer(1, 12))
        cta = Table([[Paragraph(
            f'<font color="#1A1A1A"><b>Interested in this financing?</b></font><br/>'
            f'<font color="#6B6558" size="8">Tap to send your info to Byrd &amp; CO — '
            f'we\'ll follow up with live terms.</font>',
            body,
        ), Paragraph(
            f'<link href="{request_url}"><font color="#1A1A1A" size="11"><b>Request a Live Quote &#8594;</b></font></link>',
            ParagraphStyle("cta_btn", parent=body, alignment=2),  # right-aligned
        )]], colWidths=[4.6 * inch, 2.7 * inch])
        cta.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#C89434")),
            ("BOX", (0, 0), (-1, -1), 0.5, BYRD_INK),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ]))
        els.append(cta)

    doc.build(els, onFirstPage=_byrd_watermark, onLaterPages=_byrd_watermark)
    return buf.getvalue()


@api.post("/admin/marketing/quote/generate")
async def admin_loanquote_generate(body: LoanQuoteGenerateBody, user=Depends(require_studio_user)):
    """Render PDF, persist quote + PDF, optionally add listing agent to CRM."""
    state = body.state.model_dump()
    state["property_info"] = _cap_rate_math(state.get("property_info") or {})
    if not (state.get("options") and len(state["options"]) >= 1):
        raise HTTPException(status_code=400, detail="Propose financing options before generating the PDF")
    qid = str(uuid.uuid4())
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    request_url = f"{base}/quote/{qid}/request" if base else None
    pdf_bytes = render_loan_quote_pdf(state, quote_id=qid, request_url=request_url)
    now = now_iso()
    fname = f"byrd-loan-quote-{(state.get('property_info', {}).get('name') or 'quote').replace(' ', '-').lower()[:40]}.pdf"
    contact_id = None
    la = state.get("listing_agent") or {}
    if body.add_listing_agent_to_crm and la.get("name") and la.get("email"):
        # Upsert into db.contacts by email; tag as "Listing Agent"
        existing = await db.contacts.find_one({"email": la["email"].lower()}, {"_id": 0})
        if existing:
            contact_id = existing["id"]
            tags = list({*(existing.get("tags") or []), "Listing Agent"})
            await db.contacts.update_one(
                {"id": contact_id},
                {"$set": {"tags": tags, "updated_at": now,
                          "phone": existing.get("phone") or la.get("phone"),
                          "company": existing.get("company") or la.get("brokerage")}},
            )
        else:
            contact_id = str(uuid.uuid4())
            await db.contacts.insert_one({
                "id": contact_id, "name": la["name"], "email": la["email"].lower(),
                "phone": la.get("phone") or "", "company": la.get("brokerage") or "",
                "tags": ["Listing Agent"], "notes": f"Auto-added from Loan Quote for {state.get('property_info', {}).get('name') or 'property'}.",
                "created_at": now, "updated_at": now, "created_by": user["id"],
            })
    await db.loan_quotes.insert_one({
        "id": qid, "created_at": now,
        "created_by": user["id"],
        "created_by_user_id": user["id"],
        "created_by_role": user.get("role"),
        "created_by_name": user.get("name") or user.get("email") or "",
        "property_info": state.get("property_info"),
        "listing_agent": la,
        "options": state.get("options"),
        "research_note": state.get("research_note"),
        "research_citations": state.get("research_citations", []),
        "filename": fname, "size": len(pdf_bytes),
        "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),
        "contact_id": contact_id,
    })
    return {"ok": True, "id": qid, "filename": fname, "contact_id": contact_id}


def _quote_owner_filter(user: dict) -> dict:
    """When the caller is NOT admin, restrict quote reads/writes to their own rows.
    Legacy admin-generated rows have no `created_by_user_id`; those stay admin-only."""
    if user.get("role") == "admin":
        return {}
    return {"created_by_user_id": user["id"]}


@api.get("/admin/marketing/quotes")
async def admin_list_loanquotes(user=Depends(require_studio_user)):
    docs = await db.loan_quotes.find(
        _quote_owner_filter(user), {"_id": 0, "pdf_b64": 0}
    ).sort("created_at", -1).to_list(200)
    return docs


@api.get("/admin/marketing/quotes/search")
async def admin_search_loanquotes(q: str, user=Depends(require_studio_user)):
    """Case-insensitive search on property name / address / city for the Ada 'load quote' flow."""
    if not q or len(q.strip()) < 2:
        return []
    needle = q.strip()
    regex = {"$regex": needle.replace("\\", "\\\\").replace(".", "\\."), "$options": "i"}
    query = {
        "$or": [
            {"property_info.name": regex},
            {"property_info.address": regex},
            {"property_info.city": regex},
        ]
    }
    owner = _quote_owner_filter(user)
    if owner:
        query = {"$and": [owner, query]}
    docs = await db.loan_quotes.find(query, {"_id": 0, "pdf_b64": 0}).sort("created_at", -1).to_list(20)
    return docs


@api.get("/admin/marketing/quotes/{qid}")
async def admin_get_loanquote(qid: str, user=Depends(require_studio_user)):
    q = await db.loan_quotes.find_one({"id": qid, **_quote_owner_filter(user)}, {"_id": 0, "pdf_b64": 0})
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    return q


@api.patch("/admin/marketing/quotes/{qid}")
async def admin_update_loanquote(qid: str, body: LoanQuoteGenerateBody, user=Depends(require_studio_user)):
    """Overwrite an existing saved quote — re-renders the PDF and replaces stored payload."""
    q = await db.loan_quotes.find_one({"id": qid, **_quote_owner_filter(user)})
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    state = body.state.model_dump()
    state["property_info"] = _cap_rate_math(state.get("property_info") or {})
    if not (state.get("options") and len(state["options"]) >= 1):
        raise HTTPException(status_code=400, detail="Financing options are required")
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    request_url = f"{base}/quote/{qid}/request" if base else None
    pdf_bytes = render_loan_quote_pdf(state, quote_id=qid, request_url=request_url)
    now = now_iso()
    fname = (q.get("filename")
             or f"byrd-loan-quote-{(state.get('property_info', {}).get('name') or 'quote').replace(' ', '-').lower()[:40]}.pdf")
    la = state.get("listing_agent") or {}
    contact_id = q.get("contact_id")
    if body.add_listing_agent_to_crm and la.get("name") and la.get("email") and not contact_id:
        # Only create a new Contact if we didn't already on the first save
        existing = await db.contacts.find_one({"email": la["email"].lower()}, {"_id": 0})
        if existing:
            contact_id = existing["id"]
            tags = list({*(existing.get("tags") or []), "Listing Agent"})
            await db.contacts.update_one({"id": contact_id},
                                         {"$set": {"tags": tags, "updated_at": now}})
        else:
            contact_id = str(uuid.uuid4())
            await db.contacts.insert_one({
                "id": contact_id, "name": la["name"], "email": la["email"].lower(),
                "phone": la.get("phone") or "", "company": la.get("brokerage") or "",
                "tags": ["Listing Agent"],
                "notes": f"Auto-added from Loan Quote for {state.get('property_info', {}).get('name') or 'property'}.",
                "created_at": now, "updated_at": now, "created_by": user["id"],
            })
    await db.loan_quotes.update_one(
        {"id": qid},
        {"$set": {
            "updated_at": now,
            "property_info": state.get("property_info"),
            "listing_agent": la,
            "options": state.get("options"),
            "research_note": state.get("research_note"),
            "research_citations": state.get("research_citations", []),
            "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),
            "size": len(pdf_bytes),
            "contact_id": contact_id,
        }},
    )
    return {"ok": True, "id": qid, "filename": fname, "contact_id": contact_id}


@api.get("/admin/marketing/quotes/{qid}/pdf")
async def admin_download_loanquote(qid: str, user=Depends(require_studio_user)):
    q = await db.loan_quotes.find_one({"id": qid, **_quote_owner_filter(user)})
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    return Response(
        content=base64.b64decode(q["pdf_b64"]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{q.get("filename") or "loan-quote.pdf"}"'},
    )


@api.delete("/admin/marketing/quotes/{qid}")
async def admin_delete_loanquote(qid: str, user=Depends(require_studio_user)):
    res = await db.loan_quotes.delete_one({"id": qid, **_quote_owner_filter(user)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {"ok": True}


# ---------------- Public "Request a Live Quote" (from PDF CTA) ----------------

class QuoteRequestPublicBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field(default="", max_length=40)
    best_time: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=4000)


@api.get("/public/quote/{qid}")
async def public_quote_meta(qid: str):
    """Minimal public snapshot for the Request-a-Quote landing page — never returns
    the PDF or full options, just enough to confirm the quote exists + let the
    landing page show a headline (property name / address) for context."""
    q = await db.loan_quotes.find_one({"id": qid},
                                       {"_id": 0, "id": 1, "property_info": 1, "created_at": 1})
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    prop = q.get("property_info") or {}
    return {
        "id": q["id"],
        "property_name": prop.get("name") or "",
        "property_type": prop.get("property_type") or "",
        "address": prop.get("address") or "",
        "city": prop.get("city") or "",
        "state": prop.get("state") or "",
    }


@api.post("/public/quote/{qid}/request-callback")
async def public_quote_request_callback(qid: str, body: QuoteRequestPublicBody,
                                         background: BackgroundTasks, request: Request):
    """A prospect on the PDF clicked 'Request a Live Quote'. Persist the lead + email
    all BROKER_EMAILS with the quote PDF re-attached for a one-tap follow-up."""
    q = await db.loan_quotes.find_one({"id": qid})
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    lead_id = str(uuid.uuid4())
    now = now_iso()
    lead = {
        "id": lead_id,
        "quote_id": qid,
        "name": body.name.strip(),
        "email": body.email.lower(),
        "phone": body.phone.strip(),
        "best_time": body.best_time.strip(),
        "message": body.message.strip(),
        "ip": (request.client.host if request.client else None),
        "user_agent": request.headers.get("user-agent", "")[:400],
        "created_at": now,
    }
    await db.loan_quote_leads.insert_one(lead)
    await audit_log(db, event_type="quote.public_request", request=request, user=None,
                    resource_type="loan_quote", resource_id=qid,
                    resource_name=q.get("filename") or "loan-quote.pdf",
                    metadata={"lead_id": lead_id, "email": body.email.lower(),
                              "phone": body.phone or "", "quote_id": qid})
    # Fire an email to every broker with lead details + the PDF attached.
    brokers = broker_emails()
    if brokers:
        prop = q.get("property_info") or {}
        subj = f"[Byrd] Live quote request — {body.name} on {prop.get('name') or prop.get('address') or 'a loan quote'}"
        base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
        review_link = f"{base}/admin/marketing/loan-quote?load={qid}" if base else "/admin/marketing/loan-quote"
        text = (
            f"A prospect just clicked 'Request a Live Quote' on a Byrd & Co PDF.\n\n"
            f"Name: {body.name}\n"
            f"Email: {body.email}\n"
            f"Phone: {body.phone or '—'}\n"
            f"Best time: {body.best_time or '—'}\n\n"
            f"Property on the PDF: {prop.get('name') or '—'} · {prop.get('address') or ''}, "
            f"{prop.get('city') or ''} {prop.get('state') or ''}\n\n"
            f"Message:\n{body.message or '(no message)'}\n\n"
            f"Open the original quote: {review_link}\n"
        )
        html = f"""
        <div style="font-family:Georgia,serif;max-width:640px;margin:auto;">
          <div style="background:#1A1A1A;color:#C89434;padding:20px;text-align:center;">
            <div style="font-size:20px;font-weight:bold;letter-spacing:0.1em;">BYRD &amp; CO</div>
            <div style="font-size:10px;color:#C9C1AF;text-transform:uppercase;letter-spacing:0.2em;">Live Quote Request</div>
          </div>
          <div style="padding:24px;background:#FBF8F1;color:#1A1A1A;">
            <h2 style="margin:0 0 4px;font-family:Georgia,serif;">{body.name}</h2>
            <div style="font-family:Arial,sans-serif;font-size:13px;color:#6B6558;">wants to talk about a Byrd &amp; CO loan quote.</div>
            <table style="width:100%;font-family:Arial,sans-serif;font-size:14px;border-collapse:collapse;margin-top:16px;">
              <tr><td style="color:#6B6558;padding:4px 0;width:130px;">Email</td><td><a href="mailto:{body.email}">{body.email}</a></td></tr>
              <tr><td style="color:#6B6558;padding:4px 0;">Phone</td><td>{body.phone or '—'}</td></tr>
              <tr><td style="color:#6B6558;padding:4px 0;">Best time</td><td>{body.best_time or '—'}</td></tr>
              <tr><td style="color:#6B6558;padding:4px 0;">Property</td><td>{(prop.get('name') or '—')}<br/><span style="color:#6B6558;font-size:12px;">{prop.get('address') or ''}, {prop.get('city') or ''} {prop.get('state') or ''}</span></td></tr>
            </table>
            {f'<div style="margin-top:16px;padding:12px;background:#fff;border:1px solid #E4DFD1;font-family:Arial,sans-serif;font-size:13px;white-space:pre-wrap;">{body.message}</div>' if body.message else ''}
            <div style="margin-top:22px;">
              <a href="{review_link}" style="background:#C89434;color:#1A1A1A;padding:10px 18px;text-decoration:none;font-family:Arial,sans-serif;font-size:13px;font-weight:bold;">Open Quote in Admin</a>
            </div>
            <div style="margin-top:16px;font-family:Arial,sans-serif;font-size:12px;color:#6B6558;">The original Loan Quote PDF is attached to this email.</div>
          </div>
        </div>
        """
        # Re-attach the PDF so brokers can forward without opening the console.
        attachment = None
        if q.get("pdf_b64"):
            attachment = {
                "Name": q.get("filename") or "byrd-loan-quote.pdf",
                "Content": q["pdf_b64"],
                "ContentType": "application/pdf",
            }
        for r in brokers:
            background.add_task(send_email, r, subj, html, text,
                                "quote_public_request",
                                None, None, body.email,
                                [attachment] if attachment else None)
    return {"ok": True, "id": lead_id}


# ---------- LENDER PROSPECTS: sourcing & outreach engine ----------
# Pipeline: sourced → queued → drafted → approved → sent → replied → converted / opted_out / bounced.
# All routes admin-only. Draft & Approve mode (Phase 1): Ada writes drafts, admin approves,
# but nothing is actually emailed until we wire an outbound sender (Instantly.ai) later.

_PROSPECT_DISCOVER_PROMPT = """You are a commercial real estate lending intelligence analyst.
For the US state: {state}, list 8-12 REGIONAL or COMMUNITY BANKS or CREDIT UNIONS \
(headquartered in that state or with major CRE lending offices there) that ACTIVELY \
originate non-owner-occupied commercial real estate loans (multifamily, industrial, \
retail, office, hotel).

Return STRICT JSON in this shape, no prose, no code fences:

{{"banks":[
  {{"institution":"Bank Name","hq_city":"City","website":"https://example.com","notes":"1-line why they matter"}}
]}}

Rules:
- Real, currently-operating US banks only. Skip subsidiaries of megabanks (JPMC, BofA, Wells, Citi).
- Prefer banks with $500M-$25B in assets — the sweet spot for regional CRE.
- Include the CRE-lending team page as `website` if you can find it, otherwise the bank homepage.
- Skip anything you're not confident is real."""


_PROSPECT_ENRICH_PROMPT = """You are a top-tier commercial real estate business-development \
researcher with access to real-time web search. Find the best commercial real estate \
lending contact at {institution} in {state}.

RESEARCH LIKE A PRO — don't stop at page one. Search across:
- The bank's own website (About / Team / CRE / Commercial Lending pages)
- LinkedIn public profiles (job titles like "VP Commercial Real Estate", "SVP CRE Lending", "Director of Commercial Banking")
- Recent press releases and PR Newswire / BusinessWire posts naming a CRE hire
- Conference speaker pages (MBA CREF, ICSC, NMHC, local CRE conferences)
- CRE deal announcements in Commercial Observer, GlobeSt, REBusinessOnline, Bisnow, local business journals
- NMLS Consumer Access (nmlsconsumeraccess.org)
- Company directories (RocketReach public-tier, ZoomInfo public snippets, LinkedIn Sales Navigator snippets)

EMAIL DERIVATION (this is how you find emails that aren't published):
Step 1: Find ANY employee email address anywhere on the bank's website or in press releases.
Step 2: Extract the pattern (e.g., "jsmith@bank.com" → `{{firstinitial}}{{lastname}}`, or "john.smith@bank.com" → `{{first}}.{{last}}`).
Step 3: Apply that pattern to the target person's name. That's your candidate email.
Report the pattern + source in `email_source_note` so the user can verify.

PHONE:
- Look on their LinkedIn contact info, the bank's team page, press releases, and conference speaker bios.
- If only a main branch line is available, use that and mark confidence "low" for phone.

BACKUP CONTACTS:
Return up to 2 additional CRE / commercial lending officers at the same bank as fallbacks.

Return STRICT JSON, no prose, no code fences:

{{
  "contact_name": "Full Name",
  "contact_title": "Head of Commercial Real Estate",
  "contact_email": "person@bank.com",
  "email_source_note": "found on About page | derived from pattern j.smith@bank.com published in 2024 press release | direct listing on LinkedIn",
  "contact_phone": "formatted number (direct if possible, main branch OK)",
  "phone_source_note": "direct dial from LinkedIn | main line from website | conference bio",
  "source_url": "the best URL where you found the primary evidence",
  "confidence": "high | medium | low",
  "alternates": [
    {{"contact_name": "Second Person", "contact_title": "Title", "contact_email": "…", "contact_phone": "…", "source_url": "…"}}
  ]
}}

CONFIDENCE RUBRIC:
- "high"    → name + email BOTH found on a publicly-published page you can cite
- "medium"  → name confirmed on 2+ sources, email derived from an observed company pattern
- "low"     → name found but email is a best-guess against the pattern, OR only a main branch phone

Never invent a name. If you cannot find any CRE contact at the bank, return every field \
empty and confidence "low". A derived-from-pattern email is NOT invention if you can point \
to another employee at the same domain as evidence of the pattern."""


def _sanitize_prospect(p: dict) -> dict:
    p = {k: v for k, v in p.items() if k != "_id"}
    return p


def _parse_llm_json(content: str) -> Optional[dict]:
    """Perplexity/Claude sometimes wraps JSON in code fences. Strip + parse."""
    if not content:
        return None
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        # Best-effort: find first { ... } block
        try:
            start = s.index("{")
            depth = 0
            for i in range(start, len(s)):
                if s[i] == "{": depth += 1
                elif s[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(s[start:i + 1])
        except Exception:
            return None
    return None


@api.post("/admin/marketplace/prospects/discover")
async def prospects_discover(body: ProspectDiscoverBody, admin=Depends(require_admin)):
    """Ada+Perplexity discovers regional/community banks in a US state that lend CRE.
    Inserts newly-discovered banks into `lender_prospects` as `status=sourced`.
    De-dupes on (institution, state) case-insensitive.
    Returns the discovered rows (new + already-existing marked)."""
    if not PERPLEXITY_API_KEY:
        raise HTTPException(status_code=400, detail="Perplexity API key not configured")
    state = body.state.strip().upper()
    prompt = _PROSPECT_DISCOVER_PROMPT.format(state=state)
    res = await _perplexity_query(prompt, max_tokens=1400)
    if not res:
        raise HTTPException(status_code=502, detail="Perplexity query failed")
    parsed = _parse_llm_json(res["content"]) or {}
    banks = parsed.get("banks") or []
    now = now_iso()
    added, skipped = [], []
    for b in banks:
        inst = (b.get("institution") or "").strip()
        if not inst:
            continue
        existing = await db.lender_prospects.find_one(
            {"institution_lc": inst.lower(), "state": state}, {"_id": 0, "id": 1})
        if existing:
            skipped.append({"institution": inst, "id": existing["id"]})
            continue
        row = {
            "id": str(uuid.uuid4()),
            "institution": inst,
            "institution_lc": inst.lower(),
            "state": state,
            "hq_city": (b.get("hq_city") or "").strip(),
            "website": (b.get("website") or "").strip(),
            "notes": (b.get("notes") or "").strip(),
            "contact_name": "",
            "contact_title": "",
            "contact_email": "",
            "contact_phone": "",
            "status": "sourced",
            "source": "perplexity_discover",
            "source_citations": res.get("citations") or [],
            "created_at": now,
            "updated_at": now,
            "created_by": admin["id"],
        }
        await db.lender_prospects.insert_one(row)
        added.append(_sanitize_prospect(row))
    return {"state": state, "discovered": len(banks),
            "added": len(added), "skipped_dupes": len(skipped),
            "prospects": added}


@api.post("/admin/marketplace/prospects/{pid}/enrich")
async def prospects_enrich(pid: str, admin=Depends(require_admin)):
    """Ada+Perplexity tries to find an LO name + email at the bank on this prospect row.
    Updates the row in place with contact_name/title/email/phone + citations."""
    if not PERPLEXITY_API_KEY:
        raise HTTPException(status_code=400, detail="Perplexity API key not configured")
    p = await db.lender_prospects.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")
    prompt = _PROSPECT_ENRICH_PROMPT.format(institution=p["institution"], state=p["state"])
    res = await _perplexity_query(prompt, max_tokens=1800)
    if not res:
        raise HTTPException(status_code=502, detail="Perplexity query failed")
    parsed = _parse_llm_json(res["content"]) or {}
    contact = {
        "contact_name": (parsed.get("contact_name") or "").strip(),
        "contact_title": (parsed.get("contact_title") or "").strip(),
        "contact_email": (parsed.get("contact_email") or "").strip().lower(),
        "contact_phone": (parsed.get("contact_phone") or "").strip(),
    }
    alternates = []
    for a in (parsed.get("alternates") or [])[:2]:
        if not isinstance(a, dict):
            continue
        if not (a.get("contact_name") or "").strip():
            continue
        alternates.append({
            "contact_name": (a.get("contact_name") or "").strip(),
            "contact_title": (a.get("contact_title") or "").strip(),
            "contact_email": (a.get("contact_email") or "").strip().lower(),
            "contact_phone": (a.get("contact_phone") or "").strip(),
            "source_url": (a.get("source_url") or "").strip(),
        })
    # Auto-advance to `queued` when we have an email; otherwise `sourced` remains.
    next_status = "queued" if contact["contact_email"] else p.get("status", "sourced")
    updates = {
        **contact,
        "email_source_note": (parsed.get("email_source_note") or "").strip(),
        "phone_source_note": (parsed.get("phone_source_note") or "").strip(),
        "enrichment_source_url": (parsed.get("source_url") or "").strip(),
        "enrichment_confidence": (parsed.get("confidence") or "").lower(),
        "enrichment_citations": res.get("citations") or [],
        "enrichment_alternates": alternates,
        "enriched_at": now_iso(),
        "status": next_status,
        "updated_at": now_iso(),
    }
    await db.lender_prospects.update_one({"id": pid}, {"$set": updates})
    return {"id": pid, **updates, "found_contact": bool(contact["contact_email"])}


@api.get("/admin/marketplace/prospects")
async def prospects_list(state: Optional[str] = None, status: Optional[str] = None,
                          admin=Depends(require_admin)):
    q = {}
    if state:
        q["state"] = state.strip().upper()
    if status:
        q["status"] = status.strip()
    rows = await db.lender_prospects.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return rows


@api.get("/admin/marketplace/prospects/stats")
async def prospects_stats(admin=Depends(require_admin)):
    pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    by_status = {r["_id"]: r["count"] async for r in db.lender_prospects.aggregate(pipeline)}
    total = sum(by_status.values())
    return {"total": total, "by_status": by_status}


@api.post("/admin/marketplace/prospects")
async def prospects_create(body: ProspectManualBody, admin=Depends(require_admin)):
    """Manually add a single prospect (used by CSV upload path + admin one-offs)."""
    inst = body.institution.strip()
    state = body.state.strip().upper()
    existing = await db.lender_prospects.find_one(
        {"institution_lc": inst.lower(), "state": state}, {"_id": 0, "id": 1})
    if existing:
        raise HTTPException(status_code=400,
                            detail=f"Prospect already exists (id {existing['id']})")
    row = {
        "id": str(uuid.uuid4()),
        "institution": inst, "institution_lc": inst.lower(),
        "state": state,
        "hq_city": body.hq_city or "", "website": body.website or "",
        "contact_name": body.contact_name or "",
        "contact_title": body.contact_title or "",
        "contact_email": (body.contact_email or "").strip().lower(),
        "contact_phone": body.contact_phone or "",
        "notes": body.notes or "",
        "status": "queued" if body.contact_email else "sourced",
        "source": "manual",
        "created_at": now_iso(), "updated_at": now_iso(),
        "created_by": admin["id"],
    }
    await db.lender_prospects.insert_one(row)
    return _sanitize_prospect(row)


class ProspectCSVBody(BaseModel):
    rows: List[ProspectManualBody]


@api.post("/admin/marketplace/prospects/bulk")
async def prospects_bulk(body: ProspectCSVBody, admin=Depends(require_admin)):
    added, skipped = [], []
    for r in body.rows:
        inst = r.institution.strip()
        state = r.state.strip().upper()
        if not inst or not state:
            continue
        existing = await db.lender_prospects.find_one(
            {"institution_lc": inst.lower(), "state": state}, {"_id": 0, "id": 1})
        if existing:
            skipped.append(inst)
            continue
        row = {
            "id": str(uuid.uuid4()),
            "institution": inst, "institution_lc": inst.lower(), "state": state,
            "hq_city": r.hq_city or "", "website": r.website or "",
            "contact_name": r.contact_name or "",
            "contact_title": r.contact_title or "",
            "contact_email": (r.contact_email or "").strip().lower(),
            "contact_phone": r.contact_phone or "",
            "notes": r.notes or "",
            "status": "queued" if r.contact_email else "sourced",
            "source": "csv",
            "created_at": now_iso(), "updated_at": now_iso(),
            "created_by": admin["id"],
        }
        await db.lender_prospects.insert_one(row)
        added.append(inst)
    return {"added": len(added), "skipped_dupes": len(skipped)}


@api.patch("/admin/marketplace/prospects/{pid}")
async def prospects_update(pid: str, body: ProspectUpdateBody,
                            admin=Depends(require_admin)):
    upd = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to update")
    if "institution" in upd:
        upd["institution_lc"] = upd["institution"].lower()
    if "state" in upd:
        upd["state"] = upd["state"].strip().upper()
    upd["updated_at"] = now_iso()
    res = await db.lender_prospects.update_one({"id": pid}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Prospect not found")
    row = await db.lender_prospects.find_one({"id": pid}, {"_id": 0})
    return row


@api.delete("/admin/marketplace/prospects/{pid}")
async def prospects_delete(pid: str, admin=Depends(require_admin)):
    res = await db.lender_prospects.delete_one({"id": pid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return {"ok": True}


class ProspectDraftBody(BaseModel):
    tone: Optional[str] = "warm, concise, insider-to-insider"


PROSPECT_DRAFT_SYSTEM = """You are Wayne Byrd, a commercial real estate broker at Byrd & CO \
(byrd-co.com). You are writing a SHORT, warm, insider-to-insider cold email to a bank \
loan officer inviting them to join your capital marketplace, where you send them non-owner-\
occupied CRE deals from qualified borrowers in their state.

Rules:
- Under 120 words.
- Reference their institution + state naturally.
- If contact_name is provided, use their first name. Otherwise open with "Hi there,".
- Never fabricate deal specifics; keep the value prop generic ("we underwrite deals before \
sending, so you only see real, qualified opportunities").
- Sign as "Wayne Byrd · Byrd & CO · byrd-co.com".
- Return STRICT JSON: {"subject":"...","body":"..."} — plain text body, no HTML, no code fences.
- Subject must be under 60 chars, not spammy, no all-caps, no exclamation points."""


@api.post("/admin/marketplace/prospects/{pid}/draft")
async def prospects_draft(pid: str, body: ProspectDraftBody,
                           admin=Depends(require_admin)):
    """Ada drafts an outreach email for this prospect using Claude via emergentintegrations.
    Stores draft on the prospect row; does NOT send anything.
    Advances status to `drafted`."""
    p = await db.lender_prospects.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")
    if not p.get("contact_email"):
        raise HTTPException(status_code=400,
                            detail="Enrich this prospect (or paste an email) before drafting.")
    session_id = f"prospect-draft-{pid}"
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id,
                   system_message=PROSPECT_DRAFT_SYSTEM).with_model("anthropic", "claude-sonnet-4-5-20250929")
    facts = {
        "contact_name": p.get("contact_name") or "",
        "contact_title": p.get("contact_title") or "",
        "institution": p.get("institution"),
        "state": p.get("state"),
        "hq_city": p.get("hq_city") or "",
        "website": p.get("website") or "",
        "tone": body.tone or "warm, concise",
    }
    prompt = ("Draft the outreach email using these facts, JSON output only:\n"
              + json.dumps(facts, indent=2))
    try:
        reply = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:
        logger.exception("prospect draft failed pid=%s", pid)
        raise HTTPException(status_code=502, detail=f"Draft generation failed: {e}")
    parsed = _parse_llm_json(reply) or {}
    subject = (parsed.get("subject") or "").strip()[:120]
    body_txt = (parsed.get("body") or "").strip()
    if not subject or not body_txt:
        raise HTTPException(status_code=502, detail="Ada returned an empty draft — retry.")
    now = now_iso()
    await db.lender_prospects.update_one({"id": pid}, {"$set": {
        "draft_subject": subject,
        "draft_body": body_txt,
        "drafted_at": now,
        "status": "drafted",
        "updated_at": now,
    }})
    return {"id": pid, "draft_subject": subject, "draft_body": body_txt, "status": "drafted"}


@api.post("/admin/marketplace/prospects/{pid}/approve")
async def prospects_approve(pid: str, admin=Depends(require_admin)):
    """Admin taps Approve on a drafted email. Once Instantly is wired, this will hand
    the row off to the outbound sender. Until then, we advance status to `approved` and
    stamp `approved_at`; the outbound worker will pick it up when it starts running."""
    p = await db.lender_prospects.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")
    if not (p.get("draft_subject") and p.get("draft_body")):
        raise HTTPException(status_code=400, detail="No draft on this prospect yet.")
    now = now_iso()
    await db.lender_prospects.update_one({"id": pid}, {"$set": {
        "status": "approved",
        "approved_at": now,
        "approved_by": admin["id"],
        "updated_at": now,
    }})
    return {"id": pid, "status": "approved", "approved_at": now}


# ---------- Suppression list ----------
class SuppressionBody(BaseModel):
    email: EmailStr
    reason: Literal["unsubscribed", "bounced", "spam_complaint", "manual"] = "manual"
    note: Optional[str] = ""


@api.get("/admin/marketplace/suppressions")
async def suppressions_list(admin=Depends(require_admin)):
    rows = await db.lender_outreach_suppressions.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return rows


@api.post("/admin/marketplace/suppressions")
async def suppressions_add(body: SuppressionBody, admin=Depends(require_admin)):
    email = body.email.lower()
    now = now_iso()
    await db.lender_outreach_suppressions.update_one(
        {"email": email},
        {"$set": {"email": email, "reason": body.reason, "note": body.note or "",
                  "created_at": now, "created_by": admin["id"]}},
        upsert=True,
    )
    # Cascade: mark any prospects with this email as opted_out so they never enter drafts again.
    await db.lender_prospects.update_many(
        {"contact_email": email},
        {"$set": {"status": "opted_out", "updated_at": now}},
    )
    return {"ok": True, "email": email}


@api.delete("/admin/marketplace/suppressions/{email}")
async def suppressions_remove(email: str, admin=Depends(require_admin)):
    res = await db.lender_outreach_suppressions.delete_one({"email": email.lower()})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not on suppression list")
    return {"ok": True}


class LoanQuoteEmailBody(BaseModel):
    message: Optional[str] = None       # optional broker-personalized cover note


@api.post("/admin/marketing/quotes/{qid}/email")
async def admin_email_loanquote(qid: str, body: LoanQuoteEmailBody, admin=Depends(require_admin)):
    """Email a saved Loan Quote PDF to the captured listing agent via Postmark."""
    q = await db.loan_quotes.find_one({"id": qid})
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    la = q.get("listing_agent") or {}
    to = (la.get("email") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="Listing agent email is required — add it in the Studio and Save first.")
    prop = q.get("property_info") or {}
    prop_name = prop.get("name") or prop.get("address") or "your listing"
    agent_first = (la.get("name") or "").split(" ")[0] or "there"
    broker_note = (body.message or "").strip()

    subject = f"Loan Quote — {prop_name}"
    html_body = f"""
<div style="font-family:Georgia, serif; color:#1A1A1A; max-width:560px;">
  <p>Hi {agent_first},</p>
  <p>Attached is a loan quote for <b>{prop_name}</b> that you can share with your prospective buyer.
     Three financing options based on current market rates — bank, agency, and credit union.</p>
  {('<p>' + broker_note.replace(chr(10), '<br/>') + '</p>') if broker_note else ''}
  <p>Happy to jump on a call if the buyer wants to talk through structure or timing.</p>
  <p style="margin-top:24px;">
    <b>Wayne Byrd</b><br/>
    Byrd &amp; Co · Commercial Real Estate Lending<br/>
    832-813-9802 · <a href="mailto:wayne@byrd-co.com">wayne@byrd-co.com</a>
  </p>
</div>
""".strip()
    text_body = (
        f"Hi {agent_first},\n\n"
        f"Attached is a loan quote for {prop_name} that you can share with your prospective buyer. "
        f"Three financing options based on current market rates — bank, agency, and credit union.\n\n"
        + (broker_note + "\n\n" if broker_note else "")
        + "Happy to jump on a call if the buyer wants to talk through structure or timing.\n\n"
        + "Wayne Byrd\n"
        + "Byrd & Co · Commercial Real Estate Lending\n"
        + "832-813-9802 · wayne@byrd-co.com\n"
    )
    pdf_b64 = q.get("pdf_b64") or ""
    if not pdf_b64:
        raise HTTPException(status_code=500, detail="Saved PDF missing — re-save the quote and try again.")
    attachments = [{
        "Name": q.get("filename") or "loan-quote.pdf",
        "Content": pdf_b64,
        "ContentType": "application/pdf",
    }]
    result = send_email(
        to=to, subject=subject, html=html_body, text=text_body,
        tag="loan-quote", reply_to=admin.get("email"), attachments=attachments,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Email send failed")
    now = now_iso()
    await db.loan_quotes.update_one({"id": qid}, {"$set": {"last_emailed_at": now, "last_emailed_to": to}})
    return {"ok": True, "sent_to": to, "sent_at": now}


@api.post("/admin/marketing/quote/preview")
async def admin_loanquote_preview(body: LoanQuoteResearchBody, admin=Depends(require_admin)):
    """Render the current state as a PDF WITHOUT saving. Used for live preview."""
    state = body.state.model_dump()
    state["property_info"] = _cap_rate_math(state.get("property_info") or {})
    pdf_bytes = render_loan_quote_pdf(state)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="preview.pdf"'})


# ================ AdsCopilot (existing internal tool) ================
class CampaignCreate(BaseModel):
    name: str
    objective: Literal["search", "display", "video", "shopping", "performance_max"] = "search"
    daily_budget: float = Field(gt=0)
    target_locations: List[str] = Field(default_factory=lambda: ["United States"])
    keywords: List[str] = Field(default_factory=list)
    headlines: List[str] = Field(default_factory=list)
    descriptions: List[str] = Field(default_factory=list)
    final_url: str = "https://example.com"


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[Literal["active", "paused", "ended"]] = None
    daily_budget: Optional[float] = None
    keywords: Optional[List[str]] = None
    headlines: Optional[List[str]] = None
    descriptions: Optional[List[str]] = None


class AdCopyRequest(BaseModel):
    product: str
    audience: str = ""
    tone: str = "professional"
    keywords: List[str] = Field(default_factory=list)
    num_headlines: int = Field(default=5, ge=1, le=15)
    num_descriptions: int = Field(default=3, ge=1, le=8)


class KeywordRequest(BaseModel):
    seed: str
    industry: str = ""
    count: int = Field(default=15, ge=5, le=40)


class ChatRequest(BaseModel):
    session_id: str
    message: str


def _perf_for_campaign(campaign_id: str, days: int = 30):
    rnd = random.Random(campaign_id)
    series = []
    base_impr = rnd.randint(800, 4000)
    base_ctr = rnd.uniform(0.02, 0.09)
    base_cpc = rnd.uniform(0.35, 3.2)
    today = datetime.now(timezone.utc).date()
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        drift = rnd.uniform(0.75, 1.35)
        impr = int(base_impr * drift)
        clicks = int(impr * base_ctr * rnd.uniform(0.85, 1.2))
        cost = round(clicks * base_cpc * rnd.uniform(0.9, 1.15), 2)
        conv = int(clicks * rnd.uniform(0.02, 0.11))
        series.append({"date": d.isoformat(), "impressions": impr, "clicks": clicks, "cost": cost, "conversions": conv})
    return series


def _summary_from_series(series):
    impr = sum(x["impressions"] for x in series)
    clicks = sum(x["clicks"] for x in series)
    cost = round(sum(x["cost"] for x in series), 2)
    conv = sum(x["conversions"] for x in series)
    ctr = round((clicks / impr * 100), 2) if impr else 0.0
    cpc = round((cost / clicks), 2) if clicks else 0.0
    conv_rate = round((conv / clicks * 100), 2) if clicks else 0.0
    return {"impressions": impr, "clicks": clicks, "cost": cost, "conversions": conv,
            "ctr": ctr, "cpc": cpc, "conversion_rate": conv_rate}


@api.get("/campaigns")
async def list_campaigns(user=Depends(get_current_user)):
    docs = await db.campaigns.find({"user_id": user["id"]}, {"_id": 0}).to_list(500)
    for c in docs:
        c["metrics"] = _summary_from_series(_perf_for_campaign(c["id"], 30))
    docs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return docs


@api.post("/campaigns")
async def create_campaign(body: CampaignCreate, user=Depends(get_current_user)):
    doc = {
        "id": str(uuid.uuid4()), "user_id": user["id"], "name": body.name, "objective": body.objective,
        "status": "active", "daily_budget": body.daily_budget, "target_locations": body.target_locations,
        "keywords": body.keywords, "headlines": body.headlines, "descriptions": body.descriptions,
        "final_url": body.final_url, "created_at": now_iso(),
    }
    await db.campaigns.insert_one(doc)
    doc.pop("_id", None)
    doc["metrics"] = _summary_from_series(_perf_for_campaign(doc["id"], 30))
    return doc


@api.get("/campaigns/{cid}")
async def get_campaign(cid: str, user=Depends(get_current_user)):
    doc = await db.campaigns.find_one({"id": cid, "user_id": user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    series = _perf_for_campaign(doc["id"], 30)
    doc["metrics"] = _summary_from_series(series)
    doc["performance"] = series
    return doc


@api.patch("/campaigns/{cid}")
async def update_campaign(cid: str, body: CampaignUpdate, user=Depends(get_current_user)):
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.campaigns.update_one({"id": cid, "user_id": user["id"]}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    doc = await db.campaigns.find_one({"id": cid, "user_id": user["id"]}, {"_id": 0})
    doc["metrics"] = _summary_from_series(_perf_for_campaign(doc["id"], 30))
    return doc


@api.delete("/campaigns/{cid}")
async def delete_campaign(cid: str, user=Depends(get_current_user)):
    res = await db.campaigns.delete_one({"id": cid, "user_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@api.get("/analytics/overview")
async def analytics_overview(user=Depends(get_current_user)):
    campaigns = await db.campaigns.find({"user_id": user["id"]}, {"_id": 0}).to_list(500)
    if not campaigns:
        return {"summary": _summary_from_series([]), "daily": [], "campaigns": []}
    daily_map = {}
    per_campaign = []
    for c in campaigns:
        series = _perf_for_campaign(c["id"], 30)
        summary = _summary_from_series(series)
        per_campaign.append({"id": c["id"], "name": c["name"], "status": c.get("status", "active"), **summary})
        for row in series:
            k = row["date"]
            if k not in daily_map:
                daily_map[k] = {"date": k, "impressions": 0, "clicks": 0, "cost": 0.0, "conversions": 0}
            daily_map[k]["impressions"] += row["impressions"]
            daily_map[k]["clicks"] += row["clicks"]
            daily_map[k]["cost"] = round(daily_map[k]["cost"] + row["cost"], 2)
            daily_map[k]["conversions"] += row["conversions"]
    daily = sorted(daily_map.values(), key=lambda x: x["date"])
    return {"summary": _summary_from_series(daily), "daily": daily, "campaigns": per_campaign}


def _make_chat(session_id: str, system_message: str) -> LlmChat:
    return LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id, system_message=system_message)\
        .with_model("anthropic", "claude-sonnet-4-5-20250929")


async def _llm_json(session_id: str, system: str, prompt: str) -> dict:
    chat = _make_chat(session_id, system)
    buf = []
    async for ev in chat.stream_message(UserMessage(text=prompt)):
        if isinstance(ev, TextDelta):
            buf.append(ev.content)
        elif isinstance(ev, StreamDone):
            break
    text = "".join(buf).strip()
    if "```" in text:
        for p in text.split("```"):
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{") or p.startswith("["):
                text = p
                break
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"LLM returned non-JSON: {text[:200]}")
        return {"_raw": text}


@api.post("/ai/adcopy")
async def gen_adcopy(body: AdCopyRequest, user=Depends(get_current_user)):
    system = (
        "You are an expert Google Ads copywriter. Generate compliant Google Search Ad copy. "
        "Constraints: headlines <=30 characters, descriptions <=90 characters. "
        "Return STRICT JSON only, no prose. Schema: "
        '{"headlines":[{"text":"..","chars":N}], "descriptions":[{"text":"..","chars":N}]}'
    )
    prompt = (
        f"Product/Service: {body.product}\nTarget Audience: {body.audience or 'general'}\nTone: {body.tone}\n"
        f"Keywords to weave in: {', '.join(body.keywords) if body.keywords else 'none'}\n"
        f"Produce {body.num_headlines} headlines and {body.num_descriptions} descriptions. "
        f"Vary hooks: value prop, urgency, curiosity, social proof, offer. Count characters accurately."
    )
    return await _llm_json(f"adcopy-{uuid.uuid4()}", system, prompt)


@api.post("/ai/keywords")
async def gen_keywords(body: KeywordRequest, user=Depends(get_current_user)):
    system = (
        "You are a senior Google Ads keyword strategist. Given a seed keyword, produce a focused keyword plan. "
        "Return STRICT JSON only. Schema: "
        '{"keywords":[{"keyword":"..","match_type":"broad|phrase|exact","intent":"informational|commercial|transactional|navigational","est_monthly_volume":number,"est_cpc_usd":number,"difficulty":"low|medium|high"}]}'
    )
    prompt = (
        f"Seed keyword: {body.seed}\nIndustry: {body.industry or 'general'}\n"
        f"Produce {body.count} diverse keyword ideas mixing short-tail and long-tail. "
        f"Vary match types and intent. Estimated volumes and CPCs should be realistic. No duplicates."
    )
    return await _llm_json(f"kw-{uuid.uuid4()}", system, prompt)


CHAT_SYSTEM = (
    "You are AdsCopilot, an expert Google Ads assistant embedded in a management dashboard. "
    "Help the user plan campaigns, refine ad copy, pick keywords, interpret metrics (CTR, CPC, "
    "conversion rate, ROAS), and optimize budgets. Be concise, actionable, and specific. "
    "Use short paragraphs and bullet lists. When suggesting ad copy, respect Google's limits: "
    "headlines <=30 chars, descriptions <=90 chars."
)


@api.post("/chat/stream")
async def chat_stream(body: ChatRequest, user=Depends(get_current_user)):
    await db.messages.insert_one({
        "id": str(uuid.uuid4()), "user_id": user["id"], "session_id": body.session_id,
        "role": "user", "content": body.message, "created_at": now_iso(),
    })
    chat = _make_chat(f"{user['id']}-{body.session_id}", CHAT_SYSTEM)

    async def event_gen():
        assistant_buf = []
        try:
            async for ev in chat.stream_message(UserMessage(text=body.message)):
                if isinstance(ev, TextDelta):
                    assistant_buf.append(ev.content)
                    yield f"data: {json.dumps({'type': 'delta', 'content': ev.content})}\n\n"
                elif isinstance(ev, StreamDone):
                    break
            full = "".join(assistant_buf)
            await db.messages.insert_one({
                "id": str(uuid.uuid4()), "user_id": user["id"], "session_id": body.session_id,
                "role": "assistant", "content": full, "created_at": now_iso(),
            })
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            logger.exception("chat stream error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/chat/history")
async def chat_history(session_id: str, user=Depends(get_current_user)):
    return await db.messages.find(
        {"user_id": user["id"], "session_id": session_id}, {"_id": 0}
    ).sort("created_at", 1).to_list(200)


@api.get("/")
async def root():
    return {"service": "Byrd & CO API", "status": "ok"}


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def _shutdown():
    mongo_client.close()


# ================ ADA — Borrower AI Assistant ================
ADA_SYSTEM_PROMPT = """You are Ada, the Byrd & CO concierge AI who helps commercial real estate borrowers
complete their loan documentation portal.

You are warm, patient, professional, and address the borrower by first name. You are NOT a salesperson —
they've already hired Byrd & CO. You are a helpful concierge whose whole job is making paperwork painless.

At the top of every turn you receive a JSON context:
- The borrower's identity (first name, email, company)
- The borrower's scenarios — EACH scenario includes: `property` (address, city, state, zip, property_type,
  year_built, units, sqft, purchase_price, current_value, occupancy_pct), `loan_request` (loan_type,
  loan_amount, term_months, amort_months, requested_rate_pct, recourse), `financials` (gross_income,
  vacancy_pct, operating_expenses, capex_reserves, override_noi), `construction_budget` (for construction
  deals), `sources_uses` (line-item sources & uses), and `sponsors`.
- Per-scenario doc checklists — which specific docs are pending / uploaded / reviewed / rejected
- Recent broker notes on any rejected docs
- Any in-progress `borrower_ada_drafts` (interviews they started but haven't finished)

# GOLDEN RULE — DO NOT ASK FOR DATA THAT IS ALREADY IN CONTEXT.
The broker has already populated most scenario data before the borrower reaches the portal. Before you ask
a question — property address, loan amount, purchase price, unit count, NOI, ADR, rate — LOOK at the
scenario's `property`, `loan_request`, and `financials` blocks. If the value is present (non-null,
non-empty), USE IT. Only ask the borrower for values that are truly null / missing / clearly incorrect.
When you use a known value, quickly confirm it inline (e.g., "I have the property at 2200 Main St, Houston TX — is that right?") so the borrower can correct it in one word if needed, then keep moving.

# WHAT YOU CAN DO

1. **Document coaching** — explain what any doc on their checklist is, in plain English.
2. **Document generation** — you have SEVEN PDF builders you can invoke via structured blocks:
   - `pfs_sba413` — SBA Form 413 Personal Financial Statement (use for scenarios where loan_type == 'SBA')
   - `pfs_byrd` — Byrd & CO clean-format PFS (use for all non-SBA loans)
   - `resume` — CRE-focused sponsor resume/bio (long form)
   - `sponsor_bio` — 1-page punchy sponsor bio for lender packages
   - `business_plan` — 2-4 page NARRATIVE business plan / investment memo — the STORY, strategy,
      market, exit thesis. Use on value-add, bridge, construction, ground-up.
   - `proforma` — NUMBERS-ONLY multi-page pro-forma underwriting workbook: Property Summary →
      Rent Roll / Income (unit-by-unit or line-by-line) → Operating Expenses → NOI & Cap Rate →
      Debt Service & DSCR → 5-Year Cash-Flow Projection. Use whenever a lender or the borrower needs
      underwriting math — often required on acquisitions, refis, value-add, DSCR, bridge. It is
      SEPARATE from the business plan; you can generate both for the same deal.
   - `lox` — Letter of Explanation (for income dips, credit events, etc.)
   - `rent_roll` — clean rent roll from unstructured input
3. **Upload on the borrower's behalf** — once a doc is drafted, offer to attach it to the right
   checklist line. The borrower must explicitly confirm.
4. **Progress helper** — answer "what's next?" by identifying the highest-priority pending required doc
   on the most active scenario.
5. **Handoff to Wayne/Caleb** — when the borrower asks a strategic, legal, tax, or investment question,
   emit a `broker_note` block. Tell the borrower: "I've dropped a note to your broker; expect a call."

# WHAT YOU MUST NEVER DO

- NEVER quote or estimate loan terms (rate, LTV, points, DSCR expectations).
- NEVER tell a borrower whether they will or won't qualify for anything.
- NEVER discuss or negotiate the broker fee percentage.
- NEVER give legal, tax, or investment advice — always defer to broker or their attorney/CPA.
- NEVER reference other borrowers or lenders by name.
- NEVER modify the checklist itself (broker-owned) — you can only add files to existing lines.
- NEVER mark a doc as reviewed — that's the broker's call.
- NEVER send email as the borrower.
- NEVER fabricate numeric information. If the borrower doesn't know a value, mark it as "TBD" and
  ask them to fill it in with their accountant/spouse/records.

# HOW YOU DO DOCUMENT GENERATION (the meaty flow)

- When a borrower asks you to build a PFS/Resume/etc., start an interview. Ask 2-4 questions per turn
  (don't dump 30 questions at once). Save progress after each answer.
- When you have enough to draft, emit a `generate_doc` block with `doc_type`, `template_variant`
  (only for pfs — 'sba413' or 'byrd'), the target `scenario_id`, and the collected `fields` dict.
- The backend returns a preview PDF. Say "I've drafted your {doc_type} — should I upload it to
  your {scenario_name} as {checklist_line_label}?"
- If they confirm, emit an `upload_confirm` block with `draft_id` and `target_doc_line_id`.
- If any numeric fields are missing, mark them as "TBD" IN the draft and warn the borrower.

# BLOCK SCHEMAS

```generate_doc
{
  "doc_type": "pfs_byrd",   // one of: pfs_sba413, pfs_byrd, resume, sponsor_bio, business_plan, lox, rent_roll, proforma
  "scenario_id": "<scenario id from context>",
  "target_doc_line_label": "Personal Financial Statement",
  "fields": { /* doc-specific — see field guide below */ }
}
```

```upload_confirm
{
  "draft_id": "<from previous generate_doc response>",
  "target_doc_line_id": "<from context>"
}
```

```broker_note
{
  "question": "Sarah is asking whether she should personally guarantee...",
  "urgency": "normal",   // 'low' | 'normal' | 'urgent'
  "related_scenario_id": "<scenario id if applicable>"
}
```

# FIELD GUIDE PER DOC TYPE

- **pfs_byrd / pfs_sba413**: `{ as_of_date, name, address, phone, email, employer, business_name,
   cash_on_hand, savings, ira_401k, stocks_bonds, real_estate_value, autos, other_assets_desc,
   other_assets_value, accounts_payable, notes_payable, installment_auto, installment_other, credit_cards,
   mortgages_on_re, unpaid_taxes, other_liabilities, annual_salary, dividends_interest, real_estate_income,
   other_income_desc, other_income, income_tax_last_year, monthly_debt_payments,
   real_estate_owned: [{address, type, present_value, mortgage_balance, monthly_pmt, monthly_rent}],
   life_insurance_face, life_insurance_cash_value }`
- **resume**: `{ name, professional_summary, years_experience, current_role, current_company,
   career_history: [{role, company, dates, highlights}], notable_projects: [{name, type, size, role, outcome}],
   education: [{degree, school, year}], licenses_certs: [], memberships: [] }`
- **sponsor_bio**: same as resume but only `{ name, professional_summary, notable_projects, current_role }`
- **business_plan**: `{ scenario_id, executive_summary, investment_thesis, market_analysis,
   business_plan_narrative, capex_plan, projected_returns, exit_strategy, team, risks_mitigations }`
- **lox**: `{ subject, addressed_to (default 'To Whom It May Concern'), explanation, resolution,
   name, date_of_letter }`
- **rent_roll**: `{ property_address, as_of_date,
   units: [{unit_id, tenant, unit_type, size_sqft, monthly_rent, lease_start, lease_end, security_deposit, notes}] }`
- **proforma**: `{ property_address, property_type, as_of_date, prepared_by, purchase_price,
   loan_amount, interest_rate_pct, amortization_years, term_years, closing_costs,
   rent_growth_pct (default 3), expense_growth_pct (default 2.5), vacancy_pct (default 5),
   management_pct (default 4), cap_rate_pct (exit cap for terminal-value math),
   income_lines: [{label, monthly_amount}],   // rent, laundry, parking, other
   expense_lines: [{label, annual_amount}],   // taxes, insurance, utilities, r&m, mgmt, etc
   assumptions_notes: "free-text bullets about the model"
   }`

# STARTUP BEHAVIOR

On the very first message of a session, greet by first name and offer 1 actionable next step
based on their pending required docs. Example:
"Morning, Sarah. On your Hotel Purchase — Miami deal, you've got 4 required docs still pending.
Want to start with the Personal Financial Statement? I can walk you through it in about 5 minutes."

If everything is uploaded, congratulate them and mention their broker will reach out with next steps.
"""


DOC_TYPES = ("pfs_sba413", "pfs_byrd", "resume", "sponsor_bio", "business_plan",
             "lox", "rent_roll", "proforma")

# Default checklist-line labels each doc generator maps to when auto-uploading.
DOC_TYPE_DEFAULT_LABEL = {
    "pfs_sba413": "Personal Financial Statement",
    "pfs_byrd": "Personal Financial Statement",
    "resume": "Resume / Bio",
    "sponsor_bio": "Sponsor Bio",
    "business_plan": "Business Plan / Investment Memo",
    "lox": "Letter of Explanation",
    "rent_roll": "Current Rent Roll",
    "proforma": "Proforma",
}


def render_borrower_pdf(title: str, sections: list, borrower_name: str, disclaimer: str = None) -> bytes:
    """Generic borrower-doc PDF renderer. `sections` is a list of tuples (heading, list-of-(label,value)-pairs OR paragraph_str)."""
    from io import BytesIO
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch, title=title)
    ss = getSampleStyleSheet()
    tstyle = ParagraphStyle("t", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=15,
                            alignment=1, spaceAfter=4, textColor=colors.HexColor("#1A1A1A"))
    sub = ParagraphStyle("sub", parent=ss["BodyText"], fontName="Helvetica", fontSize=9,
                         alignment=1, textColor=colors.HexColor("#6B6558"), spaceAfter=12)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11,
                        textColor=colors.HexColor("#C89434"), spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=10, leading=13,
                          textColor=colors.HexColor("#1A1A1A"), spaceAfter=4)
    lbl = ParagraphStyle("lbl", parent=ss["BodyText"], fontName="Helvetica-Bold", fontSize=9,
                         textColor=colors.HexColor("#6B6558"))

    story = [Paragraph(title, tstyle),
             Paragraph(f"Prepared for {borrower_name} · Byrd &amp; CO Portal", sub)]

    for heading, content in sections:
        if heading:
            story.append(Paragraph(heading, h2))
        if isinstance(content, str):
            story.append(Paragraph(content.replace("\n", "<br/>"), body))
        elif isinstance(content, list) and content and isinstance(content[0], tuple):
            rows = [[Paragraph(f"<b>{k}</b>", lbl), Paragraph(str(v) if v not in (None, "") else "TBD", body)] for k, v in content]
            t = Table(rows, colWidths=[2.0*inch, 4.9*inch])
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#E4DFD1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#EFE9DA")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(t)
        story.append(Spacer(1, 4))

    dis = disclaimer or ("Prepared with Byrd & CO Ada Assistant on " +
                         datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC") +
                         ". Content provided by borrower and not independently verified.")
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<font size='7.5' color='#6B6558'>{dis}</font>", body))
    doc.build(story)
    return buf.getvalue()


def _sum(*vals):
    tot = 0.0
    for v in vals:
        try:
            tot += float(v or 0)
        except (TypeError, ValueError):
            pass
    return tot


def render_pfs(fields: dict, borrower_name: str, variant: str) -> bytes:
    """PFS renderer. `variant`: 'sba413' or 'byrd'."""
    f = fields or {}
    total_assets = _sum(
        f.get("cash_on_hand"), f.get("savings"), f.get("ira_401k"), f.get("stocks_bonds"),
        f.get("real_estate_value"), f.get("autos"), f.get("other_assets_value"),
        f.get("life_insurance_cash_value"),
    )
    total_liabs = _sum(
        f.get("accounts_payable"), f.get("notes_payable"), f.get("installment_auto"),
        f.get("installment_other"), f.get("credit_cards"), f.get("mortgages_on_re"),
        f.get("unpaid_taxes"), f.get("other_liabilities"),
    )
    net_worth = total_assets - total_liabs

    def fmt(v):
        try:
            return f"${float(v):,.0f}"
        except (TypeError, ValueError):
            return "TBD"

    title = "SBA Form 413 — Personal Financial Statement" if variant == "sba413" \
            else "Personal Financial Statement"

    sections = [
        ("Applicant", [
            ("Name", f.get("name") or borrower_name),
            ("As of", f.get("as_of_date") or datetime.now(timezone.utc).date().isoformat()),
            ("Address", f.get("address")),
            ("Phone", f.get("phone")),
            ("Email", f.get("email")),
            ("Employer", f.get("employer")),
            ("Business Name", f.get("business_name")),
        ]),
        ("Assets", [
            ("Cash on hand & in banks", fmt(f.get("cash_on_hand"))),
            ("Savings accounts", fmt(f.get("savings"))),
            ("IRA / 401(k)", fmt(f.get("ira_401k"))),
            ("Stocks & bonds", fmt(f.get("stocks_bonds"))),
            ("Real estate (see schedule)", fmt(f.get("real_estate_value"))),
            ("Autos", fmt(f.get("autos"))),
            (f"Other assets — {f.get('other_assets_desc') or ''}", fmt(f.get("other_assets_value"))),
            ("Life insurance — cash value", fmt(f.get("life_insurance_cash_value"))),
            ("TOTAL ASSETS", fmt(total_assets)),
        ]),
        ("Liabilities", [
            ("Accounts payable", fmt(f.get("accounts_payable"))),
            ("Notes payable to banks/others", fmt(f.get("notes_payable"))),
            ("Installment (auto)", fmt(f.get("installment_auto"))),
            ("Installment (other)", fmt(f.get("installment_other"))),
            ("Credit card balances", fmt(f.get("credit_cards"))),
            ("Mortgages on real estate", fmt(f.get("mortgages_on_re"))),
            ("Unpaid taxes", fmt(f.get("unpaid_taxes"))),
            ("Other liabilities", fmt(f.get("other_liabilities"))),
            ("TOTAL LIABILITIES", fmt(total_liabs)),
            ("NET WORTH (Assets − Liabilities)", fmt(net_worth)),
        ]),
        ("Annual Income", [
            ("Salary", fmt(f.get("annual_salary"))),
            ("Dividends & interest", fmt(f.get("dividends_interest"))),
            ("Real estate income", fmt(f.get("real_estate_income"))),
            (f"Other income — {f.get('other_income_desc') or ''}", fmt(f.get("other_income"))),
            ("Income tax paid last year", fmt(f.get("income_tax_last_year"))),
            ("Total monthly debt payments", fmt(f.get("monthly_debt_payments"))),
        ]),
        ("Life Insurance", [
            ("Face amount", fmt(f.get("life_insurance_face"))),
            ("Cash surrender value", fmt(f.get("life_insurance_cash_value"))),
        ]),
    ]

    # Real estate schedule (if any)
    reo = f.get("real_estate_owned") or []
    if reo:
        reo_rows = "<br/>".join([
            f"• <b>{r.get('address','—')}</b> ({r.get('type','—')}) — "
            f"Value {fmt(r.get('present_value'))} · "
            f"Mortgage {fmt(r.get('mortgage_balance'))} · "
            f"Monthly pmt {fmt(r.get('monthly_pmt'))} · "
            f"Monthly rent {fmt(r.get('monthly_rent'))}"
            for r in reo
        ])
        sections.append(("Real Estate Schedule", reo_rows))

    disclaimer = (
        "The applicant certifies the information above is true and complete to the best of their knowledge. "
        + ("This statement is intended for use with the SBA in connection with a loan application. "
           if variant == "sba413" else "")
        + "Prepared with Byrd & CO Ada Assistant on "
        + datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
        + ". Applicant-provided; not independently verified by Byrd & CO."
    )
    return render_borrower_pdf(title, sections, borrower_name, disclaimer=disclaimer)


def render_resume_pdf(fields: dict, borrower_name: str, short: bool = False) -> bytes:
    """Resume or 1-page Sponsor Bio (if short=True)."""
    f = fields or {}
    title = "Sponsor Bio" if short else "Resume"
    sections = [
        ("Summary", f.get("professional_summary") or "TBD"),
        (f.get("current_role") and "Current Role" or "", [
            ("Role", f.get("current_role")),
            ("Company", f.get("current_company")),
            ("Years of experience", f.get("years_experience")),
        ] if f.get("current_role") or f.get("current_company") else "TBD"),
    ]
    proj = f.get("notable_projects") or []
    if proj:
        rows = "<br/>".join([
            f"• <b>{p.get('name','—')}</b> — {p.get('type','')} · Size: {p.get('size','—')} · "
            f"Role: {p.get('role','—')}. Outcome: {p.get('outcome','—')}"
            for p in proj
        ])
        sections.append(("Notable Projects", rows))
    if not short:
        hist = f.get("career_history") or []
        if hist:
            rows = "<br/>".join([
                f"• <b>{h.get('role','—')}</b> at {h.get('company','—')} ({h.get('dates','')}). "
                f"{h.get('highlights','')}"
                for h in hist
            ])
            sections.append(("Career History", rows))
        ed = f.get("education") or []
        if ed:
            rows = "<br/>".join([f"• {e.get('degree','—')}, {e.get('school','—')} ({e.get('year','')})"
                                 for e in ed])
            sections.append(("Education", rows))
        if f.get("licenses_certs"):
            sections.append(("Licenses & Certifications", ", ".join(f["licenses_certs"])))
        if f.get("memberships"):
            sections.append(("Memberships", ", ".join(f["memberships"])))
    return render_borrower_pdf(title, sections, borrower_name)


def render_business_plan_pdf(fields: dict, borrower_name: str) -> bytes:
    f = fields or {}
    sections = [
        ("Executive Summary", f.get("executive_summary") or "TBD"),
        ("Investment Thesis", f.get("investment_thesis") or "TBD"),
        ("Market Analysis", f.get("market_analysis") or "TBD"),
        ("Business Plan / Strategy", f.get("business_plan_narrative") or "TBD"),
        ("Capex / Renovation Plan", f.get("capex_plan") or "TBD"),
        ("Projected Returns", f.get("projected_returns") or "TBD"),
        ("Exit Strategy", f.get("exit_strategy") or "TBD"),
        ("Team", f.get("team") or "TBD"),
        ("Risks & Mitigations", f.get("risks_mitigations") or "TBD"),
    ]
    return render_borrower_pdf("Business Plan / Investment Memo", sections, borrower_name)


def render_lox_pdf(fields: dict, borrower_name: str) -> bytes:
    f = fields or {}
    body_txt = (
        f"<b>Date:</b> {f.get('date_of_letter') or datetime.now(timezone.utc).date().isoformat()}<br/>"
        f"<b>To:</b> {f.get('addressed_to') or 'To Whom It May Concern'}<br/><br/>"
        f"<b>Re:</b> {f.get('subject') or 'Letter of Explanation'}<br/><br/>"
        + (f.get("explanation") or "TBD").replace("\n", "<br/>") + "<br/><br/>"
        + (f.get("resolution") or "").replace("\n", "<br/>") + "<br/><br/>"
        f"Sincerely,<br/><br/><b>{f.get('name') or borrower_name}</b>"
    )
    return render_borrower_pdf("Letter of Explanation", [("", body_txt)], borrower_name)


def render_rent_roll_pdf(fields: dict, borrower_name: str) -> bytes:
    from io import BytesIO
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import inch

    f = fields or {}
    units = f.get("units") or []
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(letter), leftMargin=0.5*inch, rightMargin=0.5*inch,
                            topMargin=0.5*inch, bottomMargin=0.5*inch, title="Rent Roll")
    ss = getSampleStyleSheet()
    t_style = ParagraphStyle("t", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=13,
                             textColor=colors.HexColor("#1A1A1A"), spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["BodyText"], fontName="Helvetica", fontSize=9,
                         textColor=colors.HexColor("#6B6558"), spaceAfter=10)
    story = [Paragraph("Rent Roll", t_style),
             Paragraph(f"{f.get('property_address') or 'Property'} — As of {f.get('as_of_date') or 'today'}", sub)]

    hdr = ["Unit", "Tenant", "Type", "Sq Ft", "Rent", "Lease Start", "Lease End", "Deposit", "Notes"]
    rows = [hdr]
    total_rent = 0.0
    for u in units:
        try: total_rent += float(u.get("monthly_rent") or 0)
        except (TypeError, ValueError): pass
        rows.append([
            u.get("unit_id", ""), u.get("tenant", ""), u.get("unit_type", ""),
            str(u.get("size_sqft") or ""),
            f"${float(u.get('monthly_rent') or 0):,.0f}" if u.get("monthly_rent") not in (None, "") else "",
            u.get("lease_start", ""), u.get("lease_end", ""),
            f"${float(u.get('security_deposit') or 0):,.0f}" if u.get("security_deposit") not in (None, "") else "",
            (u.get("notes") or "")[:40],
        ])
    rows.append(["", "TOTAL", "", "", f"${total_rent:,.0f}", "", "", "", ""])

    tbl = Table(rows, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A1A1A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F3EEE0")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E4DFD1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        f"<font size='7.5' color='#6B6558'>Prepared with Byrd & CO Ada Assistant on "
        f"{datetime.now(timezone.utc).strftime('%B %d, %Y at %H:%M UTC')}. "
        f"Borrower-attested; not independently verified.</font>",
        ParagraphStyle("d", parent=ss["BodyText"], fontName="Helvetica", fontSize=8)))
    doc.build(story)
    return buf.getvalue()


def render_proforma_pdf(fields: dict, borrower_name: str) -> bytes:
    """CRE Proforma / underwriting workbook. Numbers-driven, multi-page."""
    from io import BytesIO
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    # PageBreak already imported at module top
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch

    f = fields or {}

    def _num(v, default=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def fmt_money(v):
        try:
            return f"${float(v):,.0f}"
        except (TypeError, ValueError):
            return "TBD"

    def fmt_pct(v):
        try:
            return f"{float(v):.2f}%"
        except (TypeError, ValueError):
            return "TBD"

    def fmt_x(v):
        try:
            return f"{float(v):.2f}x"
        except (TypeError, ValueError):
            return "TBD"

    # --- Core assumptions ---
    purchase_price = _num(f.get("purchase_price"))
    loan_amount = _num(f.get("loan_amount"))
    rate = _num(f.get("interest_rate_pct"))
    amort_years = _num(f.get("amortization_years"), 30)
    term_years = _num(f.get("term_years"), 5)
    closing_costs = _num(f.get("closing_costs"))
    rent_growth = _num(f.get("rent_growth_pct"), 3.0)
    expense_growth = _num(f.get("expense_growth_pct"), 2.5)
    vacancy_pct = _num(f.get("vacancy_pct"), 5.0)
    mgmt_pct = _num(f.get("management_pct"), 4.0)
    exit_cap = _num(f.get("cap_rate_pct"), 0)

    income_lines = f.get("income_lines") or []
    expense_lines = f.get("expense_lines") or []

    # --- Derived monthly / annual totals ---
    monthly_gross_income = sum(_num(li.get("monthly_amount")) for li in income_lines)
    annual_gross_income = monthly_gross_income * 12.0
    vacancy_loss = annual_gross_income * (vacancy_pct / 100.0)
    egi = annual_gross_income - vacancy_loss  # effective gross income
    # Management fee auto-computed off EGI unless user provided a mgmt line already
    has_mgmt_line = any((li.get("label") or "").strip().lower().startswith(("mgmt", "management"))
                       for li in expense_lines)
    mgmt_fee_auto = 0.0 if has_mgmt_line else egi * (mgmt_pct / 100.0)
    hard_expenses = sum(_num(li.get("annual_amount")) for li in expense_lines)
    total_expenses = hard_expenses + mgmt_fee_auto
    noi = egi - total_expenses
    # Cap rate implied on purchase
    implied_cap = (noi / purchase_price * 100.0) if purchase_price else 0.0
    # Debt service — monthly, level-pay amort
    if loan_amount > 0 and rate > 0 and amort_years > 0:
        i = rate / 100.0 / 12.0
        n = amort_years * 12.0
        monthly_pmt = loan_amount * (i * (1 + i) ** n) / (((1 + i) ** n) - 1)
    else:
        monthly_pmt = 0.0
    annual_ds = monthly_pmt * 12.0
    dscr = (noi / annual_ds) if annual_ds > 0 else 0.0
    cash_flow_before_tax = noi - annual_ds
    total_cash_in = (purchase_price - loan_amount) + closing_costs
    cash_on_cash = (cash_flow_before_tax / total_cash_in * 100.0) if total_cash_in > 0 else 0.0
    ltv = (loan_amount / purchase_price * 100.0) if purchase_price else 0.0
    dy = (noi / loan_amount * 100.0) if loan_amount else 0.0

    # --- PDF build ---
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6*inch, rightMargin=0.6*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch, title="Proforma")
    ss = getSampleStyleSheet()
    tstyle = ParagraphStyle("t", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=16,
                            alignment=1, spaceAfter=2, textColor=colors.HexColor("#1A1A1A"))
    sub = ParagraphStyle("sub", parent=ss["BodyText"], fontName="Helvetica", fontSize=9,
                         alignment=1, textColor=colors.HexColor("#6B6558"), spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11,
                        textColor=colors.HexColor("#C89434"), spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=12,
                          textColor=colors.HexColor("#1A1A1A"), spaceAfter=4)

    def kv_table(rows, col1=2.2*inch, col2=4.5*inch):
        t = Table(rows, colWidths=[col1, col2])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#E4DFD1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#EFE9DA")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#6B6558")),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    def data_table(header, rows, footer=None, widths=None):
        all_rows = [header] + rows + ([footer] if footer else [])
        t = Table(all_rows, colWidths=widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A1A1A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E4DFD1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if footer:
            style += [
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F3EEE0")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]
        t.setStyle(TableStyle(style))
        return t

    story = [
        Paragraph("Proforma — Underwriting Workbook", tstyle),
        Paragraph(
            f"{f.get('property_address') or 'Property'} · "
            f"{f.get('property_type') or 'Commercial Real Estate'} · "
            f"As of {f.get('as_of_date') or datetime.now(timezone.utc).date().isoformat()}",
            sub
        ),
    ]

    # ---------- Page 1: Property Summary + Deal Assumptions ----------
    story.append(Paragraph("Property Summary", h2))
    story.append(kv_table([
        ["Property Address", f.get("property_address") or "TBD"],
        ["Property Type", f.get("property_type") or "TBD"],
        ["Prepared By", f.get("prepared_by") or borrower_name],
        ["As-of Date", f.get("as_of_date") or datetime.now(timezone.utc).date().isoformat()],
    ]))

    story.append(Paragraph("Deal Assumptions", h2))
    story.append(kv_table([
        ["Purchase Price", fmt_money(purchase_price)],
        ["Loan Amount", fmt_money(loan_amount)],
        ["LTV", fmt_pct(ltv)],
        ["Interest Rate", fmt_pct(rate)],
        ["Amortization", f"{int(amort_years)} years" if amort_years else "TBD"],
        ["Term", f"{int(term_years)} years" if term_years else "TBD"],
        ["Closing Costs", fmt_money(closing_costs)],
        ["Total Cash Required", fmt_money(total_cash_in)],
        ["Vacancy Assumption", fmt_pct(vacancy_pct)],
        ["Management Fee (of EGI)", fmt_pct(mgmt_pct)],
        ["Rent Growth", fmt_pct(rent_growth) + " / yr"],
        ["Expense Growth", fmt_pct(expense_growth) + " / yr"],
    ]))
    story.append(PageBreak())

    # ---------- Page 2: Income & Rent Roll ----------
    story.append(Paragraph("Income Schedule (Year 1)", h2))
    inc_rows = []
    for li in income_lines:
        m = _num(li.get("monthly_amount"))
        inc_rows.append([li.get("label") or "Line", fmt_money(m), fmt_money(m * 12)])
    if not inc_rows:
        inc_rows.append(["No income lines provided", "TBD", "TBD"])
    story.append(data_table(
        ["Line", "Monthly", "Annual"],
        inc_rows,
        footer=["Gross Potential Income (GPI)", fmt_money(monthly_gross_income),
                fmt_money(annual_gross_income)],
        widths=[3.4*inch, 1.7*inch, 1.7*inch],
    ))
    story.append(Spacer(1, 8))
    story.append(kv_table([
        ["Gross Potential Income", fmt_money(annual_gross_income)],
        [f"Less: Vacancy ({fmt_pct(vacancy_pct)})", "(" + fmt_money(vacancy_loss) + ")"],
        ["Effective Gross Income (EGI)", fmt_money(egi)],
    ]))
    story.append(PageBreak())

    # ---------- Page 3: Operating Expenses + NOI ----------
    story.append(Paragraph("Operating Expenses (Year 1)", h2))
    exp_rows = []
    for li in expense_lines:
        a = _num(li.get("annual_amount"))
        exp_rows.append([li.get("label") or "Line", fmt_money(a), fmt_money(a / 12.0)])
    if mgmt_fee_auto > 0:
        exp_rows.append([f"Management Fee ({fmt_pct(mgmt_pct)} of EGI)",
                        fmt_money(mgmt_fee_auto), fmt_money(mgmt_fee_auto / 12.0)])
    if not exp_rows:
        exp_rows.append(["No expense lines provided", "TBD", "TBD"])
    story.append(data_table(
        ["Line", "Annual", "Monthly"],
        exp_rows,
        footer=["Total Operating Expenses", fmt_money(total_expenses),
                fmt_money(total_expenses / 12.0)],
        widths=[3.4*inch, 1.7*inch, 1.7*inch],
    ))

    exp_ratio = (total_expenses / egi * 100.0) if egi else 0.0
    story.append(Spacer(1, 8))
    story.append(Paragraph("Net Operating Income", h2))
    story.append(kv_table([
        ["Effective Gross Income", fmt_money(egi)],
        ["Less: Total Operating Expenses", "(" + fmt_money(total_expenses) + ")"],
        ["Net Operating Income (NOI)", fmt_money(noi)],
        ["Operating Expense Ratio", fmt_pct(exp_ratio)],
        ["Implied Cap Rate on Purchase", fmt_pct(implied_cap)],
    ]))
    story.append(PageBreak())

    # ---------- Page 4: Debt Service & Returns ----------
    story.append(Paragraph("Debt Service & Coverage", h2))
    story.append(kv_table([
        ["Loan Amount", fmt_money(loan_amount)],
        ["LTV", fmt_pct(ltv)],
        ["Interest Rate", fmt_pct(rate)],
        ["Amortization", f"{int(amort_years)} years" if amort_years else "TBD"],
        ["Monthly Debt Service", fmt_money(monthly_pmt)],
        ["Annual Debt Service", fmt_money(annual_ds)],
        ["Debt Service Coverage Ratio (DSCR)", fmt_x(dscr)],
        ["Debt Yield (NOI / Loan)", fmt_pct(dy)],
    ]))

    story.append(Paragraph("Cash Flow & Returns (Year 1)", h2))
    story.append(kv_table([
        ["Net Operating Income", fmt_money(noi)],
        ["Less: Annual Debt Service", "(" + fmt_money(annual_ds) + ")"],
        ["Cash Flow Before Tax", fmt_money(cash_flow_before_tax)],
        ["Total Cash Required (Equity + Closing)", fmt_money(total_cash_in)],
        ["Cash-on-Cash Return", fmt_pct(cash_on_cash)],
    ]))
    story.append(PageBreak())

    # ---------- Page 5: 5-Year Projection ----------
    story.append(Paragraph("5-Year Cash-Flow Projection", h2))
    years = int(max(5, min(term_years or 5, 10)))
    proj_header = ["Year"] + [str(y) for y in range(1, years + 1)]
    egi_row = ["Effective Gross Income"]
    exp_row = ["Operating Expenses"]
    noi_row = ["NOI"]
    ds_row = ["Debt Service"]
    cf_row = ["Cash Flow (BT)"]
    dscr_row = ["DSCR"]

    y_egi = egi
    y_exp = total_expenses
    for y in range(1, years + 1):
        if y > 1:
            y_egi = y_egi * (1 + rent_growth / 100.0)
            y_exp = y_exp * (1 + expense_growth / 100.0)
        y_noi = y_egi - y_exp
        y_cf = y_noi - annual_ds
        y_dscr = (y_noi / annual_ds) if annual_ds > 0 else 0.0
        egi_row.append(fmt_money(y_egi))
        exp_row.append("(" + fmt_money(y_exp) + ")")
        noi_row.append(fmt_money(y_noi))
        ds_row.append("(" + fmt_money(annual_ds) + ")")
        cf_row.append(fmt_money(y_cf))
        dscr_row.append(fmt_x(y_dscr))

    proj_table = Table([proj_header, egi_row, exp_row, noi_row, ds_row, cf_row, dscr_row],
                       repeatRows=1)
    proj_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A1A1A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 3), (0, 3), "Helvetica-Bold"),  # NOI row
        ("FONTNAME", (0, 5), (0, 5), "Helvetica-Bold"),  # CF row
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#F3EEE0")),
        ("BACKGROUND", (0, 5), (-1, 5), colors.HexColor("#F3EEE0")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E4DFD1")),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(proj_table)

    # Terminal value / exit if exit_cap provided
    if exit_cap > 0:
        # Use year-{years} NOI (recompute)
        y_egi = egi
        y_exp = total_expenses
        for y in range(1, years + 1):
            if y > 1:
                y_egi = y_egi * (1 + rent_growth / 100.0)
                y_exp = y_exp * (1 + expense_growth / 100.0)
        terminal_noi = y_egi - y_exp
        terminal_value = terminal_noi / (exit_cap / 100.0)
        story.append(Spacer(1, 8))
        story.append(Paragraph("Terminal Value (Year " + str(years) + ")", h2))
        story.append(kv_table([
            [f"Year {years} NOI", fmt_money(terminal_noi)],
            ["Exit Cap Rate", fmt_pct(exit_cap)],
            ["Estimated Terminal Value", fmt_money(terminal_value)],
        ]))

    # Assumptions / Notes
    notes = (f.get("assumptions_notes") or "").strip()
    if notes:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Assumptions & Notes", h2))
        story.append(Paragraph(notes.replace("\n", "<br/>"), body))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        f"<font size='7.5' color='#6B6558'>Prepared with Byrd &amp; CO Ada Assistant on "
        f"{datetime.now(timezone.utc).strftime('%B %d, %Y at %H:%M UTC')}. "
        f"Borrower-attested underwriting model — projections not guarantees. "
        f"Numbers not independently verified.</font>",
        body))
    doc.build(story)
    return buf.getvalue()


def _render_ada_doc(doc_type: str, fields: dict, borrower_name: str, variant: Optional[str] = None) -> bytes:
    if doc_type in ("pfs_sba413", "pfs_byrd"):
        return render_pfs(fields, borrower_name, "sba413" if doc_type == "pfs_sba413" else "byrd")
    if doc_type == "resume":
        return render_resume_pdf(fields, borrower_name, short=False)
    if doc_type == "sponsor_bio":
        return render_resume_pdf(fields, borrower_name, short=True)
    if doc_type == "business_plan":
        return render_business_plan_pdf(fields, borrower_name)
    if doc_type == "lox":
        return render_lox_pdf(fields, borrower_name)
    if doc_type == "rent_roll":
        return render_rent_roll_pdf(fields, borrower_name)
    if doc_type == "proforma":
        return render_proforma_pdf(fields, borrower_name)
    raise HTTPException(status_code=400, detail=f"Unknown doc_type {doc_type}")


async def _ada_turn_context(user: dict) -> str:
    """Compact JSON snapshot Ada receives every turn."""
    scenarios = await db.scenarios.find(
        {"client_id": user["id"]},
        {"_id": 0, "id": 1, "name": 1, "status": 1, "loan_request": 1, "property_info": 1},
    ).to_list(50)
    scen_ids = [s["id"] for s in scenarios]
    docs_by_scen: dict[str, list] = {sid: [] for sid in scen_ids}
    if scen_ids:
        async for d in db.client_docs.find(
            {"scenario_id": {"$in": scen_ids}},
            {"_id": 0, "id": 1, "scenario_id": 1, "label": 1, "category": 1, "required": 1,
             "status": 1, "notes": 1, "file_id": 1, "files": 1},
        ).sort("order", 1):
            docs_by_scen.setdefault(d["scenario_id"], []).append({
                "doc_line_id": d["id"], "label": d["label"], "category": d.get("category"),
                "required": d.get("required", False), "status": d.get("status"),
                "has_file": bool(d.get("file_id")) or bool(d.get("files")),
                "file_count": len(d.get("files") or []) or (1 if d.get("file_id") else 0),
                "broker_note": d.get("notes") if d.get("status") == "rejected" else None,
            })
    drafts = await db.borrower_ada_drafts.find(
        {"client_id": user["id"], "status": "in_progress"},
        {"_id": 0, "id": 1, "doc_type": 1, "scenario_id": 1, "updated_at": 1},
    ).to_list(20)
    # Load recent conversation history so Ada retains memory across process restarts,
    # worker cycles, and any in-memory-session eviction inside LlmChat. Cap the tail so
    # very long chats don't blow the token budget — 24 messages ≈ 12 back-and-forth turns.
    recent = await db.borrower_ada_messages.find(
        {"client_id": user["id"]}, {"_id": 0, "role": 1, "content": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(24)
    # We queried DESC to grab the tail; flip to chronological for the transcript.
    recent.reverse()
    # Exclude the *current* user turn we just inserted (last one) so it's not duplicated —
    # the current message is appended to the prompt separately by the caller.
    if recent and recent[-1].get("role") == "user":
        recent = recent[:-1]
    transcript_lines = []
    for m in recent:
        role = "Borrower" if m.get("role") == "user" else "Ada"
        content = (m.get("content") or "").strip()
        if content:
            transcript_lines.append(f"{role}: {content}")
    transcript = "\n\n".join(transcript_lines)
    payload = {
        "borrower": {
            "first_name": (user.get("name") or user.get("email", "").split("@")[0]).split(" ")[0],
            "full_name": user.get("name"),
            "email": user.get("email"),
            "company": user.get("company"),
        },
        "today": datetime.now(timezone.utc).date().isoformat(),
        "scenarios": [{
            "id": s["id"], "name": s.get("name"), "status": s.get("status"),
            # Full property snapshot — Ada should NOT re-ask the borrower for anything below
            # that's already populated. Only ask for values that are null / missing.
            "property": {
                "address": (s.get("property_info") or {}).get("address"),
                "city": (s.get("property_info") or {}).get("city"),
                "state": (s.get("property_info") or {}).get("state"),
                "zip": (s.get("property_info") or {}).get("zip"),
                "property_type": (s.get("property_info") or {}).get("property_type"),
                "year_built": (s.get("property_info") or {}).get("year_built"),
                "units": (s.get("property_info") or {}).get("units"),
                "sqft": (s.get("property_info") or {}).get("sqft"),
                "purchase_price": (s.get("property_info") or {}).get("purchase_price"),
                "current_value": (s.get("property_info") or {}).get("current_value"),
                "occupancy_pct": (s.get("property_info") or {}).get("occupancy_pct"),
            },
            "loan_request": {
                "loan_type": (s.get("loan_request") or {}).get("loan_type"),
                "loan_amount": (s.get("loan_request") or {}).get("loan_amount"),
                "term_months": (s.get("loan_request") or {}).get("term_months"),
                "amort_months": (s.get("loan_request") or {}).get("amort_months"),
                "requested_rate_pct": (s.get("loan_request") or {}).get("requested_rate_pct"),
                "recourse": (s.get("loan_request") or {}).get("recourse"),
            },
            "financials": {
                "gross_income": (s.get("financials") or {}).get("gross_income"),
                "vacancy_pct": (s.get("financials") or {}).get("vacancy_pct"),
                "operating_expenses": (s.get("financials") or {}).get("operating_expenses"),
                "capex_reserves": (s.get("financials") or {}).get("capex_reserves"),
                "override_noi": (s.get("financials") or {}).get("override_noi"),
            },
            "construction_budget": s.get("construction_budget") or {},
            "sources_uses": s.get("sources_uses") or [],
            "sponsors": [{
                "name": sp.get("name"), "role": sp.get("role"),
                "ownership_pct": sp.get("ownership_pct"),
                "is_guarantor": sp.get("is_guarantor"),
            } for sp in (s.get("sponsors") or [])],
            "docs": docs_by_scen.get(s["id"], []),
        } for s in scenarios],
        "in_progress_drafts": drafts,
    }
    parts = [
        "Here is the current state (READ ONLY):",
        "",
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```",
    ]
    if transcript:
        parts.append("")
        parts.append("## Recent conversation (chronological — use this to maintain continuity, "
                     "remember what was discussed, and avoid greeting the borrower again if you've "
                     "already been talking):")
        parts.append("")
        parts.append(transcript)
    parts.append("")
    parts.append("Respond to the borrower's new message below.")
    return "\n".join(parts)


def _ada_grab(full_text: str, marker: str) -> Optional[str]:
    needle = f"```{marker}"
    idx = full_text.find(needle)
    if idx < 0:
        return None
    start = full_text.find("\n", idx) + 1
    end = full_text.find("```", start)
    return full_text[start:end].strip() if end > 0 else None


def _ada_strip_blocks(full_text: str) -> str:
    out = full_text
    for m in ("generate_doc", "upload_confirm", "broker_note"):
        needle = f"```{m}"
        idx = out.find(needle)
        while idx >= 0:
            end = out.find("```", idx + len(needle))
            if end < 0:
                break
            out = out[:idx] + out[end + 3:]
            idx = out.find(needle)
    return out.strip()


@api.get("/client/ada/messages")
async def ada_messages(user=Depends(require_client)):
    msgs = await db.borrower_ada_messages.find(
        {"client_id": user["id"]}, {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    return msgs


@api.post("/client/ada/reset")
async def ada_reset(user=Depends(require_client)):
    await db.borrower_ada_messages.delete_many({"client_id": user["id"]})
    return {"ok": True}


class AdaChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


@api.post("/client/ada/chat")
async def ada_chat(body: AdaChatBody, user=Depends(require_client)):
    """SSE streaming chat. Applies generate_doc / upload_confirm / broker_note blocks after Claude completes."""
    now = now_iso()
    await db.borrower_ada_messages.insert_one({
        "id": str(uuid.uuid4()), "client_id": user["id"], "role": "user",
        "content": body.message, "created_at": now,
    })
    ctx = await _ada_turn_context(user)
    session_id = f"ada::{user['id']}"
    chat = _make_scenario_ai_chat(session_id, ADA_SYSTEM_PROMPT)

    async def gen():
        buf: list[str] = []
        try:
            async for ev in chat.stream_message(UserMessage(text=ctx + "\n\n---\n\nBorrower: " + body.message)):
                if isinstance(ev, TextDelta):
                    buf.append(ev.content)
                    yield f"data: {json.dumps({'type':'token','content':ev.content})}\n\n"
                elif isinstance(ev, StreamDone):
                    break
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','detail':str(e)[:300]})}\n\n"
            return

        full = "".join(buf)
        chat_text = _ada_strip_blocks(full)

        # Parse & apply blocks
        drafts_created: list[dict] = []
        uploads_done: list[dict] = []
        broker_notes: list[dict] = []

        raw_gen = _ada_grab(full, "generate_doc")
        if raw_gen:
            try:
                p = json.loads(raw_gen)
                d = await _ada_apply_generate_doc(user, p)
                if d:
                    drafts_created.append(d)
            except Exception as e:
                logger.warning("generate_doc block failed: %s", e)

        raw_up = _ada_grab(full, "upload_confirm")
        if raw_up:
            try:
                p = json.loads(raw_up)
                up = await _ada_apply_upload(user, p)
                if up:
                    uploads_done.append(up)
            except Exception as e:
                logger.warning("upload_confirm block failed: %s", e)

        raw_bn = _ada_grab(full, "broker_note")
        if raw_bn:
            try:
                p = json.loads(raw_bn)
                bn = await _ada_apply_broker_note(user, p)
                if bn:
                    broker_notes.append(bn)
            except Exception as e:
                logger.warning("broker_note block failed: %s", e)

        msg_id = str(uuid.uuid4())
        await db.borrower_ada_messages.insert_one({
            "id": msg_id, "client_id": user["id"], "role": "assistant",
            "content": chat_text, "drafts_created": drafts_created,
            "uploads_done": uploads_done, "broker_notes": broker_notes,
            "created_at": now_iso(),
        })
        yield "data: " + json.dumps({
            "type": "done", "message_id": msg_id, "text": chat_text,
            "drafts_created": drafts_created, "uploads_done": uploads_done,
            "broker_notes": broker_notes,
        }) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


async def _ada_apply_generate_doc(user: dict, block: dict) -> Optional[dict]:
    doc_type = block.get("doc_type")
    if doc_type not in DOC_TYPES:
        return None
    scenario_id = block.get("scenario_id")
    if scenario_id:
        scen = await db.scenarios.find_one(
            {"id": scenario_id, "client_id": user["id"]}, {"_id": 0, "id": 1, "name": 1},
        )
        if not scen:
            return None
    fields = block.get("fields") or {}
    borrower_name = user.get("name") or (user.get("email") or "Borrower").split("@")[0]
    pdf_bytes = _render_ada_doc(doc_type, fields, borrower_name)
    now = now_iso()
    draft_id = str(uuid.uuid4())
    # Ephemeral file (stored in client_files with is_draft=True; deleted on upload/dismiss)
    file_id = str(uuid.uuid4())
    filename = f"{DOC_TYPE_DEFAULT_LABEL.get(doc_type, 'Document')} (draft).pdf"
    await db.client_files.insert_one({
        "id": file_id, "doc_id": None, "client_id": user["id"], "scenario_id": scenario_id,
        "filename": filename, "content_type": "application/pdf", "size": len(pdf_bytes),
        "data_b64": base64.b64encode(pdf_bytes).decode(),
        "uploaded_at": now, "is_ada_draft": True,
    })
    await db.borrower_ada_drafts.insert_one({
        "id": draft_id, "client_id": user["id"], "scenario_id": scenario_id,
        "doc_type": doc_type,
        "target_doc_line_label": block.get("target_doc_line_label") or DOC_TYPE_DEFAULT_LABEL.get(doc_type),
        "fields": fields, "preview_file_id": file_id, "status": "ready",
        "created_at": now, "updated_at": now,
    })
    return {
        "draft_id": draft_id, "doc_type": doc_type, "scenario_id": scenario_id,
        "preview_file_id": file_id, "filename": filename,
        "target_doc_line_label": block.get("target_doc_line_label") or DOC_TYPE_DEFAULT_LABEL.get(doc_type),
    }


async def _ada_apply_upload(user: dict, block: dict) -> Optional[dict]:
    draft_id = block.get("draft_id")
    target_line_id = block.get("target_doc_line_id")
    if not draft_id or not target_line_id:
        return None
    draft = await db.borrower_ada_drafts.find_one({"id": draft_id, "client_id": user["id"]}, {"_id": 0})
    if not draft or draft.get("status") == "uploaded":
        return None
    dl = None
    try:
        dl = await _resolve_client_doc_for_user(target_line_id, user)
    except HTTPException:
        dl = None
    if not dl or dl.get("system"):
        return None
    # Copy the preview file into a real, permanent file on the doc line
    preview = await db.client_files.find_one({"id": draft["preview_file_id"]}, {"_id": 0})
    if not preview:
        return None
    now = now_iso()
    new_file_id = str(uuid.uuid4())
    filename = preview["filename"].replace(" (draft)", "")
    await db.client_files.insert_one({
        "id": new_file_id, "doc_id": target_line_id, "client_id": user["id"],
        "scenario_id": draft["scenario_id"], "filename": filename,
        "content_type": preview["content_type"], "size": preview["size"],
        "data_b64": preview["data_b64"], "uploaded_at": now, "uploaded_by_ada": True,
    })
    # Preserve any existing uploads on the line; Ada's generated doc is simply ADDED as another file.
    existing_metas = _ensure_doc_files_meta(dl)
    new_meta = {
        "file_id": new_file_id,
        "filename": filename,
        "content_type": preview["content_type"],
        "size": preview["size"],
        "uploaded_at": now,
        "uploaded_by": "ada",
    }
    existing_metas.append(new_meta)
    await db.client_docs.update_one({"id": target_line_id},
        {"$set": {"file_id": new_file_id, "filename": filename,
                  "content_type": preview["content_type"], "size": preview["size"],
                  "files": existing_metas,
                  "status": "uploaded",
                  "notes": f"Uploaded via Ada on {now.split('T')[0]}", "updated_at": now}})
    await db.borrower_ada_drafts.update_one({"id": draft_id},
        {"$set": {"status": "uploaded", "uploaded_file_id": new_file_id, "updated_at": now}})
    # Delete the preview to save space
    await db.client_files.delete_one({"id": draft["preview_file_id"]})
    return {"draft_id": draft_id, "doc_line_id": target_line_id, "filename": filename,
            "doc_type": draft["doc_type"]}


async def _ada_apply_broker_note(user: dict, block: dict) -> Optional[dict]:
    """Post a task into EACH admin's assistant queue with the borrower's question."""
    question = (block.get("question") or "").strip()
    if not question:
        return None
    urgency = block.get("urgency") or "normal"
    scen_id = block.get("related_scenario_id")
    related_name = user.get("name") or user.get("email")
    admins = await db.users.find({"role": "admin"}, {"_id": 0, "id": 1, "name": 1}).to_list(20)
    now = now_iso()
    posted_admin_ids: list[str] = []
    for a in admins:
        task_id = str(uuid.uuid4())
        title_prefix = "URGENT: " if urgency == "urgent" else ""
        await db.assistant_tasks.insert_one({
            "id": task_id, "admin_id": a["id"],
            "title": f"{title_prefix}Ada relay from {related_name}",
            "notes": question, "related_name": related_name,
            "related_scenario_id": scen_id, "status": "open",
            "due_date": None, "assigned_by_name": "Ada (borrower relay)",
            "created_at": now, "updated_at": now,
        })
        posted_admin_ids.append(a["id"])
    return {"question": question[:200], "urgency": urgency, "posted_to_admins": len(posted_admin_ids)}


# ---- Proactive 3-day silence nudge ----
NUDGE_SILENCE_DAYS = 3
NUDGE_QUIET_DAYS = 7  # after we ping a borrower, don't ping again for a week


async def _ada_nudge_check() -> dict:
    """Find borrowers whose scenarios have pending required docs and who haven't opened Ada in 3+ days.
    Sends a Postmark email inviting them back."""
    now = datetime.now(timezone.utc)
    counters = {"considered": 0, "sent": 0, "skipped_quiet": 0}
    scenarios = await db.scenarios.find(
        {"client_id": {"$exists": True, "$ne": None}, "status": {"$in": ["draft", "shopping"]}},
        {"_id": 0, "id": 1, "client_id": 1, "name": 1},
    ).to_list(500)
    scen_by_client: dict[str, list] = {}
    for s in scenarios:
        scen_by_client.setdefault(s["client_id"], []).append(s)
    for client_id, scens in scen_by_client.items():
        counters["considered"] += 1
        # Recent ada activity check
        last_msg = await db.borrower_ada_messages.find_one(
            {"client_id": client_id}, {"_id": 0, "created_at": 1},
            sort=[("created_at", -1)],
        )
        last_active = None
        if last_msg and last_msg.get("created_at"):
            try:
                last_active = datetime.fromisoformat(last_msg["created_at"].replace("Z", "+00:00"))
            except Exception:
                last_active = None
        if last_active and (now - last_active).days < NUDGE_SILENCE_DAYS:
            continue
        # Recent nudge quiet window
        last_nudge = await db.borrower_ada_nudges.find_one(
            {"client_id": client_id}, {"_id": 0, "sent_at": 1},
            sort=[("sent_at", -1)],
        )
        if last_nudge and last_nudge.get("sent_at"):
            try:
                sent_dt = datetime.fromisoformat(last_nudge["sent_at"].replace("Z", "+00:00"))
                if (now - sent_dt).days < NUDGE_QUIET_DAYS:
                    counters["skipped_quiet"] += 1
                    continue
            except Exception:
                pass
        # Count pending required docs across all their scenarios
        pending_required = await db.client_docs.count_documents({
            "client_id": client_id,
            "scenario_id": {"$in": [s["id"] for s in scens]},
            "required": True, "status": "pending",
        })
        if pending_required == 0:
            continue
        # Fetch client + send
        client = await db.users.find_one({"id": client_id}, {"_id": 0, "name": 1, "email": 1})
        if not client or not client.get("email"):
            continue
        first_name = (client.get("name") or "there").split(" ")[0]
        portal_url = f"{public_base_url()}/portal" if public_base_url() else "/portal"
        subject = f"{first_name}, want a hand with your remaining docs?"
        html = (
            f"<div style='font-family:Helvetica,Arial,sans-serif;color:#1A1A1A;line-height:1.55;font-size:14px;'>"
            f"<p>Hi {first_name},</p>"
            f"<p>It's Ada from Byrd &amp; CO. I noticed there are still <b>{pending_required} required document"
            f"{'s' if pending_required != 1 else ''}</b> pending on your loan. I can walk you through them "
            f"in about 5-10 minutes — including generating your Personal Financial Statement and resume for you.</p>"
            f"<p><a href='{portal_url}' style='background:#1A1A1A;color:#FBF8F1;text-decoration:none;padding:12px 18px;border-radius:6px;font-weight:600;display:inline-block;'>Open my portal</a></p>"
            f"<p style='font-size:12px;color:#6B6558;'>Reply to this email if you'd rather have Wayne or Caleb call you.</p>"
            f"</div>"
        )
        text = (f"Hi {first_name},\n\nAda from Byrd & CO here. You have {pending_required} required "
                f"document(s) still pending. Open your portal to knock them out: {portal_url}\n")
        try:
            send_email(client["email"], subject, html, text, "ada_nudge")
            await db.borrower_ada_nudges.insert_one({
                "id": str(uuid.uuid4()), "client_id": client_id,
                "pending_required": pending_required, "sent_at": now.isoformat(),
            })
            counters["sent"] += 1
        except Exception as e:
            logger.warning("Ada nudge send failed for %s: %s", client["email"], e)
    return counters


@api.post("/admin/ada/run-nudges")
async def admin_run_ada_nudges(admin=Depends(require_admin)):
    """Manual trigger for the nudge scan (also runs automatically every 24h at startup)."""
    return await _ada_nudge_check()


@app.on_event("startup")
async def _ada_nudge_loop():
    async def loop():
        # Warm up 5 min after startup, then every 24h
        await asyncio.sleep(300)
        while True:
            try:
                res = await _ada_nudge_check()
                logger.info("Ada nudge scan: %s", res)
            except Exception as e:
                logger.warning("Ada nudge loop error: %s", e)
            await asyncio.sleep(86400)
    asyncio.create_task(loop())


app.include_router(api)


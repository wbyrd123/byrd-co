"""
Byrd & CO backend — FastAPI + MongoDB.
Powers:
  * Public marketing site (quote requests, testimonials)
  * Client document portal (invite-based, per-client checklists, uploads with status)
  * Admin/broker portal (manage clients, review docs, view quotes)
  * AdsCopilot internal tool (Claude Sonnet 4.5) — kept from prior iteration
"""
from fastapi import FastAPI, APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import base64
import logging
import random
import uuid
import json
import bcrypt
import jwt as pyjwt
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Literal, Dict
from datetime import datetime, timezone, timedelta

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
from email_service import (
    send_email, broker_emails, public_base_url,
    tmpl_quote, tmpl_invite, tmpl_lender_activity,
)

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


def sanitize_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "email": u["email"],
        "name": u["name"],
        "role": u.get("role", "client"),
        "phone": u.get("phone"),
        "company": u.get("company"),
    }


# ================ Startup: seed admins & default doc template ================
DEFAULT_DOC_TEMPLATE = [
    {"label": "Personal Financial Statement", "category": "Personal", "required": True},
    {"label": "Personal Tax Returns — Year 1", "category": "Personal", "required": True},
    {"label": "Personal Tax Returns — Year 2", "category": "Personal", "required": True},
    {"label": "Personal Tax Returns — Year 3", "category": "Personal", "required": True},
    {"label": "Business Tax Returns — Year 1", "category": "Business", "required": True},
    {"label": "Business Tax Returns — Year 2", "category": "Business", "required": True},
    {"label": "Business Tax Returns — Year 3", "category": "Business", "required": True},
    {"label": "Resume", "category": "Personal", "required": True},
    {"label": "Government-Issued ID", "category": "Personal", "required": True},
    {"label": "Bank Statements (3 months)", "category": "Financial", "required": True},
    {"label": "Entity Docs (LLC / EIN)", "category": "Business", "required": True},
    {"label": "Rent Roll", "category": "Property", "required": False},
    {"label": "Operating Statements / T-12", "category": "Property", "required": False},
    {"label": "Property Photos", "category": "Property", "required": False},
    {"label": "Purchase Contract", "category": "Property", "required": False},
    {"label": "Appraisal", "category": "Property", "required": False},
    {"label": "Insurance Certificate", "category": "Property", "required": False},
    {"label": "Construction Budget", "category": "Property", "required": False},
]


@app.on_event("startup")
async def seed():
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


# ================ Models ================
class LoginInput(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


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


class DocUpdate(BaseModel):
    label: Optional[str] = None
    status: Optional[Literal["pending", "uploaded", "reviewed", "rejected"]] = None
    notes: Optional[str] = None


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
@api.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginInput):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not check_pw(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": make_token(user["id"]), "user": sanitize_user(user)}


@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return sanitize_user(user)


# ================ Invites ================
@api.post("/admin/invites")
async def create_invite(body: InviteCreate, background: BackgroundTasks, admin=Depends(require_admin)):
    # If user already exists, error out; otherwise create pending user + invite token
    existing = await db.users.find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="A user with this email already exists")
    user_id = str(uuid.uuid4())
    token = uuid.uuid4().hex + uuid.uuid4().hex
    template = body.doc_template or DEFAULT_DOC_TEMPLATE
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
    # Seed doc checklist
    for i, item in enumerate(template):
        await db.client_docs.insert_one({
            "id": str(uuid.uuid4()),
            "client_id": user_id,
            "label": item.get("label", "Document"),
            "category": item.get("category", "Other"),
            "required": item.get("required", True),
            "status": "pending",
            "notes": "",
            "file_id": None,
            "order": i,
            "created_at": now,
            "updated_at": now,
        })
    # Email the invite link to the client (non-blocking, safe if Postmark down)
    invite_url = f"{public_base_url()}/portal/invite/{token}" if public_base_url() else f"/portal/invite/{token}"
    user_stub = {"name": body.name, "email": body.email.lower()}
    subj, html, text = tmpl_invite(user_stub, invite_url)
    background.add_task(send_email, body.email.lower(), subj, html, text, "invite")
    return {
        "token": token,
        "invite_url_path": f"/portal/invite/{token}",
        "user": {
            "id": user_id, "email": body.email.lower(), "name": body.name,
            "company": body.company, "phone": body.phone,
        },
    }


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
async def accept_invite(token: str, body: InviteAccept):
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
    return {"token": make_token(user["id"]), "user": sanitize_user({**user, "role": "client"})}


# ================ Admin: clients ================
async def _client_summary(client_id: str) -> dict:
    docs = await db.client_docs.find({"client_id": client_id}, {"_id": 0}).to_list(500)
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
    u.pop("loan_type", None)  # legacy field — loan_type now lives on the scenario
    docs = await db.client_docs.find({"client_id": client_id}, {"_id": 0}).sort("order", 1).to_list(500)
    # Attach file metadata (without content) for docs that have uploads
    for d in docs:
        if d.get("file_id"):
            f = await db.client_files.find_one({"id": d["file_id"]}, {"_id": 0, "data_b64": 0})
            d["file"] = f
    invite = await db.invites.find_one({"user_id": client_id}, {"_id": 0})
    scenarios = await db.scenarios.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "status": 1, "loan_request": 1, "updated_at": 1, "created_at": 1},
    ).sort("updated_at", -1).to_list(200)
    # Slim loan_request down to just loan_type + loan_amount for the client page
    for s in scenarios:
        lr = s.pop("loan_request", None) or {}
        s["loan_type"] = lr.get("loan_type")
        s["loan_amount"] = lr.get("loan_amount")
    return {"client": u, "docs": docs, "invite": invite, "scenarios": scenarios}


@api.post("/admin/clients/{client_id}/docs")
async def admin_add_doc(client_id: str, body: DocCreate, admin=Depends(require_admin)):
    u = await db.users.find_one({"id": client_id, "role": "client"})
    if not u:
        raise HTTPException(status_code=404, detail="Client not found")
    # Determine next order
    last = await db.client_docs.find({"client_id": client_id}).sort("order", -1).to_list(1)
    next_order = (last[0]["order"] + 1) if last else 0
    now = now_iso()
    doc = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "label": body.label,
        "category": body.category or "Other",
        "required": body.required,
        "status": "pending",
        "notes": "",
        "file_id": None,
        "order": next_order,
        "created_at": now,
        "updated_at": now,
    }
    await db.client_docs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.patch("/admin/clients/{client_id}/docs/{doc_id}")
async def admin_update_doc(client_id: str, doc_id: str, body: DocUpdate, admin=Depends(require_admin)):
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = now_iso()
    res = await db.client_docs.update_one({"id": doc_id, "client_id": client_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Doc not found")
    d = await db.client_docs.find_one({"id": doc_id}, {"_id": 0})
    return d


@api.delete("/admin/clients/{client_id}/docs/{doc_id}")
async def admin_delete_doc(client_id: str, doc_id: str, admin=Depends(require_admin)):
    d = await db.client_docs.find_one({"id": doc_id, "client_id": client_id})
    if not d:
        raise HTTPException(status_code=404, detail="Doc not found")
    if d.get("file_id"):
        await db.client_files.delete_one({"id": d["file_id"]})
    await db.client_docs.delete_one({"id": doc_id})
    return {"ok": True}


# ================ Client portal ================
@api.get("/client/me")
async def client_me(user=Depends(require_client)):
    docs = await db.client_docs.find({"client_id": user["id"]}, {"_id": 0}).sort("order", 1).to_list(500)
    for d in docs:
        if d.get("file_id"):
            f = await db.client_files.find_one({"id": d["file_id"]}, {"_id": 0, "data_b64": 0})
            d["file"] = f
    return {"user": user, "docs": docs}


@api.post("/client/docs/{doc_id}/upload")
async def client_upload(doc_id: str, body: DocUploadInput, user=Depends(require_client)):
    d = await db.client_docs.find_one({"id": doc_id, "client_id": user["id"]})
    if not d:
        raise HTTPException(status_code=404, detail="Doc not found")
    try:
        raw = base64.b64decode(body.data_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_FILE_MB}MB limit")
    # If replacing an existing file, remove old
    if d.get("file_id"):
        await db.client_files.delete_one({"id": d["file_id"]})
    file_id = str(uuid.uuid4())
    await db.client_files.insert_one({
        "id": file_id,
        "doc_id": doc_id,
        "client_id": user["id"],
        "filename": body.filename,
        "content_type": body.content_type,
        "size": len(raw),
        "data_b64": body.data_b64,
        "uploaded_at": now_iso(),
    })
    await db.client_docs.update_one(
        {"id": doc_id},
        {"$set": {
            "file_id": file_id,
            "status": "uploaded",
            "updated_at": now_iso(),
        }},
    )
    return {"ok": True, "file_id": file_id}


@api.get("/files/{file_id}")
async def get_file(file_id: str, user=Depends(get_current_user)):
    f = await db.client_files.find_one({"id": file_id})
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    # Access control: admins can access anything; clients only their own
    if user.get("role") != "admin" and f.get("client_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    raw = base64.b64decode(f["data_b64"])
    return Response(
        content=raw,
        media_type=f.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{f["filename"]}"'},
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


# ================================================================
# Deal Engine — Scenarios, Lenders, Lender Shares (Phase 1 + 2)
# ================================================================
from io import BytesIO
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
    name: Optional[str] = ""
    entity: Optional[str] = ""
    credit_score: Optional[int] = None
    liquidity: Optional[float] = None
    net_worth: Optional[float] = None


class PropertyInfo(BaseModel):
    address: Optional[str] = ""
    city: Optional[str] = ""
    state: Optional[str] = ""
    zip: Optional[str] = ""
    property_type: Optional[str] = ""
    year_built: Optional[int] = None
    units: Optional[int] = None
    sqft: Optional[float] = None
    purchase_price: Optional[float] = None
    current_value: Optional[float] = None
    occupancy_pct: Optional[float] = None


class LoanRequest(BaseModel):
    loan_amount: Optional[float] = None
    loan_type: Optional[str] = ""            # Purchase / Refi / Cash-Out / Construction / Bridge / Portfolio
    term_months: Optional[int] = None
    amort_months: Optional[int] = None
    requested_rate_pct: Optional[float] = None
    recourse: Optional[str] = ""             # recourse / non-recourse / partial


class Financials(BaseModel):
    gross_income: Optional[float] = None
    vacancy_pct: Optional[float] = None
    operating_expenses: Optional[float] = None
    capex_reserves: Optional[float] = None
    override_noi: Optional[float] = None     # if borrower provides NOI directly


class ConstructionBudget(BaseModel):
    total_project_cost: Optional[float] = None
    land_cost: Optional[float] = None
    hard_costs: Optional[float] = None
    soft_costs: Optional[float] = None
    contingency: Optional[float] = None


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
    sponsor: SponsorInfo = Field(default_factory=SponsorInfo)
    property_info: PropertyInfo = Field(default_factory=PropertyInfo)
    loan_request: LoanRequest = Field(default_factory=LoanRequest)
    financials: Financials = Field(default_factory=Financials)
    construction: Optional[ConstructionBudget] = None
    sources_uses: List[SUItem] = Field(default_factory=list)
    attached_docs: List[AttachedDoc] = Field(default_factory=list)
    notes: Optional[str] = ""
    business_plan: Optional[str] = ""


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[Literal["draft", "shopping", "term_sheet", "closed", "lost"]] = None
    client_id: Optional[str] = None
    sponsor: Optional[SponsorInfo] = None
    property_info: Optional[PropertyInfo] = None
    loan_request: Optional[LoanRequest] = None
    financials: Optional[Financials] = None
    construction: Optional[ConstructionBudget] = None
    sources_uses: Optional[List[SUItem]] = None
    attached_docs: Optional[List[AttachedDoc]] = None
    notes: Optional[str] = None
    business_plan: Optional[str] = None


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


class LenderDocAccessAction(BaseModel):
    action: Literal["approve", "revoke"]


# ---------- Sizing engine ----------
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
    rate = float(loan.get("requested_rate_pct") or 0) or None
    amort = int(loan.get("amort_months") or 0) or None

    property_value = _property_value(prop)
    tpc = _total_project_cost(prop, con)
    noi = _calc_noi(fin)
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
        "monthly_payment": monthly_pmt,
        "annual_debt_service": annual_ds,
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


def match_lenders(scen: dict, lenders: List[dict]) -> List[dict]:
    prop = scen.get("property_info") or {}
    loan = scen.get("loan_request") or {}
    metrics = compute_scenario_metrics(scen)
    loan_amount = float(loan.get("loan_amount") or 0) or None
    ptype = (prop.get("property_type") or "").lower()
    state = (prop.get("state") or "").upper()
    ltv = metrics.get("ltv_pct")
    dscr = metrics.get("dscr")
    dy = metrics.get("debt_yield_pct")

    results = []
    for l in lenders:
        reasons_fit = []
        reasons_miss = []
        # property type
        pt_list = [p.lower() for p in (l.get("property_types") or [])]
        if pt_list and ptype:
            if ptype in pt_list or "other" in pt_list:
                reasons_fit.append(f"lends on {ptype}")
            else:
                reasons_miss.append(f"doesn't lend on {ptype}")
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

    # Business plan / notes
    if scen.get("business_plan"):
        elements.append(Paragraph("Business Plan", h2))
        elements.append(Paragraph(scen["business_plan"].replace("\n", "<br/>"), body))
    if scen.get("notes"):
        elements.append(Paragraph("Notes", h2))
        elements.append(Paragraph(scen["notes"].replace("\n", "<br/>"), body))

    doc.build(elements, onFirstPage=_watermark_canvas(watermark_text), onLaterPages=_watermark_canvas(watermark_text))
    return buf.getvalue()


# ---------- SCENARIOS: admin routes ----------
def _clean_scenario(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


@api.post("/admin/scenarios")
async def create_scenario(body: ScenarioCreate, admin=Depends(require_admin)):
    if body.client_id:
        client = await db.users.find_one({"id": body.client_id, "role": "client"})
        if not client:
            raise HTTPException(status_code=400, detail="Client not found")
    doc = {
        "id": str(uuid.uuid4()),
        "broker_id": admin["id"],
        "status": "draft",
        **body.model_dump(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.scenarios.insert_one(doc)
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
        # attach client docs (for the picker)
        client_docs = await db.client_docs.find({"client_id": d["client_id"]}, {"_id": 0}).sort("order", 1).to_list(500)
        for cd in client_docs:
            if cd.get("file_id"):
                f = await db.client_files.find_one({"id": cd["file_id"]}, {"_id": 0, "data_b64": 0})
                cd["file"] = f
        d["client_docs"] = client_docs
    else:
        d["client_docs"] = []
    d["shares"] = await db.scenario_shares.find({"scenario_id": sid}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return d


@api.patch("/admin/scenarios/{sid}")
async def update_scenario(sid: str, body: ScenarioUpdate, admin=Depends(require_admin)):
    update = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = now_iso()
    res = await db.scenarios.update_one({"id": sid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    d = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    d["metrics"] = compute_scenario_metrics(d)
    return d


@api.delete("/admin/scenarios/{sid}")
async def delete_scenario(sid: str, admin=Depends(require_admin)):
    res = await db.scenarios.delete_one({"id": sid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    await db.scenario_shares.delete_many({"scenario_id": sid})
    await db.share_views.delete_many({"scenario_id": sid})
    return {"ok": True}


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


@api.get("/admin/scenarios/{sid}/docs.zip")
async def admin_scenario_docs_zip(sid: str, admin=Depends(require_admin)):
    """Bundle every attached document (that has an uploaded file) into a single ZIP."""
    import zipfile
    from io import BytesIO
    scen = await db.scenarios.find_one({"id": sid}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    attached = scen.get("attached_docs") or []
    doc_ids = [a["doc_id"] for a in attached]
    if not doc_ids:
        raise HTTPException(status_code=404, detail="No documents attached")
    docs = await db.client_docs.find({"id": {"$in": doc_ids}}, {"_id": 0}).to_list(500)
    if not docs:
        raise HTTPException(status_code=404, detail="No documents found")
    buf = BytesIO()
    used_names = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cd in docs:
            if not cd.get("file_id"):
                continue
            f = await db.client_files.find_one({"id": cd["file_id"]})
            if not f:
                continue
            raw = base64.b64decode(f["data_b64"])
            # Prefix filename with the checklist label so lenders see logical names
            label = (cd.get("label") or "document").replace("/", "-").replace("\\", "-").strip()
            base_name = f["filename"] or "file"
            name = f"{label} - {base_name}"
            # Deduplicate
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
async def lender_gate(token: str, body: LenderGate):
    share = await db.scenario_shares.find_one({"token": token})
    if not share:
        raise HTTPException(status_code=404, detail="Link not found or revoked")
    session_token = _make_view_session(share["id"], body.model_dump())
    await _log_view(share["scenario_id"], share["id"], body.model_dump(), "gate")
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
    Priority: per-share override > legacy per-share grant > scenario default."""
    overrides = share.get("doc_overrides") or {}
    if doc_id in overrides:
        v = overrides[doc_id]
        return {"include": "included", "on_request": "on_request", "hidden": "hidden"}.get(v, "on_request")
    grants = share.get("doc_grants") or []
    if doc_id in grants:
        return "included"
    scen_v = (attach_map.get(doc_id) or {}).get("visibility", "on_request")
    return "included" if scen_v == "included" else "on_request"


@api.get("/lender-view/{token}")
async def lender_get_package(token: str, session_token: Optional[str] = None):
    share, session = await _require_view_session(token, session_token)
    scen = await db.scenarios.find_one({"id": share["scenario_id"]}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    metrics = compute_scenario_metrics(scen)

    # Filter docs into included vs on-request vs hidden (per-share overrides applied)
    attached = scen.get("attached_docs") or []
    doc_map = {d["doc_id"]: d for d in attached}
    client_docs = []
    if scen.get("client_id"):
        client_docs = await db.client_docs.find(
            {"client_id": scen["client_id"], "id": {"$in": list(doc_map.keys())}}, {"_id": 0}
        ).to_list(500)

    docs_out = []
    for cd in client_docs:
        eff = _effective_doc_visibility(share, doc_map, cd["id"])
        if eff == "hidden":
            continue  # lender never learns this doc exists
        has_file = bool(cd.get("file_id"))
        viewable = has_file and eff == "included"
        docs_out.append({
            "id": cd["id"],
            "label": cd["label"],
            "category": cd.get("category"),
            "visibility": doc_map[cd["id"]].get("visibility", "on_request"),
            "has_file": has_file,
            "viewable": viewable,
            "requires_request": eff == "on_request",
        })

    await _log_view(scen["id"], share["id"], session, "view_scenario")

    # Strip client PII from the outer payload
    watermark = f"{session.get('viewer_institution')} — {session.get('viewer_name')}"

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
        "docs": docs_out,
        "watermark": watermark,
        "share_note": share.get("note"),
    }


@api.get("/lender-view/{token}/doc/{doc_id}")
async def lender_get_doc(token: str, doc_id: str, session_token: Optional[str] = None):
    share, session = await _require_view_session(token, session_token)
    scen = await db.scenarios.find_one({"id": share["scenario_id"]})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    # Confirm doc is attached to scenario and effective visibility is 'included'
    attached = scen.get("attached_docs") or []
    attach_map = {d["doc_id"]: d for d in attached}
    if doc_id not in attach_map:
        raise HTTPException(status_code=404, detail="Doc not part of this package")
    eff = _effective_doc_visibility(share, attach_map, doc_id)
    if eff == "hidden":
        raise HTTPException(status_code=404, detail="Doc not part of this package")
    if eff != "included":
        raise HTTPException(status_code=403, detail="Access not granted for this document yet")
    # Fetch file
    cd = await db.client_docs.find_one({"id": doc_id})
    if not cd or not cd.get("file_id"):
        raise HTTPException(status_code=404, detail="Document not uploaded")
    f = await db.client_files.find_one({"id": cd["file_id"]})
    if not f:
        raise HTTPException(status_code=404, detail="File missing")
    await _log_view(scen["id"], share["id"], session, "view_doc",
                    extra={"doc_id": doc_id, "doc_label": cd.get("label")})
    raw = base64.b64decode(f["data_b64"])
    return Response(
        content=raw,
        media_type=f.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{f["filename"]}"'},
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
    attached = scen.get("attached_docs") or []
    attach_map = {d["doc_id"]: d for d in attached}
    # Only docs whose effective visibility is 'included' are bundled
    allowed_ids = [
        did for did in attach_map
        if _effective_doc_visibility(share, attach_map, did) == "included"
    ]
    if not allowed_ids:
        raise HTTPException(status_code=404, detail="No documents available to download")
    docs = await db.client_docs.find({"id": {"$in": allowed_ids}}, {"_id": 0}).to_list(500)
    buf = BytesIO()
    used_names = set()
    included_names = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cd in docs:
            if not cd.get("file_id"):
                continue
            f = await db.client_files.find_one({"id": cd["file_id"]})
            if not f:
                continue
            raw = base64.b64decode(f["data_b64"])
            label = (cd.get("label") or "document").replace("/", "-").replace("\\", "-").strip()
            base_name = f["filename"] or "file"
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


ASSISTANT_SYSTEM_PROMPT = """You are the personal assistant to a commercial real estate broker at Byrd & CO.
You are warm, concise, and proactive. You address the broker by first name.

At the top of every turn you receive:
- The broker's identity (name, email)
- Today's date + local weekday
- The broker's CURRENT open task list (with due dates and any linked client)
- The broker's client roster (name + email, for quick recognition)

# What you do
1. Have a natural conversation. Keep responses short and friendly.
2. Extract commitments the broker makes and turn them into structured tasks.
3. If a due date is mentioned (e.g. "check with me on July 21st", "next Tuesday"), compute the
   real ISO date given today's date and put it on the task.
4. If the broker mentions a person who is NOT in the client roster, offer to add them as a client
   (name only — never fabricate emails or phone numbers).
5. If the broker asks you to email someone, DRAFT the email in the structured block below —
   do not send it. The user will review and send.
6. When the broker tells you something is done, mark the matching open task complete.
7. Never expose task IDs in visible chat — only in the structured blocks.

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

Rules:
- Only include blocks you're actually proposing. Never emit empty ones.
- Never emit `complete_tasks` unless you're matching a task from the "OPEN TASKS" list.
- Never emit `email_draft` unless the broker asked you to email someone.
- Dates in `due_date` MUST be ISO format YYYY-MM-DD.
- Keep quotes/apostrophes safe in JSON (escape with \\").
"""


def _assistant_turn_context(admin: dict, open_tasks: List[dict], clients: List[dict]) -> str:
    today = datetime.now(timezone.utc)
    slim_tasks = [
        {
            "id": t["id"],
            "title": t["title"],
            "due_date": t.get("due_date"),
            "notes": t.get("notes", ""),
            "related_name": t.get("related_name") or "",
        }
        for t in open_tasks
    ]
    slim_clients = [
        {"id": c["id"], "name": c.get("name"), "email": c.get("email"), "company": c.get("company")}
        for c in clients
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

    chat_text = full_text
    for marker in ("new_tasks", "complete_tasks", "email_draft", "suggest_client"):
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
    }


async def _apply_assistant_actions(admin_id: str, parsed: dict) -> dict:
    """Persist any tasks Claude proposed / completed. Returns the applied deltas."""
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

    return {"created": applied_new, "completed": applied_complete}


@api.post("/admin/assistant/chat")
async def assistant_chat(body: AssistantChatRequest, admin=Depends(require_admin)):
    """SSE streaming chat with the personal assistant, per-admin private."""
    open_tasks = await db.assistant_tasks.find(
        {"admin_id": admin["id"], "status": "open"}, {"_id": 0}
    ).sort("due_date", 1).to_list(200)
    clients = await db.users.find(
        {"role": "client"}, {"_id": 0, "id": 1, "name": 1, "email": 1, "company": 1}
    ).to_list(500)

    session_id = f"assistant::{admin['id']}"
    chat = _make_scenario_ai_chat(session_id, ASSISTANT_SYSTEM_PROMPT)
    turn_context = _assistant_turn_context(admin, open_tasks, clients)
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
        applied = await _apply_assistant_actions(admin["id"], parsed)

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


@api.post("/admin/assistant/email/send")
async def assistant_send_email(body: AssistantEmailSend, background: BackgroundTasks, admin=Depends(require_admin)):
    """Send an email FROM the admin's own address via Postmark, and log it."""
    from_email = admin.get("email")
    if not from_email:
        raise HTTPException(status_code=400, detail="Admin has no email on file")
    from_name = admin.get("name") or "Byrd & CO"
    # Wrap the body in a lightweight branded template so it doesn't look like a system email
    safe_body = body.body.replace("<", "&lt;").replace(">", "&gt;")
    html = (
        "<div style=\"font-family:Georgia,serif;max-width:640px;margin:auto;color:#1A1A1A;\">"
        f"<div style=\"white-space:pre-wrap;font-family:Arial,sans-serif;font-size:14px;line-height:1.55;\">{safe_body}</div>"
        f"<hr style=\"margin:24px 0;border:none;border-top:1px solid #E4DFD1;\"/>"
        f"<div style=\"font-family:Arial,sans-serif;font-size:12px;color:#6B6558;\">{from_name}<br/>Byrd &amp; CO Commercial Real Estate Lending<br/>"
        f"<a href=\"mailto:{from_email}\" style=\"color:#6B6558;\">{from_email}</a></div>"
        "</div>"
    )
    # Fire-and-forget in background so we return quickly
    background.add_task(
        send_email, body.to, body.subject, html, body.body, "assistant-outbound",
        from_email, from_name, from_email,
    )
    # Log the outbound
    log_id = str(uuid.uuid4())
    await db.assistant_emails.insert_one({
        "id": log_id,
        "admin_id": admin["id"],
        "from_email": from_email,
        "to": body.to,
        "subject": body.subject,
        "body": body.body,
        "related_task_id": body.related_task_id,
        "sent_at": now_iso(),
    })
    return {"ok": True, "id": log_id}


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


app.include_router(api)

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

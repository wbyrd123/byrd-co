"""
Byrd & CO backend — FastAPI + MongoDB.
Powers:
  * Public marketing site (quote requests, testimonials)
  * Client document portal (invite-based, per-client checklists, uploads with status)
  * Admin/broker portal (manage clients, review docs, view quotes)
  * AdsCopilot internal tool (Claude Sonnet 4.5) — kept from prior iteration
"""
from fastapi import FastAPI, APIRouter, HTTPException, Depends
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
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

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
    loan_type: Optional[str] = None
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
async def submit_quote(body: QuoteRequest):
    doc = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "read": False,
        "created_at": now_iso(),
    }
    await db.quotes.insert_one(doc)
    doc.pop("_id", None)
    logger.info(f"New quote request from {body.email}")
    return {"ok": True, "id": doc["id"]}


@api.get("/public/testimonials")
async def testimonials():
    # Seeded testimonials — editable later
    return [
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
async def create_invite(body: InviteCreate, admin=Depends(require_admin)):
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
        "loan_type": body.loan_type,
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
    return {
        "token": token,
        "invite_url_path": f"/portal/invite/{token}",
        "user": {
            "id": user_id, "email": body.email.lower(), "name": body.name,
            "company": body.company, "phone": body.phone, "loan_type": body.loan_type,
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
    result = []
    for u in users:
        s = await _client_summary(u["id"])
        u["doc_summary"] = s
        result.append(u)
    return result


@api.get("/admin/clients/{client_id}")
async def admin_get_client(client_id: str, admin=Depends(require_admin)):
    u = await db.users.find_one({"id": client_id, "role": "client"}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Client not found")
    docs = await db.client_docs.find({"client_id": client_id}, {"_id": 0}).sort("order", 1).to_list(500)
    # Attach file metadata (without content) for docs that have uploads
    for d in docs:
        if d.get("file_id"):
            f = await db.client_files.find_one({"id": d["file_id"]}, {"_id": 0, "data_b64": 0})
            d["file"] = f
    invite = await db.invites.find_one({"user_id": client_id}, {"_id": 0})
    return {"client": u, "docs": docs, "invite": invite}


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

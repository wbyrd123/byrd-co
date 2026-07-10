"""
AdsCopilot backend — FastAPI + MongoDB + Claude Sonnet 4.5.
Auth: JWT (bcrypt). Real Google Ads API is not connected — campaigns are stored in Mongo (demo mode).
"""
from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
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
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

EMERGENT_LLM_KEY = os.environ['EMERGENT_LLM_KEY']
JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGO = "HS256"
JWT_EXPIRY_HOURS = 24 * 7

app = FastAPI(title="AdsCopilot API")
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("adscopilot")


# ============ Helpers ============
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


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


# ============ Models ============
class RegisterInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1)


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


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


# ============ Analytics simulation ============
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
        series.append({
            "date": d.isoformat(),
            "impressions": impr,
            "clicks": clicks,
            "cost": cost,
            "conversions": conv,
        })
    return series


def _summary_from_series(series):
    impr = sum(x["impressions"] for x in series)
    clicks = sum(x["clicks"] for x in series)
    cost = round(sum(x["cost"] for x in series), 2)
    conv = sum(x["conversions"] for x in series)
    ctr = round((clicks / impr * 100), 2) if impr else 0.0
    cpc = round((cost / clicks), 2) if clicks else 0.0
    conv_rate = round((conv / clicks * 100), 2) if clicks else 0.0
    return {
        "impressions": impr,
        "clicks": clicks,
        "cost": cost,
        "conversions": conv,
        "ctr": ctr,
        "cpc": cpc,
        "conversion_rate": conv_rate,
    }


# ============ Auth routes ============
@api.post("/auth/register", response_model=AuthResponse)
async def register(body: RegisterInput):
    existing = await db.users.find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    pw_hash = bcrypt.hashpw(body.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user_id = str(uuid.uuid4())
    doc = {
        "id": user_id,
        "email": body.email.lower(),
        "name": body.name,
        "password_hash": pw_hash,
        "created_at": now_iso(),
    }
    await db.users.insert_one(doc)
    token = make_token(user_id)
    return {"token": token, "user": {"id": user_id, "email": doc["email"], "name": doc["name"]}}


@api.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginInput):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not bcrypt.checkpw(body.password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = make_token(user["id"])
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"]},
    }


@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return user


# ============ Campaigns ============
@api.get("/campaigns")
async def list_campaigns(user=Depends(get_current_user)):
    docs = await db.campaigns.find({"user_id": user["id"]}, {"_id": 0}).to_list(500)
    # Attach summary metrics
    for c in docs:
        series = _perf_for_campaign(c["id"], 30)
        c["metrics"] = _summary_from_series(series)
    docs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return docs


@api.post("/campaigns")
async def create_campaign(body: CampaignCreate, user=Depends(get_current_user)):
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "name": body.name,
        "objective": body.objective,
        "status": "active",
        "daily_budget": body.daily_budget,
        "target_locations": body.target_locations,
        "keywords": body.keywords,
        "headlines": body.headlines,
        "descriptions": body.descriptions,
        "final_url": body.final_url,
        "created_at": now_iso(),
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


# ============ Analytics ============
@api.get("/analytics/overview")
async def analytics_overview(user=Depends(get_current_user)):
    campaigns = await db.campaigns.find({"user_id": user["id"]}, {"_id": 0}).to_list(500)
    if not campaigns:
        return {
            "summary": _summary_from_series([]),
            "daily": [],
            "campaigns": [],
        }
    daily_map = {}
    per_campaign = []
    for c in campaigns:
        series = _perf_for_campaign(c["id"], 30)
        summary = _summary_from_series(series)
        per_campaign.append({
            "id": c["id"], "name": c["name"], "status": c.get("status", "active"),
            **summary,
        })
        for row in series:
            k = row["date"]
            if k not in daily_map:
                daily_map[k] = {"date": k, "impressions": 0, "clicks": 0, "cost": 0.0, "conversions": 0}
            daily_map[k]["impressions"] += row["impressions"]
            daily_map[k]["clicks"] += row["clicks"]
            daily_map[k]["cost"] = round(daily_map[k]["cost"] + row["cost"], 2)
            daily_map[k]["conversions"] += row["conversions"]
    daily = sorted(daily_map.values(), key=lambda x: x["date"])
    total_summary = _summary_from_series(daily)
    return {"summary": total_summary, "daily": daily, "campaigns": per_campaign}


# ============ LLM helpers ============
def _make_chat(session_id: str, system_message: str) -> LlmChat:
    return LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=system_message,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")


async def _llm_json(session_id: str, system: str, prompt: str) -> dict:
    """Non-streaming JSON helper using stream_message under the hood."""
    chat = _make_chat(session_id, system)
    buf = []
    async for ev in chat.stream_message(UserMessage(text=prompt)):
        if isinstance(ev, TextDelta):
            buf.append(ev.content)
        elif isinstance(ev, StreamDone):
            break
    text = "".join(buf).strip()
    # Extract JSON substring (defensive: model may wrap in fences)
    if "```" in text:
        parts = text.split("```")
        for p in parts:
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


# ============ Ad copy generator ============
@api.post("/ai/adcopy")
async def gen_adcopy(body: AdCopyRequest, user=Depends(get_current_user)):
    system = (
        "You are an expert Google Ads copywriter. Generate compliant Google Search Ad copy. "
        "Constraints: headlines <=30 characters, descriptions <=90 characters. "
        "Return STRICT JSON only, no prose. Schema: "
        '{"headlines":[{"text":"..","chars":N}], "descriptions":[{"text":"..","chars":N}]}'
    )
    prompt = (
        f"Product/Service: {body.product}\n"
        f"Target Audience: {body.audience or 'general'}\n"
        f"Tone: {body.tone}\n"
        f"Keywords to weave in: {', '.join(body.keywords) if body.keywords else 'none'}\n"
        f"Produce {body.num_headlines} headlines and {body.num_descriptions} descriptions. "
        f"Vary hooks: value prop, urgency, curiosity, social proof, offer. "
        f"Count characters accurately."
    )
    result = await _llm_json(f"adcopy-{uuid.uuid4()}", system, prompt)
    return result


# ============ Keyword research ============
@api.post("/ai/keywords")
async def gen_keywords(body: KeywordRequest, user=Depends(get_current_user)):
    system = (
        "You are a senior Google Ads keyword strategist. Given a seed keyword, produce a "
        "focused keyword plan. Return STRICT JSON only. Schema: "
        '{"keywords":[{"keyword":"..","match_type":"broad|phrase|exact","intent":"informational|commercial|transactional|navigational","est_monthly_volume":number,"est_cpc_usd":number,"difficulty":"low|medium|high"}]}'
    )
    prompt = (
        f"Seed keyword: {body.seed}\n"
        f"Industry: {body.industry or 'general'}\n"
        f"Produce {body.count} diverse keyword ideas mixing short-tail and long-tail. "
        f"Vary match types and intent. Estimated volumes and CPCs should be realistic. "
        f"Do not include duplicates."
    )
    result = await _llm_json(f"kw-{uuid.uuid4()}", system, prompt)
    return result


# ============ Chat (streaming SSE) ============
CHAT_SYSTEM = (
    "You are AdsCopilot, an expert Google Ads assistant embedded in a management dashboard. "
    "Help the user plan campaigns, refine ad copy, pick keywords, interpret metrics (CTR, CPC, "
    "conversion rate, ROAS), and optimize budgets. Be concise, actionable, and specific. "
    "Use short paragraphs and bullet lists. When suggesting ad copy, respect Google's limits: "
    "headlines <=30 chars, descriptions <=90 chars. If the user asks to create a campaign, "
    "ask for missing details (goal, budget, geo, keywords) then confirm."
)


@api.post("/chat/stream")
async def chat_stream(body: ChatRequest, user=Depends(get_current_user)):
    # Persist user message
    await db.messages.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "session_id": body.session_id,
        "role": "user",
        "content": body.message,
        "created_at": now_iso(),
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
                "id": str(uuid.uuid4()),
                "user_id": user["id"],
                "session_id": body.session_id,
                "role": "assistant",
                "content": full,
                "created_at": now_iso(),
            })
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            logger.exception("chat stream error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/chat/history")
async def chat_history(session_id: str, user=Depends(get_current_user)):
    docs = await db.messages.find(
        {"user_id": user["id"], "session_id": session_id},
        {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    return docs


@api.get("/")
async def root():
    return {"service": "AdsCopilot API", "status": "ok"}


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
    client.close()

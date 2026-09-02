"""Byrd & CO — Loan Quote PDF watermark + public 'Request a Live Quote' flow tests."""
import base64
import os
import uuid
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE}/api"

ADMIN = ("wayne@byrd-co.com", "byrdco2026")

mongo = MongoClient(be["MONGO_URL"])
mdb = mongo[be["DB_NAME"]]

TAG = f"TEST_qreq_{os.getpid()}_"


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, r.text[:200]
    return r.json()["token"]


def auth(t): return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for q in list(mdb.loan_quotes.find({"property_info.name": {"$regex": f"^{TAG}"}}, {"_id": 0, "id": 1})):
        mdb.loan_quote_leads.delete_many({"quote_id": q["id"]})
    mdb.loan_quotes.delete_many({"property_info.name": {"$regex": f"^{TAG}"}})


@pytest.fixture(scope="module")
def sample_quote(admin_tok):
    body = {
        "state": {
            "property_info": {
                "name": f"{TAG}Riverbend Warehouse",
                "property_type": "Industrial",
                "address": "1200 Bayou Rd", "city": "Houston", "state": "TX",
                "estimated_value": 10_000_000, "noi": 700_000,
            },
            "listing_agent": {"name": "", "email": "", "phone": "", "brokerage": ""},
            "options": [
                {"label": "Bank", "loan_amount": 6_500_000, "rate_pct": 6.75,
                 "amortization_years": 25, "term_months": 60, "notes": ""},
                {"label": "Agency", "loan_amount": 6_500_000, "rate_pct": 6.20,
                 "amortization_years": 30, "term_months": 120, "notes": ""},
                {"label": "Credit Union", "loan_amount": 6_500_000, "rate_pct": 6.90,
                 "amortization_years": 25, "term_months": 60, "notes": ""},
            ],
        },
        "add_listing_agent_to_crm": False,
    }
    r = requests.post(f"{API}/admin/marketing/quote/generate", json=body,
                      headers=auth(admin_tok), timeout=90)
    assert r.status_code == 200, r.text[:300]
    return r.json()["id"]


# ---------------- Watermark ----------------

class TestWatermark:
    def test_pdf_bytes_include_watermark_text_and_footer(self, admin_tok, sample_quote):
        pr = requests.get(f"{API}/admin/marketing/quotes/{sample_quote}/pdf",
                          headers=auth(admin_tok), timeout=60)
        assert pr.status_code == 200
        pdf_bytes = pr.content
        assert pdf_bytes.startswith(b"%PDF"), "must be a valid PDF"
        import pypdf
        from io import BytesIO
        text = "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(BytesIO(pdf_bytes)).pages)
        # Watermark: 5x5 grid means the phrase appears at least 25 times.
        assert text.count("BYRD & CO") >= 20, f"watermark tile count too low: {text.count('BYRD & CO')}"
        # Footer stamp on every page
        assert "byrd-co.com" in text
        # Broker contact info remains printed (fee-agreement-style cropping-defense).
        assert "wayne@byrd-co.com" in text
        # 'Request a Live Quote' CTA button rendered when PUBLIC_BASE_URL is set.
        assert "Request a Live Quote" in text


# ---------------- Public request-callback ----------------

class TestPublicQuoteRequest:
    def test_public_meta_exposes_property_snippet_only(self, sample_quote):
        r = requests.get(f"{API}/public/quote/{sample_quote}", timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert j["id"] == sample_quote
        assert j["property_name"].startswith(TAG)
        # Sensitive fields must NOT leak to the public snippet
        assert "pdf_b64" not in j
        assert "options" not in j
        assert "research_note" not in j
        assert "created_by" not in j

    def test_public_meta_404_on_bad_id(self):
        r = requests.get(f"{API}/public/quote/does-not-exist", timeout=30)
        assert r.status_code == 404

    def test_public_request_creates_lead_and_audit(self, sample_quote):
        body = {
            "name": f"{TAG}Prospect",
            "email": f"{TAG.lower()}prospect@example.com",
            "phone": "555-0000",
            "best_time": "Weekday mornings",
            "message": "Looking for 10y IO options on this deal.",
        }
        r = requests.post(f"{API}/public/quote/{sample_quote}/request-callback",
                          json=body, timeout=60)
        assert r.status_code == 200, r.text[:200]
        lead_id = r.json()["id"]

        lead = mdb.loan_quote_leads.find_one({"id": lead_id}, {"_id": 0})
        assert lead
        assert lead["quote_id"] == sample_quote
        assert lead["email"] == body["email"].lower()
        assert lead["message"] == body["message"]

        # Audit event fires
        ev = mdb.audit_log.find_one({"event_type": "quote.public_request",
                                     "resource_id": sample_quote},
                                    {"_id": 0}, sort=[("timestamp", -1)])
        assert ev, "missing audit event"
        assert ev["metadata"]["lead_id"] == lead_id

    def test_public_request_404_on_missing_quote(self):
        r = requests.post(f"{API}/public/quote/does-not-exist/request-callback",
                          json={"name": "X", "email": "x@y.com"}, timeout=30)
        assert r.status_code == 404

    def test_public_request_rejects_bad_input(self, sample_quote):
        # Missing email
        r = requests.post(f"{API}/public/quote/{sample_quote}/request-callback",
                          json={"name": "X"}, timeout=30)
        assert r.status_code == 422
        # Invalid email
        r = requests.post(f"{API}/public/quote/{sample_quote}/request-callback",
                          json={"name": "X", "email": "not-an-email"}, timeout=30)
        assert r.status_code == 422
        # Empty name
        r = requests.post(f"{API}/public/quote/{sample_quote}/request-callback",
                          json={"name": "", "email": "x@y.com"}, timeout=30)
        assert r.status_code == 422

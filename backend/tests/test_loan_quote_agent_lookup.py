"""Tests for POST /api/admin/marketing/agent-lookup + regression on chat."""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://google-ads-auto-2.preview.emergentagent.com"
ADMIN_EMAIL = "wayne@byrd-co.com"
ADMIN_PASS = "byrdco2026"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=30)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"No token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ---- Agent lookup endpoint ----
class TestAgentLookup:
    def test_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/admin/marketing/agent-lookup",
                          json={"name": "Jane Doe"}, timeout=20)
        assert r.status_code in (401, 403), f"Expected 401/403 without auth, got {r.status_code} {r.text[:200]}"

    def test_rejects_missing_name(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/admin/marketing/agent-lookup",
                          headers=admin_headers, json={"brokerage": "Compass"}, timeout=20)
        assert r.status_code == 422, f"Expected 422, got {r.status_code}"

    def test_lookup_returns_shape(self, admin_headers):
        payload = {"name": "Wayne Byrd", "brokerage": "Byrd & Co", "city": "Houston", "state": "TX"}
        r = requests.post(f"{BASE_URL}/api/admin/marketing/agent-lookup",
                          headers=admin_headers, json=payload, timeout=90)
        assert r.status_code == 200, f"Expected 200, got {r.status_code} body={r.text[:400]}"
        data = r.json()
        for key in ("found", "emails", "phones", "summary", "citations"):
            assert key in data, f"Missing key {key} in response: {data.keys()}"
        assert isinstance(data["found"], bool)
        assert isinstance(data["emails"], list)
        assert isinstance(data["phones"], list)
        assert isinstance(data["summary"], str) and len(data["summary"]) > 20, "Summary looks empty"
        assert isinstance(data["citations"], list)
        # Print for evidence
        print(f"AGENT LOOKUP: found={data['found']} emails={data['emails']} phones={data['phones']} citations={len(data['citations'])}")
        print(f"SUMMARY EXCERPT: {data['summary'][:300]}")


# ---- Regression: chat lookup_agent flag ----
class TestChatLookupFlag:
    def test_chat_sets_lookup_agent_true(self, admin_headers):
        """When broker asks Ada to look up agent email, lookup_agent should come back true."""
        state = {
            "property_info": {
                "name": "Wheatley Court",
                "property_type": "Multifamily",
                "address": "5408 Market St",
                "city": "Houston",
                "state": "TX",
                "estimated_value": 3000000,
                "cap_rate_pct": 12.56,
            },
            "listing_agent": {"name": "Jane Doe", "brokerage": "Compass"},
            "options": [],
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/marketing/quote/chat",
            headers=admin_headers,
            json={"session_id": None, "message": "Can you look up her email online?", "state": state},
            timeout=60,
        )
        assert r.status_code == 200, f"Chat failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        assert "lookup_agent" in data, f"lookup_agent key missing in response: {data.keys()}"
        print(f"CHAT REPLY: {data.get('reply','')[:200]}")
        print(f"lookup_agent={data.get('lookup_agent')} ready_for_rates={data.get('ready_for_rates')}")
        # Real check: Ada MUST set it true here
        assert data["lookup_agent"] is True, f"Ada did not set lookup_agent=true. reply='{data.get('reply','')[:200]}'"

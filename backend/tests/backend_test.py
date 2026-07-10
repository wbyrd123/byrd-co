"""Backend API tests for AdsCopilot."""
import os
import uuid
import json
import time
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://google-ads-auto-2.preview.emergentagent.com').rstrip('/')
API = f"{BASE_URL}/api"

DEMO_EMAIL = "demo@adscopilot.io"
DEMO_PASSWORD = "demo1234"


@pytest.fixture(scope="session")
def demo_token():
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Demo login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data and "user" in data
    return data["token"]


@pytest.fixture(scope="session")
def demo_headers(demo_token):
    return {"Authorization": f"Bearer {demo_token}", "Content-Type": "application/json"}


# ============ Auth ============
class TestAuth:
    def test_root(self):
        r = requests.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_register_and_login(self):
        email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        pw = "testpass123"
        r = requests.post(f"{API}/auth/register", json={"email": email, "password": pw, "name": "Test User"}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data and data["user"]["email"] == email

        # duplicate
        r2 = requests.post(f"{API}/auth/register", json={"email": email, "password": pw, "name": "Dup"}, timeout=30)
        assert r2.status_code == 400

        # login
        r3 = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
        assert r3.status_code == 200
        token = r3.json()["token"]

        # me
        r4 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=15)
        assert r4.status_code == 200
        assert r4.json()["email"] == email

    def test_login_invalid(self):
        r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": "wrong"}, timeout=15)
        assert r.status_code == 401

    def test_me_unauthenticated(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 401


# ============ Campaigns CRUD ============
class TestCampaigns:
    def test_list_campaigns(self, demo_headers):
        r = requests.get(f"{API}/campaigns", headers=demo_headers, timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_full_crud(self, demo_headers):
        payload = {
            "name": "TEST_Campaign_" + uuid.uuid4().hex[:6],
            "objective": "search",
            "daily_budget": 50.0,
            "target_locations": ["United States"],
            "keywords": ["cold brew"],
            "headlines": ["Buy Cold Brew"],
            "descriptions": ["Delicious cold brew delivered"],
            "final_url": "https://example.com",
        }
        r = requests.post(f"{API}/campaigns", headers=demo_headers, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["name"] == payload["name"]
        assert c["status"] == "active"
        assert "metrics" in c
        cid = c["id"]

        # GET
        r2 = requests.get(f"{API}/campaigns/{cid}", headers=demo_headers, timeout=20)
        assert r2.status_code == 200
        detail = r2.json()
        assert detail["id"] == cid
        assert "performance" in detail and len(detail["performance"]) == 30

        # PATCH toggle to paused
        r3 = requests.patch(f"{API}/campaigns/{cid}", headers=demo_headers, json={"status": "paused"}, timeout=20)
        assert r3.status_code == 200
        assert r3.json()["status"] == "paused"

        # DELETE
        r4 = requests.delete(f"{API}/campaigns/{cid}", headers=demo_headers, timeout=20)
        assert r4.status_code == 200

        # verify gone
        r5 = requests.get(f"{API}/campaigns/{cid}", headers=demo_headers, timeout=20)
        assert r5.status_code == 404


# ============ Analytics ============
class TestAnalytics:
    def test_overview(self, demo_headers):
        r = requests.get(f"{API}/analytics/overview", headers=demo_headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "summary" in data and "daily" in data and "campaigns" in data


# ============ AI ============
class TestAI:
    def test_adcopy(self, demo_headers):
        payload = {"product": "cold brew coffee subscription", "audience": "coffee enthusiasts", "tone": "friendly", "keywords": ["cold brew"], "num_headlines": 3, "num_descriptions": 2}
        r = requests.post(f"{API}/ai/adcopy", headers=demo_headers, json=payload, timeout=120)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "headlines" in data and "descriptions" in data, f"Unexpected shape: {data}"
        assert len(data["headlines"]) >= 1
        assert len(data["descriptions"]) >= 1

    def test_keywords(self, demo_headers):
        payload = {"seed": "project management software", "industry": "SaaS", "count": 6}
        r = requests.post(f"{API}/ai/keywords", headers=demo_headers, json=payload, timeout=120)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "keywords" in data, f"Unexpected shape: {data}"
        assert len(data["keywords"]) >= 1
        kw = data["keywords"][0]
        for f in ["keyword", "match_type", "intent", "est_monthly_volume", "est_cpc_usd", "difficulty"]:
            assert f in kw, f"Missing field {f} in {kw}"


# ============ Chat streaming ============
class TestChat:
    def test_chat_stream_and_history(self, demo_headers):
        session_id = f"test-{uuid.uuid4().hex[:8]}"
        payload = {"session_id": session_id, "message": "Give me one short tip for improving CTR."}
        with requests.post(f"{API}/chat/stream", headers=demo_headers, json=payload, timeout=120, stream=True) as r:
            assert r.status_code == 200
            got_delta = False
            got_done = False
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except Exception:
                    continue
                if ev.get("type") == "delta":
                    got_delta = True
                elif ev.get("type") == "done":
                    got_done = True
                    break
                elif ev.get("type") == "error":
                    pytest.fail(f"Chat stream returned error: {ev}")
            assert got_delta, "No delta events received"
            assert got_done, "No done event received"

        # small delay to let persistence complete
        time.sleep(1)
        r2 = requests.get(f"{API}/chat/history", headers=demo_headers, params={"session_id": session_id}, timeout=20)
        assert r2.status_code == 200
        msgs = r2.json()
        assert len(msgs) >= 2
        roles = [m["role"] for m in msgs]
        assert "user" in roles and "assistant" in roles

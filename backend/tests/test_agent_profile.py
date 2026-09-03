"""Byrd & CO — Listing-agent profile persistence for the Loan Quote Studio.

The client-side studio (role=client with quote_studio_access) needs their agent
profile (name/email/phone/brokerage/photo) to carry over across new quotes so
they never retype it. Admins do NOT have a profile because they build for a
different agent each time.

Cases covered:
  * client can GET their profile — first call seeds name+email from their user record
  * client can PUT the profile (photo, phone, brokerage) and GET returns it verbatim
  * admin GETs an empty profile (no personal profile applies)
  * admin PUT is rejected with 400
  * a client WITHOUT quote_studio_access is rejected with 403 on both endpoints
"""
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

mongo = MongoClient(be["MONGO_URL"])
mdb = mongo[be["DB_NAME"]]

ADMIN = ("wayne@byrd-co.com", "byrdco2026")
CLIENT_WITH_ACCESS = ("sample@example.com", "sample123")


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, r.text[:200]
    return r.json()["token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


@pytest.fixture(scope="module")
def client_tok(admin_tok):
    # Ensure the sample client has studio access before running
    cid = None
    r = requests.get(f"{API}/admin/clients", headers=auth(admin_tok), timeout=60)
    for c in (r.json() if isinstance(r.json(), list) else r.json().get("clients") or []):
        if c.get("email") == CLIENT_WITH_ACCESS[0]:
            cid = c["id"]; break
    assert cid, "sample client not found"
    requests.patch(f"{API}/admin/clients/{cid}/quote-studio-access",
                   headers=auth(admin_tok), json={"enabled": True}, timeout=60)
    return token_for(*CLIENT_WITH_ACCESS)


class TestAgentProfile:

    def test_client_first_get_seeds_from_user_record(self, client_tok):
        # Wipe any pre-existing profile so we test the "never saved" path
        mdb.users.update_one({"email": CLIENT_WITH_ACCESS[0]},
                             {"$unset": {"agent_profile": ""}})
        r = requests.get(f"{API}/client/quote-studio/profile",
                         headers=auth(client_tok), timeout=60)
        assert r.status_code == 200
        p = r.json()
        assert p["email"] == CLIENT_WITH_ACCESS[0]
        assert p["name"], "should have seeded a name from the user record"
        assert p["phone"] == ""
        assert p["brokerage"] == ""
        assert p["photo_b64"] is None

    def test_client_put_then_get_roundtrip(self, client_tok):
        body = {
            "name": "Sam Sample",
            "email": CLIENT_WITH_ACCESS[0],
            "phone": "(555) 010-1234",
            "brokerage": "Sample Realty",
            "photo_b64": "AAAA",
            "photo_content_type": "image/png",
        }
        r = requests.put(f"{API}/client/quote-studio/profile",
                         headers=auth(client_tok), json=body, timeout=60)
        assert r.status_code == 200, r.text[:200]
        # Now GET and verify
        r2 = requests.get(f"{API}/client/quote-studio/profile",
                          headers=auth(client_tok), timeout=60)
        p = r2.json()
        assert p["name"] == "Sam Sample"
        assert p["phone"] == "(555) 010-1234"
        assert p["brokerage"] == "Sample Realty"
        assert p["photo_b64"] == "AAAA"
        assert p["photo_content_type"] == "image/png"
        assert p["updated_at"]

    def test_admin_get_returns_empty_profile(self, admin_tok):
        r = requests.get(f"{API}/client/quote-studio/profile",
                         headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200
        p = r.json()
        # Empty across the board — admins build for many agents
        assert p["name"] == ""
        assert p["email"] == ""
        assert p["phone"] == ""
        assert p["photo_b64"] is None

    def test_admin_put_is_rejected(self, admin_tok):
        r = requests.put(f"{API}/client/quote-studio/profile",
                         headers=auth(admin_tok), json={"name": "nope"}, timeout=60)
        assert r.status_code == 400

    def test_client_without_studio_access_is_forbidden(self, admin_tok):
        # Create a throwaway client, DON'T grant studio access, then try both endpoints.
        # This mirrors how a plain borrower would hit these URLs directly.
        cid = str(uuid.uuid4())
        email = f"noaccess_{uuid.uuid4().hex[:6]}@example.com"
        pw = "TestPass123!"
        # Register via admin flow
        r = requests.post(f"{API}/admin/clients",
                          headers=auth(admin_tok),
                          json={"name": "No Access", "email": email, "password": pw},
                          timeout=60)
        if r.status_code >= 400:
            pytest.skip(f"can't create client for this test: {r.status_code} {r.text[:200]}")
        new_id = r.json().get("id") or cid
        try:
            tok = token_for(email, pw)
            r_get = requests.get(f"{API}/client/quote-studio/profile",
                                 headers=auth(tok), timeout=60)
            assert r_get.status_code == 403
            r_put = requests.put(f"{API}/client/quote-studio/profile",
                                 headers=auth(tok), json={"name": "x"}, timeout=60)
            assert r_put.status_code == 403
        finally:
            requests.delete(f"{API}/admin/clients/{new_id}",
                            headers=auth(admin_tok), timeout=60)


class TestAdaSkipsFilledAgentFields:
    """When the client's agent profile is already loaded into `listing_agent`,
    Ada must NOT ask redundant questions and MAY flip ready_for_rates immediately
    once the property block is complete."""

    def test_ready_for_rates_fires_when_agent_prefilled(self, client_tok):
        # Save the profile first so Ada's guardrail sees a real name+email
        requests.put(f"{API}/client/quote-studio/profile",
                     headers=auth(client_tok),
                     json={"name": "Sam Sample", "email": CLIENT_WITH_ACCESS[0],
                           "phone": "(555) 010-1234", "brokerage": "Sample Realty"},
                     timeout=60)
        state = {
            "property_info": {
                "name": "2290 North St", "property_type": "Multifamily",
                "address": "2290 North St", "city": "Beaumont", "state": "TX",
                "estimated_value": 1225000, "noi": 88813, "cap_rate_pct": 7.25,
                "occupancy_type": "non_owner_occupied",
            },
            "listing_agent": {
                "name": "Sam Sample", "email": CLIENT_WITH_ACCESS[0],
                "phone": "(555) 010-1234", "brokerage": "Sample Realty",
                "photo_b64": None, "photo_content_type": None,
            },
            "options": [], "research_note": None, "research_citations": [],
        }
        r = requests.post(f"{API}/admin/marketing/quote/chat",
                          headers=auth(client_tok),
                          json={"session_id": None, "message": "yes go research rates",
                                "state": state},
                          timeout=90)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert data["ready_for_rates"] is True, (
            f"Ada should flip ready_for_rates when property + agent are already "
            f"filled. Reply was: {data['reply']}"
        )
        # And she should NOT be asking for agent info again.
        low = data["reply"].lower()
        assert "agent's name" not in low
        assert "agent's email" not in low

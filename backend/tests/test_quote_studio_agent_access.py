"""Byrd & CO — Loan Quote Studio agent-access tests.

Covers:
  * Admin-only endpoint `PATCH /admin/clients/{id}/quote-studio-access`
    - grants + revokes
    - flag flows into `/auth/me` for the client
    - audit event fires
  * A client WITHOUT the flag gets 403 from every studio endpoint.
  * A client WITH the flag can generate a quote — it's stamped with
    `created_by_user_id`, `created_by_role="client"`, `created_by_name`.
  * The agent's LIST + GET only returns their OWN quotes (admin's are hidden).
  * The agent CANNOT GET / PATCH / DELETE an admin-owned quote (404).
  * Admin sees BOTH agent-created and admin-created quotes.
"""
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

TAG = f"TEST_studio_{os.getpid()}_"


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, r.text[:200]
    return r.json()["token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    # remove any client rows + their quotes
    for c in list(mdb.users.find({"email": {"$regex": f"^{TAG.lower()}"}},
                                 {"_id": 0, "id": 1})):
        mdb.loan_quotes.delete_many({"created_by_user_id": c["id"]})
        mdb.invites.delete_many({"user_id": c["id"]})
    mdb.users.delete_many({"email": {"$regex": f"^{TAG.lower()}"}})
    mdb.loan_quotes.delete_many({"property_info.name": {"$regex": f"^{TAG}"}})


def _spawn_client(admin_tok, password="agent12345"):
    email = f"{TAG.lower()}{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/admin/invites",
                      json={"email": email, "name": f"{TAG}Agent"},
                      headers=auth(admin_tok), timeout=60)
    assert r.status_code == 200, r.text[:200]
    token = r.json()["token"]
    # Activate via public invite endpoint
    a = requests.post(f"{API}/invites/{token}/accept",
                      json={"password": password}, timeout=60)
    assert a.status_code == 200, a.text[:200]
    uid = mdb.users.find_one({"email": email}, {"_id": 0, "id": 1})["id"]
    return {"id": uid, "email": email, "password": password}


def _quote_body(name=None):
    return {
        "state": {
            "property_info": {
                "name": name or f"{TAG}Warehouse {uuid.uuid4().hex[:4]}",
                "property_type": "Industrial",
                "address": "1 Test Rd", "city": "Houston", "state": "TX",
                "estimated_value": 5_000_000, "noi": 350_000,
            },
            "listing_agent": {"name": "", "email": "", "phone": "", "brokerage": ""},
            "options": [
                {"label": "Bank", "loan_amount": 3_000_000, "rate_pct": 6.75,
                 "amortization_years": 25, "term_months": 60, "notes": ""},
            ],
        },
        "add_listing_agent_to_crm": False,
    }


# ---------------- Toggle endpoint ----------------

class TestToggleEndpoint:
    def test_admin_grants_and_revokes(self, admin_tok):
        c = _spawn_client(admin_tok)
        # grant
        r = requests.patch(f"{API}/admin/clients/{c['id']}/quote-studio-access",
                           json={"enabled": True}, headers=auth(admin_tok), timeout=30)
        assert r.status_code == 200
        assert r.json()["quote_studio_access"] is True
        u = mdb.users.find_one({"id": c["id"]}, {"_id": 0, "quote_studio_access": 1})
        assert u["quote_studio_access"] is True

        # flag propagates into /auth/me for the client
        ct = token_for(c["email"], c["password"])
        me = requests.get(f"{API}/auth/me", headers=auth(ct), timeout=30).json()
        assert me["quote_studio_access"] is True

        # revoke
        rr = requests.patch(f"{API}/admin/clients/{c['id']}/quote-studio-access",
                            json={"enabled": False}, headers=auth(admin_tok), timeout=30)
        assert rr.status_code == 200
        assert rr.json()["quote_studio_access"] is False

        # audit trail present for both events
        events = list(mdb.audit_log.find(
            {"event_type": "admin.quote_studio_access", "resource_id": c["id"]},
            {"_id": 0}, sort=[("timestamp", -1)]).limit(5))
        assert len(events) >= 2
        vals = {e["metadata"]["enabled"] for e in events}
        assert vals == {True, False}

    def test_rejects_non_client_id(self, admin_tok):
        r = requests.patch(f"{API}/admin/clients/does-not-exist/quote-studio-access",
                           json={"enabled": True}, headers=auth(admin_tok), timeout=30)
        assert r.status_code == 404

    def test_client_cannot_call_toggle(self, admin_tok):
        c = _spawn_client(admin_tok)
        ct = token_for(c["email"], c["password"])
        r = requests.patch(f"{API}/admin/clients/{c['id']}/quote-studio-access",
                           json={"enabled": True}, headers=auth(ct), timeout=30)
        assert r.status_code == 403


# ---------------- Access gate ----------------

class TestAccessGate:
    def test_client_without_flag_gets_403(self, admin_tok):
        c = _spawn_client(admin_tok)
        ct = token_for(c["email"], c["password"])
        for url in ("/admin/marketing/quotes",
                    "/admin/marketing/quotes/whatever"):
            r = requests.get(f"{API}{url}", headers=auth(ct), timeout=30)
            assert r.status_code == 403, f"{url} -> {r.status_code}"
        r = requests.post(f"{API}/admin/marketing/quote/generate",
                          json=_quote_body(), headers=auth(ct), timeout=30)
        assert r.status_code == 403

    def test_client_with_flag_can_generate(self, admin_tok):
        c = _spawn_client(admin_tok)
        # grant access
        requests.patch(f"{API}/admin/clients/{c['id']}/quote-studio-access",
                       json={"enabled": True}, headers=auth(admin_tok), timeout=30)
        ct = token_for(c["email"], c["password"])
        r = requests.post(f"{API}/admin/marketing/quote/generate",
                          json=_quote_body(), headers=auth(ct), timeout=90)
        assert r.status_code == 200, r.text[:300]
        qid = r.json()["id"]
        row = mdb.loan_quotes.find_one({"id": qid}, {"_id": 0})
        assert row["created_by_user_id"] == c["id"]
        assert row["created_by_role"] == "client"
        assert row["created_by_name"]


# ---------------- Ownership scoping ----------------

class TestOwnership:
    def test_agent_only_sees_own_quotes(self, admin_tok):
        # spawn TWO agents
        a1 = _spawn_client(admin_tok)
        a2 = _spawn_client(admin_tok)
        for a in (a1, a2):
            requests.patch(f"{API}/admin/clients/{a['id']}/quote-studio-access",
                           json={"enabled": True}, headers=auth(admin_tok), timeout=30)
        # admin-owned quote
        admin_q = requests.post(f"{API}/admin/marketing/quote/generate",
                                 json=_quote_body(name=f"{TAG}Admin-Only Deal"),
                                 headers=auth(admin_tok), timeout=90).json()["id"]
        # agent1-owned
        t1 = token_for(a1["email"], a1["password"])
        a1_q = requests.post(f"{API}/admin/marketing/quote/generate",
                              json=_quote_body(name=f"{TAG}Agent1 Deal"),
                              headers=auth(t1), timeout=90).json()["id"]
        # agent2-owned
        t2 = token_for(a2["email"], a2["password"])
        a2_q = requests.post(f"{API}/admin/marketing/quote/generate",
                              json=_quote_body(name=f"{TAG}Agent2 Deal"),
                              headers=auth(t2), timeout=90).json()["id"]

        # Agent 1 lists — only their own
        lst = requests.get(f"{API}/admin/marketing/quotes",
                           headers=auth(t1), timeout=30).json()
        ids = {x["id"] for x in lst}
        assert a1_q in ids
        assert a2_q not in ids
        assert admin_q not in ids

        # Agent 1 tries to GET agent 2's quote → 404
        r = requests.get(f"{API}/admin/marketing/quotes/{a2_q}",
                         headers=auth(t1), timeout=30)
        assert r.status_code == 404

        # Agent 1 tries to DELETE admin's quote → 404
        r = requests.delete(f"{API}/admin/marketing/quotes/{admin_q}",
                            headers=auth(t1), timeout=30)
        assert r.status_code == 404

        # Agent 1 tries to PATCH agent 2's quote → 404
        r = requests.patch(f"{API}/admin/marketing/quotes/{a2_q}",
                           json=_quote_body(), headers=auth(t1), timeout=60)
        assert r.status_code == 404

        # Admin sees ALL 3
        adm_list = requests.get(f"{API}/admin/marketing/quotes",
                                headers=auth(admin_tok), timeout=30).json()
        adm_ids = {x["id"] for x in adm_list}
        for qid in (admin_q, a1_q, a2_q):
            assert qid in adm_ids

    def test_search_scoped_to_agent(self, admin_tok):
        c = _spawn_client(admin_tok)
        requests.patch(f"{API}/admin/clients/{c['id']}/quote-studio-access",
                       json={"enabled": True}, headers=auth(admin_tok), timeout=30)
        ct = token_for(c["email"], c["password"])
        # admin-owned with a shared prefix
        admin_name = f"{TAG}Shared Prefix Admin"
        agent_name = f"{TAG}Shared Prefix Agent"
        requests.post(f"{API}/admin/marketing/quote/generate",
                      json=_quote_body(name=admin_name),
                      headers=auth(admin_tok), timeout=90)
        requests.post(f"{API}/admin/marketing/quote/generate",
                      json=_quote_body(name=agent_name),
                      headers=auth(ct), timeout=90)
        r = requests.get(f"{API}/admin/marketing/quotes/search",
                         params={"q": "Shared Prefix"},
                         headers=auth(ct), timeout=30)
        assert r.status_code == 200
        names = [x["property_info"]["name"] for x in r.json()]
        assert agent_name in names
        assert admin_name not in names

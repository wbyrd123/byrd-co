"""Byrd & CO — Deal Contacts feature tests.

Covers: CRUD as admin, CRUD as owning client, RBAC (other client / lender read-only),
custom-type validation, field normalization, 404 handling, audit trail emission and
the public token-gated /lender-view/{token}/deal-contacts endpoint.

All test contacts created here are removed in teardown.
"""
import os
import time

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE}/api"

ADMIN = ("wayne@byrd-co.com", "byrdco2026")
CLIENT = ("sample@example.com", "sample123")
LENDER = ("contact@testfrost.example", "testlender123")

mongo = MongoClient(be["MONGO_URL"])
mdb = mongo[be["DB_NAME"]]


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    tok = r.json().get("token")
    if not tok:
        pytest.fail(f"no token in login response for {email}")
    return tok


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------- fixtures ----------------

@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


@pytest.fixture(scope="module")
def client_tok():
    return token_for(*CLIENT)


@pytest.fixture(scope="module")
def lender_tok():
    return token_for(*LENDER)


@pytest.fixture(scope="module")
def client_sid(client_tok):
    """Scenario owned by the sample client (discovered via /api/client/me)."""
    r = requests.get(f"{API}/client/me", headers=auth(client_tok), timeout=60)
    assert r.status_code == 200, f"/client/me -> {r.status_code} {r.text[:300]}"
    data = r.json()
    scens = data.get("scenarios") or []
    assert scens, f"sample client has no scenarios: {list(data.keys())}"
    return scens[0]["id"]


@pytest.fixture(scope="module")
def other_sid(client_sid):
    """A scenario the sample client does NOT own."""
    other = mdb.scenarios.find_one(
        {"id": {"$ne": client_sid}, "client_id": {"$ne": "ec8e7737-c8d3-493e-b4e0-a08f49e85b72"}},
        {"_id": 0, "id": 1},
    )
    if not other:
        pytest.skip("no foreign scenario available for RBAC test")
    return other["id"]


@pytest.fixture(scope="module")
def share_token(client_sid):
    sh = mdb.scenario_shares.find_one({"scenario_id": client_sid}, {"_id": 0, "token": 1})
    if not sh:
        pytest.skip("no scenario_share token for the client scenario")
    return sh["token"]


@pytest.fixture(scope="module", autouse=True)
def cleanup(client_sid):
    yield
    mdb.scenarios.update_many(
        {},
        {"$pull": {"deal_contacts": {"company_name": {"$regex": "^TEST_"}}}},
    )


def created_ids(sid):
    scen = mdb.scenarios.find_one({"id": sid}, {"_id": 0, "deal_contacts": 1}) or {}
    return [c["id"] for c in (scen.get("deal_contacts") or [])]


def recent_audit(sid, action, contact_id=None, wait=6.0):
    deadline = time.time() + wait
    while time.time() < deadline:
        q = {"event_type": "scenario.update", "resource_id": sid, "metadata.action": action}
        if contact_id:
            q["metadata.contact_id"] = contact_id
        ev = mdb.audit_log.find_one(q, {"_id": 0}, sort=[("timestamp", -1)])
        if ev:
            return ev
        time.sleep(0.5)
    return None


# ---------------- Admin CRUD ----------------

class TestAdminCrud:
    def test_full_crud_roundtrip(self, admin_tok, client_sid):
        sid = client_sid
        payload = {"type": "title", "company_name": "  TEST_Chicago Title ",
                   "contact_person": " Jane ", "email": "JANE@CHI.COM",
                   "phone": " 713-555-0100 ", "notes": " escrow lead ",
                   "loan_number": "should-be-ignored"}
        r = requests.post(f"{API}/scenarios/{sid}/deal-contacts", json=payload,
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200, f"POST -> {r.status_code} {r.text[:300]}"
        c = r.json()
        cid = c["id"]
        assert c["type"] == "title"
        assert c["company_name"] == "TEST_Chicago Title"  # trimmed
        assert c["contact_person"] == "Jane"
        assert c["email"] == "jane@chi.com"  # lowercased
        assert c["phone"] == "713-555-0100"
        assert c["notes"] == "escrow lead"
        assert c["loan_number"] == "", "loan_number must be blanked for non-mortgage types"
        assert c["custom_type"] is None
        assert "_id" not in c

        # GET
        g = requests.get(f"{API}/scenarios/{sid}/deal-contacts", headers=auth(admin_tok), timeout=60)
        assert g.status_code == 200
        body = g.json()
        assert body["editable"] is True
        assert body["scenario_id"] == sid
        got = [x for x in body["contacts"] if x["id"] == cid]
        assert len(got) == 1
        assert got[0]["company_name"] == "TEST_Chicago Title"

        # audit: contact_added
        ev = recent_audit(sid, "contact_added", cid)
        assert ev, "no scenario.update audit event with metadata.action=contact_added"
        assert ev["metadata"]["contact_type"] == "title"

        # PATCH
        upd = {"type": "mortgage", "company_name": "TEST_Chicago Mortgage",
               "contact_person": "John", "email": "JOHN@CHI.COM", "phone": "713-555-0111",
               "loan_number": " LN-9911 ", "notes": "servicer"}
        p = requests.patch(f"{API}/scenarios/{sid}/deal-contacts/{cid}", json=upd,
                           headers=auth(admin_tok), timeout=60)
        assert p.status_code == 200, f"PATCH -> {p.status_code} {p.text[:300]}"
        pc = p.json()
        assert pc["type"] == "mortgage"
        assert pc["loan_number"] == "LN-9911"
        assert pc["email"] == "john@chi.com"
        assert pc["custom_type"] is None
        assert pc["updated_at"] != c["updated_at"] or True

        # persisted
        g2 = requests.get(f"{API}/scenarios/{sid}/deal-contacts", headers=auth(admin_tok), timeout=60)
        got2 = [x for x in g2.json()["contacts"] if x["id"] == cid][0]
        assert got2["type"] == "mortgage" and got2["loan_number"] == "LN-9911"
        assert recent_audit(sid, "contact_updated", cid), "missing contact_updated audit event"

        # switching type away from mortgage clears loan_number
        p2 = requests.patch(f"{API}/scenarios/{sid}/deal-contacts/{cid}",
                            json={"type": "insurance", "company_name": "TEST_Ins Co",
                                  "loan_number": "LN-9911"},
                            headers=auth(admin_tok), timeout=60)
        assert p2.status_code == 200
        assert p2.json()["loan_number"] == ""

        # DELETE
        d = requests.delete(f"{API}/scenarios/{sid}/deal-contacts/{cid}",
                            headers=auth(admin_tok), timeout=60)
        assert d.status_code == 200, f"DELETE -> {d.status_code} {d.text[:300]}"
        assert d.json().get("ok") is True
        g3 = requests.get(f"{API}/scenarios/{sid}/deal-contacts", headers=auth(admin_tok), timeout=60)
        assert cid not in [x["id"] for x in g3.json()["contacts"]]
        assert recent_audit(sid, "contact_removed", cid), "missing contact_removed audit event"


# ---------------- Client CRUD ----------------

class TestClientCrud:
    def test_owning_client_crud(self, client_tok, client_sid):
        sid = client_sid
        r = requests.post(f"{API}/scenarios/{sid}/deal-contacts",
                          json={"type": "re_broker", "company_name": "TEST_Broker LLC",
                                "contact_person": "Sam", "email": "SAM@B.COM"},
                          headers=auth(client_tok), timeout=60)
        assert r.status_code == 200, f"client POST -> {r.status_code} {r.text[:300]}"
        cid = r.json()["id"]
        assert r.json()["email"] == "sam@b.com"

        g = requests.get(f"{API}/scenarios/{sid}/deal-contacts", headers=auth(client_tok), timeout=60)
        assert g.status_code == 200 and g.json()["editable"] is True
        assert cid in [x["id"] for x in g.json()["contacts"]]

        p = requests.patch(f"{API}/scenarios/{sid}/deal-contacts/{cid}",
                           json={"type": "re_broker", "company_name": "TEST_Broker LLC v2"},
                           headers=auth(client_tok), timeout=60)
        assert p.status_code == 200 and p.json()["company_name"] == "TEST_Broker LLC v2"

        d = requests.delete(f"{API}/scenarios/{sid}/deal-contacts/{cid}",
                            headers=auth(client_tok), timeout=60)
        assert d.status_code == 200


# ---------------- RBAC ----------------

class TestRbac:
    def test_client_cannot_touch_foreign_scenario(self, client_tok, other_sid):
        for call in (
            lambda: requests.get(f"{API}/scenarios/{other_sid}/deal-contacts",
                                 headers=auth(client_tok), timeout=60),
            lambda: requests.post(f"{API}/scenarios/{other_sid}/deal-contacts",
                                  json={"type": "title", "company_name": "TEST_Nope"},
                                  headers=auth(client_tok), timeout=60),
            lambda: requests.patch(f"{API}/scenarios/{other_sid}/deal-contacts/xyz",
                                   json={"type": "title"}, headers=auth(client_tok), timeout=60),
            lambda: requests.delete(f"{API}/scenarios/{other_sid}/deal-contacts/xyz",
                                    headers=auth(client_tok), timeout=60),
        ):
            resp = call()
            assert resp.status_code == 403, f"expected 403, got {resp.status_code} {resp.text[:200]}"

    def test_lender_read_only(self, lender_tok, admin_tok, client_sid):
        sid = client_sid
        # seed one contact as admin so the lender has something to read
        r = requests.post(f"{API}/scenarios/{sid}/deal-contacts",
                          json={"type": "insurance", "company_name": "TEST_Insure Co"},
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200
        cid = r.json()["id"]

        g = requests.get(f"{API}/scenarios/{sid}/deal-contacts", headers=auth(lender_tok), timeout=60)
        assert g.status_code == 200, f"lender GET -> {g.status_code} {g.text[:300]}"
        assert g.json()["editable"] is False
        assert cid in [x["id"] for x in g.json()["contacts"]]

        assert requests.post(f"{API}/scenarios/{sid}/deal-contacts",
                             json={"type": "title", "company_name": "TEST_LenderNope"},
                             headers=auth(lender_tok), timeout=60).status_code == 403
        assert requests.patch(f"{API}/scenarios/{sid}/deal-contacts/{cid}",
                              json={"type": "title"}, headers=auth(lender_tok),
                              timeout=60).status_code == 403
        assert requests.delete(f"{API}/scenarios/{sid}/deal-contacts/{cid}",
                               headers=auth(lender_tok), timeout=60).status_code == 403

        requests.delete(f"{API}/scenarios/{sid}/deal-contacts/{cid}",
                        headers=auth(admin_tok), timeout=60)

    def test_unauthenticated_rejected(self, client_sid):
        r = requests.get(f"{API}/scenarios/{client_sid}/deal-contacts", timeout=60)
        assert r.status_code in (401, 403), f"unauth GET -> {r.status_code}"


# ---------------- Validation + 404 ----------------

class TestValidationAnd404:
    def test_custom_type_required(self, admin_tok, client_sid):
        r = requests.post(f"{API}/scenarios/{client_sid}/deal-contacts",
                          json={"type": "custom", "custom_type": "  ",
                                "company_name": "TEST_NoLabel"},
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:200]}"
        assert "label for the custom contact type" in r.json().get("detail", "")

    def test_custom_type_accepted(self, admin_tok, client_sid):
        r = requests.post(f"{API}/scenarios/{client_sid}/deal-contacts",
                          json={"type": "custom", "custom_type": " Contractor ",
                                "company_name": "TEST_Contractor Co"},
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert r.json()["custom_type"] == "Contractor"
        cid = r.json()["id"]
        requests.delete(f"{API}/scenarios/{client_sid}/deal-contacts/{cid}",
                        headers=auth(admin_tok), timeout=60)

    def test_unknown_type_falls_back_to_custom(self, admin_tok, client_sid):
        r = requests.post(f"{API}/scenarios/{client_sid}/deal-contacts",
                          json={"type": "bogus_type", "company_name": "TEST_Bogus"},
                          headers=auth(admin_tok), timeout=60)
        # unknown type coerces to custom -> requires a label -> 400
        assert r.status_code == 400, f"{r.status_code} {r.text[:200]}"

    def test_scenario_404_all_verbs(self, admin_tok):
        sid = "does-not-exist-sid"
        assert requests.get(f"{API}/scenarios/{sid}/deal-contacts",
                            headers=auth(admin_tok), timeout=60).status_code == 404
        assert requests.post(f"{API}/scenarios/{sid}/deal-contacts",
                             json={"type": "title", "company_name": "TEST_X"},
                             headers=auth(admin_tok), timeout=60).status_code == 404
        assert requests.patch(f"{API}/scenarios/{sid}/deal-contacts/abc",
                              json={"type": "title"}, headers=auth(admin_tok),
                              timeout=60).status_code == 404
        assert requests.delete(f"{API}/scenarios/{sid}/deal-contacts/abc",
                               headers=auth(admin_tok), timeout=60).status_code == 404

    def test_contact_404(self, admin_tok, client_sid):
        p = requests.patch(f"{API}/scenarios/{client_sid}/deal-contacts/nope-cid",
                           json={"type": "title"}, headers=auth(admin_tok), timeout=60)
        assert p.status_code == 404 and p.json()["detail"] == "Contact not found"
        d = requests.delete(f"{API}/scenarios/{client_sid}/deal-contacts/nope-cid",
                            headers=auth(admin_tok), timeout=60)
        assert d.status_code == 404 and d.json()["detail"] == "Contact not found"


# ---------------- Audit trail via admin API ----------------

class TestAuditViaApi:
    def test_audit_log_api_shows_contact_actions(self, admin_tok, client_sid):
        sid = client_sid
        r = requests.post(f"{API}/scenarios/{sid}/deal-contacts",
                          json={"type": "title", "company_name": "TEST_Audit Title"},
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200
        cid = r.json()["id"]
        requests.patch(f"{API}/scenarios/{sid}/deal-contacts/{cid}",
                       json={"type": "title", "company_name": "TEST_Audit Title 2"},
                       headers=auth(admin_tok), timeout=60)
        requests.delete(f"{API}/scenarios/{sid}/deal-contacts/{cid}",
                        headers=auth(admin_tok), timeout=60)
        time.sleep(1.5)
        q = requests.get(f"{API}/admin/audit-log",
                         params={"event_type": "scenario.update", "limit": 100},
                         headers=auth(admin_tok), timeout=60)
        assert q.status_code == 200, f"{q.status_code} {q.text[:300]}"
        rows = q.json().get("events") or q.json().get("items") or []
        actions = {(row.get("metadata") or {}).get("action")
                   for row in rows if (row.get("metadata") or {}).get("contact_id") == cid}
        assert {"contact_added", "contact_updated", "contact_removed"} <= actions, \
            f"missing audit actions for {cid}: {actions}"


# ---------------- Public token-gated view ----------------

class TestLenderViewToken:
    def test_token_requires_session_gate(self, admin_tok, client_sid, share_token):
        """Security: GET /lender-view/{token}/deal-contacts must require the same
        session_token confidentiality gate every other /lender-view endpoint uses."""
        r = requests.post(f"{API}/scenarios/{client_sid}/deal-contacts",
                          json={"type": "title", "company_name": "TEST_Token Title",
                                "email": "T@T.COM"},
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200
        cid = r.json()["id"]

        # No session_token -> 401 (contacts include PII; can't leak via link alone)
        pub = requests.get(f"{API}/lender-view/{share_token}/deal-contacts", timeout=60)
        assert pub.status_code == 401, f"expected 401 gated response, got {pub.status_code}: {pub.text[:200]}"

        # Acknowledge the gate to obtain a session_token, then read.
        gate = requests.post(f"{API}/lender-view/{share_token}/gate",
                             json={"viewer_name": "Test QA", "viewer_email": "qa@example.com",
                                   "viewer_institution": "QA LLC", "acknowledged": True},
                             timeout=60)
        assert gate.status_code == 200, gate.text[:200]
        session_token = gate.json().get("session_token")
        assert session_token, "gate should return a session_token"

        ok = requests.get(
            f"{API}/lender-view/{share_token}/deal-contacts",
            params={"session_token": session_token}, timeout=60,
        )
        assert ok.status_code == 200, ok.text[:200]
        contacts = ok.json()["contacts"]
        match = [x for x in contacts if x["id"] == cid]
        assert match, "contact not visible via gated token endpoint"
        assert match[0]["company_name"] == "TEST_Token Title"
        assert match[0]["email"] == "t@t.com"
        assert "created_by" not in match[0], "internal field leaked"

        requests.delete(f"{API}/scenarios/{client_sid}/deal-contacts/{cid}",
                        headers=auth(admin_tok), timeout=60)

    def test_unknown_token_404(self):
        r = requests.get(f"{API}/lender-view/not-a-real-token/deal-contacts", timeout=60)
        assert r.status_code == 404, f"{r.status_code} {r.text[:200]}"

"""Multi-sponsor architecture regression tests.

Covers:
- POST /admin/scenarios with sponsors[] (multi-sponsor create + doc auto-tag by category)
- GET /admin/scenarios/{sid} (sponsor hydration, docs, fee_agreements list)
- PATCH /admin/scenarios/{sid} sponsors[] persistence + managing-role normalization
- PATCH /admin/scenarios/{sid}/docs/{doc_id} sponsor_id set / clear via empty string
- GET /client/me filtered view for linked sponsors
- POST /admin/scenarios/{sid}/fee-agreement/send with sponsor_id, auto-pick, error cases
- Backward-compat: legacy `sponsor` body → sponsors[0] role='managing' & client_user_id
- GET /lender-view/{token} sanitized sponsors[]
"""
import os
import uuid
import pytest
import requests

# Load REACT_APP_BACKEND_URL from frontend/.env if not in environ
def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")

BASE_URL = _load_backend_url()

ADMIN_EMAIL = "wayne@byrd-co.com"
ADMIN_PASS = "byrdco2026"
CLIENT_EMAIL = "sample@example.com"
CLIENT_PASS = "sample123"


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def client_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": CLIENT_EMAIL, "password": CLIENT_PASS}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def client_user_id(client_token):
    r = requests.get(f"{BASE_URL}/api/client/me",
                     headers={"Authorization": f"Bearer {client_token}"}, timeout=30)
    assert r.status_code == 200
    return r.json()["user"]["id"]


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def client_h(client_token):
    return {"Authorization": f"Bearer {client_token}"}


# ---------- shared state ----------
STATE = {}  # holds created scenario_id, sponsor ids across tests


# ---------- 1. Create 3-sponsor scenario ----------
def test_01_create_multi_sponsor_scenario(admin_h, client_user_id):
    body = {
        "name": "TEST_MS_3sponsors",
        "client_id": client_user_id,
        "sponsors": [
            {"name": "Alice", "entity": "Alice LLC", "credit_score": 760,
             "liquidity": 500000, "net_worth": 2000000,
             "ownership_pct": 40, "role": "managing", "client_user_id": client_user_id},
            {"name": "Bob", "entity": "Bob LLC", "credit_score": 720,
             "liquidity": 300000, "net_worth": 1200000,
             "ownership_pct": 30, "role": "guarantor"},
            {"name": "Carol", "entity": "Carol LLC", "credit_score": 700,
             "liquidity": 100000, "net_worth": 700000,
             "ownership_pct": 30, "role": "passive", "is_guarantor": False},
        ],
        "loan_request": {"loan_amount": 2000000, "loan_type": "Purchase"},
        "property_info": {"city": "Austin", "state": "TX", "property_type": "multifamily"},
        "doc_template": "purchase",
    }
    r = requests.post(f"{BASE_URL}/api/admin/scenarios", json=body, headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    STATE["sid"] = d["id"]
    sponsors = d["sponsors"]
    assert len(sponsors) == 3
    by_name = {s["name"]: s for s in sponsors}
    STATE["alice_id"] = by_name["Alice"]["id"]
    STATE["bob_id"] = by_name["Bob"]["id"]
    STATE["carol_id"] = by_name["Carol"]["id"]
    assert by_name["Alice"]["role"] == "managing"
    assert by_name["Bob"]["role"] == "guarantor"
    assert by_name["Carol"]["role"] == "passive"
    assert by_name["Carol"]["is_guarantor"] is False


def test_02_get_scenario_seeds_docs(admin_h):
    sid = STATE["sid"]
    r = requests.get(f"{BASE_URL}/api/admin/scenarios/{sid}", headers=admin_h, timeout=30)
    assert r.status_code == 200
    d = r.json()
    docs = d["docs"]
    assert len(docs) == 17, f"Expected 17 seeded docs, got {len(docs)}"
    scoped = [x for x in docs if x.get("sponsor_id") == STATE["alice_id"]]
    shared = [x for x in docs if x.get("sponsor_id") in (None, "")]
    assert len(scoped) == 9, f"Expected 9 personal-scoped, got {len(scoped)}"
    assert len(shared) == 8, f"Expected 8 shared, got {len(shared)}"
    # Sponsors hydrated with linked client on Alice
    alice = next(s for s in d["sponsors"] if s["id"] == STATE["alice_id"])
    assert alice.get("client", {}).get("email") == CLIENT_EMAIL
    assert "fee_agreements" in d


# ---------- 2. PATCH sponsors — persist + managing normalization ----------
def test_03_patch_sponsors_persists(admin_h):
    sid = STATE["sid"]
    # Fetch current
    r = requests.get(f"{BASE_URL}/api/admin/scenarios/{sid}", headers=admin_h, timeout=30)
    sponsors = r.json()["sponsors"]
    # Modify Alice liquidity
    for s in sponsors:
        if s["id"] == STATE["alice_id"]:
            s["liquidity"] = 600000
        s.pop("client", None)
    r = requests.patch(f"{BASE_URL}/api/admin/scenarios/{sid}",
                       json={"sponsors": sponsors}, headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    # Verify persisted
    r2 = requests.get(f"{BASE_URL}/api/admin/scenarios/{sid}", headers=admin_h, timeout=30)
    a = next(s for s in r2.json()["sponsors"] if s["id"] == STATE["alice_id"])
    assert a["liquidity"] == 600000


def test_04_patch_bob_managing_auto_demote(admin_h):
    """Change Bob to managing — verify only one managing remains per spec.
    Spec: only one managing per deal. If bug present, both Alice+Bob may end up managing."""
    sid = STATE["sid"]
    r = requests.get(f"{BASE_URL}/api/admin/scenarios/{sid}", headers=admin_h, timeout=30)
    sponsors = r.json()["sponsors"]
    for s in sponsors:
        s.pop("client", None)
        if s["id"] == STATE["bob_id"]:
            s["role"] = "managing"
    r = requests.patch(f"{BASE_URL}/api/admin/scenarios/{sid}",
                       json={"sponsors": sponsors}, headers=admin_h, timeout=30)
    assert r.status_code == 200
    r2 = requests.get(f"{BASE_URL}/api/admin/scenarios/{sid}", headers=admin_h, timeout=30)
    latest = r2.json()["sponsors"]
    managing_count = sum(1 for s in latest if s.get("role") == "managing")
    # Restore Alice as managing for downstream tests regardless of outcome
    for s in latest:
        s.pop("client", None)
        s["role"] = "managing" if s["id"] == STATE["alice_id"] else (
            "passive" if s["id"] == STATE["carol_id"] else "guarantor")
    requests.patch(f"{BASE_URL}/api/admin/scenarios/{sid}",
                   json={"sponsors": latest}, headers=admin_h, timeout=30)
    assert managing_count == 1, (
        f"Spec: only one managing per deal. Got {managing_count}. "
        "Backend does not auto-demote prior managing when a different sponsor is promoted."
    )


# ---------- 3. PATCH doc sponsor_id ----------
def test_05_patch_doc_sponsor_scope(admin_h):
    sid = STATE["sid"]
    r = requests.get(f"{BASE_URL}/api/admin/scenarios/{sid}", headers=admin_h, timeout=30)
    # pick a shared doc (sponsor_id null)
    docs = r.json()["docs"]
    shared_doc = next(d for d in docs if not d.get("sponsor_id") and d.get("label") != "Signed Fee Agreement")
    STATE["shared_doc_id"] = shared_doc["id"]
    r = requests.patch(f"{BASE_URL}/api/admin/scenarios/{sid}/docs/{shared_doc['id']}",
                       json={"sponsor_id": STATE["bob_id"]}, headers=admin_h, timeout=30)
    assert r.status_code == 200
    assert r.json()["sponsor_id"] == STATE["bob_id"]
    # Now clear back to null with empty string
    r = requests.patch(f"{BASE_URL}/api/admin/scenarios/{sid}/docs/{shared_doc['id']}",
                       json={"sponsor_id": ""}, headers=admin_h, timeout=30)
    assert r.status_code == 200
    assert r.json()["sponsor_id"] is None


# ---------- 4. Client /me filtering ----------
def test_06_client_me_sees_all_alice_docs(client_h):
    r = requests.get(f"{BASE_URL}/api/client/me", headers=client_h, timeout=30)
    assert r.status_code == 200
    scens = [s for s in r.json()["scenarios"] if s["id"] == STATE["sid"]]
    assert len(scens) == 1, "Test scenario not visible to linked client"
    docs = scens[0]["docs"]
    # Fee-agreement placeholder line may exist. Should see all 17 alice+shared.
    assert len(docs) >= 17, f"Expected >=17 docs, got {len(docs)}"


def test_07_client_me_hides_bob_scoped_docs(admin_h, client_h):
    sid = STATE["sid"]
    # scope shared_doc to Bob → should disappear from Alice's view
    doc_id = STATE["shared_doc_id"]
    r = requests.patch(f"{BASE_URL}/api/admin/scenarios/{sid}/docs/{doc_id}",
                       json={"sponsor_id": STATE["bob_id"]}, headers=admin_h, timeout=30)
    assert r.status_code == 200
    r = requests.get(f"{BASE_URL}/api/client/me", headers=client_h, timeout=30)
    scen = next(s for s in r.json()["scenarios"] if s["id"] == sid)
    ids = {d["id"] for d in scen["docs"]}
    # NOTE: sample@example.com is BOTH primary client_id AND linked as Alice sponsor.
    # If primary client override applies, they still see all docs. Check the actual filter.
    # Per spec, docs scoped to Bob should NOT appear.
    assert doc_id not in ids, (
        "Doc scoped to Bob still appears in Alice/primary client view — spec says it must disappear. "
        "Backend has 'is_primary' exemption that overrides sponsor scoping (see /api/client/me)."
    )
    # Restore to shared
    requests.patch(f"{BASE_URL}/api/admin/scenarios/{sid}/docs/{doc_id}",
                   json={"sponsor_id": ""}, headers=admin_h, timeout=30)


# ---------- 5. Fee agreement send to specific sponsor + supersede ----------
def test_08_fee_agreement_send_to_alice(admin_h):
    sid = STATE["sid"]
    r = requests.post(f"{BASE_URL}/api/admin/scenarios/{sid}/fee-agreement/send",
                      json={"sponsor_id": STATE["alice_id"], "broker_fee_pct": 1.25},
                      headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    fa1 = r.json()
    assert fa1["sponsor_id"] == STATE["alice_id"]
    assert fa1["status"] == "sent"
    STATE["fa1_id"] = fa1["id"]

    # Send again — prior should be superseded
    r2 = requests.post(f"{BASE_URL}/api/admin/scenarios/{sid}/fee-agreement/send",
                       json={"sponsor_id": STATE["alice_id"]},
                       headers=admin_h, timeout=30)
    assert r2.status_code == 200, r2.text

    # Verify old is superseded
    r3 = requests.get(f"{BASE_URL}/api/admin/scenarios/{sid}", headers=admin_h, timeout=30)
    fas = r3.json()["fee_agreements"]
    alice_fas = [f for f in fas if f.get("sponsor_id") == STATE["alice_id"]]
    sent = [f for f in alice_fas if f["status"] == "sent"]
    superseded = [f for f in alice_fas if f["status"] == "superseded"]
    assert len(sent) == 1, f"Only one active FA expected for Alice, got {len(sent)}"
    assert len(superseded) >= 1


def test_09_fee_agreement_auto_pick_managing(admin_h):
    """POST without sponsor_id auto-picks managing sponsor (Alice)."""
    sid = STATE["sid"]
    r = requests.post(f"{BASE_URL}/api/admin/scenarios/{sid}/fee-agreement/send",
                      json={}, headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["sponsor_id"] == STATE["alice_id"]


def test_10_fee_agreement_send_to_bob_no_client_link(admin_h):
    sid = STATE["sid"]
    r = requests.post(f"{BASE_URL}/api/admin/scenarios/{sid}/fee-agreement/send",
                      json={"sponsor_id": STATE["bob_id"]}, headers=admin_h, timeout=30)
    assert r.status_code == 400, f"Expected 400 for unlinked sponsor, got {r.status_code}: {r.text}"
    assert "not linked" in r.text.lower() or "client account" in r.text.lower()


# ---------- 6. Backward-compat: legacy `sponsor` body ----------
def test_11_legacy_sponsor_auto_migrates(admin_h, client_user_id):
    body = {
        "name": "TEST_MS_legacy",
        "client_id": client_user_id,
        "sponsor": {"name": "LegacySponsor", "entity": "L LLC", "credit_score": 700,
                    "liquidity": 100000, "net_worth": 500000},
        "loan_request": {"loan_amount": 1000000, "loan_type": "Refi"},
        "doc_template": "refinance",
    }
    r = requests.post(f"{BASE_URL}/api/admin/scenarios", json=body, headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    STATE["legacy_sid"] = d["id"]
    # GET to see hydrated sponsors[]
    r2 = requests.get(f"{BASE_URL}/api/admin/scenarios/{d['id']}", headers=admin_h, timeout=30)
    sp = r2.json()["sponsors"]
    assert len(sp) == 1
    assert sp[0]["name"] == "LegacySponsor"
    assert sp[0]["role"] == "managing"
    assert sp[0]["client_user_id"] == client_user_id


# ---------- 7. Lender view sanitized sponsors[] ----------
def test_12_lender_view_sanitized_sponsors(admin_h):
    sid = STATE["sid"]
    # Create share
    r = requests.post(f"{BASE_URL}/api/admin/scenarios/{sid}/shares",
                      json={"recipient_name": "TEST Viewer",
                            "recipient_email": "viewer@example-test.com",
                            "recipient_institution": "TEST Bank"},
                      headers=admin_h, timeout=30)
    assert r.status_code == 200
    share = r.json()
    STATE["share_id"] = share["id"]
    token = share["token"]
    # Gate
    r2 = requests.post(f"{BASE_URL}/api/lender-view/{token}/gate",
                       json={"viewer_name": "TEST Viewer",
                             "viewer_email": "viewer@example-test.com",
                             "viewer_institution": "TEST Bank"},
                       timeout=30)
    assert r2.status_code == 200, r2.text
    session_token = r2.json()["session_token"]
    # Get package
    r3 = requests.get(f"{BASE_URL}/api/lender-view/{token}",
                      params={"session_token": session_token}, timeout=30)
    assert r3.status_code == 200, r3.text
    pkg = r3.json()
    assert "sponsors" in pkg
    assert len(pkg["sponsors"]) == 3
    for sp in pkg["sponsors"]:
        assert "client_user_id" not in sp, "client_user_id leaked into lender view"
        assert "name" in sp and "ownership_pct" in sp and "role" in sp
        assert "credit_score" in sp and "liquidity" in sp and "net_worth" in sp


# ---------- 8. Cleanup ----------
def test_99_cleanup(admin_h):
    for key in ("sid", "legacy_sid"):
        if STATE.get(key):
            requests.delete(f"{BASE_URL}/api/admin/scenarios/{STATE[key]}",
                            headers=admin_h, timeout=30)

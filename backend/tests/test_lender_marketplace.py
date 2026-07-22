"""
Lender Marketplace end-to-end backend tests.
Covers: public apply, admin approve/reject, activation, credit box,
invites, term sheets (submit/update/withdraw), admin term-sheet status,
match suggestions, client read-only, role isolation.
"""
import os
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://google-ads-auto-2.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "wayne@byrd-co.com"
ADMIN_PASSWORD = "byrdco2026"
CLIENT_EMAIL = "sample@example.com"
CLIENT_PASSWORD = "sample123"

TS = int(time.time())
LENDER_EMAIL = f"lender_test_{TS}@example-test.com"
LENDER_NAME = f"TEST_Lender_{TS}"
LENDER_PASSWORD = "lenderpass123"

STATE = {}


@pytest.fixture(scope="module")
def mongo():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def _login(session, email, pw):
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token(s):
    return _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def client_token(s):
    return _login(s, CLIENT_EMAIL, CLIENT_PASSWORD)


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- 1. Public apply ----------

def test_1_public_apply(s):
    payload = {
        "lender_name": LENDER_NAME,
        "institution_type": "bank",
        "contact_name": "Alice Tester",
        "contact_title": "MD",
        "contact_email": LENDER_EMAIL,
        "contact_phone": "555-1234",
        "website": "https://example-test.com",
        "property_types": ["multifamily", "office"],
        "geography": ["tx", "la"],
        "min_loan": 1000000,
        "max_loan": 25000000,
        "max_ltv": 75,
        "min_dscr": 1.25,
    }
    r = s.post(f"{BASE_URL}/api/public/lender/apply", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    assert "id" in data
    STATE["lender_id"] = data["id"]


def test_2_duplicate_apply_rejected(s):
    r = s.post(f"{BASE_URL}/api/public/lender/apply", json={
        "lender_name": LENDER_NAME,
        "contact_name": "Alice Tester",
        "contact_email": LENDER_EMAIL,
    })
    assert r.status_code == 400, r.text


# ---------- 2. Admin pending / approve ----------

def test_3_admin_pending_lenders(s, admin_token):
    r = s.get(f"{BASE_URL}/api/admin/marketplace/pending-lenders", headers=h(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    ids = [x["id"] for x in data]
    assert STATE["lender_id"] in ids


def test_4_admin_approve_lender(s, admin_token, mongo):
    lid = STATE["lender_id"]
    r = s.post(f"{BASE_URL}/api/admin/marketplace/lenders/{lid}/approve", headers=h(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    assert "activate_url" in data
    # token must exist in db
    tok_doc = mongo.lender_activation_tokens.find_one({"lender_id": lid})
    assert tok_doc is not None
    STATE["activation_token"] = tok_doc["token"]
    # activate_url contains it
    assert STATE["activation_token"] in data["activate_url"]


# ---------- 3. Activation ----------

def test_5_get_activation(s):
    tok = STATE["activation_token"]
    r = s.get(f"{BASE_URL}/api/lender/activate/{tok}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["email"] == LENDER_EMAIL
    assert d["lender_name"] == LENDER_NAME
    assert d["contact_name"] == "Alice Tester"


def test_6_activate_lender(s):
    tok = STATE["activation_token"]
    r = s.post(f"{BASE_URL}/api/lender/activate/{tok}", json={"password": LENDER_PASSWORD})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "token" in d and d["user"]["role"] == "lender"
    STATE["lender_token"] = d["token"]


def test_7_reuse_token_rejected(s):
    tok = STATE["activation_token"]
    r = s.post(f"{BASE_URL}/api/lender/activate/{tok}", json={"password": LENDER_PASSWORD})
    assert r.status_code == 410, r.text


# ---------- 4. Lender me + credit box ----------

def test_8_lender_me(s):
    r = s.get(f"{BASE_URL}/api/lender/me", headers=h(STATE["lender_token"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == LENDER_NAME
    assert d["approval_status"] == "approved"
    assert "broker_id" not in d


def test_9_update_credit_box(s):
    r = s.patch(f"{BASE_URL}/api/lender/me/credit-box",
                headers=h(STATE["lender_token"]),
                json={"max_ltv": 80, "min_dscr": 1.2,
                      "property_types": ["multifamily"], "geography": ["tx"]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["max_ltv"] == 80
    assert d["min_dscr"] == 1.2
    assert d["property_types"] == ["multifamily"]
    assert d["geography"] == ["TX"]  # upper-cased


# ---------- 5. Match suggestions + invite ----------

@pytest.fixture(scope="module")
def scenario_id(mongo):
    # Sample scenario
    scen = mongo.scenarios.find_one({"name": "Sample MF Refi — Sugar Land"}, {"id": 1})
    if not scen:
        pytest.skip("Sample scenario missing")
    return scen["id"]


def test_10_match_suggestions(s, admin_token, scenario_id):
    r = s.get(f"{BASE_URL}/api/admin/scenarios/{scenario_id}/match-suggestions",
              headers=h(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    # Our newly-approved lender should appear (multifamily + TX in credit box)
    ids = [m.get("lender", {}).get("id") or m.get("id") for m in data]
    # match_lenders returns items with lender info -- inspect structure
    found = any(STATE["lender_id"] == (m.get("lender", {}) or {}).get("id") or
                STATE["lender_id"] == m.get("id") or
                STATE["lender_id"] == m.get("lender_id")
                for m in data)
    assert found, f"lender not in match suggestions: {data}"


def test_11_invite_lender(s, admin_token, scenario_id):
    r = s.post(f"{BASE_URL}/api/admin/scenarios/{scenario_id}/invite-lenders",
               headers=h(admin_token),
               json={"lender_ids": [STATE["lender_id"]], "note": "TEST invite"})
    assert r.status_code == 200, r.text
    d = r.json()
    invited = d["invited"]
    assert len(invited) == 1
    assert invited[0]["lender_id"] == STATE["lender_id"]
    assert invited[0]["already"] is False
    STATE["share_id"] = invited[0]["share_id"]


def test_12_invite_idempotent(s, admin_token, scenario_id):
    r = s.post(f"{BASE_URL}/api/admin/scenarios/{scenario_id}/invite-lenders",
               headers=h(admin_token),
               json={"lender_ids": [STATE["lender_id"]]})
    assert r.status_code == 200
    assert r.json()["invited"][0]["already"] is True


# ---------- 6. Lender invites + term sheet ----------

def test_13_lender_invites(s, scenario_id):
    r = s.get(f"{BASE_URL}/api/lender/invites", headers=h(STATE["lender_token"]))
    assert r.status_code == 200, r.text
    invites = r.json()
    match = [i for i in invites if i["scenario"]["id"] == scenario_id]
    assert match, "invited scenario missing"
    inv = match[0]
    assert inv["term_sheet"] is None
    assert "token" in inv
    assert inv["broker_note"] == "TEST invite"
    assert inv["scenario"]["name"]


def test_14_submit_term_sheet(s, scenario_id):
    payload = {
        "rate_type": "fixed",
        "interest_rate_pct": 6.75,
        "loan_amount": 5000000,
        "ltv_pct": 70,
        "ltc_pct": 65,
        "amortization_years": 30,
        "term_months": 60,
        "io_months": 24,
        "recourse": "non-recourse",
        "prepay": "3-2-1",
        "origination_fee_pct": 1.0,
        "exit_fee_pct": 0.5,
        "expiration_date": "2026-12-31",
        "contingencies": "Standard",
        "notes": "TEST term sheet",
    }
    r = s.post(f"{BASE_URL}/api/lender/scenarios/{scenario_id}/term-sheet",
               headers=h(STATE["lender_token"]), json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True and "id" in d
    STATE["ts_id"] = d["id"]


def test_15_resubmit_updates_same_row(s, scenario_id):
    r = s.post(f"{BASE_URL}/api/lender/scenarios/{scenario_id}/term-sheet",
               headers=h(STATE["lender_token"]),
               json={"rate_type": "fixed", "interest_rate_pct": 6.5, "loan_amount": 5000000})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == STATE["ts_id"], "should update same row not duplicate"


# ---------- 7. Admin term sheets view + status change ----------

def test_16_admin_list_term_sheets(s, admin_token, scenario_id):
    r = s.get(f"{BASE_URL}/api/admin/scenarios/{scenario_id}/term-sheets",
              headers=h(admin_token))
    assert r.status_code == 200
    sheets = r.json()
    ours = [x for x in sheets if x["id"] == STATE["ts_id"]]
    assert ours, "admin can't see the term sheet"
    assert ours[0]["interest_rate_pct"] == 6.5


def test_17_admin_counter(s, admin_token):
    r = s.patch(f"{BASE_URL}/api/admin/term-sheets/{STATE['ts_id']}",
                headers=h(admin_token),
                json={"status": "countered", "broker_note": "please tighten spread"})
    assert r.status_code == 200, r.text


# ---------- 8. Client read-only ----------

def test_18_client_can_read_term_sheets(s, client_token, scenario_id):
    r = s.get(f"{BASE_URL}/api/client/scenarios/{scenario_id}/term-sheets",
              headers=h(client_token))
    assert r.status_code == 200, r.text
    sheets = r.json()
    assert any(x["id"] == STATE["ts_id"] for x in sheets)


def test_19_client_403_on_foreign_scenario(s, client_token, mongo):
    # find any scenario NOT owned by sample client
    sample_user = mongo.users.find_one({"email": CLIENT_EMAIL}, {"id": 1})
    foreign = mongo.scenarios.find_one({"client_id": {"$ne": sample_user["id"]}}, {"id": 1})
    if not foreign:
        pytest.skip("no foreign scenario")
    r = s.get(f"{BASE_URL}/api/client/scenarios/{foreign['id']}/term-sheets",
              headers=h(client_token))
    assert r.status_code == 403


# ---------- 9. Role isolation ----------

def test_20_lender_cannot_hit_admin(s):
    r = s.get(f"{BASE_URL}/api/admin/marketplace/pending-lenders",
              headers=h(STATE["lender_token"]))
    assert r.status_code == 403


def test_21_client_cannot_submit_term_sheet(s, client_token, scenario_id):
    r = s.post(f"{BASE_URL}/api/lender/scenarios/{scenario_id}/term-sheet",
               headers=h(client_token), json={"interest_rate_pct": 5})
    assert r.status_code == 403


def test_22_admin_cannot_hit_lender_me(s, admin_token):
    r = s.get(f"{BASE_URL}/api/lender/me", headers=h(admin_token))
    assert r.status_code == 403


# ---------- 10. Withdraw ----------

def test_23_lender_withdraw(s):
    r = s.delete(f"{BASE_URL}/api/lender/term-sheets/{STATE['ts_id']}",
                 headers=h(STATE["lender_token"]))
    assert r.status_code == 200, r.text


def test_24_withdrawn_hidden_from_client(s, client_token, scenario_id):
    r = s.get(f"{BASE_URL}/api/client/scenarios/{scenario_id}/term-sheets",
              headers=h(client_token))
    assert r.status_code == 200
    assert not any(x["id"] == STATE["ts_id"] for x in r.json())


# ---------- Cleanup ----------

def test_99_cleanup(mongo):
    lid = STATE.get("lender_id")
    if not lid:
        return
    lender = mongo.lenders.find_one({"id": lid})
    owner_id = lender.get("owner_user_id") if lender else None
    mongo.term_sheets.delete_many({"lender_id": lid})
    mongo.scenario_shares.delete_many({"lender_id": lid})
    mongo.lender_activation_tokens.delete_many({"lender_id": lid})
    mongo.lenders.delete_one({"id": lid})
    if owner_id:
        mongo.users.delete_one({"id": owner_id})
    mongo.assistant_tasks.delete_many({"title": {"$regex": f"^Review term sheet from {LENDER_NAME}"}})

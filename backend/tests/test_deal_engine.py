"""Deal Engine (Phase 3) backend tests: scenarios, lenders, matching, shares,
public lender view (preflight/gate/package/doc/pdf/request-docs), audit trail,
and PDF regression check.
"""
import os
import uuid
import base64
import pytest
import requests

# --- BASE URL ---
def _load_backend_url():
    v = os.environ.get('REACT_APP_BACKEND_URL')
    if v:
        return v.rstrip('/')
    envp = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', '.env')
    with open(envp) as f:
        for line in f:
            if line.startswith('REACT_APP_BACKEND_URL='):
                return line.split('=', 1)[1].strip().rstrip('/')
    raise RuntimeError("REACT_APP_BACKEND_URL not found")

BASE = _load_backend_url()
API = f"{BASE}/api"

WAYNE = ("wayne@byrd-co.com", "byrdco2026")
SAMPLE = ("sample@example.com", "sample123")


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(*WAYNE)}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def client_h():
    return {"Authorization": f"Bearer {_login(*SAMPLE)}", "Content-Type": "application/json"}


# ---------- Scenarios: list + seeded sample ----------
def test_list_scenarios_has_seeded_sample(admin_h):
    r = requests.get(f"{API}/admin/scenarios", headers=admin_h, timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) >= 1
    seeded = [s for s in data if "Sugar Land" in (s.get("name") or "")]
    assert seeded, "Sample MF Refi — Sugar Land not found"
    s = seeded[0]
    assert "metrics" in s and s["metrics"].get("ltv_pct") is not None
    assert s["metrics"].get("dscr") is not None


def test_create_scenario_defaults(admin_h):
    # Frontend sends "Untitled Scenario" as default name.
    r = requests.post(f"{API}/admin/scenarios", headers=admin_h,
                      json={"name": "Untitled Scenario"}, timeout=30)
    assert r.status_code in (200, 201), r.text
    d = r.json()
    assert d["status"] == "draft"
    assert d.get("name") == "Untitled Scenario"
    # cleanup
    requests.delete(f"{API}/admin/scenarios/{d['id']}", headers=admin_h, timeout=30)


def test_patch_scenario_recomputes_metrics(admin_h):
    r = requests.post(f"{API}/admin/scenarios", headers=admin_h, json={"name": "TEST_metrics_calc"}, timeout=30)
    assert r.status_code in (200, 201)
    sid = r.json()["id"]
    payload = {
        "property_info": {"purchase_price": 3800000, "current_value": 4100000, "property_type": "multifamily", "state": "TX"},
        "loan_request": {"loan_amount": 2900000, "requested_rate_pct": 6.75, "amort_months": 360},
        "financials": {"gross_income": 410000, "vacancy_pct": 6, "operating_expenses": 175000, "capex_reserves": 8000},
        "construction": {},
        "sources_uses": [{"category": "source", "label": "Debt", "amount": 2900000},
                         {"category": "use", "label": "Purchase", "amount": 3800000}],
    }
    r2 = requests.patch(f"{API}/admin/scenarios/{sid}", headers=admin_h, json=payload, timeout=30)
    assert r2.status_code == 200, r2.text
    m = r2.json()["metrics"]
    # NOI = 410000*(1-.06) - 175000 - 8000 = 202400
    assert abs(m["noi"] - 202400) < 1
    assert abs(m["ltv_pct"] - 70.73) < 0.5
    assert abs(m["dscr"] - 0.9) < 0.05
    assert abs(m["debt_yield_pct"] - 6.98) < 0.05
    assert abs(m["monthly_payment"] - 18809) < 5
    requests.delete(f"{API}/admin/scenarios/{sid}", headers=admin_h, timeout=30)


def test_scenario_pdf(admin_h):
    r = requests.get(f"{API}/admin/scenarios", headers=admin_h, timeout=30)
    sid = r.json()[0]["id"]
    r2 = requests.get(f"{API}/admin/scenarios/{sid}/pdf", headers=admin_h, timeout=60)
    assert r2.status_code == 200, r2.text
    assert r2.headers.get("content-type", "").startswith("application/pdf")
    body = r2.content
    assert len(body) >= 3000, f"PDF too small: {len(body)}"
    assert body[:4] == b"%PDF"


# ---------- Lenders CRUD ----------
def test_lender_crud(admin_h):
    payload = {
        "name": "TEST_Lender_" + uuid.uuid4().hex[:6],
        "kind": "bank",
        "property_types": ["multifamily"],
        "geography": ["TX"],
        "min_loan": 1_000_000,
        "max_loan": 20_000_000,
        "max_ltv": 75,
        "min_dscr": 1.20,
        "min_debt_yield": 7.0,
        "contacts": [{"name": "Jane Doe", "email": "jane@testlender.com"}],
    }
    r = requests.post(f"{API}/admin/lenders", headers=admin_h, json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text
    lid = r.json()["id"]

    r = requests.get(f"{API}/admin/lenders", headers=admin_h, timeout=30)
    assert r.status_code == 200 and any(l["id"] == lid for l in r.json())

    r = requests.patch(f"{API}/admin/lenders/{lid}", headers=admin_h, json={"max_ltv": 80}, timeout=30)
    assert r.status_code == 200 and r.json()["max_ltv"] == 80

    r = requests.delete(f"{API}/admin/lenders/{lid}", headers=admin_h, timeout=30)
    assert r.status_code == 200


def test_scenario_match_ordered(admin_h):
    sid = requests.get(f"{API}/admin/scenarios", headers=admin_h, timeout=30).json()[0]["id"]
    r = requests.get(f"{API}/admin/scenarios/{sid}/match", headers=admin_h, timeout=30)
    assert r.status_code == 200
    matches = r.json()
    assert isinstance(matches, list)
    if len(matches) >= 2:
        for a, b in zip(matches, matches[1:]):
            assert a["score"] >= b["score"]


# ---------- Shares + public lender view ----------
@pytest.fixture(scope="module")
def scenario_and_lender(admin_h):
    """Create isolated TEST_ scenario+lender+attached-doc for share tests."""
    # Client uploads a small file so we have a doc_id with a file
    ch_token = _login(*SAMPLE)
    ch = {"Authorization": f"Bearer {ch_token}", "Content-Type": "application/json"}
    docs_resp = requests.get(f"{API}/client/me", headers=ch, timeout=30).json()
    docs = docs_resp.get("docs", [])
    assert docs, "Sample client has no docs"
    target = docs[0]
    if not target.get("file_id"):
        b64 = base64.b64encode(b"hello test file").decode()
        up = requests.post(f"{API}/client/docs/{target['id']}/upload", headers=ch,
                           json={"filename": "test.txt", "content_type": "text/plain",
                                 "data_b64": b64}, timeout=30)
        assert up.status_code == 200, up.text

    # Also grab a second doc-id for on_request
    on_req = None
    for d in docs[1:]:
        on_req = d
        break
    if on_req and not on_req.get("file_id"):
        b64 = base64.b64encode(b"secret personal doc").decode()
        requests.post(f"{API}/client/docs/{on_req['id']}/upload", headers=ch,
                      json={"filename": "personal.txt", "content_type": "text/plain",
                            "data_b64": b64}, timeout=30)

    # Find sample client_id
    me = requests.get(f"{API}/auth/me", headers=ch, timeout=30).json()
    client_id = me.get("id") or me.get("user", {}).get("id") or docs_resp.get("user", {}).get("id")

    # Create scenario linked to client
    r = requests.post(f"{API}/admin/scenarios", headers=admin_h,
                      json={"name": "TEST_Share_Scenario", "client_id": client_id},
                      timeout=30)
    sid = r.json()["id"]
    # Attach the two docs
    attached = [{"doc_id": target["id"], "visibility": "included"}]
    if on_req:
        attached.append({"doc_id": on_req["id"], "visibility": "on_request"})
    r = requests.patch(f"{API}/admin/scenarios/{sid}", headers=admin_h,
                       json={"attached_docs": attached,
                             "property_info": {"property_type": "multifamily", "state": "TX",
                                               "purchase_price": 3800000, "current_value": 4100000},
                             "loan_request": {"loan_amount": 2900000, "requested_rate_pct": 6.75, "amort_months": 360},
                             "financials": {"gross_income": 410000, "vacancy_pct": 6, "opex": 175000, "capex": 8000}},
                       timeout=30)
    assert r.status_code == 200

    # Create lender
    r = requests.post(f"{API}/admin/lenders", headers=admin_h, json={
        "name": "TEST_Share_Lender_" + uuid.uuid4().hex[:5],
        "kind": "bank", "property_types": ["multifamily"], "geography": ["TX"],
        "min_loan": 500_000, "max_loan": 20_000_000, "max_ltv": 75,
        "min_dscr": 0.5, "min_debt_yield": 5.0,
        "contacts": [{"name": "Test", "email": "test@lender.com"}],
    }, timeout=30)
    lid = r.json()["id"]

    yield {"sid": sid, "lid": lid, "included_doc": target["id"],
           "on_request_doc": on_req["id"] if on_req else None}

    requests.delete(f"{API}/admin/scenarios/{sid}", headers=admin_h, timeout=30)
    requests.delete(f"{API}/admin/lenders/{lid}", headers=admin_h, timeout=30)


def test_create_share_and_status_transition(admin_h, scenario_and_lender):
    ctx = scenario_and_lender
    # Ensure status is draft
    requests.patch(f"{API}/admin/scenarios/{ctx['sid']}", headers=admin_h,
                   json={"status": "draft"}, timeout=30)
    r = requests.post(f"{API}/admin/scenarios/{ctx['sid']}/shares", headers=admin_h,
                      json={"lender_id": ctx["lid"]}, timeout=30)
    assert r.status_code in (200, 201), r.text
    share = r.json()
    assert share["token"] and len(share["token"]) >= 32
    ctx["share_id"] = share["id"]
    ctx["token"] = share["token"]

    # scenario is now shopping
    r = requests.get(f"{API}/admin/scenarios/{ctx['sid']}", headers=admin_h, timeout=30)
    assert r.json()["status"] == "shopping"


def test_public_lender_flow(admin_h, scenario_and_lender):
    ctx = scenario_and_lender
    token = ctx["token"]

    # Preflight (no auth)
    r = requests.get(f"{API}/lender-view/{token}/preflight", timeout=30)
    assert r.status_code == 200
    assert "scenario_name" in r.json()

    # Package without session -> 401
    r = requests.get(f"{API}/lender-view/{token}", timeout=30)
    assert r.status_code == 401

    # Gate
    r = requests.post(f"{API}/lender-view/{token}/gate", timeout=30, json={
        "viewer_name": "TEST Viewer", "viewer_email": "viewer@t.com",
        "viewer_institution": "TestBank"
    })
    assert r.status_code == 200, r.text
    st = r.json()["session_token"]

    # Package (with session)
    r = requests.get(f"{API}/lender-view/{token}", params={"session_token": st}, timeout=30)
    assert r.status_code == 200, r.text
    pkg = r.json()
    assert "TestBank" in pkg["watermark"] and "TEST Viewer" in pkg["watermark"]
    assert pkg["metrics"]["ltv_pct"] is not None

    # Included doc 200
    r = requests.get(f"{API}/lender-view/{token}/doc/{ctx['included_doc']}",
                     params={"session_token": st}, timeout=30)
    assert r.status_code == 200, r.text

    # On-request doc 403 before grant
    if ctx["on_request_doc"]:
        r = requests.get(f"{API}/lender-view/{token}/doc/{ctx['on_request_doc']}",
                         params={"session_token": st}, timeout=30)
        assert r.status_code == 403, f"Expected 403 pre-grant, got {r.status_code}: {r.text}"

        # Grant
        rg = requests.post(f"{API}/admin/scenarios/{ctx['sid']}/shares/{ctx['share_id']}/grant/{ctx['on_request_doc']}",
                           headers=admin_h, timeout=30)
        assert rg.status_code == 200

        # Now 200
        r = requests.get(f"{API}/lender-view/{token}/doc/{ctx['on_request_doc']}",
                         params={"session_token": st}, timeout=30)
        assert r.status_code == 200, r.text

    # request-docs
    r = requests.post(f"{API}/lender-view/{token}/request-docs",
                      params={"session_token": st}, timeout=30)
    assert r.status_code == 200

    # PDF via lender view
    r = requests.get(f"{API}/lender-view/{token}/pdf",
                     params={"session_token": st}, timeout=60)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"

    # Audit trail
    r = requests.get(f"{API}/admin/scenarios/{ctx['sid']}/shares/{ctx['share_id']}/views",
                     headers=admin_h, timeout=30)
    assert r.status_code == 200
    actions = {v["action"] for v in r.json()}
    for expected in ("gate", "view_scenario", "view_doc", "request_docs", "download_pdf"):
        assert expected in actions, f"Missing audit action {expected}. Got: {actions}"


# ---------- Regression: prior features still intact ----------
def test_public_quote_still_works():
    r = requests.post(f"{API}/public/quote", json={
        "name": "TEST_regression", "email": "t@t.com", "phone": "555",
        "program": "Bridge", "amount": 100000, "message": "hi"
    }, timeout=30)
    assert r.status_code in (200, 201)


def test_admin_quotes_inbox(admin_h):
    r = requests.get(f"{API}/admin/quotes", headers=admin_h, timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

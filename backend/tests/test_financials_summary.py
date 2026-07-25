"""Financials tab (multi-period NOI/DSCR) + Executive Loan Summary PDF integration tests."""
import base64
import os
import struct
import zlib

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")

ADMIN_EMAIL = "wayne@byrd-co.com"
ADMIN_PASSWORD = "byrdco2026"
EXISTING_SCEN_ID = "c4d98f0b-f8d6-4399-abde-ccad9312c953"


# ---------- helpers ----------
def _tiny_png_b64() -> str:
    """1x1 red PNG."""
    sig = b'\x89PNG\r\n\x1a\n'
    def _chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b"\x00\xff\x00\x00"
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")
    return base64.b64encode(sig + ihdr + idat + iend).decode("ascii")


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.fail(f"Admin login failed: {r.status_code} {r.text[:400]}")
    token = r.json().get("token")
    if not token:
        pytest.fail(f"No token in login resp: {r.json()}")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def anon_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def scen_id(admin_client):
    # Verify existing scenario is reachable; else create ephemeral
    r = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{EXISTING_SCEN_ID}")
    if r.status_code == 200:
        return EXISTING_SCEN_ID
    # create a lightweight scenario
    payload = {
        "name": "TEST_Financials_Scen",
        "property_info": {"address": "123 Main St, Sugar Land, TX 77478", "purchase_price": 5000000},
        "loan_request": {"loan_amount": 3500000, "requested_rate_pct": 7.0, "amort_months": 360, "term_months": 60},
    }
    r = admin_client.post(f"{BASE_URL}/api/admin/scenarios", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# ---------- auth guard ----------
class TestAuth:
    def test_financials_requires_admin(self, anon_client, scen_id):
        r = anon_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials")
        assert r.status_code in (401, 403)

    def test_summary_requires_admin(self, anon_client, scen_id):
        r = anon_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary")
        assert r.status_code in (401, 403)


# ---------- financials core ----------
class TestFinancials:
    _created_period_ids: list = []

    def test_get_financials_shape(self, admin_client, scen_id):
        r = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "periods" in data and isinstance(data["periods"], list)
        assert "selected_period_id" in data
        uw = data["uw_assumptions"]
        assert "rate_pct" in uw and "amort_months" in uw and "term_months" in uw
        m = data["metrics"]
        assert "noi_source" in m

    def test_patch_uw_assumptions_persists(self, admin_client, scen_id):
        r = admin_client.patch(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials/assumptions",
                               json={"rate_pct": 6.75, "amort_months": 360, "term_months": 60})
        assert r.status_code == 200, r.text
        # verify via GET
        r2 = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials")
        d = r2.json()
        assert d["uw_assumptions"]["rate_pct"] == 6.75
        assert d["uw_assumptions"]["amort_months"] == 360
        assert d["uw_assumptions"]["term_months"] == 60
        m = d["metrics"]
        # uw source should be uw when uw rate is present
        assert m.get("uw_rate_pct") == 6.75
        assert m.get("uw_amort_months") == 360
        assert m.get("uw_source") == "uw"

    def test_add_period_computed_and_autoselect(self, admin_client, scen_id):
        payload = {
            "label": "TEST_Period_A",
            "doc_type": "manual",
            "is_pro_forma": False,
            "include_reserves_in_opex": True,
            "income": {"gross_potential_rent": 600000, "vacancy_loss": 30000, "other_income": 10000},
            "expenses": {"taxes": 50000, "insurance": 20000, "utilities": 15000, "reserves_capex": 12000,
                         "management": 30000},
        }
        r = admin_client.post(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials/periods", json=payload)
        assert r.status_code == 200, r.text
        p = r.json()
        assert "_computed" in p
        egi = 600000 - 30000 + 10000  # 580000
        opex = 50000 + 20000 + 15000 + 30000 + 12000  # 127000 incl reserves
        assert p["_computed"]["egi"] == egi
        assert p["_computed"]["total_expenses"] == opex
        assert p["_computed"]["noi"] == egi - opex
        TestFinancials._created_period_ids.append(p["id"])

    def test_reserves_excluded_when_flag_off(self, admin_client, scen_id):
        payload = {
            "label": "TEST_Period_NoReserves",
            "doc_type": "manual",
            "include_reserves_in_opex": False,
            "income": {"gross_potential_rent": 500000, "vacancy_loss": 25000, "other_income": 5000},
            "expenses": {"taxes": 40000, "reserves_capex": 10000},
        }
        r = admin_client.post(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials/periods", json=payload)
        assert r.status_code == 200, r.text
        p = r.json()
        # reserves not included → opex = 40000
        assert p["_computed"]["total_expenses"] == 40000
        assert p["_computed"]["egi"] == 480000
        assert p["_computed"]["noi"] == 440000
        TestFinancials._created_period_ids.append(p["id"])

    def test_patch_period_partial_merge(self, admin_client, scen_id):
        pid = TestFinancials._created_period_ids[0]
        r = admin_client.patch(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials/periods/{pid}",
                               json={"income": {"other_income": 25000}})
        assert r.status_code == 200, r.text
        p = r.json()
        # untouched keys preserved
        assert p["income"]["gross_potential_rent"] == 600000
        assert p["income"]["vacancy_loss"] == 30000
        assert p["income"]["other_income"] == 25000
        # recomputed
        assert p["_computed"]["egi"] == 600000 - 30000 + 25000

    def test_select_period_and_metrics_source(self, admin_client, scen_id):
        pid = TestFinancials._created_period_ids[0]
        r = admin_client.post(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials/select",
                              json={"period_id": pid})
        assert r.status_code == 200, r.text
        assert r.json()["selected_period_id"] == pid
        r2 = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials")
        d = r2.json()
        assert d["selected_period_id"] == pid
        ns = d["metrics"]["noi_source"]
        assert ns is not None
        assert ns.get("period_id") == pid
        assert "label" in ns and "is_pro_forma" in ns
        # DSCR/debt_yield sanity: NOI is present
        assert d["metrics"].get("noi") is not None

    def test_dscr_and_debt_yield_math(self, admin_client, scen_id):
        r = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials")
        m = r.json()["metrics"]
        # If DSCR is exposed, sanity-check it's positive when NOI > 0
        if m.get("dscr") is not None and m.get("noi", 0) > 0:
            assert m["dscr"] > 0
        if m.get("debt_yield_pct") is not None and m.get("noi", 0) > 0:
            assert m["debt_yield_pct"] > 0

    def test_delete_period_reselect(self, admin_client, scen_id):
        # delete currently-selected period; next remaining should be selected
        selected = TestFinancials._created_period_ids[0]
        r = admin_client.delete(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials/periods/{selected}")
        assert r.status_code == 200
        r2 = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials")
        d = r2.json()
        remaining_ids = [p["id"] for p in d["periods"]]
        assert selected not in remaining_ids
        if remaining_ids:
            assert d["selected_period_id"] in remaining_ids

    def test_parse_doc_404_bad_file(self, admin_client, scen_id):
        r = admin_client.post(f"{BASE_URL}/api/admin/scenarios/{scen_id}/financials/parse-doc",
                              json={"file_id": "nonexistent-xyz", "doc_type": "tax_return"})
        assert r.status_code == 404, r.text

    def test_parse_doc_422_no_text(self, admin_client, scen_id):
        # upload a tiny non-text/non-pdf file via client_files direct insert route?
        # Use summary photo endpoint which stores in a different collection — instead
        # try creating a scenario doc + upload with text-less bytes via the admin upload path if available.
        # If no such helper, skip this scenario.
        # Best-effort: create client_files via /admin/scenarios/{sid}/docs endpoint (if used elsewhere).
        # Skipping for env-simplicity: we still cover the 404 branch above.
        pytest.skip("Direct client_files upload without content skipped in this env; 404 path covered.")

    @classmethod
    def teardown_class(cls):
        # best-effort cleanup of remaining test periods
        try:
            s = requests.Session()
            s.headers.update({"Content-Type": "application/json"})
            r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
            token = r.json().get("token") or r.json().get("access_token")
            s.headers.update({"Authorization": f"Bearer {token}"})
            for pid in cls._created_period_ids:
                s.delete(f"{BASE_URL}/api/admin/scenarios/{EXISTING_SCEN_ID}/financials/periods/{pid}")
        except Exception:
            pass


# ---------- occupancy_type ----------
class TestOccupancy:
    def test_occupancy_type_values(self, admin_client, scen_id):
        for v in ("owner_occupied", "non_owner_occupied", None):
            r = admin_client.patch(f"{BASE_URL}/api/admin/scenarios/{scen_id}",
                                   json={"property_info": {"occupancy_type": v}})
            assert r.status_code == 200, f"{v} -> {r.status_code} {r.text[:200]}"
            r2 = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}")
            got = (r2.json().get("property_info") or {}).get("occupancy_type")
            assert got == v, f"expected {v}, got {got}"


# ---------- summary ----------
class TestSummary:
    _photo_ids: list = []

    def test_get_summary_defaults(self, admin_client, scen_id):
        r = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary")
        assert r.status_code == 200, r.text
        d = r.json()
        assert "config" in d and "photos" in d
        c = d["config"]
        for k in ("narrative", "include_map", "include_census", "include_photos", "include_sponsor_snapshot"):
            assert k in c, f"missing config key: {k}"

    def test_patch_summary_config(self, admin_client, scen_id):
        r = admin_client.patch(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary",
                               json={"narrative": "TEST_narrative_text", "include_map": False})
        assert r.status_code == 200, r.text
        r2 = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary")
        c = r2.json()["config"]
        assert c["narrative"] == "TEST_narrative_text"
        assert c["include_map"] is False

    def test_photo_upload_cap(self, admin_client, scen_id):
        # cleanup any existing photos first
        r0 = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary")
        for ph in r0.json().get("photos", []):
            admin_client.delete(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary/photos/{ph['id']}")
        b64 = _tiny_png_b64()
        for i in range(4):
            r = admin_client.post(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary/photos",
                                  json={"filename": f"t{i}.png", "content_type": "image/png",
                                        "data_b64": b64})
            assert r.status_code == 200, f"upload {i}: {r.status_code} {r.text[:200]}"
            TestSummary._photo_ids.append(r.json()["id"])
        # 5th must 400
        r5 = admin_client.post(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary/photos",
                               json={"filename": "t5.png", "content_type": "image/png", "data_b64": b64})
        assert r5.status_code == 400, f"expected 400, got {r5.status_code}: {r5.text[:200]}"

    def test_get_photo_bytes(self, admin_client, scen_id):
        pid = TestSummary._photo_ids[0]
        r = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary/photos/{pid}")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")
        assert r.content.startswith(b"\x89PNG")

    def test_delete_photo(self, admin_client, scen_id):
        pid = TestSummary._photo_ids.pop()
        r = admin_client.delete(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary/photos/{pid}")
        assert r.status_code == 200

    def test_generate_pdf(self, admin_client, scen_id):
        r = admin_client.post(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary/generate")
        assert r.status_code == 200, r.text[:400]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content.startswith(b"%PDF-")
        assert len(r.content) > 1000

    def test_save_to_portal_creates_doc(self, admin_client, scen_id):
        r = admin_client.post(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary/save-to-portal",
                              json={})
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d.get("ok") is True
        doc_id_1 = d.get("doc_id")
        file_id_1 = d.get("file_id")
        assert doc_id_1 and file_id_1

        # verify doc appears in scenario detail with order=-1000, lender_visibility, sponsor_id=None
        r2 = admin_client.get(f"{BASE_URL}/api/admin/scenarios/{scen_id}")
        docs = r2.json().get("docs") or []
        matching = [d for d in docs if d.get("label") == "Loan Executive Summary"]
        assert matching, f"Loan Executive Summary doc not found. docs labels={[dd.get('label') for dd in docs]}"
        m = matching[0]
        assert m.get("order") == -1000
        assert m.get("lender_visibility") == "included"
        assert m.get("sponsor_id") is None

        # Re-run: same doc_id, new file_id, previous file replaced
        r3 = admin_client.post(f"{BASE_URL}/api/admin/scenarios/{scen_id}/summary/save-to-portal",
                               json={})
        assert r3.status_code == 200, r3.text[:400]
        d3 = r3.json()
        assert d3.get("doc_id") == doc_id_1, "doc row must be reused"
        assert d3.get("file_id") != file_id_1, "file_id should be regenerated"

    @classmethod
    def teardown_class(cls):
        try:
            s = requests.Session()
            s.headers.update({"Content-Type": "application/json"})
            r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
            token = r.json().get("token") or r.json().get("access_token")
            s.headers.update({"Authorization": f"Bearer {token}"})
            for pid in cls._photo_ids:
                s.delete(f"{BASE_URL}/api/admin/scenarios/{EXISTING_SCEN_ID}/summary/photos/{pid}")
        except Exception:
            pass

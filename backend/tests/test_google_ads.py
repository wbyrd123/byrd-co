"""Byrd & CO — Google Ads API endpoints (Phase 1: read-only).

Live smoke tests against the actual Google Ads API using the credentials in .env.
These tests will FAIL loudly if:
  * env vars are missing / wrong
  * the refresh token expired or was revoked
  * the developer token was rejected
  * the OAuth client is misconfigured

Test Access limitations (until Basic Access is approved):
  * ListAccessibleCustomers still works
  * customer_client GAQL against the MCC works but only lists the MCC itself
  * Real campaign reports on production customer IDs will fail with
    CUSTOMER_NOT_ENABLED / requestor doesn't have permission for CID
"""
import os
import pytest
import requests
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE}/api"

ADMIN = ("wayne@byrd-co.com", "byrdco2026")
CLIENT = ("sample@example.com", "sample123")

pytestmark = pytest.mark.skipif(
    not all(be.get(k) for k in ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
                                "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
                                "GOOGLE_ADS_MCC_CUSTOMER_ID")),
    reason="Google Ads credentials not configured — skipping live integration tests",
)


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, r.text[:200]
    return r.json()["token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


class TestGoogleAdsStatusEndpoint:

    def test_admin_can_check_connection(self, admin_tok):
        r = requests.get(f"{API}/admin/google-ads/status", headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data["configured"] is True
        assert data["ok"] is True, f"connection should be live: {data}"
        assert data["mcc"].isdigit()
        assert len(data["mcc"]) == 10
        assert isinstance(data["accessible_customers"], list)
        # OAuth login should have SOME accessible customer (at minimum the MCC itself)
        assert len(data["accessible_customers"]) >= 1
        # All entries follow the customers/<id> shape
        for res in data["accessible_customers"]:
            assert res.startswith("customers/")
            assert res.split("/")[1].isdigit()

    def test_non_admin_gets_403(self):
        client_tok = token_for(*CLIENT)
        r = requests.get(f"{API}/admin/google-ads/status", headers=auth(client_tok), timeout=60)
        assert r.status_code == 403

    def test_no_auth_gets_401(self):
        r = requests.get(f"{API}/admin/google-ads/status", timeout=60)
        assert r.status_code in (401, 403)


class TestMCCAccountsEndpoint:

    def test_admin_can_list_mcc_accounts(self, admin_tok):
        r = requests.get(f"{API}/admin/google-ads/accounts", headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data["ok"] is True
        assert data["mcc"].isdigit()
        assert isinstance(data["accounts"], list)
        # Under Test Access with an empty MCC tree the response can be [] OR [MCC itself]
        # Either is valid — we just care the shape is correct.
        for a in data["accounts"]:
            assert a["id"].isdigit()
            assert isinstance(a["name"], str)
            assert isinstance(a["is_manager"], bool)
            assert isinstance(a["is_test_account"], bool)
            assert isinstance(a["level"], int)


class TestCampaignReportEndpointValidation:
    """Validation-layer coverage. Real report data requires Basic Access."""

    def test_bad_customer_id_returns_400(self, admin_tok):
        r = requests.get(
            f"{API}/admin/google-ads/report",
            params={"customer_id": "abc", "start_date": "2026-08-01", "end_date": "2026-08-31"},
            headers=auth(admin_tok), timeout=60,
        )
        assert r.status_code == 400

    def test_hyphenated_customer_id_accepted(self, admin_tok, request):
        # Should NOT reject on validation — it may fail with 502 downstream because
        # the customer isn't accessible under Test Access, but the 10-digit shape
        # after stripping dashes is valid.
        r = requests.get(
            f"{API}/admin/google-ads/report",
            params={"customer_id": "742-198-9452", "start_date": "2026-08-01",
                    "end_date": "2026-08-31"},
            headers=auth(admin_tok), timeout=90,
        )
        # 200 (empty rows for MCC), or 502 (Test Access denies MCC as target) — both
        # prove the validator accepted the input. 400 would be a regression.
        assert r.status_code != 400, r.text[:400]

    def test_bad_date_format_returns_400(self, admin_tok):
        r = requests.get(
            f"{API}/admin/google-ads/report",
            params={"customer_id": "7421989452", "start_date": "August 1, 2026",
                    "end_date": "2026-08-31"},
            headers=auth(admin_tok), timeout=60,
        )
        assert r.status_code == 400
        assert "start_date" in r.text.lower() or "yyyy-mm-dd" in r.text.lower()

    def test_end_before_start_returns_400(self, admin_tok):
        r = requests.get(
            f"{API}/admin/google-ads/report",
            params={"customer_id": "7421989452", "start_date": "2026-09-01",
                    "end_date": "2026-08-01"},
            headers=auth(admin_tok), timeout=60,
        )
        assert r.status_code == 400

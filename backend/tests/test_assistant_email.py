"""Tests for POST /api/admin/assistant/email/send + assistant endpoint regressions.

Iteration 5: Post-fix. From is now POSTMARK_FROM, admin.email is in Reply-To,
and Postmark errors return HTTP 400 (was 502) so Cloudflare passes the JSON
body through unchanged.
"""
import os
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "wayne@byrd-co.com"
ADMIN_PASSWORD = "byrdco2026"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="session")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"No token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="session")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- Assistant email send ----------
class TestAssistantEmailSend:
    def test_off_domain_returns_400_json_not_html(self, h):
        """Off-domain send should return HTTP 400 with JSON detail (NOT 502 HTML).
        Cloudflare only masks 5xx; 400 passes through unchanged so the user sees
        the pending-approval hint.
        """
        payload = {
            "to": f"TEST_offdomain_{int(time.time())}@gmail.com",
            "subject": "TEST off-domain sanity",
            "body": "This should fail because Postmark trial only allows same-domain.",
        }
        r = requests.post(f"{API}/admin/assistant/email/send", headers=h, json=payload, timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:400]}"
        ct = r.headers.get("content-type", "")
        assert "application/json" in ct, f"Expected application/json, got {ct}"
        data = r.json()
        detail = (data.get("detail") or "").lower()
        assert "pending approval" in detail, f"'pending approval' not in detail: {detail}"
        assert "byrd-co.com" in detail, f"'byrd-co.com' hint missing: {detail}"

    def test_same_domain_returns_200_sent(self, h, db):
        """Same-domain send should now succeed with HTTP 200 {ok, id, status:'sent'}
        because From is POSTMARK_FROM (verified) and Reply-To is the admin.
        Also verify db.assistant_emails record has status='sent' and reply_to=admin.email.
        """
        payload = {
            "to": "caleb@byrd-co.com",
            "subject": f"TEST same-domain send {int(time.time())}",
            "body": "Automated backend test — please ignore.",
        }
        r = requests.post(f"{API}/admin/assistant/email/send", headers=h, json=payload, timeout=45)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:800]}"
        data = r.json()
        assert data.get("ok") is True, data
        assert data.get("status") == "sent", data
        log_id = data.get("id")
        assert log_id, data

        # Verify db record
        rec = db.assistant_emails.find_one({"id": log_id})
        assert rec is not None, "db.assistant_emails record not found"
        assert rec.get("status") == "sent"
        assert rec.get("reply_to") == ADMIN_EMAIL
        assert not rec.get("error"), f"expected empty error, got: {rec.get('error')}"
        assert rec.get("to") == "caleb@byrd-co.com"

    def test_failed_record_written_to_db(self, h, db):
        """Off-domain (failed) send should insert an assistant_emails row with
        status='failed' and error populated.
        """
        unique_to = f"TEST_dbcheck_{int(time.time())}@example.com"
        payload = {
            "to": unique_to,
            "subject": "TEST db write on failure",
            "body": "verifying db write",
        }
        r = requests.post(f"{API}/admin/assistant/email/send", headers=h, json=payload, timeout=30)
        assert r.status_code == 400, r.text[:400]

        rec = db.assistant_emails.find_one({"to": unique_to})
        assert rec is not None, "no db.assistant_emails row for failed send"
        assert rec.get("status") == "failed", rec
        assert rec.get("error"), f"error field empty on failed record: {rec}"
        assert rec.get("reply_to") == ADMIN_EMAIL


# ---------- Regression tests for other assistant endpoints ----------
class TestAssistantRegressions:
    def test_get_tasks(self, h):
        r = requests.get(f"{API}/admin/assistant/tasks", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), (list, dict))

    def test_get_messages(self, h):
        r = requests.get(f"{API}/admin/assistant/messages", headers=h, timeout=15)
        assert r.status_code == 200, r.text

    def test_get_teammates(self, h):
        r = requests.get(f"{API}/admin/assistant/teammates", headers=h, timeout=15)
        assert r.status_code == 200, r.text

    def test_post_reset(self, h):
        r = requests.post(f"{API}/admin/assistant/reset", headers=h, timeout=15)
        assert r.status_code == 200, r.text

    def test_post_chat_sse(self, h):
        r = requests.post(
            f"{API}/admin/assistant/chat",
            headers=h,
            json={"message": "hi, just a smoke test", "stream": True},
            timeout=45,
            stream=True,
        )
        assert r.status_code == 200, r.text[:500] if not r.ok else "ok"
        got_any = False
        try:
            for chunk in r.iter_content(chunk_size=256):
                if chunk:
                    got_any = True
                    break
        finally:
            r.close()
        assert got_any, "SSE stream returned nothing"

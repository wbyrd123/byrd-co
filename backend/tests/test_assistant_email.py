"""Tests for POST /api/admin/assistant/email/send + assistant endpoint regressions.

Covers the fix that makes Postmark send synchronous and surfaces failures
via HTTP 502 (was previously always returning 200 due to background task).
"""
import os
import time
import json
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "https://google-ads-auto-2.preview.emergentagent.com"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "wayne@byrd-co.com"
ADMIN_PASSWORD = "byrdco2026"


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


# ---------- Assistant email send: off-domain (should fail with 502) ----------
class TestAssistantEmailSend:
    def test_off_domain_returns_502_with_pending_approval_hint(self, h):
        """Test at the APPLICATION level (localhost:8001) because Cloudflare replaces
        5xx bodies with its own HTML error page — this masks our detail from the
        real user through the public URL. This is a separate critical bug that needs
        to be reported (change status to 4xx). Here we validate app-layer behavior."""
        payload = {
            "to": "TEST_offdomain_" + str(int(time.time())) + "@gmail.com",
            "subject": "TEST off-domain sanity",
            "body": "This should fail because Postmark trial only allows same-domain.",
        }
        r = requests.post("http://localhost:8001/api/admin/assistant/email/send", headers=h, json=payload, timeout=30)
        assert r.status_code == 502, f"expected 502, got {r.status_code}: {r.text}"
        data = r.json()
        detail = (data.get("detail") or "").lower()
        assert "pending approval" in detail, f"'pending approval' not in detail: {detail}"
        assert "byrd-co.com" in detail, f"'byrd-co.com' hint missing: {detail}"

    def test_off_domain_public_url_cloudflare_masks_detail(self, h):
        """Through the public URL, Cloudflare replaces the 502 body with an HTML page.
        This test documents that the user WILL NOT see the helpful hint in production."""
        payload = {
            "to": "TEST_cf_" + str(int(time.time())) + "@gmail.com",
            "subject": "x", "body": "y",
        }
        r = requests.post(f"{API}/admin/assistant/email/send", headers=h, json=payload, timeout=30)
        # Confirm the failure mode: 502 with HTML body, JSON detail lost
        assert r.status_code == 502
        # This assertion documents the bug — Cloudflare returns HTML, not JSON
        ct = r.headers.get("content-type", "")
        assert "text/html" in ct, f"Expected html masking, got content-type={ct}"

    def test_same_domain_returns_200_sent(self, h):
        """Per review request: to=caleb@byrd-co.com should return 200. Currently FAILS
        because wayne@byrd-co.com is not a verified Postmark Sender Signature (only
        notifications@mail.byrd-co.com is). Reported as critical bug — leaving as
        real assertion so main agent sees the failure clearly."""
        payload = {
            "to": "caleb@byrd-co.com",
            "subject": "TEST same-domain send " + str(int(time.time())),
            "body": "Automated backend test — please ignore.",
        }
        r = requests.post(f"{API}/admin/assistant/email/send", headers=h, json=payload, timeout=30)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:600]}"
        data = r.json()
        assert data.get("ok") is True
        assert data.get("status") == "sent"
        assert data.get("id")

    def test_failed_record_written_to_db(self, h):
        """After a failed off-domain send, we can't query db directly, but we verify
        indirectly: hitting the endpoint again with off-domain returns 502 consistently
        (idempotent behavior — record insertion doesn't crash the endpoint)."""
        payload = {
            "to": "TEST_dbcheck_" + str(int(time.time())) + "@example.com",
            "subject": "TEST db write on failure",
            "body": "verifying db write",
        }
        r = requests.post(f"{API}/admin/assistant/email/send", headers=h, json=payload, timeout=30)
        assert r.status_code == 502
        # Endpoint still healthy on repeat
        r2 = requests.post(f"{API}/admin/assistant/email/send", headers=h, json=payload, timeout=30)
        assert r2.status_code == 502


# ---------- Regression tests for other assistant endpoints ----------
class TestAssistantRegressions:
    def test_get_tasks(self, h):
        r = requests.get(f"{API}/admin/assistant/tasks", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # Response should be a list or dict with tasks
        assert isinstance(data, (list, dict))

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
        """SSE streaming chat — verify it responds and streams something."""
        r = requests.post(
            f"{API}/admin/assistant/chat",
            headers=h,
            json={"message": "hi, just a smoke test", "stream": True},
            timeout=45,
            stream=True,
        )
        assert r.status_code == 200, r.text[:500] if not r.ok else "ok"
        # Consume a bit of the stream to verify it's actually streaming
        got_any = False
        try:
            for chunk in r.iter_content(chunk_size=256):
                if chunk:
                    got_any = True
                    break
        finally:
            r.close()
        assert got_any, "SSE stream returned nothing"

    def test_task_reply(self, h):
        """Reply endpoint expects a handoff task (has handoff_note). Create one first."""
        # Create a handoff task via /admin/assistant/tasks with source=handoff style
        # Since the endpoint may not support setting source directly, we'll search
        # existing tasks for one with source==handoff. If none, we skip.
        r = requests.get(f"{API}/admin/assistant/tasks", headers=h, timeout=15)
        assert r.status_code == 200
        data = r.json()
        tasks = data if isinstance(data, list) else data.get("tasks", [])
        handoff = next((t for t in tasks if t.get("source") == "handoff" or t.get("handoff_note")), None)
        if not handoff:
            pytest.skip("No handoff-type task available to reply to (endpoint only allows reply to handoff tasks)")
        tid = handoff["id"]
        rr = requests.post(
            f"{API}/admin/assistant/tasks/{tid}/reply",
            headers=h,
            json={"message": "TEST reply body from regression suite", "mark_done": False},
            timeout=15,
        )
        assert rr.status_code == 200, rr.text
        assert rr.json().get("ok") is True

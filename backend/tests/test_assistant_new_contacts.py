"""Tests for `new_contacts` block in Personal Assistant chat.

Verifies:
1. Assistant emits new_contacts block when asked to add 3 contacts -> persisted in db.contacts
2. Dedupe by name OR email (case-insensitive)
3. Regression: new_tasks and email_draft still work
4. Regression: /api/admin/assistant/marketing-status still returns valid data
"""
import os
import json
import time
import pytest
import requests
from pymongo import MongoClient

from dotenv import load_dotenv
load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "wayne@byrd-co.com"
ADMIN_PASSWORD = "byrdco2026"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

# Test contacts with clearly fake emails
TEST_CONTACTS_MSG = (
    "Add three contacts to my CRM: "
    "Sarah Chen (sarah_testnc@example-test.com, referral), "
    "Mike Torres (mike_testnc@example-test.com, lender), "
    "and Jenna Park (jenna_testnc@example-test.com, past sponsor)."
)
TEST_EMAILS = {
    "sarah_testnc@example-test.com",
    "mike_testnc@example-test.com",
    "jenna_testnc@example-test.com",
}
TEST_NAMES_LOWER = {"sarah chen", "mike torres", "jenna park"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, r.json()
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _cleanup_test_contacts(db):
    db.contacts.delete_many({"$or": [
        {"email": {"$in": list(TEST_EMAILS)}},
        {"name": {"$regex": "^(Sarah Chen|Mike Torres|Jenna Park)$", "$options": "i"}},
    ]})


@pytest.fixture(scope="module", autouse=True)
def _pre_and_post_cleanup(db):
    _cleanup_test_contacts(db)
    yield
    _cleanup_test_contacts(db)


def _sse_chat(h, message: str, timeout: int = 90) -> dict:
    """POST to /admin/assistant/chat as SSE stream, return the 'done' payload."""
    r = requests.post(
        f"{API}/admin/assistant/chat",
        headers=h,
        json={"message": message, "stream": True},
        timeout=timeout,
        stream=True,
    )
    assert r.status_code == 200, f"chat failed {r.status_code}: {r.text[:400]}"
    done = None
    tokens = []
    try:
        for raw in r.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "):
                continue
            try:
                payload = json.loads(raw[6:])
            except Exception:
                continue
            if payload.get("type") == "token":
                tokens.append(payload.get("content", ""))
            elif payload.get("type") == "done":
                done = payload
                break
            elif payload.get("type") == "error":
                pytest.fail(f"assistant error event: {payload}")
    finally:
        r.close()
    assert done is not None, f"No done event received. Tokens buffer:\n{''.join(tokens)[:2000]}"
    done["_raw_text"] = "".join(tokens)
    return done


class TestNewContactsBlock:
    def test_add_three_contacts_persists_and_returns_block(self, h, db):
        done = _sse_chat(h, TEST_CONTACTS_MSG, timeout=120)
        nc = done.get("new_contacts") or []
        assert isinstance(nc, list), f"new_contacts not a list: {done}"
        assert len(nc) == 3, (
            f"Expected 3 new_contacts, got {len(nc)}. done={json.dumps(done)[:1500]}"
        )
        # Verify each entry structure
        for entry in nc:
            for key in ("id", "name", "email", "phone", "tags", "notes"):
                assert key in entry, f"Missing field '{key}' in {entry}"
        names_lower = {(e.get("name") or "").lower() for e in nc}
        assert names_lower == TEST_NAMES_LOWER, f"names mismatch: {names_lower}"

        # Visible chat text should mention adding them
        text = (done.get("text") or "").lower()
        assert any(n in text for n in ("added", "adding", "saved", "created", "crm")), f"Response text lacks confirmation: {text[:400]}"

        # Verify db.contacts persistence via API
        r = requests.get(f"{API}/admin/contacts", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        contacts = r.json()
        if isinstance(contacts, dict):
            contacts = contacts.get("contacts") or contacts.get("items") or []
        emails_in_crm = {(c.get("email") or "").lower() for c in contacts}
        for te in TEST_EMAILS:
            assert te in emails_in_crm, f"{te} not persisted in /admin/contacts. Found: {emails_in_crm}"

    def test_dedupe_same_name_or_email(self, h, db):
        # Attempt to re-add Sarah Chen
        done = _sse_chat(h, "Add Sarah Chen (sarah_testnc@example-test.com) to my CRM again as a referral.", timeout=90)
        # New contacts should be empty OR not include Sarah
        nc = done.get("new_contacts") or []
        for entry in nc:
            assert (entry.get("name") or "").lower() != "sarah chen", (
                f"Sarah Chen duplicated! done.new_contacts={nc}"
            )
        # Db must contain exactly one Sarah Chen
        count = db.contacts.count_documents({"name": {"$regex": "^sarah chen$", "$options": "i"}})
        assert count == 1, f"Expected 1 Sarah Chen in db.contacts, got {count}"


class TestRegressionOtherBlocks:
    def test_new_tasks_still_works(self, h, db):
        done = _sse_chat(h, f"Remind me to follow up with TEST_regression_target_{int(time.time())} tomorrow at 3pm about paperwork.", timeout=90)
        created = done.get("created_tasks") or []
        assert len(created) >= 1, f"Expected a new task, got: {done}"
        # Ensure tasks endpoint reflects new task
        r = requests.get(f"{API}/admin/assistant/tasks", headers=h, timeout=15)
        assert r.status_code == 200
        tasks = r.json()
        # Endpoint returns dict of buckets {overdue, due_today, upcoming, done, dismissed}
        if isinstance(tasks, dict):
            flat = []
            for k in ("overdue", "due_today", "upcoming", "done", "dismissed"):
                flat.extend(tasks.get(k) or [])
            tasks = flat
        # Cleanup: mark test task IDs — best-effort
        new_ids = {t.get("id") for t in created if t.get("id")}
        assert new_ids, "no ids in created_tasks"
        api_ids = {t.get("id") for t in tasks}
        assert new_ids & api_ids, f"created task not visible via /assistant/tasks. created={new_ids}, api={list(api_ids)[:10]}"
        # cleanup
        for tid in new_ids:
            requests.delete(f"{API}/admin/assistant/tasks/{tid}", headers=h, timeout=10)

    def test_email_draft_still_works(self, h):
        done = _sse_chat(h, "Draft an email to Rod that we're moving forward on the Sugar Land refi.", timeout=90)
        ed = done.get("email_draft")
        assert ed and isinstance(ed, dict), f"Expected email_draft dict, got: {done}"
        assert ed.get("subject") or ed.get("body"), f"email_draft missing content: {ed}"

    def test_marketing_status_endpoint_still_works(self, h):
        r = requests.get(f"{API}/admin/assistant/marketing-status", headers=h, timeout=20)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert isinstance(data, dict), data

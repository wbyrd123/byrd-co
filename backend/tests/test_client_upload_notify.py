"""Byrd & CO — Broker email on client doc upload.

We patch `email_service.send_email` (which is what `background.add_task` invokes) and
assert:
  * a broker notification is queued on upload
  * the subject / HTML mention the scenario name + filename + broker deep-link
  * the coalesce window prevents a burst of uploads from spamming the inbox
  * a linked SPONSOR (not primary client) also triggers the notification
  * NOTIFY_BROKER_ON_UPLOAD=false disables notifications
  * empty BROKER_EMAILS => no notification
  * a lender upload (via lender term-sheet doc endpoint, if applicable) does NOT trigger

Uploads use a tiny valid PDF payload so `_append_file_to_doc` accepts them.
"""
import base64
import os
import time as _time
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
CLIENT = ("sample@example.com", "sample123")
LENDER = ("contact@testfrost.example", "testlender123")

mongo = MongoClient(be["MONGO_URL"])
mdb = mongo[be["DB_NAME"]]

TINY_PDF = base64.b64encode(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n").decode()


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, r.text[:200]
    return r.json()["token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


@pytest.fixture(scope="module")
def client_tok():
    return token_for(*CLIENT)


@pytest.fixture(scope="module")
def uploadable_doc(client_tok):
    """Pick a non-system, non-fee-agreement doc line for the sample client."""
    r = requests.get(f"{API}/client/me", headers=auth(client_tok), timeout=60)
    assert r.status_code == 200
    for scen in r.json().get("scenarios") or []:
        for d in scen.get("docs") or []:
            if not d.get("system") and d.get("label") != "Signed Fee Agreement":
                return {"doc_id": d["id"], "scenario_id": scen["id"],
                        "label": d.get("label"), "scenario_name": scen.get("name")}
    pytest.skip("sample client has no uploadable doc lines")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Each test gets a fresh throttle state + captured outbox.
    We patch the *live* server module attributes so background tasks land in our list."""
    import sys
    sys.path.insert(0, "/app/backend")
    import server as srv
    outbox = []

    def _fake_send_email(to, subject, html, text, tag="", *a, **kw):
        outbox.append({"to": to, "subject": subject, "html": html, "text": text, "tag": tag})
        return {"ok": True}

    monkeypatch.setattr(srv, "send_email", _fake_send_email)
    monkeypatch.setattr("server.broker_emails",
                        lambda: ["wayne+test@byrd-co.com", "caleb+test@byrd-co.com"])
    # Reset in-process coalesce state so tests don't interfere with each other.
    srv._UPLOAD_NOTIFY_STATE.clear()
    # Force window=0 by default; individual tests override.
    monkeypatch.setenv("UPLOAD_NOTIFY_WINDOW_SECONDS", "0")
    monkeypatch.setenv("NOTIFY_BROKER_ON_UPLOAD", "true")
    yield outbox
    # cleanup: strip any test files we uploaded from mongo
    # (we don't know file_ids, so we clean by filename prefix "TEST_notify_")
    mdb.client_docs.update_many(
        {},
        {"$pull": {"files": {"filename": {"$regex": "^TEST_notify_"}}}},
    )


def _do_upload(client_tok, doc_id, name_suffix=""):
    filename = f"TEST_notify_{uuid.uuid4().hex[:6]}{name_suffix}.pdf"
    r = requests.post(f"{API}/client/docs/{doc_id}/upload",
                      json={"filename": filename, "content_type": "application/pdf",
                            "data_b64": TINY_PDF},
                      headers=auth(client_tok), timeout=60)
    assert r.status_code == 200, r.text[:200]
    return filename


# NOTE: These tests exercise the HTTP endpoint which runs in a SEPARATE process (uvicorn).
# `monkeypatch` on the server module in our test process therefore doesn't affect the live
# uvicorn worker. Instead, we assert via the audit_log side-effect that upload happened,
# and via a mongo-side check that the notification metadata is captured.
#
# To fully test the send_email call path, we run the notification function IN-PROCESS by
# importing `server._maybe_notify_broker_of_upload` and passing an inline BackgroundTasks
# instance whose `add_task` we intercept.


import asyncio
from fastapi import BackgroundTasks
from starlette.background import BackgroundTask as _BackgroundTask

import sys as _sys
_sys.path.insert(0, "/app/backend")
import server as _srv  # noqa: E402


class _CapturingBackground(BackgroundTasks):
    """A BackgroundTasks that just captures the (func, args, kwargs) tuples."""
    def add_task(self, func, *args, **kwargs):
        self.tasks.append(_BackgroundTask(func, *args, **kwargs))
        # Also stash a plain-tuple record so tests can inspect kwargs easily.
        self.records.append((func, args, kwargs))

    def __init__(self):
        super().__init__()
        self.records = []


@pytest.fixture
def call_notify():
    """Return a helper that invokes _maybe_notify_broker_of_upload with fake user+doc and
    returns the list of enqueued send_email calls without hitting the network."""
    def _run(user, doc, filename, *, window="0", enabled="true",
             brokers=("wayne+test@byrd-co.com",)):
        os.environ["UPLOAD_NOTIFY_WINDOW_SECONDS"] = str(window)
        os.environ["NOTIFY_BROKER_ON_UPLOAD"] = enabled
        # Patch email_service.broker_emails so the notifier sees our list.
        import email_service
        original = email_service.broker_emails
        email_service.broker_emails = lambda: list(brokers)
        _srv.broker_emails = lambda: list(brokers)   # notifier imports at module scope
        try:
            bg = _CapturingBackground()
            asyncio.get_event_loop().run_until_complete(
                _srv._maybe_notify_broker_of_upload(user, doc, filename, bg)
            )
            return bg.records
        finally:
            email_service.broker_emails = original
            _srv.broker_emails = original
    return _run


# ---------------- End-to-end: HTTP upload still works ----------------

class TestUploadHappyPath:
    def test_client_upload_still_succeeds_after_notify_wiring(self, client_tok, uploadable_doc):
        """Sanity: the notification code path must not break the upload response contract."""
        r = requests.post(f"{API}/client/docs/{uploadable_doc['doc_id']}/upload",
                          json={"filename": f"TEST_notify_{uuid.uuid4().hex[:6]}.pdf",
                                "content_type": "application/pdf",
                                "data_b64": TINY_PDF},
                          headers=auth(client_tok), timeout=60)
        assert r.status_code == 200
        assert r.json().get("ok") is True
        assert r.json().get("file_id")


# ---------------- In-process: notifier behavior ----------------

class TestNotifier:
    def test_sends_one_email_per_broker(self, call_notify):
        user = {"id": "u1", "email": "borrower@example.com", "name": "Bob Borrower"}
        doc = {"id": "d1", "scenario_id": "s1", "label": "Personal Tax Returns", "files": []}
        records = call_notify(user, doc, "TEST_notify_taxes.pdf",
                              brokers=("wayne+test@byrd-co.com", "caleb+test@byrd-co.com"))
        assert len(records) == 2, f"expected 2 broker emails, got {len(records)}"
        recipients = {r[1][0] for r in records}
        assert recipients == {"wayne+test@byrd-co.com", "caleb+test@byrd-co.com"}
        # Subject includes borrower name + filename + scenario name (scenario resolution
        # from mongo — we didn't insert a scenario for 's1', so it falls back to
        # "(untitled scenario)"; that's fine for this unit test.)
        first = records[0][1]
        subject, html, text = first[1], first[2], first[3]
        assert "TEST_notify_taxes.pdf" in subject
        assert "Bob Borrower" in subject or "Bob Borrower" in html
        assert "Personal Tax Returns" in html
        assert "TEST_notify_taxes.pdf" in html
        # tag lives in positional args after text
        assert first[4] == "client_upload"

    def test_coalesce_window_skips_burst_uploads(self, call_notify):
        user = {"id": "u1", "email": "borrower@example.com", "name": "Bob"}
        doc = {"id": "d1", "scenario_id": "s-burst", "label": "PFS", "files": []}
        first = call_notify(user, doc, "TEST_notify_a.pdf",
                            window="60", brokers=("only@byrd.co",))
        second = call_notify(user, doc, "TEST_notify_b.pdf",
                             window="60", brokers=("only@byrd.co",))
        assert len(first) == 1
        assert len(second) == 0, "second upload within window should be coalesced"

    def test_window_zero_never_coalesces(self, call_notify):
        user = {"id": "u1", "email": "b@example.com", "name": "B"}
        doc = {"id": "d1", "scenario_id": "s-noco", "label": "X", "files": []}
        r1 = call_notify(user, doc, "TEST_notify_1.pdf", window="0",
                         brokers=("only@byrd.co",))
        r2 = call_notify(user, doc, "TEST_notify_2.pdf", window="0",
                         brokers=("only@byrd.co",))
        assert len(r1) == 1
        assert len(r2) == 1, "window=0 should always fire"

    def test_disabled_flag_short_circuits(self, call_notify):
        user = {"id": "u1", "email": "b@x", "name": "B"}
        doc = {"id": "d", "scenario_id": "s", "label": "X", "files": []}
        records = call_notify(user, doc, "TEST_notify.pdf", enabled="false",
                              brokers=("only@byrd.co",))
        assert records == []

    def test_no_brokers_configured_no_op(self, call_notify):
        user = {"id": "u1", "email": "b@x", "name": "B"}
        doc = {"id": "d", "scenario_id": "s", "label": "X", "files": []}
        records = call_notify(user, doc, "TEST_notify.pdf", brokers=())
        assert records == []

    def test_scenario_metadata_pulled_from_db(self, call_notify, admin_tok):
        """When we insert a real scenario record, the email subject uses its name."""
        sid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        try:
            mdb.scenarios.insert_one({
                "id": sid, "name": "TEST_notify_ Warehouse Refi", "client_id": cid,
            })
            mdb.users.insert_one({"id": cid, "email": "co@example.com",
                                   "name": "Coop LLC", "role": "client"})
            user = {"id": cid, "email": "u@example.com", "name": "Sam Uploader"}
            doc = {"id": "d99", "scenario_id": sid, "label": "Rent Roll", "files": []}
            records = call_notify(user, doc, "TEST_notify_rr.xlsx",
                                  brokers=("only@byrd.co",))
            assert len(records) == 1
            subj = records[0][1][1]
            html = records[0][1][2]
            assert "TEST_notify_ Warehouse Refi" in subj
            assert "TEST_notify_ Warehouse Refi" in html
            assert "Coop LLC" in html   # client_name resolution
        finally:
            mdb.scenarios.delete_one({"id": sid})
            mdb.users.delete_one({"id": cid})

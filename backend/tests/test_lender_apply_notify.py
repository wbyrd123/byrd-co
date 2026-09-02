"""Byrd & CO — Broker notification on public lender-apply submissions."""
import os
import uuid
import time as _time
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE}/api"

ADMIN = ("wayne@byrd-co.com", "byrdco2026")

mongo = MongoClient(be["MONGO_URL"])
mdb = mongo[be["DB_NAME"]]

TAG = f"TEST_lenderapply_{os.getpid()}_"


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200
    return r.json()["token"]


def auth(t): return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    mdb.lenders.delete_many({"name": {"$regex": f"^{TAG}"}})
    mdb.audit_log.delete_many({"metadata.tag_prefix": TAG})


# ---------------- HTTP: end-to-end via the running uvicorn ----------------

class TestApplyLive:
    def test_apply_returns_ok_and_persists(self):
        email = f"{TAG.lower()}{uuid.uuid4().hex[:6]}@example.com"
        body = {
            "lender_name": f"{TAG}Alpha Bank",
            "institution_type": "bank",
            "contact_name": "QA Bot",
            "contact_email": email,
            "property_types": ["Industrial"],
            "property_subtypes": ["Manufacturing Heavy Industrial"],
            "geography": ["TX"],
            "min_loan": 1_000_000,
            "max_loan": 25_000_000,
            "notes": "Test notes — please ignore.",
        }
        r = requests.post(f"{API}/public/lender/apply", json=body, timeout=60)
        assert r.status_code == 200, r.text[:200]
        assert r.json()["ok"] is True
        # lender row created + specialties saved
        rec = mdb.lenders.find_one({"apply_email": email}, {"_id": 0})
        assert rec and rec["property_subtypes"] == body["property_subtypes"]

    def test_pending_lenders_endpoint_shows_new_application(self, ):
        # Freshly applied lender should show up on the pending endpoint the sidebar polls.
        admin_tok = token_for(*ADMIN)
        # Create a unique application
        email = f"{TAG.lower()}pending{uuid.uuid4().hex[:6]}@example.com"
        r = requests.post(f"{API}/public/lender/apply", json={
            "lender_name": f"{TAG}Pending Nudge",
            "institution_type": "credit_union",
            "contact_name": "QA",
            "contact_email": email,
            "property_types": ["Retail"], "geography": ["TX"],
        }, timeout=60)
        assert r.status_code == 200

        pr = requests.get(f"{API}/admin/marketplace/pending-lenders",
                          headers=auth(admin_tok), timeout=60)
        assert pr.status_code == 200
        names = [x.get("name") for x in pr.json()]
        assert f"{TAG}Pending Nudge" in names


# ---------------- In-process: notifier behavior ----------------

import asyncio
import sys as _sys
_sys.path.insert(0, "/app/backend")
from fastapi import BackgroundTasks
from starlette.background import BackgroundTask as _BackgroundTask
import server as _srv           # noqa: E402
import email_service as _emsvc  # noqa: E402


class _CapturingBackground(BackgroundTasks):
    def __init__(self):
        super().__init__()
        self.records = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append(_BackgroundTask(func, *args, **kwargs))
        self.records.append((func, args, kwargs))


def _run_apply(body, brokers=("wayne+test@byrd-co.com",),
               notify_env="true"):
    """Invoke the lender_apply endpoint IN-PROCESS with a fake BackgroundTasks so we can
    inspect what emails would be enqueued without hitting Postmark."""
    os.environ["NOTIFY_BROKER_ON_LENDER_APPLY"] = notify_env
    orig_be = _srv.broker_emails
    orig_em = _emsvc.broker_emails
    _srv.broker_emails = lambda: list(brokers)
    _emsvc.broker_emails = lambda: list(brokers)
    try:
        from pydantic import BaseModel  # noqa
        # Build the pydantic model the endpoint expects
        payload = _srv.LenderApplyBody(**body)
        # Fake Request
        class _Req:
            client = type("c", (), {"host": "127.0.0.1"})()
            headers = {}
        bg = _CapturingBackground()
        asyncio.get_event_loop().run_until_complete(
            _srv.lender_apply(payload, bg, _Req())
        )
        return bg.records
    finally:
        _srv.broker_emails = orig_be
        _emsvc.broker_emails = orig_em


class TestNotifier:
    def test_emails_all_brokers_plus_applicant(self):
        email = f"{TAG.lower()}nfy{uuid.uuid4().hex[:6]}@example.com"
        recs = _run_apply({
            "lender_name": f"{TAG}Notify Bank",
            "institution_type": "bank",
            "contact_name": "Bob Broker",
            "contact_email": email,
            "contact_phone": "555-0101",
            "property_types": ["Industrial", "Retail"],
            "property_subtypes": ["Manufacturing Heavy Industrial"],
            "geography": ["tx", "la"],
            "min_loan": 500_000,
            "max_loan": 10_000_000,
            "notes": "Focus on secondary markets.",
        }, brokers=("wayne+test@byrd-co.com", "caleb+test@byrd-co.com"))
        # 1 applicant confirmation + 2 broker alerts = 3 send_email calls
        assert len(recs) == 3, f"expected 3 emails, got {len(recs)}: {[r[1][:3] for r in recs]}"
        tags = [r[1][4] for r in recs]
        assert tags.count("lender_application") == 1
        assert tags.count("lender_application_alert") == 2
        # Broker alerts go to the broker addresses (not the applicant)
        broker_recipients = {r[1][0] for r in recs if r[1][4] == "lender_application_alert"}
        assert broker_recipients == {"wayne+test@byrd-co.com", "caleb+test@byrd-co.com"}
        # HTML content sanity: mentions lender name + subtype specialty
        broker_html = next(r[1][2] for r in recs if r[1][4] == "lender_application_alert")
        assert f"{TAG}Notify Bank" in broker_html
        assert "Manufacturing Heavy Industrial" in broker_html
        assert "TX" in broker_html and "LA" in broker_html   # geo upper-cased
        # Subject prefixed for filtering
        broker_subj = next(r[1][1] for r in recs if r[1][4] == "lender_application_alert")
        assert broker_subj.startswith("[Byrd] New lender application —")

    def test_kill_switch_suppresses_broker_alert_but_keeps_applicant_confirmation(self):
        email = f"{TAG.lower()}kill{uuid.uuid4().hex[:6]}@example.com"
        recs = _run_apply({
            "lender_name": f"{TAG}Kill Switch",
            "institution_type": "bank",
            "contact_name": "K",
            "contact_email": email,
            "property_types": ["Multifamily"], "geography": ["TX"],
        }, brokers=("wayne+test@byrd-co.com",), notify_env="false")
        tags = [r[1][4] for r in recs]
        assert "lender_application" in tags, "applicant confirmation must still fire"
        assert "lender_application_alert" not in tags, "broker alert must be suppressed"

    def test_no_brokers_no_alert(self):
        email = f"{TAG.lower()}nob{uuid.uuid4().hex[:6]}@example.com"
        recs = _run_apply({
            "lender_name": f"{TAG}No Brokers",
            "institution_type": "bank", "contact_name": "N",
            "contact_email": email,
            "property_types": ["Office"], "geography": ["TX"],
        }, brokers=())
        tags = [r[1][4] for r in recs]
        assert "lender_application" in tags
        assert "lender_application_alert" not in tags

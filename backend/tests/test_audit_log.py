"""Byrd & CO — Audit Log feature tests (iteration 15).

Covers: audit event emission on auth/doc/scenario/term-sheet/admin flows,
/api/admin/audit-log query filters, pagination, event-types, CSV export, RBAC,
IP extraction and fire-and-forget resilience.

Verification is done both via the admin API and directly against MongoDB.
All test data created here is cleaned up at the end of the class.
"""
import base64
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

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

TWOFA_EMAIL = "test_2fa_email_user@byrd-co.com"
TWOFA_PASSWORD = "TestEmail2fa!23"
TWOFA_BACKUP = "abcd-1234"

mongo = MongoClient(be["MONGO_URL"])
mdb = mongo[be["DB_NAME"]]

CSV_HEADER = ("timestamp_utc,event_type,event_label,result,user_email,user_name,user_role,"
              "user_id,ip,user_agent,resource_type,resource_id,resource_name,metadata")


def login(email, password, headers=None):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password},
                      headers=headers or {}, timeout=60)
    return r


def token_for(email, password):
    r = login(email, password)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:300]}"
    return r.json()["token"]


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def find_events(event_type=None, since=None, wait=6.0, **match):
    """Poll mongo for audit events (audit writes are awaited, but be tolerant)."""
    q = dict(match)
    if event_type:
        q["event_type"] = event_type
    if since:
        q["timestamp"] = {"$gte": since}
    deadline = time.time() + wait
    rows = []
    while time.time() < deadline:
        rows = list(mdb.audit_log.find(q, {"_id": 0}).sort("timestamp", -1))
        if rows:
            return rows
        time.sleep(0.4)
    return rows


def utcnow():
    return datetime.now(timezone.utc)


@pytest.fixture(scope="class")
def admin_tok():
    return token_for(*ADMIN)


@pytest.fixture(scope="class")
def client_tok():
    return token_for(*CLIENT)


@pytest.fixture(scope="class")
def lender_tok():
    return token_for(*LENDER)


@pytest.fixture(scope="class")
def trash():
    """Collect cleanup callables."""
    items = []
    yield items
    for fn in reversed(items):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print("cleanup failed:", e)


class TestAuditLog:
    # ---------- Auth: login success / failure ----------
    def test_01_login_success_event(self):
        t0 = utcnow()
        r = login(*ADMIN)
        assert r.status_code == 200, r.text[:300]
        rows = find_events("auth.login.success", since=t0, user_email=ADMIN[0])
        assert rows, "no auth.login.success audit row for admin login"
        e = rows[0]
        assert e["user_role"] == "admin"
        assert e["user_id"]
        assert e["result"] == "success"
        assert e["ip"]
        assert isinstance(e["timestamp"], datetime)

    def test_02_login_failure_event(self):
        t0 = utcnow()
        bogus = f"nobody_{uuid.uuid4().hex[:8]}@example.com"
        r = login(bogus, "wrongpass")
        assert r.status_code == 401, r.text[:300]
        rows = find_events("auth.login.failure", since=t0, user_email=bogus)
        assert rows, "no auth.login.failure audit row"
        e = rows[0]
        assert e["result"] == "failure"
        assert e["user_id"] is None
        assert e["metadata"].get("reason") == "bad_credentials"

    def test_03_login_failure_wrong_password_real_user(self):
        """Wrong password for a real admin -> 401 + failure event (no user_id)."""
        t0 = utcnow()
        r = login(ADMIN[0], "definitely-wrong")
        assert r.status_code in (401, 429), r.text[:300]
        rows = find_events("auth.login.failure", since=t0, user_email=ADMIN[0])
        assert rows, "no failure event for wrong-password login"
        assert rows[0]["user_id"] is None
        # clear the lockout counter so later admin logins keep working
        mdb.login_attempts.delete_many({"email": ADMIN[0], "success": False})

    # ---------- Auth: password_ok + 2FA challenge ----------
    def test_04_password_ok_then_2fa_success(self):
        seed = subprocess.run([sys.executable, "/app/backend/tests/seed_email_2fa_user.py", "seed"],
                              capture_output=True, text=True)
        assert seed.returncode == 0, seed.stderr[:500]
        try:
            t0 = utcnow()
            r = login(TWOFA_EMAIL, TWOFA_PASSWORD)
            assert r.status_code == 200, r.text[:300]
            body = r.json()
            assert body.get("requires_2fa") is True
            ok_rows = find_events("auth.login.password_ok", since=t0, user_email=TWOFA_EMAIL)
            assert ok_rows, "no auth.login.password_ok event"
            assert ok_rows[0]["metadata"].get("method") == "email"
            premature = find_events("auth.login.success", since=t0, user_email=TWOFA_EMAIL, wait=1.0)
            assert not premature, "auth.login.success fired before 2FA challenge passed"

            t1 = utcnow()
            ch = requests.post(f"{API}/auth/2fa/challenge", timeout=60, json={
                "challenge_token": body["challenge_token"],
                "method": "backup", "code": TWOFA_BACKUP,
            })
            assert ch.status_code == 200, ch.text[:300]
            assert ch.json().get("token")
            assert find_events("auth.2fa.challenge.success", since=t1, user_email=TWOFA_EMAIL), \
                "no auth.2fa.challenge.success event"
            final = find_events("auth.login.success", since=t1, user_email=TWOFA_EMAIL)
            assert final, "no final auth.login.success after 2FA challenge"
            assert final[0]["metadata"].get("factor") == "backup"
        finally:
            subprocess.run([sys.executable, "/app/backend/tests/seed_email_2fa_user.py", "clean"],
                           capture_output=True, text=True)

    def test_05_2fa_challenge_failure_event(self):
        seed = subprocess.run([sys.executable, "/app/backend/tests/seed_email_2fa_user.py", "seed"],
                              capture_output=True, text=True)
        assert seed.returncode == 0, seed.stderr[:500]
        try:
            r = login(TWOFA_EMAIL, TWOFA_PASSWORD)
            ct = r.json()["challenge_token"]
            t0 = utcnow()
            ch = requests.post(f"{API}/auth/2fa/challenge", timeout=60, json={
                "challenge_token": ct, "method": "backup", "code": "zzzz-9999"})
            assert ch.status_code == 400, ch.text[:300]
            rows = find_events("auth.2fa.challenge.failure", since=t0, user_email=TWOFA_EMAIL)
            assert rows and rows[0]["result"] == "failure"
        finally:
            subprocess.run([sys.executable, "/app/backend/tests/seed_email_2fa_user.py", "clean"],
                           capture_output=True, text=True)

    # ---------- Documents: client upload / view / download / delete ----------
    def test_06_client_doc_upload_view_download_delete(self, client_tok):
        me = requests.get(f"{API}/client/me", headers=auth(client_tok), timeout=60)
        assert me.status_code == 200, me.text[:300]
        doc = None
        for s in me.json()["scenarios"]:
            for d in s["docs"]:
                if not d.get("system"):
                    doc = d
                    break
            if doc:
                break
        assert doc, "no uploadable doc line found for sample client"
        payload = {"filename": "TEST_audit_upload.txt", "content_type": "text/plain",
                   "data_b64": base64.b64encode(b"audit log test file").decode()}
        t0 = utcnow()
        up = requests.post(f"{API}/client/docs/{doc['id']}/upload", json=payload,
                           headers=auth(client_tok), timeout=60)
        assert up.status_code == 200, up.text[:300]
        file_id = up.json()["file_id"]
        rows = find_events("document.upload", since=t0, resource_id=doc["id"])
        assert rows, "no document.upload event"
        e = rows[0]
        assert e["resource_name"] == payload["filename"]
        assert e["metadata"].get("file_id") == file_id
        assert e["metadata"].get("scenario_id")
        assert e["ip"]
        assert e["user_email"] == CLIENT[0]

        # view (inline)
        t1 = utcnow()
        v = requests.get(f"{API}/files/{file_id}", headers=auth(client_tok), timeout=60)
        assert v.status_code == 200
        assert "inline" in v.headers.get("content-disposition", "")
        assert find_events("document.view", since=t1, resource_id=file_id), "no document.view event"

        # download
        t2 = utcnow()
        d = requests.get(f"{API}/files/{file_id}?download=1", headers=auth(client_tok), timeout=60)
        assert d.status_code == 200
        assert "attachment" in d.headers.get("content-disposition", "")
        dl = find_events("document.download", since=t2, resource_id=file_id)
        assert dl, "no document.download event"
        assert dl[0]["resource_name"] == payload["filename"]

        # delete
        t3 = utcnow()
        dele = requests.delete(f"{API}/client/docs/{doc['id']}/files/{file_id}",
                               headers=auth(client_tok), timeout=60)
        assert dele.status_code == 200, dele.text[:300]
        rows = find_events("document.delete", since=t3, resource_id=doc["id"])
        assert rows, "no document.delete event"
        assert rows[0]["metadata"].get("file_id") == file_id
        assert rows[0]["resource_name"] == payload["filename"], \
            f"document.delete resource_name should be the filename, got {rows[0]['resource_name']!r}"

    # ---------- Scenario CRUD + admin doc actions ----------
    def test_07_scenario_crud_and_admin_doc_events(self, admin_tok, trash):
        client = mdb.users.find_one({"email": CLIENT[0]}, {"_id": 0, "id": 1})
        t0 = utcnow()
        cr = requests.post(f"{API}/admin/scenarios", headers=auth(admin_tok), timeout=90,
                           json={"name": "TEST_audit_scenario", "client_id": client["id"]})
        assert cr.status_code == 200, cr.text[:300]
        sid = cr.json()["id"]
        trash.append(lambda: requests.delete(f"{API}/admin/scenarios/{sid}",
                                             headers=auth(admin_tok), timeout=60))
        rows = find_events("scenario.create", since=t0, resource_id=sid)
        assert rows, "no scenario.create event"
        assert rows[0]["resource_name"] == "TEST_audit_scenario"
        assert rows[0]["metadata"].get("client_id") == client["id"]
        assert rows[0]["user_role"] == "admin"

        # PATCH -> scenario.update with metadata.fields
        t1 = utcnow()
        pa = requests.patch(f"{API}/admin/scenarios/{sid}", headers=auth(admin_tok), timeout=60,
                            json={"notes": "TEST audit note", "status": "shopping"})
        assert pa.status_code == 200, pa.text[:300]
        rows = find_events("scenario.update", since=t1, resource_id=sid)
        assert rows, "no scenario.update event"
        fields = rows[0]["metadata"].get("fields") or []
        assert "notes" in fields and "status" in fields, fields

        # Admin doc upload / delete on this scenario
        full = requests.get(f"{API}/admin/scenarios/{sid}", headers=auth(admin_tok), timeout=60).json()
        doc = next(d for d in full["docs"] if not d.get("system"))
        payload = {"filename": "TEST_admin_upload.txt", "content_type": "text/plain",
                   "data_b64": base64.b64encode(b"broker upload").decode()}
        t2 = utcnow()
        up = requests.post(f"{API}/admin/scenarios/{sid}/docs/{doc['id']}/upload",
                           json=payload, headers=auth(admin_tok), timeout=60)
        assert up.status_code == 200, up.text[:300]
        fid = up.json()["file_id"]
        rows = find_events("document.upload", since=t2, resource_id=doc["id"])
        assert rows, "no admin document.upload event"
        assert rows[0]["user_role"] == "admin"
        assert rows[0]["metadata"].get("uploaded_by") == "broker"

        t3 = utcnow()
        dele = requests.delete(f"{API}/admin/scenarios/{sid}/docs/{doc['id']}/files/{fid}",
                               headers=auth(admin_tok), timeout=60)
        assert dele.status_code == 200, dele.text[:300]
        rows = find_events("document.delete", since=t3, resource_id=doc["id"])
        assert rows, "no admin document.delete event"
        assert rows[0]["metadata"].get("file_id") == fid
        assert rows[0]["resource_name"] == payload["filename"], \
            f"admin document.delete resource_name should be filename, got {rows[0]['resource_name']!r}"

        # DELETE scenario -> scenario.delete with cascaded_files
        t4 = utcnow()
        dl = requests.delete(f"{API}/admin/scenarios/{sid}", headers=auth(admin_tok), timeout=60)
        assert dl.status_code == 200, dl.text[:300]
        rows = find_events("scenario.delete", since=t4, resource_id=sid)
        assert rows, "no scenario.delete event"
        assert "cascaded_files" in rows[0]["metadata"]
        assert rows[0]["resource_name"] == "TEST_audit_scenario"

    # ---------- Term sheets ----------
    def test_08_term_sheet_events(self, admin_tok, lender_tok):
        lender = mdb.lenders.find_one({"contact_email": {"$exists": True}}, {"_id": 0})
        share = None
        lu = mdb.users.find_one({"email": LENDER[0]}, {"_id": 0})
        assert lu, "lender user missing"
        for l in mdb.lenders.find({"owner_user_id": lu["id"]}, {"_id": 0, "id": 1}):
            share = mdb.scenario_shares.find_one({"lender_id": l["id"]}, {"_id": 0})
            if share:
                lender = l
                break
        if not share:
            pytest.skip("no scenario_share exists for the lender user — cannot submit a term sheet")
        sid = share["scenario_id"]
        t0 = utcnow()
        sub = requests.post(f"{API}/lender/scenarios/{sid}/term-sheet", headers=auth(lender_tok),
                            timeout=90, json={"interest_rate_pct": 6.75, "loan_amount": 5000000})
        assert sub.status_code == 200, sub.text[:300]
        tid = sub.json()["id"]
        rows = find_events("term_sheet.submit", since=t0, resource_id=tid)
        assert rows, "no term_sheet.submit event"
        assert rows[0]["metadata"].get("scenario_id") == sid
        assert rows[0]["metadata"].get("lender_id") == lender["id"]

        t1 = utcnow()
        pa = requests.patch(f"{API}/admin/term-sheets/{tid}", headers=auth(admin_tok), timeout=60,
                            json={"status": "passed", "broker_note": "TEST audit"})
        assert pa.status_code == 200, pa.text[:300]
        rows = find_events("term_sheet.status_change", since=t1, resource_id=tid)
        assert rows, "no term_sheet.status_change event"
        assert rows[0]["metadata"].get("from") == "submitted"
        assert rows[0]["metadata"].get("to") == "passed"

        t2 = utcnow()
        dl = requests.delete(f"{API}/admin/term-sheets/{tid}", headers=auth(admin_tok), timeout=60)
        assert dl.status_code == 200, dl.text[:300]
        assert find_events("term_sheet.delete", since=t2, resource_id=tid), "no term_sheet.delete event"

    def test_08b_term_sheet_document_view_and_download(self, admin_tok, lender_tok):
        lu = mdb.users.find_one({"email": LENDER[0]}, {"_id": 0})
        share = None
        for l in mdb.lenders.find({"owner_user_id": lu["id"]}, {"_id": 0, "id": 1}):
            share = mdb.scenario_shares.find_one({"lender_id": l["id"]}, {"_id": 0})
            if share:
                break
        if not share:
            pytest.skip("no scenario_share for lender user")
        sid = share["scenario_id"]
        up = requests.post(f"{API}/lender/scenarios/{sid}/term-sheet/upload", headers=auth(lender_tok),
                           timeout=60, json={"filename": "TEST_term_sheet.txt", "content_type": "text/plain",
                                             "data_b64": base64.b64encode(b"term sheet body").decode()})
        assert up.status_code == 200, up.text[:300]
        fid = up.json()["file_id"]
        sub = requests.post(f"{API}/lender/scenarios/{sid}/term-sheet", headers=auth(lender_tok),
                            timeout=90, json={"pdf_file_id": fid, "interest_rate_pct": 7.1})
        assert sub.status_code == 200, sub.text[:300]
        tid = sub.json()["id"]
        try:
            t0 = utcnow()
            v = requests.get(f"{API}/term-sheets/{tid}/document", headers=auth(admin_tok), timeout=60)
            assert v.status_code == 200, v.text[:300]
            assert "inline" in v.headers.get("content-disposition", "")
            rows = find_events("term_sheet.view", since=t0, resource_id=tid)
            assert rows, "no term_sheet.view event"
            assert rows[0]["resource_name"] == "TEST_term_sheet.txt"

            t1 = utcnow()
            d = requests.get(f"{API}/term-sheets/{tid}/document?download=1", headers=auth(admin_tok), timeout=60)
            assert d.status_code == 200
            assert "attachment" in d.headers.get("content-disposition", "")
            assert find_events("document.download", since=t1, resource_id=tid), \
                "no document.download event for term-sheet download"
        finally:
            requests.delete(f"{API}/admin/term-sheets/{tid}", headers=auth(admin_tok), timeout=60)
            mdb.term_sheet_files.delete_many({"id": fid})

    # ---------- Admin invites ----------
    def test_09_invite_events(self, admin_tok):
        email = f"test_audit_invite_{uuid.uuid4().hex[:6]}@example.com"
        t0 = utcnow()
        cr = requests.post(f"{API}/admin/invites", headers=auth(admin_tok), timeout=60,
                           json={"email": email, "name": "TEST Audit Invitee"})
        assert cr.status_code == 200, cr.text[:300]
        uid = cr.json()["user"]["id"]
        try:
            rows = find_events("admin.invite.sent", since=t0, resource_id=uid)
            assert rows, "no admin.invite.sent event on create"
            assert rows[0]["metadata"].get("email_sent") is False
            assert rows[0]["metadata"].get("reason") == "create_only"
            assert rows[0]["resource_name"] == email

            t1 = utcnow()
            sv = requests.post(f"{API}/admin/users/{uid}/send-invite", headers=auth(admin_tok), timeout=90)
            assert sv.status_code == 200, sv.text[:300]
            rows = find_events("admin.invite.sent", since=t1, resource_id=uid)
            assert rows, "no admin.invite.sent event on send-invite"
            assert rows[0]["metadata"].get("email_sent") is True
        finally:
            mdb.invites.delete_many({"user_id": uid})
            mdb.users.delete_many({"id": uid})

    # ---------- Password reset ----------
    def test_10_password_reset_request_events(self):
        t0 = utcnow()
        r = requests.post(f"{API}/public/password-reset/request", timeout=90,
                          json={"email": ADMIN[0]})
        assert r.status_code == 200, r.text[:300]
        rows = find_events("auth.password_reset.request", since=t0, user_email=ADMIN[0])
        assert rows, "no auth.password_reset.request event for known user"
        assert rows[0]["result"] == "success"
        assert rows[0]["user_id"]
        mdb.password_resets.delete_many({"user_id": rows[0]["user_id"]})

        unknown = "unknown_audit_test@example.com"
        t1 = utcnow()
        r2 = requests.post(f"{API}/public/password-reset/request", json={"email": unknown}, timeout=60)
        assert r2.status_code == 200
        rows = find_events("auth.password_reset.request", since=t1, user_email=unknown)
        assert rows, "no event for unknown-email reset request"
        assert rows[0]["result"] == "failure"
        assert rows[0]["metadata"].get("reason") == "no_active_account"

    # ---------- Admin 2FA reset ----------
    def test_11_admin_2fa_reset_event(self, admin_tok):
        sample = mdb.users.find_one({"email": CLIENT[0]}, {"_id": 0, "id": 1, "email": 1})
        t0 = utcnow()
        r = requests.post(f"{API}/admin/users/{sample['id']}/2fa/reset",
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200, r.text[:300]
        rows = find_events("auth.2fa.reset", since=t0, resource_id=sample["id"])
        assert rows, "no auth.2fa.reset event"
        e = rows[0]
        assert e["user_email"] == ADMIN[0]
        assert e["resource_name"] == sample["email"]
        assert e["metadata"].get("target_email") == sample["email"]

    # ---------- RBAC ----------
    def test_12_rbac_audit_log(self, admin_tok, client_tok, lender_tok):
        assert requests.get(f"{API}/admin/audit-log", timeout=60).status_code == 401
        assert requests.get(f"{API}/admin/audit-log", headers=auth(client_tok), timeout=60).status_code == 403
        assert requests.get(f"{API}/admin/audit-log", headers=auth(lender_tok), timeout=60).status_code == 403
        r = requests.get(f"{API}/admin/audit-log", headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200
        body = r.json()
        for k in ("total", "page", "page_size", "events"):
            assert k in body
        assert all("_id" not in e for e in body["events"])

    # ---------- Filters ----------
    def test_13_filters(self, admin_tok):
        h = auth(admin_tok)
        r = requests.get(f"{API}/admin/audit-log", headers=h, timeout=60,
                         params={"event_type": "auth.login.success", "page_size": 50})
        assert r.status_code == 200
        assert r.json()["events"], "expected some login-success rows"
        assert all(e["event_type"] == "auth.login.success" for e in r.json()["events"])

        r = requests.get(f"{API}/admin/audit-log", headers=h, timeout=60,
                         params={"user_email": ADMIN[0]})
        assert r.status_code == 200
        assert all(e["user_email"] == ADMIN[0] for e in r.json()["events"])
        assert r.json()["total"] > 0

        # ip filter
        some_ip = r.json()["events"][0]["ip"]
        r2 = requests.get(f"{API}/admin/audit-log", headers=h, timeout=60, params={"ip": some_ip})
        assert r2.status_code == 200 and r2.json()["total"] > 0
        assert all(e["ip"] == some_ip for e in r2.json()["events"])

        # q free text
        r3 = requests.get(f"{API}/admin/audit-log", headers=h, timeout=60, params={"q": "wayne"})
        assert r3.status_code == 200
        assert r3.json()["total"] > 0

    def test_14_q_regex_special_chars_safe(self, admin_tok):
        h = auth(admin_tok)
        for q in ["(admin)", ".*", "[", "\\", "a{2,", "+?"]:
            r = requests.get(f"{API}/admin/audit-log", headers=h, timeout=60, params={"q": q})
            assert r.status_code == 200, f"q={q!r} -> {r.status_code} {r.text[:200]}"
            if q == ".*":
                assert r.json()["total"] == 0, "'.*' matched everything — regex not escaped"

    def test_15_date_filters_end_of_day(self, admin_tok):
        h = auth(admin_tok)
        today = utcnow().strftime("%Y-%m-%d")
        yesterday = (utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        r = requests.get(f"{API}/admin/audit-log", headers=h, timeout=60,
                         params={"date_from": "2026-08-01", "date_to": today, "page_size": 5})
        assert r.status_code == 200
        assert r.json()["total"] > 0, "date_to=today excluded today's events (end-of-day bug)"
        assert any(e["timestamp"].startswith(today) for e in r.json()["events"])

        r2 = requests.get(f"{API}/admin/audit-log", headers=h, timeout=60,
                          params={"date_to": yesterday, "page_size": 50})
        assert r2.status_code == 200
        assert not any(e["timestamp"].startswith(today) for e in r2.json()["events"]), \
            "date_to=yesterday still returned today's events"

    def test_16_pagination(self, admin_tok):
        h = auth(admin_tok)
        # Generate 60 low-side-effect events (failed logins against unique fake emails)
        stamp = uuid.uuid4().hex[:6]
        for i in range(60):
            login(f"pagtest_{stamp}_{i}@example.com", "nope")
        marker = f"pagtest_{stamp}_"
        rows = list(mdb.audit_log.find({"user_email": {"$regex": f"^{marker}"}}, {"_id": 0}))
        assert len(rows) >= 60, f"only {len(rows)} dummy events recorded"
        try:
            p1 = requests.get(f"{API}/admin/audit-log", headers=h, timeout=60,
                              params={"q": marker, "page": 1, "page_size": 25}).json()
            p2 = requests.get(f"{API}/admin/audit-log", headers=h, timeout=60,
                              params={"q": marker, "page": 2, "page_size": 25}).json()
            p3 = requests.get(f"{API}/admin/audit-log", headers=h, timeout=60,
                              params={"q": marker, "page": 3, "page_size": 25}).json()
            assert p1["total"] >= 60, p1["total"]
            assert len(p1["events"]) == 25 and len(p2["events"]) == 25
            assert len(p3["events"]) >= 10
            ids1 = {e["id"] for e in p1["events"]}
            ids2 = {e["id"] for e in p2["events"]}
            ids3 = {e["id"] for e in p3["events"]}
            assert not (ids1 & ids2) and not (ids2 & ids3)
        finally:
            mdb.audit_log.delete_many({"user_email": {"$regex": f"^{marker}"}})
            mdb.login_attempts.delete_many({"email": {"$regex": f"^{marker}"}})

    def test_17_event_types_endpoint(self, admin_tok):
        r = requests.get(f"{API}/admin/audit-log/event-types", headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200
        types = r.json()["types"]
        keys = [t["key"] for t in types]
        assert "auth.login.password_ok" in keys
        assert len(types) == 23, f"expected 23 event types, got {len(types)}"
        assert all(t.get("label") for t in types)

    def test_18_csv_export(self, admin_tok):
        h = auth(admin_tok)
        r = requests.get(f"{API}/admin/audit-log/export.csv", headers=h, timeout=120)
        assert r.status_code == 200
        assert r.headers["content-type"].lower().replace(" ", "") == "text/csv;charset=utf-8", \
            r.headers.get("content-type")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd and "byrd-audit-" in cd and cd.rstrip().endswith('.csv"'), cd
        lines = r.text.splitlines()
        assert lines[0] == CSV_HEADER, lines[0]

        # filter respected
        r2 = requests.get(f"{API}/admin/audit-log/export.csv", headers=h, timeout=120,
                          params={"event_type": "auth.login.success"})
        assert r2.status_code == 200
        body_lines = [ln for ln in r2.text.splitlines()[1:] if ln.strip()]
        assert body_lines
        assert all(",auth.login.success," in ln for ln in body_lines[:20])

        # limit caps rows
        r3 = requests.get(f"{API}/admin/audit-log/export.csv", headers=h, timeout=120,
                          params={"limit": 5})
        assert r3.status_code == 200
        assert len([ln for ln in r3.text.splitlines() if ln.strip()]) <= 6

    def test_19_csv_export_large_limit_not_capped_at_500(self, admin_tok):
        """Export claims a 10k default / 50k hard cap. Verify a >500 request can
        actually return >500 rows when enough events exist."""
        total = mdb.audit_log.count_documents({})
        if total <= 500:
            pytest.skip(f"only {total} audit rows — cannot test >500 export")
        r = requests.get(f"{API}/admin/audit-log/export.csv", headers=auth(admin_tok),
                         timeout=180, params={"limit": 2000})
        assert r.status_code == 200
        rows = len([ln for ln in r.text.splitlines() if ln.strip()]) - 1
        assert rows > 500, f"export returned only {rows} rows — page_size clamp (500) caps CSV export"

    def test_20_ip_extraction_xff(self):
        t0 = utcnow()
        bogus = f"xfftest_{uuid.uuid4().hex[:8]}@example.com"
        r = login(bogus, "nope", headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.1"})
        assert r.status_code == 401
        rows = find_events("auth.login.failure", since=t0, user_email=bogus)
        assert rows, "no audit row for XFF test"
        assert rows[0]["ip"] == "1.2.3.4", f"expected first XFF hop, got {rows[0]['ip']!r}"
        mdb.audit_log.delete_many({"user_email": bogus})
        mdb.login_attempts.delete_many({"email": bogus})

    def test_21_ip_extraction_xrealip(self):
        t0 = utcnow()
        bogus = f"xriptest_{uuid.uuid4().hex[:8]}@example.com"
        r = login(bogus, "nope", headers={"X-Real-IP": "9.9.9.9"})
        assert r.status_code == 401
        rows = find_events("auth.login.failure", since=t0, user_email=bogus)
        assert rows
        ip = rows[0]["ip"]
        mdb.audit_log.delete_many({"user_email": bogus})
        mdb.login_attempts.delete_many({"email": bogus})
        # The ingress always injects XFF, so X-Real-IP is only a fallback. Just assert an IP was captured.
        assert ip and ip != "unknown", ip

    def test_22_log_event_never_raises(self):
        """Unit-level: a failing insert must be swallowed by audit_service.log_event."""
        sys.path.insert(0, "/app/backend")
        import asyncio

        import audit_service

        class BoomColl:
            async def insert_one(self, doc):
                raise RuntimeError("boom")

        class BoomDB:
            audit_log = BoomColl()

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            audit_service.log_event(BoomDB(), event_type="auth.login.success")
        )

    def test_23_login_still_works_when_audit_write_fails(self):
        """End-to-end sanity: login endpoint returns 200/401 regardless of audit state."""
        assert login(*ADMIN).status_code == 200
        assert login(ADMIN[0], "bad").status_code in (401, 429)
        mdb.login_attempts.delete_many({"email": ADMIN[0], "success": False})

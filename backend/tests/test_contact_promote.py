"""Byrd & CO — Contact → Client promotion tests.

Covers:
  * happy-path: contact with email + name gets promoted, invite token returned,
    contact stamped with client_user_id + promoted_at
  * NO invite email is sent on promote (broker sends it manually later)
  * rejects contact without an email (400)
  * rejects if an active user already exists with that email (400)
  * rejects double-promotion of the same contact (400)
  * allows re-promoting a contact whose linked client user was deleted
  * RBAC — non-admin gets 403; unauth 401
  * 404 for missing contact id
  * audit event `admin.invite.sent` fires with reason=promote_from_contact
"""
import os
import time
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

mongo = MongoClient(be["MONGO_URL"])
mdb = mongo[be["DB_NAME"]]

TAG = f"TEST_promote_{os.getpid()}_"


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


@pytest.fixture(scope="module")
def client_tok():
    return token_for(*CLIENT)


def _make_contact(admin_tok, email=None, name=None, phone=None):
    body = {
        "name": name or f"{TAG}Contact {uuid.uuid4().hex[:6]}",
        "email": email if email is not None else f"{TAG.lower()}{uuid.uuid4().hex[:8]}@example.com",
        "phone": phone or "555-0100",
        "contact_type": ["email"],
        # Tag with the worker-unique TAG so cleanup only targets this worker's rows.
        "tags": [TAG, "promote-suite"],
    }
    if body["email"] is None:
        body.pop("email")
    r = requests.post(f"{API}/admin/contacts", json=body, headers=auth(admin_tok), timeout=60)
    assert r.status_code == 200, f"create contact: {r.status_code} {r.text[:200]}"
    return r.json()


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    """Purge only THIS worker's promoted users + contacts (worker-unique TAG so parallel
    xdist workers don't nuke each other's in-flight data)."""
    yield
    for c in list(mdb.contacts.find({"tags": TAG}, {"_id": 0, "id": 1, "client_user_id": 1})):
        uid = c.get("client_user_id")
        if uid:
            mdb.invites.delete_many({"user_id": uid})
            mdb.users.delete_one({"id": uid})
    mdb.contacts.delete_many({"tags": TAG})
    mdb.users.delete_many({"email": {"$regex": f"^{TAG.lower()}"}})


def _wait_audit(user_id, reason, wait=6.0):
    deadline = time.time() + wait
    while time.time() < deadline:
        ev = mdb.audit_log.find_one({
            "event_type": "admin.invite.sent",
            "resource_id": user_id,
            "metadata.reason": reason,
        }, {"_id": 0}, sort=[("timestamp", -1)])
        if ev:
            return ev
        time.sleep(0.4)
    return None


# ---------------- Happy path ----------------

class TestHappyPath:
    def test_promote_creates_pending_client_with_invite_token(self, admin_tok):
        c = _make_contact(admin_tok, name=f"{TAG}Alice")
        r = requests.post(f"{API}/admin/contacts/{c['id']}/promote-to-client",
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["token"] and len(body["token"]) >= 32
        assert body["invite_url_path"].startswith("/portal/invite/")
        assert body["user"]["email"] == c["email"].lower()
        assert body["user"]["name"].startswith(TAG)

        uid = body["user"]["id"]

        # user row: role=client, pending=True, no password, linked back to contact
        user = mdb.users.find_one({"id": uid}, {"_id": 0})
        assert user["role"] == "client"
        assert user["pending"] is True
        assert user.get("password_hash") in (None,)
        assert user.get("promoted_from_contact_id") == c["id"]

        # contact row now stamped
        contact = mdb.contacts.find_one({"id": c["id"]}, {"_id": 0})
        assert contact["client_user_id"] == uid
        assert contact.get("promoted_at")

        # unused invite exists
        inv = mdb.invites.find_one({"user_id": uid, "used_at": None})
        assert inv and inv["token"] == body["token"]

        # audit event
        assert _wait_audit(uid, "promote_from_contact"), "missing audit event"

    def test_promoted_client_shows_up_in_admin_clients_list(self, admin_tok):
        c = _make_contact(admin_tok, name=f"{TAG}Bob")
        r = requests.post(f"{API}/admin/contacts/{c['id']}/promote-to-client",
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200
        uid = r.json()["user"]["id"]

        lr = requests.get(f"{API}/admin/clients", headers=auth(admin_tok), timeout=60)
        assert lr.status_code == 200
        assert uid in [x["id"] for x in lr.json()], "promoted client not in /admin/clients"


# ---------------- Guardrails ----------------

class TestGuardrails:
    def test_rejects_contact_without_email(self, admin_tok):
        # Create a contact WITHOUT email — the ContactCreate model allows null
        body = {"name": f"{TAG}NoEmail", "phone": "555-0000",
                "contact_type": ["phone"], "tags": [TAG, "promote-suite"]}
        r = requests.post(f"{API}/admin/contacts", json=body,
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200
        cid = r.json()["id"]

        p = requests.post(f"{API}/admin/contacts/{cid}/promote-to-client",
                          headers=auth(admin_tok), timeout=60)
        assert p.status_code == 400
        assert "email" in p.json()["detail"].lower()

    def test_rejects_existing_user_email_conflict(self, admin_tok):
        # borrow the sample client's email → any promote attempt must 400
        c = _make_contact(admin_tok, email="sample@example.com", name=f"{TAG}Conflict")
        p = requests.post(f"{API}/admin/contacts/{c['id']}/promote-to-client",
                          headers=auth(admin_tok), timeout=60)
        assert p.status_code == 400
        assert "already exists" in p.json()["detail"].lower()

    def test_rejects_double_promotion(self, admin_tok):
        c = _make_contact(admin_tok, name=f"{TAG}Double")
        r1 = requests.post(f"{API}/admin/contacts/{c['id']}/promote-to-client",
                           headers=auth(admin_tok), timeout=60)
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/admin/contacts/{c['id']}/promote-to-client",
                           headers=auth(admin_tok), timeout=60)
        assert r2.status_code == 400
        assert "already linked" in r2.json()["detail"].lower()

    def test_re_promote_after_client_user_deleted(self, admin_tok):
        """If the linked client was later deleted, admin should be able to re-promote
        the contact and get a fresh invite."""
        c = _make_contact(admin_tok, name=f"{TAG}Rescue")
        r1 = requests.post(f"{API}/admin/contacts/{c['id']}/promote-to-client",
                           headers=auth(admin_tok), timeout=60)
        uid_old = r1.json()["user"]["id"]
        # simulate deletion
        mdb.users.delete_one({"id": uid_old})
        r2 = requests.post(f"{API}/admin/contacts/{c['id']}/promote-to-client",
                           headers=auth(admin_tok), timeout=60)
        assert r2.status_code == 200, r2.text[:200]
        uid_new = r2.json()["user"]["id"]
        assert uid_new != uid_old
        contact = mdb.contacts.find_one({"id": c["id"]}, {"_id": 0})
        assert contact["client_user_id"] == uid_new

    def test_404_on_unknown_contact(self, admin_tok):
        r = requests.post(f"{API}/admin/contacts/does-not-exist/promote-to-client",
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 404

    def test_does_not_send_invite_email_by_default(self, admin_tok):
        """The promote endpoint MUST NOT send an email — broker sends manually later."""
        c = _make_contact(admin_tok, name=f"{TAG}NoEmailSent")
        r = requests.post(f"{API}/admin/contacts/{c['id']}/promote-to-client",
                          headers=auth(admin_tok), timeout=60)
        assert r.status_code == 200
        uid = r.json()["user"]["id"]
        ev = _wait_audit(uid, "promote_from_contact")
        assert ev is not None
        # metadata explicitly records email_sent=False
        assert ev["metadata"]["email_sent"] is False


# ---------------- RBAC ----------------

class TestRbac:
    def test_client_role_cannot_promote(self, admin_tok, client_tok):
        c = _make_contact(admin_tok, name=f"{TAG}RbacClient")
        r = requests.post(f"{API}/admin/contacts/{c['id']}/promote-to-client",
                          headers=auth(client_tok), timeout=60)
        assert r.status_code == 403

    def test_unauth_rejected(self, admin_tok):
        c = _make_contact(admin_tok, name=f"{TAG}RbacAnon")
        r = requests.post(f"{API}/admin/contacts/{c['id']}/promote-to-client", timeout=60)
        assert r.status_code in (401, 403)

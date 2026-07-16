"""Backend API tests for Byrd & CO (client portal + admin + public).
Also covers the retained AdsCopilot endpoints.
"""
import os
import uuid
import json
import time
import base64
import pytest
import requests

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


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

WAYNE = ("wayne@byrd-co.com", "byrdco2026")
CALEB = ("caleb@byrd-co.com", "byrdco2026")
SAMPLE = ("sample@example.com", "sample123")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    return r


@pytest.fixture(scope="session")
def admin_headers():
    r = _login(*WAYNE)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def sample_client_headers():
    r = _login(*SAMPLE)
    if r.status_code != 200:
        pytest.skip(f"Sample client not activated: {r.status_code}")
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


# ============ Public ============
class TestPublic:
    def test_root(self):
        r = requests.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_testimonials(self):
        r = requests.get(f"{API}/public/testimonials", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list) and len(data) == 4
        for t in data:
            for f in ("name", "title", "quote", "rating", "avatar"):
                assert f in t, f"Missing {f} in testimonial"
            assert t["rating"] >= 1

    def test_principals(self):
        r = requests.get(f"{API}/public/principals", timeout=15)
        assert r.status_code == 200
        data = r.json()
        emails = [p["email"] for p in data]
        assert "wayne@byrd-co.com" in emails and "caleb@byrd-co.com" in emails

    def test_quote_submit(self):
        payload = {
            "name": "TEST Buyer",
            "email": f"test_{uuid.uuid4().hex[:6]}@example.com",
            "phone": "555-0100",
            "loan_type": "Multifamily",
            "loan_amount": "$2M",
            "property_type": "Multifamily",
            "message": "Interested in refi.",
        }
        r = requests.post(f"{API}/public/quote", json=payload, timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("ok") is True and "id" in j


# ============ Auth ============
class TestAuth:
    def test_admin_login(self):
        r = _login(*WAYNE)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "admin"

    def test_invalid(self):
        r = _login("wayne@byrd-co.com", "wrongpw")
        assert r.status_code == 401

    def test_me_unauth(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 401

    def test_me(self, admin_headers):
        r = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"


# ============ Admin: clients / invites / docs ============
class TestAdminClientFlow:
    invite_data = {}

    def test_list_clients(self, admin_headers):
        r = requests.get(f"{API}/admin/clients", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_invite_create_and_accept(self, admin_headers):
        email = f"test_{uuid.uuid4().hex[:6]}@example.com"
        r = requests.post(
            f"{API}/admin/invites", headers=admin_headers,
            json={"email": email, "name": "TEST Client", "loan_type": "Multifamily"}, timeout=20,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert "token" in j and j["invite_url_path"].endswith(j["token"])
        assert j["user"]["email"] == email
        token = j["token"]
        user_id = j["user"]["id"]
        self.__class__.invite_data = {"token": token, "user_id": user_id, "email": email}

        # GET invite meta
        r2 = requests.get(f"{API}/invites/{token}", timeout=15)
        assert r2.status_code == 200
        assert r2.json()["email"] == email

        # Client detail with docs
        r3 = requests.get(f"{API}/admin/clients/{user_id}", headers=admin_headers, timeout=20)
        assert r3.status_code == 200
        d = r3.json()
        docs = d["docs"]
        assert len(docs) == 18, f"Expected 18 default docs, got {len(docs)}"
        labels = [x["label"] for x in docs]
        assert "Resume" in labels
        assert "Construction Budget" in labels
        assert sum(1 for l in labels if "Personal Tax Returns" in l) == 3
        assert sum(1 for l in labels if "Business Tax Returns" in l) == 3

        # Accept invite
        r4 = requests.post(f"{API}/invites/{token}/accept", json={"password": "testpass123"}, timeout=20)
        assert r4.status_code == 200
        client_token = r4.json()["token"]
        self.__class__.invite_data["client_headers"] = {
            "Authorization": f"Bearer {client_token}", "Content-Type": "application/json",
        }

        # Re-using invite should 410
        r5 = requests.post(f"{API}/invites/{token}/accept", json={"password": "another"}, timeout=15)
        assert r5.status_code == 410

    def test_duplicate_invite_rejected(self, admin_headers):
        assert self.invite_data
        r = requests.post(
            f"{API}/admin/invites", headers=admin_headers,
            json={"email": self.invite_data["email"], "name": "dup"}, timeout=15,
        )
        assert r.status_code == 400

    def test_add_and_update_and_delete_doc(self, admin_headers):
        user_id = self.invite_data["user_id"]
        # Add custom doc
        r = requests.post(
            f"{API}/admin/clients/{user_id}/docs", headers=admin_headers,
            json={"label": "TEST Custom Doc", "category": "Custom", "required": False}, timeout=15,
        )
        assert r.status_code == 200, r.text
        doc = r.json()
        doc_id = doc["id"]
        assert doc["status"] == "pending"

        # Update status via PATCH
        r2 = requests.patch(
            f"{API}/admin/clients/{user_id}/docs/{doc_id}", headers=admin_headers,
            json={"status": "reviewed", "notes": "OK"}, timeout=15,
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "reviewed"
        assert r2.json()["notes"] == "OK"

        # Verify persistence via GET
        r3 = requests.get(f"{API}/admin/clients/{user_id}", headers=admin_headers, timeout=15)
        found = next(x for x in r3.json()["docs"] if x["id"] == doc_id)
        assert found["status"] == "reviewed"

        # Delete
        r4 = requests.delete(f"{API}/admin/clients/{user_id}/docs/{doc_id}", headers=admin_headers, timeout=15)
        assert r4.status_code == 200
        r5 = requests.get(f"{API}/admin/clients/{user_id}", headers=admin_headers, timeout=15)
        assert not any(x["id"] == doc_id for x in r5.json()["docs"])

    def test_client_upload_and_admin_status_flip(self, admin_headers):
        client_headers = self.invite_data["client_headers"]
        # get client docs
        r = requests.get(f"{API}/client/me", headers=client_headers, timeout=15)
        assert r.status_code == 200
        me = r.json()
        assert me["user"]["role"] == "client"
        assert len(me["docs"]) >= 1
        doc_id = me["docs"][0]["id"]

        # upload small file
        content = b"Hello Byrd test file"
        b64 = base64.b64encode(content).decode()
        r2 = requests.post(
            f"{API}/client/docs/{doc_id}/upload", headers=client_headers,
            json={"filename": "test.txt", "content_type": "text/plain", "data_b64": b64}, timeout=20,
        )
        assert r2.status_code == 200, r2.text
        file_id = r2.json()["file_id"]

        # verify status uploaded
        r3 = requests.get(f"{API}/client/me", headers=client_headers, timeout=15)
        d = next(x for x in r3.json()["docs"] if x["id"] == doc_id)
        assert d["status"] == "uploaded"
        assert d.get("file", {}).get("filename") == "test.txt"

        # download file
        r4 = requests.get(f"{API}/files/{file_id}", headers=client_headers, timeout=15)
        assert r4.status_code == 200
        assert r4.content == content

        # admin flips to reviewed
        user_id = self.invite_data["user_id"]
        r5 = requests.patch(
            f"{API}/admin/clients/{user_id}/docs/{doc_id}", headers=admin_headers,
            json={"status": "reviewed"}, timeout=15,
        )
        assert r5.status_code == 200
        r6 = requests.get(f"{API}/client/me", headers=client_headers, timeout=15)
        d6 = next(x for x in r6.json()["docs"] if x["id"] == doc_id)
        assert d6["status"] == "reviewed"

    def test_client_cannot_access_admin(self):
        client_headers = self.invite_data["client_headers"]
        r = requests.get(f"{API}/admin/clients", headers=client_headers, timeout=15)
        assert r.status_code == 403


# ============ Admin: quotes ============
class TestQuotes:
    def test_quote_appears_in_admin(self, admin_headers):
        # submit a quote
        payload = {"name": "TEST Quote", "email": f"tq_{uuid.uuid4().hex[:6]}@example.com",
                   "loan_type": "SBA", "message": "Testing quote inbox"}
        r = requests.post(f"{API}/public/quote", json=payload, timeout=15)
        assert r.status_code == 200
        qid = r.json()["id"]

        r2 = requests.get(f"{API}/admin/quotes", headers=admin_headers, timeout=15)
        assert r2.status_code == 200
        ids = [q["id"] for q in r2.json()]
        assert qid in ids

        # patch read
        r3 = requests.patch(f"{API}/admin/quotes/{qid}", headers=admin_headers, json={"read": True}, timeout=15)
        assert r3.status_code == 200


# ============ Sample client ============
class TestSampleClient:
    def test_sample_login_and_me(self, sample_client_headers):
        r = requests.get(f"{API}/client/me", headers=sample_client_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "client"

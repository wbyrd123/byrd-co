"""Byrd & CO — Lender apply/create form now carries two Y/N underwriting flags:

    * deposit_relationship_required
    * borrower_in_state_required

Both are Optional[bool] on the wire (None = unspecified). This test locks in
the round-trip for both entry paths (public apply + admin create) and confirms
the fields survive a PATCH.
"""
import os
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

mongo = MongoClient(be["MONGO_URL"])
mdb = mongo[be["DB_NAME"]]


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, r.text[:200]
    return r.json()["token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


class TestPublicApplyUnderwritingFlags:

    def test_apply_persists_yes_no_flags(self):
        email = f"deposit_test_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/public/lender/apply", timeout=60, json={
            "lender_name": "Deposit Y Test Bank",
            "institution_type": "bank",
            "contact_name": "Test Officer",
            "contact_email": email,
            "property_types": ["Multifamily"],
            "geography": ["TX"],
            "deposit_relationship_required": True,
            "borrower_in_state_required": False,
        })
        assert r.status_code == 200, r.text[:400]
        lid = r.json()["id"]
        try:
            row = mdb.lenders.find_one({"id": lid})
            assert row["deposit_relationship_required"] is True
            assert row["borrower_in_state_required"] is False
        finally:
            mdb.lenders.delete_one({"id": lid})

    def test_apply_accepts_null_when_unspecified(self):
        email = f"deposit_unspec_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/public/lender/apply", timeout=60, json={
            "lender_name": "Unspecified Bank",
            "institution_type": "bank",
            "contact_name": "T",
            "contact_email": email,
            "property_types": ["Office"],
            "geography": ["OH"],
        })
        assert r.status_code == 200, r.text[:400]
        lid = r.json()["id"]
        try:
            row = mdb.lenders.find_one({"id": lid})
            # Both stored as None when not sent
            assert row.get("deposit_relationship_required") is None
            assert row.get("borrower_in_state_required") is None
        finally:
            mdb.lenders.delete_one({"id": lid})


class TestAdminLenderUnderwritingFlags:

    def test_admin_create_and_patch(self, admin_tok):
        r = requests.post(f"{API}/admin/lenders", headers=auth(admin_tok), timeout=60, json={
            "name": "Admin Constraint Bank",
            "institution_type": "bank",
            "property_types": ["Retail"],
            "geography": ["AL"],
            "deposit_relationship_required": True,
            "borrower_in_state_required": True,
        })
        assert r.status_code == 200, r.text[:400]
        lid = r.json()["id"]
        assert r.json()["deposit_relationship_required"] is True
        assert r.json()["borrower_in_state_required"] is True
        try:
            # Now PATCH one flag off — LenderUpdate inherits from LenderCreate
            r2 = requests.patch(f"{API}/admin/lenders/{lid}", headers=auth(admin_tok), timeout=60,
                                json={"deposit_relationship_required": False})
            assert r2.status_code == 200, r2.text[:400]
            assert r2.json()["deposit_relationship_required"] is False
            # Other flag untouched
            assert r2.json()["borrower_in_state_required"] is True
        finally:
            requests.delete(f"{API}/admin/lenders/{lid}", headers=auth(admin_tok), timeout=30)

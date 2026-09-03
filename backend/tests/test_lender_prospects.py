"""Byrd & CO — Lender Prospects outreach engine tests.

Covers the pieces that don't require live Perplexity / Claude:
  * manual create + bulk CSV + dedupe (same institution + state = 400)
  * list + filter by state + status
  * stats aggregation
  * PATCH updates + status transitions
  * DELETE
  * suppression list (add, cascade to prospects, remove)
  * RBAC (non-admin 403)

Discovery / enrichment / draft endpoints hit external APIs; we do a light "endpoint
exists + rejects non-admin" check on them here, and defer the live call to a manual
smoke test once the user has warmed up Instantly.
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
CLIENT = ("sample@example.com", "sample123")

mongo = MongoClient(be["MONGO_URL"])
mdb = mongo[be["DB_NAME"]]

TAG = f"TEST_prospect_{os.getpid()}_"


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200
    return r.json()["token"]


def auth(t): return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


@pytest.fixture(scope="module")
def client_tok():
    return token_for(*CLIENT)


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    mdb.lender_prospects.delete_many({"institution_lc": {"$regex": f"^{TAG.lower()}"}})
    mdb.lender_outreach_suppressions.delete_many(
        {"email": {"$regex": f"^{TAG.lower()}"}})


class TestManualCrud:
    def test_create_dedupe_list(self, admin_tok):
        body = {"institution": f"{TAG}Test Regional Bank",
                "state": "TX", "hq_city": "Houston",
                "contact_email": f"{TAG.lower()}lo1@example.com"}
        r = requests.post(f"{API}/admin/marketplace/prospects",
                          json=body, headers=auth(admin_tok), timeout=30)
        assert r.status_code == 200, r.text[:200]
        j = r.json()
        assert j["state"] == "TX"
        assert j["status"] == "queued"     # has email -> queued
        assert j["contact_email"] == body["contact_email"]

        # dupe on same (institution, state) -> 400
        d = requests.post(f"{API}/admin/marketplace/prospects",
                          json=body, headers=auth(admin_tok), timeout=30)
        assert d.status_code == 400
        assert "already exists" in d.json()["detail"].lower()

        # different state OK
        body2 = {**body, "state": "LA"}
        r2 = requests.post(f"{API}/admin/marketplace/prospects",
                           json=body2, headers=auth(admin_tok), timeout=30)
        assert r2.status_code == 200
        assert r2.json()["state"] == "LA"

        # no email -> status stays sourced
        body3 = {"institution": f"{TAG}No Contact CU", "state": "TX"}
        r3 = requests.post(f"{API}/admin/marketplace/prospects",
                           json=body3, headers=auth(admin_tok), timeout=30)
        assert r3.status_code == 200
        assert r3.json()["status"] == "sourced"

        # list filter
        l = requests.get(f"{API}/admin/marketplace/prospects",
                         params={"state": "TX"},
                         headers=auth(admin_tok), timeout=30)
        states = {x["state"] for x in l.json() if x["institution"].startswith(TAG)}
        assert states == {"TX"}

        l2 = requests.get(f"{API}/admin/marketplace/prospects",
                          params={"status": "sourced"},
                          headers=auth(admin_tok), timeout=30)
        statuses = {x["status"] for x in l2.json() if x["institution"].startswith(TAG)}
        assert statuses == {"sourced"}

    def test_patch_and_delete(self, admin_tok):
        body = {"institution": f"{TAG}Patch Target", "state": "OK"}
        r = requests.post(f"{API}/admin/marketplace/prospects",
                          json=body, headers=auth(admin_tok), timeout=30)
        pid = r.json()["id"]
        # add email via PATCH
        p = requests.patch(f"{API}/admin/marketplace/prospects/{pid}",
                           json={"contact_email": f"{TAG.lower()}p@example.com",
                                  "contact_name": "Patchy Person",
                                  "status": "queued"},
                           headers=auth(admin_tok), timeout=30)
        assert p.status_code == 200
        assert p.json()["contact_email"] == f"{TAG.lower()}p@example.com"
        assert p.json()["status"] == "queued"

        # delete
        d = requests.delete(f"{API}/admin/marketplace/prospects/{pid}",
                            headers=auth(admin_tok), timeout=30)
        assert d.status_code == 200
        d2 = requests.delete(f"{API}/admin/marketplace/prospects/{pid}",
                             headers=auth(admin_tok), timeout=30)
        assert d2.status_code == 404


class TestBulk:
    def test_bulk_upload_dedupes_within_and_across_calls(self, admin_tok):
        rows = [
            {"institution": f"{TAG}Bulk A", "state": "TX",
             "contact_email": f"{TAG.lower()}bulka@example.com"},
            {"institution": f"{TAG}Bulk B", "state": "TX"},
            {"institution": f"{TAG}Bulk A", "state": "TX"},   # dupe in payload
        ]
        r = requests.post(f"{API}/admin/marketplace/prospects/bulk",
                          json={"rows": rows}, headers=auth(admin_tok), timeout=30)
        assert r.status_code == 200
        assert r.json()["added"] == 2
        assert r.json()["skipped_dupes"] == 1

        # second call — everything dupes
        r2 = requests.post(f"{API}/admin/marketplace/prospects/bulk",
                           json={"rows": rows}, headers=auth(admin_tok), timeout=30)
        assert r2.json()["added"] == 0
        assert r2.json()["skipped_dupes"] == 3


class TestStats:
    def test_stats_endpoint_returns_status_breakdown(self, admin_tok):
        r = requests.get(f"{API}/admin/marketplace/prospects/stats",
                         headers=auth(admin_tok), timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert "total" in j and "by_status" in j
        # created a few above — total must be >= those still not deleted
        assert j["total"] >= 3


class TestSuppression:
    def test_add_cascades_to_prospects(self, admin_tok):
        email = f"{TAG.lower()}suppress@example.com"
        # seed 2 prospects sharing this email in different states
        for st in ("TX", "GA"):
            requests.post(f"{API}/admin/marketplace/prospects",
                          json={"institution": f"{TAG}Suppr {st}", "state": st,
                                "contact_email": email},
                          headers=auth(admin_tok), timeout=30)

        # add to suppression list
        r = requests.post(f"{API}/admin/marketplace/suppressions",
                          json={"email": email, "reason": "unsubscribed",
                                "note": "user asked"},
                          headers=auth(admin_tok), timeout=30)
        assert r.status_code == 200
        # every matching prospect flipped to opted_out
        lst = requests.get(f"{API}/admin/marketplace/prospects",
                           headers=auth(admin_tok), timeout=30).json()
        matches = [x for x in lst if x.get("contact_email") == email]
        assert len(matches) >= 2
        assert all(x["status"] == "opted_out" for x in matches)

        # remove from suppression list — does NOT re-activate prospects
        d = requests.delete(f"{API}/admin/marketplace/suppressions/{email}",
                            headers=auth(admin_tok), timeout=30)
        assert d.status_code == 200

    def test_suppress_upsert_and_404_on_remove(self, admin_tok):
        email = f"{TAG.lower()}upsert@example.com"
        # first add
        r1 = requests.post(f"{API}/admin/marketplace/suppressions",
                           json={"email": email, "reason": "manual"},
                           headers=auth(admin_tok), timeout=30)
        assert r1.status_code == 200
        # second add — same email, different reason -> upserts (still 200)
        r2 = requests.post(f"{API}/admin/marketplace/suppressions",
                           json={"email": email, "reason": "bounced"},
                           headers=auth(admin_tok), timeout=30)
        assert r2.status_code == 200
        row = mdb.lender_outreach_suppressions.find_one({"email": email})
        assert row["reason"] == "bounced"

        # 404 on remove for unknown email
        r3 = requests.delete(f"{API}/admin/marketplace/suppressions/nobody-{TAG.lower()}@x.com",
                             headers=auth(admin_tok), timeout=30)
        assert r3.status_code == 404


class TestRbac:
    def test_client_cannot_hit_prospect_endpoints(self, client_tok):
        for method, path in [
            ("get", "/admin/marketplace/prospects"),
            ("post", "/admin/marketplace/prospects"),
            ("post", "/admin/marketplace/prospects/bulk"),
            ("post", "/admin/marketplace/prospects/discover"),
            ("get", "/admin/marketplace/suppressions"),
        ]:
            fn = getattr(requests, method)
            kwargs = {"headers": auth(client_tok), "timeout": 30}
            if method == "post":
                kwargs["json"] = {"institution": "X", "state": "TX",
                                  "rows": [], "email": "x@y.com"}
            r = fn(f"{API}{path}", **kwargs)
            assert r.status_code == 403, f"{method.upper()} {path} -> {r.status_code}"

    def test_unauth_rejected(self):
        r = requests.get(f"{API}/admin/marketplace/prospects", timeout=30)
        assert r.status_code in (401, 403)


class TestDraftApproveGuards:
    def test_draft_requires_email(self, admin_tok):
        r = requests.post(f"{API}/admin/marketplace/prospects",
                          json={"institution": f"{TAG}NeedsEmail",
                                "state": "AR"},
                          headers=auth(admin_tok), timeout=30)
        pid = r.json()["id"]
        d = requests.post(f"{API}/admin/marketplace/prospects/{pid}/draft",
                          json={}, headers=auth(admin_tok), timeout=30)
        assert d.status_code == 400
        assert "email" in d.json()["detail"].lower()

    def test_approve_requires_draft(self, admin_tok):
        r = requests.post(f"{API}/admin/marketplace/prospects",
                          json={"institution": f"{TAG}NeedsDraft", "state": "AR",
                                "contact_email": f"{TAG.lower()}nd@example.com"},
                          headers=auth(admin_tok), timeout=30)
        pid = r.json()["id"]
        a = requests.post(f"{API}/admin/marketplace/prospects/{pid}/approve",
                          headers=auth(admin_tok), timeout=30)
        assert a.status_code == 400
        assert "draft" in a.json()["detail"].lower()

    def test_approve_404_missing(self, admin_tok):
        r = requests.post(f"{API}/admin/marketplace/prospects/nope-id/approve",
                          headers=auth(admin_tok), timeout=30)
        assert r.status_code == 404

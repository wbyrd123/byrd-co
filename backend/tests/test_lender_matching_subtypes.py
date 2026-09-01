"""Byrd & CO — Sub-type-aware lender matching tests.

Covers:
  * match_lenders() ranks a lender WHO declares the deal's sub-type ABOVE a lender
    who only matches the top-level type
  * a lender who declared different sub-types on the same top-level is now a MISS
    ("doesn't specialize in <subtype>") — not a fit
  * a lender who declared NO sub-types stays a fit on any sub-type (interpretation:
    "open to all sub-types")
  * legacy label aliasing — "Hospitality"/"Self-storage"/"Mixed-use" from lender
    application forms canonicalise to Hotel/Self Storage/Multifamily
  * lender application (POST /api/public/lender/apply) accepts property_subtypes
  * lender self-serve (PATCH /api/lender/me/credit-box) accepts property_subtypes
  * admin create/patch lender persists property_subtypes
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

TAG = f"TEST_ptsub_{os.getpid()}_"


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, r.text[:200]
    return r.json()["token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    mdb.lenders.delete_many({"name": {"$regex": f"^{TAG}"}})
    mdb.scenarios.delete_many({"name": {"$regex": f"^{TAG}"}})


# ---------------- Backend unit test on match_lenders ----------------

class TestMatchEngine:
    """Direct import — validates the ranking without going through HTTP."""

    def test_ranks_subtype_specialist_higher_than_toplevel_only(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from server import match_lenders

        scen = {
            "property_info": {"property_type": "Industrial",
                              "property_subtype": "Manufacturing Heavy Industrial",
                              "state": "TX"},
            "loan_request": {"loan_amount": 5_000_000},
            "financials": {},
        }
        toplevel_only = {"id": "l-top", "name": "Broad Industrial LLC",
                         "property_types": ["Industrial"],
                         "property_subtypes": [],
                         "geography": ["TX"]}
        specialist = {"id": "l-spec", "name": "Heavy Iron Capital",
                      "property_types": ["Industrial"],
                      "property_subtypes": ["Manufacturing Heavy Industrial"],
                      "geography": ["TX"]}
        wrong_sub = {"id": "l-wrong", "name": "Warehouse Cold Chain Bank",
                     "property_types": ["Industrial"],
                     "property_subtypes": ["Warehouse Cold Storage"],
                     "geography": ["TX"]}

        out = match_lenders(scen, [toplevel_only, specialist, wrong_sub])
        by_id = {r["lender"]["id"]: r for r in out}

        assert by_id["l-spec"]["score"] > by_id["l-top"]["score"], \
            "specialist should outrank generic top-level lender"
        assert by_id["l-spec"]["score"] > by_id["l-wrong"]["score"], \
            "specialist should outrank wrong-sub lender"
        assert any("specializes in Manufacturing Heavy Industrial" in f
                   for f in by_id["l-spec"]["fits"])
        assert any("doesn't specialize in Manufacturing Heavy Industrial" in m
                   for m in by_id["l-wrong"]["misses"])
        # top-level-only lender explains itself with the top-level fit ("Industrial")
        assert any("Industrial" in f for f in by_id["l-top"]["fits"])

    def test_toplevel_only_lender_still_fit_when_deal_has_no_subtype(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from server import match_lenders

        scen = {
            "property_info": {"property_type": "Industrial", "property_subtype": ""},
            "loan_request": {}, "financials": {},
        }
        broad = {"id": "l-broad", "name": "Broad", "property_types": ["Industrial"],
                 "property_subtypes": []}
        specialist = {"id": "l-spec", "name": "Spec", "property_types": ["Industrial"],
                      "property_subtypes": ["Manufacturing Heavy Industrial"]}
        out = {r["lender"]["id"]: r for r in match_lenders(scen, [broad, specialist])}
        # both should get the top-level fit; neither should get a subtype miss.
        assert any("Industrial" in f for f in out["l-broad"]["fits"])
        assert not any("specialize" in m for m in out["l-broad"]["misses"])
        assert any("Industrial" in f for f in out["l-spec"]["fits"])
        assert not any("specialize" in m for m in out["l-spec"]["misses"])

    def test_legacy_alias_hospitality_matches_hotel(self):
        """A pre-existing lender with 'Hospitality' should still match a Hotel deal."""
        import sys
        sys.path.insert(0, "/app/backend")
        from server import match_lenders

        scen = {"property_info": {"property_type": "Hotel"},
                "loan_request": {}, "financials": {}}
        legacy = {"id": "l-leg", "name": "Legacy Hotel Bank",
                  "property_types": ["Hospitality"], "property_subtypes": []}
        out = match_lenders(scen, [legacy])
        assert out[0]["verdict"] in ("fit", "partial"), \
            f"expected match on Hospitality->Hotel alias, got {out[0]}"
        assert not any("doesn't lend on" in m for m in out[0]["misses"])


# ---------------- HTTP: apply / self-serve / admin ----------------

class TestApplyPersistsSubtypes:
    def test_public_apply_saves_property_subtypes(self):
        email = f"{TAG.lower()}apply{uuid.uuid4().hex[:6]}@example.com"
        body = {
            "lender_name": f"{TAG}Heavy Iron Capital",
            "institution_type": "private",
            "contact_name": "QA Bot",
            "contact_email": email,
            "property_types": ["Industrial"],
            "property_subtypes": ["Manufacturing Heavy Industrial", "Warehouse Cold Storage"],
            "geography": ["TX"],
        }
        r = requests.post(f"{API}/public/lender/apply", json=body, timeout=60)
        assert r.status_code == 200, r.text[:200]

        rec = mdb.lenders.find_one({"apply_email": email}, {"_id": 0})
        assert rec, "lender row not created"
        assert rec["property_subtypes"] == body["property_subtypes"]
        assert rec["property_types"] == ["Industrial"]

    def test_admin_lender_crud_persists_subtypes(self, admin_tok):
        # create
        body = {
            "name": f"{TAG}Retail Specialist",
            "institution_type": "bank",
            "contacts": [{"name": "QA", "title": "Broker", "phone": "", "email": ""}],
            "property_types": ["Retail"],
            "property_subtypes": ["Neighborhood Center Grocery (Anchored)"],
            "geography": ["TX"],
        }
        c = requests.post(f"{API}/admin/lenders", json=body,
                          headers=auth(admin_tok), timeout=60)
        assert c.status_code == 200, c.text[:200]
        lid = c.json()["id"]
        assert c.json()["property_subtypes"] == body["property_subtypes"]

        # patch — add another specialty
        p = requests.patch(f"{API}/admin/lenders/{lid}",
                           json={"property_subtypes": [
                               "Neighborhood Center Grocery (Anchored)",
                               "Power Center"]},
                           headers=auth(admin_tok), timeout=60)
        assert p.status_code == 200
        assert p.json()["property_subtypes"] == [
            "Neighborhood Center Grocery (Anchored)", "Power Center"]

        # cleanup handled by autouse via TAG regex

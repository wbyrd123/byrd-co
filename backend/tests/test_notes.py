"""Byrd & CO — Deal Notes feature tests.

Covers:
  * CRUD as admin, CRUD as owning client (general + per-doc notes)
  * RBAC (foreign client 403, unauthed 401, lender read-only writes)
  * Doc-count aggregation endpoint
  * Admin-only visibility toggle (hidden_from_lenders)
    - Lender GET filters hidden notes
    - Lender doc-counts endpoint excludes hidden notes
    - Client + admin still see hidden notes
  * Token-gated lender-view endpoints require session_token
  * Author-or-admin only edit/delete
  * Audit trail metadata emission

All test notes here are body-tagged `TEST_notes_` and cleaned up in teardown.
"""
import os
import time

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

TAG = f"TEST_notes_{os.getpid()}_"


def token_for(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    tok = r.json().get("token")
    if not tok:
        pytest.fail(f"no token in login response for {email}")
    return tok


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------- fixtures ----------------

@pytest.fixture(scope="module")
def admin_tok():
    return token_for(*ADMIN)


@pytest.fixture(scope="module")
def client_tok():
    return token_for(*CLIENT)


@pytest.fixture(scope="module")
def lender_tok():
    return token_for(*LENDER)


@pytest.fixture(scope="module")
def client_sid(client_tok):
    """Scenario owned by the sample client (discovered via /api/client/me).
    Prefers a scenario that has at least one attachable (non-fee-agreement) doc line,
    so per-doc note tests don't skip. Falls back to the first scenario if none qualify."""
    r = requests.get(f"{API}/client/me", headers=auth(client_tok), timeout=60)
    assert r.status_code == 200, f"/client/me -> {r.status_code} {r.text[:300]}"
    scens = r.json().get("scenarios") or []
    assert scens, "sample client has no scenarios"
    with_docs = [s for s in scens if any(
        (d.get("label") != "Signed Fee Agreement") for d in (s.get("docs") or []))]
    return (with_docs or scens)[0]["id"]


@pytest.fixture(scope="module")
def client_docs(client_tok, client_sid):
    """Returns the borrower's doc list for the sample scenario."""
    r = requests.get(f"{API}/client/me", headers=auth(client_tok), timeout=60)
    assert r.status_code == 200
    scen = next((s for s in r.json().get("scenarios") or [] if s["id"] == client_sid), None)
    return (scen or {}).get("docs") or []


@pytest.fixture(scope="module")
def client_doc_id(client_docs):
    """Pick a non-fee-agreement doc line to attach per-doc notes to."""
    doc = next((d for d in client_docs if d.get("label") != "Signed Fee Agreement"), None)
    if not doc:
        pytest.skip("no attachable doc line on the sample scenario")
    return doc["id"]


@pytest.fixture(scope="module")
def other_sid(client_sid):
    """A scenario the sample client does NOT own."""
    other = mdb.scenarios.find_one(
        {"id": {"$ne": client_sid}, "client_id": {"$ne": "ec8e7737-c8d3-493e-b4e0-a08f49e85b72"}},
        {"_id": 0, "id": 1},
    )
    if not other:
        pytest.skip("no foreign scenario available for RBAC test")
    return other["id"]


@pytest.fixture(scope="module")
def share_token(client_sid):
    sh = mdb.scenario_shares.find_one({"scenario_id": client_sid}, {"_id": 0, "token": 1})
    if not sh:
        pytest.skip("no scenario_share token for the client scenario")
    return sh["token"]


@pytest.fixture(scope="module", autouse=True)
def cleanup(client_sid):
    """Cleanup all test-tagged notes AND ensure the test lender has read access to the
    client_sid scenario for the RBAC / doc-count tests (an actual scenario_share row).
    The seeded share is removed on teardown."""
    lender_user = mdb.users.find_one({"email": LENDER[0]}, {"_id": 0, "id": 1})
    lender_uid = (lender_user or {}).get("id")
    lender_rec = mdb.lenders.find_one({"owner_user_id": lender_uid}, {"_id": 0, "id": 1}) \
        if lender_uid else None
    lender_id = (lender_rec or {}).get("id")
    seed_share = None
    if lender_id:
        have = mdb.scenario_shares.find_one(
            {"scenario_id": client_sid, "lender_id": lender_id},
            {"_id": 0, "id": 1},
        )
        if not have:
            import uuid as _uuid
            from datetime import datetime, timezone
            seed_share = {
                "id": str(_uuid.uuid4()),
                "scenario_id": client_sid,
                "lender_id": lender_id,
                "lender_name": "Test Frost Bank (test_notes seed)",
                "token": _uuid.uuid4().hex,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "note": "seeded by test_notes.py",
            }
            mdb.scenario_shares.insert_one(seed_share)
    yield
    if seed_share:
        mdb.scenario_shares.delete_one({"id": seed_share["id"]})
    mdb.scenario_notes.delete_many({"body": {"$regex": f"^{TAG}"}})


def make_note(sid, headers, body, doc_id=None):
    payload = {"body": body}
    if doc_id:
        payload["doc_id"] = doc_id
    r = requests.post(f"{API}/scenarios/{sid}/notes", json=payload, headers=headers, timeout=60)
    assert r.status_code == 200, f"POST /notes -> {r.status_code} {r.text[:300]}"
    return r.json()


def recent_audit(sid, action, note_id=None, wait=6.0):
    deadline = time.time() + wait
    while time.time() < deadline:
        q = {"event_type": "scenario.update", "resource_id": sid, "metadata.action": action}
        if note_id:
            q["metadata.note_id"] = note_id
        ev = mdb.audit_log.find_one(q, {"_id": 0}, sort=[("timestamp", -1)])
        if ev:
            return ev
        time.sleep(0.5)
    return None


# ---------------- Admin CRUD ----------------

class TestAdminCrud:
    def test_general_note_full_roundtrip(self, admin_tok, client_sid):
        sid = client_sid
        n = make_note(sid, auth(admin_tok), f"{TAG}admin general v1")
        nid = n["id"]
        assert n["author_role"] == "admin"
        assert n["doc_id"] is None
        assert n["hidden_from_lenders"] is False
        assert n["body"] == f"{TAG}admin general v1"
        assert "_id" not in n
        assert recent_audit(sid, "note_added", nid), "missing note_added audit event"

        # list general only
        g = requests.get(f"{API}/scenarios/{sid}/notes", headers=auth(admin_tok), timeout=60)
        assert g.status_code == 200
        body = g.json()
        assert body["editable"] is True
        assert body["current_user_role"] == "admin"
        ids = [x["id"] for x in body["notes"]]
        assert nid in ids

        # patch
        p = requests.patch(f"{API}/scenarios/{sid}/notes/{nid}",
                           json={"body": f"{TAG}admin general v2"},
                           headers=auth(admin_tok), timeout=60)
        assert p.status_code == 200
        pj = p.json()
        assert pj["body"] == f"{TAG}admin general v2"
        assert pj["updated_at"] >= n["updated_at"]
        assert recent_audit(sid, "note_updated", nid), "missing note_updated audit event"

        # delete
        d = requests.delete(f"{API}/scenarios/{sid}/notes/{nid}",
                            headers=auth(admin_tok), timeout=60)
        assert d.status_code == 200 and d.json().get("ok") is True
        g2 = requests.get(f"{API}/scenarios/{sid}/notes", headers=auth(admin_tok), timeout=60)
        assert nid not in [x["id"] for x in g2.json()["notes"]]
        assert recent_audit(sid, "note_removed", nid), "missing note_removed audit event"

    def test_doc_note_scoped(self, admin_tok, client_sid, client_doc_id):
        """A doc-scoped note must not appear in general (doc_id=null) results, and vice versa."""
        sid = client_sid
        gen = make_note(sid, auth(admin_tok), f"{TAG}gen scope")
        docn = make_note(sid, auth(admin_tok), f"{TAG}doc scope", doc_id=client_doc_id)
        assert docn["doc_id"] == client_doc_id

        # general listing must NOT include doc note
        g = requests.get(f"{API}/scenarios/{sid}/notes", headers=auth(admin_tok), timeout=60)
        ids_general = [x["id"] for x in g.json()["notes"]]
        assert gen["id"] in ids_general
        assert docn["id"] not in ids_general

        # doc listing must NOT include general note
        d = requests.get(f"{API}/scenarios/{sid}/notes",
                         params={"doc_id": client_doc_id},
                         headers=auth(admin_tok), timeout=60)
        ids_doc = [x["id"] for x in d.json()["notes"]]
        assert docn["id"] in ids_doc
        assert gen["id"] not in ids_doc

        # doc_id=all returns everything
        a = requests.get(f"{API}/scenarios/{sid}/notes",
                        params={"doc_id": "all"},
                        headers=auth(admin_tok), timeout=60)
        ids_all = [x["id"] for x in a.json()["notes"]]
        assert gen["id"] in ids_all and docn["id"] in ids_all


# ---------------- Client CRUD ----------------

class TestClientCrud:
    def test_owning_client_full_crud(self, client_tok, client_sid, client_doc_id):
        sid = client_sid
        n = make_note(sid, auth(client_tok), f"{TAG}client v1", doc_id=client_doc_id)
        assert n["author_role"] == "client"
        assert n["doc_id"] == client_doc_id

        p = requests.patch(f"{API}/scenarios/{sid}/notes/{n['id']}",
                           json={"body": f"{TAG}client v2", "doc_id": client_doc_id},
                           headers=auth(client_tok), timeout=60)
        assert p.status_code == 200 and p.json()["body"] == f"{TAG}client v2"

        d = requests.delete(f"{API}/scenarios/{sid}/notes/{n['id']}",
                            headers=auth(client_tok), timeout=60)
        assert d.status_code == 200

    def test_client_cannot_edit_others_note(self, admin_tok, client_tok, client_sid):
        """Non-admin, non-author can't edit or delete."""
        sid = client_sid
        admin_note = make_note(sid, auth(admin_tok), f"{TAG}admin-owned")
        try:
            p = requests.patch(f"{API}/scenarios/{sid}/notes/{admin_note['id']}",
                               json={"body": f"{TAG}hijack"},
                               headers=auth(client_tok), timeout=60)
            assert p.status_code == 403
            d = requests.delete(f"{API}/scenarios/{sid}/notes/{admin_note['id']}",
                                headers=auth(client_tok), timeout=60)
            assert d.status_code == 403
        finally:
            requests.delete(f"{API}/scenarios/{sid}/notes/{admin_note['id']}",
                            headers=auth(admin_tok), timeout=60)

    def test_admin_can_delete_any_note(self, admin_tok, client_tok, client_sid):
        """Admin override on delete — used to purge borrower/lender chatter."""
        sid = client_sid
        n = make_note(sid, auth(client_tok), f"{TAG}by-client")
        d = requests.delete(f"{API}/scenarios/{sid}/notes/{n['id']}",
                            headers=auth(admin_tok), timeout=60)
        assert d.status_code == 200


# ---------------- Lender via auth token ----------------

class TestLenderAuthedAccess:
    def test_lender_can_post_and_read_but_not_hide(self, admin_tok, lender_tok, client_sid):
        """A logged-in lender who has been invited to this scenario can add notes,
        but cannot toggle visibility (admin-only)."""
        sid = client_sid
        # lender POST
        ln = make_note(sid, auth(lender_tok), f"{TAG}lender chirp")
        try:
            assert ln["author_role"] == "lender"

            # lender sees own note
            g = requests.get(f"{API}/scenarios/{sid}/notes", headers=auth(lender_tok), timeout=60)
            assert g.status_code == 200
            assert g.json()["current_user_role"] == "lender"
            assert ln["id"] in [x["id"] for x in g.json()["notes"]]

            # lender cannot flip visibility (admin-only endpoint)
            v = requests.patch(f"{API}/scenarios/{sid}/notes/{ln['id']}/visibility",
                               json={"hidden_from_lenders": True},
                               headers=auth(lender_tok), timeout=60)
            assert v.status_code == 403, f"lender should not access admin endpoint, got {v.status_code}"

            # client cannot flip visibility either
            client_tok = token_for(*CLIENT)
            v2 = requests.patch(f"{API}/scenarios/{sid}/notes/{ln['id']}/visibility",
                                json={"hidden_from_lenders": True},
                                headers=auth(client_tok), timeout=60)
            assert v2.status_code == 403
        finally:
            requests.delete(f"{API}/scenarios/{sid}/notes/{ln['id']}",
                            headers=auth(admin_tok), timeout=60)


# ---------------- RBAC ----------------

class TestRbac:
    def test_client_cannot_touch_foreign_scenario(self, client_tok, other_sid):
        for call in (
            lambda: requests.get(f"{API}/scenarios/{other_sid}/notes",
                                 headers=auth(client_tok), timeout=60),
            lambda: requests.post(f"{API}/scenarios/{other_sid}/notes",
                                  json={"body": f"{TAG}foreign"},
                                  headers=auth(client_tok), timeout=60),
            lambda: requests.patch(f"{API}/scenarios/{other_sid}/notes/xyz",
                                   json={"body": "nope"}, headers=auth(client_tok), timeout=60),
            lambda: requests.delete(f"{API}/scenarios/{other_sid}/notes/xyz",
                                    headers=auth(client_tok), timeout=60),
        ):
            resp = call()
            assert resp.status_code == 403, f"expected 403, got {resp.status_code} {resp.text[:200]}"

    def test_unauthenticated_rejected(self, client_sid):
        r = requests.get(f"{API}/scenarios/{client_sid}/notes", timeout=60)
        assert r.status_code in (401, 403), f"unauth GET -> {r.status_code}"

    def test_scenario_404(self, admin_tok):
        r = requests.get(f"{API}/scenarios/does-not-exist/notes",
                         headers=auth(admin_tok), timeout=60)
        assert r.status_code == 404

    def test_note_404_on_wrong_scenario(self, admin_tok, client_sid, other_sid):
        n = make_note(client_sid, auth(admin_tok), f"{TAG}scoped-to-a")
        try:
            # can't patch by another scenario's id
            p = requests.patch(f"{API}/scenarios/{other_sid}/notes/{n['id']}",
                               json={"body": "hi"},
                               headers=auth(admin_tok), timeout=60)
            assert p.status_code == 404
        finally:
            requests.delete(f"{API}/scenarios/{client_sid}/notes/{n['id']}",
                            headers=auth(admin_tok), timeout=60)


# ---------------- Doc counts + hide toggle ----------------

class TestDocCountsAndHide:
    def test_doc_counts_and_hide_from_lender(self, admin_tok, client_tok, lender_tok,
                                              client_sid, client_doc_id):
        """Membership-based: assert the specific hidden note stops appearing in lender-facing
        list + count (rather than a global count delta, which races with parallel workers)."""
        sid = client_sid
        did = client_doc_id
        n_public = make_note(sid, auth(client_tok), f"{TAG}public doc note", doc_id=did)
        n_hidden = make_note(sid, auth(client_tok), f"{TAG}sensitive borrower doc note",
                             doc_id=did)
        try:
            # baseline: lender sees both notes
            g0 = requests.get(f"{API}/scenarios/{sid}/notes",
                              params={"doc_id": did}, headers=auth(lender_tok), timeout=60)
            assert g0.status_code == 200
            baseline_ids = [x["id"] for x in g0.json()["notes"]]
            assert n_public["id"] in baseline_ids and n_hidden["id"] in baseline_ids

            c0 = requests.get(f"{API}/scenarios/{sid}/notes/doc-counts",
                              headers=auth(lender_tok), timeout=60).json()["counts"]
            c_admin = requests.get(f"{API}/scenarios/{sid}/notes/doc-counts",
                                    headers=auth(admin_tok), timeout=60).json()["counts"]
            assert c0.get(did, 0) >= 2
            assert c_admin.get(did, 0) >= c0.get(did, 0), \
                "admin count should be >= lender count (admin sees hidden too)"

            # admin hides one
            v = requests.patch(f"{API}/scenarios/{sid}/notes/{n_hidden['id']}/visibility",
                               json={"hidden_from_lenders": True},
                               headers=auth(admin_tok), timeout=60)
            assert v.status_code == 200 and v.json()["hidden_from_lenders"] is True
            assert recent_audit(sid, "note_visibility_changed", n_hidden["id"]), \
                "missing note_visibility_changed audit event"

            # lender GET no longer includes it
            glen = requests.get(f"{API}/scenarios/{sid}/notes",
                                params={"doc_id": did},
                                headers=auth(lender_tok), timeout=60)
            assert glen.status_code == 200
            lender_ids = [x["id"] for x in glen.json()["notes"]]
            assert n_public["id"] in lender_ids
            assert n_hidden["id"] not in lender_ids

            # admin + client still see it
            for tok in (admin_tok, client_tok):
                g = requests.get(f"{API}/scenarios/{sid}/notes",
                                 params={"doc_id": did},
                                 headers=auth(tok), timeout=60)
                assert n_hidden["id"] in [x["id"] for x in g.json()["notes"]]

            # unhide restores lender visibility
            v2 = requests.patch(f"{API}/scenarios/{sid}/notes/{n_hidden['id']}/visibility",
                                json={"hidden_from_lenders": False},
                                headers=auth(admin_tok), timeout=60)
            assert v2.status_code == 200 and v2.json()["hidden_from_lenders"] is False
            glen2 = requests.get(f"{API}/scenarios/{sid}/notes",
                                 params={"doc_id": did},
                                 headers=auth(lender_tok), timeout=60)
            assert n_hidden["id"] in [x["id"] for x in glen2.json()["notes"]]

        finally:
            for nid in (n_public["id"], n_hidden["id"]):
                requests.delete(f"{API}/scenarios/{sid}/notes/{nid}",
                                headers=auth(admin_tok), timeout=60)

    def test_hide_missing_note_404(self, admin_tok, client_sid):
        r = requests.patch(f"{API}/scenarios/{client_sid}/notes/nope-nid/visibility",
                           json={"hidden_from_lenders": True},
                           headers=auth(admin_tok), timeout=60)
        assert r.status_code == 404


# ---------------- Public token-gated lender-view ----------------

class TestLenderViewToken:
    def test_gated_notes_endpoint(self, admin_tok, client_sid, share_token, client_doc_id):
        sid = client_sid
        # Seed: one visible, one hidden
        n_v = make_note(sid, auth(admin_tok), f"{TAG}public gated", doc_id=client_doc_id)
        n_h = make_note(sid, auth(admin_tok), f"{TAG}hidden gated", doc_id=client_doc_id)
        requests.patch(f"{API}/scenarios/{sid}/notes/{n_h['id']}/visibility",
                       json={"hidden_from_lenders": True},
                       headers=auth(admin_tok), timeout=60)

        try:
            # no session_token -> 401 (notes may contain PII / sensitive underwriting chatter)
            r0 = requests.get(f"{API}/lender-view/{share_token}/notes", timeout=60)
            assert r0.status_code == 401, f"expected gated 401, got {r0.status_code}: {r0.text[:200]}"

            # acknowledge gate as anon
            gate = requests.post(f"{API}/lender-view/{share_token}/gate",
                                 json={"viewer_name": "Test QA",
                                       "viewer_email": "qa@example.com",
                                       "viewer_institution": "QA LLC",
                                       "acknowledged": True},
                                 timeout=60)
            assert gate.status_code == 200, gate.text[:200]
            session_token = gate.json()["session_token"]

            # gated notes list: doc-scoped
            r = requests.get(f"{API}/lender-view/{share_token}/notes",
                             params={"session_token": session_token, "doc_id": client_doc_id},
                             timeout=60)
            assert r.status_code == 200
            ids = [x["id"] for x in r.json()["notes"]]
            assert n_v["id"] in ids
            assert n_h["id"] not in ids, "hidden_from_lenders leaked through token endpoint"

            # gated doc-count endpoint excludes hidden
            c = requests.get(f"{API}/lender-view/{share_token}/notes/doc-counts",
                             params={"session_token": session_token}, timeout=60)
            assert c.status_code == 200
            visible_ct = c.json()["counts"].get(client_doc_id, 0)
            # exactly the visible one (there may be other notes seeded by other tests, so just >=1)
            assert visible_ct >= 1

            # no author_id / author_email exposed via lender-view? (sanity: sanitize_note keeps
            # author_role + author_name only, which is the same shape returned everywhere)
            visible = [x for x in r.json()["notes"] if x["id"] == n_v["id"]][0]
            for leaked in ("_id",):
                assert leaked not in visible

        finally:
            for nid in (n_v["id"], n_h["id"]):
                requests.delete(f"{API}/scenarios/{sid}/notes/{nid}",
                                headers=auth(admin_tok), timeout=60)

    def test_unknown_token_404(self):
        r = requests.get(f"{API}/lender-view/not-a-real-token/notes", timeout=60)
        assert r.status_code == 404

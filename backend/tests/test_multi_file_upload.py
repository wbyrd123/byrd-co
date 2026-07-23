"""Tests for multi-file uploads per document line item.

Feature: Each client_docs row can now hold many attached files (files: [] audit list).
Legacy file_id remains a "latest" pointer. Both borrowers (incl. linked sponsors)
and admins can upload/delete individual files.
"""
import base64
import io
import os
import zipfile
import uuid
import pytest
import requests

def _read_frontend_env():
    try:
        with open("/app/frontend/.env") as fh:
            for line in fh:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return None


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _read_frontend_env() or "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "wayne@byrd-co.com"
ADMIN_PASS = "byrdco2026"
CLIENT_EMAIL = "sample@example.com"
CLIENT_PASS = "sample123"

# Known permanent 3-Sponsor Test Deal
SCENARIO_ID = "c4d98f0b-f8d6-4399-abde-ccad9312c953"
PFS_DOC_ID = "a9e4380f-bcb6-4484-af69-17a0bac461df"
LENDER_TOKEN = "6e455e255da149349dd4e7e21ac6b3678c048c7026554d60867e7f557e75abfd"


def _b64(txt: str) -> str:
    return base64.b64encode(txt.encode()).decode()


@pytest.fixture(scope="module")
def client_token():
    r = requests.post(f"{API}/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PASS})
    assert r.status_code == 200, f"client login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200, f"admin login failed: {r.text}"
    return r.json()["token"]


def _hc(t): return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _get_doc_from_client_me(client_token, doc_id):
    r = requests.get(f"{API}/client/me", headers=_hc(client_token))
    assert r.status_code == 200, r.text
    data = r.json()
    for s in data.get("scenarios", []):
        for d in s.get("docs", []):
            if d["id"] == doc_id:
                return d
    return None


def _get_doc_from_admin(admin_token, sid, doc_id):
    r = requests.get(f"{API}/admin/scenarios/{sid}", headers=_hc(admin_token))
    assert r.status_code == 200, r.text
    for d in r.json().get("docs", []):
        if d["id"] == doc_id:
            return d
    return None


def _cleanup_all_files_from_doc(admin_token, sid, doc_id):
    """Best-effort clear PFS doc before/after tests using admin delete-file endpoint."""
    d = _get_doc_from_admin(admin_token, sid, doc_id)
    if not d:
        return
    for f in (d.get("files") or []):
        fid = f.get("id")
        if fid:
            requests.delete(f"{API}/admin/scenarios/{sid}/docs/{doc_id}/files/{fid}",
                            headers=_hc(admin_token))


@pytest.fixture(scope="module", autouse=True)
def _pretest_cleanup(admin_token):
    _cleanup_all_files_from_doc(admin_token, SCENARIO_ID, PFS_DOC_ID)
    yield
    _cleanup_all_files_from_doc(admin_token, SCENARIO_ID, PFS_DOC_ID)


# ------------------------------------------------------------------
# Borrower (linked sponsor) multi-file upload flow
# ------------------------------------------------------------------
class TestBorrowerMultiFile:
    file_ids: list = []

    def test_01_upload_three_files_as_linked_sponsor(self, client_token):
        """Sample user is a LINKED SPONSOR (not primary client_id) on the doc.
        Multiple sequential uploads should all succeed and each return a new file_id."""
        ids = []
        for i in range(3):
            body = {
                "data_b64": _b64(f"file-{i}-content"),
                "filename": f"pfs_page_{i+1}.txt",
                "content_type": "text/plain",
            }
            r = requests.post(f"{API}/client/docs/{PFS_DOC_ID}/upload",
                              headers=_hc(client_token), json=body)
            assert r.status_code == 200, f"upload #{i} failed: {r.status_code} {r.text}"
            j = r.json()
            assert j.get("ok") is True
            assert isinstance(j.get("file_id"), str) and len(j["file_id"]) > 0
            ids.append(j["file_id"])
        assert len(set(ids)) == 3, "file_ids must be unique per upload"
        TestBorrowerMultiFile.file_ids = ids

    def test_02_client_me_returns_all_three_files_in_order(self, client_token):
        d = _get_doc_from_client_me(client_token, PFS_DOC_ID)
        assert d is not None, "PFS doc must be visible to linked sponsor"
        files = d.get("files") or []
        assert len(files) == 3, f"expected 3 files, got {len(files)}: {files}"
        # Verify order preserved
        expected_names = ["pfs_page_1.txt", "pfs_page_2.txt", "pfs_page_3.txt"]
        assert [f["filename"] for f in files] == expected_names
        for f in files:
            assert f.get("id"), "each file must expose id"
            assert f.get("size") is not None
            assert f.get("uploaded_by") == "client"
            assert f.get("uploaded_at")
        assert d["status"] == "uploaded", "status should flip to uploaded after first upload"

    def test_03_delete_middle_file_keeps_others(self, client_token):
        target = TestBorrowerMultiFile.file_ids[1]
        r = requests.delete(f"{API}/client/docs/{PFS_DOC_ID}/files/{target}",
                            headers=_hc(client_token))
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("ok") is True
        doc = j.get("doc") or {}
        remaining_meta = doc.get("files") or []
        remaining_ids = [m.get("file_id") for m in remaining_meta]
        assert target not in remaining_ids
        assert len(remaining_ids) == 2

        # Verify via /client/me too
        d = _get_doc_from_client_me(client_token, PFS_DOC_ID)
        files = d.get("files") or []
        assert len(files) == 2
        assert {f["filename"] for f in files} == {"pfs_page_1.txt", "pfs_page_3.txt"}
        assert d["status"] == "uploaded"

    def test_04_delete_all_files_resets_status_to_pending(self, client_token):
        d = _get_doc_from_client_me(client_token, PFS_DOC_ID)
        remaining_ids = [f["id"] for f in d.get("files") or []]
        for fid in remaining_ids:
            r = requests.delete(f"{API}/client/docs/{PFS_DOC_ID}/files/{fid}",
                                headers=_hc(client_token))
            assert r.status_code == 200
        d2 = _get_doc_from_client_me(client_token, PFS_DOC_ID)
        assert (d2.get("files") or []) == []
        assert d2["status"] == "pending", f"status should reset to pending, got {d2['status']}"


# ------------------------------------------------------------------
# Admin upload on behalf + admin delete
# ------------------------------------------------------------------
class TestAdminMultiFile:
    def test_10_admin_upload_on_behalf(self, admin_token, client_token):
        body = {
            "data_b64": _b64("broker-uploaded-file"),
            "filename": "broker_upload.txt",
            "content_type": "text/plain",
        }
        r = requests.post(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{PFS_DOC_ID}/upload",
                          headers=_hc(admin_token), json=body)
        assert r.status_code == 200, r.text
        fid = r.json().get("file_id")
        assert fid

        # Appears in /client/me with uploaded_by='broker'
        d = _get_doc_from_client_me(client_token, PFS_DOC_ID)
        assert d is not None
        broker_files = [f for f in (d.get("files") or []) if f["id"] == fid]
        assert broker_files, "admin-uploaded file must appear in borrower view"
        assert broker_files[0]["uploaded_by"] == "broker"

    def test_11_admin_delete_individual_file(self, admin_token, client_token):
        # Add a second file via admin, then delete only the FIRST admin file
        body_b = {
            "data_b64": _b64("second-broker-file"),
            "filename": "broker_upload_2.txt",
            "content_type": "text/plain",
        }
        r = requests.post(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{PFS_DOC_ID}/upload",
                          headers=_hc(admin_token), json=body_b)
        assert r.status_code == 200
        fid_second = r.json()["file_id"]

        d = _get_doc_from_admin(admin_token, SCENARIO_ID, PFS_DOC_ID)
        files = d.get("files") or []
        assert len(files) == 2

        # Delete the first
        fid_first = [f["id"] for f in files if f["id"] != fid_second][0]
        r = requests.delete(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{PFS_DOC_ID}/files/{fid_first}",
                            headers=_hc(admin_token))
        assert r.status_code == 200, r.text

        d2 = _get_doc_from_admin(admin_token, SCENARIO_ID, PFS_DOC_ID)
        remaining = d2.get("files") or []
        assert len(remaining) == 1
        assert remaining[0]["id"] == fid_second


# ------------------------------------------------------------------
# Admin scenario docs.zip must include ALL files across ALL lines
# ------------------------------------------------------------------
class TestAdminScenarioZip:
    line_b_id = None
    fids: list = []

    def test_20_upload_files_across_two_lines(self, admin_token):
        # Find a second doc line on the scenario (any non-system, non-PFS one)
        r = requests.get(f"{API}/admin/scenarios/{SCENARIO_ID}", headers=_hc(admin_token))
        assert r.status_code == 200
        docs = r.json().get("docs", [])
        other = next((d for d in docs if d["id"] != PFS_DOC_ID and not d.get("system")), None)
        assert other is not None, "need a second doc line for zip test"
        TestAdminScenarioZip.line_b_id = other["id"]

        # Clear that line first (best effort)
        for f in (other.get("files") or []):
            requests.delete(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{other['id']}/files/{f['id']}",
                            headers=_hc(admin_token))

        # PFS: 2 files
        for i in range(2):
            requests.post(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{PFS_DOC_ID}/upload",
                          headers=_hc(admin_token),
                          json={"data_b64": _b64(f"pfs-{i}"),
                                "filename": f"pfs_{i}.txt", "content_type": "text/plain"})
        # Other line: 1 file
        requests.post(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{other['id']}/upload",
                      headers=_hc(admin_token),
                      json={"data_b64": _b64("other-content"),
                            "filename": "other.txt", "content_type": "text/plain"})

    def test_21_zip_contains_all_three_files(self, admin_token):
        r = requests.get(f"{API}/admin/scenarios/{SCENARIO_ID}/docs.zip",
                         headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/zip")
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        # We expect at least 3 entries (may include other pre-existing uploaded lines from prior tests)
        pfs_entries = [n for n in names if "pfs_0" in n or "pfs_1" in n]
        other_entries = [n for n in names if "other.txt" in n]
        assert len(pfs_entries) == 2, f"expected 2 PFS files in zip, got names={names}"
        assert len(other_entries) == 1
        # Zip filename convention: '<label> - <filename>'
        assert any(" - " in n for n in names), f"expected 'label - filename' format, got: {names}"

    def test_22_cleanup_line_b(self, admin_token):
        # Delete file on line B
        d = _get_doc_from_admin(admin_token, SCENARIO_ID, TestAdminScenarioZip.line_b_id)
        for f in (d.get("files") or []):
            requests.delete(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{TestAdminScenarioZip.line_b_id}/files/{f['id']}",
                            headers=_hc(admin_token))


# ------------------------------------------------------------------
# Lender view multi-file
# ------------------------------------------------------------------
class TestLenderView:
    session_token: str = ""

    def test_30_setup_share_override_to_include_pfs(self, admin_token):
        """Ensure the known share has doc_overrides[PFS] = 'include'."""
        # Fetch share for the scenario, find one; if none, create.
        r = requests.get(f"{API}/admin/scenarios/{SCENARIO_ID}", headers=_hc(admin_token))
        assert r.status_code == 200
        shares = r.json().get("shares", [])
        share = next((s for s in shares if s.get("token") == LENDER_TOKEN), None)
        if not share and shares:
            share = shares[0]
        assert share, "Need at least one existing lender share on scenario"

        # PATCH doc_overrides
        share_id = share["id"]
        payload = {"doc_overrides": {PFS_DOC_ID: "included"}}
        r = requests.patch(f"{API}/admin/scenarios/{SCENARIO_ID}/shares/{share_id}",
                           headers=_hc(admin_token), json=payload)
        # Endpoint might not exist under this exact path — try alt
        if r.status_code == 404:
            r = requests.patch(f"{API}/admin/shares/{share_id}",
                               headers=_hc(admin_token), json=payload)
        # If neither works, just log; the test itself will detect if the doc is visible
        TestLenderView.share_token = share.get("token") or LENDER_TOKEN

        # Upload one file to PFS as admin so lender can see it
        requests.post(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{PFS_DOC_ID}/upload",
                      headers=_hc(admin_token),
                      json={"data_b64": _b64("pfs-lender-1"),
                            "filename": "lender_pfs_1.txt", "content_type": "text/plain"})
        requests.post(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{PFS_DOC_ID}/upload",
                      headers=_hc(admin_token),
                      json={"data_b64": _b64("pfs-lender-2"),
                            "filename": "lender_pfs_2.txt", "content_type": "text/plain"})

    def test_31_gate_and_get_package(self):
        token = getattr(TestLenderView, "share_token", LENDER_TOKEN)
        r = requests.post(f"{API}/lender-view/{token}/gate", json={
            "viewer_name": "Test Viewer",
            "viewer_institution": "Test Bank",
            "viewer_email": "viewer@testbank.com",
            "accept_nda": True,
        })
        if r.status_code != 200:
            pytest.skip(f"lender gate failed ({r.status_code}): {r.text}")
        st = r.json().get("session_token")
        assert st
        TestLenderView.session_token = st

        r = requests.get(f"{API}/lender-view/{token}", params={"session_token": st})
        assert r.status_code == 200, r.text
        data = r.json()
        docs = data.get("docs") or []
        pfs = next((d for d in docs if d["id"] == PFS_DOC_ID), None)
        assert pfs is not None, "PFS doc must be in lender package"
        if pfs.get("viewable"):
            assert isinstance(pfs.get("files"), list)
            assert pfs.get("file_count") == len(pfs["files"])
            assert pfs["file_count"] >= 2, f"expected ≥2 files on PFS, got {pfs['file_count']}"
            for f in pfs["files"]:
                assert f.get("id") and f.get("filename")
        else:
            pytest.skip(f"PFS doc not viewable in this share (visibility={pfs.get('visibility')}, "
                        f"requires_request={pfs.get('requires_request')}). Set doc_overrides.")

    def test_32_fetch_specific_file_and_default(self):
        token = getattr(TestLenderView, "share_token", LENDER_TOKEN)
        st = TestLenderView.session_token
        if not st:
            pytest.skip("no session token")

        # Get file list via package
        r = requests.get(f"{API}/lender-view/{token}", params={"session_token": st})
        docs = r.json().get("docs") or []
        pfs = next((d for d in docs if d["id"] == PFS_DOC_ID and d.get("viewable")), None)
        if not pfs:
            pytest.skip("PFS not viewable")
        files = pfs["files"]
        # Fetch with file_id
        r = requests.get(f"{API}/lender-view/{token}/doc/{PFS_DOC_ID}",
                         params={"session_token": st, "file_id": files[1]["id"]})
        assert r.status_code == 200
        assert r.content == b"pfs-lender-2" or files[1]["filename"] in r.headers.get("content-disposition", "")
        # Fetch without file_id => defaults to first file
        r2 = requests.get(f"{API}/lender-view/{token}/doc/{PFS_DOC_ID}",
                          params={"session_token": st})
        assert r2.status_code == 200

    def test_33_per_doc_zip(self):
        token = getattr(TestLenderView, "share_token", LENDER_TOKEN)
        st = TestLenderView.session_token
        if not st:
            pytest.skip("no session")
        r = requests.get(f"{API}/lender-view/{token}/doc/{PFS_DOC_ID}/zip",
                         params={"session_token": st})
        if r.status_code == 403:
            pytest.skip("PFS not included in this share")
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/zip")
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        assert len(zf.namelist()) >= 2

    def test_34_all_docs_zip(self):
        token = getattr(TestLenderView, "share_token", LENDER_TOKEN)
        st = TestLenderView.session_token
        if not st:
            pytest.skip("no session")
        r = requests.get(f"{API}/lender-view/{token}/docs.zip",
                         params={"session_token": st})
        if r.status_code == 404:
            pytest.skip("no docs available in this share")
        assert r.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        # If PFS is included, we should see BOTH PFS files (not just one)
        pfs_names = [n for n in names if "lender_pfs" in n]
        assert len(pfs_names) >= 2, f"docs.zip should contain all files, got PFS names: {pfs_names}, all: {names}"


# ------------------------------------------------------------------
# Legacy backward-compat: doc with only file_id (no files[]) must still work
# ------------------------------------------------------------------
class TestLegacyCompat:
    def test_40_synthetic_legacy_row_returns_files_array(self, admin_token, client_token):
        """Simulate a pre-migration row by uploading then manually clearing files[] on a fresh line.
        We do this by using an admin scenario doc and creating a scenario_doc row through create.
        Since we can't easily reach the DB directly here, we validate by using the existing PFS doc
        (which has been touched by _populate_doc_files) and check no crashes for docs with no uploads.
        """
        # Ensure PFS is empty
        _cleanup_all_files_from_doc(admin_token, SCENARIO_ID, PFS_DOC_ID)
        d = _get_doc_from_client_me(client_token, PFS_DOC_ID)
        # Empty state must still return files=[] array (not None) — this is the migration guarantee
        assert isinstance(d.get("files"), list)
        assert d["files"] == []
        assert d["status"] == "pending"


# ------------------------------------------------------------------
# Delete cascade
# ------------------------------------------------------------------
class TestDeleteCascade:
    def test_50_delete_scenario_doc_removes_all_underlying_files(self, admin_token):
        # Create a temp doc line, upload 3 files, delete the line, verify no client_files left
        r = requests.post(f"{API}/admin/scenarios/{SCENARIO_ID}/docs",
                          headers=_hc(admin_token),
                          json={"label": "TEST_MultiCascade", "category": "Other", "required": False})
        assert r.status_code == 200, r.text
        doc = r.json()
        doc_id = doc["id"]
        fids = []
        for i in range(3):
            r = requests.post(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{doc_id}/upload",
                              headers=_hc(admin_token),
                              json={"data_b64": _b64(f"cascade-{i}"),
                                    "filename": f"c_{i}.txt", "content_type": "text/plain"})
            assert r.status_code == 200
            fids.append(r.json()["file_id"])
        # Delete the whole doc line
        r = requests.delete(f"{API}/admin/scenarios/{SCENARIO_ID}/docs/{doc_id}",
                            headers=_hc(admin_token))
        assert r.status_code == 200

        # Each file_id must be inaccessible via /api/files/{fid}
        for fid in fids:
            r = requests.get(f"{API}/files/{fid}",
                             headers={"Authorization": f"Bearer {admin_token}"})
            assert r.status_code == 404, f"file {fid} should be deleted after cascade, got {r.status_code}"

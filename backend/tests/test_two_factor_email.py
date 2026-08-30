"""Email-only 2FA + cross-role 2FA backend tests (Byrd & CO).

Email content cannot be read by the test agent, so email codes are seeded directly
into db.two_fa_email_codes with a known bcrypt hash (same helper the server uses).
"""
import os
import time
import uuid
from datetime import datetime, timezone, timedelta

import bcrypt
import pyotp
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = base_url.rstrip("/") + "/api"

WAYNE = {"email": "wayne@byrd-co.com", "password": "byrdco2026"}
CALEB = {"email": "caleb@byrd-co.com", "password": "byrdco2026"}
CLIENT = {"email": "sample@example.com", "password": "sample123"}
LENDER = {"email": "contact@testfrost.example", "password": "testlender123"}

EMAIL_USER = {"email": "test_2fa_email_user@byrd-co.com", "password": "TestEmail2fa!23"}
EMAIL_USER_BACKUP = "test-abcd-abcd"


def mdb():
    return MongoClient(be["MONGO_URL"])[be["DB_NAME"]]


def bhash(s):
    return bcrypt.hashpw(s.encode(), bcrypt.gensalt()).decode()


def hard_disable_2fa(email):
    db = mdb()
    db.users.update_one({"email": email}, {
        "$set": {"totp_enabled": False, "backup_codes": [], "two_fa_method": None},
        "$unset": {"totp_secret": "", "pending_totp_secret": "", "totp_enrolled_at": ""},
    })
    db.two_fa_attempts.delete_many({})
    db.login_attempts.delete_many({})


def seed_email_code(user_id, purpose, code, minutes=10, used=False):
    mdb().two_fa_email_codes.insert_one({
        "user_id": user_id, "purpose": purpose, "code_hash": bhash(code),
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=minutes),
        "used": used,
    })


def login(email, password):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)


def token_for(creds):
    r = login(creds["email"], creds["password"])
    assert r.status_code == 200, r.text
    tok = r.json().get("token")
    assert tok, r.json()
    return tok


def hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def fresh_totp(secret):
    if 30 - (int(time.time()) % 30) < 3:
        time.sleep(3)
    return pyotp.TOTP(secret).now()


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    for e in [WAYNE["email"], CALEB["email"], CLIENT["email"], LENDER["email"]]:
        hard_disable_2fa(e)
    yield
    for e in [WAYNE["email"], CALEB["email"], CLIENT["email"], LENDER["email"]]:
        hard_disable_2fa(e)
    db = mdb()
    u = db.users.find_one({"email": EMAIL_USER["email"]})
    if u:
        db.two_fa_email_codes.delete_many({"user_id": u["id"]})
    db.users.delete_many({"email": EMAIL_USER["email"]})


# ================= TOTP regression =================
class TestTotpRegression:
    def test_totp_enroll_still_works_and_sets_method_totp(self):
        hard_disable_2fa(WAYNE["email"])
        tok = token_for(WAYNE)
        r = requests.post(f"{API}/auth/2fa/setup", headers=hdr(tok), timeout=30)
        assert r.status_code == 200, r.text
        secret = r.json()["secret"]
        assert r.json()["qr_data_url"].startswith("data:image/png;base64,")

        v = requests.post(f"{API}/auth/2fa/verify-setup", headers=hdr(tok),
                          json={"code": fresh_totp(secret)}, timeout=30)
        assert v.status_code == 200, v.text
        assert v.json()["method"] == "totp"
        assert len(v.json()["backup_codes"]) == 10

        st = requests.get(f"{API}/auth/2fa/status", headers=hdr(tok), timeout=30)
        assert st.status_code == 200
        assert st.json()["enabled"] is True
        assert st.json()["method"] == "totp"
        assert st.json()["backup_codes_remaining"] == 10

        me = requests.get(f"{API}/auth/me", headers=hdr(tok), timeout=30)
        assert me.status_code == 200
        assert me.json()["two_fa_method"] == "totp"
        assert "_id" not in me.json()

        # login now requires 2FA, primary_method totp, totp_available true
        lr = login(WAYNE["email"], WAYNE["password"])
        assert lr.status_code == 200, lr.text
        d = lr.json()
        assert d["requires_2fa"] is True
        assert d["primary_method"] == "totp"
        assert d["totp_available"] is True
        assert d["challenge_token"]

        # disable with fresh TOTP
        dis = requests.post(f"{API}/auth/2fa/disable", headers=hdr(tok),
                            json={"password": WAYNE["password"], "code": fresh_totp(secret)}, timeout=30)
        assert dis.status_code == 200, dis.text
        assert requests.get(f"{API}/auth/2fa/status", headers=hdr(tok), timeout=30).json()["method"] is None


# ================= Email-only enrollment =================
class TestEmailEnrollment:
    def test_email_setup_sends_code_and_bad_code_rejected(self):
        hard_disable_2fa(WAYNE["email"])
        tok = token_for(WAYNE)
        r = requests.post(f"{API}/auth/2fa/email/setup", headers=hdr(tok), timeout=45)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["sent_to_masked"] == "w***@byrd-co.com"
        assert d["expires_in_minutes"] == 10

        # code doc stored with purpose='setup'
        uid = mdb().users.find_one({"email": WAYNE["email"]})["id"]
        doc = mdb().two_fa_email_codes.find_one({"user_id": uid, "purpose": "setup"},
                                                sort=[("created_at", -1)])
        assert doc is not None
        assert doc["used"] is False
        assert doc["code_hash"].startswith("$2b$")

        bad = requests.post(f"{API}/auth/2fa/email/verify-setup", headers=hdr(tok),
                            json={"code": "000000"}, timeout=30)
        assert bad.status_code == 400, bad.text
        # 2FA must still be off after a bad code
        assert requests.get(f"{API}/auth/2fa/status", headers=hdr(tok), timeout=30).json()["enabled"] is False

    def test_email_enrollment_happy_path_sets_method_email(self):
        hard_disable_2fa(CALEB["email"])
        tok = token_for(CALEB)
        uid = mdb().users.find_one({"email": CALEB["email"]})["id"]
        requests.post(f"{API}/auth/2fa/email/setup", headers=hdr(tok), timeout=45)
        seed_email_code(uid, "setup", "123456")

        v = requests.post(f"{API}/auth/2fa/email/verify-setup", headers=hdr(tok),
                          json={"code": "123456"}, timeout=30)
        assert v.status_code == 200, v.text
        assert v.json()["method"] == "email"
        codes = v.json()["backup_codes"]
        assert len(codes) == 10

        st = requests.get(f"{API}/auth/2fa/status", headers=hdr(tok), timeout=30).json()
        assert st["enabled"] is True and st["method"] == "email"

        me = requests.get(f"{API}/auth/me", headers=hdr(tok), timeout=30).json()
        assert me["two_fa_method"] == "email"

        dbu = mdb().users.find_one({"email": CALEB["email"]})
        assert not dbu.get("totp_secret"), "email-only user must not have a totp_secret"

        # login shape for email-primary user
        lr = login(CALEB["email"], CALEB["password"]).json()
        assert lr["requires_2fa"] is True
        assert lr["primary_method"] == "email"
        assert lr["totp_available"] is False
        assert lr["email_available"] is True

        # reused setup code cannot be replayed
        again = requests.post(f"{API}/auth/2fa/email/verify-setup", headers=hdr(tok),
                              json={"code": "123456"}, timeout=30)
        assert again.status_code == 400

        # send-verification (purpose='verify') then disable with that code
        sv = requests.post(f"{API}/auth/2fa/email/send-verification", headers=hdr(tok), timeout=45)
        assert sv.status_code == 200, sv.text
        assert sv.json()["ok"] is True
        vdoc = mdb().two_fa_email_codes.find_one({"user_id": uid, "purpose": "verify"},
                                                 sort=[("created_at", -1)])
        assert vdoc is not None

        # regenerate backup codes with a seeded verify code
        seed_email_code(uid, "verify", "222222")
        rg = requests.post(f"{API}/auth/2fa/regenerate-backup-codes", headers=hdr(tok),
                           json={"code": "222222"}, timeout=30)
        assert rg.status_code == 200, rg.text
        new_codes = rg.json()["backup_codes"]
        assert len(new_codes) == 10 and set(new_codes) != set(codes)

        # old backup code no longer valid for disable
        bad = requests.post(f"{API}/auth/2fa/disable", headers=hdr(tok),
                            json={"password": CALEB["password"], "code": codes[0]}, timeout=30)
        assert bad.status_code == 400, bad.text

        # disable with a NEW valid backup code
        ok = requests.post(f"{API}/auth/2fa/disable", headers=hdr(tok),
                           json={"password": CALEB["password"], "code": new_codes[0]}, timeout=30)
        assert ok.status_code == 200, ok.text
        st = requests.get(f"{API}/auth/2fa/status", headers=hdr(tok), timeout=30).json()
        assert st["enabled"] is False and st["method"] is None
        assert login(CALEB["email"], CALEB["password"]).json().get("token")

    def test_send_verification_requires_2fa_enabled(self):
        hard_disable_2fa(WAYNE["email"])
        tok = token_for(WAYNE)
        r = requests.post(f"{API}/auth/2fa/email/send-verification", headers=hdr(tok), timeout=30)
        assert r.status_code == 400, r.text

    def test_email_setup_endpoints_require_auth(self):
        for path in ["/auth/2fa/email/setup", "/auth/2fa/email/send-verification"]:
            r = requests.post(f"{API}{path}", timeout=30)
            assert r.status_code in (401, 403), f"{path} -> {r.status_code}"


# ================= Seeded email-only user: login + purpose isolation =================
class TestEmailOnlyUser:
    @pytest.fixture(scope="class", autouse=True)
    def seeded_user(self):
        db = mdb()
        db.users.delete_many({"email": EMAIL_USER["email"]})
        uid = str(uuid.uuid4())
        db.users.insert_one({
            "id": uid,
            "email": EMAIL_USER["email"],
            "name": "TEST Email 2FA User",
            "role": "client",
            "status": "active",
            "password_hash": bhash(EMAIL_USER["password"]),
            "totp_enabled": True,
            "two_fa_method": "email",
            "backup_codes": [bhash(EMAIL_USER_BACKUP)],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        yield uid
        db.two_fa_email_codes.delete_many({"user_id": uid})
        db.users.delete_many({"email": EMAIL_USER["email"]})

    def test_login_returns_email_primary(self, seeded_user):
        d = login(EMAIL_USER["email"], EMAIL_USER["password"])
        assert d.status_code == 200, d.text
        j = d.json()
        assert j["requires_2fa"] is True
        assert j["primary_method"] == "email"
        assert j["totp_available"] is False
        assert j["email_available"] is True
        assert j.get("token") in (None, "")

    def test_challenge_send_email_code_and_login_purpose_isolation(self, seeded_user):
        ct = login(EMAIL_USER["email"], EMAIL_USER["password"]).json()["challenge_token"]
        s = requests.post(f"{API}/auth/2fa/send-email-code", json={"challenge_token": ct}, timeout=45)
        assert s.status_code == 200, s.text
        assert s.json()["sent_to_masked"].startswith("t***@")
        doc = mdb().two_fa_email_codes.find_one({"user_id": seeded_user, "purpose": "login"},
                                                sort=[("created_at", -1)])
        assert doc is not None, "login-purpose code not stored"

        # A 'verify' purpose code must NOT satisfy a login challenge
        seed_email_code(seeded_user, "verify", "333333")
        bad = requests.post(f"{API}/auth/2fa/challenge",
                            json={"challenge_token": ct, "method": "email", "code": "333333"}, timeout=30)
        assert bad.status_code == 400, bad.text

        # A 'login' purpose code DOES satisfy the challenge
        seed_email_code(seeded_user, "login", "444444")
        good = requests.post(f"{API}/auth/2fa/challenge",
                             json={"challenge_token": ct, "method": "email", "code": "444444"}, timeout=30)
        assert good.status_code == 200, good.text
        assert good.json()["token"]
        assert good.json()["user"]["two_fa_method"] == "email"
        assert good.json()["user"]["email"] == EMAIL_USER["email"]
        assert "password_hash" not in good.json()["user"]

    def test_login_purpose_code_cannot_be_used_for_disable(self, seeded_user):
        # obtain a full JWT via backup code challenge
        ct = login(EMAIL_USER["email"], EMAIL_USER["password"]).json()["challenge_token"]
        ch = requests.post(f"{API}/auth/2fa/challenge",
                           json={"challenge_token": ct, "method": "backup", "code": EMAIL_USER_BACKUP}, timeout=30)
        assert ch.status_code == 200, ch.text
        tok = ch.json()["token"]

        seed_email_code(seeded_user, "login", "555555")
        bad = requests.post(f"{API}/auth/2fa/disable", headers=hdr(tok),
                            json={"password": EMAIL_USER["password"], "code": "555555"}, timeout=30)
        assert bad.status_code == 400, "login-purpose code must not authorize disable"

        # wrong password -> 401
        seed_email_code(seeded_user, "verify", "666666")
        wp = requests.post(f"{API}/auth/2fa/disable", headers=hdr(tok),
                           json={"password": "wrong-password", "code": "666666"}, timeout=30)
        assert wp.status_code == 401, wp.text

        ok = requests.post(f"{API}/auth/2fa/disable", headers=hdr(tok),
                           json={"password": EMAIL_USER["password"], "code": "666666"}, timeout=30)
        assert ok.status_code == 200, ok.text
        u = mdb().users.find_one({"id": seeded_user})
        assert u.get("totp_enabled") is False and u.get("two_fa_method") is None


# ================= Cross-role (client + lender) =================
class TestCrossRole:
    @pytest.mark.parametrize("creds", [CLIENT, LENDER], ids=["client", "lender"])
    def test_role_can_enroll_email_2fa_and_status(self, creds):
        hard_disable_2fa(creds["email"])
        tok = token_for(creds)
        st = requests.get(f"{API}/auth/2fa/status", headers=hdr(tok), timeout=30)
        assert st.status_code == 200, st.text
        assert st.json()["enabled"] is False and st.json()["method"] is None

        r = requests.post(f"{API}/auth/2fa/email/setup", headers=hdr(tok), timeout=45)
        assert r.status_code == 200, r.text
        uid = mdb().users.find_one({"email": creds["email"]})["id"]
        seed_email_code(uid, "setup", "777777")
        v = requests.post(f"{API}/auth/2fa/email/verify-setup", headers=hdr(tok),
                          json={"code": "777777"}, timeout=30)
        assert v.status_code == 200, v.text
        assert v.json()["method"] == "email"
        assert requests.get(f"{API}/auth/2fa/status", headers=hdr(tok), timeout=30).json()["method"] == "email"

        # cannot re-enroll while enabled
        dup = requests.post(f"{API}/auth/2fa/email/setup", headers=hdr(tok), timeout=30)
        assert dup.status_code == 400
        dup2 = requests.post(f"{API}/auth/2fa/setup", headers=hdr(tok), timeout=30)
        assert dup2.status_code == 400

        # clean up via disable with backup code
        d = requests.post(f"{API}/auth/2fa/disable", headers=hdr(tok),
                          json={"password": creds["password"], "code": v.json()["backup_codes"][1]}, timeout=30)
        assert d.status_code == 200, d.text
        hard_disable_2fa(creds["email"])


# ================= Admin reset =================
class TestAdminReset:
    def test_admin_reset_clears_two_fa_method(self):
        hard_disable_2fa(CLIENT["email"])
        ctok = token_for(CLIENT)
        requests.post(f"{API}/auth/2fa/email/setup", headers=hdr(ctok), timeout=45)
        uid = mdb().users.find_one({"email": CLIENT["email"]})["id"]
        seed_email_code(uid, "setup", "888888")
        v = requests.post(f"{API}/auth/2fa/email/verify-setup", headers=hdr(ctok),
                          json={"code": "888888"}, timeout=30)
        assert v.status_code == 200, v.text

        hard_disable_2fa(WAYNE["email"])
        atok = token_for(WAYNE)
        r = requests.post(f"{API}/admin/users/{uid}/2fa/reset", headers=hdr(atok), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

        u = mdb().users.find_one({"id": uid})
        assert u.get("totp_enabled") is False
        assert u.get("two_fa_method") is None
        assert not u.get("totp_secret")
        assert login(CLIENT["email"], CLIENT["password"]).json().get("token")

    def test_admin_reset_requires_admin_and_404_for_unknown(self):
        ctok = token_for(CLIENT)
        uid = mdb().users.find_one({"email": CLIENT["email"]})["id"]
        r = requests.post(f"{API}/admin/users/{uid}/2fa/reset", headers=hdr(ctok), timeout=30)
        assert r.status_code in (401, 403), r.status_code
        atok = token_for(WAYNE)
        r2 = requests.post(f"{API}/admin/users/{uuid.uuid4()}/2fa/reset", headers=hdr(atok), timeout=30)
        assert r2.status_code == 404, r2.status_code

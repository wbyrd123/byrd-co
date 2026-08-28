"""2FA (TOTP + email fallback + backup codes) backend tests for Byrd & CO portal."""
import os
import time

import pyotp
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
backend_env = dotenv_values("/app/backend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")
API = BASE_URL + "/api"

WAYNE = {"email": "wayne@byrd-co.com", "password": "byrdco2026"}
CALEB = {"email": "caleb@byrd-co.com", "password": "byrdco2026"}


# ---------- helpers ----------
def mongo_db():
    cli = MongoClient(backend_env["MONGO_URL"])
    return cli[backend_env["DB_NAME"]]


def hard_disable_2fa(email):
    """Safety net: clear 2FA state directly in DB so no account gets locked out."""
    db = mongo_db()
    db.users.update_one({"email": email}, {
        "$set": {"totp_enabled": False, "backup_codes": []},
        "$unset": {"totp_secret": "", "pending_totp_secret": "", "totp_enrolled_at": ""},
    })
    db.two_fa_attempts.delete_many({})
    db.login_attempts.delete_many({})


def fresh_totp(secret):
    """Return a TOTP code, avoiding the tail of a time step so it stays valid."""
    if pyotp.TOTP(secret).interval - (int(time.time()) % 30) < 3:
        time.sleep(3)
    return pyotp.TOTP(secret).now()


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    hard_disable_2fa(WAYNE["email"])
    hard_disable_2fa(CALEB["email"])
    yield
    hard_disable_2fa(WAYNE["email"])
    hard_disable_2fa(CALEB["email"])


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def login(s, creds):
    r = s.post(f"{API}/auth/login", json=creds, timeout=30)
    return r


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- 1. Regression: login without 2FA ----------
class TestLoginNo2FA:
    def test_login_returns_full_jwt(self, s):
        r = login(s, WAYNE)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("token"), f"no token in {d}"
        assert d.get("requires_2fa") in (False, None)
        assert d["user"]["email"] == WAYNE["email"]
        assert d["user"]["totp_enabled"] is False
        pytest.wayne_token = d["token"]

    def test_me_works(self, s):
        r = s.get(f"{API}/auth/me", headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["email"] == WAYNE["email"]
        pytest.wayne_uid = r.json()["id"]

    def test_status_disabled(self, s):
        r = s.get(f"{API}/auth/2fa/status", headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is False


# ---------- 2. Enrollment ----------
class TestEnrollment:
    def test_setup(self, s):
        r = s.post(f"{API}/auth/2fa/setup", headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["secret"] and isinstance(d["secret"], str)
        assert d["qr_data_url"].startswith("data:image/png;base64,")
        assert d["otpauth_uri"].startswith("otpauth://totp/")
        assert "Byrd" in d["otpauth_uri"]
        pytest.secret = d["secret"]

    def test_verify_setup_bad_code(self, s):
        r = s.post(f"{API}/auth/2fa/verify-setup", json={"code": "000000"},
                   headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 400, r.text

    def test_verify_setup_good_code(self, s):
        r = s.post(f"{API}/auth/2fa/verify-setup", json={"code": fresh_totp(pytest.secret)},
                   headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        codes = d["backup_codes"]
        assert len(codes) == 10
        for c in codes:
            assert len(c) == 9 and c[4] == "-", c
        pytest.backup_codes = codes

    def test_setup_again_rejected(self, s):
        r = s.post(f"{API}/auth/2fa/setup", headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 400, r.text

    def test_status_enabled(self, s):
        r = s.get(f"{API}/auth/2fa/status", headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["enabled"] is True
        assert d["backup_codes_remaining"] == 10
        assert d["enrolled_at"]


# ---------- 3. Login now requires 2FA ----------
class TestChallengeFlow:
    def test_login_requires_2fa(self, s):
        r = login(s, WAYNE)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["requires_2fa"] is True
        assert d["challenge_token"]
        assert d.get("token") in (None, ""), f"token leaked: {d}"
        assert d["totp_available"] is True and d["email_available"] is True
        pytest.challenge = d["challenge_token"]

    def test_challenge_bad_code_400(self, s):
        r = s.post(f"{API}/auth/2fa/challenge",
                   json={"challenge_token": pytest.challenge, "code": "123456", "method": "totp"}, timeout=30)
        assert r.status_code == 400, r.text

    def test_challenge_valid_totp(self, s):
        r = s.post(f"{API}/auth/2fa/challenge",
                   json={"challenge_token": pytest.challenge, "code": fresh_totp(pytest.secret),
                         "method": "totp"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["token"]
        assert d["user"]["email"] == WAYNE["email"]
        assert d["user"]["totp_enabled"] is True
        pytest.wayne_token = d["token"]
        me = s.get(f"{API}/auth/me", headers=auth_headers(d["token"]), timeout=30)
        assert me.status_code == 200, me.text
        assert me.json()["email"] == WAYNE["email"]

    def test_challenge_token_not_reusable_as_auth_jwt(self, s):
        r = s.get(f"{API}/auth/me", headers=auth_headers(pytest.challenge), timeout=30)
        assert r.status_code == 401, f"challenge token accepted as auth JWT! {r.status_code}"

    def test_auth_jwt_rejected_as_challenge_token(self, s):
        r = s.post(f"{API}/auth/2fa/challenge",
                   json={"challenge_token": pytest.wayne_token, "code": fresh_totp(pytest.secret),
                         "method": "totp"}, timeout=30)
        assert r.status_code == 401, f"auth JWT accepted as challenge token! {r.status_code} {r.text}"


# ---------- 4. Email fallback ----------
class TestEmailFallback:
    def test_send_email_code(self, s):
        ch = login(s, WAYNE).json()["challenge_token"]
        pytest.challenge = ch
        r = s.post(f"{API}/auth/2fa/send-email-code", json={"challenge_token": ch}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert "***@byrd-co.com" in d["sent_to_masked"]
        assert d["sent_to_masked"].startswith("w")

    def test_send_email_code_bad_challenge(self, s):
        r = s.post(f"{API}/auth/2fa/send-email-code", json={"challenge_token": "not-a-jwt"}, timeout=30)
        assert r.status_code == 401, r.text

    def test_email_wrong_code_400(self, s):
        r = s.post(f"{API}/auth/2fa/challenge",
                   json={"challenge_token": pytest.challenge, "code": "000000", "method": "email"}, timeout=30)
        assert r.status_code == 400, r.text

    def test_email_real_code_from_db(self, s):
        """Pull the actual generated code path: verify a stored code doc exists and is unused."""
        db = mongo_db()
        doc = db.two_fa_email_codes.find_one({"user_id": pytest.wayne_uid}, sort=[("created_at", -1)])
        assert doc is not None, "no email code persisted"
        assert doc["used"] is False
        assert doc["code_hash"].startswith("$2b$")


# ---------- 5. Backup codes ----------
class TestBackupCodes:
    def test_backup_code_login(self, s):
        ch = login(s, WAYNE).json()["challenge_token"]
        code = pytest.backup_codes[0]
        r = s.post(f"{API}/auth/2fa/challenge",
                   json={"challenge_token": ch, "code": code.lower(), "method": "backup"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["token"]
        pytest.wayne_token = r.json()["token"]

    def test_remaining_decremented(self, s):
        r = s.get(f"{API}/auth/2fa/status", headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.json()["backup_codes_remaining"] == 9

    def test_backup_code_single_use(self, s):
        ch = login(s, WAYNE).json()["challenge_token"]
        r = s.post(f"{API}/auth/2fa/challenge",
                   json={"challenge_token": ch, "code": pytest.backup_codes[0].lower(), "method": "backup"},
                   timeout=30)
        assert r.status_code == 400, f"backup code reusable! {r.text}"

    def test_regenerate_backup_codes(self, s):
        r = s.post(f"{API}/auth/2fa/regenerate-backup-codes", json={"code": fresh_totp(pytest.secret)},
                   headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 200, r.text
        new = r.json()["backup_codes"]
        assert len(new) == 10
        assert set(new).isdisjoint(set(pytest.backup_codes))
        pytest.new_backup_codes = new

    def test_old_backup_code_invalid_after_regen(self, s):
        ch = login(s, WAYNE).json()["challenge_token"]
        r = s.post(f"{API}/auth/2fa/challenge",
                   json={"challenge_token": ch, "code": pytest.backup_codes[1].lower(), "method": "backup"},
                   timeout=30)
        assert r.status_code == 400, f"stale backup code still valid! {r.text}"

    def test_new_backup_code_works(self, s):
        ch = login(s, WAYNE).json()["challenge_token"]
        r = s.post(f"{API}/auth/2fa/challenge",
                   json={"challenge_token": ch, "code": pytest.new_backup_codes[0].lower(), "method": "backup"},
                   timeout=30)
        assert r.status_code == 200, r.text
        pytest.wayne_token = r.json()["token"]

    def test_regenerate_bad_totp(self, s):
        r = s.post(f"{API}/auth/2fa/regenerate-backup-codes", json={"code": "111111"},
                   headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 400, r.text


# ---------- 6. Rate limit lockout ----------
class TestLockout:
    def test_lockout_after_5_fails(self, s):
        db = mongo_db()
        db.two_fa_attempts.delete_many({})
        ch = login(s, WAYNE).json()["challenge_token"]
        statuses = []
        for _ in range(7):
            r = s.post(f"{API}/auth/2fa/challenge",
                       json={"challenge_token": ch, "code": "000000", "method": "totp"}, timeout=30)
            statuses.append(r.status_code)
        assert 429 in statuses, f"no 429 lockout triggered: {statuses}"
        assert statuses[:5] == [400] * 5, statuses

    def test_valid_code_blocked_while_locked(self, s):
        ch = login(s, WAYNE).json()["challenge_token"]
        r = s.post(f"{API}/auth/2fa/challenge",
                   json={"challenge_token": ch, "code": fresh_totp(pytest.secret), "method": "totp"}, timeout=30)
        assert r.status_code == 429, f"lockout bypassed with valid code: {r.status_code}"
        mongo_db().two_fa_attempts.delete_many({})


# ---------- 7. Disable ----------
class TestDisable:
    def test_disable_wrong_password(self, s):
        r = s.post(f"{API}/auth/2fa/disable", json={"password": "wrongpass", "code": fresh_totp(pytest.secret)},
                   headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 401, r.text

    def test_disable_bad_code(self, s):
        r = s.post(f"{API}/auth/2fa/disable", json={"password": WAYNE["password"], "code": "000000"},
                   headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 400, r.text

    def test_disable_success(self, s):
        r = s.post(f"{API}/auth/2fa/disable",
                   json={"password": WAYNE["password"], "code": fresh_totp(pytest.secret)},
                   headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_status_after_disable(self, s):
        r = s.get(f"{API}/auth/2fa/status", headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.json()["enabled"] is False
        assert r.json()["backup_codes_remaining"] == 0

    def test_login_full_token_again(self, s):
        d = login(s, WAYNE).json()
        assert d.get("token"), d
        assert d.get("requires_2fa") in (False, None)
        pytest.wayne_token = d["token"]

    def test_disable_when_not_enabled(self, s):
        r = s.post(f"{API}/auth/2fa/disable", json={"password": WAYNE["password"], "code": "000000"},
                   headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 400, r.text


# ---------- 8. Admin reset ----------
class TestAdminReset:
    def test_enable_on_caleb(self, s):
        c = requests.Session()
        d = login(c, CALEB).json()
        assert d.get("token"), d
        tok = d["token"]
        pytest.caleb_uid = c.get(f"{API}/auth/me", headers=auth_headers(tok), timeout=30).json()["id"]
        setup = c.post(f"{API}/auth/2fa/setup", headers=auth_headers(tok), timeout=30).json()
        r = c.post(f"{API}/auth/2fa/verify-setup", json={"code": fresh_totp(setup["secret"])},
                   headers=auth_headers(tok), timeout=30)
        assert r.status_code == 200, r.text
        assert login(c, CALEB).json()["requires_2fa"] is True

    def test_admin_reset(self, s):
        r = s.post(f"{API}/admin/users/{pytest.caleb_uid}/2fa/reset",
                   headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_caleb_login_full_token(self, s):
        d = login(requests.Session(), CALEB).json()
        assert d.get("token"), d
        assert d.get("requires_2fa") in (False, None)

    def test_admin_reset_unknown_user_404(self, s):
        r = s.post(f"{API}/admin/users/does-not-exist/2fa/reset",
                   headers=auth_headers(pytest.wayne_token), timeout=30)
        assert r.status_code == 404, r.text

    def test_admin_reset_requires_admin(self, s):
        r = requests.post(f"{API}/admin/users/{pytest.caleb_uid}/2fa/reset", timeout=30)
        assert r.status_code in (401, 403), r.status_code


# ---------- 9. Auth hardening checks from playbook ----------
class TestAuthHardening:
    def test_bcrypt_hash_format(self):
        db = mongo_db()
        u = db.users.find_one({"email": WAYNE["email"]})
        assert u["password_hash"].startswith("$2b$"), u["password_hash"][:10]

    def test_2fa_endpoints_require_auth(self):
        for path in ["/auth/2fa/status", "/auth/2fa/setup", "/auth/2fa/verify-setup",
                     "/auth/2fa/disable", "/auth/2fa/regenerate-backup-codes"]:
            m = requests.get if path.endswith("status") else requests.post
            r = m(f"{API}{path}", json={"code": "000000", "password": "x"}, timeout=30)
            assert r.status_code in (401, 403), f"{path} -> {r.status_code}"

    def test_cors_credentials(self):
        r = requests.options(f"{API}/auth/login", headers={
            "Origin": BASE_URL, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        }, timeout=30)
        allow_origin = r.headers.get("access-control-allow-origin")
        print("CORS allow-origin:", allow_origin,
              "credentials:", r.headers.get("access-control-allow-credentials"))
        assert allow_origin is not None

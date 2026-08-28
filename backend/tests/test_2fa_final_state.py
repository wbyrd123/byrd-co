"""Post-test guard: both admin accounts must be able to log in with a full JWT (no 2FA lockout)."""
import os

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"


def test_admin_accounts_clean():
    db = MongoClient(be["MONGO_URL"])[be["DB_NAME"]]
    for email in ["wayne@byrd-co.com", "caleb@byrd-co.com"]:
        u = db.users.find_one({"email": email})
        assert not u.get("totp_enabled"), f"{email} still has 2FA enabled"
        assert not u.get("totp_secret"), f"{email} still has a totp_secret"
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": "byrdco2026"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("token"), r.json()
        assert r.json()["user"]["totp_enabled"] is False


def test_login_sets_no_session_cookie_localstorage_jwt_design():
    """Documents the current design: JWT is returned in the body (stored in localStorage),
    no httpOnly cookie is issued. Informational assertion only."""
    r = requests.post(f"{API}/auth/login",
                      json={"email": "wayne@byrd-co.com", "password": "byrdco2026"}, timeout=30)
    assert r.status_code == 200
    print("Set-Cookie header:", r.headers.get("set-cookie"))
    assert "token" in r.json()

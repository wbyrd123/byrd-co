"""Final state guard after 2FA email testing: no real account left enrolled; logins clean."""
import os

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"

ACCOUNTS = [
    ("wayne@byrd-co.com", "byrdco2026"),
    ("caleb@byrd-co.com", "byrdco2026"),
    ("sample@example.com", "sample123"),
    ("contact@testfrost.example", "testlender123"),
]


def test_all_accounts_2fa_off_and_login_clean():
    db = MongoClient(be["MONGO_URL"])[be["DB_NAME"]]
    for email, pwd in ACCOUNTS:
        u = db.users.find_one({"email": email})
        assert u, f"{email} missing"
        assert not u.get("totp_enabled"), f"{email} still has 2FA enabled"
        assert not u.get("totp_secret"), f"{email} still has totp_secret"
        assert not u.get("two_fa_method"), f"{email} still has two_fa_method"
        assert u["password_hash"].startswith("$2b$"), f"{email} hash format {u['password_hash'][:4]}"
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=30)
        assert r.status_code == 200, f"{email}: {r.status_code} {r.text[:200]}"
        assert r.json().get("token"), f"{email} did not get a full JWT"


def test_temp_test_user_removed():
    db = MongoClient(be["MONGO_URL"])[be["DB_NAME"]]
    assert db.users.find_one({"email": "test_2fa_email_user@byrd-co.com"}) is None

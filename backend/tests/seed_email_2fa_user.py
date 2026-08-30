"""Seed / remove a temporary email-primary 2FA user for frontend E2E. Usage: python seed_email_2fa_user.py [seed|clean]"""
import sys
import uuid
from datetime import datetime, timezone

import bcrypt
from dotenv import dotenv_values
from pymongo import MongoClient

be = dotenv_values("/app/backend/.env")
db = MongoClient(be["MONGO_URL"])[be["DB_NAME"]]

EMAIL = "test_2fa_email_user@byrd-co.com"
PASSWORD = "TestEmail2fa!23"
BACKUP = "abcd-1234"


def bh(s):
    return bcrypt.hashpw(s.encode(), bcrypt.gensalt()).decode()


def clean():
    u = db.users.find_one({"email": EMAIL})
    if u:
        db.two_fa_email_codes.delete_many({"user_id": u["id"]})
    print("deleted:", db.users.delete_many({"email": EMAIL}).deleted_count)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "seed"
    clean()
    if mode == "seed":
        uid = str(uuid.uuid4())
        db.users.insert_one({
            "id": uid, "email": EMAIL, "name": "TEST Email 2FA User", "role": "client",
            "status": "active", "password_hash": bh(PASSWORD),
            "totp_enabled": True, "two_fa_method": "email",
            "backup_codes": [bh(BACKUP)],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        print("seeded", uid)

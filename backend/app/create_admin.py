from getpass import getpass
import sys
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.core.security import hash_password
from app.database.mongo import create_mongo_client


def main() -> int:
    settings = get_settings()
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip().lower()
    password = getpass("Admin password (minimum 8 characters): ")
    if len(name) < 2 or len(password) < 8:
        print("Name must have at least 2 characters and password at least 8.", file=sys.stderr)
        return 1

    client = create_mongo_client(settings.mongodb_uri)
    try:
        users = client[settings.mongodb_database]["users"]
        users.create_index("email", unique=True)
        now = datetime.now(timezone.utc)
        users.insert_one({
            "name": name,
            "email": email,
            "password_hash": hash_password(password),
            "role": "admin",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        })
    except DuplicateKeyError:
        print("An account with this email already exists.", file=sys.stderr)
        return 1
    finally:
        client.close()

    print(f"Admin account created for {email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from copy import deepcopy

from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.main import create_app


class FakeUsers:
    def __init__(self):
        self.documents = []

    def create_index(self, field, unique=False):
        assert field == "email"
        assert unique

    def insert_one(self, document):
        if any(user["email"] == document["email"] for user in self.documents):
            raise DuplicateKeyError("duplicate email")
        stored = deepcopy(document)
        stored["_id"] = ObjectId()
        self.documents.append(stored)
        return type("InsertResult", (), {"inserted_id": stored["_id"]})()

    def find_one(self, query):
        return next(
            (
                deepcopy(user)
                for user in self.documents
                if all(user.get(key) == value for key, value in query.items())
            ),
            None,
        )

    def find(self, query, projection):
        assert projection == {"password_hash": 0}
        return FakeCursor(self.documents)

    def find_one_and_update(self, query, update, return_document):
        user = self.find_one(query)
        if user is None:
            return None
        stored = next(user for user in self.documents if user["_id"] == query["_id"])
        stored.update(update["$set"])
        return deepcopy(stored)


class FakeCursor:
    def __init__(self, users):
        self.users = [deepcopy(user) for user in users]

    def sort(self, field, direction):
        self.users.sort(key=lambda user: user[field], reverse=direction < 0)
        return self

    def skip(self, count):
        self.users = self.users[count:]
        return self

    def limit(self, count):
        self.users = self.users[:count]
        return self

    def __iter__(self):
        return iter(self.users)


class FakeDatabase:
    def __init__(self, users):
        self.users = users

    def __getitem__(self, collection_name):
        assert collection_name == "users"
        return self.users


class FakeMongoClient:
    def __init__(self):
        self.users = FakeUsers()
        self.database = FakeDatabase(self.users)

    def __getitem__(self, database_name):
        assert database_name == "nexusai"
        return self.database

    def close(self):
        pass


def build_test_client(monkeypatch):
    mongo = FakeMongoClient()
    monkeypatch.setattr("app.main.create_mongo_client", lambda uri: mongo)
    app = create_app(Settings(jwt_secret_key="test-signing-secret-with-32-bytes-minimum"))
    return TestClient(app), mongo


def test_register_creates_customer_and_sets_http_only_session(monkeypatch):
    client, mongo = build_test_client(monkeypatch)

    with client:
        response = client.post(
            "/api/auth/register",
            json={
                "name": "  Alex Support  ",
                "email": "ALEX@example.com",
                "password": "secure-passphrase",
            },
        )

        assert response.status_code == 201
        assert response.json()["user"]["role"] == "customer"
        assert response.json()["user"]["name"] == "Alex Support"
        assert "password_hash" not in response.json()["user"]
        assert "httponly" in response.headers["set-cookie"].lower()

        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "alex@example.com"

    stored = mongo.users.documents[0]
    assert stored["role"] == "customer"
    assert stored["password_hash"] != "secure-passphrase"


def test_registration_rejects_role_escalation_and_duplicate_email(monkeypatch):
    client, _ = build_test_client(monkeypatch)
    with client:
        payload = {
            "name": "Alex",
            "email": "alex@example.com",
            "password": "secure-passphrase",
        }
        escalated = client.post("/api/auth/register", json={**payload, "role": "admin"})
        assert escalated.status_code == 422

        assert client.post("/api/auth/register", json=payload).status_code == 201
        duplicate = client.post("/api/auth/register", json=payload)
        assert duplicate.status_code == 409


def test_login_rejects_wrong_password_and_requires_session(monkeypatch):
    client, _ = build_test_client(monkeypatch)
    with client:
        client.post(
            "/api/auth/register",
            json={
                "name": "Alex",
                "email": "alex@example.com",
                "password": "secure-passphrase",
            },
        )
        client.post("/api/auth/logout")

        wrong_password = client.post(
            "/api/auth/login",
            json={"email": "alex@example.com", "password": "wrong-password"},
        )
        assert wrong_password.status_code == 401
        assert client.get("/api/auth/me").status_code == 401

        login = client.post(
            "/api/auth/login",
            json={"email": "alex@example.com", "password": "secure-passphrase"},
        )
        assert login.status_code == 200
        assert client.get("/api/auth/me").status_code == 200


def test_production_settings_require_a_jwt_secret():
    try:
        Settings(app_env="production")
    except ValueError as exc:
        assert "JWT_SECRET_KEY" in str(exc)
    else:
        raise AssertionError("Production settings must reject a missing JWT secret")


def test_production_settings_reject_wildcard_cors_origins():
    try:
        Settings(
            app_env="production",
            jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
            cors_origins="*",
        )
    except ValueError as exc:
        assert "explicit trusted origins" in str(exc)
    else:
        raise AssertionError("Production settings must reject wildcard CORS")


def test_user_access_is_role_protected_and_admin_can_update_role(monkeypatch):
    client, mongo = build_test_client(monkeypatch)
    with client:
        registered = client.post(
            "/api/auth/register",
            json={
                "name": "Alex",
                "email": "alex@example.com",
                "password": "secure-passphrase",
            },
        )
        user_id = registered.json()["user"]["id"]
        assert client.get("/api/users").status_code == 403
        assert client.get(f"/api/users/{user_id}").status_code == 200

        mongo.users.documents[0]["role"] = "admin"
        listing = client.get("/api/users")
        assert listing.status_code == 200
        assert len(listing.json()) == 1
        assert "password_hash" not in listing.text

        changed = client.patch(f"/api/users/{user_id}", json={"role": "agent"})
        assert changed.status_code == 200
        assert changed.json()["role"] == "agent"
        assert client.get("/api/users").status_code == 403

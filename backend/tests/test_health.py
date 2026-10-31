from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.core.config import Settings
from app.main import create_app


class FakeMongoClient:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.admin = self
        self.closed = False

    def command(self, name: str) -> dict[str, int]:
        assert name == "ping"
        if self.should_fail:
            raise ServerSelectionTimeoutError("MongoDB is unavailable")
        return {"ok": 1}

    def close(self) -> None:
        self.closed = True


def test_health_returns_connected_when_mongodb_is_available(monkeypatch):
    client = FakeMongoClient()
    monkeypatch.setattr("app.main.create_mongo_client", lambda uri: client)
    app = create_app(Settings())

    with TestClient(app) as test_client:
        response = test_client.get("/api/health")
        live = test_client.get("/api/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert client.closed


def test_health_returns_service_unavailable_when_mongodb_is_unavailable(monkeypatch):
    client = FakeMongoClient(should_fail=True)
    monkeypatch.setattr("app.main.create_mongo_client", lambda uri: client)
    app = create_app(Settings())

    with TestClient(app) as test_client:
        response = test_client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "status": "degraded",
        "database": "unavailable",
    }

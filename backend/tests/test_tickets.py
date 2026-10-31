import re
import json
import pymupdf as fitz
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.ai.provider import ChatReply, TicketClassification
from app.core.config import Settings
from app.core.security import hash_password
from app.main import create_app


def matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(document, option) for option in expected):
                return False
        elif key == "$and":
            if not all(matches(document, option) for option in expected):
                return False
        elif isinstance(expected, dict) and any(str(operator).startswith("$") for operator in expected):
            value = document.get(key)
            for operator, condition in expected.items():
                if operator == "$regex":
                    if value is None or re.search(condition, str(value), re.IGNORECASE) is None:
                        return False
                elif operator == "$gte" and (value is None or value < condition):
                    return False
                elif operator == "$lte" and (value is None or value > condition):
                    return False
                elif operator == "$ne" and value == condition:
                    return False
        elif document.get(key) != expected:
            return False
    return True


class Cursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]

    def sort(self, key, direction):
        if isinstance(key, list):
            key, direction = key[0]
        self.documents.sort(key=lambda document: document.get(key), reverse=direction < 0)
        return self

    def skip(self, count):
        self.documents = self.documents[count:]
        return self

    def limit(self, count):
        self.documents = self.documents[:count]
        return self

    def __iter__(self):
        return iter(self.documents)


class Collection:
    def __init__(self):
        self.documents = []

    def create_index(self, *args, **kwargs):
        return "index"

    def insert_one(self, document):
        stored = deepcopy(document)
        stored.setdefault("_id", ObjectId())
        self.documents.append(stored)
        return type("InsertResult", (), {"inserted_id": stored["_id"]})()

    def find_one(self, query):
        return next((deepcopy(item) for item in self.documents if matches(item, query)), None)

    def find(self, query=None, projection=None):
        query = query or {}
        found = [item for item in self.documents if matches(item, query)]
        if projection and "password_hash" in projection and projection["password_hash"] == 0:
            found = [{key: value for key, value in item.items() if key != "password_hash"} for item in found]
        return Cursor(found)

    def count_documents(self, query):
        return sum(1 for item in self.documents if matches(item, query))

    def update_one(self, query, update, upsert=False):
        current = next((item for item in self.documents if matches(item, query)), None)
        if current is None:
            if upsert:
                current = deepcopy(query)
                current.update(deepcopy(update.get("$setOnInsert", {})))
                current.setdefault("_id", ObjectId())
                self.documents.append(current)
            else:
                return type("UpdateResult", (), {"matched_count": 0})()
        current.update(deepcopy(update.get("$set", {})))
        for field, amount in update.get("$inc", {}).items():
            current[field] = current.get(field, 0) + amount
        for field, push in update.get("$push", {}).items():
            if isinstance(push, dict) and "$each" in push:
                values = current.setdefault(field, []) + deepcopy(push["$each"])
                if "$slice" in push:
                    count = push["$slice"]
                    values = values[count:] if count < 0 else values[:count]
                current[field] = values
            else:
                current.setdefault(field, []).append(deepcopy(push))
        return type("UpdateResult", (), {"matched_count": 1})()

    def find_one_and_update(self, query, update, upsert=False, return_document=None):
        self.update_one(query, update, upsert=upsert)
        return self.find_one(query)

    def delete_one(self, query):
        for index, item in enumerate(self.documents):
            if matches(item, query):
                del self.documents[index]
                return type("DeleteResult", (), {"deleted_count": 1})()
        return type("DeleteResult", (), {"deleted_count": 0})()

    def delete_many(self, query):
        kept = [item for item in self.documents if not matches(item, query)]
        deleted = len(self.documents) - len(kept)
        self.documents = kept
        return type("DeleteResult", (), {"deleted_count": deleted})()

    def update_many(self, query, update):
        count = 0
        for item in self.documents:
            if matches(item, query):
                item.update(deepcopy(update.get("$set", {})))
                count += 1
        return type("UpdateResult", (), {"matched_count": count})()

    def insert_many(self, documents):
        ids = []
        for document in documents:
            ids.append(self.insert_one(document).inserted_id)
        return type("InsertManyResult", (), {"inserted_ids": ids})()


class Database:
    def __init__(self):
        self.tables = {}

    def __getitem__(self, name):
        if name not in self.tables:
            self.tables[name] = Collection()
        return self.tables[name]


class Mongo:
    def __init__(self):
        self.database = Database()

    def __getitem__(self, name):
        assert name == "nexusai"
        return self.database

    def close(self):
        pass


@pytest.fixture
def ticket_clients(monkeypatch):
    mongo = Mongo()
    monkeypatch.setattr("app.main.create_mongo_client", lambda uri: mongo)
    app = create_app(Settings(jwt_secret_key="test-signing-secret-with-32-bytes-minimum"))
    customer = TestClient(app)
    agent = TestClient(app)
    customer.__enter__()
    agent.__enter__()
    agent_user = {
        "name": "Agent One",
        "email": "agent@example.com",
        "password_hash": hash_password("agent-password"),
        "role": "agent",
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    mongo.database["users"].insert_one(agent_user)
    customer.post(
        "/api/auth/register",
        json={"name": "Customer One", "email": "customer@example.com", "password": "customer-password"},
    )
    agent.post("/api/auth/login", json={"email": "agent@example.com", "password": "agent-password"})
    yield customer, agent, mongo
    customer.__exit__(None, None, None)
    agent.__exit__(None, None, None)


@pytest.fixture
def admin_client(ticket_clients):
    customer, _, mongo = ticket_clients
    mongo.database["users"].insert_one({
        "name": "Admin User",
        "email": "admin@example.com",
        "password_hash": hash_password("admin-password"),
        "role": "admin",
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    client = TestClient(customer.app)
    client.__enter__()
    client.post("/api/auth/login", json={"email": "admin@example.com", "password": "admin-password"})
    yield client, customer, mongo
    client.__exit__(None, None, None)


def create_ticket(client, subject="Unable to sign in"):
    return client.post(
        "/api/tickets",
        json={
            "subject": subject,
            "description": "I cannot access my account after resetting the password.",
            "category": "account",
            "priority": "high",
            "tags": ["login", "Login"],
        },
    )


def test_ticket_creation_and_server_side_search_pagination(ticket_clients):
    customer, _, _ = ticket_clients
    first = create_ticket(customer)
    second = create_ticket(customer, "Invoice question")
    assert first.status_code == 201
    assert first.json()["ticket_number"] == "NEX-10001"
    assert second.json()["ticket_number"] == "NEX-10002"
    assert first.json()["tags"] == ["login"]
    assert first.json()["ai_classification"] == {"status": "pending"}

    page = customer.get("/api/tickets?search=NEX-10001&skip=0&limit=1")
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["id"] == first.json()["id"]

    filtered = customer.get("/api/tickets?priority=high&category=account&skip=1&limit=1")
    assert filtered.json()["total"] == 2
    assert len(filtered.json()["items"]) == 1
    assert customer.get("/api/tickets?skip=-1").status_code == 422


def test_customer_ownership_and_staff_assignment_status_updates(ticket_clients):
    customer, agent, _ = ticket_clients
    ticket = create_ticket(customer).json()
    ticket_id = ticket["id"]

    assert customer.get(f"/api/tickets/{ticket_id}").status_code == 200
    assert customer.patch(f"/api/tickets/{ticket_id}/assign", json={"agent_id": None}).status_code == 403
    assert agent.get("/api/tickets").json()["total"] == 1
    claim = agent.patch(f"/api/tickets/{ticket_id}/assign", json={"agent_id": agent.get('/api/auth/me').json()['id']})
    assert claim.status_code == 200
    assert claim.json()["assigned_agent_name"] == "Agent One"
    status_result = agent.patch(f"/api/tickets/{ticket_id}/status", json={"status": "in_progress"})
    assert status_result.status_code == 200
    assert status_result.json()["status"] == "in_progress"
    assert agent.get(f"/api/tickets/{ticket_id}/history").json()[-1]["action"] == "status_changed"
    assert agent.get("/api/tickets?agent_id=unassigned").json()["total"] == 0


def test_internal_notes_are_never_returned_to_customers(ticket_clients):
    customer, agent, _ = ticket_clients
    ticket = create_ticket(customer).json()
    ticket_id = ticket["id"]
    agent_id = agent.get("/api/auth/me").json()["id"]
    assert agent.patch(f"/api/tickets/{ticket_id}/assign", json={"agent_id": agent_id}).status_code == 200

    public_reply = customer.post(
        f"/api/tickets/{ticket_id}/messages",
        json={"content": "Please let me know when this is fixed."},
    )
    assert public_reply.status_code == 201
    note = agent.post(
        f"/api/tickets/{ticket_id}/internal-notes",
        json={"content": "Check the account recovery logs internally."},
    )
    assert note.status_code == 201
    assert any(message["is_internal"] for message in note.json()["messages"])

    customer_view = customer.get(f"/api/tickets/{ticket_id}")
    assert customer_view.status_code == 200
    assert all(not message["is_internal"] for message in customer_view.json()["messages"])
    assert "Check the account recovery logs internally." not in customer_view.text
    customer_thread = customer.get(f"/api/tickets/{ticket_id}/messages?skip=0&limit=10")
    assert customer_thread.status_code == 200
    assert customer_thread.json()["total"] == 1
    assert all(not message["is_internal"] for message in customer_thread.json()["items"])
    staff_thread = agent.get(f"/api/tickets/{ticket_id}/messages?skip=0&limit=10")
    assert staff_thread.json()["total"] == 2
    assert all(event["action"] != "internal_note" for event in customer.get(f"/api/tickets/{ticket_id}/history").json())

    denied = customer.post(
        f"/api/tickets/{ticket_id}/internal-notes",
        json={"content": "Not allowed"},
    )
    assert denied.status_code == 403
    assert customer.get("/api/ai/status").status_code == 403
    assert customer.post(f"/api/ai/tickets/{ticket_id}/suggest-response").status_code == 403


def test_other_customer_cannot_read_ticket(ticket_clients):
    customer, _, mongo = ticket_clients
    ticket = create_ticket(customer).json()
    other_user = {
        "name": "Other Customer",
        "email": "other@example.com",
        "password_hash": hash_password("other-password"),
        "role": "customer",
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    mongo.database["users"].insert_one(other_user)
    other_client = TestClient(customer.app)
    other_client.post("/api/auth/login", json={"email": "other@example.com", "password": "other-password"})
    assert other_client.get(f"/api/tickets/{ticket['id']}").status_code == 404


def test_agent_can_reassign_own_ticket_but_not_take_another_agents_ticket(ticket_clients):
    customer, agent, mongo = ticket_clients
    ticket = create_ticket(customer).json()
    agent_id = agent.get("/api/auth/me").json()["id"]
    agent.patch(f"/api/tickets/{ticket['id']}/assign", json={"agent_id": agent_id})

    second_agent = mongo.database["users"].insert_one({
        "name": "Agent Two",
        "email": "agent2@example.com",
        "password_hash": hash_password("second-agent-password"),
        "role": "agent",
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }).inserted_id
    reassigned = agent.patch(
        f"/api/tickets/{ticket['id']}/assign",
        json={"agent_id": str(second_agent)},
    )
    assert reassigned.status_code == 200
    assert reassigned.json()["assigned_agent_name"] == "Agent Two"
    assert agent.get(f"/api/tickets/{ticket['id']}").status_code == 404


def test_ticket_update_validates_payload_and_records_priority_change(ticket_clients):
    customer, agent, _ = ticket_clients
    ticket = create_ticket(customer).json()
    agent_id = agent.get("/api/auth/me").json()["id"]
    agent.patch(f"/api/tickets/{ticket['id']}/assign", json={"agent_id": agent_id})

    changed = agent.patch(f"/api/tickets/{ticket['id']}", json={"priority": "critical"})
    assert changed.status_code == 200
    assert changed.json()["priority"] == "critical"
    history = agent.get(f"/api/tickets/{ticket['id']}/history").json()
    assert any(event["action"] == "priority_changed" for event in history)


def test_configured_ai_classifies_suggests_and_summarizes_without_sending(ticket_clients, monkeypatch):
    customer, agent, _ = ticket_clients
    agent.app.state.settings = Settings(
        jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
        llm_api_base_url="https://llm.example/v1",
        llm_api_key="test-api-key",
        llm_model="test-model",
    )

    def fake_post(url, **kwargs):
        system_prompt = kwargs["json"]["messages"][0]["content"]
        if system_prompt.startswith("Classify support tickets"):
            result = {
                "category": "account",
                "priority": "critical",
                "summary": "Customer cannot sign into their account.",
                "confidence": 0.95,
            }
        elif system_prompt.startswith("Draft one concise"):
            result = {"suggestion": "I can help investigate the sign-in issue. Could you share the error shown?"}
        else:
            result = {
                "main_issue": "The customer cannot sign in.",
                "steps_attempted": ["Reset the password"],
                "current_status": "Open; awaiting agent follow-up.",
                "recommended_next_action": "Check the account recovery logs.",
            }

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": json.dumps(result)}}]}

        return FakeResponse()

    monkeypatch.setattr("app.ai.provider.httpx.post", fake_post)
    ticket_response = create_ticket(customer)
    assert ticket_response.status_code == 201
    ticket = ticket_response.json()
    assert ticket["ai_classification"]["status"] == "complete"
    assert ticket["category"] == "account"
    assert ticket["priority"] == "critical"

    agent_id = agent.get("/api/auth/me").json()["id"]
    agent.patch(f"/api/tickets/{ticket['id']}/assign", json={"agent_id": agent_id})
    before = agent.get(f"/api/tickets/{ticket['id']}/messages").json()["total"]
    suggestion = agent.post(f"/api/ai/tickets/{ticket['id']}/suggest-response")
    summary = agent.post(f"/api/ai/tickets/{ticket['id']}/summarize")
    assert suggestion.status_code == 200
    assert "Could you share the error" in suggestion.json()["suggestion"]
    assert summary.status_code == 200
    assert summary.json()["steps_attempted"] == ["Reset the password"]
    assert agent.get(f"/api/tickets/{ticket['id']}/messages").json()["total"] == before


def test_customer_chat_persists_only_own_conversation_and_uses_bounded_context(ticket_clients, monkeypatch):
    customer, _, mongo = ticket_clients
    customer.app.state.settings = Settings(
        jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
        llm_api_base_url="https://llm.example/v1",
        llm_api_key="test-api-key",
        llm_model="test-model",
    )
    captured = []
    sources = [{
        "chunk_id": str(ObjectId()),
        "document_id": str(ObjectId()),
        "filename": "refund-policy.pdf",
        "page_number": 2,
        "text": "Refunds are available within 30 days.",
        "score": 0.9,
    }]

    def answer(self, question, conversation, context):
        captured.append((question, conversation, context))
        return type("Reply", (), {
            "answer": "Refunds are available within 30 days.",
            "needs_human": False,
        })()

    monkeypatch.setattr("app.api.ai.search_knowledge", lambda *args: (sources, "keyword_fallback"))
    monkeypatch.setattr("app.api.ai.LLMProvider.answer_with_knowledge", answer)
    first = customer.post("/api/ai/chat", json={"content": "Can you check my account?"})
    assert first.status_code == 200
    assert first.json()["needs_human"] is False
    assert [message["role"] for message in first.json()["messages"]] == ["user", "assistant"]
    assert captured[0][0:2] == ("Can you check my account?", [])
    assert captured[0][2] == sources
    assert first.json()["messages"][1]["sources"][0]["filename"] == "refund-policy.pdf"
    assert "text" not in first.json()["messages"][1]["sources"][0]

    follow_up = customer.post("/api/ai/chat", json={"content": "What did I ask you before?"})
    assert follow_up.status_code == 200
    assert len(captured[1][1]) == 2
    assert captured[1][1][0]["content"] == "Can you check my account?"
    for index in range(7):
        response = customer.post("/api/ai/chat", json={"content": f"Follow-up question {index}?"})
        assert response.status_code == 200
    assert len(captured[-1][1]) == 12
    own_history = customer.get("/api/ai/chat")
    assert len(own_history.json()["messages"]) == 18
    assert own_history.json()["ai_available"] is True

    other = TestClient(customer.app)
    other.post(
        "/api/auth/register",
        json={"name": "Other Chat User", "email": "other-chat@example.com", "password": "other-password"},
    )
    assert other.get("/api/ai/chat").json()["messages"] == []

    deleted = customer.delete("/api/ai/chat")
    assert deleted.status_code == 204
    assert customer.get("/api/ai/chat").json()["messages"] == []


def test_customer_chat_provider_failure_does_not_save_unanswered_turn(ticket_clients, monkeypatch):
    customer, _, _ = ticket_clients
    customer.app.state.settings = Settings(
        jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
        llm_api_base_url="https://llm.example/v1",
        llm_api_key="test-api-key",
        llm_model="test-model",
    )

    def fail(*args):
        from app.ai.provider import AIProviderError
        raise AIProviderError("provider unavailable")

    monkeypatch.setattr("app.api.ai.search_knowledge", fail)
    response = customer.post("/api/ai/chat", json={"content": "I need help with billing."})
    assert response.status_code == 502
    assert customer.get("/api/ai/chat").json()["messages"] == []


def test_customer_chat_rate_limit_and_human_escalation(ticket_clients, monkeypatch):
    customer, _, mongo = ticket_clients
    customer.app.state.settings = Settings(
        jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
        llm_api_base_url="https://llm.example/v1",
        llm_api_key="test-api-key",
        llm_model="test-model",
    )
    monkeypatch.setattr("app.api.ai.search_knowledge", lambda *args: ([], "keyword_fallback"))
    for index in range(10):
        result = customer.post("/api/ai/chat", json={"content": f"My account issue number {index}."})
        assert result.status_code == 200
    limited = customer.post("/api/ai/chat", json={"content": "Another account question."})
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers

    session = mongo.database["ai_chat_sessions"].find_one({"_id": ObjectId(customer.get("/api/auth/me").json()["id"])})
    assert len(session["messages"]) == 20
    customer.app.state.settings = Settings(jwt_secret_key="test-signing-secret-with-32-bytes-minimum")
    escalation = customer.post("/api/ai/chat/escalate", json={})
    assert escalation.status_code == 201
    ticket = escalation.json()["ticket"]
    assert ticket["subject"] == "My account issue number 9."
    assert ticket["status"] == "open"
    assert "My account issue number 0." in ticket["description"]
    assert "My account issue number 9." in ticket["description"]


def test_customer_chat_no_retrieved_evidence_is_honest_and_offers_escalation(ticket_clients):
    customer, _, _ = ticket_clients
    customer.app.state.settings = Settings(
        jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
        llm_api_base_url="https://llm.example/v1",
        llm_api_key="test-api-key",
        llm_model="test-model",
    )
    response = customer.post("/api/ai/chat", json={"content": "What is the company's refund deadline?"})
    assert response.status_code == 200
    assistant = response.json()["messages"][-1]
    assert "couldn't find supporting information" in assistant["content"]
    assert assistant["sources"] == []
    assert response.json()["needs_human"] is True


def _create_pdf(text):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((50, 50), text)
    content = pdf.tobytes()
    pdf.close()
    return content


def _configure_knowledge_admin(admin, monkeypatch, **settings_overrides):
    admin.app.state.settings = Settings(
        jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
        llm_api_base_url="https://llm.example/v1",
        llm_api_key="test-api-key",
        llm_model="test-model",
        embedding_dimensions=2,
        knowledge_chunk_size=100,
        knowledge_chunk_overlap=20,
        **settings_overrides,
    )
    monkeypatch.setattr(
        "app.ai.provider.LLMProvider.embed_texts",
        lambda self, texts: [[0.1, 0.2] for _ in texts],
    )


def test_admin_pdf_upload_extracts_chunks_retrieves_sources_and_deactivates(admin_client, monkeypatch):
    admin, customer, mongo = admin_client
    _configure_knowledge_admin(admin, monkeypatch, knowledge_tenant_id="tenant-one")
    stored = {}

    def store_source(database, content, filename, document_type):
        source_id = ObjectId()
        stored[source_id] = content
        return source_id

    monkeypatch.setattr("app.api.knowledge._store_source", store_source)
    response = admin.post(
        "/api/knowledge/upload",
        files={"file": ("..\\private\\refunds.pdf", _create_pdf("Refunds are available within 30 days for unused products."), "application/pdf")},
    )
    assert response.status_code == 201
    document = response.json()
    assert document["filename"] == "refunds.pdf"
    assert document["status"] == "ready"
    assert document["chunk_count"] == 1

    chunks = mongo.database["knowledge_chunks"].find({"document_id": ObjectId(document["id"])})
    chunk = list(chunks)[0]
    assert chunk["page_number"] == 1
    assert chunk["embedding"] == [0.1, 0.2]

    result = admin.post("/api/knowledge/search", json={"query": "What is the refund period?"})
    assert result.status_code == 200
    assert result.json()["mode"] == "keyword_fallback"
    assert result.json()["sources"][0]["filename"] == "refunds.pdf"
    assert result.json()["sources"][0]["page_number"] == 1

    mongo.database["knowledge_chunks"].insert_one({
        "document_id": ObjectId(),
        "tenant_id": "tenant-two",
        "is_active": True,
        "chunk_order": 0,
        "page_number": 1,
        "text": "Refund period is 365 days.",
        "embedding": [0.3, 0.4],
        "metadata": {"filename": "other-tenant.pdf"},
    })
    scoped = admin.post("/api/knowledge/search", json={"query": "refund period"})
    assert len(scoped.json()["sources"]) == 1
    assert scoped.json()["sources"][0]["filename"] == "refunds.pdf"

    assert customer.get("/api/knowledge").status_code == 403
    assert customer.post("/api/knowledge/search", json={"query": "refund period"}).status_code == 403
    deactivated = admin.delete(f"/api/knowledge/{document['id']}")
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "inactive"
    no_results = admin.post("/api/knowledge/search", json={"query": "refund period"})
    assert no_results.json()["sources"] == []
    assert admin.get("/api/knowledge").json()["total"] == 0
    assert admin.get("/api/knowledge?include_inactive=true").json()["total"] == 1


def test_pdf_upload_rejects_fake_pdf_signature_and_customers_cannot_upload(admin_client):
    admin, customer, _ = admin_client
    invalid = admin.post("/api/knowledge/upload", files={"file": ("fake.pdf", b"not a pdf document", "application/pdf")})
    assert invalid.status_code == 422
    denied = customer.post("/api/knowledge/upload", files={"file": ("fake.pdf", b"not a pdf", "application/pdf")})
    assert denied.status_code == 403


def test_article_creation_and_reprocessing_replaces_old_chunks(admin_client, monkeypatch):
    admin, _, mongo = admin_client
    _configure_knowledge_admin(admin, monkeypatch)
    stored = {}

    def store_source(database, content, filename, document_type):
        source_id = ObjectId()
        stored[source_id] = content
        return source_id

    class FakeBucket:
        def __init__(self, database, bucket_name):
            pass

        def open_download_stream(self, file_id):
            return type("Download", (), {"read": lambda self: stored[file_id]})()

    monkeypatch.setattr("app.api.knowledge._store_source", store_source)
    monkeypatch.setattr("app.api.knowledge.GridFSBucket", FakeBucket)
    response = admin.post(
        "/api/knowledge/articles",
        json={"title": "Account access", "content": "Customers can reset passwords using the account recovery page."},
    )
    assert response.status_code == 201
    document = response.json()
    assert document["document_type"] == "article"
    assert document["status"] == "ready"
    assert mongo.database["knowledge_chunks"].count_documents({"document_id": ObjectId(document["id"])}) == 1
    admin.delete(f"/api/knowledge/{document['id']}")
    indexed = admin.post(f"/api/knowledge/{document['id']}/reprocess")
    assert indexed.status_code == 200
    assert indexed.json()["status"] == "ready"
    assert mongo.database["knowledge_chunks"].count_documents({"document_id": ObjectId(document["id"])}) == 1
    assert mongo.database["knowledge_chunks"].find_one({"document_id": ObjectId(document["id"])})["is_active"] is True


def test_production_state_changing_requests_require_an_allowed_origin(admin_client):
    admin, _, _ = admin_client
    admin.app.state.settings.app_env = "production"
    admin.app.state.settings.cors_origins = "https://app.example"
    path = "/api/knowledge/invalid-id/reprocess"

    no_origin = admin.post(path)
    assert no_origin.status_code == 403
    evil_origin = admin.post(path, headers={"Origin": "https://attacker.example"})
    assert evil_origin.status_code == 403
    allowed_origin = admin.post(path, headers={"Origin": "https://app.example"})
    assert allowed_origin.status_code == 404


def test_end_to_end_customer_agent_admin_and_rag_workflow(admin_client, monkeypatch):
    admin, customer, mongo = admin_client
    settings = Settings(
        jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
        llm_api_base_url="https://llm.example/v1",
        llm_api_key="test-api-key",
        llm_model="test-model",
        embedding_dimensions=2,
        knowledge_chunk_size=400,
        knowledge_chunk_overlap=40,
        knowledge_tenant_id="demo-tenant",
    )
    admin.app.state.settings = settings
    monkeypatch.setattr(
        "app.api.tickets.LLMProvider.classify_ticket",
        lambda self, subject, description: TicketClassification(
            category="billing",
            priority="high",
            summary="Customer asks about a refund.",
            confidence=0.98,
        ),
    )
    monkeypatch.setattr(
        "app.api.ai.LLMProvider.suggest_response",
        lambda self, subject, description, conversation: "A human-reviewed refund response draft.",
    )
    monkeypatch.setattr(
        "app.api.knowledge._store_source",
        lambda database, source, filename, document_type: ObjectId(),
    )
    monkeypatch.setattr(
        "app.ai.provider.LLMProvider.embed_texts",
        lambda self, texts: [[0.1, 0.2] for _ in texts],
    )
    agent = TestClient(admin.app)
    agent.post("/api/auth/login", json={"email": "agent@example.com", "password": "agent-password"})

    created = customer.post("/api/tickets", json={
        "subject": "Refund timing",
        "description": "I need to know how long a refund takes to arrive.",
        "category": "general_support",
        "priority": "medium",
        "tags": [],
    })
    assert created.status_code == 201
    ticket = created.json()
    assert ticket["ai_classification"]["status"] == "complete"
    assert ticket["ticket_number"].startswith("NEX-")
    assert customer.get(f"/api/tickets/{ticket['id']}").status_code == 200

    agent_ticket = next(item for item in agent.get("/api/tickets").json()["items"] if item["id"] == ticket["id"])
    assert agent_ticket["subject"] == "Refund timing"
    agent_id = agent.get("/api/auth/me").json()["id"]
    assigned = agent.patch(f"/api/tickets/{ticket['id']}/assign", json={"agent_id": agent_id})
    assert assigned.status_code == 200
    reply = agent.post(
        f"/api/tickets/{ticket['id']}/messages",
        json={"content": "Please share your order reference so we can check this."},
    )
    assert reply.status_code == 201
    internal = agent.post(
        f"/api/tickets/{ticket['id']}/internal-notes",
        json={"content": "Internal: review refund request."},
    )
    assert internal.status_code == 201
    customer_thread = customer.get(f"/api/tickets/{ticket['id']}/messages")
    assert "Please share your order reference" in customer_thread.text
    assert "Internal: review refund request" not in customer_thread.text

    admin_users = admin.get("/api/users")
    assert admin_users.status_code == 200
    assert any(user["email"] == "agent@example.com" for user in admin_users.json())
    assert "password_hash" not in admin_users.text
    assert admin.get(f"/api/tickets/{ticket['id']}").status_code == 200

    message_count = customer_thread.json()["total"]
    draft = agent.post(f"/api/ai/tickets/{ticket['id']}/suggest-response")
    assert draft.status_code == 200
    assert customer.get(f"/api/tickets/{ticket['id']}/messages").json()["total"] == message_count

    upload = admin.post(
        "/api/knowledge/upload",
        files={"file": (
            "refund-policy.pdf",
            _create_pdf("Refund requests are processed within 5 business days after approval."),
            "application/pdf",
        )},
    )
    assert upload.status_code == 201
    assert upload.json()["status"] == "ready"

    captured = {}

    def grounded_answer(self, question, conversation, context):
        captured["context"] = context
        return ChatReply(
            answer="Approved refunds are processed within 5 business days.",
            needs_human=False,
        )

    monkeypatch.setattr("app.api.ai.LLMProvider.answer_with_knowledge", grounded_answer)
    chat = customer.post("/api/ai/chat", json={"content": "How many business days are refund requests processed?"})
    assert chat.status_code == 200
    assistant = chat.json()["messages"][-1]
    assert assistant["content"] == "Approved refunds are processed within 5 business days."
    assert assistant["sources"][0]["filename"] == "refund-policy.pdf"
    assert assistant["sources"][0]["page_number"] == 1
    assert captured["context"][0]["text"].find("5 business days") >= 0
    stored_ticket = mongo.database["tickets"].find_one({"_id": ObjectId(ticket["id"])})
    assert stored_ticket["ai_classification"]["status"] == "complete"

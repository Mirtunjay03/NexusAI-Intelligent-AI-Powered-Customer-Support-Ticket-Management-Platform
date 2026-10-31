import pytest
from pymongo.errors import OperationFailure

from app.ai.knowledge import search_knowledge, split_pages, split_text
from app.core.config import Settings


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def limit(self, count):
        return self.documents[:count]

    def __iter__(self):
        return iter(self.documents)


class FakeChunks:
    def __init__(self, documents=None, vector_results=None):
        self.documents = documents or []
        self.vector_results = vector_results or []
        self.pipeline = None
        self.aggregate_error = None

    def find(self, query):
        tenant = query["tenant_id"]
        return FakeCursor([
            item for item in self.documents
            if item.get("is_active") and item.get("tenant_id") == tenant
        ])

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        if self.aggregate_error:
            raise self.aggregate_error
        return iter(self.vector_results)


class FakeDatabase:
    def __init__(self, chunks):
        self.chunks = chunks

    def __getitem__(self, collection):
        assert collection == "knowledge_chunks"
        return self.chunks


def test_chunking_normalizes_text_and_keeps_page_metadata():
    chunks = split_pages(
        [(1, "  Refunds   are allowed. " * 20), (2, "Contact support for details.")],
        chunk_size=80,
        overlap=15,
    )
    assert len(chunks) > 2
    assert chunks[0]["page_number"] == 1
    assert chunks[-1]["page_number"] == 2
    assert [item["chunk_order"] for item in chunks] == list(range(len(chunks)))
    assert all("\n" not in item["text"] for item in chunks)
    assert split_text("  \n ", 100, 10) == []


def test_keyword_fallback_is_tenant_scoped_and_labels_mode():
    chunks = FakeChunks(documents=[
        {
            "_id": "chunk-1",
            "document_id": "doc-1",
            "tenant_id": "tenant-a",
            "is_active": True,
            "chunk_order": 0,
            "page_number": 3,
            "text": "Refunds are available within 30 days.",
            "metadata": {"filename": "refund-policy.pdf"},
        },
        {
            "_id": "chunk-2",
            "document_id": "doc-2",
            "tenant_id": "tenant-b",
            "is_active": True,
            "chunk_order": 0,
            "page_number": 1,
            "text": "Refunds are available within 365 days.",
            "metadata": {"filename": "private-policy.pdf"},
        },
    ])
    settings = Settings(
        jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
        knowledge_tenant_id="tenant-a",
    )
    results, mode = search_knowledge(FakeDatabase(chunks), None, settings, "When is the refund period?")
    assert mode == "keyword_fallback"
    assert len(results) == 1
    assert results[0]["filename"] == "refund-policy.pdf"
    assert results[0]["page_number"] == 3


def test_vector_search_uses_configured_index_tenant_filter_and_score_floor():
    chunks = FakeChunks(vector_results=[
        {
            "_id": "chunk-1",
            "document_id": "doc-1",
            "chunk_order": 0,
            "page_number": 2,
            "text": "Refunds are allowed within 30 days.",
            "metadata": {"filename": "refund-policy.pdf"},
            "score": 0.9,
        },
        {
            "_id": "chunk-2",
            "document_id": "doc-2",
            "chunk_order": 0,
            "page_number": 1,
            "text": "Low relevance text.",
            "metadata": {"filename": "other.pdf"},
            "score": 0.2,
        },
    ])
    settings = Settings(
        jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
        vector_search_index_name="kb-index",
        knowledge_tenant_id="tenant-a",
    )

    class Provider:
        def embed_texts(self, texts):
            assert texts == ["refund time"]
            return [[0.1, 0.2]]

    results, mode = search_knowledge(FakeDatabase(chunks), Provider(), settings, "refund time")
    vector_stage = chunks.pipeline[0]["$vectorSearch"]
    assert mode == "vector"
    assert vector_stage["index"] == "kb-index"
    assert vector_stage["filter"] == {"is_active": True, "tenant_id": "tenant-a"}
    assert [item["filename"] for item in results] == ["refund-policy.pdf"]


def test_configured_but_missing_atlas_index_does_not_silently_use_keyword_search():
    chunks = FakeChunks()
    chunks.aggregate_error = OperationFailure("index unavailable")
    settings = Settings(
        jwt_secret_key="test-signing-secret-with-32-bytes-minimum",
        vector_search_index_name="missing-index",
    )

    class Provider:
        def embed_texts(self, texts):
            return [[0.1, 0.2]]

    with pytest.raises(RuntimeError, match="index is unavailable or misconfigured"):
        search_knowledge(FakeDatabase(chunks), Provider(), settings, "refund")


import re
from typing import Any

from pymongo.errors import OperationFailure

from app.ai.provider import AIProviderError, LLMProvider
from app.core.config import Settings

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "for", "from",
    "how", "i", "in", "is", "it", "me", "of", "on", "or", "our", "the",
    "this", "to", "we", "what", "when", "where", "which", "with", "you",
}


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        if end < len(cleaned):
            boundary = cleaned.rfind(" ", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(start + 1, end - overlap)
    return chunks


def split_pages(
    pages: list[tuple[int | None, str]],
    chunk_size: int,
    overlap: int,
) -> list[dict[str, Any]]:
    result = []
    for page_number, text in pages:
        result.extend(
            {"text": chunk, "page_number": page_number, "chunk_order": len(result)}
            for chunk in split_text(text, chunk_size, overlap)
        )
    return result


def build_chunks(
    database: Any,
    provider: LLMProvider,
    settings: Settings,
    document: dict[str, Any],
    pages: list[tuple[int | None, str]],
) -> int:
    parts = split_pages(pages, settings.knowledge_chunk_size, settings.knowledge_chunk_overlap)
    if not parts:
        raise ValueError("No searchable text was found in the document")
    vectors = provider.embed_texts([item["text"] for item in parts])
    chunks = database["knowledge_chunks"]
    chunks.create_index([("tenant_id", 1), ("is_active", 1)])
    chunks.create_index([("document_id", 1), ("chunk_order", 1)])
    chunks.delete_many({"document_id": document["_id"]})
    chunks.insert_many([
        {
            "document_id": document["_id"],
            "tenant_id": document["tenant_id"],
            "is_active": True,
            "chunk_order": item["chunk_order"],
            "page_number": item["page_number"],
            "text": item["text"],
            "embedding": vectors[index],
            "embedding_model": settings.embedding_model,
            "metadata": {"filename": document["filename"], "document_type": document["document_type"]},
        }
        for index, item in enumerate(parts)
    ])
    return len(parts)


def search_knowledge(
    database: Any,
    provider: LLMProvider,
    settings: Settings,
    question: str,
) -> tuple[list[dict[str, Any]], str]:
    chunks = database["knowledge_chunks"]
    base_filter = {"is_active": True, "tenant_id": settings.knowledge_tenant_id}
    if settings.vector_search_index_name:
        query_vector = provider.embed_texts([question])[0]
        pipeline = [
            {
                "$vectorSearch": {
                    "index": settings.vector_search_index_name,
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": max(settings.knowledge_top_k * 20, 100),
                    "limit": settings.knowledge_top_k,
                    "filter": base_filter,
                }
            },
            {
                "$project": {
                    "document_id": 1,
                    "chunk_order": 1,
                    "page_number": 1,
                    "text": 1,
                    "metadata": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        try:
            results = list(chunks.aggregate(pipeline))
        except OperationFailure as exc:
            raise RuntimeError("Atlas Vector Search index is unavailable or misconfigured") from exc
        return [
            _source(item, item.get("score", 0))
            for item in results
            if item.get("score", 0) >= settings.knowledge_min_score
        ], "vector"

    terms = list(dict.fromkeys(
        word[:-1] if word.endswith("s") and len(word) > 3 else word
        for word in re.findall(r"[a-z0-9]{2,}", question.lower())
        if word not in STOP_WORDS
    ))
    if not terms:
        return [], "keyword_fallback"
    query = {
        **base_filter,
        "$or": [{"text": {"$regex": re.escape(term), "$options": "i"}} for term in terms],
    }
    candidates = list(chunks.find(query).limit(200))
    ranked = []
    for item in candidates:
        document_terms = {
            token[:-1] if token.endswith("s") and len(token) > 3 else token
            for token in re.findall(r"[a-z0-9]{2,}", item["text"].lower())
        }
        query_terms = {
            term[:-1] if term.endswith("s") and len(term) > 3 else term
            for term in terms
        }
        matched = len(document_terms.intersection(query_terms))
        if matched:
            ranked.append((matched / len(terms), item))
    ranked.sort(key=lambda result: (result[0], -result[1].get("chunk_order", 0)), reverse=True)
    return [
        _source(item, score)
        for score, item in ranked[:settings.knowledge_top_k]
        if score >= 0.25
    ], "keyword_fallback"


def _source(item: dict[str, Any], score: float) -> dict[str, Any]:
    metadata = item.get("metadata", {})
    return {
        "chunk_id": str(item["_id"]),
        "document_id": str(item["document_id"]),
        "filename": metadata.get("filename", "Knowledge base"),
        "page_number": item.get("page_number"),
        "text": item["text"],
        "score": score,
    }

import logging
import re
from datetime import datetime, timezone
from typing import Any

import pymupdf as fitz
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from gridfs import GridFSBucket
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool

from app.ai.knowledge import build_chunks, search_knowledge
from app.ai.provider import AIProviderError, LLMProvider
from app.api.deps import get_current_user
from app.schemas.auth import UserRole

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge", tags=["Knowledge base"])
PDF_MIME = "application/pdf"


class ArticleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=160)
    content: str = Field(min_length=20, max_length=200_000)


class ChatSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=2000)


class DocumentResponse(BaseModel):
    id: str
    filename: str
    document_type: str
    status: str
    processing_error: str | None = None
    chunk_count: int
    uploaded_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class KnowledgeSearchResponse(BaseModel):
    mode: str
    sources: list[dict[str, Any]]


def _database(request: Request) -> Any:
    settings = request.app.state.settings
    return request.app.state.mongo_client[settings.mongodb_database]


def _require_admin(user: dict[str, Any]) -> None:
    if user.get("role") != UserRole.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")


def _provider(request: Request) -> LLMProvider:
    provider = LLMProvider(request.app.state.settings)
    if not provider.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI and embeddings are not configured. Set LLM_API_BASE_URL, LLM_API_KEY, and LLM_MODEL.",
        )
    return provider


def _documents(database: Any) -> Any:
    collection = database["knowledge_documents"]
    collection.create_index([("tenant_id", 1), ("created_at", -1)])
    collection.create_index([("tenant_id", 1), ("status", 1)])
    return collection


def _safe_filename(filename: str | None, fallback: str) -> str:
    name = re.split(r"[/\\]", filename or "")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:180] or fallback


def _document_response(document: dict[str, Any]) -> DocumentResponse:
    return DocumentResponse(
        id=str(document["_id"]),
        filename=document["filename"],
        document_type=document["document_type"],
        status=document["status"],
        processing_error=document.get("processing_error"),
        chunk_count=document.get("chunk_count", 0),
        uploaded_at=document["created_at"],
        updated_at=document["updated_at"],
    )


def _extract_pdf(data: bytes, max_chars: int) -> list[tuple[int, str]]:
    if b"%PDF-" not in data[:1024]:
        raise ValueError("The uploaded file does not have a valid PDF signature")
    try:
        with fitz.open(stream=data, filetype="pdf") as pdf:
            if pdf.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported")
            if pdf.page_count > 1000:
                raise ValueError("PDFs cannot contain more than 1000 pages")
            pages = [(index + 1, page.get_text("text")) for index, page in enumerate(pdf)]
    except (fitz.FileDataError, fitz.EmptyFileError) as exc:
        raise ValueError("The uploaded PDF could not be opened") from exc
    if not any(text.strip() for _, text in pages):
        raise ValueError("No searchable text was found in the PDF")
    if sum(len(text) for _, text in pages) > max_chars:
        raise ValueError("Extracted PDF text exceeds the configured character limit")
    return pages


def _process(
    database: Any,
    document: dict[str, Any],
    pages: list[tuple[int | None, str]],
    provider: LLMProvider,
    settings: Any,
) -> dict[str, Any]:
    try:
        count = build_chunks(database, provider, settings, document, pages)
        now = datetime.now(timezone.utc)
        _documents(database).update_one(
            {"_id": document["_id"]},
            {"$set": {
                "status": "ready",
                "is_active": True,
                "chunk_count": count,
                "processing_error": None,
                "updated_at": now,
            }},
        )
        document.update(status="ready", is_active=True, chunk_count=count, processing_error=None, updated_at=now)
        return document
    except (AIProviderError, ValueError, RuntimeError, PyMongoError) as exc:
        logger.warning("Knowledge document processing failed for %s: %s", document["_id"], type(exc).__name__)
        message = "Database storage failed while indexing the source" if isinstance(exc, PyMongoError) else str(exc)[:300]
        now = datetime.now(timezone.utc)
        _documents(database).update_one(
            {"_id": document["_id"]},
            {"$set": {"status": "failed", "is_active": False, "processing_error": message, "updated_at": now}},
        )
        document.update(status="failed", is_active=False, processing_error=message, updated_at=now)
        return document


def _new_document(
    database: Any,
    settings: Any,
    user: dict[str, Any],
    filename: str,
    document_type: str,
    file_id: ObjectId,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    document = {
        "tenant_id": settings.knowledge_tenant_id,
        "filename": filename,
        "document_type": document_type,
        "uploaded_by": user["_id"],
        "file_id": file_id,
        "status": "processing",
        "is_active": False,
        "chunk_count": 0,
        "processing_error": None,
        "created_at": now,
        "updated_at": now,
    }
    document["_id"] = _documents(database).insert_one(document).inserted_id
    return document


def _store_source(database: Any, source: bytes, filename: str, document_type: str) -> ObjectId:
    bucket = GridFSBucket(database, bucket_name="knowledge_sources")
    return bucket.upload_from_stream(
        filename,
        source,
        metadata={"document_type": document_type},
    )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DocumentResponse:
    _require_admin(current_user)
    settings = request.app.state.settings
    if file.content_type != PDF_MIME:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Upload a PDF file")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.knowledge_max_pdf_bytes + 262_144:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="PDF exceeds the configured size limit")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Content-Length header") from exc
    content = await file.read(settings.knowledge_max_pdf_bytes + 1)
    await file.close()
    if len(content) > settings.knowledge_max_pdf_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="PDF exceeds the configured size limit")
    try:
        pages = await run_in_threadpool(_extract_pdf, content, settings.knowledge_max_extracted_chars)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    provider = _provider(request)
    database = _database(request)
    filename = _safe_filename(file.filename, "knowledge.pdf")
    file_id = await run_in_threadpool(_store_source, database, content, filename, "pdf")
    document = await run_in_threadpool(
        _new_document,
        database,
        settings,
        current_user,
        filename,
        "pdf",
        file_id,
    )
    processed = await run_in_threadpool(_process, database, document, pages, provider, settings)
    return _document_response(processed)


@router.post("/articles", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def create_article(
    payload: ArticleRequest,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DocumentResponse:
    _require_admin(current_user)
    database = _database(request)
    settings = request.app.state.settings
    provider = _provider(request)
    filename = f"{_safe_filename(payload.title, 'Knowledge article')}.txt"
    file_id = _store_source(database, payload.content.encode("utf-8"), filename, "article")
    document = _new_document(database, settings, current_user, filename, "article", file_id)
    return _document_response(_process(database, document, [(None, payload.content)], provider, settings))


@router.get("", response_model=DocumentListResponse)
def list_documents(
    request: Request,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    include_inactive: bool = False,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DocumentListResponse:
    _require_admin(current_user)
    tenant_id = request.app.state.settings.knowledge_tenant_id
    query: dict[str, Any] = {"tenant_id": tenant_id}
    if not include_inactive:
        query["status"] = {"$ne": "inactive"}
    collection = _documents(_database(request))
    items = list(collection.find(query).sort("created_at", -1).skip(skip).limit(limit))
    return DocumentListResponse(
        items=[_document_response(item) for item in items],
        total=collection.count_documents(query),
    )


@router.delete("/{document_id}", response_model=DocumentResponse)
def deactivate_document(
    document_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DocumentResponse:
    _require_admin(current_user)
    try:
        object_id = ObjectId(document_id)
    except (InvalidId, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found") from exc
    database = _database(request)
    query = {"_id": object_id, "tenant_id": request.app.state.settings.knowledge_tenant_id}
    document = _documents(database).find_one(query)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found")
    now = datetime.now(timezone.utc)
    _documents(database).update_one(query, {"$set": {"is_active": False, "status": "inactive", "updated_at": now}})
    database["knowledge_chunks"].update_many({"document_id": object_id}, {"$set": {"is_active": False}})
    document.update(is_active=False, status="inactive", updated_at=now)
    return _document_response(document)


@router.post("/{document_id}/reprocess", response_model=DocumentResponse)
def reprocess_document(
    document_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DocumentResponse:
    _require_admin(current_user)
    try:
        object_id = ObjectId(document_id)
    except (InvalidId, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found") from exc
    database = _database(request)
    query = {"_id": object_id, "tenant_id": request.app.state.settings.knowledge_tenant_id}
    document = _documents(database).find_one(query)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found")
    provider = _provider(request)
    source = GridFSBucket(database, bucket_name="knowledge_sources").open_download_stream(document["file_id"]).read()
    if document["document_type"] == "pdf":
        try:
            pages = _extract_pdf(source, request.app.state.settings.knowledge_max_extracted_chars)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    else:
        pages = [(None, source.decode("utf-8"))]
    now = datetime.now(timezone.utc)
    _documents(database).update_one(query, {"$set": {"status": "processing", "is_active": False, "updated_at": now}})
    database["knowledge_chunks"].update_many({"document_id": object_id}, {"$set": {"is_active": False}})
    document.update(status="processing", is_active=False, updated_at=now)
    return _document_response(_process(database, document, pages, provider, request.app.state.settings))


@router.post("/search", response_model=KnowledgeSearchResponse)
def search_documents(
    payload: ChatSearchRequest,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> KnowledgeSearchResponse:
    _require_admin(current_user)
    provider = _provider(request)
    sources, mode = search_knowledge(
        _database(request),
        provider,
        request.app.state.settings,
        payload.query,
    )
    return KnowledgeSearchResponse(mode=mode, sources=sources)

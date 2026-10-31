import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.provider import AIProviderError, ChatReply, LLMProvider, TicketClassification
from app.ai.knowledge import search_knowledge
from app.api.deps import get_current_user
from app.api.tickets import add_event, collections, create_ticket, get_staff_ticket, staff_role
from app.schemas.auth import UserRole
from app.schemas.tickets import TicketCreate, TicketResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI ticket intelligence"])


class SuggestionResponse(BaseModel):
    suggestion: str


class AIStatusResponse(BaseModel):
    configured: bool
    model: str | None
    status: str


class SummaryResponse(BaseModel):
    main_issue: str
    steps_attempted: list[str]
    current_status: str
    recommended_next_action: str


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot be blank")
        return normalized


class ChatSource(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_number: int | None = None


class ChatMessageResponse(BaseModel):
    role: str
    content: str
    created_at: datetime
    sources: list[ChatSource] = Field(default_factory=list)


class ChatResponse(BaseModel):
    messages: list[ChatMessageResponse]
    needs_human: bool = False
    ai_available: bool = True
    source_mode: str


class ChatEscalationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, min_length=4, max_length=160)


class ChatEscalationResponse(BaseModel):
    ticket: TicketResponse


def get_provider(request: Request) -> LLMProvider:
    return LLMProvider(request.app.state.settings)


def require_staff(user: dict[str, Any]) -> None:
    if not staff_role(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")


def load_ticket_context(ticket_id: str, request: Request, user: dict[str, Any]):
    require_staff(user)
    tickets, messages, _, _ = collections(request)
    ticket = get_staff_ticket(ticket_id, tickets, user)
    conversation = [
        {
            "sender": message.get("sender_role"),
            "content": message.get("content"),
            "internal": message.get("is_internal", False),
        }
        for message in messages.find({"ticket_id": ticket["_id"]})
        .sort("created_at", 1)
        .limit(200)
    ]
    return ticket, conversation


def require_provider(provider: LLMProvider) -> None:
    if not provider.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI is not configured. Set LLM_API_BASE_URL, LLM_API_KEY, and LLM_MODEL.",
        )


def require_customer(user: dict[str, Any]) -> None:
    if user["role"] != UserRole.CUSTOMER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer access required")


def get_chat_collection(request: Request) -> Any:
    database = request.app.state.mongo_client[request.app.state.settings.mongodb_database]
    collection = database["ai_chat_sessions"]
    collection.create_index("expires_at", expireAfterSeconds=0)
    return collection


def rate_limit_ai(request: Request, user_id: ObjectId, scope: str, limit: int) -> None:
    database = request.app.state.mongo_client[request.app.state.settings.mongodb_database]
    limits = database["ai_rate_limits"]
    limits.create_index("expires_at", expireAfterSeconds=0)
    window_seconds = 60
    now_epoch = int(time.time())
    window = now_epoch // window_seconds
    now = datetime.now(timezone.utc)
    record = limits.find_one_and_update(
        {"_id": f"{scope}:{user_id}:{window}"},
        {
            "$inc": {"count": 1},
            "$setOnInsert": {
                "expires_at": datetime.fromtimestamp((window + 2) * window_seconds, timezone.utc),
            },
        },
        upsert=True,
        return_document=True,
    )
    if record and record["count"] > limit:
        retry_after = window_seconds - (now_epoch % window_seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Chat rate limit reached. Please wait a moment before trying again.",
            headers={"Retry-After": str(retry_after)},
        )


def chat_messages_from_session(session: dict[str, Any] | None) -> list[ChatMessageResponse]:
    return [
        ChatMessageResponse(
            role=item["role"],
            content=item["content"],
            created_at=item["created_at"],
            sources=[
                ChatSource(
                    chunk_id=source["chunk_id"],
                    document_id=source["document_id"],
                    filename=source["filename"],
                    page_number=source.get("page_number"),
                )
                for source in item.get("sources", [])
            ],
        )
        for item in (session or {}).get("messages", [])
    ]


@router.get("/status", response_model=AIStatusResponse)
def ai_status(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> AIStatusResponse:
    require_staff(current_user)
    provider = get_provider(request)
    return AIStatusResponse(
        configured=provider.configured,
        model=request.app.state.settings.llm_model if provider.configured else None,
        status="ready" if provider.configured else "not_configured",
    )


@router.get("/chat", response_model=ChatResponse)
def get_chat_history(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ChatResponse:
    require_customer(current_user)
    sessions = get_chat_collection(request)
    session = sessions.find_one({"_id": current_user["_id"]})
    return ChatResponse(
        messages=chat_messages_from_session(session),
        needs_human=bool((session or {}).get("needs_human", False)),
        ai_available=get_provider(request).configured,
        source_mode="vector" if request.app.state.settings.vector_search_index_name else "keyword_fallback",
    )


@router.post("/chat", response_model=ChatResponse)
def chat_with_customer(
    payload: ChatMessageRequest,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ChatResponse:
    require_customer(current_user)
    provider = get_provider(request)
    require_provider(provider)
    rate_limit_ai(request, current_user["_id"], "chat", 10)

    sessions = get_chat_collection(request)
    session = sessions.find_one({"_id": current_user["_id"]}) or {"messages": []}
    old_messages = session["messages"][-12:]
    context = [
        {"role": item["role"], "content": item["content"]}
        for item in old_messages
    ]
    try:
        database = request.app.state.mongo_client[request.app.state.settings.mongodb_database]
        sources, source_mode = search_knowledge(
            database,
            provider,
            request.app.state.settings,
            payload.content,
        )
        if sources:
            reply = provider.answer_with_knowledge(payload.content, context, sources)
        else:
            reply = ChatReply(
                answer="I couldn't find supporting information for that question in the company knowledge base. Please contact our support team so a person can help.",
                needs_human=True,
            )
    except AIProviderError as exc:
        logger.warning("Customer chatbot unavailable for user %s: %s", current_user["_id"], exc)
        raise HTTPException(status_code=502, detail="AI assistant is temporarily unavailable. Please try again or create a support ticket.") from exc
    except RuntimeError as exc:
        logger.error("Knowledge retrieval unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
    append_messages = [
        {"role": "user", "content": payload.content, "created_at": now},
        {
            "role": "assistant",
            "content": reply.answer,
            "created_at": now,
            "sources": [
                {key: source[key] for key in ("chunk_id", "document_id", "filename", "page_number")}
                for source in sources
            ],
        },
    ]
    updated = sessions.find_one_and_update(
        {"_id": current_user["_id"]},
        {
            "$push": {"messages": {"$each": append_messages, "$slice": -40}},
            "$set": {
                "updated_at": now,
                "expires_at": now + timedelta(days=30),
                "needs_human": reply.needs_human,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
        return_document=True,
    )
    return ChatResponse(
        messages=chat_messages_from_session(updated),
        needs_human=reply.needs_human,
        ai_available=True,
        source_mode=source_mode,
    )


@router.delete("/chat", status_code=status.HTTP_204_NO_CONTENT)
def clear_chat_history(
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    require_customer(current_user)
    get_chat_collection(request).delete_one({"_id": current_user["_id"]})
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/chat/escalate", response_model=ChatEscalationResponse, status_code=status.HTTP_201_CREATED)
def escalate_chat_to_ticket(
    payload: ChatEscalationRequest,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ChatEscalationResponse:
    require_customer(current_user)
    sessions = get_chat_collection(request)
    session = sessions.find_one({"_id": current_user["_id"]})
    user_messages = [
        item["content"]
        for item in (session or {}).get("messages", [])
        if item.get("role") == "user"
    ]
    if not user_messages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Send a chat message before requesting human support")
    description = "Customer requested human support from the AI assistant.\n\n" + "\n\n".join(user_messages[-10:])
    description = description[:10000]
    default_subject = user_messages[-1].strip()
    subject = payload.subject or (default_subject[:157] + "..." if len(default_subject) > 160 else default_subject)
    if len(subject) < 4:
        subject = f"Support request: {subject}"
    ticket = create_ticket(
        TicketCreate(
            subject=subject,
            description=description,
            category="general_support",
            priority="medium",
        ),
        request,
        current_user,
    )
    sessions.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"needs_human": True, "escalated_ticket_id": ObjectId(ticket.id), "updated_at": datetime.now(timezone.utc)}},
    )
    return ChatEscalationResponse(ticket=ticket)


@router.post("/tickets/{ticket_id}/classify", response_model=TicketClassification)
def classify_ticket(
    ticket_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TicketClassification:
    require_staff(current_user)
    provider = get_provider(request)
    require_provider(provider)
    rate_limit_ai(request, current_user["_id"], "staff", 30)
    ticket, _ = load_ticket_context(ticket_id, request, current_user)
    tickets, _, events, _ = collections(request)
    try:
        classification = provider.classify_ticket(ticket["subject"], ticket["description"])
    except AIProviderError as exc:
        logger.warning("Ticket classification unavailable for %s: %s", ticket["ticket_number"], exc)
        tickets.update_one(
            {"_id": ticket["_id"]},
            {"$set": {"ai_classification": {"status": "pending"}}},
        )
        raise HTTPException(status_code=502, detail="AI ticket classification is temporarily unavailable") from exc

    classification_data = {
        "status": "complete",
        **classification.model_dump(mode="json"),
    }
    tickets.update_one(
        {"_id": ticket["_id"]},
        {"$set": {
            "category": classification.category.value,
            "priority": classification.priority.value,
            "ai_classification": classification_data,
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    add_event(events, ticket["_id"], current_user, "ai_classified", {
        "category": classification.category.value,
        "priority": classification.priority.value,
        "confidence": classification.confidence,
    })
    return classification


@router.post("/tickets/{ticket_id}/suggest-response", response_model=SuggestionResponse)
def suggest_response(
    ticket_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SuggestionResponse:
    require_staff(current_user)
    provider = get_provider(request)
    require_provider(provider)
    rate_limit_ai(request, current_user["_id"], "staff", 30)
    ticket, conversation = load_ticket_context(ticket_id, request, current_user)
    try:
        public_conversation = [message for message in conversation if not message["internal"]]
        suggestion = provider.suggest_response(ticket["subject"], ticket["description"], public_conversation)
    except AIProviderError as exc:
        logger.warning("Response suggestion unavailable for ticket %s: %s", ticket["ticket_number"], exc)
        raise HTTPException(status_code=502, detail="AI response suggestion is temporarily unavailable") from exc
    return SuggestionResponse(suggestion=suggestion)


@router.post("/tickets/{ticket_id}/summarize", response_model=SummaryResponse)
def summarize_ticket(
    ticket_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SummaryResponse:
    require_staff(current_user)
    provider = get_provider(request)
    require_provider(provider)
    rate_limit_ai(request, current_user["_id"], "staff", 30)
    ticket, conversation = load_ticket_context(ticket_id, request, current_user)
    try:
        summary = provider.summarize_ticket(
            ticket["subject"],
            ticket["description"],
            ticket["status"],
            conversation,
        )
    except AIProviderError as exc:
        logger.warning("Ticket summary unavailable for ticket %s: %s", ticket["ticket_number"], exc)
        raise HTTPException(status_code=502, detail="AI ticket summary is temporarily unavailable") from exc
    return SummaryResponse(**summary.model_dump())

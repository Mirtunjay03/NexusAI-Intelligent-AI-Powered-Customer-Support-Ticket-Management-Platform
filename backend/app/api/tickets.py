import re
import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pymongo import ReturnDocument

from app.ai.provider import AIProviderError, LLMProvider
from app.api.deps import get_current_user
from app.schemas.auth import UserRole
from app.schemas.tickets import (
    AgentOption,
    AssignmentUpdate,
    MessageCreate,
    MessagePage,
    MessageResponse,
    StatusUpdate,
    TicketCategory,
    TicketCreate,
    TicketEventResponse,
    TicketPage,
    TicketPriority,
    TicketResponse,
    TicketStatus,
    TicketUpdate,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])
SORT_FIELDS = {"created_at", "updated_at", "ticket_number", "priority", "status"}
logger = logging.getLogger(__name__)


def collections(request: Request) -> tuple[Any, Any, Any, Any]:
    database = request.app.state.mongo_client[request.app.state.settings.mongodb_database]
    return (
        database["tickets"],
        database["ticket_messages"],
        database["ticket_events"],
        database["users"],
    )


def ensure_indexes(tickets: Any, messages: Any, events: Any) -> None:
    tickets.create_index("ticket_number", unique=True)
    tickets.create_index("customer_id")
    tickets.create_index("assigned_agent_id")
    tickets.create_index("status")
    tickets.create_index("priority")
    tickets.create_index("created_at")
    messages.create_index([("ticket_id", 1), ("created_at", -1)])
    events.create_index([("ticket_id", 1), ("created_at", -1)])


def object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found") from exc


def staff_role(user: dict[str, Any]) -> bool:
    return user["role"] in {UserRole.ADMIN.value, UserRole.AGENT.value}


def can_access_ticket(ticket: dict[str, Any], user: dict[str, Any]) -> bool:
    if user["role"] == UserRole.ADMIN.value:
        return True
    if user["role"] == UserRole.AGENT.value:
        return ticket.get("assigned_agent_id") in (None, user["_id"])
    return ticket["customer_id"] == user["_id"]


def require_ticket_access(ticket: dict[str, Any] | None, user: dict[str, Any]) -> dict[str, Any]:
    if ticket is None or not can_access_ticket(ticket, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


def add_event(
    events: Any,
    ticket_id: ObjectId,
    actor: dict[str, Any],
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    events.insert_one({
        "ticket_id": ticket_id,
        "actor_id": actor["_id"],
        "actor_name": actor["name"],
        "action": action,
        "details": details or {},
        "created_at": datetime.now(timezone.utc),
    })


def serialize_message(message: dict[str, Any]) -> MessageResponse:
    return MessageResponse(
        id=str(message["_id"]),
        sender_id=str(message["sender_id"]),
        sender_name=message["sender_name"],
        sender_role=message["sender_role"],
        content=message["content"],
        is_internal=message["is_internal"],
        created_at=message["created_at"],
    )


def serialize_ticket(ticket: dict[str, Any], messages: list[dict[str, Any]] | None = None) -> TicketResponse:
    return TicketResponse(
        id=str(ticket["_id"]),
        ticket_number=ticket["ticket_number"],
        subject=ticket["subject"],
        description=ticket["description"],
        customer_id=str(ticket["customer_id"]),
        customer_name=ticket["customer_name"],
        assigned_agent_id=str(ticket["assigned_agent_id"]) if ticket.get("assigned_agent_id") else None,
        assigned_agent_name=ticket.get("assigned_agent_name"),
        category=ticket["category"],
        priority=ticket["priority"],
        status=ticket["status"],
        tags=ticket.get("tags", []),
        created_at=ticket["created_at"],
        updated_at=ticket["updated_at"],
        resolved_at=ticket.get("resolved_at"),
        ai_classification=ticket.get("ai_classification"),
        messages=[serialize_message(message) for message in messages or []],
    )


def get_ticket_messages(messages: Any, ticket_id: ObjectId, include_internal: bool) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"ticket_id": ticket_id}
    if not include_internal:
        query["is_internal"] = False
    return list(messages.find(query).sort("created_at", -1).limit(100))[::-1]


def get_message_page(
    messages: Any,
    ticket_id: ObjectId,
    include_internal: bool,
    skip: int,
    limit: int,
) -> MessagePage:
    query: dict[str, Any] = {"ticket_id": ticket_id}
    if not include_internal:
        query["is_internal"] = False
    total = messages.count_documents(query)
    page = list(messages.find(query).sort("created_at", -1).skip(skip).limit(limit))[::-1]
    return MessagePage(
        items=[serialize_message(message) for message in page],
        total=total,
        skip=skip,
        limit=limit,
    )


def staff_only(user: dict[str, Any]) -> None:
    if not staff_role(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")


def get_staff_ticket(ticket_id: str, tickets: Any, user: dict[str, Any]) -> dict[str, Any]:
    ticket = tickets.find_one({"_id": object_id(ticket_id)})
    ticket = require_ticket_access(ticket, user)
    staff_only(user)
    return ticket


@router.get("/agents", response_model=list[AgentOption])
def list_agents(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[AgentOption]:
    staff_only(current_user)
    _, _, _, users = collections(request)
    return [
        AgentOption(id=str(user["_id"]), name=user["name"])
        for user in users.find(
            {"role": UserRole.AGENT.value, "is_active": True},
            {"name": 1},
        ).sort("name", 1)
    ]


@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreate,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TicketResponse:
    if current_user["role"] != UserRole.CUSTOMER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can create support tickets",
        )
    tickets, messages, events, _ = collections(request)
    ensure_indexes(tickets, messages, events)
    database = request.app.state.mongo_client[request.app.state.settings.mongodb_database]
    counters = database["counters"]
    counters.update_one(
        {"_id": "ticket_number"},
        {"$setOnInsert": {"value": 10000}},
        upsert=True,
    )
    sequence = counters.find_one_and_update(
        {"_id": "ticket_number"},
        {"$inc": {"value": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if sequence is None:
        raise HTTPException(status_code=500, detail="Could not allocate a ticket number")

    now = datetime.now(timezone.utc)
    ticket_id = ObjectId()
    ticket_number = f"NEX-{sequence['value']}"
    ticket = {
        "_id": ticket_id,
        "ticket_number": ticket_number,
        "subject": payload.subject,
        "description": payload.description,
        "customer_id": current_user["_id"],
        "customer_name": current_user["name"],
        "assigned_agent_id": None,
        "assigned_agent_name": None,
        "category": payload.category.value,
        "priority": payload.priority.value,
        "status": TicketStatus.OPEN.value,
        "tags": payload.tags,
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
        "ai_classification": {"status": "pending"},
    }
    provider = LLMProvider(request.app.state.settings)
    if provider.configured:
        try:
            classification = provider.classify_ticket(ticket["subject"], ticket["description"])
            ticket["category"] = classification.category.value
            ticket["priority"] = classification.priority.value
            ticket["ai_classification"] = {
                "status": "complete",
                **classification.model_dump(mode="json"),
            }
        except AIProviderError as exc:
            logger.warning("Ticket classification pending for %s: %s", ticket_number, exc)
    tickets.insert_one(ticket)
    add_event(events, ticket_id, current_user, "created", {"ticket_number": ticket_number})
    return serialize_ticket(ticket)


@router.get("", response_model=TicketPage)
def list_tickets(
    request: Request,
    status_filter: TicketStatus | None = Query(default=None, alias="status"),
    priority: TicketPriority | None = None,
    category: TicketCategory | None = None,
    agent_id: str | None = None,
    search: str | None = Query(default=None, max_length=160),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TicketPage:
    if sort_by not in SORT_FIELDS:
        raise HTTPException(status_code=422, detail=f"sort_by must be one of {', '.join(sorted(SORT_FIELDS))}")
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=422, detail="created_from must be before created_to")

    tickets, messages, events, _ = collections(request)
    ensure_indexes(tickets, messages, events)
    query: dict[str, Any] = {}
    if current_user["role"] == UserRole.CUSTOMER.value:
        query["customer_id"] = current_user["_id"]
    elif current_user["role"] == UserRole.AGENT.value:
        query["$or"] = [
            {"assigned_agent_id": current_user["_id"]},
            {"assigned_agent_id": None},
        ]
    if status_filter:
        query["status"] = status_filter.value
    if priority:
        query["priority"] = priority.value
    if category:
        query["category"] = category.value
    if agent_id is not None:
        query["assigned_agent_id"] = None if agent_id == "unassigned" else object_id(agent_id)
    if search:
        escaped = re.escape(search.strip())
        query["$and"] = query.get("$and", []) + [
            {"$or": [
                {"ticket_number": {"$regex": escaped, "$options": "i"}},
                {"subject": {"$regex": escaped, "$options": "i"}},
            ]}
        ]
    if created_from or created_to:
        date_filter = {}
        if created_from:
            date_filter["$gte"] = created_from
        if created_to:
            date_filter["$lte"] = created_to
        query["created_at"] = date_filter

    total = tickets.count_documents(query)
    cursor = tickets.find(query).sort(sort_by, -1 if sort_order == "desc" else 1).skip(skip).limit(limit)
    ticket_list = list(cursor)
    for ticket in ticket_list:
        ticket["_messages"] = get_ticket_messages(
            messages,
            ticket["_id"],
            include_internal=staff_role(current_user),
        )
    return TicketPage(
        items=[serialize_ticket(ticket, ticket["_messages"]) for ticket in ticket_list],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TicketResponse:
    tickets, messages, _, _ = collections(request)
    ticket = require_ticket_access(tickets.find_one({"_id": object_id(ticket_id)}), current_user)
    thread = get_ticket_messages(messages, ticket["_id"], include_internal=staff_role(current_user))
    return serialize_ticket(ticket, thread)


@router.patch("/{ticket_id}", response_model=TicketResponse)
def update_ticket(
    ticket_id: str,
    payload: TicketUpdate,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TicketResponse:
    tickets, messages, events, _ = collections(request)
    ticket = require_ticket_access(tickets.find_one({"_id": object_id(ticket_id)}), current_user)
    if current_user["role"] == UserRole.CUSTOMER.value and ticket["status"] != TicketStatus.OPEN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customers can only edit open tickets",
        )
    updates = payload.model_dump(exclude_unset=True)
    previous_priority = ticket["priority"]
    for key in ("category", "priority"):
        if key in updates and updates[key] is not None:
            updates[key] = updates[key].value
    updates["updated_at"] = datetime.now(timezone.utc)
    tickets.update_one({"_id": ticket["_id"]}, {"$set": updates})
    if updates.get("priority", previous_priority) != previous_priority:
        add_event(events, ticket["_id"], current_user, "priority_changed", {
            "from": previous_priority,
            "to": updates["priority"],
        })
    ticket.update(updates)
    thread = get_ticket_messages(messages, ticket["_id"], include_internal=staff_role(current_user))
    return serialize_ticket(ticket, thread)


@router.patch("/{ticket_id}/status", response_model=TicketResponse)
def update_status(
    ticket_id: str,
    payload: StatusUpdate,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TicketResponse:
    tickets, messages, events, _ = collections(request)
    ticket = get_staff_ticket(ticket_id, tickets, current_user)
    if current_user["role"] == UserRole.AGENT.value and ticket.get("assigned_agent_id") != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assign this ticket before changing its status")
    previous = ticket["status"]
    updated_at = datetime.now(timezone.utc)
    resolved_at = updated_at if payload.status in {TicketStatus.RESOLVED, TicketStatus.CLOSED} else None
    tickets.update_one(
        {"_id": ticket["_id"]},
        {"$set": {"status": payload.status.value, "updated_at": updated_at, "resolved_at": resolved_at}},
    )
    if previous != payload.status.value:
        add_event(events, ticket["_id"], current_user, "status_changed", {
            "from": previous,
            "to": payload.status.value,
        })
    ticket.update({"status": payload.status.value, "updated_at": updated_at, "resolved_at": resolved_at})
    thread = get_ticket_messages(messages, ticket["_id"], include_internal=True)
    return serialize_ticket(ticket, thread)


@router.patch("/{ticket_id}/assign", response_model=TicketResponse)
def assign_ticket(
    ticket_id: str,
    payload: AssignmentUpdate,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TicketResponse:
    tickets, messages, events, users = collections(request)
    ticket = get_staff_ticket(ticket_id, tickets, current_user)
    agent = None
    if payload.agent_id is not None:
        agent_id = object_id(payload.agent_id)
        agent = users.find_one({
            "_id": agent_id,
            "role": UserRole.AGENT.value,
            "is_active": True,
        })
        if agent is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select an active support agent")
        if current_user["role"] == UserRole.AGENT.value:
            if ticket.get("assigned_agent_id") not in (None, current_user["_id"]):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This ticket belongs to another agent")
            if ticket.get("assigned_agent_id") is None and agent["_id"] != current_user["_id"]:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agents can only claim tickets for themselves")

    previous_id = ticket.get("assigned_agent_id")
    if previous_id == (agent["_id"] if agent else None):
        thread = get_ticket_messages(messages, ticket["_id"], include_internal=True)
        return serialize_ticket(ticket, thread)
    updates = {
        "assigned_agent_id": agent["_id"] if agent else None,
        "assigned_agent_name": agent["name"] if agent else None,
        "updated_at": datetime.now(timezone.utc),
    }
    tickets.update_one({"_id": ticket["_id"]}, {"$set": updates})
    add_event(events, ticket["_id"], current_user, "assigned", {
        "from_agent_id": str(previous_id) if previous_id else None,
        "to_agent_id": str(agent["_id"]) if agent else None,
        "to_agent_name": agent["name"] if agent else None,
    })
    ticket.update(updates)
    thread = get_ticket_messages(messages, ticket["_id"], include_internal=True)
    return serialize_ticket(ticket, thread)


def add_message(
    ticket_id: str,
    content: str,
    is_internal: bool,
    request: Request,
    current_user: dict[str, Any],
) -> TicketResponse:
    tickets, messages, events, _ = collections(request)
    ticket = require_ticket_access(tickets.find_one({"_id": object_id(ticket_id)}), current_user)
    if is_internal:
        staff_only(current_user)
    elif current_user["role"] == UserRole.AGENT.value and ticket.get("assigned_agent_id") != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assign this ticket before replying")

    now = datetime.now(timezone.utc)
    message_result = messages.insert_one({
        "ticket_id": ticket["_id"],
        "sender_id": current_user["_id"],
        "sender_name": current_user["name"],
        "sender_role": current_user["role"],
        "content": content,
        "is_internal": is_internal,
        "created_at": now,
    })
    tickets.update_one({"_id": ticket["_id"]}, {"$set": {"updated_at": now}})
    action = "internal_note" if is_internal else "reply_added"
    add_event(events, ticket["_id"], current_user, action, {"message_id": str(message_result.inserted_id)})
    ticket["updated_at"] = now
    thread = get_ticket_messages(messages, ticket["_id"], include_internal=staff_role(current_user))
    return serialize_ticket(ticket, thread)


@router.post("/{ticket_id}/messages", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def reply_to_ticket(
    ticket_id: str,
    payload: MessageCreate,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TicketResponse:
    return add_message(ticket_id, payload.content, False, request, current_user)


@router.post("/{ticket_id}/internal-notes", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def add_internal_note(
    ticket_id: str,
    payload: MessageCreate,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TicketResponse:
    staff_only(current_user)
    return add_message(ticket_id, payload.content, True, request, current_user)


@router.get("/{ticket_id}/history", response_model=list[TicketEventResponse])
def get_ticket_history(
    ticket_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[TicketEventResponse]:
    tickets, _, events, _ = collections(request)
    ticket = require_ticket_access(tickets.find_one({"_id": object_id(ticket_id)}), current_user)
    query: dict[str, Any] = {"ticket_id": ticket["_id"]}
    if not staff_role(current_user):
        query["action"] = {"$ne": "internal_note"}
    return [
        TicketEventResponse(
            id=str(event["_id"]),
            actor_id=str(event["actor_id"]),
            actor_name=event["actor_name"],
            action=event["action"],
            details=event["details"],
            created_at=event["created_at"],
        )
        for event in events.find(query).sort("created_at", 1).limit(200)
    ]


@router.get("/{ticket_id}/messages", response_model=MessagePage)
def list_ticket_messages(
    ticket_id: str,
    request: Request,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> MessagePage:
    tickets, messages, _, _ = collections(request)
    ticket = require_ticket_access(tickets.find_one({"_id": object_id(ticket_id)}), current_user)
    return get_message_page(
        messages,
        ticket["_id"],
        include_internal=staff_role(current_user),
        skip=skip,
        limit=limit,
    )

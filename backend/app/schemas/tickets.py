from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING_CUSTOMER = "pending_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketCategory(StrEnum):
    TECHNICAL_ISSUE = "technical_issue"
    BILLING = "billing"
    ACCOUNT = "account"
    PRODUCT_INQUIRY = "product_inquiry"
    GENERAL_SUPPORT = "general_support"


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=4, max_length=160)
    description: str = Field(min_length=10, max_length=10000)
    category: TicketCategory = TicketCategory.GENERAL_SUPPORT
    priority: TicketPriority = TicketPriority.MEDIUM
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("subject", "description")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Field cannot be blank")
        return normalized

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(tag.strip().lower() for tag in values if tag.strip()))
        if any(len(tag) > 32 for tag in cleaned):
            raise ValueError("Tags must be 32 characters or fewer")
        return cleaned


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, min_length=4, max_length=160)
    description: str | None = Field(default=None, min_length=10, max_length=10000)
    category: TicketCategory | None = None
    priority: TicketPriority | None = None
    tags: list[str] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def validate_changes(self) -> "TicketUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Update fields cannot be null")
        return self


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TicketStatus


class AssignmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str | None


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=10000)

    @field_validator("content")
    @classmethod
    def trim_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot be blank")
        return normalized


class MessageResponse(BaseModel):
    id: str
    sender_id: str
    sender_name: str
    sender_role: str
    content: str
    is_internal: bool
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageResponse]
    total: int
    skip: int
    limit: int


class TicketResponse(BaseModel):
    id: str
    ticket_number: str
    subject: str
    description: str
    customer_id: str
    customer_name: str
    assigned_agent_id: str | None
    assigned_agent_name: str | None
    category: TicketCategory
    priority: TicketPriority
    status: TicketStatus
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    ai_classification: dict[str, object] | None = None
    messages: list[MessageResponse] = Field(default_factory=list)


class TicketEventResponse(BaseModel):
    id: str
    actor_id: str
    actor_name: str
    action: str
    details: dict[str, object]
    created_at: datetime


class TicketPage(BaseModel):
    items: list[TicketResponse]
    total: int
    skip: int
    limit: int


class AgentOption(BaseModel):
    id: str
    name: str

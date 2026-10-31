from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.auth import UserRole


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=100)
    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Name must contain at least 2 non-whitespace characters")
        return normalized

    @model_validator(mode="after")
    def require_an_update(self) -> "UserUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Update fields cannot be null")
        return self

from functools import lru_cache
import secrets

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEVELOPMENT_JWT_SECRET = secrets.token_urlsafe(32)


class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "nexusai"
    cors_origins: str = "http://localhost:5173"
    app_env: str = "development"
    jwt_secret_key: str | None = None
    jwt_access_token_expire_minutes: int = 60
    llm_api_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_classification_model: str | None = None
    llm_response_model: str | None = None
    llm_summary_model: str | None = None
    llm_chat_model: str | None = None
    llm_request_timeout_seconds: float = 25
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    vector_search_index_name: str | None = None
    knowledge_tenant_id: str = "default"
    knowledge_chunk_size: int = 1200
    knowledge_chunk_overlap: int = 180
    knowledge_top_k: int = 5
    knowledge_min_score: float = 0.65
    knowledge_max_pdf_bytes: int = 10_485_760
    knowledge_max_extracted_chars: int = 500_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production_secret(self) -> "Settings":
        if self.app_env == "production" and not self.jwt_secret_key:
            raise ValueError("JWT_SECRET_KEY must be configured in production")
        if self.app_env == "production" and (
            not self.allowed_origins or "*" in self.allowed_origins
        ):
            raise ValueError("CORS_ORIGINS must list explicit trusted origins in production")
        if self.jwt_access_token_expire_minutes < 1:
            raise ValueError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be positive")
        if self.llm_request_timeout_seconds <= 0:
            raise ValueError("LLM_REQUEST_TIMEOUT_SECONDS must be positive")
        if self.embedding_dimensions < 1:
            raise ValueError("EMBEDDING_DIMENSIONS must be positive")
        if self.knowledge_chunk_size < 100:
            raise ValueError("KNOWLEDGE_CHUNK_SIZE must be at least 100")
        if not 0 <= self.knowledge_chunk_overlap < self.knowledge_chunk_size:
            raise ValueError("KNOWLEDGE_CHUNK_OVERLAP must be smaller than chunk size")
        if not 1 <= self.knowledge_top_k <= 20:
            raise ValueError("KNOWLEDGE_TOP_K must be between 1 and 20")
        if not 0 <= self.knowledge_min_score <= 1:
            raise ValueError("KNOWLEDGE_MIN_SCORE must be between 0 and 1")
        if self.knowledge_max_pdf_bytes < 1024:
            raise ValueError("KNOWLEDGE_MAX_PDF_BYTES must be at least 1024")
        if self.knowledge_max_extracted_chars < 1000:
            raise ValueError("KNOWLEDGE_MAX_EXTRACTED_CHARS must be at least 1000")
        return self

    @property
    def signing_secret(self) -> str:
        if self.jwt_secret_key:
            return self.jwt_secret_key
        if self.app_env == "production":
            raise RuntimeError("JWT_SECRET_KEY must be configured in production")
        return _DEVELOPMENT_JWT_SECRET

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def secure_cookie(self) -> bool:
        return self.app_env == "production"

    @property
    def cookie_samesite(self) -> str:
        return "none" if self.secure_cookie else "lax"


@lru_cache
def get_settings() -> Settings:
    return Settings()

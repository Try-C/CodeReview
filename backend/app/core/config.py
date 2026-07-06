"""Typed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnvironment = Literal["dev", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables and an optional .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    app_name: str = "CodeReview Agent"
    app_version: str = "0.1.0"
    app_env: AppEnvironment = "dev"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    allowed_origins: list[str] = ["http://localhost:5173"]
    log_level: LogLevel = "INFO"
    log_json: bool = True
    request_id_header: str = "X-Request-ID"
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://codereview:codereview@localhost:5432/codereview"
    )
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    task_event_retention_days: int = Field(default=7, ge=1, le=90)
    task_event_stream_max_length: int = Field(default=10_000, ge=100, le=1_000_000)
    sse_heartbeat_seconds: float = Field(default=15.0, ge=1.0, le=30.0)
    sse_event_batch_size: int = Field(default=100, ge=1, le=1000)
    jwt_secret_key: SecretStr = SecretStr("development-only-change-me")
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "codereview-agent"
    jwt_access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    health_dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    upload_root: Path = Path("var/uploads")
    max_project_size_mb: int = Field(default=300, ge=1, le=10_000)
    max_single_file_mb: int = Field(default=3, ge=1, le=100)
    max_file_count: int = Field(default=5000, ge=1, le=100_000)
    max_total_lines: int = Field(default=150_000, ge=1, le=10_000_000)
    max_relative_path_length: int = Field(default=512, ge=64, le=4096)
    enabled_languages: tuple[Literal["java", "python"], ...] = ("java", "python")
    chunk_ideal_min_lines: int = Field(default=50, ge=1, le=10_000)
    chunk_ideal_max_lines: int = Field(default=150, ge=1, le=10_000)
    chunk_max_lines: int = Field(default=200, ge=1, le=10_000)
    chunk_overlap_lines: int = Field(default=15, ge=0, le=1000)
    embedding_provider: Literal["dashscope"] = "dashscope"
    dashscope_api_key: SecretStr | None = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dimension: Literal[1024] = 1024
    embedding_batch_size: int = Field(default=10, ge=1, le=10)
    embedding_max_input_tokens: int = Field(default=8192, ge=1, le=8192)
    embedding_output_type: Literal["dense"] = "dense"
    embedding_version: int = Field(default=1, ge=1)
    pgvector_min_version: str = "0.8.0"
    hnsw_ef_search: int = Field(default=100, ge=1, le=1000)
    hnsw_iterative_scan: Literal["strict_order", "relaxed_order"] = "strict_order"
    top_k: int = Field(default=10, ge=1, le=100)
    max_top_k: int = Field(default=30, ge=1, le=100)
    rrf_k: int = Field(default=60, ge=1, le=1000)

    # ── LLM / Agent / Graph (§5) ────────────────────────────────────────────
    llm_provider: Literal["deepseek"] = "deepseek"
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_benchmark_model: str = "deepseek-v4-pro"
    llm_temperature: float = 0.0
    deepseek_api_key: SecretStr | None = None

    max_llm_calls: int = Field(default=30, ge=1)
    max_token_budget: int = Field(default=100_000, ge=1)
    langgraph_recursion_limit: int = Field(default=100, ge=1)
    max_review_rounds: int = Field(default=2, ge=1, le=10)
    max_retrieval_retries: int = Field(default=2, ge=0, le=10)
    max_json_repair_retries: int = Field(default=1, ge=0, le=3)

    # Pricing — environment-configured, never hardcoded in business logic (§5)
    llm_input_price_per_million: str = "0"
    llm_output_price_per_million: str = "0"
    llm_pricing_currency: str = "USD"
    llm_pricing_version: str = "unconfigured"
    embedding_input_price_per_million: str = "0"
    embedding_pricing_version: str = "unconfigured"

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Require a stable absolute prefix without a trailing slash."""
        if not value.startswith("/"):
            raise ValueError("api_v1_prefix must start with '/'")
        if value == "/" or value.endswith("/"):
            raise ValueError("api_v1_prefix must not be '/' or end with '/'")
        return value

    @field_validator("request_id_header")
    @classmethod
    def validate_request_id_header(cls, value: str) -> str:
        """Reject empty or whitespace-containing HTTP header names."""
        if not value or any(character.isspace() for character in value):
            raise ValueError("request_id_header must be a non-empty HTTP header name")
        return value

    @model_validator(mode="after")
    def validate_production_safety(self) -> Self:
        """Prevent unsafe debug and wildcard CORS settings in production."""
        if not (self.chunk_ideal_min_lines <= self.chunk_ideal_max_lines <= self.chunk_max_lines):
            raise ValueError("chunk line limits must satisfy ideal_min <= ideal_max <= max")
        if self.chunk_overlap_lines >= self.chunk_max_lines:
            raise ValueError("chunk_overlap_lines must be less than chunk_max_lines")
        if self.app_env == "production" and self.debug:
            raise ValueError("debug must be disabled in production")
        if self.app_env == "production" and "*" in self.allowed_origins:
            raise ValueError("wildcard CORS origins are not allowed in production")
        if (
            self.app_env == "production"
            and self.jwt_secret_key.get_secret_value() == "development-only-change-me"
        ):
            raise ValueError("jwt_secret_key must be changed in production")
        if self.app_env == "production" and len(self.jwt_secret_key.get_secret_value()) < 32:
            raise ValueError("jwt_secret_key must contain at least 32 characters in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""
    return Settings()

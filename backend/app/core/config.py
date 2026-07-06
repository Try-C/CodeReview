"""Typed application configuration."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import field_validator, model_validator
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
        if self.app_env == "production" and self.debug:
            raise ValueError("debug must be disabled in production")
        if self.app_env == "production" and "*" in self.allowed_origins:
            raise ValueError("wildcard CORS origins are not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""
    return Settings()

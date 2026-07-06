"""Unit tests for typed settings validation."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_load_json_origins_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        '["https://review.example.com","https://admin.example.com"]',
    )

    settings = Settings(_env_file=None)

    assert settings.allowed_origins == [
        "https://review.example.com",
        "https://admin.example.com",
    ]


@pytest.mark.parametrize("prefix", ["api/v1", "/", "/api/v1/"])
def test_invalid_api_prefix_is_rejected(prefix: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_v1_prefix=prefix)


def test_production_debug_is_rejected() -> None:
    with pytest.raises(ValidationError, match="debug must be disabled"):
        Settings(_env_file=None, app_env="production", debug=True)


def test_production_wildcard_cors_is_rejected() -> None:
    with pytest.raises(ValidationError, match="wildcard CORS"):
        Settings(
            _env_file=None,
            app_env="production",
            allowed_origins=["*"],
        )


def test_production_default_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="jwt_secret_key must be changed"):
        Settings(_env_file=None, app_env="production")


def test_production_short_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key="short-production-secret",
        )


def test_invalid_request_id_header_is_rejected() -> None:
    with pytest.raises(ValidationError, match="request_id_header"):
        Settings(_env_file=None, request_id_header="X Request ID")


def test_dependency_urls_are_masked_in_settings_representation() -> None:
    database_url = "postgresql+asyncpg://user:private-password@localhost/database"
    redis_url = "redis://:private-password@localhost:6379/0"

    settings = Settings(
        _env_file=None,
        database_url=database_url,
        redis_url=redis_url,
    )

    assert database_url not in repr(settings)
    assert redis_url not in repr(settings)
    assert settings.database_url.get_secret_value() == database_url
    assert settings.redis_url.get_secret_value() == redis_url


@pytest.mark.parametrize("timeout", [0, -1, 31])
def test_invalid_health_dependency_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, health_dependency_timeout_seconds=timeout)


@pytest.mark.parametrize("heartbeat", [0, 0.5, 31])
def test_invalid_sse_heartbeat_is_rejected(heartbeat: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, sse_heartbeat_seconds=heartbeat)


@pytest.mark.parametrize(
    ("ideal_min", "ideal_max", "maximum", "overlap"),
    [
        (151, 150, 200, 15),
        (50, 201, 200, 15),
        (5, 10, 15, 15),
    ],
)
def test_invalid_chunk_line_limits_are_rejected(
    ideal_min: int,
    ideal_max: int,
    maximum: int,
    overlap: int,
) -> None:
    with pytest.raises(ValidationError, match="chunk"):
        Settings(
            _env_file=None,
            chunk_ideal_min_lines=ideal_min,
            chunk_ideal_max_lines=ideal_max,
            chunk_max_lines=maximum,
            chunk_overlap_lines=overlap,
        )

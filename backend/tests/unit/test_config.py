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


def test_invalid_request_id_header_is_rejected() -> None:
    with pytest.raises(ValidationError, match="request_id_header"):
        Settings(_env_file=None, request_id_header="X Request ID")

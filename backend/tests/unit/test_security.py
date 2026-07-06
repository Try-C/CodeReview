"""Unit tests for password and access-token security boundaries."""

import pytest

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import AccessTokenService, PasswordManager


def test_password_manager_stores_and_verifies_argon2_hashes() -> None:
    passwords = PasswordManager()

    password_hash = passwords.hash("correct horse battery staple")

    assert password_hash.startswith("$argon2")
    assert "correct horse battery staple" not in password_hash
    assert passwords.verify("correct horse battery staple", password_hash)
    assert not passwords.verify("incorrect password", password_hash)
    assert not passwords.verify("correct horse battery staple", None)


def test_access_token_round_trip_and_tamper_rejection() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        jwt_secret_key="test-secret-that-is-long-enough-for-tests",
    )
    tokens = AccessTokenService(settings)
    token = tokens.create(42)

    assert tokens.subject(token) == 42

    header, payload, signature = token.split(".")
    tampered_signature = f"{'a' if signature[0] != 'a' else 'b'}{signature[1:]}"
    tampered = ".".join((header, payload, tampered_signature))
    with pytest.raises(AppError) as error:
        tokens.subject(tampered)

    assert error.value.code == "AUTHENTICATION_REQUIRED"
    assert error.value.status_code == 401


def test_get_token_service_builds_from_cached_settings() -> None:
    from app.core.security import AccessTokenService, get_token_service

    svc = get_token_service()
    assert isinstance(svc, AccessTokenService)
    assert svc._issuer == "codereview-agent"


def test_token_service_rejects_non_positive_subject() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        jwt_secret_key="test-secret-that-is-long-enough-for-tests",
    )
    tokens = AccessTokenService(settings)
    token = tokens.create(0)
    from app.core.exceptions import AppError

    with pytest.raises(AppError) as error:
        tokens.subject(token)
    assert error.value.code == "AUTHENTICATION_REQUIRED"


def test_get_token_service_returns_configured_service() -> None:
    from app.core.security import AccessTokenService, get_token_service

    svc = get_token_service()
    assert isinstance(svc, AccessTokenService)
    assert svc._issuer == "codereview-agent"
    assert svc.expires_in_seconds == 30 * 60  # 30 min

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

    tampered = f"{token[:-1]}{'a' if token[-1] != 'a' else 'b'}"
    with pytest.raises(AppError) as error:
        tokens.subject(tampered)

    assert error.value.code == "AUTHENTICATION_REQUIRED"
    assert error.value.status_code == 401

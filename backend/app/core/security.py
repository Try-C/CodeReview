"""Password hashing and signed access-token services."""

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import Settings
from app.core.exceptions import AppError


def authentication_error() -> AppError:
    """Build the uniform bearer-authentication failure response."""
    return AppError(
        code="AUTHENTICATION_REQUIRED",
        message="Valid authentication credentials are required",
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


class PasswordManager:
    """Hash passwords with Argon2 and equalize unknown-user verification work."""

    def __init__(self, password_hash: PasswordHash | None = None) -> None:
        self._password_hash = password_hash or PasswordHash.recommended()
        self._dummy_hash = self._password_hash.hash("dummy-password-not-used")

    def hash(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify(self, password: str, password_hash: str | None) -> bool:
        candidate_hash = password_hash or self._dummy_hash
        valid = self._password_hash.verify(password, candidate_hash)
        return password_hash is not None and valid


@lru_cache
def get_password_manager() -> PasswordManager:
    """Build one reusable Argon2 manager per application process."""
    return PasswordManager()


class AccessTokenService:
    """Issue and validate short-lived, issuer-bound JWT access tokens."""

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret_key.get_secret_value()
        self._algorithm = settings.jwt_algorithm
        self._issuer = settings.jwt_issuer
        self.expires_in_seconds = settings.jwt_access_token_expire_minutes * 60

    def create(self, user_id: int) -> str:
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "iss": self._issuer,
            "iat": now,
            "exp": now + timedelta(seconds=self.expires_in_seconds),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def subject(self, token: str) -> int:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                options={"require": ["sub", "iss", "iat", "exp"]},
            )
            subject = int(payload["sub"])
            if subject <= 0:
                raise ValueError
        except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise authentication_error() from exc
        return subject

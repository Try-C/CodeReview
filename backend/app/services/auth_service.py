"""Transactional authentication use cases."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.security import PasswordManager
from app.models.user import User


class AuthService:
    """Create and authenticate users through an injected database session."""

    def __init__(self, session: AsyncSession, passwords: PasswordManager) -> None:
        self._session = session
        self._passwords = passwords

    async def register(
        self,
        *,
        username: str,
        password: str,
        email: str | None,
    ) -> User:
        existing_id = await self._session.scalar(select(User.id).where(User.username == username))
        if existing_id is not None:
            raise self._username_conflict()

        user = User(
            username=username,
            password_hash=self._passwords.hash(password),
            email=email,
        )
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise self._username_conflict() from exc
        await self._session.refresh(user)
        return user

    async def authenticate(self, *, username: str, password: str) -> User:
        user = await self._session.scalar(select(User).where(User.username == username))
        password_hash = user.password_hash if user is not None else None
        if not self._passwords.verify(password, password_hash):
            raise AppError(
                code="INVALID_CREDENTIALS",
                message="Username or password is incorrect",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if user is None:  # pragma: no cover - narrowed by verify result
            raise RuntimeError("Password verification returned an impossible result")
        return user

    @staticmethod
    def _username_conflict() -> AppError:
        return AppError(
            code="USERNAME_ALREADY_EXISTS",
            message="Username is already registered",
            status_code=409,
        )

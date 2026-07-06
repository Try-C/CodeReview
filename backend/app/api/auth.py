"""Registration, login, and current-user endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import get_session
from app.core.security import (
    AccessTokenService,
    PasswordManager,
    authentication_error,
    get_password_manager,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.schemas.common import ErrorResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])
bearer_scheme = HTTPBearer(auto_error=False)
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
BearerDependency = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(bearer_scheme),
]
PasswordDependency = Annotated[PasswordManager, Depends(get_password_manager)]

AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Authentication failed"},
    422: {"model": ErrorResponse, "description": "Request validation failed"},
}


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def get_current_user(
    request: Request,
    credentials: BearerDependency,
    session: SessionDependency,
) -> User:
    """Resolve a valid bearer token to a currently existing user."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authentication_error()
    user_id = AccessTokenService(_settings(request)).subject(credentials.credentials)
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise authentication_error()
    return user


async def get_current_user_sse(
    request: Request,
    credentials: BearerDependency,
    session: SessionDependency,
    token: str = "",
) -> User:
    """Same as get_current_user but also accepts ?token= query param for EventSource."""
    token_value = credentials.credentials if (
        credentials is not None and credentials.scheme.lower() == "bearer"
    ) else token
    if not token_value:
        raise authentication_error()
    user_id = AccessTokenService(_settings(request)).subject(token_value)
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise authentication_error()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserSSE = Annotated[User, Depends(get_current_user_sse)]


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "Username already exists"},
        422: {"model": ErrorResponse, "description": "Request validation failed"},
    },
)
async def register(
    payload: RegisterRequest,
    session: SessionDependency,
    passwords: PasswordDependency,
) -> User:
    """Create an account while persisting only an Argon2 password hash."""
    return await AuthService(session, passwords).register(
        username=payload.username,
        password=payload.password.get_secret_value(),
        email=payload.email,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    responses=AUTH_ERROR_RESPONSES,
)
async def login(
    payload: LoginRequest,
    request: Request,
    session: SessionDependency,
    passwords: PasswordDependency,
) -> TokenResponse:
    """Exchange valid JSON credentials for a short-lived bearer token."""
    user = await AuthService(session, passwords).authenticate(
        username=payload.username,
        password=payload.password.get_secret_value(),
    )
    tokens = AccessTokenService(_settings(request))
    return TokenResponse(
        access_token=tokens.create(user.id),
        expires_in=tokens.expires_in_seconds,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    responses=AUTH_ERROR_RESPONSES,
)
async def me(current_user: CurrentUser) -> User:
    """Return the public profile associated with the bearer token."""
    return current_user

"""Application exceptions and unified HTTP error handling."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ErrorResponse

logger = logging.getLogger(__name__)
ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


class AppError(Exception):
    """Expected domain or application error safe to expose to API clients."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.headers = headers or {}


def _request_id(request: Request) -> str:
    return cast(str, getattr(request.state, "request_id", "unknown"))


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    payload = ErrorResponse(
        code=code,
        message=message,
        request_id=request_id,
        details=details or {},
    )
    header_name = cast(str, request.app.state.settings.request_id_header)
    response_headers = dict(headers or {})
    response_headers[header_name] = request_id
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=response_headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Render expected application failures with their stable error code."""
    return _error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        headers=exc.headers,
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Render request validation failures without echoing rejected input values."""
    errors = [
        {
            "location": list(error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return _error_response(
        request,
        status_code=422,
        code="REQUEST_VALIDATION_ERROR",
        message="Request validation failed",
        details={"errors": errors},
    )


async def http_error_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Normalize framework HTTP errors such as 404 and 405."""
    codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    message = exc.detail if isinstance(exc.detail, str) else "HTTP request failed"
    return _error_response(
        request,
        status_code=exc.status_code,
        code=codes.get(exc.status_code, "HTTP_ERROR"),
        message=message,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unexpected failures and return a non-sensitive response."""
    logger.exception(
        "unhandled_request_error",
        extra={"request_id": _request_id(request)},
        exc_info=exc,
    )
    return _error_response(
        request,
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all handlers in one place for consistent application startup."""
    app.add_exception_handler(AppError, cast(ExceptionHandler, app_error_handler))
    app.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, validation_error_handler),
    )
    app.add_exception_handler(
        StarletteHTTPException,
        cast(ExceptionHandler, http_error_handler),
    )
    app.add_exception_handler(Exception, unhandled_error_handler)

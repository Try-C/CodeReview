"""Integration tests for the public error contract."""

from typing import NoReturn

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import AppError


def test_not_found_uses_unified_error_schema(client: TestClient) -> None:
    response = client.get("/api/v1/missing")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "Not Found",
        "request_id": response.headers["X-Request-ID"],
        "details": {},
    }


def test_app_error_preserves_stable_code_and_details(application: FastAPI) -> None:
    async def raise_app_error() -> NoReturn:
        raise AppError(
            code="PROJECT_NOT_FOUND",
            message="Project does not exist",
            status_code=404,
            details={"project_id": 42},
        )

    application.add_api_route(
        "/_test/app-error",
        raise_app_error,
        response_model=None,
    )

    with TestClient(application) as client:
        response = client.get("/_test/app-error")

    assert response.status_code == 404
    assert response.json() == {
        "code": "PROJECT_NOT_FOUND",
        "message": "Project does not exist",
        "request_id": response.headers["X-Request-ID"],
        "details": {"project_id": 42},
    }


def test_validation_error_does_not_echo_rejected_input(application: FastAPI) -> None:
    async def require_number(value: int) -> dict[str, int]:
        return {"value": value}

    application.add_api_route("/_test/numbers/{value}", require_number)

    with TestClient(application) as client:
        response = client.get("/_test/numbers/not-a-number")

    body = response.json()
    assert response.status_code == 422
    assert body["code"] == "REQUEST_VALIDATION_ERROR"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["details"]["errors"] == [
        {
            "location": ["path", "value"],
            "message": "Input should be a valid integer, unable to parse string as an integer",
            "type": "int_parsing",
        }
    ]
    assert "not-a-number" not in response.text


def test_unhandled_error_returns_generic_message(application: FastAPI) -> None:
    async def raise_unhandled_error() -> NoReturn:
        raise RuntimeError("database password should never leak")

    application.add_api_route(
        "/_test/unhandled",
        raise_unhandled_error,
        response_model=None,
    )

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/_test/unhandled")

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_SERVER_ERROR",
        "message": "An unexpected error occurred",
        "request_id": response.headers["X-Request-ID"],
        "details": {},
    }
    assert "database password" not in response.text

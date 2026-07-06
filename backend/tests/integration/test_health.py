"""Integration tests for liveness, readiness, and request IDs."""

import re

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.runtime import RuntimeContext
from app.main import create_app
from tests.fakes import FakeHealthDependency


def test_live_health_does_not_call_dependencies(
    client: TestClient,
    database_dependency: FakeHealthDependency,
    redis_dependency: FakeHealthDependency,
) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "CodeReview Agent",
        "version": "0.1.0",
    }
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])
    assert database_dependency.check_calls == 0
    assert redis_dependency.check_calls == 0


def test_ready_health_reports_current_checks(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "CodeReview Agent",
        "version": "0.1.0",
        "checks": {
            "configuration": "ok",
            "database": "ok",
            "redis": "ok",
        },
    }


def test_ready_health_returns_503_when_a_dependency_fails(
    test_settings: Settings,
) -> None:
    runtime = RuntimeContext(
        dependencies=(
            FakeHealthDependency(
                name="database",
                check_error=RuntimeError("connection details must remain private"),
            ),
            FakeHealthDependency(name="redis"),
        )
    )

    with TestClient(create_app(test_settings, runtime)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "code": "SERVICE_NOT_READY",
        "message": "One or more service dependencies are unavailable",
        "request_id": response.headers["X-Request-ID"],
        "details": {
            "checks": {
                "configuration": "ok",
                "database": "error",
                "redis": "ok",
            }
        },
    }
    assert "connection details" not in response.text


def test_application_closes_dependencies(
    test_settings: Settings,
) -> None:
    database = FakeHealthDependency(name="database")
    redis = FakeHealthDependency(name="redis")
    runtime = RuntimeContext(dependencies=(database, redis))

    with TestClient(create_app(test_settings, runtime)):
        pass

    assert database.close_calls == 1
    assert redis.close_calls == 1


def test_valid_caller_request_id_is_propagated(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "client-request_123"},
    )

    assert response.headers["X-Request-ID"] == "client-request_123"


def test_unsafe_caller_request_id_is_replaced(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "unsafe request id"},
    )

    request_id = response.headers["X-Request-ID"]
    assert request_id != "unsafe request id"
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)

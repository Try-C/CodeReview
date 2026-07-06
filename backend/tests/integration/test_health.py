"""Integration tests for liveness, readiness, and request IDs."""

import re

from fastapi.testclient import TestClient


def test_live_health(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "CodeReview Agent",
        "version": "0.1.0",
    }
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_ready_health_reports_current_checks(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "CodeReview Agent",
        "version": "0.1.0",
        "checks": {"configuration": "ok"},
    }


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

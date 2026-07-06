"""Unit tests for structured log serialization."""

import json
import logging

from app.core.logging import (
    JsonFormatter,
    RequestContextFilter,
    bind_request_id,
    reset_request_id,
)


def test_json_formatter_includes_context_and_structured_fields() -> None:
    token = bind_request_id("request-123")
    try:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="request completed",
            args=(),
            exc_info=None,
        )
        record.status_code = 200

        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_request_id(token)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "request completed"
    assert payload["request_id"] == "request-123"
    assert payload["status_code"] == 200
    assert payload["timestamp"].endswith("+00:00")


def test_request_context_filter_supplies_id_for_text_logs() -> None:
    token = bind_request_id("request-456")
    try:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="application started",
            args=(),
            exc_info=None,
        )

        accepted = RequestContextFilter().filter(record)
    finally:
        reset_request_id(token)

    assert accepted is True
    assert record.__dict__["request_id"] == "request-456"

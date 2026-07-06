import json
import logging

logger = logging.getLogger(__name__)


def parse_config(raw: str) -> dict:
    """Safe: specific exception handling with logging."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Invalid config JSON: %s", e)
        return {}

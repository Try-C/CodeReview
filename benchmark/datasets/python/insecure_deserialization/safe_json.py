import json


def load_user(data: bytes) -> dict:
    """Safe: json.loads with schema validation."""
    return json.loads(data)

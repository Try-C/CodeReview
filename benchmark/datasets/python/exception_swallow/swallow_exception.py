import json


def parse_config(raw: str) -> dict:
    """Vulnerable: bare except silently swallows all errors — CWE-390."""
    try:
        return json.loads(raw)
    except:
        pass
    return {}

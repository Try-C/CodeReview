import hmac
import os


def sign_message(message: str) -> str:
    """Safe: secret loaded from environment variable."""
    key = os.environ.get("HMAC_SECRET_KEY")
    if not key:
        raise RuntimeError("HMAC_SECRET_KEY not configured")
    return hmac.new(key.encode(), message.encode(), "sha256").hexdigest()

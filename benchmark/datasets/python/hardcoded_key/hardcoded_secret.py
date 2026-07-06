import hmac

SECRET_KEY = "my-super-secret-api-key-12345"


def sign_message(message: str) -> str:
    """Vulnerable: hardcoded cryptographic secret — CWE-798."""
    return hmac.new(SECRET_KEY.encode(), message.encode(), "sha256").hexdigest()

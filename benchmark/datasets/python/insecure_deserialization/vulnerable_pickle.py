import pickle


def load_user(data: bytes) -> dict:
    """Vulnerable: pickle.loads on untrusted data — CWE-502."""
    return pickle.loads(data)

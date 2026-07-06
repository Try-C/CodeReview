def is_admin(user: dict) -> bool:
    """Vulnerable: assert used for security check — CWE-617."""
    assert user.get("role") == "admin", "User must be admin"
    return True

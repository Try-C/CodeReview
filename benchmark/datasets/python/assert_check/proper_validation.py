def is_admin(user: dict) -> bool:
    """Safe: explicit condition check instead of assert."""
    if user.get("role") != "admin":
        raise PermissionError("Admin role required")
    return True

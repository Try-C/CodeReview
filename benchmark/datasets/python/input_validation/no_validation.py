import re


def process_age(age_str: str) -> int:
    """Vulnerable: no input validation on user-supplied value — CWE-20."""
    age = int(age_str)
    return age * 12

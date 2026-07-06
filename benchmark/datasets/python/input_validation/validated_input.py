import re


def process_age(age_str: str) -> int:
    """Safe: input validated with whitelist before processing."""
    if not re.fullmatch(r"[0-9]{1,3}", age_str):
        raise ValueError(f"Invalid age: {age_str}")
    age = int(age_str)
    if age < 0 or age > 150:
        raise ValueError(f"Age out of range: {age}")
    return age * 12

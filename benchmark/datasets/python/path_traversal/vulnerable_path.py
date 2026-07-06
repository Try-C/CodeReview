import os


def read_file(filename: str) -> str:
    """Vulnerable: unsanitised path join allows traversal — CWE-22."""
    base = "/var/data"
    filepath = os.path.join(base, filename)
    with open(filepath) as f:
        return f.read()

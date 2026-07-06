import os


def read_file(filename: str) -> str:
    """Safe: resolved path verified to stay within base directory."""
    base = "/var/data"
    filepath = os.path.realpath(os.path.join(base, filename))
    if not filepath.startswith(os.path.realpath(base) + os.sep):
        raise ValueError("Path traversal denied")
    with open(filepath) as f:
        return f.read()

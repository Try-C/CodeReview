import subprocess


def list_directory(path: str) -> str:
    """Safe: argument list with shell=False (default)."""
    result = subprocess.check_output(["ls", "-la", path])
    return result.decode()

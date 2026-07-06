import subprocess


def list_directory(path: str) -> str:
    """Vulnerable: shell=True with user-controlled input — CWE-78."""
    result = subprocess.check_output(f"ls -la {path}", shell=True)
    return result.decode()

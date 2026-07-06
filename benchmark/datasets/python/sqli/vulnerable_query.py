import sqlite3


def find_user(username: str) -> list:
    """Vulnerable: user input interpolated directly into SQL — CWE-89."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchall()

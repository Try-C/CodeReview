import sqlite3


def find_user(username: str) -> list:
    """Safe: parameterised query prevents SQL injection."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    return cursor.fetchall()

"""Database repository with SQL injection vulnerability."""

import sqlite3
from typing import Any


class UserRepository:
    """Repository for user data access."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path)
        return self._connection

    def find_by_name(self, name: str) -> list[dict[str, Any]]:
        """Find users by name.
        
        VULNERABILITY: SQL injection (CQ-004)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # VULNERABLE: Direct string interpolation
        query = f"SELECT * FROM users WHERE name = '{name}'"
        cursor.execute(query)

        return [dict(row) for row in cursor.fetchall()]

    def find_by_id(self, user_id: int) -> dict[str, Any] | None:
        """Find user by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # SAFE: Parameterized query
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()

        return dict(row) if row else None

    def search_users(self, filters: dict[str, str]) -> list[dict[str, Any]]:
        """Search users with multiple filters.
        
        VULNERABILITY: SQL injection in dynamic query building
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        conditions = []
        for key, value in filters.items():
            conditions.append(f"{key} = '{value}'")  # VULNERABLE

        where_clause = " AND ".join(conditions)
        query = f"SELECT * FROM users WHERE {where_clause}"

        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]

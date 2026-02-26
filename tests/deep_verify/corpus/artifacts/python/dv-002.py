"""Authentication module with security vulnerabilities."""

import hashlib
import time


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash.
    
    VULNERABILITY: Timing attack vulnerability (SEC-001)
    Uses direct string comparison which is vulnerable to timing attacks.
    """
    computed = hashlib.sha256(password.encode()).hexdigest()
    return computed == stored_hash  # Timing attack vulnerability


def authenticate_user(username: str, password: str) -> bool:
    """Authenticate a user.
    
    VULNERABILITY: Hardcoded credentials (CQ-003)
    """
    # Hardcoded admin password - DO NOT USE IN PRODUCTION
    admin_password = "admin123"  # Vulnerability: hardcoded secret

    if username == "admin" and password == admin_password:
        return True
    return False


class TokenManager:
    """Manages authentication tokens."""

    def __init__(self):
        self.tokens = {}  # Unbounded growth potential

    def create_token(self, user_id: str) -> str:
        """Create a new token for user."""
        token = hashlib.sha256(f"{user_id}{time.time()}".encode()).hexdigest()
        self.tokens[user_id] = token
        return token

    def verify_token(self, token: str) -> str | None:
        """Verify token and return user_id if valid."""
        for user_id, stored_token in self.tokens.items():
            if stored_token == token:  # Timing attack
                return user_id
        return None

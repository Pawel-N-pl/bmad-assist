"""URL and token masking utilities for notification providers.

Centralizes credential masking to prevent leakage in logs and tracebacks.
"""

import logging

logger = logging.getLogger(__name__)

__all__ = ["mask_url", "mask_token"]

# Default prefix lengths
# Discord webhook: https://discord.com/api/webhooks/{id}/{token} - domain+path is ~37 chars
# Use 40 to show service identifier without exposing token
URL_PREFIX_LENGTH = 40
TOKEN_PREFIX_LENGTH = 5


def mask_url(url: str | None, prefix_length: int = URL_PREFIX_LENGTH) -> str:
    """Mask URL showing only prefix, with smart marker detection.

    For known API patterns (Discord webhooks, Telegram bot), masks after
    the identifying path segment to ensure tokens are never exposed.

    SECURITY: Markers must be in PATH (after ://host/), not in domain.
    F5 FIX: Prevents false match on domains like "mybot.example.com".
    F7 FIX: Short URLs show scheme+domain, not just "***".

    Args:
        url: URL to mask, or None.
        prefix_length: Characters to show before '***' (fallback if no marker found).

    Returns:
        Masked URL (e.g., "https://discord.com/api/webhooks/***") or "(not configured)".

    Examples:
        >>> mask_url("https://discord.com/api/webhooks/123456/abcdef")
        'https://discord.com/api/webhooks/***'
        >>> mask_url("https://api.telegram.org/bot123:ABC/sendMessage")
        'https://api.telegram.org/bot***'
        >>> mask_url("https://mybot.example.com/secret")  # F5: /bot in domain, not path
        'https://mybot.example.com/***'
        >>> mask_url("http://x.co/s")  # F7: show scheme+domain
        'http://x.co/***'
        >>> mask_url(None)
        '(not configured)'
    """
    if not url:
        return "(not configured)"

    # F7 FIX: Find path start (after scheme://host)
    # This ensures we can always show at least scheme+domain
    path_start = url.find("://")
    if path_start != -1:
        path_start = url.find("/", path_start + 3)  # Find first / after ://
    if path_start == -1:
        path_start = len(url)  # No path, entire URL is domain

    # Smart marker detection - mask after known API path segments
    # F5 FIX: Only match markers AFTER path_start (not in domain)
    markers = ["/webhooks/", "/bot"]
    for marker in markers:
        idx = url.find(marker, path_start)  # Search only in path portion
        if idx != -1:
            # Show up to and including the marker, then mask
            return f"{url[:idx + len(marker)]}***"

    # F7 FIX: For short URLs, show scheme+domain+/*** instead of just ***
    if len(url) <= prefix_length:
        if path_start < len(url):
            return f"{url[:path_start + 1]}***"  # scheme://domain/***
        return f"{url}***"  # No path, just append ***

    return f"{url[:prefix_length]}***"


def mask_token(token: str | None, prefix_length: int = TOKEN_PREFIX_LENGTH) -> str:
    """Mask token showing only prefix.

    Args:
        token: Token to mask, or None.
        prefix_length: Characters to show before '***'.

    Returns:
        Masked token (e.g., "12345***") or "(not configured)".

    Examples:
        >>> mask_token("123456789:ABCdefGHI")
        '12345***'
        >>> mask_token(None)
        '(not configured)'
    """
    if not token:
        return "(not configured)"
    if len(token) <= prefix_length:
        return "***"
    return f"{token[:prefix_length]}***"

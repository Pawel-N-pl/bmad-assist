"""Time formatting utilities for project tree generation."""

import time


def format_relative_time(timestamp: float, now: float | None = None) -> str:
    """Format a Unix timestamp as relative time string.

    Args:
        timestamp: Unix timestamp (from stat().st_mtime)
        now: Optional reference timestamp (defaults to current time)

    Returns:
        Formatted string like "(20s ago)", "(5m 30s ago)", "(2h 15m ago)",
        "(3d ago)", or "(1y ago)"

    Edge cases:
        - Future timestamp → "(just now)"
        - Timestamp = 0 (epoch) → "(unknown)"

    """
    if timestamp == 0:
        return "(unknown)"

    if now is None:
        now = time.time()

    diff = now - timestamp

    if diff < 0:
        # Future timestamp
        return "(just now)"

    if diff < 60:
        # Less than 60 seconds
        return f"({int(diff)}s ago)"

    if diff < 3600:
        # Less than 60 minutes
        minutes = int(diff // 60)
        seconds = int(diff % 60)
        if seconds > 0:
            return f"({minutes}m {seconds}s ago)"
        return f"({minutes}m ago)"

    if diff < 86400:
        # Less than 24 hours
        hours = int(diff // 3600)
        minutes = int((diff % 3600) // 60)
        if minutes > 0:
            return f"({hours}h {minutes}m ago)"
        return f"({hours}h ago)"

    if diff < 2592000:
        # Less than 30 days
        days = int(diff // 86400)
        return f"({days}d ago)"

    if diff < 31536000:
        # Less than 365 days
        days = int(diff // 86400)
        return f"({days}d ago)"

    # 365 days or more
    years = int(diff // 31536000)
    return f"({years}y ago)"

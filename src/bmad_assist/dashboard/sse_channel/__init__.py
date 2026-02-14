"""SSE channel package for multi-project dashboard.

Provides per-project SSE streaming with:
- Bounded queues and backpressure
- DASHBOARD_EVENT parsing
- Channel management

Based on design document: docs/multi-project-dashboard.md Section 6
"""

from .channel import SSEChannel, SSEChannelManager, SSEEvent
from .event_parser import ParsedEvent, parse_line, parse_lines

__all__ = [
    "ParsedEvent",
    "SSEChannel",
    "SSEChannelManager",
    "SSEEvent",
    "parse_line",
    "parse_lines",
]

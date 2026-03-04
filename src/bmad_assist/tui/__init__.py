"""TUI abstraction layer for bmad-assist.

Provides a pluggable Renderer protocol with two implementations:
- PlainRenderer: stdout/Rich logging (CI, pipes, --plain)
- InteractiveRenderer: future TUI (Stories 30.2-30.6)

The get_renderer() factory handles TTY auto-detection.
"""

from __future__ import annotations

import sys

from bmad_assist.tui.interactive import InteractiveRenderer
from bmad_assist.tui.plain import PlainRenderer
from bmad_assist.tui.protocol import Renderer

__all__ = [
    "InteractiveRenderer",
    "PlainRenderer",
    "Renderer",
    "get_renderer",
]


def get_renderer(*, plain: bool = False) -> PlainRenderer | InteractiveRenderer:
    """Create the appropriate renderer based on TTY detection.

    Args:
        plain: If True, always return PlainRenderer regardless of TTY.

    Returns:
        PlainRenderer for CI/pipes/--plain, InteractiveRenderer for TTY.

    """
    if plain:
        return PlainRenderer()

    # Defensive: stdout may be None in some environments (GUI apps, etc.)
    stdout = sys.stdout
    if stdout is None or not stdout.isatty():
        return PlainRenderer()

    return InteractiveRenderer()

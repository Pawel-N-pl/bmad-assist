"""XML formatter for project tree generation."""

import html
import logging
from pathlib import Path

from bmad_assist.core.project_tree.time_format import format_relative_time
from bmad_assist.core.project_tree.types import TreeEntry

logger = logging.getLogger(__name__)

# Token estimation: 4 chars per token
CHARS_PER_TOKEN = 4


class TreeFormatter:
    """Formatter for generating XML project tree output."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the formatter.

        Args:
            project_root: Root directory of the project

        """
        self.project_root = project_root

    def _escape_filename(self, name: str) -> str:
        """Escape filename for XML.

        Args:
            name: Filename to escape

        Returns:
            XML-escaped filename

        """
        return html.escape(name, quote=True)

    def _format_entry(self, entry: TreeEntry) -> str:
        """Format a single tree entry as string.

        Args:
            entry: TreeEntry to format

        Returns:
            Formatted string with indentation

        """
        indent = "  " * entry.depth
        escaped_name = self._escape_filename(entry.name)

        if entry.is_dir:
            # Directory ends with /
            return f"{indent}{escaped_name}/"
        else:
            # File with relative time
            # Special case for truncation indicator
            if entry.name.startswith("(+" ) and entry.name.endswith(" more)"):
                return f"{indent}{escaped_name}"
            else:
                time_str = format_relative_time(entry.mtime)
                return f"{indent}{escaped_name} {time_str}"

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count

        """
        return len(text) // CHARS_PER_TOKEN

    def format_tree(self, entries: list[TreeEntry], token_budget: int) -> str:
        """Format tree entries as XML with token budget enforcement.

        Args:
            entries: List of tree entries to format
            token_budget: Maximum tokens allowed

        Returns:
            XML formatted tree string, possibly truncated

        """
        lines: list[str] = ["<project-tree>"]
        current_tokens = self._estimate_tokens(lines[0])

        for entry in entries:
            formatted = self._format_entry(entry)
            entry_tokens = self._estimate_tokens(formatted)

            # Check if adding this entry would exceed budget
            if current_tokens + entry_tokens > token_budget:
                # Add truncation indicator
                lines.append("[truncated]")
                lines.append("</project-tree>")
                return "\n".join(lines)

            lines.append(formatted)
            current_tokens += entry_tokens

        lines.append("</project-tree>")
        return "\n".join(lines)

    def format_tree_streaming(
        self,
        entries: list[TreeEntry],
        token_budget: int,
    ) -> str:
        """Format tree entries with streaming budget checks.

        This is an alternative implementation that processes entries
        in batches and handles truncation gracefully.

        Args:
            entries: List of tree entries to format
            token_budget: Maximum tokens allowed

        Returns:
            XML formatted tree string, possibly truncated

        """
        # Start with opening tag
        result_parts: list[str] = ["<project-tree>"]
        current_tokens = self._estimate_tokens("<project-tree>")
        budget_exceeded = False

        for entry in entries:
            if budget_exceeded:
                break

            formatted = self._format_entry(entry)
            entry_tokens = self._estimate_tokens(formatted)

            # Check budget before adding
            if current_tokens + entry_tokens > token_budget:
                budget_exceeded = True
                break

            result_parts.append(formatted)
            current_tokens += entry_tokens

        # Add truncation indicator if needed
        if budget_exceeded:
            result_parts.append("[truncated]")

        # Close tag
        result_parts.append("</project-tree>")

        return "\n".join(result_parts)

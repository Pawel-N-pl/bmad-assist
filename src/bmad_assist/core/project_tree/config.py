"""Configuration for the project tree generator."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ProjectTreeConfig:
    """Runtime configuration for project tree generation.

    This is a runtime config populated from strategic_context.tree_budget -
    NOT a standalone YAML config. The single source of truth is
    strategic_context.tree_budget in user-facing YAML config.

    Attributes:
        tree_budget: Maximum tokens for the project tree output
        max_files_per_dir: Maximum files to list per directory (default: 20)
        max_depth: Maximum directory depth to traverse (default: 100)
        follow_symlinks: Whether to follow symlinks (always False for security)
        time_format: Format for timestamps (always "relative" for now)

    """

    tree_budget: int
    max_files_per_dir: int = 20
    max_depth: int = 100
    follow_symlinks: bool = False
    time_format: Literal["relative"] = "relative"

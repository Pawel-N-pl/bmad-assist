"""High-level service for project tree generation."""

import logging
from typing import TYPE_CHECKING

from bmad_assist.core.paths import ProjectPaths
from bmad_assist.core.project_tree.config import ProjectTreeConfig
from bmad_assist.core.project_tree.formatter import TreeFormatter
from bmad_assist.core.project_tree.gitignore import GitignoreParser
from bmad_assist.core.project_tree.types import TreeEntry
from bmad_assist.core.project_tree.walker import TreeWalker

if TYPE_CHECKING:
    from bmad_assist.core.config.models.main import Config

logger = logging.getLogger(__name__)


class ProjectTreeService:
    """High-level service for generating project tree XML.

    Orchestrates gitignore parsing, tree walking, and XML formatting
    to produce a project tree suitable for inclusion in workflow prompts.
    """

    def __init__(self, config: "Config", paths: ProjectPaths) -> None:
        """Initialize the service.

        Args:
            config: Main bmad-assist configuration
            paths: Project paths singleton

        """
        self.config = config
        self.paths = paths

    def _get_tree_budget(self, workflow_name: str | None = None) -> int:
        """Get the token budget for project tree generation.

        Args:
            workflow_name: Optional workflow name for per-workflow budgets

        Returns:
            Token budget (0 if disabled)

        """
        # Check if strategic_context is configured
        if not hasattr(self.config, "compiler"):
            logger.debug("compiler config not available, project tree disabled")
            return 0

        strategic_ctx = self.config.compiler.strategic_context
        if strategic_ctx is None:
            logger.debug("strategic_context not configured, project tree disabled")
            return 0

        # Get tree_budget (defaults to 10000 if not set)
        tree_budget = getattr(strategic_ctx, "tree_budget", 10000)

        # Check if project-tree is in include list for this workflow
        include, _ = strategic_ctx.get_workflow_config(workflow_name or "default")

        if "project-tree" not in include:
            logger.debug("project-tree not in include list for workflow %s", workflow_name)
            return 0

        return tree_budget

    def generate_tree(self, workflow_name: str | None = None) -> str:
        """Generate project tree XML for the given workflow.

        Args:
            workflow_name: Optional workflow name for per-workflow configuration

        Returns:
            XML formatted project tree, or empty string if disabled

        """
        budget = self._get_tree_budget(workflow_name)

        if budget <= 0:
            logger.debug("Project tree generation disabled or budget is 0")
            return ""

        # Create runtime config
        tree_config = ProjectTreeConfig(tree_budget=budget)

        # Initialize components
        gitignore = GitignoreParser(self.paths.project_root)
        walker = TreeWalker(self.paths.project_root, tree_config, gitignore)
        formatter = TreeFormatter(self.paths.project_root)

        # Collect all entries
        entries: list[TreeEntry] = []
        try:
            for entry in walker.walk():
                entries.append(entry)
        except Exception as e:
            logger.error(f"Error walking project tree: {e}")
            return ""

        if not entries:
            logger.debug("No entries found in project tree")
            return ""

        # Format as XML with budget enforcement
        return formatter.format_tree(entries, budget)

    def is_enabled(self, workflow_name: str | None = None) -> bool:
        """Check if project tree is enabled for the given workflow.

        Args:
            workflow_name: Optional workflow name to check

        Returns:
            True if project tree is enabled, False otherwise

        """
        return self._get_tree_budget(workflow_name) > 0

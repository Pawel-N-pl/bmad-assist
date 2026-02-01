"""Compiler for the testarch-test-review workflow.

This module implements the WorkflowCompiler protocol for the testarch-test-review
workflow, producing standalone prompts for test quality review.

The test review workflow validates tests against best practices for maintainability,
determinism, isolation, and flakiness prevention.

Public API:
    TestarchTestReviewCompiler: Workflow compiler class implementing WorkflowCompiler protocol
"""

import logging
from pathlib import Path
from typing import Any

from bmad_assist.compiler.shared_utils import (
    safe_read_file,
)
from bmad_assist.compiler.types import CompilerContext, WorkflowIR
from bmad_assist.compiler.workflows.testarch_base import TestarchTriModalCompiler
from bmad_assist.core.exceptions import CompilerError

logger = logging.getLogger(__name__)

# Maximum number of test files to include in context
_MAX_TEST_FILES = 20


class TestarchTestReviewCompiler(TestarchTriModalCompiler):
    """Compiler for the testarch-test-review workflow.

    Extends TestarchTriModalCompiler to add test-review-specific features:
    - Test file discovery and inclusion in context
    - Story file context for test coverage validation

    Context embedding follows recency-bias ordering:
    1. project_context.md (general rules)
    2. story file (test context)
    3. test files (most relevant for review)

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "testarch-test-review"

    def get_variables(self) -> dict[str, Any]:
        """Return test-review-specific variables.

        Returns:
            Variables needed for testarch-test-review compilation.

        """
        base_vars = super().get_variables()
        base_vars.update({
            "test_dir": None,
            "project_path": None,
        })
        return base_vars

    def validate_context(self, context: CompilerContext) -> None:
        """Validate context before compilation.

        Test review requires story_num (story-level workflow).

        Args:
            context: The compilation context to validate.

        Raises:
            CompilerError: If required context is missing.

        """
        # Call parent validation first
        super().validate_context(context)

        # Test review requires story_num (it's a story-level workflow)
        story_num = context.resolved_variables.get("story_num")
        if story_num is None:
            raise CompilerError(
                "story_num is required for testarch-test-review compilation.\n"
                "  Suggestion: Provide story_num via invocation params"
            )

    def _get_workflow_specific_variables(
        self,
        resolved: dict[str, Any],
        context: CompilerContext,
        workflow_ir: WorkflowIR,
    ) -> None:
        """Add test-review-specific variables.

        Resolves test_dir and project_path variables.

        Args:
            resolved: Resolved variables dict (modified in place).
            context: Compilation context.
            workflow_ir: Workflow IR.

        """
        # Resolve test_dir from workflow.yaml variables
        workflow_vars = workflow_ir.raw_config.get("variables", {})
        test_dir = workflow_vars.get("test_dir", "{project-root}/tests")
        test_dir = test_dir.replace("{project-root}", str(context.project_root))
        resolved["test_dir"] = test_dir
        resolved["project_path"] = str(context.project_root)

        # Override story_id format for test review (uses dash, not dot)
        epic_num = resolved.get("epic_num")
        story_num = resolved.get("story_num")
        if epic_num is not None and story_num is not None:
            resolved["story_id"] = f"{epic_num}-{story_num}"

    def _build_context_files(
        self,
        context: CompilerContext,
        resolved: dict[str, Any],
    ) -> dict[str, str]:
        """Build context files with test-review-specific additions.

        For test review workflow:
        1. project_context.md (general rules)
        2. story file (test context)
        3. test files (most relevant for review)

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables.

        Returns:
            Dictionary mapping file paths to content.

        """
        # Get base context files (project_context + story file)
        files = super()._build_context_files(context, resolved)

        # Add test files
        epic_num = resolved.get("epic_num")
        story_num = resolved.get("story_num")
        test_files = self._discover_test_files(context, epic_num, story_num)

        for test_file in test_files:
            content = safe_read_file(test_file, context.project_root)
            if content:
                files[str(test_file)] = content

        return files

    def _discover_test_files(
        self,
        context: CompilerContext,
        epic_num: Any,
        story_num: Any,
    ) -> list[Path]:
        """Discover test files relevant to the story.

        Uses multiple patterns to find tests:
        1. tests/**/*{epic_num}-{story_num}*.py (e.g., test_testarch-9_*.py)
        2. tests/**/*{epic_num}_{story_num}*.py (e.g., test_testarch_9_*.py)
        3. Fallback: tests/**/*.py limited to 20 most recently modified files

        Args:
            context: Compilation context with paths.
            epic_num: Epic number (e.g., "testarch", 1, 2).
            story_num: Story number (e.g., "9", 1, 2).

        Returns:
            List of Path objects for discovered test files.

        """
        tests_dir = context.project_root / "tests"
        if not tests_dir.exists():
            logger.warning("Tests directory not found: %s", tests_dir)
            return []

        # Try story-specific patterns first
        story_patterns = [
            f"**/*{epic_num}-{story_num}*.py",
            f"**/*{epic_num}_{story_num}*.py",
        ]

        for pattern in story_patterns:
            matches = list(tests_dir.glob(pattern))
            if matches:
                logger.debug("Found %d test files matching pattern %s", len(matches), pattern)
                return sorted(matches)[:_MAX_TEST_FILES]

        # Fallback: get most recently modified test files
        all_test_files = list(tests_dir.glob("**/*.py"))
        if not all_test_files:
            logger.warning("No test files found in %s (non-blocking)", tests_dir)
            return []

        # Sort by modification time (most recent first)
        all_test_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        selected = all_test_files[:_MAX_TEST_FILES]
        logger.debug("Using fallback: %d most recently modified test files", len(selected))
        return selected

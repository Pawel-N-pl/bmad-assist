"""Compiler for the testarch-atdd workflow.

This module implements the WorkflowCompiler protocol for the testarch-atdd
workflow, producing standalone prompts for ATDD (Acceptance Test Driven
Development) workflow execution.

The ATDD workflow generates failing acceptance tests before implementation
using the TDD red-green-refactor cycle.

Public API:
    TestarchAtddCompiler: Workflow compiler class implementing WorkflowCompiler protocol
"""

import logging
from pathlib import Path
from typing import Any

from bmad_assist.compiler.shared_utils import safe_read_file
from bmad_assist.compiler.types import CompilerContext, WorkflowIR
from bmad_assist.compiler.workflows.testarch_base import TestarchTriModalCompiler
from bmad_assist.core.exceptions import CompilerError

logger = logging.getLogger(__name__)


class TestarchAtddCompiler(TestarchTriModalCompiler):
    """Compiler for the testarch-atdd workflow.

    Extends TestarchTriModalCompiler to add ATDD-specific features:
    - test-design-epic file inclusion in context
    - test_dir variable resolution from workflow.yaml

    Context embedding follows recency-bias ordering:
    1. project_context.md (general)
    2. test-design-epic (P0/P1/P2 priorities)
    3. story file (specific - most relevant for ATDD)

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "testarch-atdd"

    def get_variables(self) -> dict[str, Any]:
        """Return ATDD-specific variables.

        Returns:
            Variables needed for testarch-atdd compilation.

        """
        base_vars = super().get_variables()
        base_vars["test_dir"] = None  # From workflow.yaml variables
        return base_vars

    def validate_context(self, context: CompilerContext) -> None:
        """Validate context before compilation.

        ATDD requires story_num (story-level workflow).

        Args:
            context: The compilation context to validate.

        Raises:
            CompilerError: If required context is missing.

        """
        # Call parent validation first
        super().validate_context(context)

        # ATDD requires story_num (it's a story-level workflow)
        story_num = context.resolved_variables.get("story_num")
        if story_num is None:
            raise CompilerError(
                "story_num is required for testarch-atdd compilation.\n"
                "  Suggestion: Provide story_num via invocation params"
            )

    def _get_workflow_specific_variables(
        self,
        resolved: dict[str, Any],
        context: CompilerContext,
        workflow_ir: WorkflowIR,
    ) -> None:
        """Add ATDD-specific variables.

        Resolves test_dir from workflow.yaml variables section.

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

    def _build_context_files(
        self,
        context: CompilerContext,
        resolved: dict[str, Any],
    ) -> dict[str, str]:
        """Build context files with ATDD-specific additions.

        Adds test-design-epic file to base context for P0/P1/P2 priorities.

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables.

        Returns:
            Dictionary mapping file paths to content.

        """
        # Get base context files (project_context + story file)
        files = super()._build_context_files(context, resolved)

        # Add test-design-epic if exists (P0/P1/P2 test priorities)
        epic_num = resolved.get("epic_num")
        if epic_num:
            test_design_pattern = f"*test-design-epic*{epic_num}*.md"
            test_design_path = self._find_test_design_file(context, test_design_pattern)
            if test_design_path:
                content = safe_read_file(test_design_path, context.project_root)
                if content:
                    files[str(test_design_path)] = content
                    logger.debug("Embedded test-design-epic: %s", test_design_path)

        return files

    def _find_test_design_file(
        self,
        context: CompilerContext,
        pattern: str,
    ) -> Path | None:
        """Find test-design file in output folder.

        Args:
            context: Compilation context with paths.
            pattern: Glob pattern to match.

        Returns:
            Path to test-design file or None if not found.

        """
        output_folder = context.output_folder
        if not output_folder or not output_folder.exists():
            return None

        # Search in implementation-artifacts first, then planning-artifacts
        for subdir in ["implementation-artifacts", "planning-artifacts", ""]:
            search_dir = output_folder / subdir if subdir else output_folder
            if search_dir.exists():
                matches = sorted(search_dir.glob(pattern))
                if matches:
                    return matches[0]

        return None

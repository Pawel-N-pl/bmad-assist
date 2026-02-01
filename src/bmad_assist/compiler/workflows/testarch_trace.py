"""Compiler for the testarch-trace workflow.

This module implements the WorkflowCompiler protocol for the testarch-trace
workflow, producing standalone prompts for generating traceability matrices
and making quality gate decisions (PASS/CONCERNS/FAIL/WAIVED).

The trace workflow runs on epic completion and maps requirements to tests.

Public API:
    TestarchTraceCompiler: Workflow compiler class implementing WorkflowCompiler protocol
"""

import logging
from pathlib import Path
from typing import Any

from bmad_assist.compiler.shared_utils import (
    find_project_context_file,
    get_epics_dir,
    get_stories_dir,
    safe_read_file,
)
from bmad_assist.compiler.types import CompilerContext, WorkflowIR
from bmad_assist.compiler.workflows.testarch_base import TestarchTriModalCompiler

logger = logging.getLogger(__name__)


class TestarchTraceCompiler(TestarchTriModalCompiler):
    """Compiler for the testarch-trace workflow.

    Extends TestarchTriModalCompiler to add trace-specific features:
    - Epic file and all story files inclusion in context
    - test_dir, source_dir, gate_type variable resolution

    Context embedding follows recency-bias ordering:
    1. project_context.md (general)
    2. epic file (overview)
    3. all stories in epic (for complete traceability)

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "testarch-trace"

    def get_required_files(self) -> list[str]:
        """Return list of required file glob patterns.

        Returns:
            Glob patterns for files needed by testarch-trace workflow.

        """
        return [
            "**/project_context.md",
            "**/project-context.md",
            "**/epic*.md",
        ]

    def get_variables(self) -> dict[str, Any]:
        """Return workflow-specific variables.

        Returns:
            Variables needed for testarch-trace compilation.

        """
        base_vars = super().get_variables()
        base_vars.update({
            "test_dir": None,  # From workflow.yaml variables
            "source_dir": None,  # From workflow.yaml variables
            "gate_type": None,  # story|epic|release|hotfix
        })
        return base_vars

    def _get_workflow_specific_variables(
        self,
        resolved: dict[str, Any],
        context: CompilerContext,
        workflow_ir: WorkflowIR,
    ) -> None:
        """Add trace-specific variables.

        Resolves test_dir, source_dir, and gate_type from workflow.yaml.

        Args:
            resolved: Resolved variables dict (modified in place).
            context: Compilation context.
            workflow_ir: Workflow IR.

        """
        workflow_vars = workflow_ir.raw_config.get("variables", {})

        test_dir = workflow_vars.get("test_dir", "{project-root}/tests")
        test_dir = test_dir.replace("{project-root}", str(context.project_root))
        resolved["test_dir"] = test_dir

        source_dir = workflow_vars.get("source_dir", "{project-root}/src")
        source_dir = source_dir.replace("{project-root}", str(context.project_root))
        resolved["source_dir"] = source_dir

        gate_type = workflow_vars.get("gate_type", "epic")
        resolved["gate_type"] = gate_type

    def _build_context_files(
        self,
        context: CompilerContext,
        resolved: dict[str, Any],
    ) -> dict[str, str]:
        """Build context files with trace-specific additions.

        For trace workflow:
        1. project_context.md (general rules)
        2. epic file (overview)
        3. all stories in epic for complete traceability

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables.

        Returns:
            Dictionary mapping file paths to content.

        """
        files: dict[str, str] = {}
        project_root = context.project_root

        # 1. Project context (general)
        project_context_path = find_project_context_file(context)
        if project_context_path:
            content = safe_read_file(project_context_path, project_root)
            if content:
                files[str(project_context_path)] = content

        # 2. Epic file (overview)
        epic_num = resolved.get("epic_num")
        if epic_num:
            epic_path = self._find_epic_file(context, epic_num)
            if epic_path:
                content = safe_read_file(epic_path, project_root)
                if content:
                    files[str(epic_path)] = content

            # 3. All stories in epic for complete traceability
            stories_dir = get_stories_dir(context)
            if stories_dir.exists():
                pattern = f"{epic_num}-*-*.md"
                story_files = sorted(stories_dir.glob(pattern))
                for story_path in story_files:
                    content = safe_read_file(story_path, project_root)
                    if content:
                        files[str(story_path)] = content
                if story_files:
                    logger.debug(
                        "Loaded %d story files for epic %s",
                        len(story_files),
                        epic_num,
                    )

        return files

    def _find_epic_file(
        self,
        context: CompilerContext,
        epic_num: Any,
    ) -> Path | None:
        """Find epic file by epic number.

        Args:
            context: Compilation context with paths.
            epic_num: Epic number.

        Returns:
            Path to epic file or None if not found.

        """
        epics_dir = get_epics_dir(context)
        if not epics_dir.exists():
            return None

        pattern = f"epic-{epic_num}*.md"
        matches = sorted(epics_dir.glob(pattern))

        if not matches:
            logger.debug("No epic file found matching %s in %s", pattern, epics_dir)
            return None

        return matches[0]

    def _build_mission(
        self,
        workflow_ir: WorkflowIR,
        resolved: dict[str, Any],
    ) -> str:
        """Build mission description for trace workflow.

        Args:
            workflow_ir: Workflow IR with description.
            resolved: Resolved variables.

        Returns:
            Mission description string.

        """
        base_description = workflow_ir.raw_config.get(
            "description", "Generate requirements-to-tests traceability matrix"
        )

        mode = resolved.get("workflow_mode", "c")
        mode_name = {"c": "Create", "v": "Validate", "e": "Edit"}.get(mode, mode)

        epic_num = resolved.get("epic_num", "?")
        gate_type = resolved.get("gate_type", "epic")

        mission = (
            f"{base_description}\n\n"
            f"Mode: {mode_name}\n"
            f"Target: Epic {epic_num}\n"
            f"Gate Type: {gate_type}\n"
            f"Analyze test coverage and make quality gate decision."
        )

        return mission

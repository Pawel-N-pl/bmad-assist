"""Compiler for the hardening workflow.

This module implements the WorkflowCompiler protocol for the hardening
workflow, producing standalone prompts for generating the hardening story
based on the latest retrospective report action items.

Public API:
    HardeningCompiler: Workflow compiler class implementing WorkflowCompiler protocol
"""

import logging
from pathlib import Path
from typing import Any

from bmad_assist.compiler.filtering import filter_instructions
from bmad_assist.compiler.output import generate_output
from bmad_assist.compiler.shared_utils import (
    apply_post_process,
    context_snapshot,
    find_sprint_status_file,
    safe_read_file,
)
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext
from bmad_assist.compiler.variable_utils import substitute_variables
from bmad_assist.compiler.variables import resolve_variables
from bmad_assist.core.exceptions import CompilerError

logger = logging.getLogger(__name__)


class HardeningCompiler:
    """Compiler for the hardening workflow.

    Implements the WorkflowCompiler protocol to compile the hardening
    workflow into a standalone prompt.

    Context focused on:
    1. Latest Retrospective Report (CRITICAL)
    2. Sprint Status (for context)

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "hardening"

    def get_required_files(self) -> list[str]:
        """Return list of required file glob patterns.

        Returns:
            Glob patterns for files needed by hardening workflow.
            Mainly needs the retrospective report.

        """
        return [
            "**/retrospectives/epic-*-retro-*.md",
            "**/sprint-status.yaml",
        ]

    def get_variables(self) -> dict[str, Any]:
        """Return workflow-specific variables to resolve.

        Returns:
            Variables needed for hardening compilation.

        """
        return {
            "epic_num": None,  # Required - current epic whose retro we consume
            "next_epic_id": None,  # Computed - next epic for the hardening story
            "date": None,
        }

    def get_workflow_dir(self, context: CompilerContext) -> Path:
        """Return the workflow directory for this compiler.

        Args:
            context: The compilation context with project paths.

        Returns:
            Path to the workflow directory containing workflow.yaml.

        Raises:
            CompilerError: If workflow directory not found.

        """
        from bmad_assist.compiler.workflow_discovery import (
            discover_workflow_dir,
            get_workflow_not_found_message,
        )

        workflow_dir = discover_workflow_dir(self.workflow_name, context.project_root)
        if workflow_dir is None:
            raise CompilerError(
                get_workflow_not_found_message(self.workflow_name, context.project_root)
            )
        return workflow_dir

    def validate_context(self, context: CompilerContext) -> None:
        """Validate context before compilation.

        Args:
            context: The compilation context to validate.

        Raises:
            CompilerError: If required context is missing.

        """
        if context.project_root is None:
            raise CompilerError("project_root is required in context")
        if context.output_folder is None:
            raise CompilerError("output_folder is required in context")

        epic_num = context.resolved_variables.get("epic_num")

        if epic_num is None:
            raise CompilerError(
                "epic_num is required for hardening compilation.\n"
                "  Suggestion: Provide epic_num via invocation params"
            )

        # Workflow directory is validated by get_workflow_dir via discovery
        workflow_dir = self.get_workflow_dir(context)
        if not workflow_dir.exists():
            raise CompilerError(
                f"Workflow directory not found: {workflow_dir}\n"
                f"  Why it's needed: Contains workflow.yaml and instructions.md\n"
                f"  How to fix: Reinstall bmad-assist or ensure BMAD is properly installed"
            )

    def compile(self, context: CompilerContext) -> CompiledWorkflow:
        """Compile hardening workflow with given context.

        Executes the full compilation pipeline:
        1. Use pre-loaded workflow_ir from context
        2. Resolve variables
        3. Build context files (Retrospective Report)
        4. Filter instructions
        5. Generate XML output

        Args:
            context: The compilation context with:
                - workflow_ir: Pre-loaded WorkflowIR
                - patch_path: Path to patch file (for post_process)

        Returns:
            CompiledWorkflow ready for output.

        Raises:
            CompilerError: If compilation fails at any stage.

        """
        workflow_ir = context.workflow_ir
        if workflow_ir is None:
            raise CompilerError(
                "workflow_ir not set in context. This is a bug - core.py should have loaded it."
            )

        workflow_dir = self.get_workflow_dir(context)

        with context_snapshot(context):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Using workflow from %s", workflow_dir)

            invocation_params = {
                k: v for k, v in context.resolved_variables.items() if k in ("epic_num", "date")
            }

            sprint_status_path = find_sprint_status_file(context)

            resolved = resolve_variables(context, invocation_params, sprint_status_path, None)

            # Compute next_epic_id for the hardening story
            epic_num = resolved.get("epic_num")
            if epic_num is not None:
                try:
                    resolved["next_epic_id"] = int(epic_num) + 1
                except (ValueError, TypeError):
                    resolved["next_epic_id"] = epic_num

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Resolved %d variables", len(resolved))

            context_files = self._build_context_files(context, resolved)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Built context with %d files", len(context_files))

            filtered_instructions = filter_instructions(workflow_ir)
            filtered_instructions = substitute_variables(filtered_instructions, resolved)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Filtered instructions: %d bytes", len(filtered_instructions))

            mission = self._build_mission(workflow_ir, resolved)

            compiled = CompiledWorkflow(
                workflow_name=self.workflow_name,
                mission=mission,
                context="",
                variables=resolved,
                instructions=filtered_instructions,
                output_template="",  # action-workflow, no template
                token_estimate=0,
            )

            result = generate_output(
                compiled,
                project_root=context.project_root,
                context_files=context_files,
                links_only=context.links_only,
            )

            final_xml = apply_post_process(result.xml, context)

            return CompiledWorkflow(
                workflow_name=self.workflow_name,
                mission=mission,
                context=final_xml,
                variables=resolved,
                instructions=filtered_instructions,
                output_template="",
                token_estimate=result.token_estimate,
            )

    def _build_context_files(
        self,
        context: CompilerContext,
        resolved: dict[str, Any],
    ) -> dict[str, str]:
        """Build context files dict.

        Mainly includes the Retrospective Report for the current epic.

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables containing epic_num.

        Returns:
            Dictionary mapping file paths to content.

        """
        files: dict[str, str] = {}
        project_root = context.project_root
        epic_num = resolved.get("epic_num")

        if epic_num is None:
            return files

        # 1. Retrospective Report (CRITICAL)
        retro_path = self._find_latest_retrospective(context, epic_num)
        if not retro_path:
            raise CompilerError(
                f"No retrospective report found for Epic {epic_num}.\n"
                f"  Why it's needed: The hardening workflow requires insights from the retrospective.\n"
                f"  How to fix: Please run the 'retrospective' phase first: `bmad-assist run -p . --phase retrospective --epic {epic_num}`"
            )

        content = safe_read_file(retro_path, project_root)
        if content:
            files[str(retro_path)] = content

        # 2. Sprint status (optional but helpful)
        sprint_status_path = find_sprint_status_file(context)
        if sprint_status_path:
            content = safe_read_file(sprint_status_path, project_root)
            if content:
                files[str(sprint_status_path)] = content

        return files

    def _find_latest_retrospective(
        self, context: CompilerContext, epic_num: Any
    ) -> Path | None:
        """Find latest retrospective report for epic.

        Args:
            context: Compilation context.
            epic_num: Epic number.

        Returns:
            Path to retrospective report, or None.

        """
        impl_artifacts = context.output_folder
        if impl_artifacts is None:
            return None

        retro_dir = impl_artifacts / "retrospectives"
        if not retro_dir.exists():
            return None

        # Find most recent retro for current epic
        # Pattern: epic-{epic_num}-retro-*.md
        pattern = f"epic-{epic_num}-retro-*.md"
        retros = sorted(retro_dir.glob(pattern), reverse=True)

        if retros:
            return retros[0]

        return None

    def _build_mission(
        self,
        workflow_ir: Any,
        resolved: dict[str, Any],
    ) -> str:
        """Build mission description for compiled workflow.

        Args:
            workflow_ir: Workflow IR with description.
            resolved: Resolved variables.

        Returns:
            Mission description string.

        """
        base_description = workflow_ir.raw_config.get(
            "description", "Generate Story 0 (Hardening) from retrospective action items"
        )

        epic_num = resolved.get("epic_num", "?")

        mission = (
            f"{base_description}\n\n"
            f"Target: Epic {epic_num} Hardening Story\n"
            f"Synthesize action items from retrospective into a concrete backlog story."
        )

        return mission

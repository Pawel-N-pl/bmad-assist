"""Base compiler for TEA tri-modal testarch workflows.

This module provides a base class for compiling TEA Enterprise tri-modal
workflows that use workflow.md + steps-c/v/e/ directory structure.

All testarch workflows (automate, ci, framework, nfr-assess, test-design,
test-review, trace, atdd) share this common compilation pattern.

Public API:
    TestarchTriModalCompiler: Base class for tri-modal workflow compilation
"""

import logging
from pathlib import Path
from typing import Any

from bmad_assist.compiler.filtering import filter_instructions
from bmad_assist.compiler.output import generate_output
from bmad_assist.compiler.shared_utils import (
    apply_post_process,
    context_snapshot,
    get_stories_dir,
    load_workflow_template,
    safe_read_file,
)
from bmad_assist.compiler.step_chain import compile_step_chain
from bmad_assist.compiler.tri_modal import get_workflow_mode, validate_workflow_mode
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext, WorkflowIR
from bmad_assist.compiler.variable_utils import substitute_variables
from bmad_assist.core.exceptions import CompilerError

logger = logging.getLogger(__name__)


class TestarchTriModalCompiler:
    """Base compiler for TEA tri-modal testarch workflows.

    Provides common compilation logic for all testarch workflows that use
    the tri-modal step-file architecture (workflow.md + steps-c/v/e/).

    Subclasses must define:
    - workflow_name: Unique workflow identifier (e.g., "testarch-automate")

    Subclasses may override:
    - _build_context_files: Add workflow-specific context files
    - _get_workflow_specific_variables: Add workflow-specific variables
    - _build_mission: Customize the mission description

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier. Must be overridden by subclasses."""
        raise NotImplementedError("Subclass must define workflow_name")

    def get_required_files(self) -> list[str]:
        """Return list of required file glob patterns.

        Returns:
            Glob patterns for files needed by testarch workflows.

        """
        return [
            "**/project_context.md",
            "**/project-context.md",
        ]

    def get_variables(self) -> dict[str, Any]:
        """Return workflow-specific variables to resolve.

        Returns:
            Variables needed for testarch compilation.

        """
        return {
            "epic_num": None,
            "story_num": None,
            "story_id": None,
            "story_file": None,
            "workflow_mode": None,
            "date": None,
        }

    def get_workflow_dir(self, context: CompilerContext) -> Path:
        """Return the workflow directory for this compiler.

        Uses workflow discovery for testarch workflows.

        Args:
            context: The compilation context with project paths.

        Returns:
            Path to the workflow directory containing workflow.md.

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
        story_num = context.resolved_variables.get("story_num")

        if epic_num is None:
            raise CompilerError(
                f"epic_num is required for {self.workflow_name} compilation.\n"
                "  Suggestion: Provide epic_num via invocation params"
            )

        # Story num is optional for some testarch workflows (epic-level)
        # Story file is optional context - warn if not found but don't error
        if story_num is not None:
            story_path = self._find_story_file(context, epic_num, story_num)
            if story_path is None:
                logger.warning(
                    "Story file not found for %s-%s-*.md (non-blocking)",
                    epic_num,
                    story_num,
                )

        # Workflow directory is validated by get_workflow_dir
        workflow_dir = self.get_workflow_dir(context)
        if not workflow_dir.exists():
            raise CompilerError(
                f"Workflow directory not found: {workflow_dir}\n"
                f"  Why it's needed: Contains workflow.md and step files\n"
                f"  How to fix: Reinstall bmad-assist or ensure BMAD is properly installed"
            )

    def compile(self, context: CompilerContext) -> CompiledWorkflow:
        """Compile workflow with given context.

        Supports both tri-modal and legacy macro workflows:
        - Tri-modal: Builds step chain from steps-c/v/e directories
        - Legacy: Uses filter_instructions from raw_instructions

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
                logger.debug("Using %s workflow from %s", self.workflow_name, workflow_dir)

            # Build resolved variables
            resolved = dict(context.resolved_variables)

            epic_num = resolved.get("epic_num")
            story_num = resolved.get("story_num")

            # Compute story_id if story_num is provided
            if story_num is not None:
                resolved["story_id"] = f"{epic_num}.{story_num}"

                # Find and add story file path
                story_path = self._find_story_file(context, epic_num, story_num)
                if story_path:
                    resolved["story_file"] = str(story_path)

            # Add workflow-specific variables
            self._get_workflow_specific_variables(resolved, context, workflow_ir)

            # Determine workflow mode (None for macro workflows)
            mode = get_workflow_mode(context)
            resolved["workflow_mode"] = mode

            # Build step chain or use legacy instructions
            step_context_files: list[str] = []

            if workflow_ir.has_tri_modal and mode is not None:
                # Tri-modal: Validate mode and build step chain
                validate_workflow_mode(workflow_ir, mode)

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Using mode: %s", mode)

                # Get first step for selected mode
                first_step = self._get_first_step_for_mode(workflow_ir, mode)
                if first_step is None:
                    raise CompilerError(
                        f"No first step found for mode '{mode}' in {self.workflow_name}\n"
                        f"  Suggestion: Check that steps-{mode}/ directory exists with step files"
                    )

                # Build step chain and resolve variables
                step_content, step_context_files = compile_step_chain(
                    first_step, resolved, context.project_root
                )

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Compiled step chain: %d bytes", len(step_content))

                filtered_instructions = substitute_variables(step_content, resolved)
            else:
                # Legacy macro workflow: use filter_instructions
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Using legacy macro workflow compilation")

                filtered_instructions = filter_instructions(workflow_ir)
                filtered_instructions = substitute_variables(filtered_instructions, resolved)

            # Build context files
            context_files = self._build_context_files(context, resolved)

            # Add step-provided context files (like knowledge index)
            for cf in step_context_files:
                if cf not in context_files:
                    content = safe_read_file(Path(cf), context.project_root)
                    if content:
                        context_files[cf] = content

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Built context with %d files", len(context_files))

            # Load template if defined
            template_content = load_workflow_template(workflow_ir, context)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Instructions: %d bytes", len(filtered_instructions))

            # Build mission
            mission = self._build_mission(workflow_ir, resolved)

            # Generate output
            compiled = CompiledWorkflow(
                workflow_name=self.workflow_name,
                mission=mission,
                context="",
                variables=resolved,
                instructions=filtered_instructions,
                output_template=template_content,
                token_estimate=0,
            )

            result = generate_output(
                compiled,
                project_root=context.project_root,
                context_files=context_files,
                links_only=context.links_only,
            )

            # Apply post_process rules if patch exists
            final_xml = apply_post_process(result.xml, context)

            return CompiledWorkflow(
                workflow_name=self.workflow_name,
                mission=mission,
                context=final_xml,
                variables=resolved,
                instructions=filtered_instructions,
                output_template=template_content,
                token_estimate=result.token_estimate,
            )

    def _get_first_step_for_mode(
        self, workflow_ir: WorkflowIR, mode: str
    ) -> Path | None:
        """Get the first step file for the given mode.

        Args:
            workflow_ir: Workflow IR with step paths.
            mode: Workflow mode (c, v, or e).

        Returns:
            Path to first step file, or None if not found.

        """
        if mode == "c":
            return workflow_ir.first_step_c
        elif mode == "v":
            return workflow_ir.first_step_v
        elif mode == "e":
            return workflow_ir.first_step_e
        return None

    def _find_story_file(
        self,
        context: CompilerContext,
        epic_num: Any,
        story_num: Any,
    ) -> Path | None:
        """Find story file by epic and story number.

        Args:
            context: Compilation context with paths.
            epic_num: Epic number.
            story_num: Story number.

        Returns:
            Path to story file or None if not found.

        """
        stories_dir = get_stories_dir(context)
        if not stories_dir.exists():
            return None

        pattern = f"{epic_num}-{story_num}-*.md"
        matches = sorted(stories_dir.glob(pattern))

        if not matches:
            logger.debug("No story file found matching %s in %s", pattern, stories_dir)
            return None

        return matches[0]

    def _build_context_files(
        self,
        context: CompilerContext,
        resolved: dict[str, Any],
    ) -> dict[str, str]:
        """Build context files with strategic, TEA, and source context.

        Follows recency-bias ordering: general context first, story file last.

        Context sources (in order):
        1. Strategic context (project-context, PRD, Architecture per workflow config)
        2. TEA context (artifacts from previous TEA runs if enabled)
        3. Source context (source files for automate/nfr-assess workflows)
        4. Story file (LAST - closest to instructions)

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables.

        Returns:
            Dictionary mapping file paths to content.

        """
        files: dict[str, str] = {}
        project_root = context.project_root

        # Cache story content once for reuse (ADR-6: avoid redundant I/O)
        story_file_path = resolved.get("story_file")
        story_content: str | None = None
        if story_file_path:
            story_content = safe_read_file(Path(story_file_path), project_root)

        # 1. Strategic context (lazy import to avoid circular deps)
        from bmad_assist.compiler.strategic_context import StrategicContextService

        strategic_service = StrategicContextService(context, self.workflow_name)
        strategic_files = strategic_service.collect()
        files.update(strategic_files)

        # 2. TEA context (artifacts from previous TEA runs)
        from bmad_assist.testarch.context import collect_tea_context, is_tea_context_enabled

        if is_tea_context_enabled(context):
            tea_files = collect_tea_context(context, self.workflow_name, resolved)
            files.update(tea_files)

        # 3. Source context for workflows that need it (check BEFORE file I/O)
        from bmad_assist.compiler.source_context import SourceContextService

        source_service = SourceContextService(context, self.workflow_name)
        if source_service.is_enabled() and story_content:
            from bmad_assist.compiler.source_context import extract_file_paths_from_story

            file_list_paths = extract_file_paths_from_story(story_content)
            source_files = source_service.collect_files(file_list_paths, None)
            files.update(source_files)

        # 4. Story file (LAST - recency bias per ADR-6)
        # Note: story_content already read above, reuse it
        if story_file_path and story_content:
            files[str(story_file_path)] = story_content

        # ADR-7: Warn if combined context is large
        from bmad_assist.compiler.shared_utils import estimate_tokens

        total_tokens = sum(estimate_tokens(c) for c in files.values())
        if total_tokens > 15000:
            logger.info(
                "TEA context large: %d tokens across %d files (workflow: %s)",
                total_tokens,
                len(files),
                self.workflow_name,
            )

        return files

    def _get_workflow_specific_variables(
        self,
        resolved: dict[str, Any],
        context: CompilerContext,
        workflow_ir: WorkflowIR,
    ) -> None:
        """Add workflow-specific variables to resolved dict.

        Default implementation does nothing. Subclasses may override
        to add variables specific to their workflow.

        Args:
            resolved: Resolved variables dict (modified in place).
            context: Compilation context.
            workflow_ir: Workflow IR.

        """
        pass

    def _build_mission(
        self,
        workflow_ir: WorkflowIR,
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
            "description", f"Execute {self.workflow_name} workflow"
        )

        mode = resolved.get("workflow_mode", "c")
        mode_name = {"c": "Create", "v": "Validate", "e": "Edit"}.get(mode, mode)

        story_id = resolved.get("story_id")
        if story_id:
            mission = (
                f"{base_description}\n\n"
                f"Mode: {mode_name}\n"
                f"Target: Story {story_id}"
            )
        else:
            epic_num = resolved.get("epic_num", "?")
            mission = (
                f"{base_description}\n\n"
                f"Mode: {mode_name}\n"
                f"Target: Epic {epic_num}"
            )

        return mission

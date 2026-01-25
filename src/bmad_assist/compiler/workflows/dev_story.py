"""Compiler for the dev-story workflow.

This module implements the WorkflowCompiler protocol for the dev-story
workflow, producing standalone prompts for story implementation with
all necessary context embedded.

Public API:
    DevStoryCompiler: Workflow compiler class implementing WorkflowCompiler protocol
"""

import logging
from pathlib import Path
from typing import Any

from bmad_assist.compiler.filtering import filter_instructions
from bmad_assist.compiler.output import generate_output
from bmad_assist.compiler.shared_utils import (
    apply_post_process,
    context_snapshot,
    find_epic_file,
    find_file_in_output_folder,
    find_sprint_status_file,
    resolve_story_file,
    safe_read_file,
)
from bmad_assist.compiler.strategic_context import StrategicContextService
from bmad_assist.compiler.source_context import (
    SourceContextService,
    extract_file_paths_from_story,
)
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext, WorkflowIR
from bmad_assist.compiler.variable_utils import substitute_variables
from bmad_assist.compiler.variables import resolve_variables
from bmad_assist.core.exceptions import CompilerError

logger = logging.getLogger(__name__)


class DevStoryCompiler:
    """Compiler for the dev-story workflow.

    Implements the WorkflowCompiler protocol to compile the dev-story
    workflow into a standalone prompt. The dev-story workflow is an
    action-workflow (no template output), focused on implementing
    stories with all necessary context embedded.

    Context embedding follows recency-bias ordering:
    1. project_context.md (general)
    2. prd.md (full, no filtering)
    3. ux.md (optional)
    4. architecture.md (technical)
    5. epic file (current epic)
    6. source files from File List (with token budget)
    7. story file (LAST - closest to instructions)

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "dev-story"

    def get_required_files(self) -> list[str]:
        """Return list of required file glob patterns.

        Returns:
            Glob patterns for files needed by dev-story workflow.

        """
        return [
            "**/project_context.md",
            "**/project-context.md",
            "**/architecture*.md",
            "**/prd*.md",
            "**/ux*.md",
            "**/sprint-status.yaml",
            "**/epic*.md",
        ]

    def get_variables(self) -> dict[str, Any]:
        """Return workflow-specific variables to resolve.

        Returns:
            Variables needed for dev-story compilation.

        """
        return {
            "epic_num": None,
            "story_num": None,
            "story_key": None,
            "story_id": None,
            "story_file": None,
            "story_title": None,
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
        story_num = context.resolved_variables.get("story_num")

        if epic_num is None:
            raise CompilerError(
                "epic_num is required for dev-story compilation.\n"
                "  Suggestion: Provide epic_num via invocation params or ensure "
                "sprint-status.yaml has a ready-for-dev story"
            )
        if story_num is None:
            raise CompilerError(
                "story_num is required for dev-story compilation.\n"
                "  Suggestion: Provide story_num via invocation params or ensure "
                "sprint-status.yaml has a ready-for-dev story"
            )

        # Workflow directory is validated by get_workflow_dir via discovery
        workflow_dir = self.get_workflow_dir(context)
        if not workflow_dir.exists():
            raise CompilerError(
                f"Workflow directory not found: {workflow_dir}\n"
                f"  Why it's needed: Contains workflow.yaml and instructions.xml\n"
                f"  How to fix: Reinstall bmad-assist or ensure BMAD is properly installed"
            )

        story_path, _, _ = resolve_story_file(context, epic_num, story_num)
        if story_path is None:
            raise CompilerError(
                f"Story file not found for {epic_num}-{story_num}-*.md\n"
                f"  Expected pattern: docs/sprint-artifacts/{epic_num}-{story_num}-*.md\n"
                f"  Suggestion: Run 'create-story' workflow first to create the story"
            )

    def compile(self, context: CompilerContext) -> CompiledWorkflow:
        """Compile dev-story workflow with given context.

        Executes the full compilation pipeline:
        1. Use pre-loaded workflow_ir from context
        2. Resolve variables with sprint-status lookup
        3. Build context files with recency-bias ordering (story LAST)
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
                k: v
                for k, v in context.resolved_variables.items()
                if k in ("epic_num", "story_num", "story_title", "date")
            }

            sprint_status_path = find_sprint_status_file(context)

            epic_num = invocation_params.get("epic_num")
            epics_path = find_epic_file(context, epic_num) if epic_num else None

            resolved = resolve_variables(context, invocation_params, sprint_status_path, epics_path)

            story_path, story_key, _ = resolve_story_file(
                context,
                resolved.get("epic_num"),
                resolved.get("story_num"),
            )
            if story_path:
                resolved["story_file"] = str(story_path)
            if story_key:
                resolved["story_key"] = story_key

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
        """Build context files dict with recency-bias ordering.

        Files are ordered from general (early) to specific (late):
        1. Strategic docs via StrategicContextService (project-context, optionally PRD/UX/Architecture)
        1b. code-antipatterns.md (if exists - general guidance)
        2. epic file (current epic)
        3. ATDD checklist (if exists)
        4. source files from File List (with token budget)
        5. story file (LAST - closest to instructions)

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables containing epic_num and story_num.

        Returns:
            Dictionary mapping file paths to content, ordered by recency-bias.

        """
        files: dict[str, str] = {}
        project_root = context.project_root

        # 1. Strategic docs (project-context, PRD, UX, Architecture) via service
        # Default config for dev_story: project-context only (other docs rarely cited)
        strategic_service = StrategicContextService(context, "dev_story")
        strategic_files = strategic_service.collect()
        files.update(strategic_files)

        # 1b. Include code antipatterns from previous code reviews (if exists)
        # Position: early in context as general guidance (after strategic docs)
        epic_num = resolved.get("epic_num")
        if epic_num is not None:
            from bmad_assist.core.paths import get_paths

            try:
                paths = get_paths()
                antipatterns_path = (
                    paths.implementation_artifacts / f"epic-{epic_num}-code-antipatterns.md"
                )
                if antipatterns_path.exists():
                    files["[ANTIPATTERNS - DO NOT REPEAT]"] = antipatterns_path.read_text(
                        encoding="utf-8"
                    )
                    logger.debug("Added code antipatterns to dev-story context")
            except (RuntimeError, OSError) as e:
                logger.debug("Could not load code antipatterns: %s", e)

        # 2. Epic file (current epic)
        epic_num = resolved.get("epic_num")
        if epic_num:
            epic_path = find_epic_file(context, epic_num)
            if epic_path:
                content = safe_read_file(epic_path, project_root)
                if content:
                    files[str(epic_path)] = content

        # 3. ATDD checklist (if exists) - provides failing tests from ATDD phase
        story_id = resolved.get("story_id")
        if story_id:
            atdd_pattern = f"*atdd-checklist*{story_id}*.md"
            atdd_path = find_file_in_output_folder(context, atdd_pattern)
            if atdd_path:
                content = safe_read_file(atdd_path, project_root)
                if content:
                    files[str(atdd_path)] = content
                    logger.debug("Embedded ATDD checklist: %s", atdd_path)

        # 4. Source files from story's File List using SourceContextService
        story_path_str = resolved.get("story_file")
        if story_path_str:
            story_path = Path(story_path_str)
            story_content = safe_read_file(story_path, project_root)
            file_list_paths: list[str] = []
            if story_content:
                file_list_paths = extract_file_paths_from_story(story_content)

            service = SourceContextService(context, "dev_story")
            source_files = service.collect_files(file_list_paths, None)
            files.update(source_files)

        # 5. Story file (LAST - closest to instructions per recency-bias)
        if story_path_str:
            story_path = Path(story_path_str)
            content = safe_read_file(story_path, project_root)
            if content:
                files[str(story_path)] = content

        return files

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
            "description", "Execute a story by implementing tasks/subtasks, writing tests"
        )

        epic_num = resolved.get("epic_num", "?")
        story_num = resolved.get("story_num", "?")
        story_title = resolved.get("story_title", "")

        if story_title:
            mission = (
                f"{base_description}\n\n"
                f"Target: Story {epic_num}.{story_num} - {story_title}\n"
                f"Implement all tasks and subtasks following TDD methodology."
            )
        else:
            mission = (
                f"{base_description}\n\n"
                f"Target: Story {epic_num}.{story_num}\n"
                f"Implement all tasks and subtasks following TDD methodology."
            )

        return mission

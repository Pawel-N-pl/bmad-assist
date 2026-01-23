"""Compiler for the create-story workflow.

This module implements the WorkflowCompiler protocol for the create-story
workflow, orchestrating all compiler pipeline components to produce
standalone prompts for story creation.

Public API:
    CreateStoryCompiler: Workflow compiler class implementing WorkflowCompiler protocol
"""

import logging
import re
from pathlib import Path
from typing import Any

from bmad_assist.compiler.context import ContextBuilder
from bmad_assist.compiler.filtering import filter_instructions
from bmad_assist.compiler.output import generate_output
from bmad_assist.compiler.shared_utils import (
    apply_post_process,
    context_snapshot,
    find_previous_stories,
    find_project_context_file,
    find_sprint_status_file,
    get_epics_dir,
    load_workflow_template,
)
from bmad_assist.compiler.source_context import (
    SourceContextService,
    extract_file_paths_from_story,
)
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext
from bmad_assist.compiler.variables import resolve_variables
from bmad_assist.core.exceptions import CompilerError

# Patterns for variable substitution
_DOUBLE_BRACE_PATTERN = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_-]*)\}\}")
_SINGLE_BRACE_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_-]*)\}")


def _substitute_variables(text: str, variables: dict[str, Any]) -> str:
    """Substitute variable placeholders in text with resolved values.

    Replaces both {{var}} and {var} patterns with their values from
    the variables dict. Unknown variables are left as-is.

    Args:
        text: Text containing variable placeholders.
        variables: Dict mapping variable names to their resolved values.

    Returns:
        Text with known variables substituted, unknown ones preserved.

    """

    def replace_var(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name in variables:
            value = variables[var_name]
            return str(value) if value is not None else ""
        # Leave unknown placeholders intact
        return match.group(0)

    # Replace double braces first (more specific), then single braces
    result = _DOUBLE_BRACE_PATTERN.sub(replace_var, text)
    result = _SINGLE_BRACE_PATTERN.sub(replace_var, result)
    return result


logger = logging.getLogger(__name__)


class CreateStoryCompiler:
    """Compiler for the create-story workflow.

    Implements the WorkflowCompiler protocol to compile the create-story
    workflow into a standalone prompt. Orchestrates all compiler pipeline
    components: parsing, variable resolution, file discovery, instruction
    filtering, and XML output generation.

    The compilation pipeline follows this order:
    1. Load workflow files via parse_workflow()
    2. Resolve variables via resolve_variables() with sprint-status.yaml lookup
    3. Build context files dict with recency-bias ordering
    4. Load and preserve template with {{placeholders}}
    5. Filter instructions via filter_instructions()
    6. Generate XML output via generate_output()
    7. Return CompiledWorkflow with all fields populated

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "create-story"

    def get_required_files(self) -> list[str]:
        """Return list of required file glob patterns.

        Returns:
            Glob patterns for files needed by create-story workflow.

        """
        return [
            "**/project_context.md",  # Required - critical implementation rules
            "**/architecture*.md",  # Architecture patterns
            "**/prd*.md",  # Product requirements
            "**/ux*.md",  # UX design (optional)
            "**/sprint-status.yaml",  # Sprint tracking
            "**/epic*.md",  # Epic files
        ]

    def get_variables(self) -> dict[str, Any]:
        """Return workflow-specific variables to resolve.

        Returns:
            Variables needed for create-story compilation.

        """
        return {
            "epic_num": None,  # Required - from invocation or sprint-status
            "story_num": None,  # Required - from invocation or computed
            "story_key": None,  # Computed: {epic_num}-{story_num}-{slug}
            "story_id": None,  # Computed: {epic_num}.{story_num}
            "story_title": None,  # From sprint-status or fallback
            "date": None,  # System-generated or override
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

        # Validate epic_num and story_num are provided
        epic_num = context.resolved_variables.get("epic_num")
        story_num = context.resolved_variables.get("story_num")

        if epic_num is None:
            raise CompilerError(
                "epic_num is required for create-story compilation.\n"
                "  Suggestion: Provide epic_num via invocation params or ensure "
                "sprint-status.yaml has a backlog story"
            )
        if story_num is None:
            raise CompilerError(
                "story_num is required for create-story compilation.\n"
                "  Suggestion: Provide story_num via invocation params or ensure "
                "sprint-status.yaml has a backlog story"
            )

        # Workflow directory is validated by get_workflow_dir via discovery
        workflow_dir = self.get_workflow_dir(context)
        if not workflow_dir.exists():
            raise CompilerError(
                f"Workflow directory not found: {workflow_dir}\n"
                f"  Why it's needed: Contains workflow.yaml and instructions.xml for compilation\n"
                f"  How to fix: Reinstall bmad-assist or ensure BMAD is properly installed"
            )

        # Validate project_context.md exists (required file)
        project_context_path = find_project_context_file(context)
        if project_context_path is None:
            raise CompilerError(
                f"project_context.md not found: {context.output_folder / 'project_context.md'}\n"
                f"  Why it's needed: Contains critical implementation rules for AI agents\n"
                f"  How to fix: Run 'generate-project-context' workflow"
            )

    def compile(self, context: CompilerContext) -> CompiledWorkflow:
        """Compile create-story workflow with given context.

        Executes the full compilation pipeline:
        1. Use pre-loaded workflow_ir from context (loaded by core.py)
        2. Resolve variables with sprint-status lookup
        3. Build context files with recency-bias ordering
        4. Load template with preserved placeholders
        5. Filter instructions
        6. Generate XML output

        Args:
            context: The compilation context with:
                - workflow_ir: Pre-loaded WorkflowIR (from cache or original)
                - patch_path: Path to patch file (for post_process)

        Returns:
            CompiledWorkflow ready for output.

        Raises:
            CompilerError: If compilation fails at any stage.

        Note:
            This method follows fail-fast principles (AC8): no partial output
            is produced on error. Context is only modified after successful
            completion of the entire pipeline.

        """
        # Step 1: Use pre-loaded workflow_ir from context
        workflow_ir = context.workflow_ir
        if workflow_ir is None:
            raise CompilerError(
                "workflow_ir not set in context. This is a bug - core.py should have loaded it."
            )

        workflow_dir = self.get_workflow_dir(context)

        # AC8: Use context_snapshot for automatic state rollback on error
        with context_snapshot(context):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Using workflow from %s", workflow_dir)

            # Step 2: Resolve variables with sprint-status lookup
            invocation_params = {
                k: v
                for k, v in context.resolved_variables.items()
                if k in ("epic_num", "story_num", "story_title", "date")
            }

            # Find sprint-status.yaml path
            sprint_status_path = find_sprint_status_file(context)

            # Find epic file for story_title extraction fallback
            epic_num = invocation_params.get("epic_num")
            epics_path = None
            if epic_num:
                epic_files = self._find_epic_context_files(
                    context, {"epic_num": epic_num, "story_num": invocation_params.get("story_num")}
                )
                # Use first epic file found (the actual epic-{num}-*.md file)
                for f in epic_files:
                    if f.name.startswith(f"epic-{epic_num}"):
                        epics_path = f
                        break
                # Fallback to any epic file if specific not found
                if not epics_path and epic_files:
                    epics_path = epic_files[0]

            resolved = resolve_variables(context, invocation_params, sprint_status_path, epics_path)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Resolved %d variables", len(resolved))

            # Step 3: Build context files with recency-bias ordering
            context_files = self._build_context_files(context, resolved)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Built context with %d files", len(context_files))

            # Step 4: Load template using shared utility
            template_content = load_workflow_template(workflow_ir, context)

            # Note: validation/checklist NOT embedded for create-story.
            # Validation is a separate workflow (validate-story).
            # Embedding checklist.md would add ~4K tokens of BMAD runtime docs
            # (workflow.xml references, etc.) that are irrelevant for compiled prompts.

            # Step 5: Filter instructions
            filtered_instructions = filter_instructions(workflow_ir)

            # Step 5b: Substitute variables in filtered instructions
            filtered_instructions = _substitute_variables(filtered_instructions, resolved)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Filtered instructions: %d bytes", len(filtered_instructions))

            # Step 6: Build mission description
            mission = self._build_mission(workflow_ir, resolved)

            # Step 7: Generate XML output for token estimation
            compiled = CompiledWorkflow(
                workflow_name=self.workflow_name,
                mission=mission,
                context="",  # Will be populated from context_files
                variables=resolved,
                instructions=filtered_instructions,
                output_template=template_content,
                token_estimate=0,  # Will be calculated
            )

            result = generate_output(
                compiled,
                project_root=context.project_root,
                context_files=context_files,
                links_only=context.links_only,
            )

            # Step 8: Apply post_process rules using shared utility
            final_xml = apply_post_process(result.xml, context)

            # Return with calculated token estimate
            return CompiledWorkflow(
                workflow_name=self.workflow_name,
                mission=mission,
                context=final_xml,  # Full XML after post_process rules
                variables=resolved,
                instructions=filtered_instructions,
                output_template=template_content,
                token_estimate=result.token_estimate,
            )

    def _build_context_files(
        self,
        context: CompilerContext,
        resolved: dict[str, Any],
    ) -> dict[str, str]:
        """Build context files dict with recency-bias ordering.

        Uses ContextBuilder for standard context assembly with recency-bias
        ordering, then adds create-story specific source files from File List.

        Files are ordered from general (early) to specific (late):
        1. project_context.md (PRIORITY_BACKGROUND=10)
        2. prd.md, ux.md, architecture.md (PRIORITY_PLANNING=20)
        3. previous stories (PRIORITY_STORIES=30, oldest first)
        4. story validations (PRIORITY_VALIDATIONS=40)
        5. source files from File List (workflow-specific, after validations)
        6. epic files (PRIORITY_EPIC=50)

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables containing epic_num and story_num.

        Returns:
            Dictionary mapping file paths to content, ordered by recency-bias.

        """
        # Store resolved variables in context for ContextBuilder to use
        context.resolved_variables = resolved

        # Use ContextBuilder for standard context (1-4, 6)
        epic_num = resolved.get("epic_num")
        builder = ContextBuilder(context)
        builder = (
            builder.add_project_context(required=False)  # Validation already checks this
            .add_planning_docs(prd=True, architecture=True, ux=True, required=False)
            .add_previous_stories(count=3)
        )
        # Add epic files if epic_num is available (validated earlier in compile())
        if epic_num is not None:
            builder = builder.add_epic_files(epic_num=epic_num)
        base_files = builder.build()

        # Get previous stories for source file collection using shared utility
        prev_stories = find_previous_stories(context, resolved)

        # Collect file paths from all previous stories' File Lists
        file_list_paths: list[str] = []
        for story_path in prev_stories:
            try:
                story_content = story_path.read_text(encoding="utf-8")
                paths = extract_file_paths_from_story(story_content)
                file_list_paths.extend(paths)
            except (OSError, UnicodeDecodeError) as e:
                logger.debug("Could not read story %s: %s", story_path, e)

        # Add source files from File List using SourceContextService
        # create_story uses File List only (no git diff)
        service = SourceContextService(context, "create_story")
        source_files = service.collect_files(file_list_paths, None)

        # Merge: base_files already has proper order, insert source_files before epics
        # Since ContextBuilder handles ordering, we just update with source files
        # They will be added after the last story but conceptually before epics
        files: dict[str, str] = {}
        epic_entries: dict[str, str] = {}

        # Include story antipatterns from previous validations (if exists)
        # Position: early in context as general guidance (before stories/epic files)
        if epic_num is not None:
            from bmad_assist.core.paths import get_paths

            try:
                paths = get_paths()
                antipatterns_path = (
                    paths.implementation_artifacts / f"epic-{epic_num}-story-antipatterns.md"
                )
                if antipatterns_path.exists():
                    files["[ANTIPATTERNS - DO NOT REPEAT]"] = antipatterns_path.read_text(
                        encoding="utf-8"
                    )
                    logger.debug("Added story antipatterns to create-story context")
            except (RuntimeError, OSError) as e:
                logger.debug("Could not load story antipatterns: %s", e)

        # Pattern to identify epic files: /epics/ directory or epic-{num/id}-*.md pattern
        epic_file_pattern = re.compile(r"(/epics/|/epic-[a-zA-Z0-9]+-)")

        for path, content in base_files.items():
            # Separate epic files (in epics/ dir or named epic-{id}-*.md) to add them last
            if epic_file_pattern.search(path):
                epic_entries[path] = content
            else:
                files[path] = content

        # Add source files after stories/validations
        files.update(source_files)

        # Add epic files last
        files.update(epic_entries)

        return files

    def _find_epic_context_files(
        self,
        context: CompilerContext,
        resolved: dict[str, Any],
    ) -> list[Path]:
        """Find epic context files for compilation.

        Handles two cases:
        1. Sharded epics (epics/ directory exists):
           - All non-epic files (index.md, summary.md, etc.)
           - The specific epic-{num}-*.md file for current epic
        2. Single-file epic:
           - The entire epic file (epics.md or epic-{num}-*.md)

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables containing epic_num.

        Returns:
            List of paths to epic context files.

        """
        epic_num = resolved.get("epic_num")
        if epic_num is None:
            return []

        epics_dir = get_epics_dir(context)
        found_files: list[Path] = []

        if epics_dir.exists() and epics_dir.is_dir():
            # Sharded epics - include supporting files + current epic
            # Pattern for epic files: epic-{number}-*.md (e.g., epic-6-main-loop.md)
            epic_pattern = re.compile(r"^epic-\d+-")

            for file_path in sorted(epics_dir.glob("*.md")):
                filename = file_path.name
                if epic_pattern.match(filename):
                    # Only include the current epic file
                    if f"epic-{epic_num}-" in filename:
                        found_files.append(file_path)
                        logger.debug("Found current epic file: %s", file_path)
                else:
                    # Include all non-epic files (index.md, summary.md, epic-list.md, etc.)
                    found_files.append(file_path)
                    logger.debug("Found epic support file: %s", file_path)

            if found_files:
                logger.debug("Found %d epic context files for epic %s", len(found_files), epic_num)
                return found_files

        # Single-file epic fallback
        epic_file = self._find_single_epic_file(context, epic_num)
        if epic_file:
            logger.debug("Found single epic file: %s", epic_file)
            return [epic_file]

        logger.warning("No epic files found for epic %s", epic_num)
        return []

    def _find_single_epic_file(self, context: CompilerContext, epic_num: Any) -> Path | None:
        """Find single-file epic (not sharded).

        Used as fallback when epics/ directory doesn't exist.
        Searches in multiple locations:
        1. output_folder (implementation_artifacts) for epic-{num}-*.md
        2. output_folder for generic epics.md
        3. project_knowledge (docs) for epic-{num}-*.md
        4. project_knowledge for generic epics.md

        Args:
            context: Compilation context with paths.
            epic_num: Epic number to find.

        Returns:
            Path to epic file or None.

        """
        from bmad_assist.core.paths import get_paths

        # Check output_folder directly for epic-{num}-*.md
        pattern = f"*epic*{epic_num}*.md"
        matches = sorted(context.output_folder.glob(pattern))
        if matches:
            return matches[0]

        # Fallback: look for generic epics.md file in output_folder
        generic_epics = context.output_folder / "epics.md"
        if generic_epics.exists():
            return generic_epics

        # Fallback to project_knowledge (docs/) if paths are initialized
        try:
            paths = get_paths()
            project_knowledge = paths.project_knowledge

            # Check project_knowledge for epic-{num}-*.md
            matches = sorted(project_knowledge.glob(pattern))
            if matches:
                return matches[0]

            # Fallback: generic epics.md in project_knowledge
            generic_epics = project_knowledge / "epics.md"
            if generic_epics.exists():
                return generic_epics
        except RuntimeError:
            # Paths not initialized - skip this fallback
            pass

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
        # Use workflow.yaml description as base
        base_description = workflow_ir.raw_config.get(
            "description", "Create the next user story from epics"
        )

        # Add story-specific context
        epic_num = resolved.get("epic_num", "?")
        story_num = resolved.get("story_num", "?")
        story_title = resolved.get("story_title", "")

        if story_title:
            mission = (
                f"{base_description}\n\n"
                f"Target: Story {epic_num}.{story_num} - {story_title}\n"
                f"Create comprehensive developer context and implementation-ready story."
            )
        else:
            mission = (
                f"{base_description}\n\n"
                f"Target: Story {epic_num}.{story_num}\n"
                f"Create comprehensive developer context and implementation-ready story."
            )

        return mission

"""Compiler for the validate-story workflow.

This module implements the WorkflowCompiler protocol for the validate-story
workflow, producing standalone prompts for adversarial story validation.

Public API:
    ValidateStoryCompiler: Workflow compiler implementing WorkflowCompiler protocol
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from bmad_assist.compiler.filtering import filter_instructions
from bmad_assist.compiler.output import generate_output
from bmad_assist.compiler.patching import (
    load_patch,
    validate_output,
)
from bmad_assist.compiler.source_context import (
    SourceContextService,
    extract_file_paths_from_story,
)
from bmad_assist.compiler.shared_utils import (
    apply_post_process,
    context_snapshot,
    find_epic_file,
    find_previous_stories,
    find_sprint_status_file,
    find_story_context_file,
    get_stories_dir,
    load_workflow_template,
    normalize_model_name,
    resolve_story_file,
    safe_read_file,
)
from bmad_assist.compiler.strategic_context import StrategicContextService
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext, WorkflowIR
from bmad_assist.compiler.variable_utils import (
    filter_garbage_variables,
    substitute_variables,
)
from bmad_assist.compiler.variables import resolve_variables
from bmad_assist.core.exceptions import CompilerError

logger = logging.getLogger(__name__)

# Workflow path relative to project root
_WORKFLOW_RELATIVE_PATH = "_bmad/bmm/workflows/4-implementation/validate-story"

# Hardcoded validation focus - not configurable via YAML
_VALIDATION_FOCUS = "story_quality"


class ValidateStoryCompiler:
    """Compiler for the validate-story workflow.

    Implements the WorkflowCompiler protocol to compile the validate-story
    workflow into a standalone prompt. This is an action-workflow (template: false)
    focused on adversarial story validation.

    The compilation pipeline follows this order:
    1. Load workflow files via parse_workflow() or cached template
    2. Resolve variables via resolve_variables() with sprint-status.yaml lookup
    3. Filter instructions via filter_instructions()
    4. Build adversarial mission description
    5. Generate XML output via generate_output()
    6. Return CompiledWorkflow with all fields populated

    Note: Context building implemented in Story 11.2 (recency-bias ordering).

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "validate-story"

    def get_required_files(self) -> list[str]:
        """Return list of required file glob patterns.

        Returns:
            Glob patterns for files needed by validate-story workflow.

        """
        return [
            "**/project_context.md",
            "**/architecture*.md",
            "**/prd*.md",
            "**/sprint-status.yaml",
            "**/epic*.md",
            "**/sprint-artifacts/*.md",  # Story files
        ]

    def get_variables(self) -> dict[str, Any]:
        """Return workflow-specific variables to resolve.

        Returns:
            Variables needed for validate-story compilation.

        """
        return {
            "epic_num": None,  # Required - from invocation or sprint-status
            "story_num": None,  # Required - from invocation or computed
            "story_key": None,  # Computed: {epic_num}-{story_num}-{slug_from_filename}
            "story_id": None,  # Computed: {epic_num}.{story_num}
            "story_file": None,  # Path to story being validated (resolved via glob)
            "story_title": None,  # Extracted from filename slug
            "validation_focus": _VALIDATION_FOCUS,  # Hardcoded constant
            "date": None,  # System-generated
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
                "epic_num is required for validate-story compilation.\n"
                "  Suggestion: Provide epic_num via invocation params or ensure "
                "sprint-status.yaml has a story to validate"
            )
        if story_num is None:
            raise CompilerError(
                "story_num is required for validate-story compilation.\n"
                "  Suggestion: Provide story_num via invocation params or ensure "
                "sprint-status.yaml has a story to validate"
            )

        # Workflow directory is validated by get_workflow_dir via discovery
        workflow_dir = self.get_workflow_dir(context)
        if not workflow_dir.exists():
            raise CompilerError(
                f"Workflow directory not found: {workflow_dir}\n"
                f"  Why it's needed: Contains workflow.yaml and instructions.xml for compilation\n"
                f"  How to fix: Reinstall bmad-assist or ensure BMAD is properly installed"
            )

    def _build_context_files(
        self,
        context: CompilerContext,
        resolved: dict[str, Any],
    ) -> dict[str, str]:
        """Build context files dict with recency-bias ordering.

        Files are ordered from general (early) to specific (late):
        1. project_context.md (general background)
        2. prd.md (requirements source - broader)
        3. architecture.md (technical constraints)
        4. ux_design.md (UI validation context) - optional
        5. epic file (epic context - related)
        6. checklist.md (validation checklist from workflow)
        7. previous stories (up to 3, chronological: oldest first)
        8. STORY FILE (LAST - primary validation target, closest to instructions)

        Also updates resolved dict with actual file paths for proper embedding.

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables containing epic_num and story_num.
                      Will be updated with actual file paths.

        Returns:
            Dictionary mapping file paths to content, ordered by recency-bias.

        Raises:
            CompilerError: If story file not found or empty.

        """
        files: dict[str, str] = {}
        project_root = context.project_root
        epic_num = resolved.get("epic_num")
        story_num = resolved.get("story_num")

        # 1. Strategic docs via StrategicContextService
        # Default config for validate_story: project-context + architecture (26% PRD citation rate)
        strategic_service = StrategicContextService(context, "validate_story")
        strategic_files = strategic_service.collect()
        files.update(strategic_files)
        logger.debug("Added %d strategic docs via service", len(strategic_files))

        # 2. Epic file (related) - optional
        epic_path = find_epic_file(context, epic_num)
        if epic_path:
            content = safe_read_file(epic_path, project_root)
            if content:
                files[str(epic_path)] = content
                resolved["epics_file"] = str(epic_path)
                logger.debug("Added epic file to context: %s", epic_path)
        else:
            logger.debug("File not found, skipping: epic file for epic %s", epic_num)

        # 3. Story Context File (internal BMM context) - optional
        story_context_path = find_story_context_file(context, epic_num, story_num)
        if story_context_path:
            content = safe_read_file(story_context_path, project_root)
            if content:
                files[str(story_context_path)] = content
                resolved["story_context_file"] = str(story_context_path)
                logger.debug("Added story context file to context: %s", story_context_path)
        else:
            logger.debug(
                "File not found, skipping: story context file for epic %s, story %s",
                epic_num,
                story_num,
            )

        # 4. Checklist (validation checklist from workflow folder)
        workflow_dir = self.get_workflow_dir(context)
        checklist_path = workflow_dir / "checklist.md"
        if checklist_path.exists():
            content = safe_read_file(checklist_path)
            if content:
                # Substitute variables in checklist
                content = substitute_variables(content, resolved)
                files[str(checklist_path)] = content
                resolved["checklist_file"] = str(checklist_path)
                logger.debug("Added checklist to context: %s", checklist_path)
        else:
            logger.debug("File not found, skipping: checklist.md")

        # 5. Previous stories (up to 3, chronological: oldest first)
        prev_stories = find_previous_stories(context, resolved)
        for prev_story in prev_stories:
            content = safe_read_file(prev_story, project_root)
            if content:
                files[str(prev_story)] = content
                logger.debug("Added previous story to context: %s", prev_story)

        # 6. STORY FILE (MUST EXIST - validation target, inserted LAST)
        stories_dir = get_stories_dir(context)
        pattern = f"{epic_num}-{story_num}-*.md"
        story_matches = sorted(stories_dir.glob(pattern)) if stories_dir.exists() else []

        if not story_matches:
            raise CompilerError(
                f"Story file not found: {stories_dir}/{pattern}\n\n"
                f"Expected pattern: {stories_dir}/{epic_num}-{story_num}-*.md\n"
                f"Found: 0 matching files\n\n"
                f"Suggestion: Run 'bmad-assist compile -w create-story -e {epic_num} "
                f"-s {story_num}' first"
            )

        story_path = story_matches[0]  # First alphabetically (deterministic)

        # Distinguish between empty file and unreadable file
        try:
            if story_path.stat().st_size == 0:
                raise CompilerError(
                    f"Story file is empty: {story_path}\n\n"
                    f"The story file exists but contains no content (0 bytes).\n\n"
                    f"Suggestion: Regenerate the story using create-story workflow"
                )
        except OSError as e:
            raise CompilerError(
                f"Cannot read story file: {story_path}\n\n"
                f"Error: {e}\n\n"
                f"Suggestion: Check file permissions"
            ) from e

        story_content = safe_read_file(story_path, project_root)

        if not story_content:
            raise CompilerError(
                f"Story file unreadable: {story_path}\n\n"
                f"The story file exists but could not be read.\n"
                f"Possible causes: permission denied, encoding error, or path outside project.\n\n"
                f"Suggestion: Check file permissions and encoding (UTF-8 required)"
            )

        # 6a. Source files from story's File List (before story for recency-bias)
        file_list_paths = extract_file_paths_from_story(story_content)
        if file_list_paths:
            try:
                service = SourceContextService(context, "validate_story")
                source_files = service.collect_files(file_list_paths, None)
                files.update(source_files)
                if source_files:
                    logger.debug(
                        "Added %d source files to context for validate_story",
                        len(source_files),
                    )
                else:
                    logger.warning(
                        "No source files collected for validate_story "
                        "(budget=%d, candidates=%d)",
                        service.budget,
                        len(file_list_paths),
                    )
            except Exception as e:
                logger.warning(
                    "Failed to collect source files for validate_story: %s", e
                )

        # 6b. Insert story LAST (closest to instructions per recency-bias)
        files[str(story_path)] = story_content
        resolved["story_file"] = str(story_path)
        logger.debug("Added story file to context (LAST): %s", story_path)

        logger.info(
            "Built context with %d files for validation of story %s.%s",
            len(files),
            epic_num,
            story_num,
        )

        return files

    def _build_mission(
        self,
        workflow_ir: WorkflowIR,
        resolved: dict[str, Any],
    ) -> str:
        """Build adversarial review mission description.

        Args:
            workflow_ir: Workflow IR with description.
            resolved: Resolved variables.

        Returns:
            Mission description emphasizing adversarial validation.

        """
        epic_num = resolved.get("epic_num", "?")
        story_num = resolved.get("story_num", "?")
        story_title = resolved.get("story_title", "")

        title_part = f" - {story_title}" if story_title else ""

        return f"""Adversarial Story Validation

Target: Story {epic_num}.{story_num}{title_part}

Your mission is to FIND ISSUES in the story file:
- Identify missing requirements or acceptance criteria
- Find ambiguous or unclear specifications
- Detect gaps in technical context
- Suggest improvements for developer clarity

CRITICAL: You are a VALIDATOR, not a developer.
- Read-only: You cannot modify any files
- Adversarial: Assume the story has problems
- Thorough: Check all sections systematically

Focus on STORY QUALITY, not code implementation."""

    def compile(self, context: CompilerContext) -> CompiledWorkflow:
        """Compile validate-story workflow with given context.

        Executes the full compilation pipeline:
        1. Use pre-loaded workflow_ir from context (loaded by core.py)
        2. Resolve variables with sprint-status lookup
        3. Filter instructions
        4. Build adversarial mission description
        5. Generate XML output
        6. Apply patch post_process rules (regex transforms)
        7. Validate output against patch validation rules

        Patch Integration:
            Patches are now handled by core.py via load_workflow_ir().
            If a patch exists, context.workflow_ir contains the cached template.
            context.patch_path points to the patch file for post_process loading.
            Validation failures log WARNING but don't fail compilation.

        Args:
            context: The compilation context with:
                - workflow_ir: Pre-loaded WorkflowIR (from cache or original)
                - patch_path: Path to patch file (for post_process)

        Returns:
            CompiledWorkflow ready for output.

        Raises:
            CompilerError: If compilation fails at any stage.

        """
        # Step 1: Use pre-loaded workflow_ir from context
        workflow_ir = context.workflow_ir
        if workflow_ir is None:
            raise CompilerError(
                "workflow_ir not set in context. This is a bug - core.py should have loaded it."
            )

        workflow_dir = self.get_workflow_dir(context)

        # Use context_snapshot for automatic state preservation and rollback on error
        with context_snapshot(context):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Using workflow from %s", workflow_dir)

            # Step 2: Resolve variables with sprint-status lookup
            invocation_params = {
                k: v
                for k, v in context.resolved_variables.items()
                if k in ("epic_num", "story_num", "story_title", "date")
            }

            sprint_status_path = find_sprint_status_file(context)

            resolved = resolve_variables(context, invocation_params, sprint_status_path, None)

            # Step 2b: Resolve story file and extract metadata
            epic_num = resolved.get("epic_num")
            story_num = resolved.get("story_num")

            story_file, story_key, story_title = resolve_story_file(context, epic_num, story_num)

            # Update resolved variables with story metadata
            resolved["story_file"] = str(story_file) if story_file else None

            # Override story_key and story_title if we found an actual story file
            # (resolve_variables may have set fallback values)
            if story_key:
                resolved["story_key"] = story_key
            if story_title:
                # Override fallback "story-N" pattern (e.g., "story-1") with actual
                # title from filename. Only override if current title matches the
                # exact fallback pattern (story-{number}), not legitimate titles
                # that happen to start with "story-" (e.g., "story-service-api").
                current_title = resolved.get("story_title", "")
                if not current_title or re.match(r"^story-\d+$", current_title):
                    logger.debug("Extracted story_title from header: %s", story_title)
                    resolved["story_title"] = story_title

            resolved["story_id"] = f"{epic_num}.{story_num}"
            resolved["validation_focus"] = _VALIDATION_FOCUS

            # Generate timestamp for output filename (compile-time, not runtime)
            resolved["timestamp"] = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Model name for output filename - will be overridden at runtime if available
            # Default to "validator" as a placeholder
            if "model" not in resolved:
                resolved["model"] = "validator"

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Resolved %d variables", len(resolved))

            # Step 3: Build context using recency-bias ordering
            # This raises CompilerError if story file not found or empty
            context_files = self._build_context_files(context, resolved)

            # Step 4: Load template (empty for action-workflow)
            template_content = load_workflow_template(workflow_ir, context)

            # Step 5: Filter instructions
            filtered_instructions = filter_instructions(workflow_ir)
            filtered_instructions = substitute_variables(filtered_instructions, resolved)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Filtered instructions: %d bytes", len(filtered_instructions))

            # Step 6: Build adversarial mission description
            mission = self._build_mission(workflow_ir, resolved)

            # Step 6b: Filter garbage variables and normalize model name
            filtered_vars = filter_garbage_variables(resolved)

            # Normalize model name for filename safety
            if "model" in filtered_vars:
                filtered_vars["model"] = normalize_model_name(str(filtered_vars["model"]))
            else:
                filtered_vars["model"] = "validator"

            logger.debug(
                "Filtered vars keys (%d): %s", len(filtered_vars), list(filtered_vars.keys())
            )

            # Step 7: Generate XML output for token estimation
            compiled = CompiledWorkflow(
                workflow_name=self.workflow_name,
                mission=mission,
                context="",  # Empty - Story 11.2 will populate
                variables=filtered_vars,
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

            # Step 8: Apply post_process rules from patch (if exists)
            final_xml = apply_post_process(result.xml, context)

            # Step 8b: Validate output against patch validation rules
            if context.patch_path and context.patch_path.exists():
                try:
                    patch = load_patch(context.patch_path)
                    if patch.validation:
                        errors = validate_output(final_xml, patch.validation)
                        if errors:
                            logger.warning(
                                "Validation warnings for %s: %s",
                                self.workflow_name,
                                "; ".join(errors),
                            )
                except Exception as e:
                    logger.warning("Failed to validate output: %s", e)

            return CompiledWorkflow(
                workflow_name=self.workflow_name,
                mission=mission,
                context=final_xml,
                variables=resolved,
                instructions=filtered_instructions,
                output_template=template_content,
                token_estimate=result.token_estimate,
            )

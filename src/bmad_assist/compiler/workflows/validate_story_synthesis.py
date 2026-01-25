"""Compiler for the validate-story-synthesis workflow.

This module implements the WorkflowCompiler protocol for the synthesis workflow,
producing standalone prompts for Master LLM to synthesize validator findings.

Context includes strategic docs based on config (default: project-context only).
Synthesis workflows need minimal context as they aggregate validator outputs.

The synthesis context is focused:
- Strategic docs via StrategicContextService (default: project-context only)
- Story file being validated (primary target)
- Anonymized validation outputs (Validator A, B, C, D)
- NO PRD or epic files (validators already incorporated these)

This focused context allows Master to evaluate validator findings with
access to project rules but without the noise of verbose requirements
documents that validators already incorporated.

Public API:
    ValidateStorySynthesisCompiler: Workflow compiler implementing WorkflowCompiler protocol
"""

import logging
from datetime import date
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
    find_sprint_status_file,
    get_stories_dir,
    load_workflow_template,
    resolve_story_file,
    safe_read_file,
)
from bmad_assist.compiler.strategic_context import StrategicContextService
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext
from bmad_assist.compiler.variable_utils import (
    filter_garbage_variables,
    substitute_variables,
)
from bmad_assist.compiler.variables import resolve_variables
from bmad_assist.core.exceptions import CompilerError
from bmad_assist.validation.anonymizer import AnonymizedValidation

logger = logging.getLogger(__name__)

# Workflow path relative to project root
_WORKFLOW_RELATIVE_PATH = "_bmad/bmm/workflows/4-implementation/validate-story-synthesis"

# Minimum validators required for meaningful synthesis
_MIN_VALIDATORS = 2


class ValidateStorySynthesisCompiler:
    """Compiler for the validate-story-synthesis workflow.

    Implements the WorkflowCompiler protocol to compile the synthesis
    workflow into a standalone prompt. This is an action-workflow (template: false)
    focused on Master LLM synthesizing validator findings.

    The compilation pipeline:
    1. Use pre-loaded workflow_ir from context (set by core.compile_workflow)
    2. Validate inputs (epic_num, story_num, minimum 2 validations)
    3. Resolve variables (story_id, validator_count, date)
    4. Build minimal context (story file + anonymized validations ONLY)
    5. Build synthesis mission description
    6. Filter instructions via filter_instructions()
    7. Generate XML output via generate_output()
    8. Apply patch post_process rules if context.patch_path exists
    9. Return CompiledWorkflow with empty output_template

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "validate-story-synthesis"

    def get_required_files(self) -> list[str]:
        """Return list of required file glob patterns.

        Returns minimal patterns - synthesis only needs story file.
        PRD and project_context are intentionally excluded (architecture is optional).

        Returns:
            Glob patterns for files needed by synthesis workflow.

        """
        return [
            "**/sprint-artifacts/*.md",  # Story files only
        ]

    def get_variables(self) -> dict[str, Any]:
        """Return workflow-specific variables to resolve.

        Returns:
            Variables needed for synthesis compilation.

        """
        return {
            # Required (from invocation)
            "epic_num": None,
            "story_num": None,
            "session_id": None,  # Anonymization session for mapping
            "anonymized_validations": None,  # list[AnonymizedValidation]
            # Computed
            "story_id": None,  # "{epic_num}.{story_num}"
            "story_key": None,  # "{epic_num}-{story_num}-{slug}"
            "story_file": None,  # Resolved path to story file
            "validator_count": None,  # len(anonymized_validations)
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
                "epic_num is required for synthesis compilation.\n"
                "  Suggestion: Provide epic_num via invocation params"
            )
        if story_num is None:
            raise CompilerError(
                "story_num is required for synthesis compilation.\n"
                "  Suggestion: Provide story_num via invocation params"
            )

        # Validate minimum validations
        validations = context.resolved_variables.get("anonymized_validations", [])
        if not validations:
            raise CompilerError(
                "No anonymized validations provided for synthesis.\n"
                "  Why it's needed: Synthesis requires validator outputs to synthesize.\n"
                "  Suggestion: Run validate-story workflow first with multiple LLMs"
            )

        if len(validations) < _MIN_VALIDATORS:
            raise CompilerError(
                f"Synthesis requires at least {_MIN_VALIDATORS} validations, "
                f"but only {len(validations)} provided.\n"
                "  Why: Single validation doesn't need synthesis - use it directly.\n"
                "  Suggestion: Run validation with additional LLM providers"
            )

        # Workflow directory is validated by get_workflow_dir via discovery
        workflow_dir = self.get_workflow_dir(context)
        if not workflow_dir.exists():
            raise CompilerError(
                f"Workflow directory not found: {workflow_dir}\n"
                f"  Why it's needed: Contains workflow.yaml and instructions.xml for compilation\n"
                f"  How to fix: Reinstall bmad-assist or ensure BMAD is properly installed"
            )

    def _build_synthesis_context(
        self,
        context: CompilerContext,
        resolved: dict[str, Any],
        validations: list[AnonymizedValidation],
    ) -> dict[str, str]:
        """Build focused context files dict for synthesis.

        Includes:
        1. project_context.md (ground truth for evaluating validator claims)
        2. architecture.md (technical constraints for story refinement)
        3. Story file being validated
        4. Anonymized validations (as special XML block)

        Does NOT include: PRD, epic files (validators already had these).

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables.
            validations: List of anonymized validations.

        Returns:
            Dictionary mapping file paths/keys to content.

        Raises:
            CompilerError: If story file not found or empty.

        """
        files: dict[str, str] = {}
        project_root = context.project_root
        epic_num = resolved.get("epic_num")
        story_num = resolved.get("story_num")

        # 1. Strategic docs via StrategicContextService
        # Default config for validate_story_synthesis: project-context only (minimal context)
        strategic_service = StrategicContextService(context, "validate_story_synthesis")
        strategic_files = strategic_service.collect()
        files.update(strategic_files)
        logger.debug("Added %d strategic docs to synthesis context", len(strategic_files))

        # 2. Story file (REQUIRED)
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

        story_path = story_matches[0]

        # Check for empty file and capture mtime for debugging
        try:
            stat = story_path.stat()
            if stat.st_size == 0:
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

        # 2a. Source files from story's File List (before story for recency-bias)
        file_list_paths = extract_file_paths_from_story(story_content)
        if file_list_paths:
            try:
                service = SourceContextService(context, "validate_story_synthesis")
                source_files = service.collect_files(file_list_paths, None)
                files.update(source_files)
                if source_files:
                    logger.debug(
                        "Added %d source files to context for validate_story_synthesis",
                        len(source_files),
                    )
                else:
                    logger.warning(
                        "No source files collected for validate_story_synthesis "
                        "(budget=%d, candidates=%d)",
                        service.budget,
                        len(file_list_paths),
                    )
            except Exception as e:
                logger.warning(
                    "Failed to collect source files for validate_story_synthesis: %s", e
                )

        # 2b. Story file
        files[str(story_path)] = story_content
        # Log mtime at compile time for debugging content freshness (Story 22.4 AC3)
        logger.debug(
            "Added story file to synthesis context: %s (mtime=%d, size=%d bytes)",
            story_path,
            int(stat.st_mtime),
            stat.st_size,
        )

        # 4. Validations (each as a separate file for clean CDATA handling)
        # Sort by validator_id for deterministic ordering
        sorted_validations = sorted(validations, key=lambda v: v.validator_id)
        for v in sorted_validations:
            # Use validator ID as virtual path (e.g., "[Validator A]")
            validation_path = f"[{v.validator_id}]"
            files[validation_path] = v.content
            logger.debug("Added validation to synthesis context: %s", validation_path)

        # Count files for logging (excluding virtual paths starting with [)
        file_count = len([k for k in files if not k.startswith("[")])
        logger.info(
            "Built synthesis context with %d files and %d validations for story %s.%s",
            file_count,
            len(validations),
            epic_num,
            story_num,
        )

        return files

    def _build_synthesis_mission(self, resolved: dict[str, Any]) -> str:
        """Build synthesis mission description.

        Args:
            resolved: Resolved variables.

        Returns:
            Mission description for Master synthesis.

        """
        epic_num = resolved.get("epic_num", "?")
        story_num = resolved.get("story_num", "?")
        validator_count = resolved.get("validator_count", 0)

        return f"""Master Synthesis: Story {epic_num}.{story_num}

You are synthesizing {validator_count} independent validator reviews.

Your mission:
1. VERIFY each issue raised by validators
   - Cross-reference with story content
   - Identify false positives (issues that aren't real problems)
   - Confirm valid issues with evidence

2. PRIORITIZE real issues by severity
   - Critical: Blocks implementation or causes major problems
   - High: Significant gaps or ambiguities
   - Medium: Improvements that would help
   - Low: Nice-to-have suggestions

3. SYNTHESIZE findings
   - Merge duplicate issues from different validators
   - Note validator consensus (if 3+ agree, high confidence)
   - Highlight unique insights from individual validators

4. APPLY changes to story file
   - You have WRITE PERMISSION to modify the story
   - CRITICAL: Before using Edit tool, ALWAYS Read the target file first
   - Use EXACT content from Read tool output as old_string, NOT content from this prompt
   - If Read output is truncated, use offset/limit parameters to locate the target section
   - Apply fixes for verified issues
   - Document what you changed and why

Output format:
## Synthesis Summary
## Issues Verified (by severity)
## Issues Dismissed (false positives with reasoning)
## Changes Applied"""

    def compile(self, context: CompilerContext) -> CompiledWorkflow:
        """Compile synthesis workflow with given context.

        Executes the full compilation pipeline:
        1. Parse workflow files (or load from cached patched template)
        2. Validate context (epic_num, story_num, minimum validations)
        3. Resolve variables
        4. Build minimal context (story + validations ONLY)
        5. Build synthesis mission description
        6. Filter instructions
        7. Generate XML output
        8. Apply patch post_process rules if exists
        9. Validate output against patch validation rules

        Args:
            context: The compilation context with project paths and initial variables.

        Returns:
            CompiledWorkflow ready for output.

        Raises:
            CompilerError: If compilation fails at any stage.

        """
        # Step 1: Use pre-loaded workflow_ir from context (set by core.compile_workflow)
        workflow_ir = context.workflow_ir
        if workflow_ir is None:
            raise CompilerError(
                "workflow_ir not set in context.\n"
                f"  Workflow: {self.workflow_name}\n"
                "  Reason: Expected core.compile_workflow() to set context.workflow_ir\n"
                "  Suggestion: Call compile_workflow() instead of compiler.compile() directly"
            )

        # Use context_snapshot for automatic state preservation and rollback on error
        with context_snapshot(context):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Using workflow_ir from context (patch: %s)",
                    context.patch_path.name if context.patch_path else "none",
                )

            # Step 2: Validate inputs early
            self.validate_context(context)

            # Step 3: Extract invocation params
            epic_num = context.resolved_variables.get("epic_num")
            story_num = context.resolved_variables.get("story_num")
            session_id = context.resolved_variables.get("session_id")
            validations: list[AnonymizedValidation] = context.resolved_variables.get(
                "anonymized_validations", []
            )

            # Step 3b: Resolve ALL workflow variables (communication_language, etc.)
            invocation_params = {
                k: v
                for k, v in context.resolved_variables.items()
                if k in ("epic_num", "story_num", "date")
            }
            sprint_status_path = find_sprint_status_file(context)
            resolved = resolve_variables(context, invocation_params, sprint_status_path, None)

            # Resolve story file path
            story_file, story_key, story_title = resolve_story_file(context, epic_num, story_num)

            # Merge synthesis-specific variables on top
            resolved.update(
                {
                    "epic_num": epic_num,
                    "story_num": story_num,
                    "story_id": f"{epic_num}.{story_num}",
                    "story_key": story_key or f"{epic_num}-{story_num}",
                    "story_file": str(story_file) if story_file else None,
                    "story_title": story_title,
                    "session_id": session_id,
                    "validator_count": len(validations),
                    "date": date.today().isoformat(),
                }
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Resolved %d variables", len(resolved))

            # Step 4: Build minimal synthesis context
            context_files = self._build_synthesis_context(context, resolved, validations)

            # Step 5: Build synthesis mission
            mission = self._build_synthesis_mission(resolved)

            # Step 6: Load template (empty for action-workflow)
            template_content = load_workflow_template(workflow_ir, context)

            # Step 7: Filter instructions
            filtered_instructions = filter_instructions(workflow_ir)
            filtered_instructions = substitute_variables(filtered_instructions, resolved)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Filtered instructions: %d bytes", len(filtered_instructions))

            # Step 7b: Filter garbage variables
            filtered_vars = filter_garbage_variables(resolved)

            # Step 8: Generate XML output
            compiled = CompiledWorkflow(
                workflow_name=self.workflow_name,
                mission=mission,
                context="",  # Will be populated by generate_output
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

            # Step 9: Apply post_process rules from patch (if exists)
            final_xml = apply_post_process(result.xml, context)

            # Step 9b: Validate output against patch validation rules
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

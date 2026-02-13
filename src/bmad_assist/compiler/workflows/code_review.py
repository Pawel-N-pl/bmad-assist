"""Compiler for the code-review workflow.

This module implements the WorkflowCompiler protocol for the code-review
workflow, producing standalone prompts for adversarial code review with
all necessary context embedded including git diff and modified source files.

Public API:
    CodeReviewCompiler: Workflow compiler class implementing WorkflowCompiler protocol
    DEFAULT_SOURCE_FILES_TOKEN_BUDGET: Token budget for source files from git diff
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from bmad_assist.compiler.filtering import filter_instructions
from bmad_assist.compiler.output import generate_output
from bmad_assist.compiler.shared_utils import (
    apply_post_process,
    context_snapshot,
    find_sprint_status_file,
    resolve_story_file,
    safe_read_file,
)
from bmad_assist.compiler.source_context import (
    SourceContextService,
    extract_file_paths_from_story,
    get_git_diff_files,
)
from bmad_assist.compiler.strategic_context import StrategicContextService
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext, WorkflowIR
from bmad_assist.compiler.variable_utils import substitute_variables
from bmad_assist.compiler.variables import resolve_variables
from bmad_assist.core.exceptions import CompilerError
from bmad_assist.git import get_validated_diff
from bmad_assist.testarch.context import collect_tea_context

logger = logging.getLogger(__name__)

# Maximum lines for git diff before truncation
_MAX_DIFF_LINES = 500

# Timeout for git commands in seconds
_GIT_TIMEOUT = 30

# Pattern for parsing git diff --stat output
# Matches: " src/file.py | 42 ++++----" or " src/file.py | 42 +"
# Uses non-greedy match to support filenames with spaces
_STAT_PATTERN = re.compile(r"^\s*(.+?)\s*\|\s*(\d+)", re.MULTILINE)

# Pattern for binary files: " file.bin | Bin 1234 -> 5678 bytes"
_BINARY_PATTERN = re.compile(r"^\s*[^\s|]+\s*\|\s*Bin\s+", re.MULTILINE)

# Pattern for renamed files with changes: " old.py => new.py | 5"
# Also handles brace-style: " src/{old => new}/file.py | 10"
# Captures new path and change count
_RENAME_WITH_CHANGES_PATTERN = re.compile(
    r"^\s*(?:\{[^}]+\}\s*=>\s*)?(.+?)\s*=>\s*(.+?)\s*\|\s*(\d+)", re.MULTILINE
)


def _capture_git_diff(context: CompilerContext) -> str:
    """Capture git diff with intelligent filtering and validation.

    Uses get_validated_diff() which:
    - Detects proper merge-base (handles merge commits correctly)
    - Filters out cache/metadata files that cause false positives
    - Validates diff quality (warns if too much garbage)

    This addresses the 92% false positive rate issue identified in
    benchmark-analysis.md by ensuring reviewers only see source files.

    Args:
        context: Compilation context with project root.

    Returns:
        Filtered git diff wrapped in markers, or empty string on any error.

    """
    project_root = context.project_root

    try:
        # Check if this is the git repository ROOT (not just a subdirectory)
        check_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=project_root,
            capture_output=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )

        if check_result.returncode != 0:
            logger.debug("Not a git repository: %s", project_root)
            return ""

        # Verify we're at the git root, not a subdirectory of another repo
        git_root = Path(check_result.stdout.strip()).resolve()
        if git_root != project_root.resolve():
            logger.debug(
                "Project %s is inside git repo %s but not at root",
                project_root,
                git_root,
            )
            return ""

        # Use the new validated diff capture with P0/P1 fixes:
        # - P0: Path filtering (excludes cache, metadata, node_modules, etc.)
        # - P0: Merge-base detection (handles merge commits correctly)
        # - P1: Quality validation (warns if garbage ratio too high)
        diff_content, validation = get_validated_diff(
            project_root,
            max_garbage_ratio=0.3,
            raise_on_invalid=False,  # Warn but don't block
        )

        # Log validation results for debugging
        if validation.total_files > 0:
            logger.debug(
                "Diff validation: %d source files, %d garbage files (%.0f%% garbage)",
                validation.source_files,
                validation.garbage_files,
                validation.garbage_ratio * 100,
            )

        if not validation.is_valid:
            logger.warning(
                "Diff quality warning: %s - review may have false positives",
                "; ".join(validation.issues),
            )

        return diff_content

    except FileNotFoundError:
        logger.warning("git command not found")
        return ""
    except subprocess.TimeoutExpired:
        logger.error("git command timed out after %ds", _GIT_TIMEOUT)
        return ""
    except OSError as e:
        logger.warning("git command failed: %s", e)
        return ""


def _extract_modified_files_from_stat(
    stat_output: str,
    skip_docs: bool = True,
    skip_generated: bool = True,
) -> list[tuple[str, int]]:
    """Extract modified file paths and change counts from git diff --stat output.

    Parses output like:
        src/file.py | 42 ++++++----
        tests/test.py | 25 ++++
        old.py => new.py | 5 +++--

    Args:
        stat_output: Raw output from git diff --stat.
        skip_docs: If True, skip files in docs/ directory.
        skip_generated: If True, skip BMAD-generated files (_bmad-output, .bmad-assist).

    Returns:
        List of (path, change_count) tuples sorted by changes desc, path asc.

    """
    # Extract only the stat section (before patch content starts)
    # The stat section ends with a summary line like:
    #   "3 files changed, 25 insertions(+), 10 deletions(-)"
    # After that comes the actual patch content which can contain | characters
    stat_end_pattern = re.compile(r"^\s*\d+\s+files?\s+changed", re.MULTILINE | re.IGNORECASE)
    stat_end_match = stat_end_pattern.search(stat_output)
    if stat_end_match:
        # Only process content up to and including the summary line
        stat_output = stat_output[: stat_end_match.end()]

    # Find all binary files to skip
    binary_matches = set()
    for match in _BINARY_PATTERN.finditer(stat_output):
        # Extract path from binary pattern
        line = match.group(0)
        path_match = re.match(r"^\s*([^\s|]+)", line)
        if path_match:
            binary_matches.add(path_match.group(1))

    result: list[tuple[str, int]] = []
    seen_paths: set[str] = set()

    # First, process renamed files (they have => in the line)
    for match in _RENAME_WITH_CHANGES_PATTERN.finditer(stat_output):
        # Group 2 is new path, group 3 is change count
        new_path = match.group(2).strip()
        try:
            changes = int(match.group(3))
        except ValueError:
            continue

        # Skip pure renames with zero content changes (AC4 requirement)
        if changes == 0:
            continue

        # Skip docs/ files if requested
        if skip_docs and new_path.startswith("docs/"):
            continue

        # Skip BMAD-generated files (synthesis artifacts, cache, etc.)
        if skip_generated and (
            new_path.startswith("_bmad-output/") or
            new_path.startswith(".bmad-assist/") or
            "/_bmad-output/" in new_path or
            "/.bmad-assist/" in new_path
        ):
            continue

        if new_path not in seen_paths:
            result.append((new_path, changes))
            seen_paths.add(new_path)

    # Then, process regular files (no =>)
    for match in _STAT_PATTERN.finditer(stat_output):
        path = match.group(1)
        try:
            changes = int(match.group(2))
        except ValueError:
            continue

        # Skip binary files
        if path in binary_matches:
            continue

        # Skip files that have => in them (they're the "old" part of renames)
        # These are already captured by the rename pattern above
        if "=>" in path:
            continue

        # Skip docs/ files if requested
        if skip_docs and path.startswith("docs/"):
            continue

        # Skip BMAD-generated files (synthesis artifacts, cache, etc.)
        if skip_generated and (
            path.startswith("_bmad-output/") or
            path.startswith(".bmad-assist/") or
            "/_bmad-output/" in path or
            "/.bmad-assist/" in path
        ):
            continue

        if path not in seen_paths:
            result.append((path, changes))
            seen_paths.add(path)

    # Sort by changes descending, then path ascending for determinism
    result.sort(key=lambda x: (-x[1], x[0]))

    return result


class CodeReviewCompiler:
    """Compiler for the code-review workflow.

    Implements the WorkflowCompiler protocol to compile the code-review
    workflow into a standalone prompt. The code-review workflow is an
    action-workflow (no template output), focused on adversarial review
    of implemented stories with git diff and modified files embedded.

    Context embedding follows recency-bias ordering:
    1. project_context.md (general)
    2. architecture.md (technical constraints)
    3. ux.md (optional UI context)
    4. git_diff section (implementation changes)
    5. modified source files (what to review)
    6. story file (LAST - what was requested)

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "code-review"

    def get_required_files(self) -> list[str]:
        """Return list of required file glob patterns.

        Returns:
            Glob patterns for files needed by code-review workflow.

        """
        return [
            "**/project_context.md",
            "**/project-context.md",
            "**/architecture*.md",
            "**/ux*.md",
            "**/sprint-status.yaml",
        ]

    def get_variables(self) -> dict[str, Any]:
        """Return workflow-specific variables to resolve.

        Returns:
            Variables needed for code-review compilation.

        """
        # NOTE: git_diff is NOT included here - it's embedded as a context file
        # to avoid HTML-escaped duplication in the <variables> section
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
                "epic_num is required for code-review compilation.\n"
                "  Suggestion: Provide epic_num via invocation params or ensure "
                "sprint-status.yaml has a story in review status"
            )
        if story_num is None:
            raise CompilerError(
                "story_num is required for code-review compilation.\n"
                "  Suggestion: Provide story_num via invocation params or ensure "
                "sprint-status.yaml has a story in review status"
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
                f"  Suggestion: Ensure the story exists and is in review status"
            )

    def compile(self, context: CompilerContext) -> CompiledWorkflow:
        """Compile code-review workflow with given context.

        Executes the full compilation pipeline:
        1. Use pre-loaded workflow_ir from context
        2. Resolve variables with sprint-status lookup
        3. Capture git diff
        4. Build context files with recency-bias ordering (story LAST)
        5. Filter instructions
        6. Generate XML output

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

            resolved = resolve_variables(context, invocation_params, sprint_status_path, None)

            story_path, story_key, _ = resolve_story_file(
                context,
                resolved.get("epic_num"),
                resolved.get("story_num"),
            )
            if story_path:
                resolved["story_file"] = str(story_path)
            if story_key:
                resolved["story_key"] = story_key

            # Capture git diff (stored in context_files only, not in variables
            # to avoid HTML-escaped duplication in <variables> section)
            git_diff = _capture_git_diff(context)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Resolved %d variables", len(resolved))

            context_files = self._build_context_files(context, resolved, git_diff)

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
        git_diff: str = "",
    ) -> dict[str, str]:
        """Build context files dict with recency-bias ordering.

        Files are ordered from general (early) to specific (late):
        1. Strategic docs via StrategicContextService (project-context only by default)
        2. git_diff section (embedded as virtual file)
        3. modified source files (what to review)
        4. story file (LAST - what was requested)

        Args:
            context: Compilation context with paths.
            resolved: Resolved variables containing epic_num, story_num.
            git_diff: Git diff content (passed separately to avoid variable duplication).

        Returns:
            Dictionary mapping file paths to content, ordered by recency-bias.

        """
        files: dict[str, str] = {}
        project_root = context.project_root

        # 1. Strategic docs (project-context only by default - 0% PRD citation in benchmarks)
        strategic_service = StrategicContextService(context, "code_review")
        strategic_files = strategic_service.collect()
        files.update(strategic_files)

        # 1b. Include code antipatterns - reviewers should know what mistakes to look for
        from bmad_assist.compiler.strategic_context import load_antipatterns

        files.update(load_antipatterns(context, "code"))

        # 1c. TEA Context (test-design) for reviewing against test plan
        files.update(collect_tea_context(context, "code_review", resolved))

        # 2. Git diff (embedded as virtual file, not in variables)
        if git_diff:
            files["[git-diff]"] = git_diff

        # 3. Source files using SourceContextService (File List + git diff)
        # Get File List from story file
        story_path_str = resolved.get("story_file")
        file_list_paths: list[str] = []
        if story_path_str:
            story_path = Path(story_path_str)
            story_content = safe_read_file(story_path, project_root)
            if story_content:
                file_list_paths = extract_file_paths_from_story(story_content)
                if file_list_paths:
                    logger.debug("Extracted %d files from File List", len(file_list_paths))

        # Get git diff files with hunk info
        git_diff_files = None
        if git_diff:
            modified_files = _extract_modified_files_from_stat(git_diff, skip_docs=True)
            if modified_files:
                git_diff_files = get_git_diff_files(project_root, git_diff)

        # Collect source files using service
        service = SourceContextService(context, "code_review")
        source_files = service.collect_files(file_list_paths, git_diff_files)
        files.update(source_files)

        # 4. Story file (LAST - closest to instructions per recency-bias)
        story_path_str = resolved.get("story_file")
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
            Mission description string emphasizing adversarial review.

        """
        base_description = workflow_ir.raw_config.get(
            "description", "Perform an ADVERSARIAL Senior Developer code review"
        )

        epic_num = resolved.get("epic_num", "?")
        story_num = resolved.get("story_num", "?")
        story_title = resolved.get("story_title", "")

        if story_title:
            mission = (
                f"{base_description}\n\n"
                f"Target: Story {epic_num}.{story_num} - {story_title}\n"
                f"Find 3-10 specific issues. Challenge every claim."
            )
        else:
            mission = (
                f"{base_description}\n\n"
                f"Target: Story {epic_num}.{story_num}\n"
                f"Find 3-10 specific issues. Challenge every claim."
            )

        return mission

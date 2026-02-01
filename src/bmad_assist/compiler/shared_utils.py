"""Shared utility functions for story-related workflow compilers.

This module provides common functionalities like:
- Variable substitution in text
- Safe file reading with path validation
- Resolving story file paths and metadata
- Loading cached templates
- Finding specific project context files (sprint-status, project_context, etc.)
- Finding previous story files for recency-bias context
"""

import logging
import re
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from bmad_assist.compiler.patching import (
    TemplateCache,
    discover_patch,
    load_patch,
    post_process_compiled,
)
from bmad_assist.compiler.types import CompilerContext, WorkflowIR
from bmad_assist.core.exceptions import CompilerError

logger = logging.getLogger(__name__)


def get_stories_dir(context: CompilerContext) -> Path:
    """Get stories directory using paths singleton if available.

    Uses the new paths architecture when initialized, with fallback
    to legacy output_folder/sprint-artifacts for backward compatibility
    with standalone tests.

    Args:
        context: Compiler context with output_folder.

    Returns:
        Path to stories directory.

    """
    try:
        from bmad_assist.core.paths import get_paths

        return get_paths().stories_dir
    except RuntimeError:
        # Paths not initialized (e.g., in standalone compiler tests)
        # Fallback to legacy location for test compatibility
        return context.output_folder / "sprint-artifacts"


def get_validations_dir(context: CompilerContext) -> Path:
    """Get validations directory using paths singleton if available.

    Args:
        context: Compiler context.

    Returns:
        Path to story-validations directory.

    """
    try:
        from bmad_assist.core.paths import get_paths

        return get_paths().validations_dir
    except RuntimeError:
        # Paths not initialized - use fallback with legacy location for test compatibility
        return context.output_folder / "sprint-artifacts" / "story-validations"


def get_sprint_status_path(context: CompilerContext) -> Path:
    """Get sprint status file path using paths singleton if available.

    Args:
        context: Compiler context.

    Returns:
        Path to sprint-status.yaml file.

    """
    try:
        from bmad_assist.core.paths import get_paths

        return get_paths().sprint_status_file
    except RuntimeError:
        return context.output_folder / "sprint-artifacts" / "sprint-status.yaml"


def get_planning_artifacts_dir(context: CompilerContext) -> Path:
    """Get planning artifacts directory using paths singleton if available.

    Args:
        context: Compiler context.

    Returns:
        Path to planning artifacts directory (where PRD, architecture live).

    """
    try:
        from bmad_assist.core.paths import get_paths

        return get_paths().planning_artifacts
    except RuntimeError:
        return context.output_folder / "planning-artifacts"


def get_epics_dir(context: CompilerContext) -> Path:
    """Get epics directory using paths singleton if available.

    Args:
        context: Compiler context.

    Returns:
        Path to epics directory.

    """
    try:
        from bmad_assist.core.paths import get_paths

        return get_paths().epics_dir
    except RuntimeError:
        return context.output_folder / "epics"


def normalize_model_name(model_name: str) -> str:
    """Normalize model name to filesystem-safe format.

    Converts model name to lowercase and replaces special characters
    with underscores for use in filenames.

    Examples:
        "claude-3-5-sonnet-20241022" -> "claude_3_5_sonnet_20241022"
        "gpt-4o" -> "gpt_4o"
        "Gemini 2.0 Flash" -> "gemini_2_0_flash"

    Args:
        model_name: Raw model name from provider config.

    Returns:
        Normalized model name safe for filenames.

    """
    if not model_name:
        return "unknown"

    # Lowercase
    normalized = model_name.lower()

    # Replace common separators with underscore
    for char in ["-", ".", " ", "/"]:
        normalized = normalized.replace(char, "_")

    # Remove any remaining non-alphanumeric except underscore
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)

    # Collapse multiple underscores
    normalized = re.sub(r"_+", "_", normalized)

    # Strip leading/trailing underscores
    normalized = normalized.strip("_")

    return normalized or "unknown"


def anonymize_model_name(model_index: int) -> str:
    """Generate anonymous model identifier for multi-LLM validation.

    Used when running multiple validators in parallel to prevent
    bias from model name in synthesis phase.

    Args:
        model_index: Zero-based index of the model in multi-LLM list.

    Returns:
        Anonymous identifier like "validator_a", "validator_b", etc.

    """
    # Use letters a-z, then aa, ab, etc for more than 26
    if model_index < 26:
        letter = chr(ord("a") + model_index)
        return f"validator_{letter}"
    else:
        first = chr(ord("a") + (model_index // 26) - 1)
        second = chr(ord("a") + (model_index % 26))
        return f"validator_{first}{second}"


def estimate_tokens(content: str) -> int:
    """Estimate token count for content.

    Uses simple heuristic: ~4 characters per token on average.
    This provides a fast approximation suitable for budget tracking.

    Args:
        content: Text content to estimate.

    Returns:
        Estimated token count.

    """
    return len(content) // 4


def safe_read_file(path: Path, project_root: Path | None = None) -> str:
    """Safely read file content with path validation.

    Ensures the path is within the project_root if provided and handles
    common file reading errors.

    Args:
        path: File path to read.
        project_root: Optional. Project root for security validation.

    Returns:
        File content or empty string on error.

    """
    try:
        resolved = path.resolve()
        if project_root is not None:
            resolved_root = project_root.resolve()
            is_in_project = resolved.is_relative_to(resolved_root)
            # Allow bundled workflows (installed in bmad_assist/workflows/)
            is_bundled = "bmad_assist/workflows" in str(resolved) or "bmad_assist\\workflows" in str(resolved) # noqa: E501
            if not is_in_project and not is_bundled:
                logger.warning("Path outside project root, skipping: %s", path)
                return ""
        return resolved.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.debug("File not found: %s", path)
        return ""
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Error reading %s: %s", path, e)
        return ""


def resolve_story_file(
    context: CompilerContext,
    epic_num: Any,
    story_num: Any,
) -> tuple[Path | None, str | None, str | None]:
    """Resolve story file path and extract metadata.

    Args:
        context: Compilation context with paths.
        epic_num: Epic number.
        story_num: Story number.

    Returns:
        Tuple of (story_path, story_key, story_title) or (None, None, None).

    """
    stories_dir = get_stories_dir(context)
    if not stories_dir.exists():
        return None, None, None

    pattern = f"{epic_num}-{story_num}-*.md"
    matches = sorted(stories_dir.glob(pattern))

    if not matches:
        logger.debug("No story file found matching %s", pattern)
        return None, None, None

    story_path = matches[0]
    filename = story_path.stem  # e.g., "11-1-validate-story-compiler-core"

    # Extract slug from filename (after epic-story prefix)
    parts = filename.split("-", 2)
    slug = parts[2] if len(parts) >= 3 else ""

    story_key = filename  # e.g., "11-1-validate-story-compiler-core"
    story_title = slug  # e.g., "validate-story-compiler-core"

    logger.debug("Resolved story file: %s (key=%s, title=%s)", story_path, story_key, story_title)
    return story_path, story_key, story_title


def try_load_cached_template(
    workflow_name: str,
    context: CompilerContext,
    workflow_dir: Path,
) -> WorkflowIR | None:
    """Try to load workflow from cached patched template.

    Checks if a valid cached patched template exists. Priority:
    1. Project cache (if patch is from project)
    2. Global cache

    Args:
        workflow_name: The name of the workflow.
        context: Compilation context with project paths.
        workflow_dir: Original workflow directory (for fallback paths).

    Returns:
        WorkflowIR from cached template, or None if no valid cache.

    """
    cache = TemplateCache()

    patch_path = discover_patch(workflow_name, context.project_root, cwd=context.cwd)
    if patch_path is None:
        logger.debug("No patch found for %s, using original workflow", workflow_name)
        return None

    workflow_yaml_path = workflow_dir / "workflow.yaml"
    instructions_xml_path = workflow_dir / "instructions.xml"

    if not workflow_yaml_path.exists() or not instructions_xml_path.exists():
        logger.debug("Original workflow files missing, cannot validate cache")
        return None

    source_files = {
        "workflow.yaml": workflow_yaml_path,
        "instructions.xml": instructions_xml_path,
    }

    # Determine cache location based on patch location
    # Priority: project → CWD → global
    project_patch_dir = context.project_root / ".bmad-assist" / "patches"
    is_project_patch = patch_path.is_relative_to(project_patch_dir)

    is_cwd_patch = False
    if context.cwd is not None:
        cwd_patch_dir = context.cwd / ".bmad-assist" / "patches"
        resolved_cwd = context.cwd.resolve()
        resolved_project = context.project_root.resolve()
        if resolved_cwd != resolved_project:
            is_cwd_patch = patch_path.is_relative_to(cwd_patch_dir)

    # Check caches in priority order based on patch location
    cache_location_path: Path | None = None
    cache_location_name: str = "global"

    if is_project_patch:
        # Patch is from project - check project cache first
        if cache.is_valid(
            workflow_name,
            context.project_root,
            source_files=source_files,
            patch_path=patch_path,
        ):
            cache_location_path = context.project_root
            cache_location_name = "project"
            logger.debug("Using project cache for %s", workflow_name)
        elif cache.is_valid(
            workflow_name,
            None,
            source_files=source_files,
            patch_path=patch_path,
        ):
            cache_location_path = None
            cache_location_name = "global"
            logger.debug("Using global cache for %s (project cache invalid)", workflow_name)
        else:
            logger.debug("No valid cache found for %s", workflow_name)
            return None
    elif is_cwd_patch:
        # Patch is from CWD - check CWD cache first
        if cache.is_valid(
            workflow_name,
            context.cwd,
            source_files=source_files,
            patch_path=patch_path,
        ):
            cache_location_path = context.cwd
            cache_location_name = "cwd"
            logger.debug("Using CWD cache for %s", workflow_name)
        elif cache.is_valid(
            workflow_name,
            None,
            source_files=source_files,
            patch_path=patch_path,
        ):
            cache_location_path = None
            cache_location_name = "global"
            logger.debug("Using global cache for %s (CWD cache invalid)", workflow_name)
        else:
            logger.debug("No valid cache found for %s", workflow_name)
            return None
    else:
        # Patch is global - check global cache
        if not cache.is_valid(
            workflow_name,
            None,
            source_files=source_files,
            patch_path=patch_path,
        ):
            logger.debug("Global cache invalid or missing for %s", workflow_name)
            return None
        cache_location_path = None
        cache_location_name = "global"

    cached_content = cache.load_cached(workflow_name, cache_location_path)
    if cached_content is None:
        logger.debug("Failed to load cached template")
        return None

    logger.info(
        "Using cached patched template for %s (%s cache)", workflow_name, cache_location_name
    )

    try:
        yaml_match = re.search(
            r"<workflow-yaml>\s*(.*?)\s*</workflow-yaml>",
            cached_content,
            re.DOTALL,
        )
        if not yaml_match:
            logger.warning("Cached template missing <workflow-yaml> section")
            return None

        yaml_content = yaml_match.group(1)
        raw_config = yaml.safe_load(yaml_content)

        instructions_match = re.search(
            r"<instructions-xml>\s*(.*?)\s*</instructions-xml>",
            cached_content,
            re.DOTALL,
        )
        if not instructions_match:
            logger.warning("Cached template missing <instructions-xml> section")
            return None

        raw_instructions = instructions_match.group(1)

        template_path = raw_config.get("template")
        validation_path = raw_config.get("validation")

        return WorkflowIR(
            name=workflow_name,
            config_path=workflow_yaml_path,
            instructions_path=instructions_xml_path,
            template_path=template_path,
            validation_path=validation_path,
            raw_config=raw_config,
            raw_instructions=raw_instructions,
        )

    except yaml.YAMLError as e:
        logger.warning("Failed to parse cached template YAML: %s", e)
        return None
    except Exception as e:
        logger.warning("Failed to parse cached template: %s", e)
        return None


def load_workflow_template(
    workflow_ir: WorkflowIR,
    context: CompilerContext,
) -> str:
    """Load template from embedded cache or file.

    Priority:
    1. workflow_ir.output_template (embedded in cached patched template)
    2. workflow_ir.template_path (load from file with path resolution)

    Handles path resolution and security checks for file-based templates.

    Args:
        workflow_ir: Workflow IR with template path or embedded content.
        context: Compilation context.

    Returns:
        Template content or empty string.

    Raises:
        CompilerError: If path security violation occurs.

    """
    # Priority 1: Use embedded template from cached patched workflow
    if workflow_ir.output_template is not None:
        logger.debug("Using embedded output template from cached workflow")
        return workflow_ir.output_template

    # Priority 2: Load from template_path
    if not workflow_ir.template_path:
        logger.debug("No template defined (action-workflow or explicit false)")
        return ""

    template_path_str = str(workflow_ir.template_path)
    template_path_str = template_path_str.replace(
        "{installed_path}", str(workflow_ir.config_path.parent)
    )
    template_path_str = template_path_str.replace("{project-root}", str(context.project_root))

    template_path = Path(template_path_str)

    try:
        if ".." in str(template_path):
            raise CompilerError(
                f"Path security violation: {template_path}\n"
                f"  Reason: Path traversal detected (..)\n"
                f"  Suggestion: Use paths within the project directory"
            )

        resolved_template = template_path.resolve()
        resolved_root = context.project_root.resolve()

        # Check if template is within project root
        is_in_project = resolved_template.is_relative_to(resolved_root)

        # Allow bundled workflows (installed in bmad_assist/workflows/)
        is_bundled = "bmad_assist/workflows" in str(resolved_template) or "bmad_assist\\workflows" in str(resolved_template) # noqa: E501

        if not is_in_project and not is_bundled:
            raise CompilerError(
                f"Path security violation: {template_path}\n"
                f"  Reason: Path outside project boundary\n"
                f"  Suggestion: Use paths within the project directory"
            )
    except ValueError:  # For paths that might not resolve or are malformed
        raise CompilerError(
            f"Path security violation: {template_path}\n"
            f"  Reason: Path outside project boundary\n"
            f"  Suggestion: Use paths within the project directory"
        ) from None

    if not template_path.exists():
        logger.warning("Template file not found: %s", template_path)
        return ""

    content = safe_read_file(template_path, context.project_root)
    logger.debug("Loaded template from %s", template_path)
    return content


def find_sprint_status_file(context: CompilerContext) -> Path | None:
    """Find sprint-status.yaml in known locations.

    Searches in priority order:
    1. implementation_artifacts/sprint-status.yaml (new BMAD v6 structure)
    2. output_folder/sprint-artifacts/sprint-status.yaml (legacy)
    3. output_folder/sprint-status.yaml (legacy fallback)
    4. project_knowledge/sprint-artifacts/sprint-status.yaml (brownfield)

    Args:
        context: Compilation context with paths.

    Returns:
        Path to sprint-status.yaml or None if not found.

    """
    candidates: list[Path] = []

    # Try paths singleton first (preferred)
    try:
        from bmad_assist.core.paths import get_paths

        paths = get_paths()
        candidates.append(paths.implementation_artifacts / "sprint-status.yaml")
        candidates.append(paths.project_knowledge / "sprint-artifacts" / "sprint-status.yaml")
    except RuntimeError:
        pass

    # Fallback locations
    candidates.extend(
        [
            context.output_folder / "planning-artifacts" / "sprint-status.yaml",  # Beta default
            context.output_folder / "sprint-artifacts" / "sprint-status.yaml",
            context.output_folder / "sprint-status.yaml",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    logger.debug("sprint-status.yaml not found in any location")
    return None


def find_project_context_file(context: CompilerContext) -> Path | None:
    """Find project_context.md (or project-context.md) in known locations.

    Searches in: project_knowledge/ (if set), output_folder/, project_root/docs/,
    and project_root/. Supports both naming conventions (hyphen and underscore).

    Args:
        context: Compilation context with paths.

    Returns:
        Path to project_context.md or None if not found.

    """
    candidates: list[Path] = []

    # Priority 1: External project_knowledge path (if configured)
    if context.project_knowledge is not None:
        candidates.extend([
            context.project_knowledge / "project-context.md",
            context.project_knowledge / "project_context.md",
        ])

    # Priority 2: Output folder
    candidates.extend([
        context.output_folder / "project-context.md",
        context.output_folder / "project_context.md",
    ])

    # Priority 2b: Parent of output folder (e.g., _bmad-output/ when output_folder is implementation-artifacts/)
    output_parent = context.output_folder.parent
    if output_parent != context.project_root:
        candidates.extend([
            output_parent / "project-context.md",
            output_parent / "project_context.md",
        ])

    # Priority 3: Local docs folder (if not using external project_knowledge)
    if context.project_knowledge is None:
        candidates.extend([
            context.project_root / "docs" / "project-context.md",
            context.project_root / "docs" / "project_context.md",
        ])

    # Priority 4: Project root (legacy)
    candidates.append(context.project_root / "project_context.md")

    for candidate in candidates:
        if candidate.exists():
            return candidate

    logger.debug("project_context.md not found in any location")
    return None


def find_story_context_file(
    context: CompilerContext,
    epic_num: Any,
    story_num: Any,
) -> Path | None:
    """Find story context file in _bmad/bmm/stories/ or .bmad/bmm/stories/.

    Searches for a file matching {epic_num}-{story_num}-*.md within
    the project's BMAD stories directory (tries _bmad/ first, then .bmad/).

    Args:
        context: Compilation context with paths.
        epic_num: Epic number.
        story_num: Story number.

    Returns:
        Path to the story context file or None if not found.

    """
    # Try new structure first (_bmad/), then legacy (.bmad/)
    for bmad_folder in ["_bmad", ".bmad"]:
        bmm_stories_dir = context.project_root / bmad_folder / "bmm" / "stories"
        if not bmm_stories_dir.exists():
            continue

        pattern = f"{epic_num}-{story_num}-*.md"
        matches = sorted(bmm_stories_dir.glob(pattern))

        if matches:
            return matches[0]

    logger.debug(
        "Story context file for %s-%s not found in _bmad/bmm/stories or .bmad/bmm/stories",
        epic_num,
        story_num,
    )
    return None


def find_file_in_output_folder(context: CompilerContext, pattern: str) -> Path | None:
    """Find first file matching pattern in output folder.

    Args:
        context: Compilation context with paths.
        pattern: Glob pattern to match.

    Returns:
        First matching file path or None.

    """
    matches = sorted(context.output_folder.glob(pattern))
    if matches:
        return matches[0]
    return None


def find_file_in_planning_dir(context: CompilerContext, pattern: str) -> Path | None:
    """Find first file matching pattern in planning directories.

    Searches in two locations with priority:
    1. planning_artifacts (specific to current work, e.g., _bmad-output/planning-artifacts/)
    2. project_knowledge (general project docs, e.g., docs/)

    This supports both:
    - Epic-specific planning docs in planning_artifacts
    - Project-wide PRD/architecture in project_knowledge (brownfield)

    Args:
        context: Compilation context with paths.
        pattern: Glob pattern to match.

    Returns:
        First matching file path or None.

    """
    # First check planning_artifacts (more specific)
    planning_dir = get_planning_artifacts_dir(context)
    matches = sorted(planning_dir.glob(pattern))
    if matches:
        return matches[0]

    # Fallback to project_knowledge (general docs like docs/)
    try:
        from bmad_assist.core.paths import get_paths

        project_knowledge = get_paths().project_knowledge
        if project_knowledge != planning_dir:
            matches = sorted(project_knowledge.glob(pattern))
            if matches:
                return matches[0]
    except RuntimeError:
        # Paths not initialized, try context.project_root/docs
        fallback = context.project_root / "docs"
        if fallback.exists() and fallback != planning_dir:
            matches = sorted(fallback.glob(pattern))
            if matches:
                return matches[0]

    return None


def find_epic_file(context: CompilerContext, epic_num: Any) -> Path | None:
    """Find epic file for given epic number.

    Searches in multiple locations with priority:
    1. output_folder/epics/epic-{epic_num}*.md (sharded epics)
    2. output_folder/epics.md (single file)
    3. output_folder/*epic*.md (glob fallback)

    Args:
        context: Compilation context with paths.
        epic_num: Epic number to find (int or str like "testarch").

    Returns:
        Path to epic file or None if not found.

    """
    # Search 1: Sharded epics directory
    epics_dir = context.output_folder / "epics"
    if epics_dir.exists():
        pattern = f"epic-{epic_num}*.md"
        matches = sorted(epics_dir.glob(pattern))
        if matches:
            return matches[0]

    # Search 2: Single epics.md file
    single_epic = context.output_folder / "epics.md"
    if single_epic.exists():
        return single_epic

    # Search 3: Glob fallback - any file with 'epic' in name
    matches = sorted(context.output_folder.glob("*epic*.md"))
    if matches:
        return matches[0]

    return None


def find_previous_stories(
    context: CompilerContext,
    resolved: dict[str, Any],
    max_stories: int = 3,
) -> list[Path]:
    """Find up to N previous story files from same epic.

    Returns stories in chronological order (oldest first) for recency-bias.

    Args:
        context: Compilation context with paths.
        resolved: Resolved variables containing epic_num and story_num.
        max_stories: Maximum number of previous stories to return.

    Returns:
        List of paths to previous story files, oldest first (chronological).

    """
    epic_num = resolved.get("epic_num")
    story_num = resolved.get("story_num")

    # Type-safe conversion of story_num
    try:
        story_num_int = int(story_num) if story_num is not None else 0
    except (TypeError, ValueError):
        logger.debug("Invalid story_num '%s', skipping previous stories", story_num)
        return []

    if story_num_int <= 1:
        return []

    stories_dir = get_stories_dir(context)
    if not stories_dir.exists():
        return []
    found_stories: list[Path] = []

    # Search backwards from current story to find up to max_stories
    for prev_num in range(story_num_int - 1, 0, -1):
        if len(found_stories) >= max_stories:
            break

        pattern = f"{epic_num}-{prev_num}-*.md"
        matches = sorted(stories_dir.glob(pattern))
        if matches:
            found_stories.append(matches[0])
            logger.debug("Found previous story: %s", matches[0])

    # Reverse to get chronological order (oldest first)
    found_stories.reverse()

    if found_stories:
        logger.debug(
            "Found %d previous stories for story %s.%s (chronological order)",
            len(found_stories),
            epic_num,
            story_num,
        )
    else:
        logger.debug("No previous stories found for epic %s", epic_num)

    return found_stories


@contextmanager
def context_snapshot(context: CompilerContext) -> Generator[CompilerContext, None, None]:
    """Preserve and restore context state on exception.

    Creates a snapshot of mutable context fields (resolved_variables,
    discovered_files, file_contents) before execution. On successful
    completion, modifications are kept. On exception, state is restored
    to the snapshot.

    Args:
        context: Compiler context to protect.

    Yields:
        The same context object (for convenience in with statement).

    Example:
        with context_snapshot(context):
            context.resolved_variables["key"] = "value"
            # If exception raised here, state is restored
            # Otherwise, changes persist

    """
    # Snapshot mutable state (shallow copy of dicts)
    original_resolved = dict(context.resolved_variables)
    original_discovered = dict(context.discovered_files)
    original_contents = dict(context.file_contents)

    try:
        yield context
    except Exception:
        # Restore original state on any exception
        context.resolved_variables = original_resolved
        context.discovered_files = original_discovered
        context.file_contents = original_contents
        raise


def apply_post_process(xml: str, context: CompilerContext) -> str:
    """Apply post_process rules from patch file to compiled XML.

    Loads patch from context.patch_path if set, applies post_process
    rules if present, and returns modified XML. Returns original XML
    if no patch, patch not found, or rules empty.

    Args:
        xml: Compiled XML content.
        context: Compiler context with optional patch_path.

    Returns:
        XML content with post_process rules applied, or original if none.

    """
    if context.patch_path is None:
        logger.debug("No patch_path set, skipping post_process")
        return xml

    if not context.patch_path.exists():
        logger.debug("Patch file not found: %s", context.patch_path)
        return xml

    try:
        patch = load_patch(context.patch_path)
        if not patch.post_process:
            logger.debug("No post_process rules in patch: %s", context.patch_path.name)
            return xml

        result = post_process_compiled(xml, patch.post_process)
        logger.debug(
            "Applied %d post_process rules from %s",
            len(patch.post_process),
            context.patch_path.name,
        )
        return result

    except Exception as e:
        logger.warning("Failed to load/apply patch %s: %s", context.patch_path.name, e)
        return xml

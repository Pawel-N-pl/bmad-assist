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
            is_bundled = "bmad_assist/workflows" in str(
                resolved
            ) or "bmad_assist\\workflows" in str(resolved)  # noqa: E501
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
        is_bundled = "bmad_assist/workflows" in str(
            resolved_template
        ) or "bmad_assist\\workflows" in str(resolved_template)  # noqa: E501

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
        candidates.append(paths.project_docs_fallback / "sprint-artifacts" / "sprint-status.yaml")
    except RuntimeError:
        pass

    # Fallback locations
    candidates.extend(
        [
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
    """Find project-context.md (or project_context.md) in known locations.

    Search order (hyphen variant first, then underscore fallback at each level):
    1. project_knowledge/ (planning_artifacts by default)
    2. output_folder (implementation_artifacts)
    3. output_folder parent (_bmad-output/ base)
    4. docs/ fallback (brownfield projects)
    5. project root (legacy)

    Args:
        context: Compilation context with paths.

    Returns:
        Path to project-context.md or None if not found.

    """
    candidates: list[Path] = []

    # Priority 1: project_knowledge path (planning_artifacts by default)
    if context.project_knowledge is not None:
        candidates.extend(
            [
                context.project_knowledge / "project-context.md",
                context.project_knowledge / "project_context.md",
            ]
        )

    # Priority 2: Output folder (implementation_artifacts)
    candidates.extend(
        [
            context.output_folder / "project-context.md",
            context.output_folder / "project_context.md",
        ]
    )

    # Priority 3: Output folder parent (_bmad-output/ base)
    # output_folder is typically _bmad-output/implementation-artifacts/,
    # but project-context.md may live directly in _bmad-output/
    output_parent = context.output_folder.parent
    if output_parent != context.output_folder and output_parent != context.project_root:
        candidates.extend(
            [
                output_parent / "project-context.md",
                output_parent / "project_context.md",
            ]
        )

    # Priority 4: docs/ fallback (brownfield projects)
    docs_fallback = context.project_root / "docs"
    if context.project_knowledge is None or context.project_knowledge.resolve() != docs_fallback.resolve():
        candidates.extend(
            [
                docs_fallback / "project-context.md",
                docs_fallback / "project_context.md",
            ]
        )

    # Priority 5: Project root (legacy)
    candidates.extend(
        [
            context.project_root / "project-context.md",
            context.project_root / "project_context.md",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    logger.debug("project-context.md not found in any location")
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

    # Fallback to project_knowledge and docs/ (brownfield support)
    checked = {planning_dir.resolve()}
    try:
        from bmad_assist.core.paths import get_paths

        paths = get_paths()
        for fallback_dir in [paths.project_knowledge, paths.project_docs_fallback]:
            resolved = fallback_dir.resolve()
            if resolved not in checked and fallback_dir.exists():
                checked.add(resolved)
                matches = sorted(fallback_dir.glob(pattern))
                if matches:
                    return matches[0]
    except RuntimeError:
        # Paths not initialized, try context.project_root/docs
        fallback = context.project_root / "docs"
        if fallback.resolve() not in checked and fallback.exists():
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

    Also inserts project-tree critical instruction if project-tree is present.

    Args:
        xml: Compiled XML content.
        context: Compiler context with optional patch_path.

    Returns:
        XML content with post_process rules applied, or original if none.

    """
    result = xml

    # Apply patch post_process rules if available
    if context.patch_path is not None and context.patch_path.exists():
        try:
            patch = load_patch(context.patch_path)
            if patch.post_process:
                result = post_process_compiled(xml, patch.post_process)
                logger.debug(
                    "Applied %d post_process rules from %s",
                    len(patch.post_process),
                    context.patch_path.name,
                )
        except Exception as e:
            logger.warning("Failed to load/apply patch %s: %s", context.patch_path.name, e)
            result = xml

    # Insert project-tree critical instruction if project-tree is present
    if "<project-tree>" in result:
        try:
            from bmad_assist.compiler.critical_instruction import (
                has_project_tree_instruction,
                insert_project_tree_instruction,
            )

            if not has_project_tree_instruction(result):
                result = insert_project_tree_instruction(result)
                logger.debug("Inserted project-tree critical instruction")
        except Exception as e:
            logger.warning("Failed to insert project-tree critical instruction: %s", e)

    return result


def _prioritize_findings(
    findings: list[dict[str, Any]],
    max_findings: int = 20,
    overflow_tolerance: int = 6,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    """Prioritize and truncate DV findings for synthesis prompt.

    Sort key: (severity_rank, -avg_domain_confidence, file_path, -max_evidence_confidence)

    Truncation rules:
    1. ALL critical findings always included — no limit
    2. Non-critical: fill up to max_findings - len(criticals)
    3. Domain integrity: if adding a finding would exceed budget but same
       (severity, domain) group has <= overflow_tolerance more items, include all
    4. If group exceeds overflow tolerance, stop before it (no partial)

    Args:
        findings: List of finding dicts (with optional file_path, evidence).
        max_findings: Maximum findings to include (criticals exempt).
        overflow_tolerance: Extra items allowed to keep domain group intact.

    Returns:
        Tuple of (prioritized_findings, omitted_count, omitted_by_severity).

    """
    severity_rank = {"critical": 0, "error": 1, "warning": 2, "info": 3}

    # Compute avg domain confidence across all findings per domain
    domain_confidences: dict[str, list[float]] = {}
    for f in findings:
        if not isinstance(f, dict):
            continue
        domain = f.get("domain") or "unknown"
        for e in f.get("evidence", []):
            if isinstance(e, dict) and isinstance(e.get("confidence"), (int, float)):
                domain_confidences.setdefault(domain, []).append(e["confidence"])

    avg_domain_conf: dict[str, float] = {}
    for domain, confs in domain_confidences.items():
        avg_domain_conf[domain] = sum(confs) / len(confs) if confs else 0.0

    def sort_key(f: dict[str, Any]) -> tuple[int, float, str, float]:
        sev = severity_rank.get(f.get("severity", "info"), 3)
        domain = f.get("domain") or "unknown"
        avg_conf = avg_domain_conf.get(domain, 0.0)
        fp = f.get("file_path") or ""
        max_ev_conf = max(
            (
                e.get("confidence", 0.0)
                for e in f.get("evidence", [])
                if isinstance(e, dict)
            ),
            default=0.0,
        )
        return (sev, -avg_conf, fp, -max_ev_conf)

    valid = [f for f in findings if isinstance(f, dict)]
    sorted_findings = sorted(valid, key=sort_key)

    # Split criticals from non-criticals
    criticals = [f for f in sorted_findings if f.get("severity") == "critical"]
    non_criticals = [f for f in sorted_findings if f.get("severity") != "critical"]

    budget = max(0, max_findings - len(criticals))
    included: list[dict[str, Any]] = list(criticals)

    # Process non-criticals with domain integrity
    i = 0
    while i < len(non_criticals) and len(included) - len(criticals) < budget:
        f = non_criticals[i]
        included.append(f)
        i += 1

    # Check if next group fits within overflow tolerance
    while i < len(non_criticals):
        f = non_criticals[i]
        group_sev = f.get("severity")
        group_domain = f.get("domain")

        # Count remaining items in this (severity, domain) group
        group_remaining = 0
        for j in range(i, len(non_criticals)):
            nf = non_criticals[j]
            if nf.get("severity") == group_sev and nf.get("domain") == group_domain:
                group_remaining += 1
            else:
                break

        if group_remaining <= overflow_tolerance:
            # Include entire group
            for j in range(i, i + group_remaining):
                included.append(non_criticals[j])
            i += group_remaining
        else:
            break

    # Skip everything after the break
    omitted = [f for f in valid if f not in included]
    omitted_by_sev: dict[str, int] = {}
    for f in omitted:
        sev = f.get("severity", "unknown")
        omitted_by_sev[sev] = omitted_by_sev.get(sev, 0) + 1

    return included, len(omitted), omitted_by_sev


def _render_flat_findings(
    findings: list[dict[str, Any]],
    dv_findings: dict[str, Any],
) -> str:
    """Render DV findings as flat markdown (original format).

    Used for Schema B (validate-story handler) and any input without file_path.

    Args:
        findings: List of finding dicts.
        dv_findings: Full DV findings dict with verdict, score, domains, methods.

    Returns:
        Markdown-formatted string.

    """
    findings_count = dv_findings.get("findings_count", len(findings))
    critical_count = dv_findings.get(
        "critical_count",
        sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == "critical"),
    )
    error_count = dv_findings.get(
        "error_count",
        sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == "error"),
    )

    lines = [
        "# Deep Verify Analysis Results",
        "",
        f"**Verdict:** {dv_findings.get('verdict', 'UNKNOWN')}",
        f"**Score:** {dv_findings.get('score', 0):.1f}",
        f"**Findings:** {findings_count} "
        f"({critical_count} critical, "
        f"{error_count} error)",
        "",
        "## Domains Detected",
        "",
    ]

    # Support both "domains" (code_review handler) and "domains_detected" (serialize)
    domains = dv_findings.get("domains") or dv_findings.get("domains_detected", [])
    for domain in domains:
        if not isinstance(domain, dict):
            continue
        lines.append(
            f"- **{domain.get('domain', '?')}** (confidence: {domain.get('confidence', 0):.2f})"
        )

    lines.extend(["", "## Methods Executed", ""])
    methods = dv_findings.get("methods") or dv_findings.get("methods_executed", [])
    lines.append(", ".join(str(m) for m in methods) if methods else "None")

    if findings:
        lines.extend(["", "## Findings", ""])

        for finding in findings:
            if not isinstance(finding, dict):
                continue
            severity = finding.get("severity", "unknown").upper()
            lines.append(
                f"### [{severity}] {finding.get('id', '?')}: {finding.get('title', 'Untitled')}"
            )
            lines.append("")
            method = finding.get("method") or finding.get("method_id", "?")
            lines.append(f"**Method:** {method}")
            if finding.get("domain"):
                lines.append(f"**Domain:** {finding.get('domain')}")
            lines.append("")
            lines.append(finding.get("description", "No description"))
            lines.append("")

            evidence = finding.get("evidence", [])
            if evidence:
                lines.append("**Evidence:**")
                for e in evidence:
                    if not isinstance(e, dict):
                        continue
                    quote = e.get("quote", "")
                    line_num = e.get("line_number")
                    if quote:
                        lines.append(f"> {quote}")
                    if line_num is not None:
                        lines.append(f"> *Line {line_num}*")
                    if quote or line_num is not None:
                        lines.append("")
            lines.append("")

    return "\n".join(lines)


def _render_grouped_findings(
    prioritized: list[dict[str, Any]],
    omitted_count: int,
    omitted_by_sev: dict[str, int],
    dv_findings: dict[str, Any],
) -> str:
    """Render prioritized DV findings as grouped markdown.

    Groups findings by severity -> domain -> file_path with line ranges.

    Args:
        prioritized: Prioritized and truncated findings list.
        omitted_count: Number of findings omitted.
        omitted_by_sev: Omitted count breakdown by severity.
        dv_findings: Full DV findings dict with verdict, score, domains, methods.

    Returns:
        Markdown-formatted string with hierarchical grouping.

    """
    total_findings = len(prioritized) + omitted_count
    verdict = dv_findings.get("verdict", "UNKNOWN")
    score = dv_findings.get("score", 0)

    lines = [
        "# Deep Verify Analysis Results",
        "",
        f"**Verdict:** {verdict} | **Score:** {score:.1f}",
        "",
    ]

    if not prioritized:
        lines.append("No findings.")
        return "\n".join(lines)

    lines.append(
        f"## Findings ({len(prioritized)} of {total_findings}"
        " — prioritized by severity, domain confidence)"
    )
    lines.append("")

    # Compute avg domain confidence (same as _prioritize_findings)
    domain_confidences: dict[str, list[float]] = {}
    # Use all findings including omitted for accurate domain avg
    all_findings = dv_findings.get("findings", [])
    for f in all_findings:
        if not isinstance(f, dict):
            continue
        domain = f.get("domain") or "unknown"
        for e in f.get("evidence", []):
            if isinstance(e, dict) and isinstance(e.get("confidence"), (int, float)):
                domain_confidences.setdefault(domain, []).append(e["confidence"])

    avg_domain_conf: dict[str, float] = {}
    for domain, confs in domain_confidences.items():
        avg_domain_conf[domain] = sum(confs) / len(confs) if confs else 0.0

    # Group by (severity, domain, file_path)
    from collections import OrderedDict

    # Build groups preserving sort order
    groups: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = OrderedDict()
    for f in prioritized:
        sev = f.get("severity", "unknown")
        domain = f.get("domain") or "unknown"
        fp = f.get("file_path") or "unknown"
        key = (sev, domain)
        if key not in groups:
            groups[key] = OrderedDict()
        if fp not in groups[key]:
            groups[key][fp] = []
        groups[key][fp].append(f)

    current_sev_domain: tuple[str, str] | None = None

    for (sev, domain), file_groups in groups.items():
        # Emit severity-domain header
        if (sev, domain) != current_sev_domain:
            current_sev_domain = (sev, domain)
            avg_conf = avg_domain_conf.get(domain, 0.0)
            lines.append(f"### {sev.upper()} — {domain} (avg confidence: {avg_conf:.2f})")
            lines.append("")

        for fp, file_findings in file_groups.items():
            # Collect all line numbers for this file group
            all_line_nums: list[int] = []
            for ff in file_findings:
                for e in ff.get("evidence", []):
                    if isinstance(e, dict) and isinstance(e.get("line_number"), int):
                        all_line_nums.append(e["line_number"])

            # Build file header with line range
            if all_line_nums:
                min_l, max_l = min(all_line_nums), max(all_line_nums)
                if min_l == max_l:
                    line_range = f"(L{min_l})"
                else:
                    line_range = f"(L{min_l}-L{max_l})"
                lines.append(f"**{fp}** {line_range}")
            else:
                lines.append(f"**{fp}**")

            # Render each finding as a compact line
            for ff in file_findings:
                # Max evidence confidence for this finding
                max_conf = max(
                    (
                        e.get("confidence", 0.0)
                        for e in ff.get("evidence", [])
                        if isinstance(e, dict)
                    ),
                    default=0.0,
                )
                title = ff.get("title", "Untitled")

                # Individual line numbers
                finding_lines: list[int] = []
                for e in ff.get("evidence", []):
                    if isinstance(e, dict) and isinstance(e.get("line_number"), int):
                        finding_lines.append(e["line_number"])

                if finding_lines:
                    line_refs = ", ".join(f"L{ln}" for ln in finding_lines)
                    lines.append(f"- [{max_conf:.2f}] {title} ({line_refs})")
                else:
                    lines.append(f"- [{max_conf:.2f}] {title}")

            lines.append("")

    # Domains Detected and Methods Executed (after findings)
    lines.append("## Domains Detected")
    lines.append("")
    domains = dv_findings.get("domains") or dv_findings.get("domains_detected", [])
    for domain in domains:
        if not isinstance(domain, dict):
            continue
        lines.append(
            f"- **{domain.get('domain', '?')}** (confidence: {domain.get('confidence', 0):.2f})"
        )

    lines.extend(["", "## Methods Executed", ""])
    methods = dv_findings.get("methods") or dv_findings.get("methods_executed", [])
    lines.append(", ".join(str(m) for m in methods) if methods else "None")

    # Omitted footer
    if omitted_count > 0:
        breakdown = ", ".join(f"{c} {s}" for s, c in sorted(omitted_by_sev.items()))
        lines.extend([
            "",
            "---",
            f"⚠️ {omitted_count} lower-priority findings omitted ({breakdown})",
        ])

    return "\n".join(lines)


def format_dv_findings_for_prompt(dv_findings: dict[str, Any]) -> str:
    """Format Deep Verify findings dict as markdown for LLM prompt.

    Dispatches to grouped rendering (with prioritization) when findings
    contain file_path, or flat rendering for backward compatibility.

    Handles two dict schemas:
    - Code review handler: domains/methods/method keys, pre-computed counts
    - Validate story handler (serialize_validation_result): domains_detected/
      methods_executed/method_id keys, no pre-computed counts

    Args:
        dv_findings: Dict with verdict, score, findings list, domains, methods.

    Returns:
        Markdown-formatted string for inclusion in prompt.

    """
    if not isinstance(dv_findings, dict):
        return "# Deep Verify: No data available"

    findings = dv_findings.get("findings", [])

    has_file_paths = any(
        isinstance(f, dict) and f.get("file_path")
        for f in findings
    )

    if has_file_paths:
        prioritized, omitted, omitted_by_sev = _prioritize_findings(findings)
        return _render_grouped_findings(prioritized, omitted, omitted_by_sev, dv_findings)
    else:
        return _render_flat_findings(findings, dv_findings)

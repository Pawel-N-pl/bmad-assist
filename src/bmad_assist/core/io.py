"""Shared I/O utilities for atomic file operations and text processing.

This module provides reusable utilities for:
- Atomic file writes (temp file + os.replace pattern)
- Markdown code block stripping
- Unified timestamp generation for filenames
- Run-scoped prompt path management (Story 22.2)

These utilities are used by multiple modules (validation, retrospective, etc.)
to ensure consistent behavior across the codebase.
"""

import contextlib
import logging
import os
import threading as _threading
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "atomic_write",
    "strip_code_block",
    "save_prompt",
    "get_prompt_path",
    "get_timestamp",
    "get_run_prompts_dir",
    "init_run_prompts_dir",
    "get_original_cwd",
]

logger = logging.getLogger(__name__)


# =============================================================================
# Original CWD for Subprocess Isolation
# =============================================================================

# Environment variable name for original CWD (set by dashboard subprocess)
BMAD_ORIGINAL_CWD_ENV = "BMAD_ORIGINAL_CWD"


def get_original_cwd() -> Path:
    """Get the original working directory for patch/cache lookup.

    When running as a subprocess (e.g., from dashboard server), the CWD
    may be changed to the project directory. This function returns the
    original CWD from the BMAD_ORIGINAL_CWD environment variable if set,
    otherwise falls back to the current working directory.

    This ensures patch discovery and cache lookup work correctly regardless
    of whether bmad-assist is run directly or as a subprocess.

    Returns:
        Path to the original working directory.

    """
    original_cwd = os.environ.get(BMAD_ORIGINAL_CWD_ENV)
    if original_cwd:
        logger.debug("Using original CWD from env: %s", original_cwd)
        return Path(original_cwd)
    return Path.cwd()


# =============================================================================
# Run-Scoped Prompt Path Management (Story 22.2)
# =============================================================================

# Thread-local storage for run context (per-bmad-assist-run isolation)
_run_context: _threading.local = _threading.local()

# Unknown phases sort last with sequence number 99
UNKNOWN_PHASE_SEQ = 99


def _get_run_dir() -> Path | None:
    """Get the current run-scoped prompts directory.

    Returns None if not initialized (run hasn't started).

    """
    return getattr(_run_context, "prompts_dir", None)


def _get_prompt_counter() -> int:
    """Get the current prompt sequence number for this run.

    Returns 0 if not initialized.

    """
    return getattr(_run_context, "prompt_counter", 0)


def _increment_prompt_counter() -> int:
    """Increment and return the next prompt sequence number.

    Thread-safe counter increment.

    """
    current = _get_prompt_counter()
    _run_context.prompt_counter = current + 1
    return _run_context.prompt_counter


def _get_phase_sequence(phase_name: str) -> int:
    """Get 1-based sequence number for a phase name.

    Maps phase_name (e.g., "create_story" or "create-story") to its position in LoopConfig.story.
    Returns 99 for unknown phases to sort them last.

    Args:
        phase_name: Phase name with underscores or hyphens (e.g., "create_story", "validate-story").

    Returns:
        1-based sequence number (1-N for known phases, 99 for unknown).

    """
    from .config import get_loop_config

    # Normalize: hyphens → underscores (workflow names use hyphens, Phase enum uses underscores)
    normalized = phase_name.replace("-", "_")

    loop_config = get_loop_config()
    try:
        return loop_config.story.index(normalized) + 1
    except ValueError:
        return UNKNOWN_PHASE_SEQ


def _extract_story_number(story_num: int | str) -> str:
    """Extract story number from various formats.

    Handles:
    - "22.6" → "6" (epic.story format)
    - "6" → "6" (plain number)
    - 6 → "6" (integer)
    - "standalone-03" → "03" (module format, extracts after last hyphen)

    Args:
        story_num: Story identifier in various formats.

    Returns:
        Extracted story number as string.

    """
    story_str = str(story_num)

    # Handle epic.story format: "22.6" → "6"
    if "." in story_str:
        return story_str.split(".")[-1]

    # Handle module format: "standalone-03" → "03"
    if "-" in story_str:
        return story_str.split("-")[-1]

    # Plain number or already clean
    return story_str


def get_run_prompts_dir(project_root: Path, run_timestamp: str) -> Path:
    """Get the run-scoped prompts directory path for a given run timestamp.

    The run-scoped directory is: {project_root}/.bmad-assist/prompts/run-{timestamp}/

    Args:
        project_root: Project root directory.
        run_timestamp: Run timestamp string (e.g., "20260114T150355Z").

    Returns:
        Path to the run-scoped prompts directory.

    Example:
        >>> from pathlib import Path
        >>> run_dir = get_run_prompts_dir(Path("/project"), "20260114T150355Z")
        >>> str(run_dir)
        '/project/.bmad-assist/prompts/run-20260114T150355Z'

    """
    return project_root / ".bmad-assist" / "prompts" / f"run-{run_timestamp}"


def init_run_prompts_dir(project_root: Path, run_timestamp: str) -> Path:
    """Initialize run-scoped prompts directory for the current bmad-assist run.

    Creates the directory structure and sets thread-local context for prompt saving.
    Prompt counter is reset to 0 for the new run.

    This should be called once at the start of each bmad-assist run.

    Args:
        project_root: Project root directory.
        run_timestamp: Run timestamp string (e.g., "20260114T150355Z").

    Returns:
        Path to the created run-scoped prompts directory.

    Raises:
        OSError: If directory creation fails.

    Example:
        >>> from pathlib import Path
        >>> run_dir = init_run_prompts_dir(Path("/project"), "20260114T150355Z")
        >>> # Now save_prompt() will use run-scoped paths
        >>> # Prompts will be saved to run_dir/prompt-001.md, prompt-002.md, etc.

    """
    run_dir = get_run_prompts_dir(project_root, run_timestamp)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Set thread-local context
    _run_context.prompts_dir = run_dir
    _run_context.prompt_counter = 0

    logger.info("Initialized run-scoped prompts directory: %s", run_dir)
    return run_dir


def get_timestamp(dt: datetime | None = None) -> str:
    """Generate unified timestamp for filenames.

    Format: YYYYMMDDTHHMMSSZ (e.g., 20250113T154530Z)
    - ISO 8601 basic format (compact, sortable, standard)
    - Explicitly UTC (Z suffix)
    - Filesystem-safe (no special characters except T and Z)
    - 16 characters total
    - 4-digit year for Y10K compatibility

    Args:
        dt: Datetime to format. If None, uses current UTC time.

    Returns:
        Timestamp string in ISO 8601 basic format.

    Examples:
        >>> get_timestamp()  # doctest: +SKIP
        '20250113T154530Z'
        >>> get_timestamp(datetime(2025, 1, 13, 15, 45, 30, tzinfo=UTC))
        '20250113T154530Z'

    """
    if dt is None:
        dt = datetime.now(UTC)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically using temp file + os.replace.

    Uses PID in temp filename to prevent collisions when multiple
    processes write simultaneously.

    Args:
        path: Target file path.
        content: Content to write.

    Raises:
        OSError: If write fails.

    """
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Use PID to prevent temp file collisions in concurrent writes
    temp_path = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp_path, path)
    except OSError:
        # Cleanup temp file if it exists, ignoring errors
        with contextlib.suppress(OSError):
            if temp_path.exists():
                temp_path.unlink()
        raise


def strip_code_block(text: str) -> str:
    r"""Strip markdown code block wrappers if present.

    Handles:
    - ```markdown\n...\n```
    - ```\n...\n```
    - Leading/trailing whitespace

    Args:
        text: Text that may be wrapped in code blocks.

    Returns:
        Text with code block wrappers removed.

    """
    stripped = text.strip()

    # Check for code block start
    if stripped.startswith("```"):
        # Find end of first line (language specifier line)
        first_newline = stripped.find("\n")
        if first_newline != -1:
            # Check for closing ```
            if stripped.endswith("```"):
                # Remove opening line and closing ```
                stripped = stripped[first_newline + 1 : -3].strip()
            else:
                # Only opening, no closing - just remove opening line
                stripped = stripped[first_newline + 1 :].strip()

    return stripped


def get_prompt_path(
    project_root: Path,
    epic_num: int | str,
    story_num: int | str,
    phase_name: str,
) -> Path | None:
    """Find the most recent prompt file for given epic/story/phase.

    Story 22.2: First searches run-scoped directories (most recent run first),
    then falls back to legacy format for backward compatibility.

    Search order:
    1. Run-scoped: .bmad-assist/prompts/run-*/prompt-*.md (reads metadata header)
    2. Legacy: .bmad-assist/prompts/{epic}-{story}-{phase}-*.xml

    Args:
        project_root: Project root directory.
        epic_num: Epic number.
        story_num: Story number.
        phase_name: Phase name (e.g., 'create-story', 'dev-story').

    Returns:
        Path to the most recent prompt file, or None if not found.

    """
    prompts_dir = project_root / ".bmad-assist" / "prompts"
    if not prompts_dir.exists():
        return None

    # First, try run-scoped directories (most recent run first)
    # Use filename-based pattern to narrow search before reading file content
    story_clean = _extract_story_number(story_num)
    phase_normalized = phase_name.replace("-", "_")
    # Pattern: prompt-{epic}-{story_clean}-*-{phase}-*.md
    filename_pattern = f"prompt-{epic_num}-{story_clean}-*-{phase_normalized}-*.md"

    run_dirs = sorted(prompts_dir.glob("run-*/"), reverse=True)
    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue
        # Search for prompt files matching the pattern (most recent first)
        for prompt_file in sorted(run_dir.glob(filename_pattern), reverse=True):
            # Verify with metadata header to confirm exact match
            try:
                with open(prompt_file, encoding="utf-8") as f:
                    header_chunk = f.read(2048)
                if _matches_metadata(header_chunk, epic_num, story_num, phase_name):
                    logger.debug("Found run-scoped prompt: %s", prompt_file)
                    return prompt_file
            except OSError:
                # Skip files that can't be read
                continue

    # Fallback: legacy format
    pattern = f"{epic_num}-{story_num}-{phase_name}-*.xml"
    matches = sorted(prompts_dir.glob(pattern))

    if matches:
        # Return most recent (last in sorted list due to timestamp format)
        logger.debug("Found legacy prompt: %s", matches[-1])
        return matches[-1]

    return None


def _matches_metadata(
    content: str,
    epic_num: int | str,
    story_num: int | str,
    phase_name: str,
) -> bool:
    """Check if prompt content metadata matches the given epic/story/phase.

    Args:
        content: Prompt file content (should start with metadata header).
        epic_num: Epic number to match.
        story_num: Story number to match.
        phase_name: Phase name to match.

    Returns:
        True if all metadata fields match AND metadata marker is present, False otherwise.

    """
    # Require BMAD metadata marker to prevent false positives from comments in content
    if "<!-- BMAD Prompt Run Metadata -->" not in content:
        return False

    # Extract metadata lines from content (stop at first non-metadata content)
    lines = content.split("\n")
    metadata = {}
    found_marker = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Allow XML declaration before metadata block
        if line.startswith("<?xml") and line.endswith("?>"):
            continue
        if not line.startswith("<!--"):
            # Stop parsing once we hit non-comment content after finding marker
            if found_marker:
                break
            continue
        if line.endswith("-->"):
            # Check for metadata marker
            if "BMAD Prompt Run Metadata" in line:
                found_marker = True
                continue
            # Extract key-value from comment: <!-- Epic: 22 --> -> ("Epic", "22")
            inner = line[4:-3].strip()  # Remove <!-- -->
            if ":" in inner:
                key, value = inner.split(":", 1)
                metadata[key.strip().lower()] = value.strip()

    # Check if all fields match
    # Story metadata may be stored as "epic.story" format (e.g., "1.1") or story-only (e.g., "1")
    # Accept both formats for backward compatibility with different workflow callers
    story_meta = metadata.get("story")
    story_matches = (
        story_meta == f"{epic_num}.{story_num}"  # Full format: "2.2"
        or story_meta == str(story_num)  # Story-only format: "2"
    )
    return (
        metadata.get("epic") == str(epic_num)
        and story_matches
        and metadata.get("phase") == phase_name.replace("_", "-")
    )


def save_prompt(
    project_root: Path,
    epic_num: int | str,
    story_num: int | str,
    phase_name: str,
    content: str,
) -> Path:
    """Save workflow prompt to project-local prompts directory.

    Prompts are saved to run-scoped paths with descriptive naming:
    .bmad-assist/prompts/run-{run_ts}/prompt-{epic}-{story}-{phase_seq}-{phase}-{ts}.md

    If run directory is not initialized, it will be auto-initialized.

    Args:
        project_root: Project root directory.
        epic_num: Epic number.
        story_num: Story number.
        phase_name: Phase name (e.g., 'create_story', 'dev_story').
        content: Prompt content to save.

    Returns:
        Path where the prompt was saved.

    Raises:
        OSError: If write fails.

    Examples:
        >>> save_prompt(Path("/project"), 22, 6, "create_story", prompt_text)  # doctest: +SKIP
        Path('.../run-.../prompt-22-6-01-create_story-20260115T050415Z.md')

    """
    # Get or auto-initialize run-scoped directory
    run_dir = _get_run_dir()
    if run_dir is None:
        # Auto-initialize if not set (no legacy format anymore)
        run_timestamp = get_timestamp()
        run_dir = init_run_prompts_dir(project_root, run_timestamp)

    # Run-scoped mode: descriptive naming with phase sequence
    # Format: prompt-{epic}-{story}-{phase_seq:02d}-{phase_name}-{timestamp}.md
    # NOTE: Counter is tracked internally but phase_seq provides file ordering
    _increment_prompt_counter()  # Track for metrics, not used in filename

    # Normalize phase_name: hyphens → underscores for consistent naming
    phase_normalized = phase_name.replace("-", "_")
    phase_seq = _get_phase_sequence(phase_normalized)
    story_clean = _extract_story_number(story_num)
    timestamp = get_timestamp()
    filename = f"prompt-{epic_num}-{story_clean}-{phase_seq:02d}-{phase_normalized}-{timestamp}.md"
    prompt_path = run_dir / filename

    # Add metadata header to prompt content
    # CRITICAL: Insert metadata AFTER XML declaration if present
    metadata_header = _build_prompt_metadata(epic_num, story_num, phase_normalized)

    # Check if content starts with XML declaration
    if content.startswith("<?xml"):
        # Find end of XML declaration
        decl_end = content.find("?>")
        if decl_end != -1:
            # Insert metadata after XML declaration
            insertion_point = decl_end + 2
            content_with_metadata = (
                content[:insertion_point] + "\n" + metadata_header + content[insertion_point:]
            )
        else:
            # Malformed XML declaration, prepend metadata
            content_with_metadata = f"{metadata_header}\n\n{content}"
    else:
        # No XML declaration, prepend metadata
        content_with_metadata = f"{metadata_header}\n\n{content}"

    atomic_write(prompt_path, content_with_metadata)
    logger.info("Saved prompt: %s", prompt_path)

    return prompt_path


def _build_prompt_metadata(
    epic_num: int | str,
    story_num: int | str,
    phase_name: str,
) -> str:
    """Build metadata header for run-scoped prompt files.

    The metadata helps identify which epic/story/phase a prompt belongs to
    without parsing the prompt content.

    Args:
        epic_num: Epic number.
        story_num: Story number.
        phase_name: Phase name (with underscores, e.g., "create_story").

    Returns:
        Multiline string with HTML comment metadata.

    """
    timestamp = get_timestamp()
    # Use hyphens in phase name for consistency with file naming conventions
    phase_normalized = phase_name.replace("_", "-")
    return (
        "<!-- BMAD Prompt Run Metadata -->\n"
        f"<!-- Epic: {epic_num} -->\n"
        f"<!-- Story: {story_num} -->\n"
        f"<!-- Phase: {phase_normalized} -->\n"
        f"<!-- Timestamp: {timestamp} -->"
    )

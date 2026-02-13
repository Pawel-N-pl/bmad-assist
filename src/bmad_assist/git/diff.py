"""Git diff utilities with intelligent filtering and validation.

Addresses the 92% false positive rate in code reviews by:
- Filtering out cache/metadata files from diffs
- Detecting proper merge-base for accurate comparisons
- Validating diff quality before passing to reviewers
"""

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Default timeout for git commands
_GIT_TIMEOUT = 30

# Patterns for files that should NEVER appear in code review diffs
# These cause false positives when reviewers see cache/metadata content
DEFAULT_EXCLUDE_PATTERNS: tuple[str, ...] = (
    # BMAD generated artifacts (run tracking, benchmarks, reports, state)
    ".bmad-assist/*",
    "_bmad-output/*",
    # Cache and metadata
    "*.cache",
    "*.meta.yaml",
    "*.meta.yml",
    ".bmad/cache/*",
    "__pycache__/*",
    "*.pyc",
    ".pytest_cache/*",
    ".mypy_cache/*",
    ".ruff_cache/*",
    # Node/JS
    "node_modules/*",
    "*.lock",
    "package-lock.json",
    # SvelteKit generated
    ".svelte-kit/*",
    # Build artifacts
    "dist/*",
    "build/*",
    "*.egg-info/*",
    # IDE/Editor
    ".idea/*",
    ".vscode/*",
    "*.swp",
    "*.swo",
    # Documentation (handled separately)
    "docs/*.md",
    "*.md",
    # Compiled templates
    "*.tpl.xml",
)

# Patterns for files that SHOULD appear in code review diffs
DEFAULT_INCLUDE_PATTERNS: tuple[str, ...] = (
    "src/*",
    "tests/*",
    "lib/*",
    "app/*",
    "*.py",
    "*.ts",
    "*.tsx",
    "*.js",
    "*.jsx",
    "*.css",
    "*.scss",
    "*.html",
    "*.json",
    "*.yaml",
    "*.yml",
    "*.toml",
)


@dataclass
class DiffValidationResult:
    """Result of diff quality validation."""

    is_valid: bool
    total_files: int
    source_files: int
    garbage_files: int
    garbage_ratio: float
    issues: list[str]


class DiffQualityError(Exception):
    """Raised when diff quality is too low to be useful."""

    def __init__(self, message: str, validation: DiffValidationResult) -> None:
        """Initialize with message and validation result."""
        super().__init__(message)
        self.validation = validation


def get_merge_base(project_root: Path, target_branch: str | None = None) -> str | None:
    """Find proper base commit for diff comparison.

    Handles merge commits correctly by finding the appropriate base:
    - For merge commits: uses first parent (main branch line)
    - For regular commits: finds merge-base with main/master

    Args:
        project_root: Path to git repository root.
        target_branch: Branch to compare against (auto-detects main/master if None).

    Returns:
        Commit SHA for diff base, or None on error.

    """
    try:
        # Check if HEAD is a merge commit (has multiple parents)
        parents_result = subprocess.run(
            ["git", "rev-parse", "HEAD^@"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if parents_result.returncode == 0:
            parents = parents_result.stdout.strip().split("\n")
            parents = [p for p in parents if p]  # Filter empty

            if len(parents) > 1:
                # Merge commit - use first parent (the branch we merged into)
                logger.debug("HEAD is merge commit, using first parent: %s", parents[0][:8])
                return parents[0]

        # Regular commit - find merge-base with main branch
        main_branch = target_branch or _detect_main_branch(project_root)
        if not main_branch:
            # Fallback to HEAD~1 if no main branch found
            logger.debug("No main branch detected, using HEAD~1")
            return "HEAD~1"

        merge_base_result = subprocess.run(
            ["git", "merge-base", main_branch, "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if merge_base_result.returncode == 0:
            base = merge_base_result.stdout.strip()
            logger.debug("Merge base with %s: %s", main_branch, base[:8])
            return base

        # Fallback
        logger.debug("Could not find merge-base, using HEAD~1")
        return "HEAD~1"

    except subprocess.TimeoutExpired:
        logger.warning("Timeout finding merge base")
        return None
    except FileNotFoundError:
        logger.warning("Git not found")
        return None


def _detect_main_branch(project_root: Path) -> str | None:
    """Detect the main branch name (main, master, or other).

    Args:
        project_root: Path to git repository.

    Returns:
        Branch name or None if not detected.

    """
    # Try common main branch names
    for branch in ("main", "master", "develop"):
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return branch

    # Try to get from remote
    result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode == 0:
        # Output like: refs/remotes/origin/main
        ref = result.stdout.strip()
        if ref:
            return ref.split("/")[-1]

    return None


def capture_filtered_diff(
    project_root: Path,
    base: str | None = None,
    include_patterns: tuple[str, ...] | None = None,
    exclude_patterns: tuple[str, ...] | None = None,
    max_lines: int = 2000,
) -> str:
    """Capture git diff with intelligent filtering and prioritization.

    Diff sections are sorted by file priority (source > test > config)
    so that real code appears first when truncated by max_lines.

    Args:
        project_root: Path to git repository root.
        base: Base commit for diff (auto-detects if None).
        include_patterns: Glob patterns for files to include.
        exclude_patterns: Glob patterns for files to exclude.
        max_lines: Maximum total lines in output (truncated with marker).

    Returns:
        Filtered diff content wrapped in markers, or empty string on error.

    """
    exclude_patterns = exclude_patterns or DEFAULT_EXCLUDE_PATTERNS

    # Auto-detect merge base if not provided
    if base is None:
        base = get_merge_base(project_root)
        if base is None:
            base = "HEAD~1"

    try:
        # Build pathspec for exclusions
        # Git pathspec magic: :(exclude)pattern excludes matching files
        pathspec_excludes = [f":(exclude){p}" for p in exclude_patterns]

        # Capture stat summary separately (lightweight, always included)
        stat_cmd = [
            "git",
            "diff",
            "--no-ext-diff",
            "--stat",
            base,
            "HEAD",
            "--",
            *pathspec_excludes,
        ]
        stat_result = subprocess.run(
            stat_cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            errors="replace",
        )
        stat_section = stat_result.stdout if stat_result.returncode == 0 else ""

        # Capture patch separately (will be prioritized)
        patch_cmd = [
            "git",
            "diff",
            "--no-ext-diff",
            "-p",
            base,
            "HEAD",
            "--",
            *pathspec_excludes,
        ]
        result = subprocess.run(
            patch_cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            errors="replace",
        )

        if result.returncode != 0:
            stderr_msg = result.stderr[:200] if result.stderr else "unknown"
            logger.warning("git diff failed: %s", stderr_msg)
            return ""

        patch_content = result.stdout
        if not patch_content.strip() and not stat_section.strip():
            return ""

        # Prioritize diff sections: source code first, tests second, config last
        prioritized_patch = _prioritize_diff_sections(patch_content)

        # Assemble: stat summary + prioritized patch
        diff_content = stat_section.rstrip("\n") + "\n\n" + prioritized_patch

        # Truncate if needed
        lines = diff_content.split("\n")
        if len(lines) > max_lines:
            lines = lines[: max_lines - 1]
            lines.append(f"[... TRUNCATED diff after line {max_lines - 1} ...]")
            diff_content = "\n".join(lines)

        # Wrap in markers
        return f"<!-- GIT_DIFF_START -->\n{diff_content}\n<!-- GIT_DIFF_END -->"

    except subprocess.TimeoutExpired:
        logger.error("git diff timed out after %ds", _GIT_TIMEOUT)
        return ""
    except FileNotFoundError:
        logger.warning("git command not found")
        return ""
    except OSError as e:
        logger.warning("git command failed: %s", e)
        return ""


# File extensions considered source code (highest priority in diff)
_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".swift",
        ".c",
        ".cpp",
        ".cc",
        ".h",
        ".hpp",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".svelte",
        ".vue",
        ".css",
        ".scss",
        ".html",
        ".sh",
        ".bash",
    }
)

# File extensions considered config (lowest priority in diff)
_CONFIG_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
    }
)

# Path segments indicating test files (medium priority)
_TEST_INDICATORS: tuple[str, ...] = (
    "tests/",
    "test/",
    "__tests__/",
    "spec/",
    "test_",
    "_test.",
    ".test.",
    ".spec.",
)

# Diff section header pattern
_DIFF_SECTION_PATTERN = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)


def _classify_file_priority(filepath: str) -> int:
    """Classify file for diff ordering. Lower number = higher priority.

    Priority levels:
        0 = Source code (src/, lib/, app/, or source extension)
        1 = Test files
        2 = Config files
        3 = Everything else

    """
    from pathlib import PurePosixPath

    ext = PurePosixPath(filepath).suffix.lower()

    # Test files (check before source — test files may have source extensions)
    if any(indicator in filepath.lower() for indicator in _TEST_INDICATORS):
        return 1

    # Source code
    if ext in _SOURCE_EXTENSIONS:
        return 0

    # Config files
    if ext in _CONFIG_EXTENSIONS:
        return 2

    return 3


def _prioritize_diff_sections(patch_content: str) -> str:
    """Reorder diff sections so source code appears first.

    Splits the unified diff into per-file sections at 'diff --git' boundaries,
    scores each by file type, and reassembles sorted by priority (source first).

    Args:
        patch_content: Raw git diff -p output.

    Returns:
        Reordered patch content.

    """
    if not patch_content.strip():
        return patch_content

    # Split into per-file sections at "diff --git" boundaries
    sections: list[tuple[str, str]] = []  # (filepath, section_text)
    current_path = ""
    current_lines: list[str] = []

    for line in patch_content.split("\n"):
        header_match = _DIFF_SECTION_PATTERN.match(line)
        if header_match:
            # Save previous section
            if current_lines:
                sections.append((current_path, "\n".join(current_lines)))
            current_path = header_match.group(2)  # b-side path
            current_lines = [line]
        else:
            current_lines.append(line)

    # Save last section
    if current_lines:
        sections.append((current_path, "\n".join(current_lines)))

    if len(sections) <= 1:
        return patch_content

    # Sort by priority (source=0, test=1, config=2, other=3), then by path
    sections.sort(key=lambda s: (_classify_file_priority(s[0]), s[0]))

    return "\n".join(text for _, text in sections)


def extract_files_from_diff(diff_content: str) -> list[str]:
    """Extract file paths from diff content.

    Parses both stat output and diff headers to find all files.

    Args:
        diff_content: Raw git diff output.

    Returns:
        List of file paths mentioned in the diff.

    """
    files: set[str] = set()

    # Pattern for diff --stat line: " src/file.py | 42 +++"
    # Also matches renames: " old.py => new.py | 5 +++--" or " {old => new}/file.py | 5 ++"
    stat_pattern = re.compile(r"^\s*(.+?)\s*\|\s*\d+")

    # Pattern for diff header: "diff --git a/src/file.py b/src/file.py"
    diff_header_pattern = re.compile(r"^diff --git a/(.+?) b/(.+?)$")

    # Pattern for rename: "old.py => new.py" or "{old => new}/file.py"
    rename_pattern = re.compile(r"^(.+?)\s*=>\s*(.+?)$")
    brace_rename_pattern = re.compile(r"\{(.+?)\s*=>\s*(.+?)\}")

    for line in diff_content.split("\n"):
        # Check stat line
        stat_match = stat_pattern.match(line)
        if stat_match:
            filepath = stat_match.group(1).strip()
            # Handle renames in stat: "old.py => new.py"
            rename_match = rename_pattern.match(filepath)
            if rename_match:
                files.add(rename_match.group(2).strip())  # New name
                continue
            # Handle brace renames: "{old => new}/file.py"
            brace_match = brace_rename_pattern.search(filepath)
            if brace_match:
                # Replace {old => new} with new
                new_path = filepath.replace(brace_match.group(0), brace_match.group(2).strip())
                files.add(new_path)
                continue
            files.add(filepath)
            continue

        # Check diff header
        diff_match = diff_header_pattern.match(line)
        if diff_match:
            files.add(diff_match.group(2))  # Use 'b' side (new path)

    return sorted(files)


def validate_diff_quality(
    diff_content: str,
    max_garbage_ratio: float = 0.3,
) -> DiffValidationResult:
    """Validate that diff contains mostly source files, not garbage.

    This is the P1 sanity gate that prevents 92% false positive reviews.

    Args:
        diff_content: Raw git diff output.
        max_garbage_ratio: Maximum allowed ratio of garbage files (default 30%).

    Returns:
        DiffValidationResult with validation details.

    """
    files = extract_files_from_diff(diff_content)

    if not files:
        return DiffValidationResult(
            is_valid=True,  # Empty diff is valid (nothing to review)
            total_files=0,
            source_files=0,
            garbage_files=0,
            garbage_ratio=0.0,
            issues=[],
        )

    # Classify files
    garbage_patterns = [
        r"^\.bmad-assist/",
        r"^_bmad-output/",
        r"\.cache$",
        r"\.meta\.ya?ml$",
        r"\.tpl\.xml$",
        r"__pycache__",
        r"node_modules/",
        r"\.pyc$",
        r"\.egg-info/",
        r"\.pytest_cache/",
        r"\.mypy_cache/",
        r"\.ruff_cache/",
        r"\.bmad/cache/",
        r"package-lock\.json$",
        r"\.lock$",
    ]

    garbage_files: list[str] = []
    source_files: list[str] = []

    for f in files:
        is_garbage = any(re.search(p, f) for p in garbage_patterns)
        if is_garbage:
            garbage_files.append(f)
        else:
            source_files.append(f)

    total = len(files)
    garbage_ratio = len(garbage_files) / total if total > 0 else 0.0

    issues: list[str] = []
    is_valid = True

    if garbage_ratio > max_garbage_ratio:
        is_valid = False
        issues.append(
            f"Garbage ratio {garbage_ratio:.0%} exceeds threshold {max_garbage_ratio:.0%}"
        )
        issues.append(f"Garbage files: {garbage_files[:5]}")  # Show first 5

    if total > 0 and len(source_files) == 0:
        is_valid = False
        issues.append("No source files in diff - only garbage/metadata")

    return DiffValidationResult(
        is_valid=is_valid,
        total_files=total,
        source_files=len(source_files),
        garbage_files=len(garbage_files),
        garbage_ratio=garbage_ratio,
        issues=issues,
    )


def get_validated_diff(
    project_root: Path,
    base: str | None = None,
    max_garbage_ratio: float = 0.3,
    raise_on_invalid: bool = False,
) -> tuple[str, DiffValidationResult]:
    """Capture diff with filtering and validation.

    Combines P0 (filtering) and P1 (validation) in one call.

    Args:
        project_root: Path to git repository root.
        base: Base commit for diff (auto-detects if None).
        max_garbage_ratio: Maximum garbage file ratio before warning/error.
        raise_on_invalid: If True, raise DiffQualityError on validation failure.

    Returns:
        Tuple of (filtered diff content, validation result).

    Raises:
        DiffQualityError: If raise_on_invalid=True and validation fails.

    """
    # Capture filtered diff
    diff_content = capture_filtered_diff(project_root, base=base)

    # Validate quality
    validation = validate_diff_quality(diff_content, max_garbage_ratio)

    if not validation.is_valid:
        logger.warning(
            "Diff quality issues detected: %s (garbage: %d/%d files)",
            validation.issues,
            validation.garbage_files,
            validation.total_files,
        )

        if raise_on_invalid:
            raise DiffQualityError(
                f"Diff contains too much garbage: {validation.garbage_ratio:.0%}",
                validation,
            )

    return diff_content, validation

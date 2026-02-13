"""Gitignore pattern matching for project tree generation."""

import logging
from pathlib import Path

from pathspec import GitIgnoreSpec as PathspecGitIgnore

logger = logging.getLogger(__name__)

# Default exclusions when no .gitignore is found
# Include both directory patterns (with trailing slash) and full names
DEFAULT_EXCLUSIONS = [
    "node_modules",
    "node_modules/",
    ".venv",
    ".venv/",
    "__pycache__",
    "__pycache__/",
    ".git",
    ".git/",
    ".tox",
    ".tox/",
    ".pytest_cache",
    ".pytest_cache/",
    ".mypy_cache",
    ".mypy_cache/",
    ".ruff_cache",
    ".ruff_cache/",
    "*.pyc",
    "*.pyo",
    ".coverage",
    "htmlcov",
    "htmlcov/",
]


class GitignoreSpec:
    """Compiled gitignore patterns for a specific directory."""

    spec: PathspecGitIgnore | None
    dir_path: Path
    patterns: list[str]

    def __init__(self, patterns: list[str], dir_path: Path) -> None:
        """Initialize with patterns and directory path.

        Args:
            patterns: List of gitignore patterns
            dir_path: Path to the directory these patterns apply to

        """
        self.dir_path = dir_path
        self.patterns = patterns
        # Compile patterns into a GitIgnoreSpec object
        if patterns:
            self.spec = PathspecGitIgnore.from_lines(patterns)
        else:
            self.spec = None

    def match(self, file_path: Path) -> bool | None:
        """Check if a file path matches any pattern in this spec.

        Args:
            file_path: Path to check (relative to project root)

        Returns:
            True if matches an ignore pattern, False if matches a negation,
            None if no match

        """
        if self.spec is None:
            return None
        # Use match_file to check if path matches
        # pathspec expects forward slashes
        path_str = file_path.as_posix()
        return self.spec.match_file(path_str)


class GitignoreParser:
    """Parser for hierarchical .gitignore files.

    Builds a stack of gitignore rules as directories are traversed,
    allowing child directories to inherit and override parent patterns.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the parser.

        Args:
            project_root: Root directory of the project

        """
        self.project_root = project_root.resolve()
        self._spec_cache: dict[Path, GitignoreSpec | None] = {}
        self._default_spec = GitignoreSpec(DEFAULT_EXCLUSIONS, project_root)

    def load_gitignore_for_dir(self, dir_path: Path) -> GitignoreSpec | None:
        """Load .gitignore for a specific directory.

        Args:
            dir_path: Directory path to load .gitignore for

        Returns:
            GitignoreSpec if .gitignore exists, None otherwise

        """
        resolved_path = dir_path.resolve()

        # Check cache first
        if resolved_path in self._spec_cache:
            return self._spec_cache[resolved_path]

        gitignore_path = resolved_path / ".gitignore"

        if gitignore_path.exists():
            try:
                content = gitignore_path.read_text(encoding="utf-8")
                patterns = [
                    line.strip()
                    for line in content.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                spec = GitignoreSpec(patterns, resolved_path)
                self._spec_cache[resolved_path] = spec
                return spec
            except OSError as e:
                logger.warning(f"Failed to read .gitignore at {gitignore_path}: {e}")
                self._spec_cache[resolved_path] = None
                return None

        self._spec_cache[resolved_path] = None
        return None

    def _collect_specs_for_path(self, rel_path: Path) -> list[GitignoreSpec]:
        """Collect all applicable gitignore specs for a path.

        Collects specs from root to the parent directory of the path,
        in order of increasing priority.

        Args:
            rel_path: Path relative to project root

        Returns:
            List of GitignoreSpec objects in priority order

        """
        specs: list[GitignoreSpec] = []

        # Add default exclusions first (lowest priority)
        specs.append(self._default_spec)

        # Walk from root to parent directory, collecting gitignore specs
        current = self.project_root
        parts = list(rel_path.parent.parts) if rel_path.parent != Path(".") else []

        # Add root .gitignore if exists
        root_spec = self.load_gitignore_for_dir(current)
        if root_spec:
            specs.append(root_spec)

        # Add intermediate directory .gitignore files
        for part in parts:
            current = current / part
            spec = self.load_gitignore_for_dir(current)
            if spec:
                specs.append(spec)

        return specs

    def is_ignored(self, path: Path) -> bool:
        """Check if a path is ignored using stacked rules.

        Patterns from parent directories apply to children.
        Child .gitignore can override parent patterns using negation (!pattern).

        Args:
            path: Path to check (relative to project root or absolute)

        Returns:
            True if path should be ignored, False otherwise

        """
        # Resolve path and ensure it's relative to project root
        resolved_path = path.resolve()
        try:
            rel_path = resolved_path.relative_to(self.project_root)
        except ValueError:
            # Path is outside project root - treat as ignored for security
            logger.warning(f"Path {path} is outside project root, treating as ignored")
            return True

        # Collect all applicable specs
        specs = self._collect_specs_for_path(rel_path)

        # Check if path itself is a directory with its own .gitignore
        if resolved_path.is_dir():
            dir_spec = self.load_gitignore_for_dir(resolved_path)
            if dir_spec:
                specs.append(dir_spec)

        # Combine all patterns into a single spec and check
        # This properly handles negation patterns across all levels
        all_patterns: list[str] = []
        for spec in specs:
            if spec.patterns:
                all_patterns.extend(spec.patterns)

        if not all_patterns:
            return False

        # Create combined spec and check
        combined_spec = PathspecGitIgnore.from_lines(all_patterns)
        path_str = rel_path.as_posix()

        # Check if path is a directory and append trailing slash for matching
        # This ensures patterns like "build/" match the directory itself
        is_dir = resolved_path.is_dir()
        if is_dir and combined_spec.match_file(path_str + "/"):
            # Try matching with trailing slash first (for directory patterns)
            return True

        return combined_spec.match_file(path_str)

    def get_patterns_for_dir(self, dir_path: Path) -> list[str]:
        """Get all active patterns for a directory (for debugging).

        Args:
            dir_path: Directory to get patterns for

        Returns:
            List of all active patterns

        """
        resolved_path = dir_path.resolve()

        patterns: list[str] = []

        # Add default exclusions
        patterns.extend([f"[DEFAULT] {p}" for p in DEFAULT_EXCLUSIONS])

        # Walk from root to this directory
        current = self.project_root
        rel_path = resolved_path.relative_to(self.project_root)
        parts = list(rel_path.parts) if str(rel_path) != "." else []

        # Root .gitignore
        root_spec = self.load_gitignore_for_dir(current)
        if root_spec and root_spec.patterns:
            patterns.extend([f"[ROOT] {p}" for p in root_spec.patterns])

        # Intermediate directories
        for part in parts:
            current = current / part
            spec = self.load_gitignore_for_dir(current)
            if spec and spec.patterns:
                patterns.extend([f"[{current.name}] {p}" for p in spec.patterns])

        return patterns

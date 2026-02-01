"""Centralized path resolution for all bmad-assist artifacts.

Single source of truth for all project paths. All modules MUST import
paths from here instead of constructing them locally.

Usage:
    from bmad_assist.core.paths import get_paths, init_paths

    # At startup (once, in cli.py):
    paths = init_paths(project_root, config)

    # Anywhere else:
    paths = get_paths()
    validation_dir = paths.validations_dir
    benchmark_dir = paths.benchmarks_dir
"""

import logging
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)


class ProjectPaths:
    """Resolves all project paths from configuration.

    This class provides a centralized way to access all project-related paths.
    Paths are lazily resolved using cached_property for efficiency.

    The path resolution supports {project-root} placeholder which is replaced
    with the actual project root path.

    Attributes:
        project_root: The root directory of the project.

    """

    # Default path templates (can be overridden via config)
    DEFAULT_OUTPUT_FOLDER = "{project-root}/_bmad-output"
    DEFAULT_PLANNING_ARTIFACTS = "{project-root}/_bmad-output/planning-artifacts"
    DEFAULT_IMPLEMENTATION_ARTIFACTS = "{project-root}/_bmad-output/implementation-artifacts"
    DEFAULT_PROJECT_KNOWLEDGE = "{project-root}/docs"

    def __init__(self, project_root: Path, config: dict[str, Any] | None = None):
        """Initialize ProjectPaths with project root and optional config.

        Args:
            project_root: The root directory of the project.
            config: Optional configuration dictionary with path overrides.
                Supported keys:
                - output_folder: Base output folder
                - planning_artifacts: Planning phase artifacts
                - implementation_artifacts: Implementation phase artifacts
                - project_knowledge: Project documentation folder

        """
        self.project_root = project_root.resolve()
        self._config = config or {}

    def _resolve_path(self, template: str) -> Path:
        """Resolve path template to absolute path.

        Handles:
        - {project-root}/relative/path -> resolved relative to project
        - /absolute/external/path -> used as-is (external location)
        - ../relative/path -> resolved relative to project_root
        - empty string -> returns project_root (fallback)

        Args:
            template: Path template string.

        Returns:
            Resolved absolute Path.

        """
        # Handle empty/whitespace template - fallback to project root
        if not template or not template.strip():
            logger.warning("Empty path template, falling back to project_root")
            return self.project_root

        # If template is already absolute (no placeholder), use as-is
        if not template.startswith("{project-root}") and Path(template).is_absolute():
            resolved = Path(template)
            logger.debug("External absolute path detected: %s", resolved)
            return resolved.resolve()

        # Handle relative paths without {project-root} placeholder (e.g., "../shared-docs")
        if not template.startswith("{project-root}"):
            # Treat as relative to project_root
            resolved = self.project_root / template
            logger.debug("Relative path resolved to: %s", resolved)
            return resolved.resolve()

        # Standard case: resolve {project-root} placeholder
        resolved_str = template.replace("{project-root}", str(self.project_root))
        return Path(resolved_str).resolve()

    def _get_config_path(self, key: str, default: str) -> Path:
        """Get path from config with fallback to default.

        Args:
            key: Configuration key to look up.
            default: Default template if key not in config.

        Returns:
            Resolved Path object.

        """
        template = self._config.get(key, default)
        return self._resolve_path(template)

    # =========================================================================
    # Base Output Folders
    # =========================================================================

    @cached_property
    def output_folder(self) -> Path:
        """Base output folder for all generated artifacts."""
        return self._get_config_path("output_folder", self.DEFAULT_OUTPUT_FOLDER)

    @cached_property
    def planning_artifacts(self) -> Path:
        """Root folder for planning phase artifacts (PRD, architecture, epics, stories)."""
        return self._get_config_path("planning_artifacts", self.DEFAULT_PLANNING_ARTIFACTS)

    @cached_property
    def implementation_artifacts(self) -> Path:
        """Root folder for implementation phase artifacts (validations, reviews, benchmarks)."""
        return self._get_config_path(
            "implementation_artifacts", self.DEFAULT_IMPLEMENTATION_ARTIFACTS
        )

    @cached_property
    def project_knowledge(self) -> Path:
        """Project knowledge/documentation folder (docs/)."""
        return self._get_config_path("project_knowledge", self.DEFAULT_PROJECT_KNOWLEDGE)

    # =========================================================================
    # Planning Artifacts (pre-implementation)
    # =========================================================================

    @cached_property
    def epics_dir(self) -> Path:
        """Directory for epic definition files.

        Resolution order:
        1. Config override: epics (e.g., "docs/development_process/epics")
        2. Standard sharded: project_knowledge/epics/ (e.g., docs/epics/)
        3. Auto-discovery: search project_knowledge (max 2 levels) for "epics" dir
        4. Fallback: planning_artifacts/epics/ (generated)
        """
        # 1. Check for explicit config override
        if "epics" in self._config:
            return self._resolve_path(self._config["epics"])

        # 2. Prefer sharded epics in project_knowledge (docs/epics/)
        sharded_dir = self.project_knowledge / "epics"
        if sharded_dir.exists() and sharded_dir.is_dir():
            return sharded_dir

        # 3. Auto-discovery: search max 2 levels deep for "epics" directory
        found = self._find_epics_dir(self.project_knowledge, max_depth=2)
        if found:
            # Warn about non-standard location
            relative = found.relative_to(self.project_knowledge)
            logger.warning(
                "Epics directory found at non-standard location: %s "
                "(expected: epics/). Consider moving or setting bmad_paths.epics in config.",
                relative,
            )
            return found

        # 4. Fallback to planning_artifacts (generated epics)
        return self.planning_artifacts / "epics"

    def _find_epics_dir(self, base: Path, max_depth: int) -> Path | None:
        """Find 'epics' directory within base, excluding archive dirs.

        Args:
            base: Directory to search in.
            max_depth: Maximum depth to search (1 = immediate children only).

        Returns:
            Path to closest epics directory, or None if not found.

        """
        if not base.exists() or not base.is_dir():
            return None

        candidates: list[tuple[int, Path]] = []  # (depth, path)

        for depth in range(1, max_depth + 1):
            # Build glob pattern for this depth: */epics, */*/epics, etc.
            pattern = "/".join(["*"] * depth) + "/epics"
            for match in base.glob(pattern):
                if not match.is_dir():
                    continue
                # Skip archive directories
                if any(part in ("archive", "archived") for part in match.parts):
                    continue
                candidates.append((depth, match))

        if not candidates:
            return None

        # Return closest (smallest depth)
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    @cached_property
    def stories_dir(self) -> Path:
        """Directory for story files.

        Stories are stored directly in implementation_artifacts/ to match
        BMAD's create-story and dev-story workflows.
        """
        return self.implementation_artifacts

    # =========================================================================
    # Implementation Artifacts (during/after implementation)
    # =========================================================================

    @cached_property
    def sprint_status_file(self) -> Path:
        """Sprint status tracking file (in implementation artifacts)."""
        return self.implementation_artifacts / "sprint-status.yaml"

    @cached_property
    def validations_dir(self) -> Path:
        """Directory for story validation reports."""
        return self.implementation_artifacts / "story-validations"

    @cached_property
    def code_reviews_dir(self) -> Path:
        """Directory for code review reports."""
        return self.implementation_artifacts / "code-reviews"

    @cached_property
    def benchmarks_dir(self) -> Path:
        """Directory for benchmarking/evaluation records."""
        return self.implementation_artifacts / "benchmarks"

    @cached_property
    def retrospectives_dir(self) -> Path:
        """Directory for epic retrospective reports."""
        return self.implementation_artifacts / "retrospectives"

    @cached_property
    def legacy_sprint_artifacts(self) -> Path:
        """Legacy sprint artifacts directory (docs/sprint-artifacts/)."""
        return self.project_knowledge / "sprint-artifacts"

    # =========================================================================
    # Project Knowledge (reference documentation)
    # =========================================================================

    @cached_property
    def prd_file(self) -> Path:
        """Product Requirements Document."""
        return self.project_knowledge / "prd.md"

    @cached_property
    def architecture_file(self) -> Path:
        """Architecture document."""
        return self.project_knowledge / "architecture.md"

    @cached_property
    def project_context_file(self) -> Path:
        """Project context file for AI agents."""
        return self.project_knowledge / "project_context.md"

    @cached_property
    def modules_dir(self) -> Path:
        """Directory for optional module documentation (docs/modules/)."""
        return self.project_knowledge / "modules"

    # =========================================================================
    # Internal Tool State (not output artifacts)
    # =========================================================================

    @cached_property
    def bmad_assist_dir(self) -> Path:
        """Internal bmad-assist state directory (.bmad-assist/)."""
        return self.project_root / ".bmad-assist"

    @cached_property
    def state_file(self) -> Path:
        """Loop state persistence file."""
        return self.bmad_assist_dir / "state.yaml"

    @cached_property
    def patches_dir(self) -> Path:
        """Workflow patches directory."""
        return self.bmad_assist_dir / "patches"

    @cached_property
    def cache_dir(self) -> Path:
        """Compiled template cache directory."""
        return self.bmad_assist_dir / "cache"

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def get_sprint_status_search_locations(self) -> list[Path]:
        """Get all locations to search for sprint-status.yaml.

        Used for error messages to show user all checked locations.
        Returns deduplicated list of resolved paths.
        """
        candidates = [
            self.sprint_status_file,  # New: implementation-artifacts/
            self.planning_artifacts / "sprint-status.yaml",  # Beta default
            self.legacy_sprint_artifacts / "sprint-status.yaml",  # Legacy
            self.project_knowledge / "sprint-status.yaml",  # Legacy (direct)
        ]
        # Deduplicate while preserving order, return resolved paths for consistency
        seen: set[Path] = set()
        result: list[Path] = []
        for path in candidates:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)
        return result

    def find_sprint_status(self) -> Path | None:
        """Find sprint-status.yaml, checking new location then legacy.

        Returns:
            Path to existing sprint-status.yaml, or None if not found.

        """
        for path in self.get_sprint_status_search_locations():
            if path.exists():
                logger.debug("Found sprint-status at: %s", path)
                return path
        return None

    def get_benchmark_month_dir(self, year: int, month: int) -> Path:
        """Get benchmark directory for a specific month.

        Args:
            year: Year (e.g., 2025).
            month: Month (1-12).

        Returns:
            Path to benchmark directory for that month (e.g., benchmarks/2025-12/).

        """
        return self.benchmarks_dir / f"{year}-{month:02d}"

    def get_story_file(self, epic: "EpicId", story: int) -> Path:
        """Get path to a story file.

        Args:
            epic: Epic ID (int or str).
            story: Story number within epic.

        Returns:
            Path to story file in stories directory.

        """
        return self.stories_dir / f"{epic}-{story}.md"

    def get_validation_file(self, epic: "EpicId", story: int | str, role_id: str) -> Path:
        """Get path to a validation report file (without timestamp).

        Note: Actual files include timestamp: validation-{epic}-{story}-{role_id}-{timestamp}.md
        This returns the base pattern for glob matching.

        Args:
            epic: Epic ID (int or str).
            story: Story number (int or str like "6a").
            role_id: Role identifier (single letter: 'a', 'b', 'c'...).

        Returns:
            Path to validation report file (base pattern).

        """
        return self.validations_dir / f"validation-{epic}-{story}-{role_id}.md"

    def get_code_review_file(self, epic: "EpicId", story: int | str, role_id: str) -> Path:
        """Get path to a code review report file (without timestamp).

        Note: Actual files include timestamp: code-review-{epic}-{story}-{role_id}-{timestamp}.md
        This returns the base pattern for glob matching.

        Args:
            epic: Epic ID (int or str).
            story: Story number (int or str like "6a").
            role_id: Role identifier (single letter: 'a', 'b', 'c'...).

        Returns:
            Path to code review report file (base pattern).

        """
        return self.code_reviews_dir / f"code-review-{epic}-{story}-{role_id}.md"

    def ensure_directories(self) -> None:
        """Create all output directories if they don't exist.

        Raises:
            PermissionError: If external path cannot be created (with clear message).

        """
        directories = [
            self.output_folder,
            self.planning_artifacts,
            self.implementation_artifacts,
            self.epics_dir,
            self.stories_dir,
            self.validations_dir,
            self.code_reviews_dir,
            self.benchmarks_dir,
            self.retrospectives_dir,
            self.bmad_assist_dir,
            self.patches_dir,
            self.cache_dir,
            # NOTE: project_knowledge intentionally NOT included
            # It should exist (external docs) or be created by user
        ]
        for directory in directories:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                logger.debug("Ensured directory exists: %s", directory)
            except PermissionError as e:
                raise PermissionError(
                    f"Cannot create directory '{directory}'. "
                    f"If this is an external path, ensure it exists and is writable. "
                    f"Original error: {e}"
                ) from e

    def __repr__(self) -> str:
        """Return string representation for debugging."""
        return f"ProjectPaths(project_root={self.project_root})"


# =============================================================================
# Singleton Pattern
# =============================================================================

_paths_instance: ProjectPaths | None = None


def init_paths(project_root: Path, config: dict[str, Any] | None = None) -> ProjectPaths:
    """Initialize the paths singleton.

    This should be called once at application startup (typically in cli.py)
    before any other module tries to access paths.

    Args:
        project_root: The root directory of the project.
        config: Optional configuration dictionary with path overrides.

    Returns:
        Initialized ProjectPaths instance.

    """
    global _paths_instance
    _paths_instance = ProjectPaths(project_root, config)
    logger.debug("Initialized paths for project: %s", project_root)
    return _paths_instance


def get_paths() -> ProjectPaths:
    """Get the paths singleton instance.

    Returns:
        The initialized ProjectPaths instance.

    Raises:
        RuntimeError: If paths have not been initialized via init_paths().

    """
    if _paths_instance is None:
        raise RuntimeError("Paths not initialized. Call init_paths() first (typically in cli.py).")
    return _paths_instance


def _reset_paths() -> None:
    """Reset paths singleton for testing purposes only.

    This function should only be used in tests to ensure clean state
    between test cases.
    """
    global _paths_instance
    _paths_instance = None

"""Strategic context collection service for workflow compilers.

Provides config-driven loading of strategic documents (PRD, Architecture, UX, project-context)
with support for sharded documents and token budgets.

Usage:
    service = StrategicContextService(context, "dev_story")
    files = service.collect()  # Returns dict[str, str] of {path: content}

The service respects strategic_context configuration in bmad-assist.yaml:
- If config is absent (None): legacy behavior (load all docs)
- If config is present: use per-workflow include lists and main_only flags
- budget=0 disables strategic context entirely
"""

import logging
from pathlib import Path
from typing import NamedTuple

from bmad_assist.bmad.sharding import load_sharded_content
from bmad_assist.bmad.sharding.sorting import DocType
from bmad_assist.compiler.shared_utils import (
    estimate_tokens,
    find_file_in_planning_dir,
    find_project_context_file,
    get_planning_artifacts_dir,
    safe_read_file,
)
from bmad_assist.compiler.types import CompilerContext

logger = logging.getLogger(__name__)


class _LoadedConfig(NamedTuple):
    """Loaded strategic context configuration."""

    include: tuple[str, ...]  # Doc types to include
    main_only: bool  # Load only main file for sharded docs
    budget: int  # Token budget cap


# Doc type -> (file_patterns, dir_name, sharding_doc_type) mapping
# file_patterns: list of patterns to try IN ORDER (first match wins)
# dir_name: directory name for sharded docs
# sharding_doc_type: DocType for load_sharded_content (or None if not applicable)
DOC_PATTERNS: dict[str, tuple[list[str] | None, str | None, DocType | None]] = {
    "project-context": (None, None, None),  # Special handling via find_project_context_file()
    "prd": (["prd.md"], "prd", "prd"),  # prd.md or prd/ directory
    "architecture": (["architecture.md"], "architecture", "architecture"),
    # Prioritized patterns - try specific first, then fallback
    "ux": (["ux.md", "ux-design.md", "ux-*.md"], "ux", "ux"),
}


class StrategicContextService:
    """Service for collecting strategic documents with config-driven filtering.

    Thread-safe: Config is read once at init and not mutated.
    Fail-safe: Errors loading individual docs are logged and skipped, not raised.

    Attributes:
        context: Compiler context with project paths.
        workflow_name: Name of the workflow being compiled.

    Example:
        >>> service = StrategicContextService(context, "dev_story")
        >>> files = service.collect()
        >>> # files = {"docs/project-context.md": "# Project Context..."}

    """

    def __init__(self, context: CompilerContext, workflow_name: str) -> None:
        """Initialize service with compiler context and workflow name.

        Args:
            context: Compiler context with project paths.
            workflow_name: Name of the workflow (e.g., "dev_story", "code_review").

        """
        self.context = context
        self.workflow_name = workflow_name
        self._config = self._load_config()

    def _load_config(self) -> _LoadedConfig:
        """Load strategic context config with fallback to hardcoded defaults.

        Always returns a valid _LoadedConfig:
        1. If config is loaded and has strategic_context section, uses it
        2. If config is loaded but strategic_context is None, uses StrategicContextConfig defaults
        3. If config is not loaded (standalone tests), uses hardcoded defaults

        Returns:
            _LoadedConfig with include, main_only, budget.

        """
        try:
            from bmad_assist.core.config import StrategicContextConfig, get_config

            cfg = get_config().compiler.strategic_context
            if cfg is None:
                # No explicit config - use StrategicContextConfig defaults
                # This enables the new optimized behavior for unconfigured projects
                cfg = StrategicContextConfig()
                logger.debug("No strategic_context config, using optimized defaults")

            include, main_only = cfg.get_workflow_config(self.workflow_name)
            logger.debug(
                "Strategic context config for %s: include=%s, main_only=%s, budget=%d",
                self.workflow_name,
                include,
                main_only,
                cfg.budget,
            )
            return _LoadedConfig(include=include, main_only=main_only, budget=cfg.budget)
        except (AttributeError, ImportError) as e:
            # Config not initialized or import failed (e.g., standalone tests)
            # Still use defaults for consistent behavior
            logger.debug("Config module not available, using hardcoded defaults: %s", e)
            return self._get_hardcoded_defaults()
        except Exception as e:
            # ConfigError when config not loaded - use hardcoded defaults
            logger.debug("Config not available, using hardcoded defaults: %s", e)
            return self._get_hardcoded_defaults()

    def _get_hardcoded_defaults(self) -> _LoadedConfig:
        """Get hardcoded defaults for workflows when config is not available.

        This ensures consistent behavior even in standalone tests.

        Returns:
            _LoadedConfig with workflow-specific defaults.

        """
        import re

        # Normalize workflow name
        name = re.sub(r"[^a-z0-9]", "_", self.workflow_name.lower())

        # Workflow-specific defaults matching StrategicContextConfig
        workflow_defaults: dict[str, tuple[tuple[str, ...], bool]] = {
            "create_story": (("project-context", "prd", "architecture", "ux"), True),
            "validate_story": (("project-context", "architecture"), True),
            "validate_story_synthesis": (("project-context",), True),
        }

        # Get workflow-specific or fall back to general defaults
        include, main_only = workflow_defaults.get(
            name,
            (("project-context",), True),  # General default
        )

        return _LoadedConfig(
            include=include,
            main_only=main_only,
            budget=8000,  # Default budget
        )

    def collect(self) -> dict[str, str]:
        """Collect strategic docs based on config.

        Returns dict with file paths as keys and content as values.
        Keys are file paths (not doc types) for compatibility with compiler context.

        Returns:
            Dictionary of {path: content} for collected documents.

        """
        # _config is always populated (from config or hardcoded defaults)
        include = self._config.include
        main_only = self._config.main_only
        budget = self._config.budget

        # budget=0 means disabled
        if budget == 0:
            logger.info("Strategic context disabled (budget=0)")
            return {}

        files: dict[str, str] = {}
        total_tokens = 0
        loaded_docs: list[str] = []
        skipped_docs: list[str] = []

        for doc_type in include:
            path, content = self._load_doc(doc_type, main_only)
            if not content:
                logger.debug("Doc %s not found or empty", doc_type)
                continue

            tokens = estimate_tokens(content)

            # Budget check - but always load at least 1 file
            if total_tokens + tokens > budget and files:
                logger.warning(
                    "Skipping %s (%d tokens): would exceed budget %d", doc_type, tokens, budget
                )
                skipped_docs.append(doc_type)
                continue

            files[path] = content
            total_tokens += tokens
            loaded_docs.append(doc_type)

        # Telemetry logging at INFO level
        logger.info(
            "Strategic context for %s: %d tokens (%d docs: %s)%s",
            self.workflow_name,
            total_tokens,
            len(loaded_docs),
            ", ".join(loaded_docs) if loaded_docs else "none",
            f" [skipped: {', '.join(skipped_docs)}]" if skipped_docs else "",
        )

        return files

    def _load_doc(self, doc_type: str, main_only: bool) -> tuple[str, str]:
        """Load a single doc, handling sharding.

        Detection order:
        1. Check if sharded directory exists (e.g., docs/architecture/)
        2. If not, check for non-sharded file (e.g., docs/architecture.md)

        Args:
            doc_type: Document type (e.g., "prd", "architecture").
            main_only: If True, load only index.md for sharded docs.

        Returns:
            Tuple of (path, content). Returns ("", "") if doc not found or error.

        """
        project_root = self.context.project_root

        try:
            # Special handling for project-context
            if doc_type == "project-context":
                path = find_project_context_file(self.context)
                if path:
                    content = safe_read_file(path, project_root)
                    return str(path), content
                return "", ""

            # Get patterns for this doc type
            patterns = DOC_PATTERNS.get(doc_type)
            if not patterns:
                logger.warning("Unknown doc type: %s", doc_type)
                return "", ""

            file_patterns, dir_name, sharding_doc_type = patterns

            # Step 1: Check for SHARDED directory first
            # This prevents missing sharded docs when glob finds nothing
            if dir_name:
                planning_dir = get_planning_artifacts_dir(self.context)

                # Try planning_artifacts first, then project_knowledge
                for base_dir in [planning_dir, self.context.project_knowledge]:
                    if base_dir is None:
                        continue
                    shard_dir = base_dir / dir_name
                    if shard_dir.is_dir():
                        logger.debug("Found sharded %s at %s", doc_type, shard_dir)
                        return self._load_sharded_doc(shard_dir, main_only, sharding_doc_type)

            # Step 2: Check for non-sharded file
            # Try patterns in order (prioritized matching)
            if file_patterns:
                for pattern in file_patterns:
                    path = find_file_in_planning_dir(self.context, pattern)
                    if path and path.is_file():
                        content = safe_read_file(path, project_root)
                        return str(path), content

            logger.debug(
                "Doc %s not found (checked dir=%s, patterns=%s)", doc_type, dir_name, file_patterns
            )
            return "", ""

        except (FileNotFoundError, OSError, UnicodeDecodeError, PermissionError) as e:
            # Catch only file-related exceptions
            logger.warning("Error loading %s: %s", doc_type, e)
            return "", ""

    def _load_sharded_doc(
        self, path: Path, main_only: bool, sharding_doc_type: DocType | None
    ) -> tuple[str, str]:
        """Load sharded document, respecting main_only flag.

        For main_only=True:
        1. Try index.md in the directory
        2. Fallback to first .md file alphabetically
        3. Return empty if no files

        For main_only=False:
        Load all shards concatenated via load_sharded_content()

        Args:
            path: Path to sharded directory.
            main_only: If True, load only main file; otherwise load all shards.
            sharding_doc_type: DocType for sharded content sorting (or None to use default).

        Returns:
            Tuple of (path, content). Path is always a file path, not directory.

        """
        shard_dir = path if path.is_dir() else path.parent

        # Determine doc_type for sorting - default to "architecture" if None
        doc_type_for_sharding: DocType = sharding_doc_type or "architecture"

        if not main_only:
            # Load all shards
            sharded = load_sharded_content(path, doc_type_for_sharding)
            if sharded and sharded.content:
                # Return index.md path (or first file) as canonical path
                # This ensures dict keys are always file paths, not directories
                index_path = shard_dir / "index.md"
                if index_path.exists():
                    return str(index_path), sharded.content
                # Fallback: use first .md file as canonical path
                md_files = sorted(shard_dir.glob("*.md"))
                if md_files:
                    return str(md_files[0]), sharded.content
                return str(path), sharded.content  # Last resort: use dir path
            return "", ""

        # main_only=True: find index.md or first file
        # Try index.md first
        index_path = shard_dir / "index.md"
        if index_path.exists():
            content = safe_read_file(index_path, self.context.project_root)
            return str(index_path), content

        # Fallback: first .md file alphabetically (excluding index.md)
        md_files = sorted(f for f in shard_dir.glob("*.md") if f.name != "index.md")
        if md_files:
            logger.warning(
                "Sharded doc %s has no index.md, using %s",
                shard_dir.name,
                md_files[0].name,
            )
            content = safe_read_file(md_files[0], self.context.project_root)
            return str(md_files[0]), content

        logger.warning("Sharded doc %s has no .md files", shard_dir.name)
        return "", ""


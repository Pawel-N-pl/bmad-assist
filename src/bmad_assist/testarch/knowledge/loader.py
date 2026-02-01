"""Knowledge Base Loader for TEA knowledge fragments.

This module provides the main loader class for loading and caching
TEA knowledge fragments with workflow-specific defaults.

Usage:
    from bmad_assist.testarch.knowledge import get_knowledge_loader

    loader = get_knowledge_loader(project_root)
    content = loader.load_by_tags(["fixtures", "playwright"])
"""

import logging
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from bmad_assist.testarch.knowledge.cache import FragmentCache
from bmad_assist.testarch.knowledge.defaults import get_workflow_defaults
from bmad_assist.testarch.knowledge.index import parse_index
from bmad_assist.testarch.knowledge.models import KnowledgeFragment, KnowledgeIndex

if TYPE_CHECKING:
    from bmad_assist.testarch.config import KnowledgeConfig

logger = logging.getLogger(__name__)

# Default knowledge index locations (relative to project root)
DEFAULT_INDEX_PATH = "_bmad/tea/testarch/tea-index.csv"
FALLBACK_INDEX_PATH = "_bmad/bmm/testarch/tea-index.csv"

# Singleton storage for loaders (per project root)
_loaders: dict[Path, "KnowledgeBaseLoader"] = {}
_loader_lock = Lock()


def get_knowledge_loader(project_root: Path) -> "KnowledgeBaseLoader":
    """Get or create loader for project root (singleton per root).

    Thread-safe: Uses lock to prevent race conditions on concurrent access.

    Args:
        project_root: Project root directory.

    Returns:
        KnowledgeBaseLoader instance for the project.

    """
    resolved = project_root.resolve()
    with _loader_lock:
        if resolved not in _loaders:
            _loaders[resolved] = KnowledgeBaseLoader(resolved)
        return _loaders[resolved]


def clear_all_loaders() -> None:
    """Clear all singleton loaders.

    Removes all cached KnowledgeBaseLoader instances from the singleton
    storage. Used primarily for testing to ensure test isolation.

    After calling this function, the next call to get_knowledge_loader()
    will create a new loader instance.

    """
    _loaders.clear()


class KnowledgeBaseLoader:
    """Loader for TEA knowledge fragments with caching.

    Provides lazy loading of the knowledge index and fragment content
    with mtime-based cache invalidation.

    Attributes:
        project_root: Project root directory.

    """

    def __init__(self, project_root: Path) -> None:
        """Initialize loader with project root.

        Args:
            project_root: Project root directory.

        """
        self._project_root = project_root.resolve()
        self._cache = FragmentCache()
        self._index: KnowledgeIndex | None = None
        self._config: "KnowledgeConfig | None" = None

    def configure(self, config: "KnowledgeConfig | None") -> None:
        """Configure the loader with KnowledgeConfig.

        Stores the config for use in load operations. Clears cached index
        if the index_path differs from the current path.

        This method should be called at initialization time, not during
        runtime, to avoid mutating singleton state unexpectedly.

        Args:
            config: Knowledge configuration, or None to reset to defaults.

        """
        if config is None:
            self._config = None
            return

        # Check if index_path differs from current path
        # If so, clear cache to force reload with new path
        current_path = self._get_index_path()
        if current_path is not None:
            try:
                current_relative = str(current_path.relative_to(self._project_root))
            except ValueError:
                # Current path is bundled (not relative to project root)
                # Always clear cache when configuring custom path
                current_relative = "__bundled__"
            if current_relative != config.index_path:
                logger.debug(
                    "Index path changed from %s to %s, clearing cache",
                    current_relative,
                    config.index_path,
                )
                self.clear_cache()

        self._config = config

    @property
    def project_root(self) -> Path:
        """Get project root path."""
        return self._project_root

    def _get_index_path(self) -> Path | None:
        """Find the knowledge index file.

        Returns:
            Path to index file, or None if not found.

        """
        # If configured, use the configured index path
        if self._config is not None:
            config_path = self._project_root / self._config.index_path
            if config_path.exists():
                return config_path
            # Fall through to defaults if configured path doesn't exist
            logger.debug(
                "Configured index path %s does not exist, checking defaults",
                config_path,
            )

        # Check default location first
        default_path = self._project_root / DEFAULT_INDEX_PATH
        if default_path.exists():
            return default_path

        # Check fallback location
        fallback_path = self._project_root / FALLBACK_INDEX_PATH
        if fallback_path.exists():
            return fallback_path

        # Check bundled knowledge base (last resort)
        from bmad_assist.testarch.knowledge_base import get_bundled_index_path

        bundled_path = get_bundled_index_path()
        if bundled_path is not None:
            logger.debug("Using bundled knowledge base: %s", bundled_path)
            return bundled_path

        return None

    def _get_knowledge_dir(self, index_path: Path) -> Path:
        """Get knowledge directory (same dir as index file)."""
        return index_path.parent

    def _get_exclude_tags_from_config(self) -> list[str]:
        """Get exclude tags based on config flags.

        Returns:
            List of tags to exclude based on config settings.

        """
        exclude_tags: list[str] = []
        if self._config is None:
            return exclude_tags

        if not self._config.playwright_utils:
            exclude_tags.append("playwright-utils")
        if not self._config.mcp_enhancements:
            exclude_tags.append("mcp")

        return exclude_tags

    def load_index(self) -> list[KnowledgeFragment]:
        """Load and cache the knowledge index (lazy loading).

        Returns:
            List of KnowledgeFragment objects from the index.
            Returns empty list if index not found (with warning).

        """
        index_path = self._get_index_path()
        if index_path is None:
            logger.warning("No knowledge index found in project: %s", self._project_root)
            return []

        # Check cache first
        cached_index = self._cache.get_index(index_path)
        if cached_index is not None:
            self._index = cached_index
            return list(cached_index.fragments.values())

        # Parse index
        try:
            mtime = index_path.stat().st_mtime
        except OSError as e:
            logger.warning("Failed to stat index file: %s", e)
            return []

        fragments = parse_index(index_path)

        # Build index
        fragments_dict = {f.id: f for f in fragments}
        fragment_order = tuple(f.id for f in fragments)

        self._index = KnowledgeIndex(
            path=str(index_path),
            fragments=fragments_dict,
            loaded_at=datetime.now(),
            fragment_order=fragment_order,
        )

        # Cache the index
        self._cache.set_index(index_path, self._index, mtime)

        logger.debug("Loaded %d fragments from index", len(fragments))
        return fragments

    def _ensure_index_loaded(self) -> KnowledgeIndex | None:
        """Ensure index is loaded, return it.

        Returns:
            KnowledgeIndex or None if not available.

        """
        if self._index is None:
            self.load_index()
        return self._index

    def _resolve_fragment_path(self, fragment: KnowledgeFragment) -> Path | None:
        """Resolve fragment file path with security validation.

        Args:
            fragment: Fragment metadata.

        Returns:
            Resolved path if valid, None otherwise.

        """
        index_path = self._get_index_path()
        if index_path is None:
            return None

        knowledge_dir = self._get_knowledge_dir(index_path)
        fragment_path = (knowledge_dir / fragment.fragment_file).resolve()

        # Security: Validate path stays within knowledge directory
        try:
            fragment_path.relative_to(knowledge_dir.resolve())
        except ValueError:
            logger.warning(
                "Fragment path escapes knowledge directory: %s",
                fragment.fragment_file,
            )
            return None

        return fragment_path

    def _load_fragment_content(self, fragment: KnowledgeFragment) -> str | None:
        """Load fragment content from disk with caching.

        Args:
            fragment: Fragment metadata.

        Returns:
            Fragment content, or None if not found.

        """
        fragment_path = self._resolve_fragment_path(fragment)
        if fragment_path is None:
            return None

        # Check cache
        cached = self._cache.get_fragment(fragment.id, fragment_path)
        if cached is not None:
            return cached

        # Load from disk
        if not fragment_path.exists():
            logger.warning(
                "Fragment file not found: %s (id=%s)",
                fragment_path,
                fragment.id,
            )
            return None

        try:
            content = fragment_path.read_text(encoding="utf-8")
            mtime = fragment_path.stat().st_mtime
            self._cache.set_fragment(fragment.id, content, mtime)
            return content
        except OSError as e:
            logger.warning("Failed to read fragment %s: %s", fragment.id, e)
            return None

    def _format_fragment(self, fragment: KnowledgeFragment, content: str) -> str:
        """Format fragment with knowledge header.

        Args:
            fragment: Fragment metadata.
            content: Fragment content.

        Returns:
            Formatted content with header.

        """
        return f"<!-- KNOWLEDGE: {fragment.name} -->\n{content}"

    def load_fragment(self, fragment_id: str) -> str | None:
        """Load a single fragment by ID.

        Args:
            fragment_id: Fragment identifier.

        Returns:
            Fragment content with header, or None if not found.

        """
        index = self._ensure_index_loaded()
        if index is None:
            return None

        fragment = index.get_fragment(fragment_id)
        if fragment is None:
            logger.debug("Fragment not found in index: %s", fragment_id)
            return None

        content = self._load_fragment_content(fragment)
        if content is None:
            return None

        return self._format_fragment(fragment, content)

    def load_by_ids(
        self,
        ids: list[str],
        exclude_tags: list[str] | None = None,
    ) -> str:
        """Load fragments by ID list, concatenate with headers.

        Args:
            ids: List of fragment IDs to load.
            exclude_tags: Tags to exclude from results.

        Returns:
            Concatenated markdown content with headers.
            Empty string if no fragments found (with warning).

        """
        index = self._ensure_index_loaded()
        if index is None:
            logger.warning("No index loaded, returning empty content")
            return ""

        # Merge explicit exclude_tags with config-based exclusions
        config_exclude = self._get_exclude_tags_from_config()
        all_exclude = list(exclude_tags) if exclude_tags else []
        all_exclude.extend(config_exclude)
        exclude_set = set(all_exclude)
        contents: list[str] = []
        missing_count = 0

        for fragment_id in ids:
            fragment = index.get_fragment(fragment_id)
            if fragment is None:
                logger.warning("Fragment not found: %s, skipping", fragment_id)
                missing_count += 1
                continue

            # Check for excluded tags
            if exclude_set and exclude_set.intersection(fragment.tags):
                logger.debug("Fragment excluded by tag: %s", fragment_id)
                continue

            content = self._load_fragment_content(fragment)
            if content is None:
                logger.warning("Fragment file missing: %s, skipping", fragment_id)
                missing_count += 1
                continue

            contents.append(self._format_fragment(fragment, content))

        if not contents:
            logger.warning(
                "No fragments loaded from %d requested IDs (%d missing)",
                len(ids),
                missing_count,
            )
            return ""

        return "\n\n".join(contents)

    def load_by_tags(
        self,
        tags: list[str],
        exclude_tags: list[str] | None = None,
    ) -> str:
        """Load all fragments matching any tag in list.

        Args:
            tags: Tags to match (OR logic).
            exclude_tags: Tags to exclude from results.

        Returns:
            Concatenated markdown content with headers.
            Empty string if no fragments found.

        """
        index = self._ensure_index_loaded()
        if index is None:
            logger.warning("No index loaded, returning empty content")
            return ""

        fragments = index.get_fragments_by_tags(tags, exclude_tags)
        if not fragments:
            logger.debug("No fragments match tags: %s", tags)
            return ""

        contents: list[str] = []
        for fragment in fragments:
            content = self._load_fragment_content(fragment)
            if content is None:
                logger.warning("Fragment file missing: %s, skipping", fragment.id)
                continue
            contents.append(self._format_fragment(fragment, content))

        if not contents:
            logger.warning("No fragment content loaded for tags: %s", tags)
            return ""

        return "\n\n".join(contents)

    def load_for_workflow(
        self,
        workflow_id: str,
        tea_flags: dict[str, Any] | None = None,
    ) -> str:
        """Load workflow-specific default fragments.

        Args:
            workflow_id: Workflow identifier (e.g., "atdd", "test-review").
            tea_flags: TEA configuration flags. If tea_use_playwright_utils
                is False, excludes fragments with "playwright-utils" tag.
                Note: tea_flags are merged with config-based exclusions.

        Returns:
            Concatenated markdown content with headers.
            Empty string if no defaults for workflow.

        """
        # Get fragment IDs from config or defaults
        if self._config is not None:
            fragment_ids = self._config.get_workflow_fragments(workflow_id)
        else:
            fragment_ids = get_workflow_defaults(workflow_id)

        if not fragment_ids:
            logger.debug("No default fragments for workflow: %s", workflow_id)
            return ""

        # Build exclude tags based on flags (AC6)
        # Config-based exclusions are handled by load_by_ids
        exclude_tags: list[str] = []
        if tea_flags:
            if not tea_flags.get("tea_use_playwright_utils", True):
                exclude_tags.append("playwright-utils")

        return self.load_by_ids(fragment_ids, exclude_tags=exclude_tags)

    def clear_cache(self) -> None:
        """Clear all cached data (for testing)."""
        self._cache.clear_cache()
        self._index = None

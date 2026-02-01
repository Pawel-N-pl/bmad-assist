"""Fragment caching for TEA Knowledge Base.

This module provides mtime-based caching for parsed index
and loaded fragment content.

Usage:
    from bmad_assist.testarch.knowledge.cache import FragmentCache

    cache = FragmentCache()
    content = cache.get_fragment("fixture-architecture")
    if content is None:
        content = load_from_disk()
        cache.set_fragment("fixture-architecture", content, mtime)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from bmad_assist.testarch.knowledge.models import KnowledgeIndex

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with content and mtime.

    Attributes:
        content: Cached content (fragment text or index).
        mtime: File modification time at cache time.
        cached_at: Timestamp when entry was cached.

    """

    content: Any
    mtime: float
    cached_at: datetime = field(default_factory=datetime.now)

    def is_valid(self, current_mtime: float) -> bool:
        """Check if cache entry is still valid.

        Args:
            current_mtime: Current file modification time.

        Returns:
            True if mtime matches, False if file was modified.

        """
        return self.mtime == current_mtime


class FragmentCache:
    """Mtime-based cache for knowledge fragments and index.

    Caches parsed index and loaded fragment content. Invalidates
    entries when file modification time changes.

    Thread-safe for read operations; not thread-safe for writes.

    """

    def __init__(self) -> None:
        """Initialize empty cache."""
        self._index_cache: CacheEntry | None = None
        self._fragment_cache: dict[str, CacheEntry] = {}
        self._index_path: Path | None = None

    def get_index(self, index_path: Path) -> KnowledgeIndex | None:
        """Get cached index if valid.

        Args:
            index_path: Path to index file.

        Returns:
            Cached KnowledgeIndex if valid, None if cache miss or stale.

        """
        if self._index_cache is None:
            return None

        if self._index_path != index_path:
            return None

        try:
            current_mtime = index_path.stat().st_mtime
        except OSError:
            return None

        if not self._index_cache.is_valid(current_mtime):
            logger.debug("Index cache stale (mtime changed): %s", index_path)
            self._index_cache = None
            return None

        return self._index_cache.content

    def set_index(self, index_path: Path, index: KnowledgeIndex, mtime: float) -> None:
        """Cache index with mtime.

        Args:
            index_path: Path to index file.
            index: Parsed KnowledgeIndex.
            mtime: File modification time.

        """
        self._index_path = index_path
        self._index_cache = CacheEntry(content=index, mtime=mtime)
        logger.debug("Cached index: %s", index_path)

    def get_fragment(self, fragment_id: str, fragment_path: Path) -> str | None:
        """Get cached fragment content if valid.

        Args:
            fragment_id: Fragment identifier.
            fragment_path: Path to fragment file.

        Returns:
            Cached content if valid, None if cache miss or stale.

        """
        entry = self._fragment_cache.get(fragment_id)
        if entry is None:
            return None

        try:
            current_mtime = fragment_path.stat().st_mtime
        except OSError:
            return None

        if not entry.is_valid(current_mtime):
            logger.debug("Fragment cache stale (mtime changed): %s", fragment_id)
            del self._fragment_cache[fragment_id]
            return None

        return entry.content

    def set_fragment(self, fragment_id: str, content: str, mtime: float) -> None:
        """Cache fragment content with mtime.

        Args:
            fragment_id: Fragment identifier.
            content: Fragment content.
            mtime: File modification time.

        """
        self._fragment_cache[fragment_id] = CacheEntry(content=content, mtime=mtime)
        logger.debug("Cached fragment: %s", fragment_id)

    def clear_cache(self) -> None:
        """Clear all cached data.

        Used for testing and manual cache invalidation.

        """
        self._index_cache = None
        self._fragment_cache.clear()
        self._index_path = None
        logger.debug("Fragment cache cleared")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats.

        """
        return {
            "index_cached": self._index_cache is not None,
            "fragments_cached": len(self._fragment_cache),
            "fragment_ids": list(self._fragment_cache.keys()),
        }

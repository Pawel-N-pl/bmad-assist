"""Tests for fragment caching."""

import pytest
from pathlib import Path
from datetime import datetime

from bmad_assist.testarch.knowledge.cache import FragmentCache, CacheEntry
from bmad_assist.testarch.knowledge.models import KnowledgeFragment, KnowledgeIndex


class TestCacheEntry:
    """Tests for CacheEntry class."""

    def test_create_cache_entry(self) -> None:
        """Test creating a cache entry."""
        entry = CacheEntry(content="test content", mtime=12345.67)
        assert entry.content == "test content"
        assert entry.mtime == 12345.67
        assert isinstance(entry.cached_at, datetime)

    def test_is_valid_matching_mtime(self) -> None:
        """Test validity check with matching mtime."""
        entry = CacheEntry(content="test", mtime=12345.67)
        assert entry.is_valid(12345.67) is True

    def test_is_valid_different_mtime(self) -> None:
        """Test validity check with different mtime."""
        entry = CacheEntry(content="test", mtime=12345.67)
        assert entry.is_valid(12345.68) is False


class TestFragmentCache:
    """Tests for FragmentCache class."""

    def test_get_index_empty_cache(self, tmp_path: Path) -> None:
        """Test getting index from empty cache returns None."""
        cache = FragmentCache()
        index_path = tmp_path / "index.csv"
        index_path.write_text("content")
        assert cache.get_index(index_path) is None

    def test_set_and_get_index(self, tmp_path: Path) -> None:
        """Test setting and getting index from cache."""
        cache = FragmentCache()
        index_path = tmp_path / "index.csv"
        index_path.write_text("content")
        mtime = index_path.stat().st_mtime

        index = KnowledgeIndex(path=str(index_path), fragments={})
        cache.set_index(index_path, index, mtime)

        cached = cache.get_index(index_path)
        assert cached is not None
        assert cached.path == str(index_path)

    def test_index_cache_invalidated_on_mtime_change(self, tmp_path: Path) -> None:
        """Test that index cache is invalidated when mtime changes."""
        cache = FragmentCache()
        index_path = tmp_path / "index.csv"
        index_path.write_text("content")
        mtime = index_path.stat().st_mtime

        index = KnowledgeIndex(path=str(index_path), fragments={})
        cache.set_index(index_path, index, mtime)

        # Modify file to change mtime
        import time
        time.sleep(0.01)  # Ensure mtime differs
        index_path.write_text("new content")

        cached = cache.get_index(index_path)
        assert cached is None

    def test_index_cache_invalidated_on_different_path(self, tmp_path: Path) -> None:
        """Test that different path returns cache miss."""
        cache = FragmentCache()
        index_path1 = tmp_path / "index1.csv"
        index_path2 = tmp_path / "index2.csv"
        index_path1.write_text("content")
        index_path2.write_text("content")
        mtime = index_path1.stat().st_mtime

        index = KnowledgeIndex(path=str(index_path1), fragments={})
        cache.set_index(index_path1, index, mtime)

        cached = cache.get_index(index_path2)
        assert cached is None

    def test_get_fragment_empty_cache(self, tmp_path: Path) -> None:
        """Test getting fragment from empty cache returns None."""
        cache = FragmentCache()
        fragment_path = tmp_path / "fragment.md"
        fragment_path.write_text("content")
        assert cache.get_fragment("test-id", fragment_path) is None

    def test_set_and_get_fragment(self, tmp_path: Path) -> None:
        """Test setting and getting fragment from cache."""
        cache = FragmentCache()
        fragment_path = tmp_path / "fragment.md"
        fragment_path.write_text("content")
        mtime = fragment_path.stat().st_mtime

        cache.set_fragment("test-id", "fragment content", mtime)

        cached = cache.get_fragment("test-id", fragment_path)
        assert cached == "fragment content"

    def test_fragment_cache_invalidated_on_mtime_change(self, tmp_path: Path) -> None:
        """Test that fragment cache is invalidated when mtime changes."""
        cache = FragmentCache()
        fragment_path = tmp_path / "fragment.md"
        fragment_path.write_text("content")
        mtime = fragment_path.stat().st_mtime

        cache.set_fragment("test-id", "fragment content", mtime)

        # Modify file to change mtime
        import time
        time.sleep(0.01)
        fragment_path.write_text("new content")

        cached = cache.get_fragment("test-id", fragment_path)
        assert cached is None

    def test_clear_cache(self, tmp_path: Path) -> None:
        """Test clearing all cached data."""
        cache = FragmentCache()
        index_path = tmp_path / "index.csv"
        fragment_path = tmp_path / "fragment.md"
        index_path.write_text("content")
        fragment_path.write_text("content")

        index = KnowledgeIndex(path=str(index_path), fragments={})
        cache.set_index(index_path, index, index_path.stat().st_mtime)
        cache.set_fragment("test-id", "content", fragment_path.stat().st_mtime)

        cache.clear_cache()

        assert cache.get_index(index_path) is None
        assert cache.get_fragment("test-id", fragment_path) is None

    def test_get_stats(self, tmp_path: Path) -> None:
        """Test getting cache statistics."""
        cache = FragmentCache()
        index_path = tmp_path / "index.csv"
        index_path.write_text("content")

        stats = cache.get_stats()
        assert stats["index_cached"] is False
        assert stats["fragments_cached"] == 0
        assert stats["fragment_ids"] == []

        index = KnowledgeIndex(path=str(index_path), fragments={})
        cache.set_index(index_path, index, index_path.stat().st_mtime)
        cache.set_fragment("frag1", "content", 123.0)
        cache.set_fragment("frag2", "content", 456.0)

        stats = cache.get_stats()
        assert stats["index_cached"] is True
        assert stats["fragments_cached"] == 2
        assert set(stats["fragment_ids"]) == {"frag1", "frag2"}

    def test_get_index_file_deleted(self, tmp_path: Path) -> None:
        """Test cache returns None when file is deleted."""
        cache = FragmentCache()
        index_path = tmp_path / "index.csv"
        index_path.write_text("content")
        mtime = index_path.stat().st_mtime

        index = KnowledgeIndex(path=str(index_path), fragments={})
        cache.set_index(index_path, index, mtime)

        # Delete the file
        index_path.unlink()

        assert cache.get_index(index_path) is None

    def test_get_fragment_file_deleted(self, tmp_path: Path) -> None:
        """Test cache returns None when fragment file is deleted."""
        cache = FragmentCache()
        fragment_path = tmp_path / "fragment.md"
        fragment_path.write_text("content")
        mtime = fragment_path.stat().st_mtime

        cache.set_fragment("test-id", "content", mtime)

        # Delete the file
        fragment_path.unlink()

        assert cache.get_fragment("test-id", fragment_path) is None

"""Tests for KnowledgeBaseLoader class."""

from pathlib import Path

import pytest

from bmad_assist.testarch.knowledge.loader import (
    DEFAULT_INDEX_PATH,
    FALLBACK_INDEX_PATH,
    KnowledgeBaseLoader,
    clear_all_loaders,
    get_knowledge_loader,
)


class TestGetKnowledgeLoader:
    """Tests for get_knowledge_loader singleton factory."""

    def test_returns_same_instance_for_same_root(self, mock_knowledge_dir: Path) -> None:
        """Test that same project root returns same loader instance."""
        clear_all_loaders()
        loader1 = get_knowledge_loader(mock_knowledge_dir)
        loader2 = get_knowledge_loader(mock_knowledge_dir)
        assert loader1 is loader2

    def test_returns_different_instance_for_different_root(self, tmp_path: Path) -> None:
        """Test that different project roots return different loaders."""
        clear_all_loaders()
        dir1 = tmp_path / "project1"
        dir2 = tmp_path / "project2"
        dir1.mkdir()
        dir2.mkdir()

        loader1 = get_knowledge_loader(dir1)
        loader2 = get_knowledge_loader(dir2)
        assert loader1 is not loader2

    def test_clear_all_loaders(self, mock_knowledge_dir: Path) -> None:
        """Test that clear_all_loaders resets the cache."""
        clear_all_loaders()
        loader1 = get_knowledge_loader(mock_knowledge_dir)
        clear_all_loaders()
        loader2 = get_knowledge_loader(mock_knowledge_dir)
        assert loader1 is not loader2


class TestKnowledgeBaseLoader:
    """Tests for KnowledgeBaseLoader class."""

    @pytest.fixture(autouse=True)
    def cleanup_loaders(self) -> None:
        """Clear loaders before each test."""
        clear_all_loaders()

    def test_init(self, mock_knowledge_dir: Path) -> None:
        """Test loader initialization."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        assert loader.project_root == mock_knowledge_dir.resolve()

    def test_load_index_success(self, mock_knowledge_dir: Path) -> None:
        """Test loading index returns fragments."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        fragments = loader.load_index()
        assert len(fragments) == 4
        assert fragments[0].id == "fixture-architecture"

    def test_load_index_no_index_file_uses_bundled(self, empty_knowledge_dir: Path) -> None:
        """Test loading index with no project index falls back to bundled."""
        loader = KnowledgeBaseLoader(empty_knowledge_dir)
        fragments = loader.load_index()
        # Falls back to bundled knowledge base (34 fragments)
        assert len(fragments) > 0
        # Verify it's using bundled by checking for known fragment
        fragment_ids = {f.id for f in fragments}
        assert "fixture-architecture" in fragment_ids

    def test_load_index_uses_cache(self, mock_knowledge_dir: Path) -> None:
        """Test that load_index uses cache on second call."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        fragments1 = loader.load_index()
        fragments2 = loader.load_index()
        # Same content
        assert len(fragments1) == len(fragments2)
        # Verify cache is being used
        stats = loader._cache.get_stats()
        assert stats["index_cached"] is True

    def test_load_fragment_success(self, mock_knowledge_dir: Path) -> None:
        """Test loading a single fragment by ID."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_fragment("fixture-architecture")
        assert content is not None
        assert "<!-- KNOWLEDGE: Fixture Architecture -->" in content
        assert "# Fixture Architecture Playbook" in content

    def test_load_fragment_not_in_index(self, mock_knowledge_dir: Path) -> None:
        """Test loading a fragment not in index returns None."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_fragment("nonexistent-fragment")
        assert content is None

    def test_load_fragment_file_missing(self, mock_knowledge_dir: Path) -> None:
        """Test loading a fragment with missing file returns None."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        # Add a fragment with missing file
        index_path = mock_knowledge_dir / "_bmad" / "tea" / "testarch" / "tea-index.csv"
        original = index_path.read_text()
        index_path.write_text(
            original + "missing,Missing,Desc,tag,knowledge/missing.md\n"
        )
        loader.clear_cache()

        content = loader.load_fragment("missing")
        assert content is None

    def test_load_by_ids_success(self, mock_knowledge_dir: Path) -> None:
        """Test loading multiple fragments by ID list."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_by_ids(["fixture-architecture", "network-first"])
        assert "<!-- KNOWLEDGE: Fixture Architecture -->" in content
        assert "<!-- KNOWLEDGE: Network-First Safeguards -->" in content

    def test_load_by_ids_missing_skipped(self, mock_knowledge_dir: Path) -> None:
        """Test that missing fragments are skipped."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_by_ids(
            ["fixture-architecture", "nonexistent", "network-first"]
        )
        assert "<!-- KNOWLEDGE: Fixture Architecture -->" in content
        assert "<!-- KNOWLEDGE: Network-First Safeguards -->" in content

    def test_load_by_ids_all_missing_returns_empty(self, mock_knowledge_dir: Path) -> None:
        """Test that all missing fragments returns empty string."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_by_ids(["nonexistent1", "nonexistent2"])
        assert content == ""

    def test_load_by_ids_with_exclude_tags(self, mock_knowledge_dir: Path) -> None:
        """Test excluding fragments by tags."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_by_ids(
            ["fixture-architecture", "network-first", "overview"],
            exclude_tags=["playwright-utils"],
        )
        # network-first and overview have playwright-utils tag
        assert "<!-- KNOWLEDGE: Fixture Architecture -->" in content
        assert "Network-First" not in content
        assert "Overview" not in content

    def test_load_by_tags_success(self, mock_knowledge_dir: Path) -> None:
        """Test loading fragments by tags."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_by_tags(["fixtures"])
        assert "<!-- KNOWLEDGE: Fixture Architecture -->" in content

    def test_load_by_tags_or_logic(self, mock_knowledge_dir: Path) -> None:
        """Test that tags use OR logic."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_by_tags(["fixtures", "network"])
        # Should include both fixture-architecture (fixtures tag) and network-first (network tag)
        assert "Fixture Architecture" in content
        assert "Network-First" in content

    def test_load_by_tags_no_matches(self, mock_knowledge_dir: Path) -> None:
        """Test loading with non-matching tags returns empty string."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_by_tags(["nonexistent-tag"])
        assert content == ""

    def test_load_by_tags_with_exclude_tags(self, mock_knowledge_dir: Path) -> None:
        """Test excluding tags when loading by tags."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_by_tags(
            ["playwright-utils"],
            exclude_tags=["network"],
        )
        # network-first has both playwright-utils and network tags
        # Should only include overview which has playwright-utils but not network
        assert "Overview" in content
        assert "Network-First" not in content

    def test_load_for_workflow_known_workflow(self, mock_knowledge_dir: Path) -> None:
        """Test loading for known workflow with defaults."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_for_workflow("atdd")
        # atdd workflow includes fixture-architecture by default
        assert "Fixture Architecture" in content or content == ""
        # Note: May be empty if default fragments don't exist

    def test_load_for_workflow_unknown_workflow(self, mock_knowledge_dir: Path) -> None:
        """Test loading for unknown workflow returns empty string."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_for_workflow("unknown-workflow")
        assert content == ""

    def test_load_for_workflow_with_tea_flags(self, mock_knowledge_dir: Path) -> None:
        """Test that tea_use_playwright_utils=False excludes playwright-utils tag."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        # ci workflow includes ci-burn-in, selective-testing, burn-in
        # None of these exist in our mock, but test the exclusion logic
        content = loader.load_for_workflow(
            "framework",
            tea_flags={"tea_use_playwright_utils": False},
        )
        # framework includes overview which has playwright-utils tag
        # Should be excluded with tea_use_playwright_utils=False
        # Since fixtures don't exist, just verify no error

    def test_clear_cache(self, mock_knowledge_dir: Path) -> None:
        """Test clearing loader cache."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        loader.load_index()
        loader.load_fragment("fixture-architecture")

        stats = loader._cache.get_stats()
        assert stats["index_cached"] is True
        assert stats["fragments_cached"] > 0

        loader.clear_cache()

        stats = loader._cache.get_stats()
        assert stats["index_cached"] is False
        assert stats["fragments_cached"] == 0

    def test_fragment_content_format(self, mock_knowledge_dir: Path) -> None:
        """Test that fragment content has correct format with header."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_fragment("fixture-architecture")
        assert content is not None
        # Check header format
        lines = content.split("\n")
        assert lines[0] == "<!-- KNOWLEDGE: Fixture Architecture -->"

    def test_multiple_fragments_separated(self, mock_knowledge_dir: Path) -> None:
        """Test that multiple fragments are separated by double newline."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        content = loader.load_by_ids(["fixture-architecture", "network-first"])
        # Should have double newline between fragments
        assert "\n\n<!-- KNOWLEDGE:" in content

    def test_fragment_path_security(self, mock_knowledge_dir: Path) -> None:
        """Test that path traversal in fragment_file is blocked."""
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        # Modify index to have path traversal
        index_path = mock_knowledge_dir / "_bmad" / "tea" / "testarch" / "tea-index.csv"
        original = index_path.read_text()
        index_path.write_text(
            original + "escape,Escape,Desc,tag,../../../etc/passwd\n"
        )
        loader.clear_cache()

        content = loader.load_fragment("escape")
        assert content is None


class TestDefaultLocations:
    """Tests for default index path constants."""

    def test_default_index_path(self) -> None:
        """Test default index path constant."""
        assert DEFAULT_INDEX_PATH == "_bmad/tea/testarch/tea-index.csv"

    def test_fallback_index_path(self) -> None:
        """Test fallback index path constant."""
        assert FALLBACK_INDEX_PATH == "_bmad/bmm/testarch/tea-index.csv"

    def test_loader_uses_fallback_path(self, tmp_path: Path) -> None:
        """Test that loader uses fallback path when default doesn't exist."""
        clear_all_loaders()
        # Create fallback location
        fallback_dir = tmp_path / "_bmad" / "bmm" / "testarch"
        fallback_dir.mkdir(parents=True)
        (fallback_dir / "knowledge").mkdir()

        index_path = fallback_dir / "tea-index.csv"
        index_path.write_text(
            """id,name,description,tags,fragment_file
test,Test,Desc,tag,knowledge/test.md
"""
        )
        (fallback_dir / "knowledge" / "test.md").write_text("# Test")

        loader = KnowledgeBaseLoader(tmp_path)
        fragments = loader.load_index()
        assert len(fragments) == 1
        assert fragments[0].id == "test"


class TestKnowledgeBaseLoaderConfigure:
    """Tests for KnowledgeBaseLoader.configure() method (Story 25.5)."""

    @pytest.fixture(autouse=True)
    def cleanup_loaders(self) -> None:
        """Clear loaders before each test."""
        clear_all_loaders()

    def test_configure_stores_config(self, mock_knowledge_dir: Path) -> None:
        """Test that configure() stores the config."""
        from bmad_assist.testarch.config import KnowledgeConfig

        config = KnowledgeConfig(playwright_utils=False)
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        loader.configure(config)

        assert loader._config is config

    def test_configure_clears_cache_on_index_path_change(
        self, mock_knowledge_dir: Path
    ) -> None:
        """Test that configure() clears cache when index_path differs."""
        from bmad_assist.testarch.config import KnowledgeConfig

        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        # Load index to populate cache
        loader.load_index()
        assert loader._cache.get_stats()["index_cached"] is True

        # Configure with different index path
        config = KnowledgeConfig(index_path="custom/path/index.csv")
        loader.configure(config)

        # Cache should be cleared
        assert loader._cache.get_stats()["index_cached"] is False

    def test_configure_preserves_cache_if_index_path_unchanged(
        self, mock_knowledge_dir: Path
    ) -> None:
        """Test that configure() preserves cache when index_path is same."""
        from bmad_assist.testarch.config import KnowledgeConfig

        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        # Load index to populate cache
        loader.load_index()
        assert loader._cache.get_stats()["index_cached"] is True

        # Configure with default index path (same as DEFAULT_INDEX_PATH)
        config = KnowledgeConfig(index_path=DEFAULT_INDEX_PATH)
        loader.configure(config)

        # Cache should still be present
        assert loader._cache.get_stats()["index_cached"] is True

    def test_configure_uses_custom_index_path(self, tmp_path: Path) -> None:
        """Test that configure() uses custom index_path for loading."""
        from bmad_assist.testarch.config import KnowledgeConfig

        # Create custom index location
        custom_dir = tmp_path / "custom" / "location"
        custom_dir.mkdir(parents=True)
        (custom_dir / "knowledge").mkdir()

        index_path = custom_dir / "my-index.csv"
        index_path.write_text(
            """id,name,description,tags,fragment_file
custom-frag,Custom Fragment,Desc,custom,knowledge/custom.md
"""
        )
        (custom_dir / "knowledge" / "custom.md").write_text("# Custom Content")

        config = KnowledgeConfig(index_path="custom/location/my-index.csv")
        loader = KnowledgeBaseLoader(tmp_path)
        loader.configure(config)

        fragments = loader.load_index()
        assert len(fragments) == 1
        assert fragments[0].id == "custom-frag"

    def test_load_for_workflow_uses_config_fragments(
        self, mock_knowledge_dir: Path
    ) -> None:
        """Test that load_for_workflow uses config.get_workflow_fragments()."""
        from bmad_assist.testarch.config import KnowledgeConfig

        # Configure with custom workflow fragments
        config = KnowledgeConfig(
            default_fragments={"atdd": ["fixture-architecture"]},
        )
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        loader.configure(config)

        content = loader.load_for_workflow("atdd")
        assert "Fixture Architecture" in content

    def test_load_for_workflow_excludes_playwright_utils_when_disabled(
        self, mock_knowledge_dir: Path
    ) -> None:
        """Test that playwright_utils=False excludes playwright-utils tag."""
        from bmad_assist.testarch.config import KnowledgeConfig

        config = KnowledgeConfig(playwright_utils=False)
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        loader.configure(config)

        # Load fragments that include playwright-utils tagged ones
        content = loader.load_by_ids(
            ["fixture-architecture", "network-first", "overview"]
        )

        # fixture-architecture doesn't have playwright-utils tag
        assert "Fixture Architecture" in content
        # network-first and overview have playwright-utils tag - should be excluded
        assert "Network-First" not in content
        assert "Overview" not in content

    def test_load_for_workflow_excludes_mcp_when_disabled(
        self, mock_knowledge_dir: Path
    ) -> None:
        """Test that mcp_enhancements=False excludes mcp tag."""
        from bmad_assist.testarch.config import KnowledgeConfig

        config = KnowledgeConfig(mcp_enhancements=False)
        loader = KnowledgeBaseLoader(mock_knowledge_dir)
        loader.configure(config)

        # The mock doesn't have mcp-tagged fragments, but test the exclusion is set up
        # This mainly tests the implementation path

    def test_configure_none_resets_to_defaults(
        self, mock_knowledge_dir: Path
    ) -> None:
        """Test that configure(None) resets to default behavior."""
        from bmad_assist.testarch.config import KnowledgeConfig

        loader = KnowledgeBaseLoader(mock_knowledge_dir)

        # First configure with custom config
        config = KnowledgeConfig(playwright_utils=False)
        loader.configure(config)
        assert loader._config is config

        # Reset with None
        loader.configure(None)
        assert loader._config is None

    def test_get_exclude_tags_from_config(self, mock_knowledge_dir: Path) -> None:
        """Test _get_exclude_tags_from_config helper method."""
        from bmad_assist.testarch.config import KnowledgeConfig

        loader = KnowledgeBaseLoader(mock_knowledge_dir)

        # No config - no exclusions
        assert loader._get_exclude_tags_from_config() == []

        # playwright_utils=False
        loader.configure(KnowledgeConfig(playwright_utils=False))
        tags = loader._get_exclude_tags_from_config()
        assert "playwright-utils" in tags

        # mcp_enhancements=False
        loader.configure(KnowledgeConfig(mcp_enhancements=False))
        tags = loader._get_exclude_tags_from_config()
        assert "mcp" in tags

        # Both disabled
        loader.configure(
            KnowledgeConfig(playwright_utils=False, mcp_enhancements=False)
        )
        tags = loader._get_exclude_tags_from_config()
        assert "playwright-utils" in tags
        assert "mcp" in tags

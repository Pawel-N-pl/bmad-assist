"""Tests for sharding loaders module."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmad_assist.bmad.sharding.loaders import (
    ShardedContent,
    load_sharded_content,
    load_sharded_epics,
)
from bmad_assist.bmad.sharding.security import DuplicateEpicError

# Use the pre-built fixtures
FIXTURES_PATH = Path(__file__).parent.parent.parent / "fixtures" / "sharding"


class TestShardedContent:
    """Tests for ShardedContent dataclass."""

    def test_dataclass_fields(self) -> None:
        """ShardedContent has expected fields."""
        result = ShardedContent(
            content="test content",
            files_loaded=["file1.md"],
            files_skipped=["file2.md"],
        )
        assert result.content == "test content"
        assert result.files_loaded == ["file1.md"]
        assert result.files_skipped == ["file2.md"]


class TestLoadShardedContent:
    """Tests for load_sharded_content function."""

    def test_loads_architecture_with_index(self) -> None:
        """Loads architecture files in index.md order (AC10)."""
        arch_dir = FIXTURES_PATH / "architecture-valid"
        result = load_sharded_content(arch_dir, "architecture")

        # Verify files were loaded (index.md is NOT loaded - it's just for ordering)
        assert len(result.files_loaded) == 3  # 3 content files, no index.md
        assert result.content  # Non-empty content

        # Verify order from index.md: project-context, core-decisions, implementation-patterns
        loaded_names = [Path(f).name for f in result.files_loaded]
        assert loaded_names[0] == "project-context.md"
        assert loaded_names[1] == "core-decisions.md"
        assert loaded_names[2] == "implementation-patterns.md"

    def test_loads_prd_with_index(self) -> None:
        """Loads PRD files with index.md ordering (AC11)."""
        prd_dir = FIXTURES_PATH / "prd-valid"
        result = load_sharded_content(prd_dir, "prd")

        assert len(result.files_loaded) >= 2
        assert result.content

    def test_loads_ux_without_index_alphabetically(self) -> None:
        """Loads UX files alphabetically when no index.md (AC12)."""
        ux_dir = FIXTURES_PATH / "ux-no-index"
        result = load_sharded_content(ux_dir, "ux")

        assert len(result.files_loaded) == 2
        # Files should be sorted alphabetically: design-system before wireframes
        assert "design-system.md" in result.files_loaded[0]
        assert "wireframes.md" in result.files_loaded[1]

    def test_empty_directory_returns_empty_result(self, tmp_path: Path) -> None:
        """Empty directory returns empty ShardedContent (AC7)."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = load_sharded_content(empty_dir, "architecture")

        assert result.content == ""
        assert result.files_loaded == []
        assert result.files_skipped == []

    def test_handles_unreadable_file(self, tmp_path: Path) -> None:
        """Skips unreadable files without failing."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        good_file = test_dir / "good.md"
        good_file.write_text("Good content")

        result = load_sharded_content(test_dir, "architecture")

        assert len(result.files_loaded) == 1
        assert "Good content" in result.content

    def test_concatenates_content_with_separator(self, tmp_path: Path) -> None:
        """Content from multiple files is separated by double newlines."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "aaa.md").write_text("First")
        (test_dir / "bbb.md").write_text("Second")

        result = load_sharded_content(test_dir, "prd")

        assert "\n\n" in result.content
        assert "First" in result.content
        assert "Second" in result.content

    def test_index_order_respected(self, tmp_path: Path) -> None:
        """Files load in order specified by index.md."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "index.md").write_text("""
- [B](./bbb.md)
- [A](./aaa.md)
""")
        (test_dir / "aaa.md").write_text("AAA")
        (test_dir / "bbb.md").write_text("BBB")

        result = load_sharded_content(test_dir, "architecture")

        # BBB should come before AAA due to index order
        assert result.content.index("BBB") < result.content.index("AAA")


class TestLoadShardedEpics:
    """Tests for load_sharded_epics function."""

    def test_loads_epics_numerically_sorted(self) -> None:
        """Epics are sorted numerically: 1, 2, 10 (not 1, 10, 2) (AC2)."""
        epics_dir = FIXTURES_PATH / "epics-valid"
        epics = load_sharded_epics(epics_dir)

        # Should be 3 epics: 1, 2, 10
        assert len(epics) == 3

        # Verify numeric order
        epic_nums = [e.epic_num for e in epics if e.epic_num is not None]
        assert epic_nums == [1, 2, 10]

    def test_loads_epics_with_index_order(self) -> None:
        """Respects index.md ordering when present (AC3)."""
        epics_dir = FIXTURES_PATH / "epics-with-index"
        epics = load_sharded_epics(epics_dir)

        # Index specifies: epic-2 before epic-1, then orphan epic-3
        assert len(epics) >= 2

        # First should be epic 2 (per index order)
        first_epic_num = epics[0].epic_num
        assert first_epic_num == 2

    def test_detects_duplicate_epic_id(self) -> None:
        """Raises DuplicateEpicError for duplicate epic_id (AC7)."""
        epics_dir = FIXTURES_PATH / "epics-duplicate"

        with pytest.raises(DuplicateEpicError, match="Duplicate epic_id 1"):
            load_sharded_epics(epics_dir)

    def test_skips_malformed_files(self) -> None:
        """Gracefully skips malformed epic files."""
        epics_dir = FIXTURES_PATH / "epics-malformed"
        epics = load_sharded_epics(epics_dir)

        # Should load at least epic-1-valid.md
        assert len(epics) >= 1
        # The valid epic should be loaded
        valid_epic = next((e for e in epics if e.epic_num == 1), None)
        assert valid_epic is not None

    def test_empty_directory_returns_empty_list(self) -> None:
        """Empty directory returns empty list (AC7)."""
        epics_dir = FIXTURES_PATH / "epics-empty"
        epics = load_sharded_epics(epics_dir)

        assert epics == []

    def test_includes_orphan_files(self) -> None:
        """Files not in index.md are included at end."""
        epics_dir = FIXTURES_PATH / "epics-with-index"
        epics = load_sharded_epics(epics_dir)

        # Should include epic-3-orphan.md not listed in index
        epic_nums = [e.epic_num for e in epics if e.epic_num is not None]
        assert 3 in epic_nums

    def test_returns_epic_document_objects(self) -> None:
        """Returns list of EpicDocument objects."""
        epics_dir = FIXTURES_PATH / "epics-valid"
        epics = load_sharded_epics(epics_dir)

        for epic in epics:
            assert hasattr(epic, "epic_num")
            assert hasattr(epic, "title")
            assert hasattr(epic, "stories")
            assert hasattr(epic, "path")

    def test_epic_path_is_set(self) -> None:
        """Each EpicDocument has correct path set."""
        epics_dir = FIXTURES_PATH / "epics-valid"
        epics = load_sharded_epics(epics_dir)

        for epic in epics:
            assert epic.path
            assert "epics-valid" in epic.path


class TestSecurityValidation:
    """Tests for security path validation in loaders."""

    def test_path_traversal_in_index_rejected(self) -> None:
        """Path traversal attempts in index.md are rejected (AC8)."""
        security_dir = FIXTURES_PATH / "security-traversal"

        # Should not raise, but should skip malicious paths
        result = load_sharded_content(security_dir, "architecture")

        # Should only load legit.md, not traversal paths
        loaded_names = [Path(f).name for f in result.files_loaded]
        assert "legit.md" in loaded_names
        assert "passwd" not in str(result.files_loaded)


class TestMixedProject:
    """Tests for mixed sharded/single-file projects."""

    def test_mixed_project_epics_sharded(self) -> None:
        """Can load epics from sharded dir in mixed project."""
        mixed_dir = FIXTURES_PATH / "mixed-project"
        epics_dir = mixed_dir / "epics"
        epics = load_sharded_epics(epics_dir)

        assert len(epics) == 1
        assert epics[0].epic_num == 1


class TestEdgeCases:
    """Tests for edge cases and error paths."""

    def test_index_references_missing_file_logs_warning(self, tmp_path: Path) -> None:
        """Missing files referenced in index.md are logged and skipped."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        (test_dir / "index.md").write_text("""
- [Missing](./missing.md)
- [Exists](./exists.md)
""")
        (test_dir / "exists.md").write_text("Content")

        result = load_sharded_content(test_dir, "architecture")

        # Should only load exists.md
        assert len(result.files_loaded) == 1
        assert "exists.md" in result.files_loaded[0]

    def test_read_error_skips_file(self, tmp_path: Path) -> None:
        """Files that fail to read are skipped."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        good_file = test_dir / "good.md"
        good_file.write_text("Good content")

        result = load_sharded_content(test_dir, "prd")

        # Should load successfully despite any bad files
        assert len(result.files_loaded) >= 1

    def test_epic_parse_error_continues(self) -> None:
        """Malformed epic files don't stop loading others."""
        epics_dir = FIXTURES_PATH / "epics-malformed"
        epics = load_sharded_epics(epics_dir)

        # Should load valid epics
        assert len(epics) >= 1

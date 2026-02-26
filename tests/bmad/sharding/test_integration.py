"""Integration tests for sharded documentation support.

Tests the complete flow from detection through loading to state reading,
covering all acceptance criteria from the story.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bmad_assist.bmad.sharding import (
    DuplicateEpicError,
    load_sharded_content,
    load_sharded_epics,
    resolve_doc_path,
)
from bmad_assist.bmad.state_reader import read_project_state

# Fixtures path
FIXTURES_PATH = Path(__file__).parent.parent.parent / "fixtures" / "sharding"


class TestAC1_DetectShardedPattern:
    """AC1: Detect sharded documentation pattern."""

    def test_detects_single_file(self, tmp_path: Path) -> None:
        """Detects single file pattern for docs/epics.md."""
        single_file = tmp_path / "epics.md"
        single_file.touch()

        path, is_sharded = resolve_doc_path(tmp_path, "epics")

        assert path == single_file
        assert is_sharded is False

    def test_detects_sharded_directory(self, tmp_path: Path) -> None:
        """Detects sharded directory pattern for docs/epics/."""
        sharded_dir = tmp_path / "epics"
        sharded_dir.mkdir()

        path, is_sharded = resolve_doc_path(tmp_path, "epics")

        assert path == sharded_dir
        assert is_sharded is True

    def test_detects_non_existent(self, tmp_path: Path) -> None:
        """Returns default single-file pattern when neither exists."""
        path, is_sharded = resolve_doc_path(tmp_path, "epics")

        assert path == tmp_path / "epics.md"
        assert is_sharded is False


class TestAC2_LoadShardedEpics:
    """AC2: Load epics from sharded directory."""

    def test_loads_all_epics_from_sharded_dir(self) -> None:
        """Loads all epic files from sharded directory."""
        epics_dir = FIXTURES_PATH / "epics-valid"
        epics = load_sharded_epics(epics_dir)

        assert len(epics) == 3
        epic_nums = [e.epic_num for e in epics if e.epic_num is not None]
        assert set(epic_nums) == {1, 2, 10}

    def test_epics_sorted_numerically(self) -> None:
        """Epics sorted numerically: 1, 2, 10 (not 1, 10, 2)."""
        epics_dir = FIXTURES_PATH / "epics-valid"
        epics = load_sharded_epics(epics_dir)

        epic_nums = [e.epic_num for e in epics if e.epic_num is not None]
        assert epic_nums == [1, 2, 10]

    def test_stories_collected_from_all_epics(self) -> None:
        """Stories from all epics are collected."""
        epics_dir = FIXTURES_PATH / "epics-valid"
        epics = load_sharded_epics(epics_dir)

        all_stories = []
        for epic in epics:
            all_stories.extend(epic.stories)

        # epic-1 has 2 stories, epic-2 has 2 stories, epic-10 has 1 story
        assert len(all_stories) >= 3


class TestAC3_IndexGuidedLoading:
    """AC3: Support index.md guided loading."""

    def test_loads_in_index_order(self) -> None:
        """Loads epics in order specified by index.md."""
        epics_dir = FIXTURES_PATH / "epics-with-index"
        epics = load_sharded_epics(epics_dir)

        # Index specifies: epic-2 before epic-1
        assert len(epics) >= 2
        # First should be epic-2 (per index order)
        assert epics[0].epic_num == 2
        # Second should be epic-1 (per index order)
        assert epics[1].epic_num == 1

    def test_orphan_files_appended(self) -> None:
        """Files not in index.md are appended at end."""
        epics_dir = FIXTURES_PATH / "epics-with-index"
        epics = load_sharded_epics(epics_dir)

        # epic-3-orphan.md is not in index
        epic_nums = [e.epic_num for e in epics if e.epic_num is not None]
        assert 3 in epic_nums  # Orphan should be included


class TestAC5_TestFixturesExist:
    """AC5: Test fixtures include sharded examples."""

    def test_epics_valid_fixture_exists(self) -> None:
        """epics-valid/ fixture directory exists."""
        assert (FIXTURES_PATH / "epics-valid").is_dir()

    def test_architecture_valid_fixture_exists(self) -> None:
        """architecture-valid/ fixture directory exists."""
        assert (FIXTURES_PATH / "architecture-valid").is_dir()

    def test_prd_valid_fixture_exists(self) -> None:
        """prd-valid/ fixture directory exists."""
        assert (FIXTURES_PATH / "prd-valid").is_dir()

    def test_ux_no_index_fixture_exists(self) -> None:
        """ux-no-index/ fixture directory exists."""
        assert (FIXTURES_PATH / "ux-no-index").is_dir()

    def test_security_traversal_fixture_exists(self) -> None:
        """security-traversal/ fixture directory exists."""
        assert (FIXTURES_PATH / "security-traversal").is_dir()


class TestAC6_BackwardsCompatibility:
    """AC6: Backwards compatibility with single-file pattern."""

    def test_single_file_still_works(self, tmp_path: Path) -> None:
        """Single-file epics.md pattern works exactly as before."""
        # Create single-file epics.md
        epics_file = tmp_path / "epics.md"
        epics_file.write_text("""---
epic_num: 1
title: Test Epic
---

# Epic 1: Test

## Story 1.1: Setup
**Status:** done
""")
        state = read_project_state(tmp_path)

        assert len(state.epics) == 1
        assert len(state.all_stories) == 1
        assert state.all_stories[0].number == "1.1"


class TestAC7_ErrorHandling:
    """AC7: Error handling for edge cases."""

    def test_empty_directory_returns_empty_list(self) -> None:
        """Empty sharded directory returns empty result with warning."""
        epics_dir = FIXTURES_PATH / "epics-empty"
        epics = load_sharded_epics(epics_dir)

        assert epics == []

    def test_duplicate_epic_id_raises_error(self) -> None:
        """Duplicate epic_id raises DuplicateEpicError."""
        epics_dir = FIXTURES_PATH / "epics-duplicate"

        with pytest.raises(DuplicateEpicError, match="Duplicate epic_id 1"):
            load_sharded_epics(epics_dir)

    def test_malformed_files_skipped(self) -> None:
        """Malformed epic files are skipped, not crash."""
        epics_dir = FIXTURES_PATH / "epics-malformed"
        epics = load_sharded_epics(epics_dir)

        # Should load epic-1-valid.md at minimum
        assert len(epics) >= 1


class TestAC8_SecurityPathTraversal:
    """AC8: Security - path traversal prevention."""

    def test_path_traversal_rejected(self) -> None:
        """Path traversal attempts in index.md are rejected."""
        security_dir = FIXTURES_PATH / "security-traversal"

        # Should not raise, but should skip malicious paths
        result = load_sharded_content(security_dir, "architecture")

        # Should only load legit.md, not traversal paths
        loaded_names = [Path(f).name for f in result.files_loaded]
        assert "legit.md" in loaded_names
        # Verify no suspicious paths
        for path in result.files_loaded:
            assert "passwd" not in path
            assert ".." not in path


class TestPrecedenceRule:
    """Precedence rule for mixed patterns - sharded wins over single file."""

    def test_sharded_dir_takes_precedence(self, tmp_path: Path) -> None:
        """Sharded directory takes precedence when both exist."""
        # Create both patterns
        single_file = tmp_path / "epics.md"
        single_file.write_text("""---
epic_num: 1
title: Single File Epic
---

# Epic 1: From Single File

## Story 1.1: Single
**Status:** done
""")
        sharded_dir = tmp_path / "epics"
        sharded_dir.mkdir()
        (sharded_dir / "epic-99-sharded.md").write_text("""---
epic_num: 99
title: Sharded Epic
---

# Epic 99: From Sharded
""")

        # Verify precedence - sharded directory wins
        path, is_sharded = resolve_doc_path(tmp_path, "epics")
        assert path == sharded_dir
        assert is_sharded is True

        # Verify state reader uses sharded directory
        state = read_project_state(tmp_path)
        assert len(state.epics) == 1
        assert state.epics[0].epic_num == 99  # From sharded, not 1


class TestAC10_LoadShardedArchitecture:
    """AC10: Load Architecture from sharded directory."""

    def test_loads_architecture_files(self) -> None:
        """Loads architecture files from sharded directory."""
        arch_dir = FIXTURES_PATH / "architecture-valid"
        result = load_sharded_content(arch_dir, "architecture")

        assert len(result.files_loaded) == 3
        assert result.content  # Non-empty

    def test_architecture_order_from_index(self) -> None:
        """Architecture files loaded in index.md order."""
        arch_dir = FIXTURES_PATH / "architecture-valid"
        result = load_sharded_content(arch_dir, "architecture")

        # Verify order matches index.md: project-context, core-decisions, impl-patterns
        loaded_names = [Path(f).name for f in result.files_loaded]
        assert loaded_names[0] == "project-context.md"
        assert loaded_names[1] == "core-decisions.md"
        assert loaded_names[2] == "implementation-patterns.md"


class TestAC11_LoadShardedPRD:
    """AC11: Load PRD from sharded directory."""

    def test_loads_prd_files(self) -> None:
        """Loads PRD files from sharded directory."""
        prd_dir = FIXTURES_PATH / "prd-valid"
        result = load_sharded_content(prd_dir, "prd")

        assert len(result.files_loaded) >= 2
        assert result.content


class TestAC12_LoadShardedUX:
    """AC12: Load UX from sharded directory."""

    def test_loads_ux_alphabetically_without_index(self) -> None:
        """Loads UX files alphabetically when no index.md."""
        ux_dir = FIXTURES_PATH / "ux-no-index"
        result = load_sharded_content(ux_dir, "ux")

        assert len(result.files_loaded) == 2
        # Alphabetical: design-system before wireframes
        loaded_names = [Path(f).name for f in result.files_loaded]
        assert loaded_names[0] == "design-system.md"
        assert loaded_names[1] == "wireframes.md"


class TestAC13_GenericShardedLoading:
    """AC13: Generic sharded loading supports any document type."""

    def test_load_with_architecture_type(self) -> None:
        """load_sharded_content works with architecture type."""
        arch_dir = FIXTURES_PATH / "architecture-valid"
        result = load_sharded_content(arch_dir, "architecture")
        assert len(result.files_loaded) >= 1

    def test_load_with_prd_type(self) -> None:
        """load_sharded_content works with prd type."""
        prd_dir = FIXTURES_PATH / "prd-valid"
        result = load_sharded_content(prd_dir, "prd")
        assert len(result.files_loaded) >= 1

    def test_load_with_ux_type(self) -> None:
        """load_sharded_content works with ux type."""
        ux_dir = FIXTURES_PATH / "ux-no-index"
        result = load_sharded_content(ux_dir, "ux")
        assert len(result.files_loaded) >= 1


class TestMixedProjectIntegration:
    """Integration tests for mixed sharded/single-file projects."""

    def test_mixed_project_loads_correctly(self) -> None:
        """Mixed project with some sharded, some single-file."""
        mixed_dir = FIXTURES_PATH / "mixed-project"

        # Epics should load from sharded directory
        epics_path, epics_sharded = resolve_doc_path(mixed_dir, "epics")
        assert epics_sharded is True
        epics = load_sharded_epics(epics_path)
        assert len(epics) == 1

        # Architecture should load from single file
        arch_path, arch_sharded = resolve_doc_path(mixed_dir, "architecture")
        assert arch_sharded is False
        assert arch_path.name == "architecture.md"

        # PRD should load from single file
        prd_path, prd_sharded = resolve_doc_path(mixed_dir, "prd")
        assert prd_sharded is False
        assert prd_path.name == "prd.md"


class TestStateReaderShardedIntegration:
    """Integration tests for state_reader with sharded epics."""

    def test_read_project_state_with_sharded_epics(self, tmp_path: Path) -> None:
        """read_project_state works with sharded epics directory."""
        # Create sharded epics directory
        epics_dir = tmp_path / "epics"
        epics_dir.mkdir()

        (epics_dir / "epic-1-first.md").write_text("""---
epic_num: 1
title: First Epic
---

# Epic 1: First

## Story 1.1: Setup
**Status:** done

## Story 1.2: Config
**Status:** in-progress
""")
        (epics_dir / "epic-2-second.md").write_text("""---
epic_num: 2
title: Second Epic
---

# Epic 2: Second

## Story 2.1: Feature
**Status:** backlog
""")

        state = read_project_state(tmp_path)

        assert len(state.epics) == 2
        assert len(state.all_stories) == 3
        assert state.current_epic == 1
        assert state.current_story == "1.2"
        assert "1.1" in state.completed_stories

    def test_sharded_epic_paths_are_correct(self, tmp_path: Path) -> None:
        """Each epic has correct file path pointing to its shard."""
        epics_dir = tmp_path / "epics"
        epics_dir.mkdir()

        (epics_dir / "epic-1-test.md").write_text("""---
epic_num: 1
title: Test
---

# Epic 1: Test

## Story 1.1: Test
**Status:** done
""")

        state = read_project_state(tmp_path)

        assert len(state.epics) == 1
        assert "epic-1-test.md" in state.epics[0].path

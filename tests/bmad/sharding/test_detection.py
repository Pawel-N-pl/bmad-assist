"""Tests for sharding detection module."""

from __future__ import annotations

from pathlib import Path

from bmad_assist.bmad.sharding.detection import is_sharded_path, resolve_doc_path


class TestIsShardedPath:
    """Tests for is_sharded_path function."""

    def test_directory_is_sharded(self, tmp_path: Path) -> None:
        """Existing directory is considered sharded."""
        dir_path = tmp_path / "epics"
        dir_path.mkdir()

        assert is_sharded_path(dir_path) is True

    def test_file_is_not_sharded(self, tmp_path: Path) -> None:
        """Existing file is not considered sharded."""
        file_path = tmp_path / "epics.md"
        file_path.touch()

        assert is_sharded_path(file_path) is False

    def test_nonexistent_path_is_not_sharded(self, tmp_path: Path) -> None:
        """Non-existent path is not considered sharded."""
        missing = tmp_path / "missing"

        assert is_sharded_path(missing) is False

    def test_symlink_to_directory_is_sharded(self, tmp_path: Path) -> None:
        """Symlink pointing to directory is considered sharded."""
        target = tmp_path / "real-dir"
        target.mkdir()
        symlink = tmp_path / "linked-dir"
        symlink.symlink_to(target)

        assert is_sharded_path(symlink) is True


class TestResolveDocPath:
    """Tests for resolve_doc_path function."""

    def test_single_file_exists(self, tmp_path: Path) -> None:
        """Returns single file when it exists."""
        single_file = tmp_path / "epics.md"
        single_file.touch()

        path, is_sharded = resolve_doc_path(tmp_path, "epics")

        assert path == single_file
        assert is_sharded is False

    def test_sharded_dir_exists(self, tmp_path: Path) -> None:
        """Returns sharded directory when only it exists."""
        sharded_dir = tmp_path / "epics"
        sharded_dir.mkdir()

        path, is_sharded = resolve_doc_path(tmp_path, "epics")

        assert path == sharded_dir
        assert is_sharded is True

    def test_both_exist_sharded_dir_wins_if_not_empty(self, tmp_path: Path) -> None:
        """Sharded directory takes precedence when it contains files."""
        single_file = tmp_path / "epics.md"
        single_file.touch()
        sharded_dir = tmp_path / "epics"
        sharded_dir.mkdir()
        (sharded_dir / "epic-1.md").touch()  # Add a shard

        path, is_sharded = resolve_doc_path(tmp_path, "epics")

        assert path == sharded_dir
        assert is_sharded is True

    def test_both_exist_empty_dir_loses(self, tmp_path: Path) -> None:
        """Single file takes precedence if sharded directory is empty."""
        single_file = tmp_path / "epics.md"
        single_file.touch()
        sharded_dir = tmp_path / "epics"
        sharded_dir.mkdir()

        path, is_sharded = resolve_doc_path(tmp_path, "epics")

        assert path == single_file
        assert is_sharded is False

    def test_neither_exists_defaults_to_single(self, tmp_path: Path) -> None:
        """Defaults to single-file pattern when neither exists."""
        path, is_sharded = resolve_doc_path(tmp_path, "epics")

        assert path == tmp_path / "epics.md"
        assert is_sharded is False

    def test_works_with_architecture(self, tmp_path: Path) -> None:
        """Works for architecture doc type."""
        arch_dir = tmp_path / "architecture"
        arch_dir.mkdir()

        path, is_sharded = resolve_doc_path(tmp_path, "architecture")

        assert path == arch_dir
        assert is_sharded is True

    def test_works_with_prd(self, tmp_path: Path) -> None:
        """Works for prd doc type."""
        prd_file = tmp_path / "prd.md"
        prd_file.touch()

        path, is_sharded = resolve_doc_path(tmp_path, "prd")

        assert path == prd_file
        assert is_sharded is False

    def test_works_with_ux(self, tmp_path: Path) -> None:
        """Works for ux doc type."""
        ux_dir = tmp_path / "ux"
        ux_dir.mkdir()

        path, is_sharded = resolve_doc_path(tmp_path, "ux")

        assert path == ux_dir
        assert is_sharded is True

    def test_case_sensitive_doc_name(self, tmp_path: Path) -> None:
        """Doc name matching is case-sensitive."""
        (tmp_path / "Epics.md").touch()

        # Looking for "epics" should not find "Epics.md"
        path, is_sharded = resolve_doc_path(tmp_path, "epics")

        assert path == tmp_path / "epics.md"  # Default path, doesn't exist
        assert is_sharded is False

    def test_empty_sharded_dir_is_sharded(self, tmp_path: Path) -> None:
        """Empty directory is still considered sharded."""
        empty_dir = tmp_path / "epics"
        empty_dir.mkdir()

        path, is_sharded = resolve_doc_path(tmp_path, "epics")

        assert path == empty_dir
        assert is_sharded is True

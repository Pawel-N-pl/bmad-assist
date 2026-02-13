"""Tests for tree walker."""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bmad_assist.core.project_tree.config import ProjectTreeConfig
from bmad_assist.core.project_tree.gitignore import GitignoreParser
from bmad_assist.core.project_tree.types import TreeEntry
from bmad_assist.core.project_tree.walker import TreeWalker


class TestTreeWalker:
    """Test cases for TreeWalker."""

    def test_basic_directory_traversal(self, tmp_path: Path) -> None:
        """Test basic directory traversal."""
        # Create structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("main")
        (tmp_path / "src" / "utils.py").write_text("utils")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text("test")

        config = ProjectTreeConfig(tree_budget=1000)
        gitignore = GitignoreParser(tmp_path)
        walker = TreeWalker(tmp_path, config, gitignore)

        entries = list(walker.walk())

        # Should find all directories and files
        names = [e.name for e in entries]
        assert "src" in names
        assert "tests" in names
        assert "main.py" in names
        assert "utils.py" in names
        assert "test_main.py" in names

    def test_file_limiting(self, tmp_path: Path) -> None:
        """Test file limiting (20 max, sorted by mtime)."""
        # Create directory with 25 files
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        for i in range(25):
            f = src_dir / f"file{i:02d}.py"
            f.write_text(f"content {i}")
            # Set different modification times
            os.utime(f, (i * 1000, i * 1000))

        config = ProjectTreeConfig(tree_budget=1000, max_files_per_dir=20)
        gitignore = GitignoreParser(tmp_path)
        walker = TreeWalker(tmp_path, config, gitignore)

        entries = list(walker.walk())

        # Count files in src directory
        src_files = [e for e in entries if not e.is_dir and e.path.parent == src_dir]

        # Should have 20 files + 1 truncation indicator
        assert len(src_files) == 20

        # Should have truncation indicator
        truncation = [e for e in entries if "(+5 more)" in e.name]
        assert len(truncation) == 1

    def test_depth_limiting(self, tmp_path: Path) -> None:
        """Test depth limiting (100 max)."""
        # Create deep structure
        current = tmp_path
        for i in range(105):
            current = current / f"level{i}"
            current.mkdir()
            (current / "file.txt").write_text("x")

        config = ProjectTreeConfig(tree_budget=1000, max_depth=100)
        gitignore = GitignoreParser(tmp_path)
        walker = TreeWalker(tmp_path, config, gitignore)

        entries = list(walker.walk())

        # Max depth entries should be around 100 (plus some root level)
        max_depth_found = max((e.depth for e in entries), default=0)
        assert max_depth_found <= 100

    def test_symlink_not_followed(self, tmp_path: Path) -> None:
        """Test that symlinks are not followed (nofollow)."""
        # Create structure with symlink
        (tmp_path / "real_dir").mkdir()
        (tmp_path / "real_dir" / "file.txt").write_text("content")

        # Create symlink to directory
        link_dir = tmp_path / "link_dir"
        link_dir.symlink_to(tmp_path / "real_dir")

        config = ProjectTreeConfig(tree_budget=1000)
        gitignore = GitignoreParser(tmp_path)
        walker = TreeWalker(tmp_path, config, gitignore)

        entries = list(walker.walk())

        # Symlink should appear as a file, not traversed
        link_entries = [e for e in entries if e.name == "link_dir"]
        assert len(link_entries) == 1
        assert not link_entries[0].is_dir  # Symlinks appear as files

    def test_gitignore_respect(self, tmp_path: Path) -> None:
        """Test that gitignore patterns are respected."""
        # Create .gitignore
        (tmp_path / ".gitignore").write_text("ignored/\n")

        # Create structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("main")
        (tmp_path / "ignored").mkdir()
        (tmp_path / "ignored" / "secret.txt").write_text("secret")

        config = ProjectTreeConfig(tree_budget=1000)
        gitignore = GitignoreParser(tmp_path)
        walker = TreeWalker(tmp_path, config, gitignore)

        entries = list(walker.walk())

        names = [e.name for e in entries]
        assert "src" in names
        assert "main.py" in names
        assert "ignored" not in names
        assert "secret.txt" not in names

    @pytest.mark.skipif(
        os.name == "nt",
        reason="chmod 000 doesn't work on Windows"
    )
    def test_permission_error_handling(self, tmp_path: Path) -> None:
        """Test graceful handling of permission errors."""
        # Create structure with inaccessible directory
        (tmp_path / "accessible").mkdir()
        (tmp_path / "accessible" / "file.txt").write_text("content")

        no_access = tmp_path / "no_access"
        no_access.mkdir()
        (no_access / "secret.txt").write_text("secret")
        os.chmod(no_access, 0o000)

        try:
            config = ProjectTreeConfig(tree_budget=1000)
            gitignore = GitignoreParser(tmp_path)
            walker = TreeWalker(tmp_path, config, gitignore)

            # Should not raise exception
            entries = list(walker.walk())

            # Accessible directory should be traversed
            names = [e.name for e in entries]
            assert "accessible" in names

        finally:
            # Restore permissions for cleanup
            os.chmod(no_access, 0o755)

    def test_circular_symlink_protection(self, tmp_path: Path) -> None:
        """Test protection against circular symlinks."""
        # Create circular symlinks: A -> B, B -> A
        dir_a = tmp_path / "A"
        dir_b = tmp_path / "B"
        dir_a.mkdir()
        dir_b.mkdir()

        link_a = dir_a / "link_to_b"
        link_b = dir_b / "link_to_a"
        link_a.symlink_to(dir_b)
        link_b.symlink_to(dir_a)

        config = ProjectTreeConfig(tree_budget=1000)
        gitignore = GitignoreParser(tmp_path)
        walker = TreeWalker(tmp_path, config, gitignore)

        # Should complete without infinite loop
        entries = list(walker.walk())

        # Should find both directories but not follow symlinks
        names = [e.name for e in entries]
        assert "A" in names
        assert "B" in names

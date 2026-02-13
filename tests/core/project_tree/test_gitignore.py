"""Tests for gitignore parser."""

from pathlib import Path

import pytest

from bmad_assist.core.project_tree.gitignore import GitignoreParser


class TestGitignoreParser:
    """Test cases for GitignoreParser."""

    def test_basic_pattern_matching(self, tmp_path: Path) -> None:
        """Test basic pattern matching (*.pyc, node_modules/)."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\nnode_modules/\n")

        parser = GitignoreParser(tmp_path)

        assert parser.is_ignored(tmp_path / "test.pyc")
        assert parser.is_ignored(tmp_path / "node_modules")
        assert parser.is_ignored(tmp_path / "node_modules" / "express" / "index.js")
        assert not parser.is_ignored(tmp_path / "test.py")

    def test_negation_patterns(self, tmp_path: Path) -> None:
        """Test negation patterns (!important.pyc)."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n!important.pyc\n")

        parser = GitignoreParser(tmp_path)

        # Note: pathspec handles negation internally
        # important.pyc should NOT be ignored due to negation
        assert not parser.is_ignored(tmp_path / "important.pyc")
        assert parser.is_ignored(tmp_path / "other.pyc")

    def test_directory_patterns(self, tmp_path: Path) -> None:
        """Test directory patterns (trailing slash)."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("build/\n")

        parser = GitignoreParser(tmp_path)

        # Directory should be ignored
        (tmp_path / "build").mkdir()
        assert parser.is_ignored(tmp_path / "build")

    def test_nested_gitignore_files(self, tmp_path: Path) -> None:
        """Test nested .gitignore files with stacked rules."""
        # Root .gitignore
        (tmp_path / ".gitignore").write_text("*.pyc\n")

        # Child directory with its own .gitignore
        child_dir = tmp_path / "child"
        child_dir.mkdir()
        (child_dir / ".gitignore").write_text("!important.pyc\n")

        parser = GitignoreParser(tmp_path)

        # Parent pattern applies to child
        assert parser.is_ignored(child_dir / "test.pyc")

        # Child negation should work
        assert not parser.is_ignored(child_dir / "important.pyc")

    def test_deep_nesting(self, tmp_path: Path) -> None:
        """Test 3+ levels of nested .gitignore files."""
        (tmp_path / ".gitignore").write_text("*.log\n")

        level1 = tmp_path / "level1"
        level1.mkdir()
        (level1 / ".gitignore").write_text("*.tmp\n")

        level2 = level1 / "level2"
        level2.mkdir()
        (level2 / ".gitignore").write_text("*.bak\n")

        level3 = level2 / "level3"
        level3.mkdir()

        parser = GitignoreParser(tmp_path)

        # All patterns should apply at deepest level
        assert parser.is_ignored(level3 / "test.log")
        assert parser.is_ignored(level3 / "test.tmp")
        assert parser.is_ignored(level3 / "test.bak")

    def test_child_only_patterns(self, tmp_path: Path) -> None:
        """Test that child patterns don't affect parent directories."""
        (tmp_path / ".gitignore").write_text("*.pyc\n")

        child = tmp_path / "child"
        child.mkdir()
        (child / ".gitignore").write_text("*.tmp\n")

        parser = GitignoreParser(tmp_path)

        # Child pattern should not affect parent
        assert not parser.is_ignored(tmp_path / "test.tmp")
        assert parser.is_ignored(child / "test.tmp")

    def test_fallback_defaults(self, tmp_path: Path) -> None:
        """Test fallback defaults when no .gitignore exists."""
        parser = GitignoreParser(tmp_path)

        # Default exclusions should apply
        assert parser.is_ignored(tmp_path / "node_modules")
        assert parser.is_ignored(tmp_path / "__pycache__")
        assert parser.is_ignored(tmp_path / ".git")
        assert parser.is_ignored(tmp_path / "test.pyc")
        assert not parser.is_ignored(tmp_path / "src")

    def test_case_sensitivity(self, tmp_path: Path) -> None:
        """Test case sensitivity handling."""
        (tmp_path / ".gitignore").write_text("*.PYC\n")

        parser = GitignoreParser(tmp_path)

        # Gitignore patterns are typically case-sensitive on case-sensitive filesystems
        # pathspec should handle this correctly
        assert parser.is_ignored(tmp_path / "test.PYC")

    def test_empty_gitignore(self, tmp_path: Path) -> None:
        """Test handling of empty .gitignore file."""
        (tmp_path / ".gitignore").write_text("")

        parser = GitignoreParser(tmp_path)

        # Should fall back to defaults
        assert parser.is_ignored(tmp_path / "node_modules")

    def test_path_outside_project(self, tmp_path: Path) -> None:
        """Test that paths outside project root are treated as ignored."""
        parser = GitignoreParser(tmp_path)

        outside_path = Path("/etc/passwd")
        assert parser.is_ignored(outside_path)

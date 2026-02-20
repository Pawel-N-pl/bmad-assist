"""Tests for tree formatter."""

from pathlib import Path

from bmad_assist.core.project_tree.formatter import TreeFormatter
from bmad_assist.core.project_tree.types import TreeEntry


class TestTreeFormatter:
    """Test cases for TreeFormatter."""

    def test_xml_format_validation(self, tmp_path: Path) -> None:
        """Test XML format validation."""
        formatter = TreeFormatter(tmp_path)

        entries = [
            TreeEntry(tmp_path / "src", "src", True, 1000.0, 0),
            TreeEntry(tmp_path / "src" / "main.py", "main.py", False, 1000.0, 1),
        ]

        result = formatter.format_tree(entries, 1000)

        # Check basic XML structure
        assert result.startswith("<project-tree>")
        assert result.endswith("</project-tree>")
        assert "src/" in result
        assert "main.py" in result

    def test_indentation_correctness(self, tmp_path: Path) -> None:
        """Test indentation correctness."""
        formatter = TreeFormatter(tmp_path)

        entries = [
            TreeEntry(tmp_path / "src", "src", True, 1000.0, 0),
            TreeEntry(tmp_path / "src" / "core", "core", True, 1000.0, 1),
            TreeEntry(tmp_path / "src" / "core" / "config.py", "config.py", False, 1000.0, 2),
        ]

        result = formatter.format_tree(entries, 1000)

        lines = result.split("\n")
        # Find lines with content
        content_lines = [l for l in lines if l.strip() and not l.strip().startswith("<")]

        # Check indentation (2 spaces per level)
        src_line = [l for l in content_lines if "src/" in l][0]
        core_line = [l for l in content_lines if "core/" in l][0]
        config_line = [l for l in content_lines if "config.py" in l][0]

        assert src_line.startswith("src/")  # 0 indent
        assert core_line.startswith("  core/")  # 2 spaces
        assert config_line.startswith("    config.py")  # 4 spaces

    def test_token_budget_truncation(self, tmp_path: Path) -> None:
        """Test token budget enforcement (truncation)."""
        formatter = TreeFormatter(tmp_path)

        # Create many entries to exceed budget
        entries = []
        for i in range(100):
            entries.append(
                TreeEntry(tmp_path / f"file{i}.txt", f"file{i}.txt", False, 1000.0, 0)
            )

        # Small budget
        result = formatter.format_tree(entries, 100)

        # Should be truncated
        assert "[truncated]" in result
        assert result.endswith("</project-tree>")

    def test_truncation_indicator(self, tmp_path: Path) -> None:
        """Test '(+N more)' indicator from walker is preserved."""
        formatter = TreeFormatter(tmp_path)

        entries = [
            TreeEntry(tmp_path / "src", "src", True, 1000.0, 0),
            TreeEntry(tmp_path / "src" / "(+5 more)", "(+5 more)", False, 0.0, 1),
        ]

        result = formatter.format_tree(entries, 1000)

        assert "(+5 more)" in result

    def test_empty_directory_handling(self, tmp_path: Path) -> None:
        """Test empty directory handling."""
        formatter = TreeFormatter(tmp_path)

        # Just root directory with no entries
        entries: list[TreeEntry] = []

        result = formatter.format_tree(entries, 1000)

        assert result == "<project-tree>\n</project-tree>"

    def test_xml_escaping_for_filenames(self, tmp_path: Path) -> None:
        """Test XML escaping for filenames with special characters."""
        formatter = TreeFormatter(tmp_path)

        entries = [
            TreeEntry(tmp_path / "foo&bar.py", "foo&bar.py", False, 1000.0, 0),
            TreeEntry(tmp_path / "test<old>.py", "test<old>.py", False, 1000.0, 0),
            TreeEntry(tmp_path / 'my"file".py', 'my"file".py', False, 1000.0, 0),
        ]

        result = formatter.format_tree(entries, 1000)

        # Check proper escaping
        assert "foo&amp;bar.py" in result
        assert "test&lt;old&gt;.py" in result
        assert "my&quot;file&quot;.py" in result

        # Original characters should not be present
        assert "foo&bar.py" not in result.replace("&amp;", "")
        assert "test<old>.py" not in result.replace("&lt;", "").replace("&gt;", "")

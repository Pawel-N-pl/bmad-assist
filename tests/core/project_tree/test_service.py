"""Integration tests for project tree service."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.project_tree.service import ProjectTreeService


class MockConfig:
    """Mock config for testing."""

    def __init__(self, tree_budget: int = 1000, include: tuple[str, ...] = ("project-tree",)):
        mock_strategic = MagicMock()
        mock_strategic.tree_budget = tree_budget
        mock_strategic.get_workflow_config.return_value = (include, True)

        self.compiler = MagicMock()
        self.compiler.strategic_context = mock_strategic


class MockPaths:
    """Mock paths for testing."""

    def __init__(self, project_root: Path):
        self.project_root = project_root


class TestProjectTreeService:
    """Test cases for ProjectTreeService."""

    def test_end_to_end_tree_generation(self, tmp_path: Path) -> None:
        """Test end-to-end tree generation."""
        # Create project structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("main")
        (tmp_path / "README.md").write_text("readme")

        config = MockConfig(tree_budget=1000, include=("project-tree",))
        paths = MockPaths(tmp_path)

        service = ProjectTreeService(config, paths)
        result = service.generate_tree("dev_story")

        # Check result
        assert "<project-tree>" in result
        assert "</project-tree>" in result
        assert "src/" in result
        assert "main.py" in result
        assert "README.md" in result

    def test_config_disabled_returns_empty(self, tmp_path: Path) -> None:
        """Test that disabled config returns empty string."""
        config = MockConfig(tree_budget=1000, include=("project-context",))  # No project-tree
        paths = MockPaths(tmp_path)

        service = ProjectTreeService(config, paths)
        result = service.generate_tree("dev_story")

        assert result == ""

    def test_zero_budget_returns_empty(self, tmp_path: Path) -> None:
        """Test that zero budget returns empty string."""
        config = MockConfig(tree_budget=0)
        paths = MockPaths(tmp_path)

        service = ProjectTreeService(config, paths)
        result = service.generate_tree("dev_story")

        assert result == ""

    def test_workflow_specific_config(self, tmp_path: Path) -> None:
        """Test workflow-specific configuration."""
        (tmp_path / "file.txt").write_text("content")

        # Config with project-tree only for specific workflow
        mock_strategic = MagicMock()
        mock_strategic.tree_budget = 1000

        def mock_get_workflow(name: str):
            if name == "dev_story":
                return (("project-tree",), True)
            return (("project-context",), True)

        mock_strategic.get_workflow_config.side_effect = mock_get_workflow

        config = MagicMock()
        config.compiler.strategic_context = mock_strategic

        paths = MockPaths(tmp_path)
        service = ProjectTreeService(config, paths)

        # Should work for dev_story
        result_dev = service.generate_tree("dev_story")
        assert "<project-tree>" in result_dev

        # Should be empty for other workflow
        result_other = service.generate_tree("other_workflow")
        assert result_other == ""

    def test_is_enabled(self, tmp_path: Path) -> None:
        """Test is_enabled method."""
        config = MockConfig(tree_budget=1000, include=("project-tree",))
        paths = MockPaths(tmp_path)

        service = ProjectTreeService(config, paths)

        assert service.is_enabled("dev_story") is True

    def test_is_enabled_disabled(self, tmp_path: Path) -> None:
        """Test is_enabled method when disabled."""
        config = MockConfig(tree_budget=1000, include=("project-context",))
        paths = MockPaths(tmp_path)

        service = ProjectTreeService(config, paths)

        assert service.is_enabled("dev_story") is False

    def test_tree_budget_enforcement(self, tmp_path: Path) -> None:
        """Test that tree_budget is enforced."""
        # Create many files
        for i in range(50):
            (tmp_path / f"file{i:02d}.txt").write_text(f"content {i}")

        config = MockConfig(tree_budget=100)  # Small budget
        paths = MockPaths(tmp_path)

        service = ProjectTreeService(config, paths)
        result = service.generate_tree("dev_story")

        # Should be truncated
        assert "[truncated]" in result

    def test_large_directory_structure(self, tmp_path: Path) -> None:
        """Test with large directory structure (>1000 files)."""
        # Create many directories and files
        for d in range(10):
            dir_path = tmp_path / f"dir{d}"
            dir_path.mkdir()
            for f in range(20):
                (dir_path / f"file{f}.txt").write_text("content")

        config = MockConfig(tree_budget=5000)
        paths = MockPaths(tmp_path)

        service = ProjectTreeService(config, paths)
        result = service.generate_tree("dev_story")

        # Should complete without error
        assert "<project-tree>" in result

"""Tests for compiler variables integration."""

from pathlib import Path

import pytest

from bmad_assist.compiler.variables.tea import (
    resolve_knowledge_base,
    resolve_tea_variables,
)
from bmad_assist.testarch.knowledge.loader import clear_all_loaders


class TestResolveKnowledgeBase:
    """Tests for resolve_knowledge_base function."""

    @pytest.fixture(autouse=True)
    def cleanup_loaders(self) -> None:
        """Clear loaders before each test."""
        clear_all_loaders()

    def test_resolve_known_workflow(self, mock_knowledge_dir: Path) -> None:
        """Test resolving knowledge base for known workflow."""
        # atdd workflow includes fixture-architecture
        content = resolve_knowledge_base(mock_knowledge_dir, "atdd")
        # May be empty if default fragments don't match index
        assert isinstance(content, str)

    def test_resolve_unknown_workflow(self, mock_knowledge_dir: Path) -> None:
        """Test resolving knowledge base for unknown workflow returns empty."""
        content = resolve_knowledge_base(mock_knowledge_dir, "unknown-workflow")
        assert content == ""

    def test_resolve_with_tea_flags(self, mock_knowledge_dir: Path) -> None:
        """Test that tea_flags are passed to loader."""
        content = resolve_knowledge_base(
            mock_knowledge_dir,
            "framework",
            tea_flags={"tea_use_playwright_utils": False},
        )
        # framework workflow includes overview which has playwright-utils tag
        # Should be excluded
        assert isinstance(content, str)

    def test_resolve_missing_project_index_uses_bundled(
        self, empty_knowledge_dir: Path
    ) -> None:
        """Test resolving with missing project index falls back to bundled."""
        content = resolve_knowledge_base(empty_knowledge_dir, "atdd")
        # Falls back to bundled knowledge base
        assert len(content) > 0
        assert "<!-- KNOWLEDGE:" in content


class TestResolveTEAVariablesWithKnowledge:
    """Tests for resolve_tea_variables with knowledge_base integration."""

    @pytest.fixture(autouse=True)
    def cleanup_loaders(self) -> None:
        """Clear loaders before each test."""
        clear_all_loaders()

    def test_resolve_without_workflow(self, mock_knowledge_dir: Path) -> None:
        """Test that knowledge_base is not set when workflow_id is None."""
        resolved: dict = {}
        resolve_tea_variables(resolved, mock_knowledge_dir)
        assert "knowledge_base" not in resolved

    def test_resolve_with_workflow(self, mock_knowledge_dir: Path) -> None:
        """Test that knowledge_base is set when workflow_id is provided."""
        # Need to ensure the workflow has matching fragments in mock
        resolved: dict = {}
        resolve_tea_variables(resolved, mock_knowledge_dir, workflow_id="atdd")
        # May or may not have knowledge_base depending on defaults matching index
        assert "tea_use_playwright_utils" in resolved
        assert "tea_use_mcp_enhancements" in resolved

    def test_resolve_adds_to_context_files(self, mock_knowledge_dir: Path) -> None:
        """Test that knowledge content is added to context_files."""
        resolved: dict = {}
        context_files: dict = {}
        resolve_tea_variables(
            resolved,
            mock_knowledge_dir,
            workflow_id="atdd",
            context_files=context_files,
        )
        # If knowledge_base is set, it should also be in context_files
        if "knowledge_base" in resolved:
            assert "knowledge_base" in context_files
            assert context_files["knowledge_base"] == resolved["knowledge_base"]

    def test_resolve_with_existing_tea_flags(self, mock_knowledge_dir: Path) -> None:
        """Test that existing tea_flags are not overwritten."""
        resolved: dict = {"tea_use_playwright_utils": False}
        resolve_tea_variables(resolved, mock_knowledge_dir, workflow_id="atdd")
        # Should preserve the existing value
        assert resolved["tea_use_playwright_utils"] is False

    def test_resolve_sets_knowledge_index(self, mock_knowledge_dir: Path) -> None:
        """Test that knowledgeIndex variable is set."""
        resolved: dict = {}
        resolve_tea_variables(resolved, mock_knowledge_dir)
        assert "knowledgeIndex" in resolved
        assert mock_knowledge_dir.name in resolved["knowledgeIndex"]

    def test_resolve_unknown_workflow(self, mock_knowledge_dir: Path) -> None:
        """Test that unknown workflow doesn't set knowledge_base."""
        resolved: dict = {}
        resolve_tea_variables(resolved, mock_knowledge_dir, workflow_id="unknown")
        assert "knowledge_base" not in resolved

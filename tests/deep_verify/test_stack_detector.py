"""Tests for deep_verify/stack_detector.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.deep_verify.stack_detector import (
    VALID_STACKS,
    _collect_project_docs,
    _parse_llm_response,
    clear_cache,
    detect_project_stacks,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the stack detector cache before each test."""
    clear_cache()


class TestParseResponse:
    """Test LLM response parsing."""

    def test_comma_separated(self) -> None:
        assert _parse_llm_response("python, javascript") == ["javascript", "python"]

    def test_no_spaces(self) -> None:
        assert _parse_llm_response("go,rust") == ["go", "rust"]

    def test_single(self) -> None:
        assert _parse_llm_response("python") == ["python"]

    def test_with_markdown_fences(self) -> None:
        assert _parse_llm_response("```\npython, go\n```") == ["go", "python"]

    def test_invalid_stacks_ignored(self) -> None:
        assert _parse_llm_response("python, brainfuck, go") == ["go", "python"]

    def test_empty(self) -> None:
        assert _parse_llm_response("") == []

    def test_extra_whitespace(self) -> None:
        assert _parse_llm_response("  python ,  javascript  ") == ["javascript", "python"]

    def test_quoted_values(self) -> None:
        assert _parse_llm_response('"python", "go"') == ["go", "python"]

    def test_newline_separated(self) -> None:
        assert _parse_llm_response("python\njavascript\ngo") == ["go", "javascript", "python"]

    def test_deduplicates(self) -> None:
        assert _parse_llm_response("python, python, go") == ["go", "python"]


class TestCollectDocs:
    """Test project documentation collection."""

    def test_reads_existing_docs(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "architecture.md").write_text("# Architecture\nTypeScript + Node.js")
        (docs_dir / "project-context.md").write_text("# Context\nUses React")

        result = _collect_project_docs(tmp_path)
        assert "Architecture" in result
        assert "Context" in result

    def test_missing_docs_returns_empty(self, tmp_path: Path) -> None:
        assert _collect_project_docs(tmp_path) == ""

    def test_partial_docs(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "architecture.md").write_text("# Arch\nPython backend")
        # project-context.md missing

        result = _collect_project_docs(tmp_path)
        assert "Python backend" in result


class TestDetectProjectStacks:
    """Test the main detection function."""

    def test_fallback_to_markers(self, tmp_path: Path) -> None:
        """Without config, falls back to marker-based detection."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
        stacks = detect_project_stacks(tmp_path, config=None)
        assert "python" in stacks

    def test_llm_detection(self, tmp_path: Path) -> None:
        """With config and docs, uses LLM detection."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "architecture.md").write_text("# Arch\nTypeScript + Python")

        mock_config = MagicMock()
        mock_config.providers.helper.provider = "claude-sdk"
        mock_config.providers.helper.model = "haiku"
        mock_config.providers.helper.settings_path = None

        mock_result = MagicMock()
        mock_result.stdout = "javascript, python"

        with patch("bmad_assist.providers.get_provider") as mock_gp:
            mock_gp.return_value.invoke.return_value = mock_result
            stacks = detect_project_stacks(tmp_path, config=mock_config)

        assert stacks == ["javascript", "python"]

    def test_llm_failure_falls_back(self, tmp_path: Path) -> None:
        """If LLM fails, falls back to markers."""
        (tmp_path / "package.json").write_text('{"name":"test"}')
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "architecture.md").write_text("# Arch")

        mock_config = MagicMock()
        mock_config.providers.helper.provider = "claude-sdk"
        mock_config.providers.helper.model = "haiku"
        mock_config.providers.helper.settings_path = None

        with patch("bmad_assist.providers.get_provider") as mock_gp:
            mock_gp.return_value.invoke.side_effect = RuntimeError("LLM down")
            stacks = detect_project_stacks(tmp_path, config=mock_config)

        assert "javascript" in stacks  # From marker detection

    def test_caching(self, tmp_path: Path) -> None:
        """Second call returns cached result."""
        (tmp_path / "pyproject.toml").write_text("[project]")

        stacks1 = detect_project_stacks(tmp_path, config=None)
        stacks2 = detect_project_stacks(tmp_path, config=None)
        assert stacks1 == stacks2

    def test_no_helper_config(self, tmp_path: Path) -> None:
        """Config without helper provider skips LLM."""
        mock_config = MagicMock()
        mock_config.providers.helper = None
        (tmp_path / "go.mod").write_text("module example.com")

        stacks = detect_project_stacks(tmp_path, config=mock_config)
        assert "go" in stacks


class TestValidStacks:
    """Validate the VALID_STACKS constant."""

    def test_all_stacks_present(self) -> None:
        expected = {"python", "javascript", "go", "java", "rust", "ruby", "csharp", "cpp", "swift"}
        assert expected == VALID_STACKS

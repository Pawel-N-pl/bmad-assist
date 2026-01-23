"""Tests for antipatterns extraction and file appending."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.antipatterns.extractor import (
    CODE_ANTIPATTERNS_HEADER,
    STORY_ANTIPATTERNS_HEADER,
    append_to_antipatterns_file,
    extract_antipatterns,
)


class TestExtractAntipatterns:
    """Tests for extract_antipatterns function."""

    @pytest.fixture
    def mock_config(self):
        """Create mock config with helper provider."""
        config = MagicMock()
        config.providers.helper.provider = "claude-subprocess"
        config.providers.helper.model = "haiku"
        config.providers.helper.settings_path = None
        return config

    @pytest.fixture
    def synthesis_content_with_issues(self):
        """Sample synthesis content with Issues Verified section."""
        return """
# Validation Synthesis Report

## Issues Verified (by severity)

### Critical
- **Issue**: Missing null check causes crash | **Source**: Validators A, B | **Fix**: Added null guard

### High
- **Issue**: No input validation | **Source**: Validator A | **Fix**: Added schema validation

## Issues Dismissed
- Some dismissed issue
"""

    @pytest.fixture
    def synthesis_content_no_issues(self):
        """Sample synthesis content without Issues Verified section."""
        return """
# Validation Synthesis Report

## Summary
Everything looks good, no issues found.
"""

    def test_extract_valid_yaml(self, mock_config, synthesis_content_with_issues):
        """Test successful extraction with clean YAML response."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = """
story_id: "24-11"
date: "2026-01-22"
issues:
  - severity: critical
    issue: "Missing null check causes crash"
    file: "src/handler.py:42"
    fix: "Added null guard"
  - severity: high
    issue: "No input validation"
    file: "src/api.py:15"
    fix: "Added schema validation"
"""

        with patch("bmad_assist.providers.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = mock_result
            mock_get_provider.return_value = mock_provider

            issues = extract_antipatterns(
                synthesis_content_with_issues,
                epic_id=24,
                story_id="24-11",
                config=mock_config,
            )

        assert len(issues) == 2
        assert issues[0]["severity"] == "critical"
        assert issues[0]["issue"] == "Missing null check causes crash"
        assert issues[1]["severity"] == "high"

    def test_extract_yaml_with_code_fences(self, mock_config, synthesis_content_with_issues):
        """Test extraction when helper returns YAML wrapped in code fences."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = """```yaml
story_id: "24-11"
date: "2026-01-22"
issues:
  - severity: critical
    issue: "Test issue"
    file: "src/foo.py:1"
    fix: "Fixed it"
```"""

        with patch("bmad_assist.providers.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = mock_result
            mock_get_provider.return_value = mock_provider

            issues = extract_antipatterns(
                synthesis_content_with_issues,
                epic_id=24,
                story_id="24-11",
                config=mock_config,
            )

        assert len(issues) == 1
        assert issues[0]["severity"] == "critical"

    def test_extract_empty_synthesis(self, mock_config):
        """Test that empty synthesis content returns empty list."""
        issues = extract_antipatterns(
            synthesis_content="",
            epic_id=24,
            story_id="24-11",
            config=mock_config,
        )
        assert issues == []

    def test_extract_no_issues_verified(self, mock_config, synthesis_content_no_issues):
        """Test that content without Issues Verified returns empty list."""
        issues = extract_antipatterns(
            synthesis_content=synthesis_content_no_issues,
            epic_id=24,
            story_id="24-11",
            config=mock_config,
        )
        assert issues == []

    def test_extract_malformed_yaml(self, mock_config, synthesis_content_with_issues):
        """Test that malformed YAML returns empty list (graceful failure)."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "this is not valid yaml: [unclosed"

        with patch("bmad_assist.providers.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = mock_result
            mock_get_provider.return_value = mock_provider

            issues = extract_antipatterns(
                synthesis_content_with_issues,
                epic_id=24,
                story_id="24-11",
                config=mock_config,
            )

        assert issues == []

    def test_extract_helper_not_configured(self, synthesis_content_with_issues):
        """Test graceful handling when helper provider not configured."""
        config = MagicMock()
        config.providers.helper.provider = None
        config.providers.helper.model = None

        issues = extract_antipatterns(
            synthesis_content_with_issues,
            epic_id=24,
            story_id="24-11",
            config=config,
        )
        assert issues == []

    def test_extract_string_epic_id(self, mock_config, synthesis_content_with_issues):
        """Test extraction works with string epic ID (e.g., 'testarch')."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = """
story_id: "testarch-01"
date: "2026-01-22"
issues:
  - severity: high
    issue: "Test issue"
    file: "src/test.py:1"
    fix: "Fixed"
"""

        with patch("bmad_assist.providers.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = mock_result
            mock_get_provider.return_value = mock_provider

            issues = extract_antipatterns(
                synthesis_content_with_issues,
                epic_id="testarch",  # String epic ID
                story_id="testarch-01",
                config=mock_config,
            )

        assert len(issues) == 1


class TestAppendToAntipatterns:
    """Tests for append_to_antipatterns_file function."""

    @pytest.fixture
    def sample_issues(self):
        """Sample issues to append."""
        return [
            {
                "severity": "critical",
                "issue": "Missing null check",
                "file": "src/handler.py:42",
                "fix": "Added null guard",
            },
            {
                "severity": "high",
                "issue": "No validation",
                "file": "src/api.py:15",
                "fix": "Added validation",
            },
        ]

    def test_append_creates_file_with_header(self, tmp_path, sample_issues):
        """Test that new file is created with warning header."""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_antipatterns_file(
                issues=sample_issues,
                epic_id=24,
                story_id="24-11",
                antipattern_type="story",
                project_path=tmp_path,
            )

        antipatterns_file = impl_artifacts / "epic-24-story-antipatterns.md"
        assert antipatterns_file.exists()

        content = antipatterns_file.read_text()
        assert "WARNING: ANTI-PATTERNS" in content
        assert "DO NOT repeat these patterns" in content
        assert "Story 24-11" in content
        assert "Missing null check" in content
        assert "| critical |" in content

    def test_append_to_existing_file(self, tmp_path, sample_issues):
        """Test appending to existing file without overwriting."""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        # Create initial file
        antipatterns_file = impl_artifacts / "epic-24-story-antipatterns.md"
        initial_content = STORY_ANTIPATTERNS_HEADER.format(epic_id=24)
        initial_content += "\n## Story 24-10 (2026-01-21)\n\nExisting content"
        antipatterns_file.write_text(initial_content)

        with patch("bmad_assist.antipatterns.extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_antipatterns_file(
                issues=sample_issues,
                epic_id=24,
                story_id="24-11",
                antipattern_type="story",
                project_path=tmp_path,
            )

        content = antipatterns_file.read_text()
        # Check both old and new content exist
        assert "Story 24-10" in content
        assert "Existing content" in content
        assert "Story 24-11" in content
        assert "Missing null check" in content

    def test_append_empty_issues_skips(self, tmp_path):
        """Test that empty issues list doesn't write anything."""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_antipatterns_file(
                issues=[],  # Empty
                epic_id=24,
                story_id="24-11",
                antipattern_type="story",
                project_path=tmp_path,
            )

        antipatterns_file = impl_artifacts / "epic-24-story-antipatterns.md"
        assert not antipatterns_file.exists()

    def test_append_code_antipatterns(self, tmp_path, sample_issues):
        """Test code antipatterns use correct header."""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_antipatterns_file(
                issues=sample_issues,
                epic_id=24,
                story_id="24-11",
                antipattern_type="code",
                project_path=tmp_path,
            )

        antipatterns_file = impl_artifacts / "epic-24-code-antipatterns.md"
        assert antipatterns_file.exists()

        content = antipatterns_file.read_text()
        assert "Code Antipatterns" in content
        assert "code review" in content

    def test_string_epic_id_path(self, tmp_path, sample_issues):
        """Test that string epic ID works for file path (e.g., epic-testarch-...)."""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_antipatterns_file(
                issues=sample_issues,
                epic_id="testarch",  # String epic ID
                story_id="testarch-01",
                antipattern_type="code",
                project_path=tmp_path,
            )

        antipatterns_file = impl_artifacts / "epic-testarch-code-antipatterns.md"
        assert antipatterns_file.exists()
        assert "testarch-01" in antipatterns_file.read_text()

    def test_pipe_characters_escaped(self, tmp_path):
        """Test that pipe characters in issue content are escaped for markdown table."""
        issues = [
            {
                "severity": "high",
                "issue": "Issue with | pipe char",
                "file": "src/foo.py",
                "fix": "Fix | also has pipe",
            }
        ]

        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_antipatterns_file(
                issues=issues,
                epic_id=24,
                story_id="24-11",
                antipattern_type="story",
                project_path=tmp_path,
            )

        content = (impl_artifacts / "epic-24-story-antipatterns.md").read_text()
        # Pipe should be escaped
        assert "Issue with \\| pipe char" in content
        assert "Fix \\| also has pipe" in content

"""Tests for antipatterns extraction and file appending."""

from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.antipatterns.extractor import (
    ISSUE_WITH_FIX_PATTERN,
    ISSUES_SECTION_PATTERN,
    SEVERITY_HEADER_PATTERN,
    STORY_ANTIPATTERNS_HEADER,
    append_to_antipatterns_file,
    extract_antipatterns,
)


class TestRegexPatterns:
    """Tests for regex patterns used in extraction."""

    def test_issues_section_pattern_basic(self):
        """Test extraction of Issues Verified section."""
        content = """
## Summary
Some summary text.

## Issues Verified (by severity)

### Critical
- **Issue**: Test | **Fix**: Done

### High
- **Issue**: Another | **Fix**: Fixed

## Issues Dismissed
Dismissed stuff.
"""
        match = ISSUES_SECTION_PATTERN.search(content)
        assert match is not None
        section = match.group(0)
        assert "### Critical" in section
        assert "### High" in section
        assert "Issues Dismissed" not in section

    def test_issues_section_pattern_ends_at_eof(self):
        """Test section extraction when it's at end of file."""
        content = """
## Other stuff

## Issues Verified
### Critical
- **Issue**: Test | **Fix**: Done
"""
        match = ISSUES_SECTION_PATTERN.search(content)
        assert match is not None
        assert "### Critical" in match.group(0)

    def test_severity_header_pattern(self):
        """Test severity header matching."""
        assert SEVERITY_HEADER_PATTERN.match("### Critical")
        assert SEVERITY_HEADER_PATTERN.match("### HIGH")
        assert SEVERITY_HEADER_PATTERN.match("### medium")
        assert SEVERITY_HEADER_PATTERN.match("###  Low")
        assert not SEVERITY_HEADER_PATTERN.match("## Critical")
        assert not SEVERITY_HEADER_PATTERN.match("### Unknown")

    def test_issue_with_fix_pattern_format_a(self):
        """Test issue pattern - Format A (validation synthesis)."""
        line = "- **Memory Leak for Inactive Destinations** | **Source**: A, B | **Fix**: Added cleanup"
        match = ISSUE_WITH_FIX_PATTERN.match(line)
        assert match is not None
        # Raw match includes trailing ** which gets cleaned in extract function
        assert "Memory Leak" in match.group(1)
        assert "Added cleanup" in match.group(2)

    def test_issue_with_fix_pattern_format_b(self):
        """Test issue pattern - Format B (code review synthesis)."""
        line = "- **Issue**: JSON Duration mismatch | **Source**: A, C | **File**: path:1 | **Fix**: Changed serializer"
        match = ISSUE_WITH_FIX_PATTERN.match(line)
        assert match is not None
        # Raw match includes "Issue**: " prefix which gets cleaned in extract function
        assert "JSON Duration mismatch" in match.group(1) or "Issue" in match.group(1)
        assert "Changed serializer" in match.group(2)

    def test_issue_without_fix_not_matched(self):
        """Test that issues with DEFERRED status are not matched."""
        line = "- **Issue**: Unused receiver | **Source**: D | **Status**: DEFERRED"
        match = ISSUE_WITH_FIX_PATTERN.match(line)
        assert match is None


class TestExtractAntipatterns:
    """Tests for extract_antipatterns function."""

    @pytest.fixture
    def mock_config(self):
        """Create mock config with antipatterns enabled."""
        config = MagicMock()
        config.antipatterns.enabled = True
        return config

    @pytest.fixture
    def mock_config_disabled(self):
        """Create mock config with antipatterns disabled."""
        config = MagicMock()
        config.antipatterns.enabled = False
        return config

    @pytest.fixture
    def synthesis_with_issues(self):
        """Sample synthesis content with Issues Verified section."""
        return """
# Validation Synthesis Report

## Summary
Review complete.

## Issues Verified (by severity)

### Critical
- **Memory Leak for Inactive Destinations** | **Source**: Validators A, B | **Fix**: Added cleanup handler

### High
- **Issue**: JSON Duration mismatch | **Source**: Reviewers A, C | **File**: path:line | **Fix**: Changed serializer

### Low
- **Issue**: Unused variable | **Source**: Reviewer D | **Status**: DEFERRED

## Issues Dismissed
- Some dismissed issue
"""

    @pytest.fixture
    def synthesis_no_issues_section(self):
        """Sample synthesis content without Issues Verified section."""
        return """
# Validation Synthesis Report

## Summary
Everything looks good, no issues found.
"""

    def test_extract_critical_issue(self, mock_config):
        """Test extraction of single critical issue with fix."""
        content = """
## Issues Verified

### Critical
- **Buffer overflow risk** | **Source**: A | **Fix**: Added bounds check
"""
        issues = extract_antipatterns(content, epic_id=1, story_id="1-1", config=mock_config)

        assert len(issues) == 1
        assert issues[0]["severity"] == "critical"
        assert "Buffer overflow" in issues[0]["issue"]
        assert "bounds check" in issues[0]["fix"]

    def test_extract_multiple_severities(self, mock_config, synthesis_with_issues):
        """Test extraction across Critical/High severity levels."""
        issues = extract_antipatterns(
            synthesis_with_issues, epic_id=24, story_id="24-11", config=mock_config
        )

        # Should extract 2 issues (critical + high), skip deferred
        assert len(issues) == 2

        severities = [i["severity"] for i in issues]
        assert "critical" in severities
        assert "high" in severities

    def test_skip_deferred_issues(self, mock_config):
        """Test that issues with Status: DEFERRED are not extracted."""
        content = """
## Issues Verified

### High
- **Issue**: Real issue | **Source**: A | **Fix**: Fixed it

### Low
- **Issue**: Deferred one | **Source**: B | **Status**: DEFERRED
- **Issue**: Another deferred | **Source**: C | **Status**: DEFERRED
"""
        issues = extract_antipatterns(content, epic_id=1, story_id="1-1", config=mock_config)

        assert len(issues) == 1
        assert issues[0]["severity"] == "high"

    def test_empty_section_handled(self, mock_config):
        """Test graceful handling of empty severity sections."""
        content = """
## Issues Verified

### Critical

### High
- **Issue**: Only high | **Source**: A | **Fix**: Done
"""
        issues = extract_antipatterns(content, epic_id=1, story_id="1-1", config=mock_config)

        assert len(issues) == 1
        assert issues[0]["severity"] == "high"

    def test_disabled_config_returns_empty(self, mock_config_disabled):
        """Test that disabled config returns empty list."""
        content = """
## Issues Verified

### Critical
- **Issue**: Should not extract | **Source**: A | **Fix**: Done
"""
        issues = extract_antipatterns(
            content, epic_id=1, story_id="1-1", config=mock_config_disabled
        )

        assert issues == []

    def test_empty_synthesis_returns_empty(self, mock_config):
        """Test that empty synthesis content returns empty list."""
        issues = extract_antipatterns("", epic_id=24, story_id="24-11", config=mock_config)
        assert issues == []

    def test_no_issues_section_returns_empty(self, mock_config, synthesis_no_issues_section):
        """Test that content without Issues Verified returns empty list."""
        issues = extract_antipatterns(
            synthesis_no_issues_section, epic_id=24, story_id="24-11", config=mock_config
        )
        assert issues == []

    def test_string_epic_id(self, mock_config):
        """Test extraction works with string epic ID (e.g., 'testarch')."""
        content = """
## Issues Verified

### High
- **Issue**: Test issue | **Source**: A | **Fix**: Fixed
"""
        issues = extract_antipatterns(
            content, epic_id="testarch", story_id="testarch-01", config=mock_config
        )

        assert len(issues) == 1


class TestAppendToAntipatterns:
    """Tests for append_to_antipatterns_file function."""

    @pytest.fixture
    def sample_issues(self):
        """Sample issues to append (3-column format)."""
        return [
            {
                "severity": "critical",
                "issue": "Missing null check",
                "fix": "Added null guard",
            },
            {
                "severity": "high",
                "issue": "No validation",
                "fix": "Added validation",
            },
        ]

    def test_append_creates_file_in_antipatterns_dir(self, tmp_path, sample_issues):
        """Test that new file is created in antipatterns/ subdirectory."""
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

        # File should be in antipatterns/ subdirectory
        antipatterns_dir = impl_artifacts / "antipatterns"
        assert antipatterns_dir.exists()

        antipatterns_file = antipatterns_dir / "epic-24-story-antipatterns.md"
        assert antipatterns_file.exists()

        content = antipatterns_file.read_text()
        assert "WARNING: ANTI-PATTERNS" in content
        assert "DO NOT repeat these patterns" in content
        assert "Story 24-11" in content
        assert "Missing null check" in content

    def test_append_three_column_table(self, tmp_path, sample_issues):
        """Test that table has 3 columns (Severity, Issue, Fix)."""
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

        antipatterns_file = impl_artifacts / "antipatterns" / "epic-24-story-antipatterns.md"
        content = antipatterns_file.read_text()

        # Check for 3-column header (no File column)
        assert "| Severity | Issue | Fix |" in content
        assert "|----------|-------|-----|" in content

        # Should NOT have 4-column format
        assert "| Severity | Issue | File | Fix |" not in content

    def test_append_to_existing_file(self, tmp_path, sample_issues):
        """Test appending to existing file without overwriting."""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        antipatterns_dir = impl_artifacts / "antipatterns"
        antipatterns_dir.mkdir(parents=True)

        # Create initial file
        antipatterns_file = antipatterns_dir / "epic-24-story-antipatterns.md"
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
                issues=[],
                epic_id=24,
                story_id="24-11",
                antipattern_type="story",
                project_path=tmp_path,
            )

        antipatterns_dir = impl_artifacts / "antipatterns"
        # Directory and file should not be created
        assert not antipatterns_dir.exists()

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

        antipatterns_file = impl_artifacts / "antipatterns" / "epic-24-code-antipatterns.md"
        assert antipatterns_file.exists()

        content = antipatterns_file.read_text()
        assert "Code Antipatterns" in content
        assert "code review" in content

    def test_string_epic_id_path(self, tmp_path, sample_issues):
        """Test that string epic ID works for file path."""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_antipatterns_file(
                issues=sample_issues,
                epic_id="testarch",
                story_id="testarch-01",
                antipattern_type="code",
                project_path=tmp_path,
            )

        antipatterns_file = impl_artifacts / "antipatterns" / "epic-testarch-code-antipatterns.md"
        assert antipatterns_file.exists()
        assert "testarch-01" in antipatterns_file.read_text()

    def test_pipe_characters_escaped(self, tmp_path):
        """Test that pipe characters in issue content are escaped for markdown table."""
        issues = [
            {
                "severity": "high",
                "issue": "Issue with | pipe char",
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

        content = (impl_artifacts / "antipatterns" / "epic-24-story-antipatterns.md").read_text()
        # Pipe should be escaped
        assert "Issue with \\| pipe char" in content
        assert "Fix \\| also has pipe" in content

    def test_creates_antipatterns_directory(self, tmp_path, sample_issues):
        """Test that antipatterns/ directory is created automatically (AC9)."""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        # Verify antipatterns dir doesn't exist yet
        antipatterns_dir = impl_artifacts / "antipatterns"
        assert not antipatterns_dir.exists()

        with patch("bmad_assist.antipatterns.extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_antipatterns_file(
                issues=sample_issues,
                epic_id=1,
                story_id="1-1",
                antipattern_type="story",
                project_path=tmp_path,
            )

        # Directory should now exist
        assert antipatterns_dir.exists()
        assert antipatterns_dir.is_dir()

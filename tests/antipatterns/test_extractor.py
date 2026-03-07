"""Tests for antipatterns extraction and file appending."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.antipatterns.extractor import (
    BLOCK_FIX_PATTERN,
    BLOCK_ISSUE_PATTERN,
    BLOCK_START_PATTERN,
    CODE_ANTIPATTERNS_HEADER,
    DISMISSED_ITEM_PATTERN,
    DISMISSED_SECTION_PATTERN,
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


class TestBlockPatterns:
    """Tests for multi-line block format regex patterns."""

    def test_block_start_numbered(self):
        """Test numbered block start: '1. **Title**'."""
        match = BLOCK_START_PATTERN.match('1. **PaymentIntent amount-sync verification**')
        assert match is not None
        assert "PaymentIntent" in match.group(1)

    def test_block_start_bold_numbered(self):
        """Test bold-numbered block start: '**1. Title**'."""
        match = BLOCK_START_PATTERN.match('**1. Status/Lifecycle Contradiction (Validator B)**')
        assert match is not None
        assert "Status/Lifecycle" in match.group(1)

    def test_block_start_bullet(self):
        """Test bullet block start: '- **Title**'."""
        match = BLOCK_START_PATTERN.match('- **Memory Leak for Inactive Destinations**')
        assert match is not None
        assert "Memory Leak" in match.group(1)

    def test_block_fix_pattern_basic(self):
        """Test fix line: '  - **Fix**: description'."""
        match = BLOCK_FIX_PATTERN.match('   - **Fix**: Added bounds check')
        assert match is not None
        assert "Added bounds check" in match.group(1)

    def test_block_fix_pattern_applied(self):
        """Test fix line with APPLIED marker."""
        line = '   - **Fix**: \u2705 **APPLIED** \u2014 Removed misleading checkbox'
        match = BLOCK_FIX_PATTERN.match(line)
        assert match is not None
        assert "APPLIED" in match.group(1)

    def test_block_fix_pattern_fix_applied_keyword(self):
        """Test 'Fix Applied' variant from validation synthesis."""
        match = BLOCK_FIX_PATTERN.match('- **Fix Applied**: Changed AC8 wording')
        assert match is not None
        assert "Changed AC8" in match.group(1)

    def test_block_fix_pattern_no_match_source(self):
        """Test that non-fix lines don't match."""
        assert BLOCK_FIX_PATTERN.match('   - **Source**: Reviewer A') is None
        assert BLOCK_FIX_PATTERN.match('   - **Files**: `path/to/file`') is None

    def test_block_issue_pattern(self):
        """Test issue description line: '- **Issue**: description'."""
        match = BLOCK_ISSUE_PATTERN.match('- **Issue**: Story header says Ready for Dev')
        assert match is not None
        assert "Story header" in match.group(1)

    def test_block_issue_pattern_indented(self):
        """Test indented issue line."""
        match = BLOCK_ISSUE_PATTERN.match('   - **Issue**: JSON Duration mismatch')
        assert match is not None
        assert "JSON Duration" in match.group(1)


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

    def test_extract_code_review_multiline_format(self, mock_config):
        """Test extraction from code review synthesis multi-line format."""
        content = """
## Issues Verified (by severity)

### Critical

1. **PaymentIntent amount-sync verification marked complete but not implemented**
   - **Source**: Reviewer A (+3), Reviewer B (+3)
   - **Files**: `apps/storefront/CheckoutForm.tsx:306-312`
   - **Evidence**: DoD claims implemented but code has TODO
   - **Fix**: \u2705 **APPLIED** \u2014 Removed misleading DoD checkbox

2. **NOT_SURE stage incorrectly treated as blocking**
   - **Source**: Reviewer B (+3) via Antipatterns log
   - **Files**: `apps/storefront/stage-safety.ts:34`
   - **Fix**: \u2705 **DEFERRED** \u2014 Code already fixed per Antipatterns log

### High

3. **CheckoutForm is a 522-line god component**
   - **Source**: Reviewer A (+1), Reviewer B (+1)
   - **Fix**: \u23ed\ufe0f **DEFERRED** \u2014 Architectural refactor beyond synthesis scope

4. **E2E test mocked payment, not real flow**
   - **Source**: Reviewer A (+1)
   - **Fix**: \u2705 **APPLIED** \u2014 Added comment documenting limited scope
"""
        issues = extract_antipatterns(content, epic_id=4, story_id="4-4", config=mock_config)

        # Should extract 2: #1 (APPLIED) and #4 (APPLIED)
        # Skip #2 (DEFERRED without APPLIED) and #3 (DEFERRED without APPLIED)
        assert len(issues) == 2

        assert issues[0]["severity"] == "critical"
        assert "PaymentIntent" in issues[0]["issue"]
        assert "Removed misleading" in issues[0]["fix"]

        assert issues[1]["severity"] == "high"
        assert "E2E test" in issues[1]["issue"]
        assert "Added comment" in issues[1]["fix"]

    def test_extract_validation_multiline_format(self, mock_config):
        """Test extraction from validation synthesis multi-line format."""
        content = """
## Issues Verified (by severity)

### Critical

**1. Status/Lifecycle Contradiction (Validator B + supported by DoD analysis)**
- **Issue**: Story header says Ready for Dev but Dev Agent Record claims implementation verified
- **Source**: Validator B, lines 5, 1047
- **Impact**: Creates execution ambiguity
- **Fix Applied**: Clarified status to Ready for Dev and reconciled Dev Agent Record

**2. AC8 Backend Enforcement Ambiguity (Validator B + Deep Verify F5)**
- **Issue**: AC8 says backend validation is ideally present, making it optional
- **Source**: Validator B, line 97
- **Fix Applied**: Changed AC8 from ideally to MUST include

### High

**3. Cart Expiry Redirect Contract Incomplete (Validator B)**
- **Issue**: AC6 requires redirect but implementation uses different approach
- **Source**: Validator B
- **Fix Applied**: Clarified AC6 to align with implementation
"""
        issues = extract_antipatterns(content, epic_id=4, story_id="4-4", config=mock_config)

        assert len(issues) == 3

        assert issues[0]["severity"] == "critical"
        assert "Ready for Dev" in issues[0]["issue"]
        assert "Clarified status" in issues[0]["fix"]

        assert issues[1]["severity"] == "critical"
        assert "optional" in issues[1]["issue"]
        assert "MUST include" in issues[1]["fix"]

        assert issues[2]["severity"] == "high"
        assert "redirect" in issues[2]["issue"]

    def test_extract_mixed_formats(self, mock_config):
        """Test extraction handles both legacy pipe and multi-line in same section."""
        content = """
## Issues Verified

### Critical
- **Buffer overflow risk** | **Source**: A | **Fix**: Added bounds check

### High

1. **Memory leak in event handler**
   - **Source**: Reviewer B
   - **Fix**: \u2705 **APPLIED** \u2014 Added cleanup on unmount
"""
        issues = extract_antipatterns(content, epic_id=1, story_id="1-1", config=mock_config)

        assert len(issues) == 2
        assert issues[0]["severity"] == "critical"
        assert "Buffer overflow" in issues[0]["issue"]
        assert issues[1]["severity"] == "high"
        assert "Memory leak" in issues[1]["issue"]
        assert "Added cleanup" in issues[1]["fix"]

    def test_multiline_deferred_skipped(self, mock_config):
        """Test that DEFERRED items in multi-line format are skipped."""
        content = """
## Issues Verified

### High

1. **Applied issue**
   - **Fix**: \u2705 **APPLIED** \u2014 Fixed the thing

2. **Deferred issue**
   - **Fix**: \u23ed\ufe0f **DEFERRED** \u2014 Too complex for now

3. **Another applied**
   - **Fix**: \u2705 **APPLIED** \u2014 Also fixed
"""
        issues = extract_antipatterns(content, epic_id=1, story_id="1-1", config=mock_config)

        assert len(issues) == 2
        assert "Applied issue" in issues[0]["issue"]
        assert "Another applied" in issues[1]["issue"]

    def test_fix_desc_cleaned_of_status_markers(self, mock_config):
        """Test that status emoji and markers are removed from fix descriptions."""
        content = """
## Issues Verified

### Critical

1. **Test issue**
   - **Fix**: \u2705 **APPLIED** \u2014 Removed misleading DoD checkbox
"""
        issues = extract_antipatterns(content, epic_id=1, story_id="1-1", config=mock_config)

        assert len(issues) == 1
        assert issues[0]["fix"] == "Removed misleading DoD checkbox"
        assert "\u2705" not in issues[0]["fix"]
        assert "APPLIED" not in issues[0]["fix"]

    def test_extract_numbered_pipe_delimited_format(self, mock_config):
        """Test extraction from numbered pipe-delimited format."""
        content = """
## Issues Verified (by severity)

### Medium

1. **Magic number 300ms scattered across files** | **Validator B** | **Files**: `CartItemRow.tsx:145` | **Fix**: Extracted constant

2. **Stagger animation delay unbounded** | **Validator B** | **File**: `CartItemRow.tsx:167` | **Fix**: Added cap at 1000ms

### Low

1. **CTA routes to wrong page** | **Validator A** | **File**: `cart.tsx:420` | **Severity**: Minor UX concern
"""
        issues = extract_antipatterns(content, epic_id=4, story_id="4-9", config=mock_config)

        # Should extract 2 medium issues (all have **Fix**:)
        # Low item has **Severity**: not **Fix**: so it's skipped
        assert len(issues) == 2

        assert issues[0]["severity"] == "medium"
        assert "Magic number" in issues[0]["issue"]
        assert "Extracted" in issues[0]["fix"]

        assert issues[1]["severity"] == "medium"
        assert "Stagger animation" in issues[1]["issue"]

    def test_numbered_pipe_with_fix_pattern_regex(self):
        """Test that ISSUE_WITH_FIX_PATTERN matches numbered pipe-delimited lines."""
        line = '1. **Magic number 300ms** | **Validator B** | **Fix**: Extracted constant'
        match = ISSUE_WITH_FIX_PATTERN.match(line)
        assert match is not None
        assert "Magic number" in match.group(1)
        assert "Extracted constant" in match.group(2)


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


class TestDismissedFindingsRegex:
    """Tests for dismissed findings regex patterns (credit: @derron1 PR #39)."""

    def test_dismissed_section_pattern_basic(self):
        """Test extraction of Issues Dismissed section."""
        content = """
## Issues Verified (by severity)

### Critical
- **Issue**: Test | **Fix**: Done

## Issues Dismissed
- **Claimed Issue**: AC6 not end-to-end | **Raised by**: Validator A, B | **Dismissal Reason**: Deferred to Story 5.3

## Changes Applied
Some changes.
"""
        match = DISMISSED_SECTION_PATTERN.search(content)
        assert match is not None
        section = match.group(1)
        assert "AC6 not end-to-end" in section
        assert "Changes Applied" not in section

    def test_dismissed_section_pattern_ends_at_eof(self):
        """Test section extraction when at end of file."""
        content = """
## Issues Verified
### High
- **Issue**: Test | **Fix**: Done

## Issues Dismissed
- **Claimed Issue**: False positive | **Raised by**: Reviewer A | **Dismissal Reason**: Stale context
"""
        match = DISMISSED_SECTION_PATTERN.search(content)
        assert match is not None
        assert "False positive" in match.group(1)

    def test_dismissed_item_pattern_single(self):
        """Test matching a single dismissed item."""
        text = "- **Claimed Issue**: AC6 not end-to-end | **Raised by**: Validator A (CRITICAL), Validator B (CRITICAL) | **Dismissal Reason**: Intentionally deferred to Story 5.3"
        matches = list(DISMISSED_ITEM_PATTERN.finditer(text))
        assert len(matches) == 1
        assert "AC6 not end-to-end" in matches[0].group(1)
        assert "Validator A" in matches[0].group(2)
        assert "deferred to Story 5.3" in matches[0].group(3)

    def test_dismissed_item_pattern_multiple(self):
        """Test matching multiple dismissed items."""
        text = """- **Claimed Issue**: AC6 not end-to-end | **Raised by**: Validator A, B | **Dismissal Reason**: Deferred to Story 5.3
- **Claimed Issue**: P1-BOOK-012 sanitization | **Raised by**: Validator B | **Dismissal Reason**: False positive - stale context
"""
        matches = list(DISMISSED_ITEM_PATTERN.finditer(text))
        assert len(matches) == 2
        assert "AC6" in matches[0].group(1)
        assert "P1-BOOK-012" in matches[1].group(1)


class TestExtractDismissedFindings:
    """Tests for dismissed findings extraction via extract_antipatterns (credit: @derron1 PR #39)."""

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.antipatterns.enabled = True
        return config

    def test_dismissed_findings_extracted_as_antipatterns(self, mock_config):
        """Test that dismissed findings from synthesis are extracted with severity='dismissed'."""
        content = """
## Issues Verified (by severity)

### Critical
- **Issue**: Real bug | **Source**: Reviewer A | **Fix**: Fixed it

## Issues Dismissed
- **Claimed Issue**: AC6 not end-to-end | **Raised by**: Validator A (CRITICAL), Validator B (CRITICAL) | **Dismissal Reason**: Intentionally deferred to Story 5.3
- **Claimed Issue**: P1-BOOK-012 sanitization missing | **Raised by**: Validator B (HIGH) | **Dismissal Reason**: False positive - already fixed in commit abc123

## Changes Applied
Some changes.
"""
        issues = extract_antipatterns(content, epic_id=5, story_id="5-1", config=mock_config)

        # 1 verified + 2 dismissed
        assert len(issues) == 3

        verified = [i for i in issues if i["severity"] != "dismissed"]
        dismissed = [i for i in issues if i["severity"] == "dismissed"]

        assert len(verified) == 1
        assert len(dismissed) == 2

        assert "AC6 not end-to-end" in dismissed[0]["issue"]
        assert "FALSE POSITIVE:" in dismissed[0]["fix"]
        assert "deferred to Story 5.3" in dismissed[0]["fix"]

        assert "P1-BOOK-012" in dismissed[1]["issue"]
        assert "FALSE POSITIVE:" in dismissed[1]["fix"]

    def test_no_dismissed_section_only_verified(self, mock_config):
        """Test that missing dismissed section doesn't break extraction."""
        content = """
## Issues Verified

### High
- **Issue**: Real bug | **Source**: A | **Fix**: Fixed
"""
        issues = extract_antipatterns(content, epic_id=5, story_id="5-1", config=mock_config)
        assert len(issues) == 1
        assert issues[0]["severity"] == "high"

    def test_no_false_positives_message_skipped(self, mock_config):
        """Test that 'no false positives' message doesn't produce dismissed items."""
        content = """
## Issues Verified

### High
- **Issue**: Real bug | **Source**: A | **Fix**: Fixed

## Issues Dismissed
No false positives identified.
"""
        issues = extract_antipatterns(content, epic_id=5, story_id="5-1", config=mock_config)
        assert len(issues) == 1
        assert issues[0]["severity"] == "high"

    def test_dismissed_only_no_verified(self, mock_config):
        """Test synthesis with only dismissed findings and no verified issues."""
        content = """
## Issues Dismissed
- **Claimed Issue**: Not a real bug | **Raised by**: Reviewer A | **Dismissal Reason**: Design decision
"""
        issues = extract_antipatterns(content, epic_id=5, story_id="5-1", config=mock_config)
        assert len(issues) == 1
        assert issues[0]["severity"] == "dismissed"
        assert "Not a real bug" in issues[0]["issue"]
        assert "FALSE POSITIVE: Design decision" == issues[0]["fix"]

    def test_dismissed_written_to_antipatterns_file(self, tmp_path, mock_config):
        """Test that dismissed items end up in the antipatterns file via full pipeline."""
        content = """
## Issues Verified

### Critical
- **Issue**: Real bug | **Source**: A | **Fix**: Fixed it

## Issues Dismissed
- **Claimed Issue**: False positive thing | **Raised by**: Reviewer B | **Dismissal Reason**: Stale context
"""
        issues = extract_antipatterns(content, epic_id=5, story_id="5-1", config=mock_config)

        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_antipatterns_file(
                issues=issues,
                epic_id=5,
                story_id="5-1",
                antipattern_type="code",
                project_path=tmp_path,
            )

        ap_file = impl_artifacts / "antipatterns" / "epic-5-code-antipatterns.md"
        assert ap_file.exists()
        file_content = ap_file.read_text()
        assert "dismissed" in file_content
        assert "False positive thing" in file_content
        assert "FALSE POSITIVE: Stale context" in file_content
        assert "Real bug" in file_content

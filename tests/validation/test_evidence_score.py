"""Tests for Evidence Score calculation module.

Tests cover:
- Severity and Verdict enums
- Score calculation with various findings
- Verdict threshold determination
- Report parsing (table and bullet formats)
- Finding deduplication
- Aggregate calculation across validators
- Context formatting for synthesis
- Exception handling for cache validation
"""

import pytest

from bmad_assist.validation.evidence_score import (
    AllValidatorsFailedError,
    CacheFormatError,
    CacheVersionError,
    EvidenceFinding,
    EvidenceScoreAggregate,
    EvidenceScoreReport,
    Severity,
    Verdict,
    aggregate_evidence_scores,
    calculate_evidence_score,
    determine_verdict,
    format_evidence_score_context,
    parse_evidence_findings,
)

# Padding to push test content above MIN_CONTENT_LENGTH (2000 chars) in parse_evidence_findings.
# Without this, the early-return for short content would skip parsing entirely.
_PAD = "\n<!-- " + "x" * 2000 + " -->\n"


# =============================================================================
# Enum Tests
# =============================================================================


class TestSeverityEnum:
    """Tests for Severity enum."""

    def test_severity_values(self) -> None:
        """Test all severity values exist."""
        assert Severity.CRITICAL.value == "CRITICAL"
        assert Severity.IMPORTANT.value == "IMPORTANT"
        assert Severity.MINOR.value == "MINOR"

    def test_severity_from_string(self) -> None:
        """Test creating severity from string."""
        assert Severity("CRITICAL") == Severity.CRITICAL
        assert Severity("IMPORTANT") == Severity.IMPORTANT
        assert Severity("MINOR") == Severity.MINOR


class TestVerdictEnum:
    """Tests for Verdict enum."""

    def test_verdict_values(self) -> None:
        """Test all verdict values exist."""
        assert Verdict.REJECT.value == "REJECT"
        assert Verdict.MAJOR_REWORK.value == "MAJOR_REWORK"
        assert Verdict.PASS.value == "PASS"
        assert Verdict.EXCELLENT.value == "EXCELLENT"

    def test_display_name_validation_context(self) -> None:
        """Test display names for validation context."""
        assert Verdict.REJECT.display_name("validation") == "REJECT"
        assert Verdict.MAJOR_REWORK.display_name("validation") == "MAJOR REWORK"
        assert Verdict.PASS.display_name("validation") == "READY"
        assert Verdict.EXCELLENT.display_name("validation") == "EXCELLENT"

    def test_display_name_code_review_context(self) -> None:
        """Test display names for code review context."""
        assert Verdict.REJECT.display_name("code_review") == "REJECT"
        assert Verdict.MAJOR_REWORK.display_name("code_review") == "MAJOR REWORK"
        assert Verdict.PASS.display_name("code_review") == "APPROVE"
        assert Verdict.EXCELLENT.display_name("code_review") == "EXEMPLARY"


# =============================================================================
# Score Calculation Tests
# =============================================================================


class TestCalculateEvidenceScore:
    """Tests for calculate_evidence_score function."""

    def test_empty_findings_zero_clean_passes(self) -> None:
        """Test score with no findings and no clean passes."""
        score = calculate_evidence_score([], 0)
        assert score == 0.0

    def test_single_critical_finding(self) -> None:
        """Test score with single CRITICAL finding (+3)."""
        findings = [
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Test critical",
                source="test.py:10",
                validator_id="Validator A",
            )
        ]
        score = calculate_evidence_score(findings, 0)
        assert score == 3.0

    def test_mixed_findings(self) -> None:
        """Test score with mixed severity findings."""
        findings = [
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Critical issue",
                source="test.py:10",
                validator_id="Validator A",
            ),
            EvidenceFinding(
                severity=Severity.IMPORTANT,
                score=1.0,
                description="Important issue",
                source="test.py:20",
                validator_id="Validator A",
            ),
            EvidenceFinding(
                severity=Severity.MINOR,
                score=0.3,
                description="Minor issue",
                source="test.py:30",
                validator_id="Validator A",
            ),
        ]
        # 3.0 + 1.0 + 0.3 = 4.3
        score = calculate_evidence_score(findings, 0)
        assert score == 4.3

    def test_clean_passes_reduce_score(self) -> None:
        """Test that CLEAN PASS categories reduce score."""
        findings = [
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Critical issue",
                source="test.py:10",
                validator_id="Validator A",
            )
        ]
        # 3.0 + (4 * -0.5) = 3.0 - 2.0 = 1.0
        score = calculate_evidence_score(findings, 4)
        assert score == 1.0

    def test_negative_score_possible(self) -> None:
        """Test that score can go negative with many clean passes."""
        # 0 findings + 10 clean passes = 10 * -0.5 = -5.0
        score = calculate_evidence_score([], 10)
        assert score == -5.0


class TestDetermineVerdict:
    """Tests for determine_verdict function."""

    def test_reject_threshold(self) -> None:
        """Test REJECT verdict for score >= 6."""
        assert determine_verdict(6.0) == Verdict.REJECT
        assert determine_verdict(10.0) == Verdict.REJECT
        assert determine_verdict(100.0) == Verdict.REJECT

    def test_major_rework_threshold(self) -> None:
        """Test MAJOR_REWORK verdict for score 4-5.9."""
        assert determine_verdict(4.0) == Verdict.MAJOR_REWORK
        assert determine_verdict(5.0) == Verdict.MAJOR_REWORK
        assert determine_verdict(5.9) == Verdict.MAJOR_REWORK

    def test_pass_threshold(self) -> None:
        """Test PASS verdict for score -2.9 to 3.9."""
        assert determine_verdict(3.9) == Verdict.PASS
        assert determine_verdict(0.0) == Verdict.PASS
        assert determine_verdict(-2.9) == Verdict.PASS

    def test_excellent_threshold(self) -> None:
        """Test EXCELLENT verdict for score <= -3."""
        assert determine_verdict(-3.0) == Verdict.EXCELLENT
        assert determine_verdict(-5.0) == Verdict.EXCELLENT
        assert determine_verdict(-10.0) == Verdict.EXCELLENT


# =============================================================================
# Parsing Tests
# =============================================================================


class TestParseEvidenceFindings:
    """Tests for parse_evidence_findings function."""

    def test_parse_table_format(self) -> None:
        """Test parsing Evidence Score table format."""
        content = _PAD + """
## Evidence Score Summary

| Severity | Description | Source | Score |
|----------|-------------|--------|-------|
| 🔴 CRITICAL | Missing input validation | auth.py:45 | +3 |
| 🟠 IMPORTANT | No error handling | api.py:100 | +1 |
| 🟡 MINOR | Inconsistent naming | utils.py:20 | +0.3 |

| 🟢 CLEAN PASS | 5 |

### Evidence Score: 4.3
"""
        report = parse_evidence_findings(content, "Validator A")
        assert report is not None
        assert len(report.findings) == 3
        assert report.clean_passes == 5
        # 3.0 + 1.0 + 0.3 + (5 * -0.5) = 4.3 - 2.5 = 1.8
        assert report.total_score == 1.8

    def test_parse_bullet_format(self) -> None:
        """Test parsing Evidence Score bullet format."""
        content = _PAD + """
## Findings

- 🔴 **CRITICAL** (+3): SQL injection vulnerability [db.py:50]
- 🟠 **IMPORTANT** (+1): Missing rate limiting [api.py:30]
- 🟡 **MINOR** (+0.3): Unused import

CLEAN PASS: 2
"""
        report = parse_evidence_findings(content, "Validator B")
        assert report is not None
        assert len(report.findings) == 3
        assert report.clean_passes == 2
        # 3.0 + 1.0 + 0.3 + (2 * -0.5) = 4.3 - 1.0 = 3.3
        assert report.total_score == 3.3

    def test_parse_no_findings_returns_none(self) -> None:
        """Test that report with no parseable data returns None."""
        content = """
This is a validation report without any Evidence Score format.

Just plain text without structured findings.
"""
        report = parse_evidence_findings(content, "Validator C")
        assert report is None

    def test_parse_short_content_returns_none(self) -> None:
        """Test that short content (<2000 chars) returns None early without warning."""
        content = "Short validator output with no structure."
        assert len(content) < 2000
        report = parse_evidence_findings(content, "Validator Short")
        assert report is None

    def test_parse_table_with_high_medium_low_aliases(self) -> None:
        """Test parsing table format with HIGH/MEDIUM/LOW aliases."""
        content = _PAD + """
## Evidence Score Summary

| Severity | Description | Source | Score |
|----------|-------------|--------|-------|
| 🔴 HIGH | Missing input validation | auth.py:45 | +3 |
| 🟠 MEDIUM | No error handling | api.py:100 | +1 |
| 🟡 LOW | Inconsistent naming | utils.py:20 | +0.3 |
"""
        report = parse_evidence_findings(content, "Validator Alias")
        assert report is not None
        assert len(report.findings) == 3
        assert report.findings[0].severity == Severity.CRITICAL
        assert report.findings[1].severity == Severity.IMPORTANT
        assert report.findings[2].severity == Severity.MINOR

    def test_parse_section_header_fallback(self) -> None:
        """Test fallback parsing from section headers (## HIGH Severity, ### HIGH: desc)."""
        content = _PAD + """
# Code Review

## HIGH Severity Findings

### 1. Missing `From<std::io::Error>` for `StorageError`

**Issue:** Task 3 requires this impl but it's not present.

### 2. `expect()` in Production Code

**Issue:** Project context bans unwrap/expect.

## MEDIUM Severity Findings

### 1. Documentation Gap

**Issue:** Missing docs for new module.

## LOW Severity Findings

Nothing significant.
"""
        report = parse_evidence_findings(content, "Validator Section")
        assert report is not None
        # Should extract: 2 HIGH (CRITICAL) + 1 MEDIUM (IMPORTANT) findings
        # The "## HIGH Severity Findings" header itself has no description after colon
        # Only sub-headings with descriptions count
        assert len(report.findings) >= 1
        # Verify severity mapping
        severities = {f.severity for f in report.findings}
        assert Severity.CRITICAL in severities or Severity.IMPORTANT in severities

    def test_parse_section_header_with_description(self) -> None:
        """Test parsing headers like '### HIGH: Path Traversal Vulnerability'."""
        content = _PAD + """
# Code Review

### HIGH: Path Traversal Vulnerability for New Files
Some details here.

### MEDIUM: Incomplete Tree Permissions
Some details here.

### MEDIUM: Missing Task Completion
Some details here.

### LOW: Documentation Gap
Some details here.
"""
        report = parse_evidence_findings(content, "Validator Desc")
        assert report is not None
        assert len(report.findings) == 4
        # HIGH → CRITICAL (+3), 2×MEDIUM → IMPORTANT (+1 each), LOW → MINOR (+0.3)
        assert report.findings[0].severity == Severity.CRITICAL
        assert report.findings[0].description == "Path Traversal Vulnerability for New Files"
        assert report.findings[1].severity == Severity.IMPORTANT
        assert report.findings[3].severity == Severity.MINOR

    def test_parse_finding_number_dash_severity_format(self) -> None:
        """Test parsing '### Finding #1 — HIGH: description' format."""
        content = _PAD + """
### Finding #1 — HIGH: tempfile is a dev-dependency but used in public module
Details here.

### Finding #2 — MEDIUM: String-based check in resolve_path is fragile
Details here.
"""
        report = parse_evidence_findings(content, "Validator Finding")
        assert report is not None
        assert len(report.findings) == 2
        assert report.findings[0].severity == Severity.CRITICAL
        assert "tempfile" in report.findings[0].description
        assert report.findings[1].severity == Severity.IMPORTANT

    def test_parse_section_header_five_hashes(self) -> None:
        """Test parsing '##### HIGH Severity Findings (Must Fix)' format."""
        content = _PAD + """
##### HIGH Severity Findings (Must Fix)

Some details about high severity issues.

##### MEDIUM Severity Findings

Some medium details.
"""
        report = parse_evidence_findings(content, "Validator 5hash")
        assert report is not None
        assert len(report.findings) >= 2
        severities = [f.severity for f in report.findings]
        assert Severity.CRITICAL in severities
        assert Severity.IMPORTANT in severities

    def test_parse_section_header_bracketed_severity(self) -> None:
        """Test parsing '### [CRITICAL] Description here' format."""
        content = _PAD + """
### [CRITICAL] False Claim: Incomplete Passphrase Zeroing in CLI

Details about the critical issue.

### [HIGH] Missing Error Handling

Details about the high issue.
"""
        report = parse_evidence_findings(content, "Validator Bracket")
        assert report is not None
        assert len(report.findings) == 2
        assert report.findings[0].severity == Severity.CRITICAL
        assert report.findings[0].description == "False Claim: Incomplete Passphrase Zeroing in CLI"
        assert report.findings[1].severity == Severity.CRITICAL  # HIGH → CRITICAL

    def test_parse_section_header_issue_n_format(self) -> None:
        """Test parsing '### ISSUE-1 [HIGH] — Description' format."""
        content = _PAD + """
### ISSUE-1 [HIGH] — Passphrase handled as raw Vec<u8>

Details about issue 1.

### ISSUE-2 [MEDIUM] — Missing unit tests for edge cases

Details about issue 2.

### ISSUE-3 [LOW] — Documentation typo

Details about issue 3.
"""
        report = parse_evidence_findings(content, "Validator Issue")
        assert report is not None
        assert len(report.findings) == 3
        assert report.findings[0].severity == Severity.CRITICAL  # HIGH → CRITICAL
        assert "Passphrase" in report.findings[0].description
        assert report.findings[1].severity == Severity.IMPORTANT  # MEDIUM → IMPORTANT
        assert report.findings[2].severity == Severity.MINOR  # LOW → MINOR

    def test_parse_trailing_bracket_severity(self) -> None:
        """Test parsing '### ISSUE-1: Description [HIGH — Category]' format."""
        content = _PAD + """
## Findings

### ISSUE-1: Decrypted plaintext not zeroized in `migrate_file()` [HIGH — Security]

**File:** `encrypted.rs:180-198`

### ISSUE-2: Story file tasks all marked incomplete [HIGH — Process]

**Evidence:** All checkboxes unchecked.

### ISSUE-3: `println!` in documentation code example [MEDIUM — Code Quality]

Details about the medium issue.

### ISSUE-4: Stale TDD comment in integration tests [LOW — Documentation]

Details about the low issue.
"""
        report = parse_evidence_findings(content, "Validator Bracket-Trail")
        assert report is not None
        assert len(report.findings) == 4
        assert report.findings[0].severity == Severity.CRITICAL  # HIGH → CRITICAL
        assert "plaintext" in report.findings[0].description.lower()
        assert report.findings[1].severity == Severity.CRITICAL  # HIGH → CRITICAL
        assert report.findings[2].severity == Severity.IMPORTANT  # MEDIUM → IMPORTANT
        assert report.findings[3].severity == Severity.MINOR  # LOW → MINOR
        assert any("trailing-bracket" in w for w in report.parse_warnings)

    def test_parse_bold_severity_line(self) -> None:
        """Test parsing '**Severity:** HIGH' on separate lines below headers."""
        content = _PAD + """
## Findings

### ISSUE-1: `expect()` calls in production code

**Severity:** HIGH
**Location:** `main.rs:338, 341, 350`

### ISSUE-2: Double config loading

**Severity:** HIGH

### ISSUE-3: Missing data directory creation

**Severity:** MEDIUM

### ISSUE-4: Feature flag should be removed

**Severity:** LOW
"""
        report = parse_evidence_findings(content, "Validator Bold-Sev")
        assert report is not None
        assert len(report.findings) == 4
        assert report.findings[0].severity == Severity.CRITICAL  # HIGH → CRITICAL
        assert report.findings[1].severity == Severity.CRITICAL  # HIGH → CRITICAL
        assert report.findings[2].severity == Severity.IMPORTANT  # MEDIUM → IMPORTANT
        assert report.findings[3].severity == Severity.MINOR  # LOW → MINOR
        assert any("bold-severity" in w for w in report.parse_warnings)

    def test_parse_section_header_numbered_prefix(self) -> None:
        """Test parsing '### 1. HIGH: Description' format (bare numbered prefix)."""
        content = _PAD + """
# Code Review Report

## Findings Summary
- **HIGH**: Documentation completely missing (AC #6).
- **MEDIUM**: Incomplete MessagePack test coverage (AC #5.1).

## Detailed Findings

### 1. HIGH: Documentation Completely Missing (AC #6)
None of the documentation requirements have been implemented.

### 2. MEDIUM: Incomplete MessagePack Test Coverage (AC #5.1)
AC #5.1 explicitly requires MessagePack and JSON round-trip tests.

### 3. MEDIUM: Weak Assertions in Round-trip Tests
The unit tests perform shallow assertions.

### 4. LOW: `Attachment` Struct Lacks Serialization
While `AttachmentMetadata` is serializable, the `Attachment` struct is not.

### 5. LOW: Inconsistent Error Context in `ProviderError`
The error messages are less actionable.
"""
        report = parse_evidence_findings(content, "Validator Numbered")
        assert report is not None
        assert len(report.findings) == 5
        assert report.findings[0].severity == Severity.CRITICAL  # HIGH → CRITICAL
        assert "Documentation Completely Missing" in report.findings[0].description
        assert report.findings[1].severity == Severity.IMPORTANT  # MEDIUM → IMPORTANT
        assert report.findings[2].severity == Severity.IMPORTANT  # MEDIUM → IMPORTANT
        assert report.findings[3].severity == Severity.MINOR  # LOW → MINOR
        assert report.findings[4].severity == Severity.MINOR  # LOW → MINOR

    def test_parse_bold_list_severity(self) -> None:
        """Test parsing numbered/bulleted lists with bold severity labels."""
        content = _PAD + """
### Adversarial Code Review Report

**Findings:**

1.  **MEDIUM**: **Incomplete Story File List**.
    *   **Context**: The file list is missing entries.
    *   **Impact**: Incomplete transparency.

2.  **HIGH**: **Incomplete serde attribute application**.
    *   **Context**: AC 1.8 mandates serde(default).
    *   **Impact**: Potential deserialization failures.

3.  **MEDIUM**: **Missing field attributes**.
    *   **Context**: AC 2.3 specifies requirements.

4.  **HIGH**: **Incomplete workspace dependency setup**.
    *   **Context**: Task 1 is incomplete.

5.  **MEDIUM**: **Loss of error detail**.
    *   **Context**: Error chain is lost.

6.  **LOW**: **Incomplete newtype functionality**.
    *   **Context**: AC 1.3 omits Default.
"""
        report = parse_evidence_findings(content, "Validator BoldList")
        assert report is not None
        assert len(report.findings) == 6
        assert report.findings[0].severity == Severity.IMPORTANT  # MEDIUM → IMPORTANT
        assert report.findings[1].severity == Severity.CRITICAL  # HIGH → CRITICAL
        assert report.findings[2].severity == Severity.IMPORTANT  # MEDIUM → IMPORTANT
        assert report.findings[3].severity == Severity.CRITICAL  # HIGH → CRITICAL
        assert report.findings[4].severity == Severity.IMPORTANT  # MEDIUM → IMPORTANT
        assert report.findings[5].severity == Severity.MINOR  # LOW → MINOR
        assert any("bold-list" in w for w in report.parse_warnings)

    def test_parse_bold_list_bullet_format(self) -> None:
        """Test parsing '- **HIGH**: Description' bullet format."""
        content = _PAD + """
# Code Review

## Findings Summary
- **HIGH**: Documentation completely missing (AC #6).
- **MEDIUM**: Incomplete test coverage (AC #5.1).
- **MEDIUM**: Weak assertions in round-trip tests.
- **LOW**: Struct lacks serialization.
"""
        report = parse_evidence_findings(content, "Validator BulletBold")
        assert report is not None
        assert len(report.findings) == 4
        assert report.findings[0].severity == Severity.CRITICAL  # HIGH → CRITICAL
        assert report.findings[1].severity == Severity.IMPORTANT  # MEDIUM → IMPORTANT
        assert report.findings[3].severity == Severity.MINOR  # LOW → MINOR
        assert any("bold-list" in w for w in report.parse_warnings)

    def test_parse_only_clean_passes(self) -> None:
        """Test parsing report with only CLEAN PASS count."""
        content = _PAD + """
## Evidence Score

No issues found!

| 🟢 CLEAN PASS | 8 |

Evidence Score: -4.0
"""
        report = parse_evidence_findings(content, "Validator D")
        assert report is not None
        assert len(report.findings) == 0
        assert report.clean_passes == 8
        assert report.total_score == -4.0
        assert report.verdict == Verdict.EXCELLENT


# =============================================================================
# Aggregation Tests
# =============================================================================


class TestAggregateEvidenceScores:
    """Tests for aggregate_evidence_scores function."""

    def test_single_report_aggregate(self) -> None:
        """Test aggregation with single report."""
        findings = (
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Test critical",
                source="test.py:10",
                validator_id="Validator A",
            ),
        )
        report = EvidenceScoreReport(
            validator_id="Validator A",
            findings=findings,
            clean_passes=2,
            total_score=2.0,
            verdict=Verdict.PASS,
        )

        aggregate = aggregate_evidence_scores([report])

        assert aggregate.total_score == 2.0
        assert aggregate.verdict == Verdict.PASS
        assert aggregate.per_validator_scores == {"Validator A": 2.0}
        assert aggregate.total_findings == 1
        assert aggregate.consensus_ratio == 0.0  # Single validator = no consensus

    def test_multiple_reports_with_consensus(self) -> None:
        """Test aggregation with multiple reports having consensus findings."""
        # Both validators report similar critical issue
        findings_a = (
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Missing input validation",
                source="auth.py:45",
                validator_id="Validator A",
            ),
        )
        findings_b = (
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Missing input validation in auth",
                source="auth.py:45",
                validator_id="Validator B",
            ),
        )

        report_a = EvidenceScoreReport(
            validator_id="Validator A",
            findings=findings_a,
            clean_passes=2,
            total_score=2.0,
            verdict=Verdict.PASS,
        )
        report_b = EvidenceScoreReport(
            validator_id="Validator B",
            findings=findings_b,
            clean_passes=1,
            total_score=2.5,
            verdict=Verdict.PASS,
        )

        aggregate = aggregate_evidence_scores([report_a, report_b])

        assert aggregate.total_score == 2.2  # Average of 2.0 and 2.5 = 2.25, rounded to 2.2
        assert aggregate.total_findings == 1  # Deduplicated
        assert len(aggregate.consensus_findings) == 1  # Both validators agree
        assert len(aggregate.unique_findings) == 0
        assert aggregate.consensus_ratio == 1.0

    def test_empty_reports_raises_error(self) -> None:
        """Test that empty reports list raises AllValidatorsFailedError."""
        with pytest.raises(AllValidatorsFailedError):
            aggregate_evidence_scores([])

    def test_consensus_with_fuzzy_match_and_severity_replacement(self) -> None:
        """Test that consensus tracking survives severity replacement.

        When two findings are fuzzy-matched (similar but not identical descriptions)
        and the second has higher severity, the replacement must update consensus
        tracking to use the new finding's normalized_description.

        Regression test for bug where consensus_counts used old key but deduped
        list contained new finding with different normalized_description.
        """
        # Validator A: MINOR finding
        # SequenceMatcher ratio for "missing input validation" vs "missing input validation in auth"
        # is 2*24/(24+32) = 48/56 = 0.857 > 0.85 threshold
        findings_a = (
            EvidenceFinding(
                severity=Severity.MINOR,
                score=0.3,
                description="Missing input validation",  # Shorter version
                source="auth.py:45",
                validator_id="Validator A",
            ),
        )
        # Validator B: CRITICAL finding with similar but longer description
        findings_b = (
            EvidenceFinding(
                severity=Severity.CRITICAL,  # Higher severity - triggers replacement
                score=3.0,
                description="Missing input validation in auth",  # Similar but different
                source="auth.py:45",
                validator_id="Validator B",
            ),
        )

        report_a = EvidenceScoreReport(
            validator_id="Validator A",
            findings=findings_a,
            clean_passes=2,
            total_score=-0.7,  # 0.3 + (2 * -0.5) = 0.3 - 1.0 = -0.7
            verdict=Verdict.PASS,
        )
        report_b = EvidenceScoreReport(
            validator_id="Validator B",
            findings=findings_b,
            clean_passes=1,
            total_score=2.5,  # 3.0 + (1 * -0.5) = 3.0 - 0.5 = 2.5
            verdict=Verdict.PASS,
        )

        aggregate = aggregate_evidence_scores([report_a, report_b])

        # Key assertions:
        # 1. Findings should be deduplicated (fuzzy match)
        assert aggregate.total_findings == 1

        # 2. The CRITICAL finding should be kept (higher severity)
        assert aggregate.findings_by_severity[Severity.CRITICAL] == 1
        assert aggregate.findings_by_severity[Severity.MINOR] == 0

        # 3. CRITICAL: Consensus tracking must work after replacement
        # Both validators found the same issue, so it's consensus (not unique)
        assert len(aggregate.consensus_findings) == 1
        assert len(aggregate.unique_findings) == 0
        assert aggregate.consensus_ratio == 1.0

        # 4. The consensus finding should be the CRITICAL one
        assert aggregate.consensus_findings[0].severity == Severity.CRITICAL


# =============================================================================
# Format Context Tests
# =============================================================================


class TestFormatEvidenceScoreContext:
    """Tests for format_evidence_score_context function."""

    def test_format_validation_context(self) -> None:
        """Test formatting for validation synthesis context."""
        aggregate = EvidenceScoreAggregate(
            total_score=2.5,
            verdict=Verdict.PASS,
            per_validator_scores={"Validator A": 3.0, "Validator B": 2.0},
            per_validator_verdicts={
                "Validator A": Verdict.PASS,
                "Validator B": Verdict.PASS,
            },
            findings_by_severity={
                Severity.CRITICAL: 1,
                Severity.IMPORTANT: 2,
                Severity.MINOR: 1,
            },
            total_findings=4,
            total_clean_passes=3,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.5,
        )

        output = format_evidence_score_context(aggregate, "validation")

        assert "<!-- PRE-CALCULATED EVIDENCE SCORE" in output
        assert "**Total Score** | 2.5" in output
        assert "**Verdict** | READY" in output  # PASS -> READY for validation
        assert "CRITICAL findings | 1" in output
        assert "IMPORTANT findings | 2" in output
        assert "Consensus ratio | 50%" in output

    def test_format_code_review_context(self) -> None:
        """Test formatting for code review synthesis context."""
        aggregate = EvidenceScoreAggregate(
            total_score=-3.5,
            verdict=Verdict.EXCELLENT,
            per_validator_scores={"Reviewer A": -3.5},
            per_validator_verdicts={"Reviewer A": Verdict.EXCELLENT},
            findings_by_severity={
                Severity.CRITICAL: 0,
                Severity.IMPORTANT: 0,
                Severity.MINOR: 1,
            },
            total_findings=1,
            total_clean_passes=8,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.0,
        )

        output = format_evidence_score_context(aggregate, "code_review")

        assert "**Verdict** | EXEMPLARY" in output  # EXCELLENT -> EXEMPLARY for code review
        assert "CLEAN PASS categories | 8" in output


# =============================================================================
# Exception Tests
# =============================================================================


class TestCacheVersionError:
    """Tests for CacheVersionError exception."""

    def test_missing_version_message(self) -> None:
        """Test error message when version is missing."""
        error = CacheVersionError(found_version=None, required_version=2)
        assert "v2 required" in str(error)
        assert "missing" in str(error).lower()

    def test_old_version_message(self) -> None:
        """Test error message when version is too old."""
        error = CacheVersionError(found_version=1, required_version=2)
        assert "v2 required" in str(error)
        assert "1" in str(error)

    def test_custom_message(self) -> None:
        """Test custom error message."""
        error = CacheVersionError(
            found_version=1,
            required_version=2,
            message="Custom error message",
        )
        assert str(error) == "Custom error message"


class TestCacheFormatError:
    """Tests for CacheFormatError exception."""

    def test_error_message(self) -> None:
        """Test error message content."""
        error = CacheFormatError("Missing required key")
        assert "Missing required key" in str(error)


class TestAllValidatorsFailedError:
    """Tests for AllValidatorsFailedError exception."""

    def test_error_message(self) -> None:
        """Test error message content."""
        error = AllValidatorsFailedError("All validators failed")
        assert "All validators failed" in str(error)

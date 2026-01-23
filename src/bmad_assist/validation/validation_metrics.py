"""Deterministic metrics extraction from validation reports.

This module provides functions for extracting reproducible metrics from
Multi-LLM validation report markdown files. These metrics are calculated
deterministically via regex parsing, not LLM judgment.

Key features:
- Extract per-validator counts (critical/enhancement/optimization issues)
- Extract Evidence Score metrics (Deep Verify format)
- Calculate aggregate statistics across all validators
- Format metrics as markdown header for synthesis reports

Evidence Score System:
    The Evidence Score system is based on the Deep Verify methodology
    developed by @LKrysik (https://github.com/LKrysik/BMAD-METHOD).
    This rigorous validation framework provides:
    - Mathematical scoring: CRITICAL (+3), IMPORTANT (+1), MINOR (+0.3), CLEAN PASS (-0.5)
    - Deterministic verdict thresholds (≥6 REJECT, 4-6 REWORK, ≤3 READY, ≤-3 EXCELLENT)
    - Mandatory quote requirements ("no quote, no finding")
    - Anti-bias battery for LLM self-checks
    Thanks @LKrysik for making validation actually rigorous! 🎯

Public API:
    extract_validator_metrics: Parse single validation report
    calculate_aggregate_metrics: Aggregate across multiple validators
    format_deterministic_metrics_header: Format for synthesis report prepend
    ValidatorMetrics: Per-validator metrics dataclass
    AggregateMetrics: Cross-validator aggregate metrics dataclass
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from bmad_assist.validation.evidence_score import (
    EvidenceScoreReport,
    parse_evidence_findings,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Regex Patterns for Validation Report Parsing
# =============================================================================

# Issue counts from the "Issues Overview" table (legacy format, kept for compatibility)
# | 🚨 Critical Issues | 4 |
CRITICAL_PATTERN = re.compile(r"\|\s*🚨\s*Critical Issues\s*\|\s*(\d+)\s*\|", re.IGNORECASE)
ENHANCEMENT_PATTERN = re.compile(r"\|\s*⚡\s*Enhancements?\s*\|\s*(\d+)\s*\|", re.IGNORECASE)
OPTIMIZATION_PATTERN = re.compile(r"\|\s*✨\s*Optimizations?\s*\|\s*(\d+)\s*\|", re.IGNORECASE)
LLM_OPTIMIZATION_PATTERN = re.compile(
    r"\|\s*🤖\s*LLM Optimizations?\s*\|\s*(\d+)\s*\|", re.IGNORECASE
)

# Evidence Score finding counts (Deep Verify format)
CRITICAL_FINDING_PATTERN = re.compile(
    r"\|\s*🔴\s*CRITICAL\s*\|\s*(\d+)\s*\|", re.IGNORECASE
)
IMPORTANT_FINDING_PATTERN = re.compile(
    r"\|\s*🟠\s*IMPORTANT\s*\|\s*(\d+)\s*\|", re.IGNORECASE
)
MINOR_FINDING_PATTERN = re.compile(
    r"\|\s*🟡\s*MINOR\s*\|\s*(\d+)\s*\|", re.IGNORECASE
)
CLEAN_PASS_PATTERN = re.compile(
    r"\|\s*🟢\s*CLEAN PASS\s*\|\s*(\d+)\s*\|", re.IGNORECASE
)

# Evidence Score patterns (Deep Verify format)
EVIDENCE_SCORE_TABLE_PATTERN = re.compile(
    r"\|\s*Evidence Score\s*\|[^\|]*\|\s*\n\|[^\|]*\|\s*\*?\*?(-?\d+(?:\.\d+)?)\*?\*?\s*\|",
    re.IGNORECASE | re.MULTILINE,
)
EVIDENCE_SCORE_HEADING_PATTERN = re.compile(
    r"###?\s*Evidence Score:?\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE
)

# Evidence Score verdict pattern
EVIDENCE_VERDICT_PATTERN = re.compile(
    r"\|\s*\*?\*?-?\d+(?:\.\d+)?\*?\*?\s*\|\s*\*?\*?(REJECT|MAJOR REWORK|READY|EXCELLENT)\*?\*?\s*\|",
    re.IGNORECASE,
)

# INVEST violations count
INVEST_VIOLATION_PATTERN = re.compile(r"###\s*INVEST Violations", re.IGNORECASE)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True)
class ValidatorMetrics:
    """Metrics extracted from a single validation report.

    All counts are from the Issues Overview table.
    Uses Evidence Score format (Deep Verify methodology).
    """

    validator_id: str
    # Legacy issue counts (kept for backward compatibility with old reports)
    critical_count: int = 0
    enhancement_count: int = 0
    optimization_count: int = 0
    llm_optimization_count: int = 0
    verdict: str | None = None
    invest_violations: int = 0
    # Evidence Score fields (Deep Verify format)
    evidence_score: float | None = None  # Can be negative
    critical_finding_count: int = 0  # CRITICAL (+3)
    important_finding_count: int = 0  # IMPORTANT (+1)
    minor_finding_count: int = 0  # MINOR (+0.3)
    clean_pass_count: int = 0  # CLEAN PASS (-0.5)
    # Parsed Evidence Score report (from evidence_score.py)
    evidence_report: EvidenceScoreReport | None = None

    @property
    def total_findings(self) -> int:
        """Total findings across all categories (legacy)."""
        return (
            self.critical_count
            + self.enhancement_count
            + self.optimization_count
            + self.llm_optimization_count
        )

    @property
    def total_evidence_findings(self) -> int:
        """Total findings using Evidence Score categories."""
        return (
            self.critical_finding_count
            + self.important_finding_count
            + self.minor_finding_count
        )


@dataclass
class AggregateMetrics:
    """Aggregate metrics across all validators.

    Provides statistics and consensus indicators.
    Uses Evidence Score format exclusively.
    """

    validator_count: int = 0
    validators: list[ValidatorMetrics] = field(default_factory=list)

    # Evidence Score statistics (Deep Verify format)
    evidence_score_min: float | None = None
    evidence_score_max: float | None = None
    evidence_score_avg: float | None = None
    evidence_score_stdev: float | None = None

    # Category totals across all validators (legacy, kept for old report parsing)
    total_critical: int = 0
    total_enhancement: int = 0
    total_optimization: int = 0
    total_llm_optimization: int = 0
    total_findings: int = 0

    # Evidence Score category totals (Deep Verify format)
    total_critical_findings: int = 0  # CRITICAL (+3)
    total_important_findings: int = 0  # IMPORTANT (+1)
    total_minor_findings: int = 0  # MINOR (+0.3)
    total_clean_passes: int = 0  # CLEAN PASS (-0.5)
    total_evidence_findings: int = 0

    # Consensus indicators (how many validators found issues in each category)
    validators_with_critical: int = 0
    validators_with_enhancement: int = 0
    validators_with_optimization: int = 0

    # Evidence Score consensus
    validators_with_critical_findings: int = 0
    validators_with_important_findings: int = 0

    # Verdicts
    verdicts: list[str] = field(default_factory=list)


# =============================================================================
# Extraction Functions
# =============================================================================


def extract_validator_metrics(
    content: str,
    validator_id: str,
) -> ValidatorMetrics:
    """Extract metrics from a single validation report.

    Parses the markdown content of a validation report to extract:
    - Issue counts from the Issues Overview table (legacy)
    - Evidence Score (Deep Verify format)
    - Verdict
    - INVEST violations count
    - Evidence Score finding counts (CRITICAL/IMPORTANT/MINOR/CLEAN PASS)

    Args:
        content: Markdown content of validation report.
        validator_id: Identifier for this validator (e.g., "Validator A").

    Returns:
        ValidatorMetrics with extracted values.
        Missing values default to 0 or None.

    """
    # Extract legacy issue counts (Issues Overview table)
    critical = _extract_int(CRITICAL_PATTERN, content)
    enhancement = _extract_int(ENHANCEMENT_PATTERN, content)
    optimization = _extract_int(OPTIMIZATION_PATTERN, content)
    llm_opt = _extract_int(LLM_OPTIMIZATION_PATTERN, content)

    # Extract Evidence Score finding counts (Deep Verify format)
    critical_finding = _extract_int(CRITICAL_FINDING_PATTERN, content)
    important_finding = _extract_int(IMPORTANT_FINDING_PATTERN, content)
    minor_finding = _extract_int(MINOR_FINDING_PATTERN, content)
    clean_pass = _extract_int(CLEAN_PASS_PATTERN, content)

    # Extract Evidence Score (try heading first, then table)
    evidence_score = _extract_float(EVIDENCE_SCORE_HEADING_PATTERN, content)
    if evidence_score is None:
        evidence_score = _extract_float(EVIDENCE_SCORE_TABLE_PATTERN, content)

    # Extract verdict (Evidence Score format)
    verdict_match = EVIDENCE_VERDICT_PATTERN.search(content)
    verdict = verdict_match.group(1).strip().upper() if verdict_match else None

    # Count INVEST violations (count bullet points after "### INVEST Violations")
    invest_violations = _count_invest_violations(content)

    # Parse Evidence Score report using evidence_score.py module
    evidence_report = parse_evidence_findings(content, validator_id)

    return ValidatorMetrics(
        validator_id=validator_id,
        critical_count=critical,
        enhancement_count=enhancement,
        optimization_count=optimization,
        llm_optimization_count=llm_opt,
        verdict=verdict,
        invest_violations=invest_violations,
        evidence_score=evidence_score,
        critical_finding_count=critical_finding,
        important_finding_count=important_finding,
        minor_finding_count=minor_finding,
        clean_pass_count=clean_pass,
        evidence_report=evidence_report,
    )


def _extract_int(pattern: re.Pattern[str], content: str) -> int:
    """Extract integer from regex match, return 0 if not found."""
    match = pattern.search(content)
    if match:
        try:
            return int(match.group(1))
        except (ValueError, IndexError):
            pass
    return 0


def _extract_float(pattern: re.Pattern[str], content: str) -> float | None:
    """Extract float from regex match, return None if not found."""
    match = pattern.search(content)
    if match:
        try:
            return float(match.group(1))
        except (ValueError, IndexError):
            pass
    return None


def _count_invest_violations(content: str) -> int:
    """Count INVEST violation bullet points."""
    # Find "### INVEST Violations" section
    match = INVEST_VIOLATION_PATTERN.search(content)
    if not match:
        return 0

    # Get content after the heading until next section
    start = match.end()
    next_section = re.search(r"\n###?\s+", content[start:])
    if next_section:
        section_content = content[start : start + next_section.start()]
    else:
        section_content = content[start:]

    # Count lines starting with "- " (bullet points)
    violations = re.findall(r"^-\s+", section_content, re.MULTILINE)
    return len(violations)


# =============================================================================
# Aggregation Functions
# =============================================================================


def calculate_aggregate_metrics(
    validators: list[ValidatorMetrics],
) -> AggregateMetrics:
    """Calculate aggregate metrics across multiple validators.

    Computes:
    - Score statistics (min, max, avg, stdev) for Evidence Score
    - Category totals
    - Consensus indicators

    Args:
        validators: List of ValidatorMetrics from each validator.

    Returns:
        AggregateMetrics with computed statistics.

    """
    if not validators:
        return AggregateMetrics()

    # Collect Evidence Scores (excluding None)
    evidence_scores = [v.evidence_score for v in validators if v.evidence_score is not None]

    # Calculate Evidence Score statistics
    evidence_score_min = min(evidence_scores) if evidence_scores else None
    evidence_score_max = max(evidence_scores) if evidence_scores else None
    evidence_score_avg = statistics.mean(evidence_scores) if evidence_scores else None
    evidence_score_stdev = (
        statistics.stdev(evidence_scores) if len(evidence_scores) >= 2 else None
    )

    # Sum legacy category totals
    total_critical = sum(v.critical_count for v in validators)
    total_enhancement = sum(v.enhancement_count for v in validators)
    total_optimization = sum(v.optimization_count for v in validators)
    total_llm_optimization = sum(v.llm_optimization_count for v in validators)
    total_findings = sum(v.total_findings for v in validators)

    # Sum Evidence Score category totals
    total_critical_findings = sum(v.critical_finding_count for v in validators)
    total_important_findings = sum(v.important_finding_count for v in validators)
    total_minor_findings = sum(v.minor_finding_count for v in validators)
    total_clean_passes = sum(v.clean_pass_count for v in validators)
    total_evidence_findings = sum(v.total_evidence_findings for v in validators)

    # Count validators with findings in each category (legacy)
    validators_with_critical = sum(1 for v in validators if v.critical_count > 0)
    validators_with_enhancement = sum(1 for v in validators if v.enhancement_count > 0)
    validators_with_optimization = sum(1 for v in validators if v.optimization_count > 0)

    # Count validators with Evidence Score findings
    validators_with_critical_findings = sum(
        1 for v in validators if v.critical_finding_count > 0
    )
    validators_with_important_findings = sum(
        1 for v in validators if v.important_finding_count > 0
    )

    # Collect verdicts
    verdicts = [v.verdict for v in validators if v.verdict]

    return AggregateMetrics(
        validator_count=len(validators),
        validators=validators,
        evidence_score_min=evidence_score_min,
        evidence_score_max=evidence_score_max,
        evidence_score_avg=evidence_score_avg,
        evidence_score_stdev=evidence_score_stdev,
        total_critical=total_critical,
        total_enhancement=total_enhancement,
        total_optimization=total_optimization,
        total_llm_optimization=total_llm_optimization,
        total_findings=total_findings,
        total_critical_findings=total_critical_findings,
        total_important_findings=total_important_findings,
        total_minor_findings=total_minor_findings,
        total_clean_passes=total_clean_passes,
        total_evidence_findings=total_evidence_findings,
        validators_with_critical=validators_with_critical,
        validators_with_enhancement=validators_with_enhancement,
        validators_with_optimization=validators_with_optimization,
        validators_with_critical_findings=validators_with_critical_findings,
        validators_with_important_findings=validators_with_important_findings,
        verdicts=verdicts,
    )


# =============================================================================
# Formatting Functions
# =============================================================================


def format_deterministic_metrics_header(
    aggregate: AggregateMetrics,
) -> str:
    """Format aggregate metrics as markdown header for synthesis report.

    Creates a structured markdown section to prepend to synthesis output.
    This provides deterministic metrics calculated from validation reports.
    Uses Evidence Score format.

    Args:
        aggregate: AggregateMetrics to format.

    Returns:
        Markdown string with formatted metrics.

    """
    lines = [
        "<!-- DETERMINISTIC_METRICS_START -->",
        "## Validation Metrics (Deterministic)",
        "",
        "These metrics are calculated deterministically from validator reports.",
        "",
        "### Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Validators | {aggregate.validator_count} |",
    ]

    # Evidence Score statistics (Deep Verify format)
    if aggregate.evidence_score_avg is not None:
        lines.append(f"| Evidence Score (avg) | {aggregate.evidence_score_avg:.2f} |")
    if aggregate.evidence_score_min is not None and aggregate.evidence_score_max is not None:
        lines.append(
            f"| Evidence Score (range) | {aggregate.evidence_score_min:.2f} - "
            f"{aggregate.evidence_score_max:.2f} |"
        )
    if aggregate.evidence_score_stdev is not None:
        lines.append(f"| Evidence Score (stdev) | {aggregate.evidence_score_stdev:.2f} |")

    # Helper for category rows
    vc = aggregate.validator_count

    # Evidence Score format findings
    crit_ev = f"{aggregate.validators_with_critical_findings}/{vc}"
    imp_ev = f"{aggregate.validators_with_important_findings}/{vc}"

    lines.extend(
        [
            f"| Total findings | {aggregate.total_evidence_findings} |",
            "",
            "### Evidence Score Findings by Severity",
            "",
            "| Severity | Score Impact | Total | Validators Reporting |",
            "|----------|--------------|-------|---------------------|",
            f"| 🔴 CRITICAL | +3 | {aggregate.total_critical_findings} | {crit_ev} |",
            f"| 🟠 IMPORTANT | +1 | {aggregate.total_important_findings} | {imp_ev} |",
            f"| 🟡 MINOR | +0.3 | {aggregate.total_minor_findings} | - |",
            f"| 🟢 CLEAN PASS | -0.5 | {aggregate.total_clean_passes} | - |",
            "",
            "### Per-Validator Breakdown (Evidence Score)",
            "",
            "| Validator | E-Score | CRITICAL | IMPORTANT | MINOR | CLEAN | Verdict |",
            "|-----------|---------|----------|-----------|-------|-------|---------|",
        ]
    )

    for v in aggregate.validators:
        score_str = f"{v.evidence_score:.2f}" if v.evidence_score is not None else "-"
        verdict_str = v.verdict or "-"
        lines.append(
            f"| {v.validator_id} | {score_str} | {v.critical_finding_count} | "
            f"{v.important_finding_count} | {v.minor_finding_count} | "
            f"{v.clean_pass_count} | {verdict_str} |"
        )

    # Verdicts summary
    if aggregate.verdicts:
        lines.extend(
            [
                "",
                "### Verdicts",
                "",
            ]
        )
        for i, verdict in enumerate(aggregate.verdicts):
            if i < len(aggregate.validators):
                vid = aggregate.validators[i].validator_id
            else:
                vid = f"Validator {i + 1}"
            lines.append(f"- **{vid}**: {verdict}")

    lines.extend(
        [
            "",
            "<!-- DETERMINISTIC_METRICS_END -->",
            "",
            "",  # Extra blank line for separation from synthesis content
        ]
    )

    return "\n".join(lines)


def extract_metrics_from_validation_files(
    validation_files: list[Path],
) -> AggregateMetrics:
    """Extract and aggregate metrics from validation report files.

    Convenience function that reads files, extracts per-validator metrics,
    and computes aggregate statistics.

    Args:
        validation_files: List of paths to validation report markdown files.

    Returns:
        AggregateMetrics with all computed statistics.

    """
    validators: list[ValidatorMetrics] = []

    for file_path in validation_files:
        try:
            content = file_path.read_text(encoding="utf-8")

            # Extract validator ID from filename or content
            # New format: validation-{epic}-{story}-{role_id}-{timestamp}.md
            # where role_id is single letter (a, b, c...)
            # Legacy format: validation-{epic}-{story}-{validator_id}-{timestamp}.md
            parts = file_path.stem.split("-")
            if len(parts) >= 4:
                raw_id = "-".join(parts[3:-1]) if len(parts) > 4 else parts[3]
                # Check if it's new format (single letter)
                if len(raw_id) == 1 and raw_id.isalpha():
                    # Convert single letter to display format: "a" -> "Validator A"
                    validator_id = f"Validator {raw_id.upper()}"
                else:
                    # Legacy format: "validator-a" -> "Validator A"
                    validator_id = raw_id.replace("-", " ").title()
            else:
                validator_id = file_path.stem

            metrics = extract_validator_metrics(content, validator_id)
            validators.append(metrics)

            logger.debug(
                "Extracted metrics from %s: evidence_score=%s, critical=%d, total=%d",
                file_path.name,
                metrics.evidence_score,
                metrics.critical_finding_count,
                metrics.total_evidence_findings,
            )

        except Exception as e:
            logger.warning("Failed to extract metrics from %s: %s", file_path, e)

    return calculate_aggregate_metrics(validators)

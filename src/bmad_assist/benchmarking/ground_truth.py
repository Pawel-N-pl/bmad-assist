"""Ground truth module for post-hoc validation accuracy measurement.

This module provides functionality to:
- Parse code review output to extract actual issues found
- Match validation findings to code review issues using fuzzy matching
- Calculate precision/recall metrics for validation accuracy
- Update evaluation records with ground truth data
- Support amendments when later phases reveal additional information

Public API:
    populate_ground_truth: Populate ground truth from code review output
    amend_ground_truth: Apply amendment to existing ground truth
    calculate_precision_recall: Calculate precision/recall from ground truth
    GroundTruthUpdate: Result dataclass for ground truth population
    GroundTruthError: Exception for ground truth operations
    CodeReviewFinding: Dataclass for code review findings
    ValidationFinding: Dataclass for validation findings
"""

import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from bmad_assist.benchmarking.schema import (
    Amendment,
    BenchmarkingError,
    ConsensusData,
    EvaluatorRole,
    GroundTruth,
    LLMEvaluationRecord,
)
from bmad_assist.benchmarking.storage import (
    RecordFilters,
    StorageError,
    list_evaluation_records,
    load_evaluation_record,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Severity and Category Classification Patterns
# =============================================================================

# Severity keywords - order matters (most specific first)
SEVERITY_PATTERNS: dict[str, re.Pattern[str]] = {
    "critical": re.compile(
        r"\b(?:critical|blocker|security\s+vulnerability|data\s+loss)\b", re.IGNORECASE
    ),
    "major": re.compile(r"\b(?:major|significant|important|breaking)\b", re.IGNORECASE),
    "minor": re.compile(r"\b(?:minor|small|low\s+priority)\b", re.IGNORECASE),
    "nit": re.compile(r"\b(?:nit|nitpick|style|formatting|trivial)\b", re.IGNORECASE),
}

# Category keywords
CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {
    "security": re.compile(
        r"\b(?:security|auth|injection|xss|csrf|vulnerable|attack)\b", re.IGNORECASE
    ),
    "performance": re.compile(
        r"\b(?:performance|slow|optimize|cache|memory|n\+1)\b", re.IGNORECASE
    ),
    "completeness": re.compile(r"\b(?:missing|incomplete|not\s+implemented|todo)\b", re.IGNORECASE),
    "correctness": re.compile(r"\b(?:bug|incorrect|wrong|error|broken|fails?)\b", re.IGNORECASE),
    "maintainability": re.compile(
        r"\b(?:refactor(?:ing)?|clean\s+up|readab(?:le|ility)|duplicate|complexity)\b",
        re.IGNORECASE,
    ),
}

# Section headers that contain findings
FINDING_HEADER_PATTERN = re.compile(
    r"^#{1,3}\s*(?:issues?|problems?|findings?|concerns?|bugs?|action\s+items?|"
    r"what\s+(?:needs|to)\s+(?:be\s+)?(?:fixed|changed|improved)|required\s+changes?)",
    re.IGNORECASE | re.MULTILINE,
)

# List item patterns (numbered or bulleted)
NUMBERED_LIST_PATTERN = re.compile(r"^\s*(\d+)\.\s+(.+)$")
BULLET_LIST_PATTERN = re.compile(r"^\s*[-*]\s+(.+)$")
NESTED_LIST_PATTERN = re.compile(r"^\s{2,}")  # Detect indentation for nested items

__all__ = [
    "GroundTruthError",
    "CodeReviewFinding",
    "ValidationFinding",
    "GroundTruthUpdate",
    "populate_ground_truth",
    "amend_ground_truth",
    "calculate_precision_recall",
]


class GroundTruthError(BenchmarkingError):
    """Ground truth operation failed.

    Raised when:
    - Code review parsing fails
    - Finding matching fails
    - Record update fails
    """

    pass


@dataclass(frozen=True)
class CodeReviewFinding:
    """A finding extracted from code review output.

    Attributes:
        description: Raw finding text.
        severity: One of "critical", "major", "minor", "nit", or None.
        category: One of "security", "performance", "completeness",
            "correctness", "maintainability", or None.

    """

    description: str
    severity: str | None
    category: str | None


@dataclass(frozen=True)
class ValidationFinding:
    """A finding extracted from validation report.

    Attributes:
        description: Raw finding text from validation report.
        severity: One of "critical", "major", "minor", "nit", or None.
        category: One of "security", "performance", "completeness",
            "correctness", "maintainability", or None.

    """

    description: str
    severity: str | None
    category: str | None


@dataclass(frozen=True)
class GroundTruthUpdate:
    """Result of populating ground truth for a single record.

    Attributes:
        record_id: Unique identifier of the updated record.
        record_path: Path to the updated record file.
        ground_truth: The populated GroundTruth object.

    """

    record_id: str
    record_path: Path
    ground_truth: GroundTruth


# =============================================================================
# Private Helper Functions - Classification
# =============================================================================


def _classify_severity(text: str) -> str | None:
    """Classify severity from finding text.

    Args:
        text: Finding description text.

    Returns:
        Severity string or None if not detected.

    """
    for severity, pattern in SEVERITY_PATTERNS.items():
        if pattern.search(text):
            return severity
    return None


def _classify_category(text: str) -> str | None:
    """Classify category from finding text.

    Args:
        text: Finding description text.

    Returns:
        Category string or None if not detected.

    """
    for category, pattern in CATEGORY_PATTERNS.items():
        if pattern.search(text):
            return category
    return None


# =============================================================================
# Private Helper Functions - Code Review Extraction
# =============================================================================


def _extract_code_review_findings(code_review_output: str) -> list[CodeReviewFinding]:
    """Extract findings from code review markdown output.

    Parses sections like "## Issues Found", "## Problems", "## Findings"
    and extracts list items as individual findings.

    Args:
        code_review_output: Raw code review markdown.

    Returns:
        List of CodeReviewFinding instances.

    """
    if not code_review_output or not code_review_output.strip():
        return []

    findings: list[CodeReviewFinding] = []
    lines = code_review_output.split("\n")
    in_finding_section = False

    for line in lines:
        # Check for finding section headers
        if FINDING_HEADER_PATTERN.match(line):
            in_finding_section = True
            continue

        # Check for other section headers (exit finding section)
        if line.startswith("#") and not FINDING_HEADER_PATTERN.match(line):
            in_finding_section = False
            continue

        if not in_finding_section:
            continue

        # Skip nested list items
        if NESTED_LIST_PATTERN.match(line):
            continue

        # Extract from numbered lists
        numbered_match = NUMBERED_LIST_PATTERN.match(line)
        if numbered_match:
            description = numbered_match.group(2).strip()
            findings.append(
                CodeReviewFinding(
                    description=description,
                    severity=_classify_severity(description),
                    category=_classify_category(description),
                )
            )
            continue

        # Extract from bullet lists
        bullet_match = BULLET_LIST_PATTERN.match(line)
        if bullet_match:
            description = bullet_match.group(1).strip()
            findings.append(
                CodeReviewFinding(
                    description=description,
                    severity=_classify_severity(description),
                    category=_classify_category(description),
                )
            )

    return findings


# =============================================================================
# Private Helper Functions - Validation Report Extraction
# =============================================================================

# Validation report section patterns with severity mapping
VALIDATION_SECTION_SEVERITY: dict[re.Pattern[str], str] = {
    re.compile(r"🚨\s*Critical", re.IGNORECASE): "critical",
    re.compile(r"⚡\s*Enhancement", re.IGNORECASE): "major",
    re.compile(r"✨\s*Optimization", re.IGNORECASE): "minor",
}

# Individual finding header pattern (### 1. Title format)
VALIDATION_FINDING_PATTERN = re.compile(r"^###\s*\d+\.\s*(.+)$")


def _extract_validation_findings(
    report_path: Path, content: str | None = None
) -> list[ValidationFinding]:
    """Extract findings from validation report markdown.

    Parses sections like "## 🚨 Critical Issues", "## ⚡ Enhancement",
    and extracts individual findings from ### headers.

    Args:
        report_path: Path to validation report file.
        content: Optional pre-loaded content (for testing).

    Returns:
        List of ValidationFinding instances.

    """
    if content is None:
        try:
            content = report_path.read_text()
        except OSError as e:
            logger.error("Failed to read validation report %s: %s", report_path, e)
            return []

    if not content or not content.strip():
        return []

    findings: list[ValidationFinding] = []
    lines = content.split("\n")
    current_severity: str | None = None

    for line in lines:
        # Detect severity from section headers
        for pattern, severity in VALIDATION_SECTION_SEVERITY.items():
            if pattern.search(line):
                current_severity = severity
                break

        # Extract individual findings from ### headers
        finding_match = VALIDATION_FINDING_PATTERN.match(line)
        if finding_match:
            title = finding_match.group(1).strip()
            category = _classify_category(title)
            findings.append(
                ValidationFinding(
                    description=title,
                    severity=current_severity,
                    category=category,
                )
            )

    return findings


def _find_validation_report_for_record(
    record: LLMEvaluationRecord,
    sprint_artifacts_dir: Path,
) -> Path | None:
    """Find the validation report file for a validator record.

    Matches by provider name pattern in filename.

    Args:
        record: Evaluation record for the validator.
        sprint_artifacts_dir: Directory containing sprint artifacts.

    Returns:
        Path to validation report, or None if not found.

    """
    story_key = f"{record.story.epic_num}-{record.story.story_num}"
    validations_dir = sprint_artifacts_dir / "story-validations"

    if not validations_dir.exists():
        return None

    # Match by provider name
    provider_pattern = f"story-validation-{story_key}-{record.evaluator.provider}*"
    matches = list(validations_dir.glob(provider_pattern))

    if not matches:
        return None

    # Return most recent if multiple
    return max(matches, key=lambda p: p.stat().st_mtime)


# =============================================================================
# Private Helper Functions - Finding Matching
# =============================================================================

# Matching thresholds
MATCH_THRESHOLD = 0.6
UNCERTAIN_LOW = 0.6
UNCERTAIN_HIGH = 0.75


def _calculate_similarity(s1: str, s2: str) -> float:
    """Calculate string similarity using SequenceMatcher.

    Args:
        s1: First string.
        s2: Second string.

    Returns:
        Similarity ratio between 0.0 and 1.0.

    """
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def _calculate_combined_score(
    v_desc: str,
    v_category: str | None,
    v_severity: str | None,
    cr_finding: CodeReviewFinding,
) -> float:
    """Calculate combined matching score with category/severity boosts.

    Args:
        v_desc: Validation finding description.
        v_category: Validation finding category.
        v_severity: Validation finding severity.
        cr_finding: Code review finding to compare.

    Returns:
        Combined score capped at 1.0.

    """
    # Primary: fuzzy string similarity
    base_score = _calculate_similarity(v_desc, cr_finding.description)

    # Secondary: category boost (+0.1)
    if v_category and cr_finding.category and v_category.lower() == cr_finding.category.lower():
        base_score += 0.1

    # Tertiary: severity boost (+0.05)
    if v_severity and cr_finding.severity and v_severity.lower() == cr_finding.severity.lower():
        base_score += 0.05

    return min(base_score, 1.0)


MatchResult = tuple[
    list[tuple[int, int]],  # matched pairs (validation_idx, code_review_idx)
    list[int],  # unmatched validation indices
    list[int],  # unmatched code review indices
]


def _match_findings(
    validation_findings: list[ValidationFinding],
    code_review_findings: list[CodeReviewFinding],
) -> MatchResult:
    """Match validation findings to code review findings.

    Uses fuzzy matching with category/severity boosts.
    Greedy 1:1 assignment by descending combined score.

    Args:
        validation_findings: Findings from validation report.
        code_review_findings: Findings from code review.

    Returns:
        Tuple of (matched, unmatched_validation, unmatched_code_review).

    """
    # Pre-filter empty descriptions
    valid_v_indices = [
        i for i, vf in enumerate(validation_findings) if vf.description and vf.description.strip()
    ]
    valid_cr_indices = [
        i for i, cf in enumerate(code_review_findings) if cf.description and cf.description.strip()
    ]

    skipped_v = len(validation_findings) - len(valid_v_indices)
    skipped_cr = len(code_review_findings) - len(valid_cr_indices)
    if skipped_v or skipped_cr:
        logger.debug(
            "Skipped %d validation, %d code review findings with empty descriptions",
            skipped_v,
            skipped_cr,
        )

    # Build similarity matrix with combined scores
    similarities: list[tuple[float, int, int]] = []
    for v_idx in valid_v_indices:
        vf = validation_findings[v_idx]
        for cr_idx in valid_cr_indices:
            cf = code_review_findings[cr_idx]
            score = _calculate_combined_score(vf.description, vf.category, vf.severity, cf)
            if score >= MATCH_THRESHOLD:
                similarities.append((score, v_idx, cr_idx))

    # Greedy matching by descending combined score
    similarities.sort(reverse=True)
    matched: list[tuple[int, int]] = []
    used_validation: set[int] = set()
    used_code_review: set[int] = set()

    for score, v_idx, cr_idx in similarities:
        if v_idx not in used_validation and cr_idx not in used_code_review:
            matched.append((v_idx, cr_idx))
            used_validation.add(v_idx)
            used_code_review.add(cr_idx)

            if UNCERTAIN_LOW <= score < UNCERTAIN_HIGH:
                logger.warning(
                    "Uncertain match (%.2f): '%s' <-> '%s'",
                    score,
                    validation_findings[v_idx].description[:50],
                    code_review_findings[cr_idx].description[:50],
                )

    # Unmatched (only from valid indices)
    unmatched_validation = [i for i in valid_v_indices if i not in used_validation]
    unmatched_code_review = [i for i in valid_cr_indices if i not in used_code_review]

    return matched, unmatched_validation, unmatched_code_review


def _atomic_update_record(record_path: Path, record: LLMEvaluationRecord) -> None:
    """Atomically update a record file.

    Args:
        record_path: Path to record file.
        record: Updated record to save.

    Raises:
        GroundTruthError: If write fails.

    """
    temp_path = record_path.with_suffix(".yaml.tmp")

    try:
        data = record.model_dump(mode="json")
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )
        os.replace(temp_path, record_path)
    except OSError as e:
        if temp_path.exists():
            temp_path.unlink()
        raise GroundTruthError(f"Failed to update record {record_path}: {e}") from e


def populate_ground_truth(
    epic_num: int,
    story_num: int | str,
    code_review_output: str,
    base_dir: Path,
) -> list[GroundTruthUpdate]:
    """Populate ground truth from code review output.

    For each VALIDATOR record for the story:
    1. Loads corresponding validation report
    2. Extracts validation finding descriptions
    3. Parses code review output for findings
    4. Matches findings using fuzzy matching
    5. Calculates precision/recall metrics
    6. Updates record atomically

    After all validators: updates synthesizer consensus fields.

    Args:
        epic_num: Epic number.
        story_num: Story number within epic.
        code_review_output: Raw code review markdown output.
        base_dir: Base directory for storage.

    Returns:
        List of GroundTruthUpdate for each updated record.

    Raises:
        GroundTruthError: If critical operation fails.

    """
    updates: list[GroundTruthUpdate] = []

    # Extract code review findings once (shared across all validators)
    cr_findings = _extract_code_review_findings(code_review_output)
    logger.info(
        "Extracted %d findings from code review for story %s.%s",
        len(cr_findings),
        epic_num,
        story_num,
    )

    # Get all records for this story
    try:
        summaries = list_evaluation_records(
            base_dir,
            RecordFilters(epic=epic_num, story=story_num),
        )
    except StorageError as e:
        logger.warning("Failed to list records for story %s.%s: %s", epic_num, story_num, e)
        return []

    if not summaries:
        logger.warning("No evaluation records found for story %s.%s", epic_num, story_num)
        return []

    # Separate validators and synthesizer
    validator_summaries = []
    synthesizer_summary = None

    for summary in summaries:
        # Load to check role
        try:
            record = load_evaluation_record(summary.path)
            if record.evaluator.role == EvaluatorRole.VALIDATOR:
                validator_summaries.append((summary, record))
            elif record.evaluator.role == EvaluatorRole.SYNTHESIZER:
                synthesizer_summary = (summary, record)
        except StorageError as e:
            logger.warning("Failed to load record %s: %s", summary.path, e)
            continue

    if not validator_summaries:
        logger.warning("No VALIDATOR records found for story %s.%s", epic_num, story_num)
        return []

    # Process each validator
    aggregate_confirmed = 0
    aggregate_false_alarm = 0
    aggregate_missed = 0

    for summary, record in validator_summaries:
        try:
            # Check if already populated
            if record.ground_truth and record.ground_truth.populated:
                logger.warning(
                    "Ground truth already populated for record %s, overwriting",
                    record.record_id,
                )

            # Find validation report for this validator
            report_path = _find_validation_report_for_record(record, base_dir)
            if report_path is None:
                logger.error(
                    "Validation report not found for validator %s (provider: %s), skipping",
                    record.record_id,
                    record.evaluator.provider,
                )
                continue

            # Extract validation findings
            v_findings = _extract_validation_findings(report_path)
            logger.debug(
                "Extracted %d findings from validation report %s",
                len(v_findings),
                report_path,
            )

            # Match findings
            matched, unmatched_v, unmatched_cr = _match_findings(v_findings, cr_findings)

            findings_confirmed = len(matched)
            findings_false_alarm = len(unmatched_v)
            issues_missed = len(unmatched_cr)

            # Calculate precision/recall
            temp_gt = GroundTruth(
                populated=True,
                findings_confirmed=findings_confirmed,
                findings_false_alarm=findings_false_alarm,
                issues_missed=issues_missed,
            )
            precision, recall = calculate_precision_recall(temp_gt)

            # Create ground truth
            ground_truth = GroundTruth(
                populated=True,
                populated_at=datetime.now(UTC),
                findings_confirmed=findings_confirmed,
                findings_false_alarm=findings_false_alarm,
                issues_missed=issues_missed,
                precision=precision,
                recall=recall,
                amendments=[],
                last_updated_at=None,
            )

            # Update record
            updated_record = record.model_copy(update={"ground_truth": ground_truth})

            # Atomic write
            _atomic_update_record(summary.path, updated_record)

            logger.info(
                "Updated ground truth for record %s: confirmed=%d, false_alarm=%d, "
                "missed=%d, precision=%.2f, recall=%s",
                record.record_id,
                findings_confirmed,
                findings_false_alarm,
                issues_missed,
                precision if precision is not None else 0.0,
                f"{recall:.2f}" if recall is not None else "N/A",
            )

            updates.append(
                GroundTruthUpdate(
                    record_id=record.record_id,
                    record_path=summary.path,
                    ground_truth=ground_truth,
                )
            )

            # Aggregate for synthesizer consensus
            aggregate_confirmed += findings_confirmed
            aggregate_false_alarm += findings_false_alarm
            aggregate_missed += issues_missed

        except GroundTruthError as e:
            logger.error(
                "Failed to process validator record %s: %s, skipping",
                record.record_id,
                e,
            )
            continue

    # Update synthesizer consensus if exists
    if synthesizer_summary:
        synth_summary, synth_record = synthesizer_summary

        if synth_record.consensus is not None:
            # Update consensus with aggregate data
            updated_consensus = ConsensusData(
                agreed_findings=synth_record.consensus.agreed_findings,
                unique_findings=synth_record.consensus.unique_findings,
                disputed_findings=synth_record.consensus.disputed_findings,
                missed_findings=aggregate_missed,
                agreement_score=synth_record.consensus.agreement_score,
                false_positive_count=aggregate_false_alarm,
            )

            updated_synth = synth_record.model_copy(update={"consensus": updated_consensus})
            _atomic_update_record(synth_summary.path, updated_synth)

            logger.info(
                "Updated synthesizer consensus for record %s: missed=%d, false_positive=%d",
                synth_record.record_id,
                aggregate_missed,
                aggregate_false_alarm,
            )
        else:
            logger.warning(
                "Synthesizer record %s has no consensus data, skipping update",
                synth_record.record_id,
            )
    else:
        logger.warning("No SYNTHESIZER record found for story %s.%s", epic_num, story_num)

    return updates


def amend_ground_truth(
    record_path: Path,
    amendment: Amendment,
) -> None:
    """Apply amendment to existing ground truth.

    Updates the ground truth counts based on delta values in the amendment,
    recalculates precision/recall, appends the amendment to the list,
    and atomically updates the record.

    Args:
        record_path: Path to the evaluation record.
        amendment: Amendment to apply.

    Raises:
        GroundTruthError: If record not found, ground truth not populated,
            or update fails.

    """
    # Load record
    try:
        record = load_evaluation_record(record_path)
    except StorageError as e:
        raise GroundTruthError(f"Record not found: {record_path}") from e

    # Check ground truth exists and is populated
    if record.ground_truth is None or not record.ground_truth.populated:
        raise GroundTruthError(f"Ground truth not populated for record {record.record_id}")

    # Apply deltas with clamping to non-negative
    new_confirmed = max(0, record.ground_truth.findings_confirmed + amendment.delta_confirmed)
    new_missed = max(0, record.ground_truth.issues_missed + amendment.delta_missed)

    # Create temporary GroundTruth for precision/recall calculation
    temp_gt = GroundTruth(
        populated=True,
        findings_confirmed=new_confirmed,
        findings_false_alarm=record.ground_truth.findings_false_alarm,
        issues_missed=new_missed,
    )
    new_precision, new_recall = calculate_precision_recall(temp_gt)

    # Build updated amendments list
    existing_amendments = list(record.ground_truth.amendments or [])
    existing_amendments.append(amendment)

    # Create updated ground truth
    updated_gt = GroundTruth(
        populated=True,
        populated_at=record.ground_truth.populated_at,
        findings_confirmed=new_confirmed,
        findings_false_alarm=record.ground_truth.findings_false_alarm,
        issues_missed=new_missed,
        precision=new_precision,
        recall=new_recall,
        amendments=existing_amendments,
        last_updated_at=datetime.now(UTC),
    )

    # Update record and save atomically
    updated_record = record.model_copy(update={"ground_truth": updated_gt})
    _atomic_update_record(record_path, updated_record)

    logger.info(
        "Applied amendment to record %s: delta_confirmed=%d, delta_missed=%d",
        record.record_id,
        amendment.delta_confirmed,
        amendment.delta_missed,
    )


def calculate_precision_recall(
    ground_truth: GroundTruth,
) -> tuple[float | None, float | None]:
    """Calculate precision and recall from ground truth.

    precision = confirmed / (confirmed + false_alarm)
    recall = confirmed / (confirmed + missed)

    Args:
        ground_truth: Populated GroundTruth object.

    Returns:
        Tuple of (precision, recall). Values are None if
        denominator is zero. Values are clamped to [0.0, 1.0].

    """
    confirmed = ground_truth.findings_confirmed
    false_alarm = ground_truth.findings_false_alarm
    missed = ground_truth.issues_missed

    # Calculate precision
    precision_denom = confirmed + false_alarm
    precision = None if precision_denom == 0 else min(max(confirmed / precision_denom, 0.0), 1.0)

    # Calculate recall
    recall_denom = confirmed + missed
    recall = None if recall_denom == 0 else min(max(confirmed / recall_denom, 0.0), 1.0)

    return precision, recall

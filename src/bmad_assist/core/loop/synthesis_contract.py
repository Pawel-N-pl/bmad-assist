"""Shared synthesis decision contract for all synthesis phases.

Defines the canonical vocabulary for:
- ExtractionQuality: how reliably was synthesis output parsed
- CanonicalResolution: the machine-derived outcome (resolved/rework/halt)
- FailureClass: how to respond to a bad synthesis outcome
- SynthesisDecision: the combined decision produced by make_synthesis_decision()
- StoryPatch: a single targeted update for one-write mutation model
- extract_story_patches(): parse patch blocks from LLM stdout
- make_synthesis_decision(): compute canonical resolution from parsed data + evidence

Both CODE_REVIEW_SYNTHESIS and VALIDATE_STORY_SYNTHESIS import from here.
No external deps — this module must be importable without side effects.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = [
    "ExtractionQuality",
    "CanonicalResolution",
    "FailureClass",
    "SynthesisDecision",
    "StoryPatch",
    "extract_story_patches",
    "make_synthesis_decision",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExtractionQuality(str, Enum):
    """How reliably was the synthesis output parsed.

    STRICT: exact HTML-comment markers found and all fields valid.
    DEGRADED: fallback to section headers or semantic keyword scan.
    FAILED: no usable structure found; decision must fall back to evidence only.
    """

    STRICT = "strict"
    DEGRADED = "degraded"
    FAILED = "failed"


class CanonicalResolution(str, Enum):
    """Machine-derived outcome of a synthesis phase.

    RESOLVED: no remaining issues; continue to next phase.
    REWORK: issues remain; loop back (if rework enabled) or log warning.
    HALT: unable to trust output or evidence is contradictory; stop for manual review.
    """

    RESOLVED = "resolved"
    REWORK = "rework"
    HALT = "halt"


class FailureClass(str, Enum):
    """How to respond to a bad synthesis outcome.

    RETRYABLE: ToolCallGuard termination or provider truncation; bounded retry is safe.
    HALT: contradictory evidence, unusable extraction with no fallback, patch ambiguity.
    IGNORE: non-critical failure that does not affect resolution.
    """

    RETRYABLE = "retryable"
    HALT = "halt"
    IGNORE = "ignore"


# ---------------------------------------------------------------------------
# SynthesisDecision dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SynthesisDecision:
    """The combined outcome of a synthesis phase.

    Attributes:
        resolution: Canonical machine-derived outcome.
        extraction_quality: How reliably the output was parsed.
        failure_class: How to respond if something went wrong (None = clean run).
        raw_parsed: Raw parsed fields from extraction, for logging/debugging.
        evidence_summary: Human-readable explanation of how the decision was made.
    """

    resolution: CanonicalResolution
    extraction_quality: ExtractionQuality
    failure_class: FailureClass | None
    raw_parsed: dict[str, Any] | None
    evidence_summary: str


# ---------------------------------------------------------------------------
# Evidence sufficiency rule
# ---------------------------------------------------------------------------

# Verdicts that indicate the evidence score found real issues pre-synthesis.
_REWORK_VERDICTS = frozenset({"REJECT", "MAJOR_REWORK"})
# Verdicts where we cannot trust evidence as a standalone signal.
_UNCERTAIN_VERDICTS = frozenset({"UNCERTAIN", "UNKNOWN"})


def _has_sufficient_evidence(
    evidence_verdict: str,
    evidence_score_data: dict[str, Any] | None,
) -> bool:
    """Return True when pre-synthesis evidence is trustworthy enough to act on alone.

    Sufficient means:
    - Pre-synthesis findings_summary contains CRITICAL > 0 or IMPORTANT > 0, AND
    - Evidence verdict is not UNCERTAIN / UNKNOWN (which would mean the signal itself
      is ambiguous).
    """
    if evidence_verdict in _UNCERTAIN_VERDICTS:
        return False
    if not evidence_score_data:
        return False
    findings = evidence_score_data.get("findings_summary", {})
    pre_critical = findings.get("CRITICAL", 0)
    pre_important = findings.get("IMPORTANT", 0)
    return pre_critical > 0 or pre_important > 0


# ---------------------------------------------------------------------------
# make_synthesis_decision
# ---------------------------------------------------------------------------


def make_synthesis_decision(
    parsed: dict[str, Any] | None,
    quality: ExtractionQuality,
    evidence_verdict: str,
    evidence_score_data: dict[str, Any] | None = None,
) -> SynthesisDecision:
    """Compute the canonical synthesis decision from parsed output + evidence.

    Resolution priority:
    1. If quality == STRICT or DEGRADED and parsed is not None → trust LLM block
       (with cross-validation: resolved+zero_fixes+evidence_issues → halt)
    2. If quality == FAILED:
       - sufficient deterministic evidence (CRITICAL/IMPORTANT > 0, verdict not UNCERTAIN)
         → REWORK (we trust the pre-synthesis counts)
       - otherwise → HALT (cannot determine outcome safely)

    Args:
        parsed: Output of the layered extraction (may be None if FAILED).
        quality: How reliably the output was parsed.
        evidence_verdict: Evidence Score verdict (REJECT, MAJOR_REWORK, PASS, etc.).
        evidence_score_data: Pre-synthesis evidence dict with findings_summary.

    Returns:
        SynthesisDecision with resolution, quality, failure_class, and summary.
    """
    if parsed is not None and quality != ExtractionQuality.FAILED:
        return _decision_from_parsed(parsed, quality, evidence_verdict, evidence_score_data)

    # quality == FAILED (or parsed is None with FAILED quality)
    return _decision_from_evidence_only(evidence_verdict, evidence_score_data, quality)


def _decision_from_parsed(
    parsed: dict[str, Any],
    quality: ExtractionQuality,
    evidence_verdict: str,
    evidence_score_data: dict[str, Any] | None,
) -> SynthesisDecision:
    """Derive decision when extraction succeeded (STRICT or DEGRADED)."""
    resolution_str = parsed.get("resolution", "")

    if quality == ExtractionQuality.DEGRADED:
        logger.warning(
            "Synthesis extraction quality is DEGRADED "
            "(markers absent or drifted; used fallback parsing). "
            "resolution=%r evidence_verdict=%s",
            resolution_str,
            evidence_verdict,
        )

    if resolution_str == "halt":
        return SynthesisDecision(
            resolution=CanonicalResolution.HALT,
            extraction_quality=quality,
            failure_class=FailureClass.HALT,
            raw_parsed=parsed,
            evidence_summary=(
                f"LLM requested halt (quality={quality.value}, verdict={evidence_verdict})"
            ),
        )

    if resolution_str == "rework":
        return SynthesisDecision(
            resolution=CanonicalResolution.REWORK,
            extraction_quality=quality,
            failure_class=None,
            raw_parsed=parsed,
            evidence_summary=(
                f"LLM reported remaining issues (quality={quality.value}, verdict={evidence_verdict})"
            ),
        )

    # resolution_str == "resolved"
    # Cross-validate: if evidence shows pre-synthesis issues existed but LLM claims
    # zero fixes, that is suspicious → halt rather than silently accept.
    if evidence_score_data:
        findings = evidence_score_data.get("findings_summary", {})
        pre_critical = findings.get("CRITICAL", 0)
        pre_important = findings.get("IMPORTANT", 0)
        if pre_critical > 0 or pre_important > 0:
            fixed_critical = parsed.get("fixed_critical", 0)
            fixed_high = parsed.get("fixed_high", 0)
            if isinstance(fixed_critical, int) and isinstance(fixed_high, int):
                if fixed_critical + fixed_high == 0:
                    logger.warning(
                        "Cross-validation halt: LLM claims resolved but "
                        "fixed_critical=%d, fixed_high=%d while evidence shows "
                        "CRITICAL=%d, IMPORTANT=%d (quality=%s)",
                        fixed_critical,
                        fixed_high,
                        pre_critical,
                        pre_important,
                        quality.value,
                    )
                    return SynthesisDecision(
                        resolution=CanonicalResolution.HALT,
                        extraction_quality=quality,
                        failure_class=FailureClass.HALT,
                        raw_parsed=parsed,
                        evidence_summary=(
                            f"LLM claims resolved but reports 0 fixes despite "
                            f"evidence showing CRITICAL={pre_critical}, IMPORTANT={pre_important}"
                        ),
                    )

    return SynthesisDecision(
        resolution=CanonicalResolution.RESOLVED,
        extraction_quality=quality,
        failure_class=None,
        raw_parsed=parsed,
        evidence_summary=(
            f"LLM reported resolved (quality={quality.value}, verdict={evidence_verdict})"
        ),
    )


def _decision_from_evidence_only(
    evidence_verdict: str,
    evidence_score_data: dict[str, Any] | None,
    quality: ExtractionQuality,
) -> SynthesisDecision:
    """Derive decision when extraction fully failed.

    Evidence sufficiency rule:
    - FAILED + sufficient deterministic evidence → REWORK
    - FAILED + insufficient / uncertain evidence → HALT
    """
    if _has_sufficient_evidence(evidence_verdict, evidence_score_data):
        logger.warning(
            "Synthesis extraction FAILED; falling back to evidence verdict=%s "
            "with sufficient pre-synthesis findings → REWORK",
            evidence_verdict,
        )
        return SynthesisDecision(
            resolution=CanonicalResolution.REWORK,
            extraction_quality=quality,
            failure_class=FailureClass.HALT,
            raw_parsed=None,
            evidence_summary=(
                f"Extraction failed; evidence verdict={evidence_verdict} with "
                f"sufficient pre-synthesis findings → rework"
            ),
        )

    logger.warning(
        "Synthesis extraction FAILED and evidence is insufficient "
        "(verdict=%s, no reliable pre-synthesis counts) → HALT",
        evidence_verdict,
    )
    return SynthesisDecision(
        resolution=CanonicalResolution.HALT,
        extraction_quality=quality,
        failure_class=FailureClass.HALT,
        raw_parsed=None,
        evidence_summary=(
            f"Extraction failed and evidence is insufficient "
            f"(verdict={evidence_verdict}) → halt for manual review"
        ),
    )


# ---------------------------------------------------------------------------
# StoryPatch and extract_story_patches
# ---------------------------------------------------------------------------

_PATCH_PATTERN = re.compile(
    r'<!--\s*STORY_PATCH_START\s+heading="([^"]+)"\s*-->'
    r"\s*(.*?)\s*"
    r"<!--\s*STORY_PATCH_END\s*-->",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class StoryPatch:
    """A single targeted replacement for one section of a story file.

    Attributes:
        heading: Exact Markdown heading text (normalized lowercase, stripped)
            used to locate the section in the story file.
        content: Complete replacement content for that section, including
            the heading line itself.
    """

    heading: str
    content: str


def extract_story_patches(stdout: str) -> list[StoryPatch]:
    """Parse STORY_PATCH_START/END blocks from LLM stdout.

    Blocks have the form:
        <!-- STORY_PATCH_START heading="## acceptance criteria" -->
        [replacement content]
        <!-- STORY_PATCH_END -->

    The heading attribute is normalized (lowercased, stripped) so that
    "## Acceptance Criteria" and "## acceptance criteria" both resolve to
    "## acceptance criteria".

    Args:
        stdout: Raw LLM output string.

    Returns:
        List of StoryPatch instances in order of appearance.
        Returns [] if no patch blocks are found or on parse error.
    """
    patches: list[StoryPatch] = []
    for match in _PATCH_PATTERN.finditer(stdout):
        raw_heading = match.group(1).strip()
        normalized_heading = raw_heading.lower().strip()
        content = match.group(2).strip()
        if normalized_heading and content:
            patches.append(StoryPatch(heading=normalized_heading, content=content))
        else:
            logger.warning(
                "Skipping malformed STORY_PATCH block: heading=%r content_len=%d",
                raw_heading,
                len(content),
            )
    return patches

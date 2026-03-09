"""Tests for synthesis-authoritative review resolution.

Tests extract_resolution() and compute_resolution() functions that derive
a canonical machine outcome from synthesis LLM output, as well as the new
layered extraction, SynthesisDecision contract, failure classification, and
STORY_PATCH extraction.
"""

import pytest

from bmad_assist.core.loop.handlers.code_review_synthesis import (
    VALID_RESOLUTIONS,
    _extract_resolution_layered,
    compute_resolution,
    extract_resolution,
)
from bmad_assist.core.loop.synthesis_contract import (
    CanonicalResolution,
    ExtractionQuality,
    FailureClass,
    StoryPatch,
    extract_story_patches,
    make_synthesis_decision,
)


class TestExtractResolution:
    """Tests for extract_resolution() — parsing structured resolution blocks."""

    def _make_output(self, block: str) -> str:
        """Wrap a resolution block in typical synthesis output."""
        return (
            "Some synthesis text above...\n"
            "<!-- CODE_REVIEW_SYNTHESIS_END -->\n"
            f"{block}\n"
            "More text below..."
        )

    def _make_block(
        self,
        resolution: str = "resolved",
        verified_critical: int = 2,
        verified_high: int = 3,
        fixed_critical: int = 2,
        fixed_high: int = 3,
        remaining_critical: int = 0,
        remaining_high: int = 0,
    ) -> str:
        return (
            "<!-- SYNTHESIS_RESOLUTION_START -->\n"
            f"resolution: {resolution}\n"
            f"verified_critical: {verified_critical}\n"
            f"verified_high: {verified_high}\n"
            f"fixed_critical: {fixed_critical}\n"
            f"fixed_high: {fixed_high}\n"
            f"remaining_critical: {remaining_critical}\n"
            f"remaining_high: {remaining_high}\n"
            "<!-- SYNTHESIS_RESOLUTION_END -->"
        )

    def test_valid_resolved_block(self) -> None:
        """Valid resolution block with all fields returns complete dict."""
        stdout = self._make_output(self._make_block(resolution="resolved"))
        result = extract_resolution(stdout)
        assert result is not None
        assert result["resolution"] == "resolved"
        assert result["verified_critical"] == 2
        assert result["verified_high"] == 3
        assert result["fixed_critical"] == 2
        assert result["fixed_high"] == 3
        assert result["remaining_critical"] == 0
        assert result["remaining_high"] == 0

    def test_valid_rework_block(self) -> None:
        """Valid rework resolution with remaining issues."""
        stdout = self._make_output(
            self._make_block(resolution="rework", remaining_critical=1)
        )
        result = extract_resolution(stdout)
        assert result is not None
        assert result["resolution"] == "rework"
        assert result["remaining_critical"] == 1

    def test_valid_halt_block(self) -> None:
        """Valid halt resolution."""
        stdout = self._make_output(self._make_block(resolution="halt"))
        result = extract_resolution(stdout)
        assert result is not None
        assert result["resolution"] == "halt"

    def test_missing_markers_returns_none(self) -> None:
        """No resolution markers in output returns None."""
        stdout = "Just some synthesis text without any markers."
        assert extract_resolution(stdout) is None

    def test_malformed_yaml_returns_none(self) -> None:
        """Malformed content inside markers returns None (missing resolution)."""
        stdout = self._make_output(
            "<!-- SYNTHESIS_RESOLUTION_START -->\n"
            "this is not yaml at all\n"
            "<!-- SYNTHESIS_RESOLUTION_END -->"
        )
        assert extract_resolution(stdout) is None

    def test_invalid_resolution_value_returns_none(self) -> None:
        """Invalid resolution value returns None."""
        stdout = self._make_output(self._make_block(resolution="maybe"))
        assert extract_resolution(stdout) is None

    def test_negative_count_returns_none(self) -> None:
        """Negative count value returns None."""
        stdout = self._make_output(
            self._make_block(remaining_critical=-1)
        )
        assert extract_resolution(stdout) is None

    def test_non_integer_count_returns_none(self) -> None:
        """Non-integer count value returns None."""
        block = (
            "<!-- SYNTHESIS_RESOLUTION_START -->\n"
            "resolution: resolved\n"
            "verified_critical: abc\n"
            "verified_high: 0\n"
            "fixed_critical: 0\n"
            "fixed_high: 0\n"
            "remaining_critical: 0\n"
            "remaining_high: 0\n"
            "<!-- SYNTHESIS_RESOLUTION_END -->"
        )
        stdout = self._make_output(block)
        assert extract_resolution(stdout) is None

    def test_cross_validate_resolved_with_remaining_critical(self) -> None:
        """resolution=resolved but remaining_critical > 0 overrides to rework."""
        stdout = self._make_output(
            self._make_block(resolution="resolved", remaining_critical=1)
        )
        result = extract_resolution(stdout)
        assert result is not None
        assert result["resolution"] == "rework"

    def test_cross_validate_resolved_with_remaining_high(self) -> None:
        """resolution=resolved but remaining_high > 0 overrides to rework."""
        stdout = self._make_output(
            self._make_block(resolution="resolved", remaining_high=2)
        )
        result = extract_resolution(stdout)
        assert result is not None
        assert result["resolution"] == "rework"

    def test_multiple_blocks_uses_last(self) -> None:
        """When multiple resolution blocks exist, uses the last one."""
        block1 = self._make_block(resolution="rework", remaining_critical=1)
        block2 = self._make_block(resolution="resolved")
        stdout = f"text\n{block1}\nmiddle\n{block2}\nend"
        result = extract_resolution(stdout)
        assert result is not None
        assert result["resolution"] == "resolved"

    def test_empty_block_returns_none(self) -> None:
        """Empty content between markers returns None."""
        stdout = self._make_output(
            "<!-- SYNTHESIS_RESOLUTION_START -->\n"
            "<!-- SYNTHESIS_RESOLUTION_END -->"
        )
        assert extract_resolution(stdout) is None

    def test_rework_not_overridden(self) -> None:
        """Cross-validation does not override rework to resolved."""
        stdout = self._make_output(
            self._make_block(resolution="rework", remaining_critical=0, remaining_high=0)
        )
        result = extract_resolution(stdout)
        assert result is not None
        assert result["resolution"] == "rework"

    def test_halt_not_overridden(self) -> None:
        """Cross-validation does not override halt."""
        stdout = self._make_output(
            self._make_block(resolution="halt", remaining_critical=5)
        )
        result = extract_resolution(stdout)
        assert result is not None
        assert result["resolution"] == "halt"


class TestComputeResolution:
    """Tests for compute_resolution() — code-first resolution with LLM input."""

    def test_parsed_resolved_no_evidence(self) -> None:
        """LLM says resolved, no evidence data → trust LLM."""
        assert compute_resolution({"resolution": "resolved"}, "REJECT") == "resolved"

    def test_parsed_resolved_with_fixes(self) -> None:
        """LLM says resolved, evidence shows issues, LLM reports fixes → resolved."""
        evidence = {"findings_summary": {"CRITICAL": 2, "IMPORTANT": 1}}
        parsed = {"resolution": "resolved", "fixed_critical": 2, "fixed_high": 1}
        assert compute_resolution(parsed, "REJECT", evidence) == "resolved"

    def test_parsed_resolved_zero_fixes_halts(self) -> None:
        """LLM says resolved but reports 0 fixes while evidence shows issues → halt."""
        evidence = {"findings_summary": {"CRITICAL": 2, "IMPORTANT": 1}}
        parsed = {"resolution": "resolved", "fixed_critical": 0, "fixed_high": 0}
        assert compute_resolution(parsed, "REJECT", evidence) == "halt"

    def test_parsed_rework(self) -> None:
        assert compute_resolution({"resolution": "rework"}, "PASS") == "rework"

    def test_parsed_halt(self) -> None:
        assert compute_resolution({"resolution": "halt"}, "UNKNOWN") == "halt"

    def test_fallback_reject_no_evidence_halts(self) -> None:
        """None parsed + REJECT verdict + no evidence data → halt.

        Evidence sufficiency rule: FAILED quality with no pre-synthesis
        evidence_score_data cannot be trusted to decide rework vs resolved;
        the safe response is halt for manual review.
        """
        assert compute_resolution(None, "REJECT") == "halt"

    def test_fallback_major_rework_no_evidence_halts(self) -> None:
        """None parsed + MAJOR_REWORK verdict + no evidence data → halt."""
        assert compute_resolution(None, "MAJOR_REWORK") == "halt"

    def test_fallback_pass_no_evidence_halts(self) -> None:
        """None parsed + PASS verdict + no evidence data → halt.

        Without evidence data we cannot confirm zero issues existed,
        so even a PASS verdict is insufficient to auto-resolve.
        """
        assert compute_resolution(None, "PASS") == "halt"

    def test_fallback_excellent_no_evidence_halts(self) -> None:
        """None parsed + EXCELLENT verdict + no evidence data → halt."""
        assert compute_resolution(None, "EXCELLENT") == "halt"

    def test_fallback_unknown_no_evidence_halts(self) -> None:
        """None parsed + UNKNOWN verdict → halt (UNKNOWN is uncertain)."""
        assert compute_resolution(None, "UNKNOWN") == "halt"

    def test_failed_with_sufficient_evidence_reworks(self) -> None:
        """None parsed + REJECT + pre-synthesis CRITICAL > 0 → rework.

        When extraction fails but evidence shows real pre-synthesis issues,
        the evidence is trustworthy enough to conclude rework is needed.
        """
        evidence = {"findings_summary": {"CRITICAL": 2, "IMPORTANT": 1}}
        assert compute_resolution(None, "REJECT", evidence) == "rework"

    def test_failed_important_only_evidence_reworks(self) -> None:
        """None parsed + REJECT + only IMPORTANT > 0 → rework."""
        evidence = {"findings_summary": {"CRITICAL": 0, "IMPORTANT": 3}}
        assert compute_resolution(None, "REJECT", evidence) == "rework"

    def test_failed_uncertain_verdict_halts_despite_evidence(self) -> None:
        """None parsed + UNCERTAIN verdict + evidence → halt.

        UNCERTAIN verdict means the evidence signal itself is ambiguous;
        we cannot use it as a fallback even when counts are non-zero.
        """
        evidence = {"findings_summary": {"CRITICAL": 2, "IMPORTANT": 0}}
        assert compute_resolution(None, "UNCERTAIN", evidence) == "halt"

    def test_failed_zero_counts_evidence_halts(self) -> None:
        """None parsed + REJECT + CRITICAL=0, IMPORTANT=0 → halt.

        Zero pre-synthesis counts mean the evidence doesn't confirm any
        real issues existed, so we cannot conclude rework is needed.
        """
        evidence = {"findings_summary": {"CRITICAL": 0, "IMPORTANT": 0}}
        assert compute_resolution(None, "REJECT", evidence) == "halt"

    def test_parsed_overrides_verdict(self) -> None:
        """resolution=resolved overrides REJECT verdict (the core feature)."""
        assert compute_resolution({"resolution": "resolved"}, "REJECT") == "resolved"

    def test_evidence_with_no_issues_trusts_resolved(self) -> None:
        """Evidence shows no critical/important → resolved trusted without fixes."""
        evidence = {"findings_summary": {"CRITICAL": 0, "IMPORTANT": 0, "MINOR": 3}}
        parsed = {"resolution": "resolved", "fixed_critical": 0, "fixed_high": 0}
        assert compute_resolution(parsed, "PASS", evidence) == "resolved"

    def test_evidence_missing_findings_summary(self) -> None:
        """Evidence data exists but no findings_summary → trust LLM."""
        evidence = {"verdict": "REJECT", "total_score": 7.0}
        parsed = {"resolution": "resolved", "fixed_critical": 0, "fixed_high": 0}
        assert compute_resolution(parsed, "REJECT", evidence) == "resolved"


class TestLayeredExtraction:
    """Tests for _extract_resolution_layered() — three-layer parsing strategy."""

    def _make_marker_block(
        self,
        resolution: str = "resolved",
        remaining_critical: int = 0,
        remaining_high: int = 0,
    ) -> str:
        return (
            "<!-- SYNTHESIS_RESOLUTION_START -->\n"
            f"resolution: {resolution}\n"
            "verified_critical: 2\n"
            "verified_high: 3\n"
            "fixed_critical: 2\n"
            "fixed_high: 3\n"
            f"remaining_critical: {remaining_critical}\n"
            f"remaining_high: {remaining_high}\n"
            "<!-- SYNTHESIS_RESOLUTION_END -->"
        )

    def test_exact_markers_returns_strict(self) -> None:
        """Valid marker block → STRICT quality."""
        stdout = self._make_marker_block(resolution="resolved")
        parsed, quality = _extract_resolution_layered(stdout)
        assert quality == ExtractionQuality.STRICT
        assert parsed is not None
        assert parsed["resolution"] == "resolved"

    def test_markers_invalid_block_returns_failed_not_layer2(self) -> None:
        """Markers found but invalid content → FAILED (no Layer 2 fallthrough).

        If the LLM output has markers but the block is corrupt (negative count),
        we must NOT fall through to Layer 2 (which could pick up unrelated text).
        """
        stdout = (
            "<!-- SYNTHESIS_RESOLUTION_START -->\n"
            "resolution: resolved\n"
            "remaining_critical: -1\n"
            "<!-- SYNTHESIS_RESOLUTION_END -->\n"
            # Layer 2 would pick this up if we fell through:
            "resolution: rework\n"
        )
        parsed, quality = _extract_resolution_layered(stdout)
        assert quality == ExtractionQuality.FAILED
        assert parsed is None

    def test_no_markers_header_fallback_returns_degraded(self) -> None:
        """No markers, bare 'resolution: X' line → DEGRADED quality."""
        stdout = (
            "The code review synthesis is complete.\n"
            "resolution: rework\n"
            "remaining_critical: 2\n"
            "remaining_high: 1\n"
            "Some additional text.\n"
        )
        parsed, quality = _extract_resolution_layered(stdout)
        assert quality == ExtractionQuality.DEGRADED
        assert parsed is not None
        assert parsed["resolution"] == "rework"
        assert parsed.get("remaining_critical") == 2

    def test_header_fallback_cross_validates(self) -> None:
        """Layer 2 cross-validates resolved → rework if remaining_critical > 0."""
        stdout = "resolution: resolved\nremaining_critical: 3\n"
        parsed, quality = _extract_resolution_layered(stdout)
        assert quality == ExtractionQuality.DEGRADED
        assert parsed is not None
        assert parsed["resolution"] == "rework"

    def test_semantic_halt_keyword_returns_degraded(self) -> None:
        """Semantic 'cannot determine' → DEGRADED with halt resolution."""
        stdout = "After reviewing the evidence, I cannot reliably determine if all issues were fixed."
        parsed, quality = _extract_resolution_layered(stdout)
        assert quality == ExtractionQuality.DEGRADED
        assert parsed is not None
        assert parsed["resolution"] == "halt"

    def test_semantic_rework_keyword_returns_degraded(self) -> None:
        """Semantic 'remaining critical issue' → DEGRADED with rework resolution."""
        stdout = "There are remaining critical issues that still need to be addressed."
        parsed, quality = _extract_resolution_layered(stdout)
        assert quality == ExtractionQuality.DEGRADED
        assert parsed is not None
        assert parsed["resolution"] == "rework"

    def test_semantic_resolved_keyword_returns_degraded(self) -> None:
        """Semantic 'all issues have been addressed' → DEGRADED with resolved resolution."""
        stdout = "The synthesis is complete. All issues have been addressed by the developer."
        parsed, quality = _extract_resolution_layered(stdout)
        assert quality == ExtractionQuality.DEGRADED
        assert parsed is not None
        assert parsed["resolution"] == "resolved"

    def test_no_signals_returns_failed(self) -> None:
        """No markers, no key-value lines, no semantic signals → FAILED."""
        stdout = "This is just some random text with no synthesis resolution information."
        parsed, quality = _extract_resolution_layered(stdout)
        assert quality == ExtractionQuality.FAILED
        assert parsed is None

    def test_empty_stdout_returns_failed(self) -> None:
        """Empty string → FAILED."""
        parsed, quality = _extract_resolution_layered("")
        assert quality == ExtractionQuality.FAILED
        assert parsed is None

    def test_markers_take_priority_over_header(self) -> None:
        """Markers in output → STRICT even if bare 'resolution:' line also present."""
        stdout = (
            self._make_marker_block(resolution="resolved") + "\n"
            "resolution: rework\n"  # Should be ignored; marker takes priority
        )
        parsed, quality = _extract_resolution_layered(stdout)
        assert quality == ExtractionQuality.STRICT
        assert parsed is not None
        assert parsed["resolution"] == "resolved"


class TestSynthesisDecision:
    """Tests for make_synthesis_decision() — canonical decision from contract."""

    def test_strict_resolved_passthrough(self) -> None:
        """STRICT quality + resolved → RESOLVED decision."""
        decision = make_synthesis_decision(
            parsed={"resolution": "resolved"},
            quality=ExtractionQuality.STRICT,
            evidence_verdict="PASS",
        )
        assert decision.resolution == CanonicalResolution.RESOLVED
        assert decision.extraction_quality == ExtractionQuality.STRICT
        assert decision.failure_class is None

    def test_strict_rework_passthrough(self) -> None:
        """STRICT quality + rework → REWORK decision."""
        decision = make_synthesis_decision(
            parsed={"resolution": "rework"},
            quality=ExtractionQuality.STRICT,
            evidence_verdict="REJECT",
        )
        assert decision.resolution == CanonicalResolution.REWORK
        assert decision.failure_class is None

    def test_strict_halt_passthrough(self) -> None:
        """STRICT quality + halt → HALT with FailureClass.HALT."""
        decision = make_synthesis_decision(
            parsed={"resolution": "halt"},
            quality=ExtractionQuality.STRICT,
            evidence_verdict="UNKNOWN",
        )
        assert decision.resolution == CanonicalResolution.HALT
        assert decision.failure_class == FailureClass.HALT

    def test_degraded_quality_still_resolves(self) -> None:
        """DEGRADED quality → resolution computed from parsed (with warning)."""
        decision = make_synthesis_decision(
            parsed={"resolution": "rework"},
            quality=ExtractionQuality.DEGRADED,
            evidence_verdict="REJECT",
        )
        assert decision.resolution == CanonicalResolution.REWORK
        assert decision.extraction_quality == ExtractionQuality.DEGRADED

    def test_failed_with_critical_evidence_reworks(self) -> None:
        """FAILED quality + CRITICAL > 0 + REJECT → REWORK.

        Pre-synthesis evidence is sufficient; we trust the counts even
        when synthesis output could not be parsed.
        """
        evidence = {"findings_summary": {"CRITICAL": 3, "IMPORTANT": 0}}
        decision = make_synthesis_decision(
            parsed=None,
            quality=ExtractionQuality.FAILED,
            evidence_verdict="REJECT",
            evidence_score_data=evidence,
        )
        assert decision.resolution == CanonicalResolution.REWORK
        assert decision.extraction_quality == ExtractionQuality.FAILED
        assert decision.failure_class == FailureClass.HALT  # Still a failure event

    def test_failed_with_zero_counts_halts(self) -> None:
        """FAILED quality + CRITICAL=0, IMPORTANT=0 → HALT (insufficient evidence)."""
        evidence = {"findings_summary": {"CRITICAL": 0, "IMPORTANT": 0}}
        decision = make_synthesis_decision(
            parsed=None,
            quality=ExtractionQuality.FAILED,
            evidence_verdict="REJECT",
            evidence_score_data=evidence,
        )
        assert decision.resolution == CanonicalResolution.HALT
        assert decision.failure_class == FailureClass.HALT

    def test_failed_no_evidence_halts(self) -> None:
        """FAILED quality + no evidence_score_data → HALT."""
        decision = make_synthesis_decision(
            parsed=None,
            quality=ExtractionQuality.FAILED,
            evidence_verdict="REJECT",
        )
        assert decision.resolution == CanonicalResolution.HALT
        assert decision.failure_class == FailureClass.HALT

    def test_failed_uncertain_verdict_halts_even_with_counts(self) -> None:
        """FAILED quality + UNCERTAIN verdict → HALT even if counts are non-zero."""
        evidence = {"findings_summary": {"CRITICAL": 5, "IMPORTANT": 2}}
        decision = make_synthesis_decision(
            parsed=None,
            quality=ExtractionQuality.FAILED,
            evidence_verdict="UNCERTAIN",
            evidence_score_data=evidence,
        )
        assert decision.resolution == CanonicalResolution.HALT

    def test_strict_resolved_zero_fixes_with_evidence_halts(self) -> None:
        """STRICT resolved + 0 fixes + evidence shows pre-existing issues → HALT.

        Cross-validation: LLM claims resolved but reports zero fixes while
        evidence shows there were CRITICAL issues. This is contradictory.
        """
        evidence = {"findings_summary": {"CRITICAL": 2, "IMPORTANT": 1}}
        parsed = {"resolution": "resolved", "fixed_critical": 0, "fixed_high": 0}
        decision = make_synthesis_decision(
            parsed=parsed,
            quality=ExtractionQuality.STRICT,
            evidence_verdict="REJECT",
            evidence_score_data=evidence,
        )
        assert decision.resolution == CanonicalResolution.HALT
        assert decision.failure_class == FailureClass.HALT

    def test_strict_resolved_with_fixes_not_halted(self) -> None:
        """STRICT resolved + non-zero fixes + evidence → RESOLVED (valid fix claim)."""
        evidence = {"findings_summary": {"CRITICAL": 2, "IMPORTANT": 1}}
        parsed = {"resolution": "resolved", "fixed_critical": 2, "fixed_high": 1}
        decision = make_synthesis_decision(
            parsed=parsed,
            quality=ExtractionQuality.STRICT,
            evidence_verdict="REJECT",
            evidence_score_data=evidence,
        )
        assert decision.resolution == CanonicalResolution.RESOLVED


class TestFailureClassification:
    """Tests for failure classification via synthesis_contract."""

    def test_retryable_enum_value(self) -> None:
        """RETRYABLE FailureClass has string value 'retryable'."""
        assert FailureClass.RETRYABLE.value == "retryable"

    def test_halt_enum_value(self) -> None:
        """HALT FailureClass has string value 'halt'."""
        assert FailureClass.HALT.value == "halt"

    def test_ignore_enum_value(self) -> None:
        """IGNORE FailureClass has string value 'ignore'."""
        assert FailureClass.IGNORE.value == "ignore"

    def test_failed_quality_with_sufficient_evidence_uses_halt_failure_class(self) -> None:
        """Even when FAILED+evidence→REWORK, failure_class is still HALT (it's a failure event)."""
        evidence = {"findings_summary": {"CRITICAL": 1, "IMPORTANT": 0}}
        decision = make_synthesis_decision(
            parsed=None,
            quality=ExtractionQuality.FAILED,
            evidence_verdict="REJECT",
            evidence_score_data=evidence,
        )
        # Resolution is REWORK (evidence rescued it) but the extraction failure is still HALT class
        assert decision.resolution == CanonicalResolution.REWORK
        assert decision.failure_class == FailureClass.HALT

    def test_clean_run_has_no_failure_class(self) -> None:
        """Successful STRICT extraction with valid resolution → failure_class is None."""
        decision = make_synthesis_decision(
            parsed={"resolution": "resolved"},
            quality=ExtractionQuality.STRICT,
            evidence_verdict="PASS",
        )
        assert decision.failure_class is None

    def test_rework_decision_has_no_failure_class(self) -> None:
        """Rework from clean STRICT extraction → failure_class is None."""
        decision = make_synthesis_decision(
            parsed={"resolution": "rework"},
            quality=ExtractionQuality.STRICT,
            evidence_verdict="REJECT",
        )
        assert decision.failure_class is None


class TestStoryPatchExtraction:
    """Tests for extract_story_patches() from synthesis_contract."""

    def test_single_patch_extracted(self) -> None:
        """Single well-formed patch block is extracted correctly."""
        stdout = (
            'Some preamble text.\n'
            '<!-- STORY_PATCH_START heading="## acceptance criteria" -->\n'
            '## Acceptance Criteria\n'
            '\n'
            '- [ ] Criterion A\n'
            '- [ ] Criterion B\n'
            '<!-- STORY_PATCH_END -->\n'
            'Some trailing text.'
        )
        patches = extract_story_patches(stdout)
        assert len(patches) == 1
        assert patches[0].heading == "## acceptance criteria"
        assert "Criterion A" in patches[0].content

    def test_multiple_patches_extracted_in_order(self) -> None:
        """Multiple patch blocks returned in order of appearance."""
        stdout = (
            '<!-- STORY_PATCH_START heading="## story" -->\n'
            '## Story\nAs a user\n'
            '<!-- STORY_PATCH_END -->\n'
            '<!-- STORY_PATCH_START heading="## acceptance criteria" -->\n'
            '## Acceptance Criteria\n- [ ] Done\n'
            '<!-- STORY_PATCH_END -->\n'
        )
        patches = extract_story_patches(stdout)
        assert len(patches) == 2
        assert patches[0].heading == "## story"
        assert patches[1].heading == "## acceptance criteria"

    def test_heading_normalized_to_lowercase(self) -> None:
        """Heading attribute is normalized to lowercase regardless of input case."""
        stdout = (
            '<!-- STORY_PATCH_START heading="## Acceptance Criteria" -->\n'
            '## Acceptance Criteria\n- [ ] Done\n'
            '<!-- STORY_PATCH_END -->\n'
        )
        patches = extract_story_patches(stdout)
        assert len(patches) == 1
        assert patches[0].heading == "## acceptance criteria"

    def test_no_patches_returns_empty_list(self) -> None:
        """Output with no patch blocks → empty list."""
        stdout = "This LLM output has no patch blocks at all."
        patches = extract_story_patches(stdout)
        assert patches == []

    def test_empty_stdout_returns_empty_list(self) -> None:
        """Empty string → empty list."""
        patches = extract_story_patches("")
        assert patches == []

    def test_patch_with_extra_whitespace_in_markers(self) -> None:
        """Whitespace variations in marker tags are handled."""
        stdout = (
            '<!--  STORY_PATCH_START  heading="## tasks"  -->\n'
            '## Tasks\n- [ ] Task 1\n'
            '<!-- STORY_PATCH_END -->\n'
        )
        patches = extract_story_patches(stdout)
        assert len(patches) == 1
        assert patches[0].heading == "## tasks"

    def test_story_patch_is_frozen_dataclass(self) -> None:
        """StoryPatch instances are immutable (frozen dataclass)."""
        patch = StoryPatch(heading="## tasks", content="## Tasks\n- [ ] Done")
        with pytest.raises(Exception):  # FrozenInstanceError
            patch.heading = "changed"  # type: ignore[misc]

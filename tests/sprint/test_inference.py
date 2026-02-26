"""Tests for the evidence-based status inference module."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmad_assist.sprint.inference import (
    InferenceConfidence,
    InferenceResult,
    _get_story_keys_for_epic,
    _normalize_status,
    infer_all_statuses,
    infer_epic_status,
    infer_story_status,
    infer_story_status_detailed,
)
from bmad_assist.sprint.scanner import ArtifactIndex

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_project_full(tmp_path: Path) -> Path:
    """Create a project with comprehensive artifacts for testing inference."""
    # New location: _bmad-output/implementation-artifacts/
    new_base = tmp_path / "_bmad-output" / "implementation-artifacts"

    # Stories with various status scenarios
    stories_dir = new_base / "stories"
    stories_dir.mkdir(parents=True)

    # Story with explicit status "done"
    (stories_dir / "20-1-entry-classification.md").write_text(
        "# Story 20.1\n\nStatus: done\n\nCompleted story."
    )
    # Story with explicit status "in-progress" (uppercase variant)
    (stories_dir / "20-2-models.md").write_text("# Story 20.2\n\nStatus: IN-PROGRESS\n\nWIP story.")
    # Story with explicit status using underscore (ready_for_dev)
    (stories_dir / "20-3-parser.md").write_text(
        "# Story 20.3\n\nStatus: ready_for_dev\n\nReady story."
    )
    # Story with invalid status value
    (stories_dir / "20-4-invalid.md").write_text(
        "# Story 20.4\n\nStatus: custom_invalid_status\n\nInvalid status."
    )
    # Story without Status field (file exists only)
    (stories_dir / "20-5-no-status.md").write_text("# Story 20.5\n\nNo status field here.")
    # Story with empty status value
    (stories_dir / "20-6-empty-status.md").write_text("# Story 20.6\n\nStatus:\n\nEmpty status.")
    # Story for epic with retrospective (should be done)
    (stories_dir / "12-1-completed.md").write_text("# Story 12.1\n\nStatus: done\n\nCompleted.")
    (stories_dir / "12-2-completed.md").write_text("# Story 12.2\n\nStatus: done\n\nCompleted.")
    # Module story
    (stories_dir / "testarch-1-config.md").write_text(
        "# Story testarch.1\n\nStatus: review\n\nModule story."
    )
    # Epic 30 - partial completion test
    (stories_dir / "30-1-partial.md").write_text("# Story 30.1\n\nStatus: done\n\nDone.")
    (stories_dir / "30-2-partial.md").write_text("# Story 30.2\n\nStatus: backlog\n\nNot started.")
    # Epic 31 - active work test
    (stories_dir / "31-1-active.md").write_text("# Story 31.1\n\nStatus: in-progress\n\nWorking.")
    # Epic 32 - ready but not started
    (stories_dir / "32-1-ready.md").write_text("# Story 32.1\n\nStatus: ready-for-dev\n\nReady.")
    (stories_dir / "32-2-ready.md").write_text("# Story 32.2\n\nStatus: backlog\n\nBacklog.")

    # Code reviews for inference tests
    reviews_dir = new_base / "code-reviews"
    reviews_dir.mkdir()
    # Master review/synthesis for 20-4 (should override invalid status → done)
    (reviews_dir / "synthesis-20-4-20260107T120000.md").write_text("# Synthesis 20-4")
    # Validator review only for 20-5 (no master) → review status
    (reviews_dir / "code-review-20-5-validator_a-20260107T120000.md").write_text("# Validator A")
    (reviews_dir / "code-review-20-5-validator_b-20260107T120001.md").write_text("# Validator B")

    # Validations for inference tests
    validations_dir = new_base / "story-validations"
    validations_dir.mkdir()
    # Validation for 20-6 (should override empty status → ready-for-dev)
    # Pattern: validation-{epic}-{story}-{role_id}-{timestamp}.md (role_id is single letter)
    (validations_dir / "validation-20-6-a-20260107T100000.md").write_text("# Validation")

    # Retrospectives
    retros_dir = new_base / "retrospectives"
    retros_dir.mkdir()
    (retros_dir / "epic-12-retro-20260105.md").write_text("# Epic 12 Retrospective")
    (retros_dir / "epic-testarch-retro-20260104.md").write_text("# Testarch Retrospective")

    return tmp_path


@pytest.fixture
def index(temp_project_full: Path) -> ArtifactIndex:
    """Create artifact index from test project."""
    return ArtifactIndex.scan(temp_project_full)


# ============================================================================
# Tests: InferenceConfidence Enum
# ============================================================================


class TestInferenceConfidence:
    """Tests for InferenceConfidence enum."""

    def test_ordering(self) -> None:
        """Test that confidence levels are correctly ordered."""
        assert InferenceConfidence.NONE < InferenceConfidence.WEAK
        assert InferenceConfidence.WEAK < InferenceConfidence.MEDIUM
        assert InferenceConfidence.MEDIUM < InferenceConfidence.STRONG
        assert InferenceConfidence.STRONG < InferenceConfidence.EXPLICIT

    def test_comparison_operators(self) -> None:
        """Test comparison operators work correctly."""
        assert InferenceConfidence.EXPLICIT > InferenceConfidence.STRONG
        assert InferenceConfidence.MEDIUM >= InferenceConfidence.MEDIUM
        assert InferenceConfidence.WEAK <= InferenceConfidence.WEAK
        assert InferenceConfidence.NONE != InferenceConfidence.EXPLICIT

    def test_int_values(self) -> None:
        """Test integer values for enum members."""
        assert int(InferenceConfidence.NONE) == 0
        assert int(InferenceConfidence.WEAK) == 1
        assert int(InferenceConfidence.MEDIUM) == 2
        assert int(InferenceConfidence.STRONG) == 3
        assert int(InferenceConfidence.EXPLICIT) == 4

    def test_str_method(self) -> None:
        """Test __str__ returns lowercase name."""
        assert str(InferenceConfidence.EXPLICIT) == "explicit"
        assert str(InferenceConfidence.NONE) == "none"


# ============================================================================
# Tests: InferenceResult Dataclass
# ============================================================================


class TestInferenceResult:
    """Tests for InferenceResult dataclass."""

    def test_creation(self) -> None:
        """Test creating InferenceResult."""
        result = InferenceResult(
            key="20-1-test",
            status="done",
            confidence=InferenceConfidence.STRONG,
            evidence_sources=(Path("/test/review.md"),),
        )
        assert result.key == "20-1-test"
        assert result.status == "done"
        assert result.confidence == InferenceConfidence.STRONG
        assert len(result.evidence_sources) == 1

    def test_frozen(self) -> None:
        """Test that InferenceResult is immutable."""
        result = InferenceResult(
            key="20-1-test",
            status="done",
            confidence=InferenceConfidence.STRONG,
        )
        with pytest.raises(AttributeError):
            result.status = "backlog"  # type: ignore[misc]

    def test_default_evidence_sources(self) -> None:
        """Test default empty evidence_sources."""
        result = InferenceResult(
            key="20-1-test",
            status="backlog",
            confidence=InferenceConfidence.NONE,
        )
        assert result.evidence_sources == ()

    def test_repr(self) -> None:
        """Test __repr__ output."""
        result = InferenceResult(
            key="20-1-test",
            status="done",
            confidence=InferenceConfidence.STRONG,
        )
        repr_str = repr(result)
        assert "InferenceResult" in repr_str
        assert "20-1-test" in repr_str
        assert "done" in repr_str
        assert "STRONG" in repr_str


# ============================================================================
# Tests: _normalize_status Helper
# ============================================================================


class TestNormalizeStatus:
    """Tests for _normalize_status helper function."""

    def test_lowercase_preserved(self) -> None:
        """Test lowercase status passes through."""
        assert _normalize_status("done") == "done"
        assert _normalize_status("backlog") == "backlog"
        assert _normalize_status("in-progress") == "in-progress"

    def test_uppercase_normalized(self) -> None:
        """Test uppercase is normalized to lowercase."""
        assert _normalize_status("DONE") == "done"
        assert _normalize_status("Done") == "done"
        assert _normalize_status("IN-PROGRESS") == "in-progress"

    def test_underscore_to_dash(self) -> None:
        """Test underscores are converted to dashes."""
        assert _normalize_status("ready_for_dev") == "ready-for-dev"
        assert _normalize_status("in_progress") == "in-progress"

    def test_space_to_dash(self) -> None:
        """Test spaces are converted to dashes."""
        assert _normalize_status("ready for dev") == "ready-for-dev"
        assert _normalize_status("in progress") == "in-progress"

    def test_whitespace_stripped(self) -> None:
        """Test whitespace is stripped."""
        assert _normalize_status("  done  ") == "done"
        assert _normalize_status("\tdone\n") == "done"

    def test_invalid_returns_none(self) -> None:
        """Test invalid status returns None."""
        assert _normalize_status("invalid") is None
        assert _normalize_status("custom-status") is None
        assert _normalize_status("completed") is None  # Not a valid status

    def test_empty_returns_none(self) -> None:
        """Test empty string returns None."""
        assert _normalize_status("") is None
        assert _normalize_status("   ") is None

    def test_all_valid_statuses(self) -> None:
        """Test all valid status values are recognized."""
        valid_statuses = [
            "backlog",
            "ready-for-dev",
            "in-progress",
            "review",
            "done",
            "blocked",
            "deferred",
        ]
        for status in valid_statuses:
            assert _normalize_status(status) == status


# ============================================================================
# Tests: _get_story_keys_for_epic Helper
# ============================================================================


class TestGetStoryKeysForEpic:
    """Tests for _get_story_keys_for_epic helper function."""

    def test_numeric_epic(self, index: ArtifactIndex) -> None:
        """Test finding stories for numeric epic."""
        keys = _get_story_keys_for_epic(20, index)
        assert len(keys) >= 6
        assert all(k.startswith("20-") for k in keys)
        # Should be sorted by story number
        assert keys[0].startswith("20-1-")
        assert keys[1].startswith("20-2-")

    def test_string_epic(self, index: ArtifactIndex) -> None:
        """Test finding stories for string epic."""
        keys = _get_story_keys_for_epic("testarch", index)
        assert len(keys) == 1
        assert keys[0] == "testarch-1-config"

    def test_nonexistent_epic(self, index: ArtifactIndex) -> None:
        """Test empty list for nonexistent epic."""
        keys = _get_story_keys_for_epic(99, index)
        assert keys == []

    def test_no_collision_with_prefix(self, index: ArtifactIndex) -> None:
        """Test that epic 1 doesn't match epic 12."""
        # Epic 12 exists with stories
        keys_12 = _get_story_keys_for_epic(12, index)
        assert len(keys_12) >= 2

        # Epic 1 should not match epic 12's stories
        keys_1 = _get_story_keys_for_epic(1, index)
        assert all(k.startswith("1-") for k in keys_1)
        # Should not contain any keys starting with "12-"
        assert not any(k.startswith("12-") for k in keys_1)


# ============================================================================
# Tests: infer_story_status Function
# ============================================================================


class TestInferStoryStatus:
    """Tests for infer_story_status function."""

    def test_priority1_explicit_status(self, index: ArtifactIndex) -> None:
        """Test Priority 1: Explicit Status field in story file."""
        status, confidence = infer_story_status("20-1-entry-classification", index)
        assert status == "done"
        assert confidence == InferenceConfidence.EXPLICIT

    def test_priority1_case_variant_status(self, index: ArtifactIndex) -> None:
        """Test Priority 1: Status with case variation is normalized."""
        status, confidence = infer_story_status("20-2-models", index)
        assert status == "in-progress"
        assert confidence == InferenceConfidence.EXPLICIT

    def test_priority1_underscore_variant_status(self, index: ArtifactIndex) -> None:
        """Test Priority 1: Status with underscore is normalized."""
        status, confidence = infer_story_status("20-3-parser", index)
        assert status == "ready-for-dev"
        assert confidence == InferenceConfidence.EXPLICIT

    def test_invalid_status_falls_through(self, index: ArtifactIndex) -> None:
        """Test that invalid status falls through to next priority."""
        # Story 20-4 has invalid status but has master review
        status, confidence = infer_story_status("20-4-invalid", index)
        assert status == "done"  # From master review
        assert confidence == InferenceConfidence.STRONG

    def test_priority2_master_review(self, index: ArtifactIndex) -> None:
        """Test Priority 2: Master code review exists → done."""
        # Story 20-4 has invalid status but master review exists
        status, confidence = infer_story_status("20-4", index)
        assert status == "done"
        assert confidence == InferenceConfidence.STRONG

    def test_priority3_validator_reviews(self, index: ArtifactIndex) -> None:
        """Test Priority 3: Validator reviews exist → review."""
        # Story 20-5 has no status, no master review, but has validator reviews
        status, confidence = infer_story_status("20-5-no-status", index)
        assert status == "review"
        assert confidence == InferenceConfidence.MEDIUM

    def test_priority4_validation_exists(self, index: ArtifactIndex) -> None:
        """Test Priority 4: Validation report exists → ready-for-dev."""
        # Story 20-6 has empty status, no reviews, but has validation
        status, confidence = infer_story_status("20-6-empty-status", index)
        assert status == "ready-for-dev"
        assert confidence == InferenceConfidence.MEDIUM

    def test_priority5_story_file_only(self, temp_project_full: Path) -> None:
        """Test Priority 5: Story file exists only → in-progress."""
        # Create story with no status, no reviews, no validations
        stories_dir = temp_project_full / "_bmad-output" / "implementation-artifacts" / "stories"
        (stories_dir / "99-1-orphan.md").write_text("# Orphan story\n\nNo status.")

        index = ArtifactIndex.scan(temp_project_full)
        status, confidence = infer_story_status("99-1-orphan", index)
        assert status == "in-progress"
        assert confidence == InferenceConfidence.WEAK

    def test_priority6_no_evidence(self, index: ArtifactIndex) -> None:
        """Test Priority 6: No evidence → backlog."""
        status, confidence = infer_story_status("99-99-nonexistent", index)
        assert status == "backlog"
        assert confidence == InferenceConfidence.NONE

    def test_short_key_lookup(self, index: ArtifactIndex) -> None:
        """Test that short keys work for lookup."""
        status, confidence = infer_story_status("20-1", index)
        assert status == "done"
        assert confidence == InferenceConfidence.EXPLICIT


# ============================================================================
# Tests: infer_story_status_detailed Function
# ============================================================================


class TestInferStoryStatusDetailed:
    """Tests for infer_story_status_detailed function."""

    def test_returns_inference_result(self, index: ArtifactIndex) -> None:
        """Test that function returns InferenceResult."""
        result = infer_story_status_detailed("20-1-entry-classification", index)
        assert isinstance(result, InferenceResult)
        assert result.key == "20-1-entry-classification"
        assert result.status == "done"
        assert result.confidence == InferenceConfidence.EXPLICIT

    def test_explicit_evidence_sources(self, index: ArtifactIndex) -> None:
        """Test evidence sources for explicit status."""
        result = infer_story_status_detailed("20-1-entry-classification", index)
        assert len(result.evidence_sources) == 1
        assert result.evidence_sources[0].name == "20-1-entry-classification.md"

    def test_master_review_evidence_sources(self, index: ArtifactIndex) -> None:
        """Test evidence sources for master review inference."""
        result = infer_story_status_detailed("20-4-invalid", index)
        assert result.status == "done"
        assert result.confidence == InferenceConfidence.STRONG
        assert len(result.evidence_sources) >= 1
        assert any("synthesis" in str(p) for p in result.evidence_sources)

    def test_validator_review_evidence_sources(self, index: ArtifactIndex) -> None:
        """Test evidence sources for validator review inference."""
        result = infer_story_status_detailed("20-5-no-status", index)
        assert result.status == "review"
        assert result.confidence == InferenceConfidence.MEDIUM
        # Should have multiple validator reviews
        assert len(result.evidence_sources) >= 2
        assert all("validator" in str(p) for p in result.evidence_sources)

    def test_validation_evidence_sources(self, index: ArtifactIndex) -> None:
        """Test evidence sources for validation inference."""
        result = infer_story_status_detailed("20-6-empty-status", index)
        assert result.status == "ready-for-dev"
        assert result.confidence == InferenceConfidence.MEDIUM
        assert len(result.evidence_sources) >= 1
        assert any("validation" in str(p) for p in result.evidence_sources)

    def test_no_evidence_empty_sources(self, index: ArtifactIndex) -> None:
        """Test empty evidence sources when no evidence."""
        result = infer_story_status_detailed("99-99-nonexistent", index)
        assert result.status == "backlog"
        assert result.confidence == InferenceConfidence.NONE
        assert result.evidence_sources == ()


# ============================================================================
# Tests: infer_epic_status Function
# ============================================================================


class TestInferEpicStatus:
    """Tests for infer_epic_status function."""

    def test_retrospective_exists(self, index: ArtifactIndex) -> None:
        """Test epic with retrospective → done (STRONG)."""
        status, confidence = infer_epic_status(12, index)
        assert status == "done"
        assert confidence == InferenceConfidence.STRONG

    def test_retrospective_string_epic(self, index: ArtifactIndex) -> None:
        """Test string epic with retrospective → done."""
        status, confidence = infer_epic_status("testarch", index)
        assert status == "done"
        assert confidence == InferenceConfidence.STRONG

    def test_empty_story_list(self, index: ArtifactIndex) -> None:
        """Test epic with no stories → backlog (NONE)."""
        status, confidence = infer_epic_status(99, index)
        assert status == "backlog"
        assert confidence == InferenceConfidence.NONE

    def test_all_stories_done(self, temp_project_full: Path) -> None:
        """Test all stories done → epic done (MEDIUM)."""
        # Epic 12 has all stories done but we need to check without retro
        # Create new epic with all done stories but no retro
        stories_dir = temp_project_full / "_bmad-output" / "implementation-artifacts" / "stories"
        (stories_dir / "40-1-all-done.md").write_text("# Story 40.1\n\nStatus: done\n")
        (stories_dir / "40-2-all-done.md").write_text("# Story 40.2\n\nStatus: done\n")

        index = ArtifactIndex.scan(temp_project_full)
        status, confidence = infer_epic_status(40, index)
        assert status == "done"
        assert confidence == InferenceConfidence.MEDIUM

    def test_partial_completion(self, index: ArtifactIndex) -> None:
        """Test partial completion (some done, some backlog) → in-progress."""
        status, confidence = infer_epic_status(30, index)
        assert status == "in-progress"
        assert confidence == InferenceConfidence.MEDIUM

    def test_active_stories(self, index: ArtifactIndex) -> None:
        """Test active stories (in-progress/review) → in-progress."""
        status, confidence = infer_epic_status(31, index)
        assert status == "in-progress"
        assert confidence == InferenceConfidence.MEDIUM

    def test_ready_not_started(self, index: ArtifactIndex) -> None:
        """Test stories ready but not started → backlog (WEAK)."""
        status, confidence = infer_epic_status(32, index)
        assert status == "backlog"
        assert confidence == InferenceConfidence.WEAK

    def test_with_precomputed_statuses(self, index: ArtifactIndex) -> None:
        """Test using pre-computed story statuses."""
        story_statuses = {
            "50-1-test": "done",
            "50-2-test": "done",
        }
        status, confidence = infer_epic_status(50, index, story_statuses)
        assert status == "done"
        assert confidence == InferenceConfidence.MEDIUM


# ============================================================================
# Tests: infer_all_statuses Function
# ============================================================================


class TestInferAllStatuses:
    """Tests for infer_all_statuses function."""

    def test_all_stories_inferred(self, index: ArtifactIndex) -> None:
        """Test that all stories are inferred."""
        results = infer_all_statuses(index)
        assert len(results) > 0
        assert all(isinstance(r, InferenceResult) for r in results.values())

    def test_returns_dict(self, index: ArtifactIndex) -> None:
        """Test that function returns dict mapping key to result."""
        results = infer_all_statuses(index)
        assert isinstance(results, dict)
        for key, result in results.items():
            assert isinstance(key, str)
            assert result.key == key

    def test_specific_keys(self, index: ArtifactIndex) -> None:
        """Test inferring specific story keys only."""
        specific_keys = ["20-1-entry-classification", "20-2-models"]
        results = infer_all_statuses(index, story_keys=specific_keys)
        assert len(results) == 2
        assert "20-1-entry-classification" in results
        assert "20-2-models" in results

    def test_empty_keys_list(self, index: ArtifactIndex) -> None:
        """Test empty keys list returns empty dict."""
        results = infer_all_statuses(index, story_keys=[])
        assert results == {}


# ============================================================================
# Tests: Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_story_file_with_whitespace_only_status(self, temp_project_full: Path) -> None:
        """Test story with whitespace-only status."""
        stories_dir = temp_project_full / "_bmad-output" / "implementation-artifacts" / "stories"
        (stories_dir / "98-1-whitespace.md").write_text("# Story\n\nStatus:   \n\nContent")

        index = ArtifactIndex.scan(temp_project_full)
        # Should fall through to file exists → in-progress
        status, confidence = infer_story_status("98-1-whitespace", index)
        assert status == "in-progress"
        assert confidence == InferenceConfidence.WEAK

    def test_mixed_evidence_explicit_wins(self, index: ArtifactIndex) -> None:
        """Test that explicit status wins even with other evidence."""
        # Story 20-1 has explicit status AND could have reviews/validations
        # But explicit status should always win
        status, confidence = infer_story_status("20-1-entry-classification", index)
        assert confidence == InferenceConfidence.EXPLICIT

    def test_case_insensitive_key_lookup(self, index: ArtifactIndex) -> None:
        """Test that key lookup is case insensitive."""
        # The normalization in scanner should handle this
        status1, _ = infer_story_status("20-1", index)
        status2, _ = infer_story_status("20-1-Entry-Classification", index)
        # Both should find the same story
        assert status1 == status2

    def test_epic_status_respects_retrospective_over_stories(self, index: ArtifactIndex) -> None:
        """Test that retrospective takes precedence over story statuses."""
        # Epic 12 has retrospective → should be done regardless of story statuses
        status, confidence = infer_epic_status(12, index)
        assert status == "done"
        assert confidence == InferenceConfidence.STRONG


# ============================================================================
# Tests: Real Project Integration
# ============================================================================


class TestRealProjectIntegration:
    """Integration tests using real project artifacts."""

    @pytest.fixture
    def real_project_root(self) -> Path:
        """Get the real project root path."""
        return Path(__file__).parent.parent.parent

    def test_infer_real_story_status(self, real_project_root: Path) -> None:
        """Test inferring status for real story."""
        if not (real_project_root / "_bmad-output").exists():
            pytest.skip("Real project artifacts not available")

        index = ArtifactIndex.scan(real_project_root)

        # Should find some stories
        if len(index.story_files) == 0:
            pytest.skip("No stories found in real project")

        # Infer status for first story
        first_key = list(index.story_files.keys())[0]
        status, confidence = infer_story_status(first_key, index)

        # Status should be valid
        valid_statuses = [
            "backlog",
            "ready-for-dev",
            "in-progress",
            "review",
            "done",
            "blocked",
            "deferred",
        ]
        assert status in valid_statuses
        assert confidence in InferenceConfidence

    def test_infer_all_real_statuses(self, real_project_root: Path) -> None:
        """Test batch inference on real project."""
        if not (real_project_root / "_bmad-output").exists():
            pytest.skip("Real project artifacts not available")

        index = ArtifactIndex.scan(real_project_root)
        results = infer_all_statuses(index)

        # All results should be valid
        for result in results.values():
            assert isinstance(result, InferenceResult)
            assert result.confidence in InferenceConfidence

    def test_infer_real_epic_status(self, real_project_root: Path) -> None:
        """Test inferring epic status from real project."""
        if not (real_project_root / "_bmad-output").exists():
            pytest.skip("Real project artifacts not available")

        index = ArtifactIndex.scan(real_project_root)

        # Try epic 12 if it exists
        if index.has_retrospective(12):
            status, confidence = infer_epic_status(12, index)
            assert status == "done"
            assert confidence == InferenceConfidence.STRONG

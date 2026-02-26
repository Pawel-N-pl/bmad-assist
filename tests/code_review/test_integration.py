"""Integration tests for code review benchmarking.

Story 13.10: Code Review Benchmarking Integration

Tests cover:
- Task 13: Integration tests for storage and reports (AC: #4, #7, #8)
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bmad_assist.benchmarking import (
    EnvironmentInfo,
    EvaluatorInfo,
    EvaluatorRole,
    ExecutionTelemetry,
    LLMEvaluationRecord,
    OutputAnalysis,
    PatchInfo,
    StoryInfo,
    WorkflowInfo,
)
from bmad_assist.benchmarking.reports import (
    MultiPhaseResult,
    compare_models,
    compare_models_by_phase,
    generate_multi_phase_report_markdown,
)
from bmad_assist.benchmarking.storage import (
    RecordFilters,
    list_evaluation_records,
    save_evaluation_record,
)
from bmad_assist.code_review.orchestrator import CODE_REVIEW_WORKFLOW_ID

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """Create base directory for storage."""
    base = tmp_path / "docs" / "sprint-artifacts"
    base.mkdir(parents=True)
    return base


def _create_record(
    workflow_id: str,
    provider: str,
    model: str,
    role: EvaluatorRole = EvaluatorRole.VALIDATOR,
    epic_num: int = 1,
    story_num: int = 1,
) -> LLMEvaluationRecord:
    """Create a test evaluation record."""
    import uuid

    timestamp = datetime.now(UTC)
    return LLMEvaluationRecord(
        record_id=f"test-{workflow_id}-{provider}-{model}-{uuid.uuid4().hex[:8]}",
        created_at=timestamp,
        workflow=WorkflowInfo(
            id=workflow_id,
            version="1.0.0",
            variant="default",
            patch=PatchInfo(applied=False),
        ),
        story=StoryInfo(
            epic_num=epic_num,
            story_num=story_num,
            title=f"Test Story {epic_num}.{story_num}",
            complexity_flags={},
        ),
        evaluator=EvaluatorInfo(
            role=role,
            role_id="a" if role == EvaluatorRole.VALIDATOR else None,
            provider=provider,
            model=model,
            session_id=f"session-{uuid.uuid4().hex[:8]}",
        ),
        execution=ExecutionTelemetry(
            start_time=timestamp,
            end_time=timestamp,
            duration_ms=1000,
            input_tokens=100,
            output_tokens=200,
            sequence_position=0,
        ),
        output=OutputAnalysis(
            char_count=1000,
            heading_count=5,
            list_depth_max=2,
            code_block_count=1,
            sections_detected=["Summary", "Findings"],
        ),
        environment=EnvironmentInfo(
            bmad_assist_version="0.1.0",
            python_version="3.11.0",
            platform="linux",
            git_commit_hash="test123",
        ),
    )


# ============================================================================
# Tests for storage workflow_id filtering (AC: #4, #7)
# ============================================================================


class TestStorageWorkflowIdFiltering:
    """Test storage filtering by workflow_id."""

    def test_filter_by_workflow_id(self, base_dir: Path) -> None:
        """Test that records can be filtered by workflow_id."""
        # Create records with different workflow IDs
        validation_record = _create_record(
            workflow_id="validate-story",
            provider="claude",
            model="sonnet",
        )
        code_review_record = _create_record(
            workflow_id=CODE_REVIEW_WORKFLOW_ID,
            provider="claude",
            model="sonnet",
        )

        # Save both records
        save_evaluation_record(validation_record, base_dir)
        save_evaluation_record(code_review_record, base_dir)

        # Filter by validate-story
        filters = RecordFilters(workflow_id="validate-story")
        summaries = list_evaluation_records(base_dir, filters)

        assert len(summaries) == 1
        assert summaries[0].workflow_id == "validate-story"

        # Filter by code-review
        filters = RecordFilters(workflow_id=CODE_REVIEW_WORKFLOW_ID)
        summaries = list_evaluation_records(base_dir, filters)

        assert len(summaries) == 1
        assert summaries[0].workflow_id == CODE_REVIEW_WORKFLOW_ID

    def test_workflow_id_in_record_summary(self, base_dir: Path) -> None:
        """Test that workflow_id is included in RecordSummary."""
        record = _create_record(
            workflow_id=CODE_REVIEW_WORKFLOW_ID,
            provider="gemini",
            model="2.5-flash",
        )
        save_evaluation_record(record, base_dir)

        summaries = list_evaluation_records(base_dir, None)

        assert len(summaries) == 1
        assert summaries[0].workflow_id == CODE_REVIEW_WORKFLOW_ID


# ============================================================================
# Tests for multi-phase reports (AC: #8)
# ============================================================================


class TestMultiPhaseReports:
    """Test multi-phase model comparison reports."""

    def test_compare_models_with_workflow_filter(self, base_dir: Path) -> None:
        """Test compare_models filters by workflow_id."""
        # Create validation records
        save_evaluation_record(
            _create_record("validate-story", "claude", "sonnet"),
            base_dir,
        )
        save_evaluation_record(
            _create_record("validate-story", "gemini", "2.5-flash"),
            base_dir,
        )

        # Create code review records
        save_evaluation_record(
            _create_record(CODE_REVIEW_WORKFLOW_ID, "claude", "sonnet"),
            base_dir,
        )

        # Compare only validation phase
        result = compare_models(base_dir, workflow_id="validate-story")

        assert result.total_records == 2

        # Compare only code review phase
        result = compare_models(base_dir, workflow_id=CODE_REVIEW_WORKFLOW_ID)

        assert result.total_records == 1

    def test_compare_models_by_phase_discovers_workflows(self, base_dir: Path) -> None:
        """Test that compare_models_by_phase discovers all workflow IDs."""
        # Create records with different workflow IDs
        save_evaluation_record(
            _create_record("validate-story", "claude", "sonnet"),
            base_dir,
        )
        save_evaluation_record(
            _create_record(CODE_REVIEW_WORKFLOW_ID, "claude", "sonnet"),
            base_dir,
        )
        save_evaluation_record(
            _create_record("validate-story-synthesis", "claude", "opus"),
            base_dir,
        )

        # Compare by phase (no specific workflow_ids)
        result = compare_models_by_phase(base_dir)

        assert len(result.phases) == 3
        assert "validate-story" in result.phases
        assert CODE_REVIEW_WORKFLOW_ID in result.phases
        assert "validate-story-synthesis" in result.phases

    def test_compare_models_by_phase_with_specific_workflows(self, base_dir: Path) -> None:
        """Test compare_models_by_phase with specific workflow list."""
        # Create records
        save_evaluation_record(
            _create_record("validate-story", "claude", "sonnet"),
            base_dir,
        )
        save_evaluation_record(
            _create_record(CODE_REVIEW_WORKFLOW_ID, "claude", "sonnet"),
            base_dir,
        )
        save_evaluation_record(
            _create_record("other-workflow", "claude", "sonnet"),
            base_dir,
        )

        # Only compare specific phases
        result = compare_models_by_phase(
            base_dir,
            workflow_ids=["validate-story", CODE_REVIEW_WORKFLOW_ID],
        )

        assert len(result.phases) == 2
        assert "other-workflow" not in result.phases

    def test_generate_multi_phase_report_markdown(self, base_dir: Path) -> None:
        """Test markdown report generation for multi-phase comparison."""
        # Create records
        save_evaluation_record(
            _create_record("validate-story", "claude", "sonnet"),
            base_dir,
        )
        save_evaluation_record(
            _create_record(CODE_REVIEW_WORKFLOW_ID, "gemini", "2.5-flash"),
            base_dir,
        )

        result = compare_models_by_phase(base_dir)
        markdown = generate_multi_phase_report_markdown(result)

        # Check header
        assert "# Multi-Phase Model Comparison Report" in markdown

        # Check phase sections
        assert "## Phase: validate-story" in markdown
        assert f"## Phase: {CODE_REVIEW_WORKFLOW_ID}" in markdown

        # Check model tables
        assert "| Model | Evaluations |" in markdown

    def test_empty_result_generates_valid_report(self, base_dir: Path) -> None:
        """Test that empty result still generates valid markdown."""
        result = MultiPhaseResult(
            phases={},
            total_records=0,
            generated_at=datetime.now(UTC),
            notes=["No records found"],
        )

        markdown = generate_multi_phase_report_markdown(result)

        assert "# Multi-Phase Model Comparison Report" in markdown
        assert "No records found" in markdown

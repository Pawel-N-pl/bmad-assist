"""Unit tests for benchmarking reports module.

Tests for Story 13.8: Workflow Comparison Report.
Tests for Story 13.9: Model Comparison Report.
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from bmad_assist.benchmarking.schema import (
    ConsensusData,
    EnvironmentInfo,
    EvaluatorInfo,
    EvaluatorRole,
    ExecutionTelemetry,
    FindingsExtracted,
    LLMEvaluationRecord,
    OutputAnalysis,
    PatchInfo,
    QualitySignals,
    StoryInfo,
    WorkflowInfo,
)
from bmad_assist.benchmarking.storage import StorageError

# =============================================================================
# Task 1: Dataclass Tests
# =============================================================================


class TestVariantMetrics:
    """Test VariantMetrics dataclass (AC4)."""

    def test_create_with_all_fields(self) -> None:
        """Test creating VariantMetrics with all fields populated."""
        from bmad_assist.benchmarking.reports import VariantMetrics

        metrics = VariantMetrics(
            variant="control",
            count=15,
            date_range=(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 15, tzinfo=UTC)),
            mean_findings_count=12.5,
            std_findings_count=3.2,
            validator_count=5,
        )

        assert metrics.variant == "control"
        assert metrics.count == 15
        assert metrics.mean_findings_count == 12.5
        assert metrics.validator_count == 5

    def test_create_with_none_metrics(self) -> None:
        """Test creating VariantMetrics with None for optional metrics."""
        from bmad_assist.benchmarking.reports import VariantMetrics

        metrics = VariantMetrics(
            variant="empty",
            count=0,
            date_range=None,
            mean_findings_count=None,
            std_findings_count=None,
            validator_count=0,
        )

        assert metrics.variant == "empty"
        assert metrics.count == 0
        assert metrics.mean_findings_count is None

    def test_frozen_dataclass(self) -> None:
        """Test that VariantMetrics is immutable."""
        from bmad_assist.benchmarking.reports import VariantMetrics

        metrics = VariantMetrics(
            variant="test",
            count=5,
            date_range=None,
            mean_findings_count=10.0,
            std_findings_count=2.0,
            validator_count=2,
        )

        with pytest.raises(AttributeError):
            metrics.variant = "modified"  # type: ignore[misc]


class TestMetricComparison:
    """Test MetricComparison dataclass (AC4)."""

    def test_create_with_all_fields(self) -> None:
        """Test creating MetricComparison with all fields."""
        from bmad_assist.benchmarking.reports import MetricComparison

        comparison = MetricComparison(
            name="Agreement Score",
            value_a=0.85,
            std_a=0.05,
            count_a=12,
            value_b=0.78,
            std_b=0.08,
            count_b=15,
            delta=0.07,
            p_value=0.023,
            significant=True,
            format_spec=".2f",
        )

        assert comparison.name == "Agreement Score"
        assert comparison.delta == 0.07
        assert comparison.significant is True

    def test_create_with_none_values(self) -> None:
        """Test creating MetricComparison with None for insufficient data."""
        from bmad_assist.benchmarking.reports import MetricComparison

        comparison = MetricComparison(
            name="Findings Count",
            value_a=None,
            std_a=None,
            count_a=0,
            value_b=5.0,
            std_b=1.5,
            count_b=10,
            delta=None,
            p_value=None,
            significant=None,
            format_spec=".1f",
        )

        assert comparison.value_a is None
        assert comparison.delta is None
        assert comparison.significant is None


class TestComparisonResult:
    """Test ComparisonResult dataclass (AC4)."""

    def test_create_full_result(self) -> None:
        """Test creating ComparisonResult with all components."""
        from bmad_assist.benchmarking.reports import (
            ComparisonResult,
            MetricComparison,
            VariantMetrics,
        )

        variant_a = VariantMetrics(
            variant="v1",
            count=10,
            date_range=None,
            mean_findings_count=5.0,
            std_findings_count=1.0,
            validator_count=2,
        )

        variant_b = VariantMetrics(
            variant="v2",
            count=12,
            date_range=None,
            mean_findings_count=6.0,
            std_findings_count=1.5,
            validator_count=2,
        )

        metrics = [
            MetricComparison(
                name="Findings Count",
                value_a=5.0,
                std_a=1.0,
                count_a=2,
                value_b=6.0,
                std_b=1.5,
                count_b=2,
                delta=-1.0,
                p_value=0.15,
                significant=False,
                format_spec=".1f",
            ),
        ]

        result = ComparisonResult(
            variant_a=variant_a,
            variant_b=variant_b,
            metrics=metrics,
            generated_at=datetime.now(UTC),
            notes=["Both variants have sufficient samples"],
            scipy_available=True,
        )

        assert result.variant_a.variant == "v1"
        assert result.variant_b.variant == "v2"
        assert len(result.metrics) == 1
        assert result.scipy_available is True


# =============================================================================
# Helper Functions for Creating Test Records
# =============================================================================


def _create_test_record(
    variant: str,
    role: EvaluatorRole,
    agreement_score: float | None = None,
    findings_count: int | None = None,
    actionable_ratio: float | None = None,
    specificity_score: float | None = None,
    role_id: str | None = None,
) -> LLMEvaluationRecord:
    """Create a test evaluation record with specified values."""
    # Ensure role_id is set for validators
    if role == EvaluatorRole.VALIDATOR and role_id is None:
        role_id = "a"

    workflow = WorkflowInfo(
        id="validate-story",
        version="1.0.0",
        variant=variant,
        patch=PatchInfo(applied=False),
    )

    story = StoryInfo(
        epic_num=13,
        story_num=8,
        title="Test Story",
        complexity_flags={},
    )

    evaluator = EvaluatorInfo(
        provider="claude",
        model="opus-4",
        role=role,
        role_id=role_id,
        session_id="test-session",
    )

    execution = ExecutionTelemetry(
        start_time=datetime.now(UTC),
        end_time=datetime.now(UTC),
        duration_ms=1000,
        input_tokens=1000,
        output_tokens=500,
        retries=0,
        sequence_position=0,
    )

    output = OutputAnalysis(
        char_count=5000,
        heading_count=10,
        list_depth_max=3,
        code_block_count=5,
        sections_detected=["Summary", "Findings"],
    )

    environment = EnvironmentInfo(
        bmad_assist_version="0.1.0",
        python_version="3.11.0",
        platform="linux",
    )

    # Build optional fields
    consensus = None
    quality = None
    findings = None

    if agreement_score is not None:
        consensus = ConsensusData(
            agreed_findings=5,
            unique_findings=2,
            disputed_findings=1,
            agreement_score=agreement_score,
        )

    if actionable_ratio is not None or specificity_score is not None:
        quality = QualitySignals(
            actionable_ratio=actionable_ratio or 0.5,
            specificity_score=specificity_score or 0.5,
            evidence_quality=0.7,
            follows_template=True,
            internal_consistency=0.8,
        )

    if findings_count is not None:
        findings = FindingsExtracted(
            total_count=findings_count,
            by_severity={"major": findings_count // 2, "minor": findings_count // 2},
            by_category={"security": findings_count},
            has_fix_count=findings_count // 2,
            has_location_count=findings_count,
            has_evidence_count=findings_count,
        )

    return LLMEvaluationRecord(
        workflow=workflow,
        story=story,
        evaluator=evaluator,
        execution=execution,
        output=output,
        environment=environment,
        consensus=consensus,
        quality=quality,
        findings=findings,
    )


# =============================================================================
# Task 9: Unit tests for metrics aggregation (AC: #4)
# =============================================================================


class TestCalculateMeanStd:
    """Test _calculate_mean_std helper function."""

    def test_empty_list(self) -> None:
        """Test with empty list returns (None, None)."""
        from bmad_assist.benchmarking.reports import _calculate_mean_std

        mean, std = _calculate_mean_std([])
        assert mean is None
        assert std is None

    def test_single_value(self) -> None:
        """Test with single value returns (value, None)."""
        from bmad_assist.benchmarking.reports import _calculate_mean_std

        mean, std = _calculate_mean_std([5.0])
        assert mean == 5.0
        assert std is None  # Not enough values for std

    def test_two_values(self) -> None:
        """Test with two values returns mean and std."""
        from bmad_assist.benchmarking.reports import _calculate_mean_std

        mean, std = _calculate_mean_std([4.0, 6.0])
        assert mean == 5.0
        assert std is not None
        assert abs(std - 1.4142) < 0.01  # sqrt(2) ≈ 1.414

    def test_multiple_values(self) -> None:
        """Test with multiple values."""
        from bmad_assist.benchmarking.reports import _calculate_mean_std

        values = [2.0, 4.0, 6.0, 8.0, 10.0]
        mean, std = _calculate_mean_std(values)
        assert mean == 6.0
        assert std is not None
        assert abs(std - 3.162) < 0.01  # sqrt(10) ≈ 3.162


class TestAggregateVariantMetrics:
    """Test _aggregate_variant_metrics function (AC4)."""

    def test_empty_records(self) -> None:
        """Test aggregation with empty record list."""
        from bmad_assist.benchmarking.reports import _aggregate_variant_metrics

        metrics = _aggregate_variant_metrics([], "empty")

        assert metrics.variant == "empty"
        assert metrics.count == 0
        assert metrics.date_range is None
        assert metrics.mean_findings_count is None
        assert metrics.validator_count == 0

    def test_validator_records_only(self) -> None:
        """Test aggregation with validator records only."""
        from bmad_assist.benchmarking.reports import _aggregate_variant_metrics

        records = [
            _create_test_record("v1", EvaluatorRole.VALIDATOR, findings_count=10, role_id="a"),
            _create_test_record("v1", EvaluatorRole.VALIDATOR, findings_count=14, role_id="b"),
        ]

        metrics = _aggregate_variant_metrics(records, "v1")

        assert metrics.count == 2
        assert metrics.validator_count == 2
        assert metrics.mean_findings_count == 12.0

    def test_mixed_records(self) -> None:
        """Test aggregation with both synthesizer and validator records."""
        from bmad_assist.benchmarking.reports import _aggregate_variant_metrics

        records = [
            _create_test_record("v1", EvaluatorRole.SYNTHESIZER, agreement_score=0.85),
            _create_test_record("v1", EvaluatorRole.VALIDATOR, findings_count=12, role_id="a"),
        ]

        metrics = _aggregate_variant_metrics(records, "v1")

        assert metrics.count == 2
        assert metrics.validator_count == 1
        assert metrics.mean_findings_count == 12.0

    def test_none_values_excluded(self) -> None:
        """Test that None values are excluded from calculations."""
        from bmad_assist.benchmarking.reports import _aggregate_variant_metrics

        # Create validator records with missing findings
        records = [
            _create_test_record("v1", EvaluatorRole.VALIDATOR, findings_count=10, role_id="a"),
            _create_test_record("v1", EvaluatorRole.VALIDATOR, role_id="b"),  # No findings
        ]

        metrics = _aggregate_variant_metrics(records, "v1")

        # Should only use the one record with findings_count
        assert metrics.mean_findings_count == 10.0
        assert metrics.std_findings_count is None  # Only one valid value


# =============================================================================
# Task 10: Unit tests for significance testing (AC: #5)
# =============================================================================


class TestCalculateSignificance:
    """Test _calculate_significance function (AC5)."""

    def test_insufficient_samples_a(self) -> None:
        """Test with insufficient samples in first variant."""
        from bmad_assist.benchmarking.reports import _calculate_significance

        values_a = [1.0, 2.0, 3.0]  # Less than 10
        values_b = [1.0] * 15

        p_val, sig = _calculate_significance(values_a, values_b)

        assert p_val is None
        assert sig is None

    def test_insufficient_samples_b(self) -> None:
        """Test with insufficient samples in second variant."""
        from bmad_assist.benchmarking.reports import _calculate_significance

        values_a = [1.0] * 15
        values_b = [1.0, 2.0, 3.0]  # Less than 10

        p_val, sig = _calculate_significance(values_a, values_b)

        assert p_val is None
        assert sig is None

    def test_sufficient_samples_significant(self) -> None:
        """Test with sufficient samples showing significant difference."""
        from bmad_assist.benchmarking.reports import _calculate_significance

        # Create two clearly different distributions
        values_a = [10.0] * 12  # All 10s
        values_b = [1.0] * 12  # All 1s

        p_val, sig = _calculate_significance(values_a, values_b)

        # Should have scipy available in test environment
        if p_val is not None:
            assert p_val < 0.05
            assert sig == True  # noqa: E712 - numpy bool comparison

    def test_sufficient_samples_not_significant(self) -> None:
        """Test with sufficient samples showing no significant difference."""
        from bmad_assist.benchmarking.reports import _calculate_significance

        # Create two similar distributions
        values_a = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]
        values_b = [5.0, 4.9, 5.1, 5.0, 4.8, 5.2, 5.0, 4.9, 5.1, 5.0]

        p_val, sig = _calculate_significance(values_a, values_b)

        if p_val is not None:
            assert p_val > 0.05
            assert sig == False  # noqa: E712 - numpy bool comparison

    def test_scipy_not_available(self) -> None:
        """Test graceful degradation when scipy is not available."""
        values_a = [1.0] * 15
        values_b = [2.0] * 15

        with patch.dict("sys.modules", {"scipy": None, "scipy.stats": None}):
            # Force reimport to pick up patched module
            import importlib

            import bmad_assist.benchmarking.reports as reports_module

            importlib.reload(reports_module)

            # This test verifies the import handling works
            # The actual behavior depends on whether scipy is installed


class TestCheckScipyAvailable:
    """Test _check_scipy_available helper."""

    def test_scipy_available(self) -> None:
        """Test when scipy is installed."""
        from bmad_assist.benchmarking.reports import _check_scipy_available

        # Assuming scipy is installed in test environment
        result = _check_scipy_available()
        # Can be True or False depending on environment
        assert isinstance(result, bool)


# =============================================================================
# Task 11: Unit tests for report generation (AC: #6)
# =============================================================================


class TestGenerateComparisonReport:
    """Test generate_comparison_report function (AC6)."""

    def test_full_report_structure(self) -> None:
        """Test that report has all required sections."""
        from bmad_assist.benchmarking.reports import (
            ComparisonResult,
            MetricComparison,
            VariantMetrics,
            generate_comparison_report,
        )

        variant_a = VariantMetrics(
            variant="control",
            count=15,
            date_range=(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 15, tzinfo=UTC)),
            mean_findings_count=12.5,
            std_findings_count=3.2,
            validator_count=5,
        )

        variant_b = VariantMetrics(
            variant="experimental",
            count=12,
            date_range=(datetime(2025, 1, 5, tzinfo=UTC), datetime(2025, 1, 20, tzinfo=UTC)),
            mean_findings_count=10.0,
            std_findings_count=2.5,
            validator_count=4,
        )

        metrics = [
            MetricComparison(
                name="Findings Count",
                value_a=12.5,
                std_a=3.2,
                count_a=5,
                value_b=10.0,
                std_b=2.5,
                count_b=4,
                delta=2.5,
                p_value=0.023,
                significant=True,
                format_spec=".1f",
            ),
        ]

        result = ComparisonResult(
            variant_a=variant_a,
            variant_b=variant_b,
            metrics=metrics,
            generated_at=datetime(2025, 1, 20, 12, 0, 0, tzinfo=UTC),
            notes=["Test note"],
            scipy_available=True,
        )

        report = generate_comparison_report(result)

        # Check required sections
        assert "# Workflow Comparison Report" in report
        assert "## Sample Sizes" in report
        assert "## Metrics Comparison" in report
        assert "## Interpretation" in report
        assert "## Notes" in report

        # Check variant names appear
        assert "control" in report
        assert "experimental" in report

    def test_table_formatting(self) -> None:
        """Test that tables are properly formatted."""
        from bmad_assist.benchmarking.reports import (
            ComparisonResult,
            MetricComparison,
            VariantMetrics,
            generate_comparison_report,
        )

        variant_a = VariantMetrics(
            variant="v1",
            count=10,
            date_range=None,
            mean_findings_count=None,
            std_findings_count=None,
            validator_count=0,
        )

        variant_b = VariantMetrics(
            variant="v2",
            count=8,
            date_range=None,
            mean_findings_count=None,
            std_findings_count=None,
            validator_count=0,
        )

        metrics = [
            MetricComparison(
                name="Findings Count",
                value_a=None,
                std_a=None,
                count_a=0,
                value_b=None,
                std_b=None,
                count_b=0,
                delta=None,
                p_value=None,
                significant=None,
                format_spec=".1f",
            ),
        ]

        result = ComparisonResult(
            variant_a=variant_a,
            variant_b=variant_b,
            metrics=metrics,
            generated_at=datetime.now(UTC),
            notes=[],
            scipy_available=True,
        )

        report = generate_comparison_report(result)

        # Check table structure
        assert "| Variant | Count | Date Range |" in report
        assert "|---------|-------|------------|" in report
        assert "| Metric |" in report

    def test_interpretation_generation(self) -> None:
        """Test interpretation section generation."""
        from bmad_assist.benchmarking.reports import (
            ComparisonResult,
            MetricComparison,
            VariantMetrics,
            generate_comparison_report,
        )

        variant_a = VariantMetrics(
            variant="v1",
            count=10,
            date_range=None,
            mean_findings_count=15.0,
            std_findings_count=2.0,
            validator_count=10,
        )

        variant_b = VariantMetrics(
            variant="v2",
            count=10,
            date_range=None,
            mean_findings_count=10.0,
            std_findings_count=1.5,
            validator_count=10,
        )

        metrics = [
            MetricComparison(
                name="Findings Count",
                value_a=15.0,
                std_a=2.0,
                count_a=10,
                value_b=10.0,
                std_b=1.5,
                count_b=10,
                delta=5.0,
                p_value=0.001,
                significant=True,
                format_spec=".1f",
            ),
        ]

        result = ComparisonResult(
            variant_a=variant_a,
            variant_b=variant_b,
            metrics=metrics,
            generated_at=datetime.now(UTC),
            notes=[],
            scipy_available=True,
        )

        report = generate_comparison_report(result)

        # Check interpretation section exists
        assert "## Interpretation" in report
        assert "v1" in report  # Should mention the better variant

    def test_edge_case_no_data(self) -> None:
        """Test report generation with no data."""
        from bmad_assist.benchmarking.reports import (
            ComparisonResult,
            MetricComparison,
            VariantMetrics,
            generate_comparison_report,
        )

        empty_metrics = VariantMetrics(
            variant="empty",
            count=0,
            date_range=None,
            mean_findings_count=None,
            std_findings_count=None,
            validator_count=0,
        )

        metrics = [
            MetricComparison(
                name="Findings Count",
                value_a=None,
                std_a=None,
                count_a=0,
                value_b=None,
                std_b=None,
                count_b=0,
                delta=None,
                p_value=None,
                significant=None,
                format_spec=".1f",
            ),
        ]

        result = ComparisonResult(
            variant_a=empty_metrics,
            variant_b=empty_metrics,
            metrics=metrics,
            generated_at=datetime.now(UTC),
            notes=["No data for variant empty"],
            scipy_available=True,
        )

        report = generate_comparison_report(result)

        assert "No data for variant empty" in report
        assert "N/A" in report  # Should show N/A for missing values

    def test_scipy_unavailable_note(self) -> None:
        """Test that scipy unavailable note is included."""
        from bmad_assist.benchmarking.reports import (
            ComparisonResult,
            VariantMetrics,
            generate_comparison_report,
        )

        variant = VariantMetrics(
            variant="v1",
            count=5,
            date_range=None,
            mean_findings_count=None,
            std_findings_count=None,
            validator_count=0,
        )

        result = ComparisonResult(
            variant_a=variant,
            variant_b=variant,
            metrics=[],
            generated_at=datetime.now(UTC),
            notes=[],
            scipy_available=False,
        )

        report = generate_comparison_report(result)

        assert "scipy not installed - significance testing unavailable" in report


# =============================================================================
# Task 12: Integration tests (AC: #1, #2, #7)
# =============================================================================


class TestCompareWorkflowVariants:
    """Test compare_workflow_variants main function."""

    def test_basic_comparison(self, tmp_path: Path) -> None:
        """Test basic comparison with mocked storage."""
        from bmad_assist.benchmarking.reports import compare_workflow_variants

        # Create mock records
        records_a = [
            _create_test_record("v1", EvaluatorRole.SYNTHESIZER, agreement_score=0.85),
            _create_test_record("v1", EvaluatorRole.SYNTHESIZER, agreement_score=0.90),
        ]
        records_b = [
            _create_test_record("v2", EvaluatorRole.SYNTHESIZER, agreement_score=0.75),
            _create_test_record("v2", EvaluatorRole.SYNTHESIZER, agreement_score=0.80),
        ]

        # Mock the storage functions
        with patch("bmad_assist.benchmarking.reports.list_evaluation_records") as mock_list:
            with patch("bmad_assist.benchmarking.reports.load_evaluation_record") as mock_load:
                # Create mock summaries
                summaries = []
                for i, r in enumerate(records_a + records_b):
                    mock_summary = Mock()
                    mock_summary.path = tmp_path / f"record_{i}.yaml"
                    summaries.append(mock_summary)

                mock_list.return_value = summaries
                mock_load.side_effect = records_a + records_b

                result = compare_workflow_variants("v1", "v2", tmp_path)

        assert result.variant_a.variant == "v1"
        assert result.variant_b.variant == "v2"
        assert result.variant_a.count == 2
        assert result.variant_b.count == 2

    def test_no_records_found(self, tmp_path: Path) -> None:
        """Test comparison with no records found."""
        from bmad_assist.benchmarking.reports import compare_workflow_variants

        with patch("bmad_assist.benchmarking.reports.list_evaluation_records") as mock_list:
            mock_list.return_value = []

            result = compare_workflow_variants("v1", "v2", tmp_path)

        assert result.variant_a.count == 0
        assert result.variant_b.count == 0
        assert "No data for variant v1" in result.notes
        assert "No data for variant v2" in result.notes

    def test_one_variant_empty(self, tmp_path: Path) -> None:
        """Test comparison with one empty variant."""
        from bmad_assist.benchmarking.reports import compare_workflow_variants

        records_a = [
            _create_test_record("v1", EvaluatorRole.SYNTHESIZER, agreement_score=0.85),
        ]

        with patch("bmad_assist.benchmarking.reports.list_evaluation_records") as mock_list:
            with patch("bmad_assist.benchmarking.reports.load_evaluation_record") as mock_load:
                mock_summary = Mock()
                mock_summary.path = tmp_path / "record.yaml"
                mock_list.return_value = [mock_summary]
                mock_load.return_value = records_a[0]

                result = compare_workflow_variants("v1", "v2", tmp_path)

        assert result.variant_a.count == 1
        assert result.variant_b.count == 0
        assert "No data for variant v2" in result.notes

    def test_date_range_filtering(self, tmp_path: Path) -> None:
        """Test that date range is passed to storage layer."""
        from bmad_assist.benchmarking.reports import compare_workflow_variants

        date_from = datetime(2025, 1, 1, tzinfo=UTC)
        date_to = datetime(2025, 1, 31, tzinfo=UTC)

        with patch("bmad_assist.benchmarking.reports.list_evaluation_records") as mock_list:
            mock_list.return_value = []

            compare_workflow_variants("v1", "v2", tmp_path, date_from, date_to)

            # Verify filters were passed
            call_args = mock_list.call_args
            filters = call_args[0][1]  # Second positional arg is filters
            assert filters.date_from == date_from
            assert filters.date_to == date_to


@pytest.mark.skipif(os.environ.get("CI") == "true", reason="Rich/Typer help rendering unreliable in CI")
class TestCLIBenchmarkCompare:
    """Test CLI benchmark compare command (AC1, AC8)."""

    def test_cli_help(self) -> None:
        """Test that CLI help shows expected options."""
        from typer.testing import CliRunner

        from bmad_assist.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "--help"])

        assert result.exit_code == 0
        assert "Workflow benchmarking comparison commands" in result.output

    def test_compare_help(self, cli_isolated_env: Path) -> None:
        """Test that compare subcommand help shows all options."""
        from typer.testing import CliRunner

        from bmad_assist.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "compare", "--help"])

        assert result.exit_code == 0
        assert "--variant-a" in result.output
        assert "--variant-b" in result.output
        assert "--output" in result.output
        assert "--from" in result.output
        assert "--to" in result.output
        assert "--project" in result.output

    def test_compare_basic_execution(self, tmp_path: Path) -> None:
        """Test basic CLI execution with mocked comparison."""
        from typer.testing import CliRunner

        from bmad_assist.cli import app

        runner = CliRunner()

        # Create project structure
        (tmp_path / "docs" / "sprint-artifacts").mkdir(parents=True)

        with patch("bmad_assist.benchmarking.reports.compare_workflow_variants") as mock_compare:
            with patch(
                "bmad_assist.benchmarking.reports.generate_comparison_report"
            ) as mock_report:
                from bmad_assist.benchmarking.reports import (
                    ComparisonResult,
                    VariantMetrics,
                )

                # Create mock result
                mock_metrics = VariantMetrics(
                    variant="v1",
                    count=5,
                    date_range=None,
                    mean_findings_count=None,
                    std_findings_count=None,
                    validator_count=0,
                )
                mock_result = ComparisonResult(
                    variant_a=mock_metrics,
                    variant_b=mock_metrics,
                    metrics=[],
                    generated_at=datetime.now(UTC),
                    notes=[],
                    scipy_available=True,
                )
                mock_compare.return_value = mock_result
                mock_report.return_value = "# Report"

                result = runner.invoke(
                    app,
                    [
                        "benchmark",
                        "compare",
                        "--variant-a",
                        "control",
                        "--variant-b",
                        "experimental",
                        "--project",
                        str(tmp_path),
                    ],
                )

        assert result.exit_code == 0
        assert "# Report" in result.output

    def test_compare_output_to_file(self, tmp_path: Path) -> None:
        """Test CLI writes to file when --output specified."""
        from typer.testing import CliRunner

        from bmad_assist.cli import app

        runner = CliRunner()

        # Create project structure
        (tmp_path / "docs" / "sprint-artifacts").mkdir(parents=True)
        output_file = tmp_path / "report.md"

        with patch("bmad_assist.benchmarking.reports.compare_workflow_variants") as mock_compare:
            with patch(
                "bmad_assist.benchmarking.reports.generate_comparison_report"
            ) as mock_report:
                from bmad_assist.benchmarking.reports import (
                    ComparisonResult,
                    VariantMetrics,
                )

                mock_metrics = VariantMetrics(
                    variant="v1",
                    count=5,
                    date_range=None,
                    mean_findings_count=None,
                    std_findings_count=None,
                    validator_count=0,
                )
                mock_result = ComparisonResult(
                    variant_a=mock_metrics,
                    variant_b=mock_metrics,
                    metrics=[],
                    generated_at=datetime.now(UTC),
                    notes=[],
                    scipy_available=True,
                )
                mock_compare.return_value = mock_result
                mock_report.return_value = "# Test Report Content"

                result = runner.invoke(
                    app,
                    [
                        "benchmark",
                        "compare",
                        "--variant-a",
                        "v1",
                        "--variant-b",
                        "v2",
                        "--output",
                        str(output_file),
                        "--project",
                        str(tmp_path),
                    ],
                )

        assert result.exit_code == 0
        assert output_file.exists()
        assert output_file.read_text() == "# Test Report Content"

    def test_compare_invalid_date(self, tmp_path: Path) -> None:
        """Test CLI handles invalid date format."""
        from typer.testing import CliRunner

        from bmad_assist.cli import app

        runner = CliRunner()

        # Create project structure
        (tmp_path / "docs" / "sprint-artifacts").mkdir(parents=True)

        result = runner.invoke(
            app,
            [
                "benchmark",
                "compare",
                "--variant-a",
                "v1",
                "--variant-b",
                "v2",
                "--from",
                "not-a-date",
                "--project",
                str(tmp_path),
            ],
        )

        assert result.exit_code == 1
        assert "Invalid --from date format" in result.output


# =============================================================================
# Story 13.9: Model Comparison Report Tests
# =============================================================================


# =============================================================================
# Task 1 & 11: Dataclass Tests for Model Comparison
# =============================================================================


class TestSeverityDistribution:
    """Test SeverityDistribution dataclass (AC4)."""

    def test_create_with_all_fields(self) -> None:
        """Test creating SeverityDistribution with all fields populated."""
        from bmad_assist.benchmarking.reports import SeverityDistribution

        dist = SeverityDistribution(
            critical_pct=0.05,
            major_pct=0.25,
            minor_pct=0.45,
            nit_pct=0.25,
            other_pct=0.0,
        )

        assert dist.critical_pct == 0.05
        assert dist.major_pct == 0.25
        assert dist.minor_pct == 0.45
        assert dist.nit_pct == 0.25
        assert dist.other_pct == 0.0

    def test_create_with_none_values(self) -> None:
        """Test creating SeverityDistribution with None values."""
        from bmad_assist.benchmarking.reports import SeverityDistribution

        dist = SeverityDistribution(
            critical_pct=None,
            major_pct=None,
            minor_pct=None,
            nit_pct=None,
            other_pct=None,
        )

        assert dist.critical_pct is None
        assert dist.major_pct is None

    def test_frozen_dataclass(self) -> None:
        """Test that SeverityDistribution is immutable."""
        from bmad_assist.benchmarking.reports import SeverityDistribution

        dist = SeverityDistribution(
            critical_pct=0.1,
            major_pct=0.2,
            minor_pct=0.3,
            nit_pct=0.3,
            other_pct=0.1,
        )

        with pytest.raises(AttributeError):
            dist.critical_pct = 0.5  # type: ignore[misc]


class TestModelTendencies:
    """Test ModelTendencies dataclass (AC5)."""

    def test_create_with_all_fields(self) -> None:
        """Test creating ModelTendencies with all fields."""
        from bmad_assist.benchmarking.reports import ModelTendencies

        tendencies = ModelTendencies(
            strength="High evidence citation (1.35x average)",
            tendency="Verbose reports (+40% avg length)",
            bias="Over-reports critical issues",
        )

        assert tendencies.strength == "High evidence citation (1.35x average)"
        assert tendencies.tendency == "Verbose reports (+40% avg length)"
        assert tendencies.bias == "Over-reports critical issues"

    def test_create_with_none_values(self) -> None:
        """Test creating ModelTendencies with None values."""
        from bmad_assist.benchmarking.reports import ModelTendencies

        tendencies = ModelTendencies(
            strength=None,
            tendency=None,
            bias=None,
        )

        assert tendencies.strength is None
        assert tendencies.tendency is None
        assert tendencies.bias is None


class TestModelMetrics:
    """Test ModelMetrics dataclass (AC3)."""

    def test_create_with_all_fields(self) -> None:
        """Test creating ModelMetrics with all fields populated."""
        from bmad_assist.benchmarking.reports import (
            ModelMetrics,
            ModelTendencies,
            SeverityDistribution,
        )

        severity = SeverityDistribution(
            critical_pct=0.05,
            major_pct=0.25,
            minor_pct=0.45,
            nit_pct=0.25,
            other_pct=0.0,
        )

        tendencies = ModelTendencies(
            strength="High evidence citation",
            tendency="Verbose reports",
            bias=None,
        )

        metrics = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=45,
            validator_count=40,
            synthesizer_count=5,
            mean_findings_count=8.2,
            std_findings_count=2.1,
            severity_distribution=severity,
            false_positive_rate=0.12,
            ground_truth_count=10,
            mean_char_count=4520.5,
            low_confidence=False,
            tendencies=tendencies,
        )

        assert metrics.provider == "claude"
        assert metrics.model == "opus-4"
        assert metrics.total_evaluations == 45
        assert metrics.false_positive_rate == 0.12
        assert metrics.low_confidence is False
        assert metrics.tendencies is not None
        assert metrics.tendencies.strength == "High evidence citation"

    def test_create_with_none_metrics(self) -> None:
        """Test creating ModelMetrics with None for optional metrics."""
        from bmad_assist.benchmarking.reports import ModelMetrics

        metrics = ModelMetrics(
            provider="gemini",
            model="2.0-flash",
            total_evaluations=3,
            validator_count=2,
            synthesizer_count=1,
            mean_findings_count=None,
            std_findings_count=None,
            severity_distribution=None,
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=None,
            low_confidence=True,
            tendencies=None,
        )

        assert metrics.mean_findings_count is None
        assert metrics.severity_distribution is None
        assert metrics.low_confidence is True
        assert metrics.tendencies is None

    def test_frozen_dataclass(self) -> None:
        """Test that ModelMetrics is immutable."""
        from bmad_assist.benchmarking.reports import ModelMetrics

        metrics = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=10,
            validator_count=8,
            synthesizer_count=2,
            mean_findings_count=5.0,
            std_findings_count=1.0,
            severity_distribution=None,
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=3000.0,
            low_confidence=False,
            tendencies=None,
        )

        with pytest.raises(AttributeError):
            metrics.provider = "modified"  # type: ignore[misc]


class TestModelComparisonResult:
    """Test ModelComparisonResult dataclass (AC7)."""

    def test_create_full_result(self) -> None:
        """Test creating ModelComparisonResult with all components."""
        from bmad_assist.benchmarking.reports import (
            ModelComparisonResult,
            ModelMetrics,
        )

        model1 = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=45,
            validator_count=40,
            synthesizer_count=5,
            mean_findings_count=8.2,
            std_findings_count=2.1,
            severity_distribution=None,
            false_positive_rate=0.12,
            ground_truth_count=10,
            mean_char_count=4500.0,
            low_confidence=False,
            tendencies=None,
        )

        model2 = ModelMetrics(
            provider="gemini",
            model="2.0-flash",
            total_evaluations=40,
            validator_count=35,
            synthesizer_count=5,
            mean_findings_count=6.5,
            std_findings_count=1.8,
            severity_distribution=None,
            false_positive_rate=0.18,
            ground_truth_count=8,
            mean_char_count=3200.0,
            low_confidence=False,
            tendencies=None,
        )

        result = ModelComparisonResult(
            models=[model1, model2],
            generated_at=datetime.now(UTC),
            total_records=85,
            date_range=(datetime(2025, 12, 1, tzinfo=UTC), datetime(2025, 12, 20, tzinfo=UTC)),
            notes=["FP Rate only available for 2 models"],
        )

        assert len(result.models) == 2
        assert result.total_records == 85
        assert result.date_range is not None
        assert len(result.notes) == 1


# =============================================================================
# Task 2: Record Loading and Grouping Tests (AC2)
# =============================================================================


def _create_model_test_record(
    provider: str,
    model: str,
    role: EvaluatorRole,
    findings_count: int | None = None,
    char_count: int = 5000,
    include_reasoning: bool = False,
    ground_truth_populated: bool = False,
    findings_confirmed: int = 0,
    findings_false_alarm: int = 0,
    by_severity: dict[str, int] | None = None,
    role_id: str | None = None,
) -> LLMEvaluationRecord:
    """Create a test evaluation record for model comparison tests."""
    from bmad_assist.benchmarking.schema import (
        GroundTruth,
        ReasoningPatterns,
    )

    # Ensure role_id is set for validators
    if role == EvaluatorRole.VALIDATOR and role_id is None:
        role_id = "a"

    workflow = WorkflowInfo(
        id="validate-story",
        version="1.0.0",
        variant="default",
        patch=PatchInfo(applied=False),
    )

    story = StoryInfo(
        epic_num=13,
        story_num=9,
        title="Model Comparison Test",
        complexity_flags={},
    )

    evaluator = EvaluatorInfo(
        provider=provider,
        model=model,
        role=role,
        role_id=role_id,
        session_id="test-session",
    )

    execution = ExecutionTelemetry(
        start_time=datetime.now(UTC),
        end_time=datetime.now(UTC),
        duration_ms=1000,
        input_tokens=1000,
        output_tokens=500,
        retries=0,
        sequence_position=0,
    )

    output = OutputAnalysis(
        char_count=char_count,
        heading_count=10,
        list_depth_max=3,
        code_block_count=5,
        sections_detected=["Summary", "Findings"],
    )

    environment = EnvironmentInfo(
        bmad_assist_version="0.1.0",
        python_version="3.11.0",
        platform="linux",
    )

    # Build optional fields
    findings = None
    if findings_count is not None:
        findings = FindingsExtracted(
            total_count=findings_count,
            by_severity=by_severity or {"major": findings_count // 2, "minor": findings_count // 2},
            by_category={"security": findings_count},
            has_fix_count=findings_count // 2,
            has_location_count=findings_count,
            has_evidence_count=findings_count,
        )

    reasoning = None
    if include_reasoning:
        reasoning = ReasoningPatterns(
            cites_prd=True,
            cites_architecture=True,
            cites_story_sections=True,
            uses_conditionals=True,
            uncertainty_phrases_count=2,
            confidence_phrases_count=3,
        )

    ground_truth = None
    if ground_truth_populated:
        ground_truth = GroundTruth(
            populated=True,
            populated_at=datetime.now(UTC),
            findings_confirmed=findings_confirmed,
            findings_false_alarm=findings_false_alarm,
        )

    return LLMEvaluationRecord(
        workflow=workflow,
        story=story,
        evaluator=evaluator,
        execution=execution,
        output=output,
        environment=environment,
        findings=findings,
        reasoning=reasoning,
        ground_truth=ground_truth,
    )


class TestLoadRecordsByModel:
    """Test _load_records_by_model function (AC2)."""

    def test_groups_by_provider_and_model(self, tmp_path: Path) -> None:
        """Test records are grouped by (provider, model) tuple."""
        from bmad_assist.benchmarking.reports import _load_records_by_model

        # Create records with different provider/model combinations
        records = [
            _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR, role_id="a"),
            _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR, role_id="b"),
            _create_model_test_record("claude", "sonnet-4", EvaluatorRole.VALIDATOR, role_id="c"),
            _create_model_test_record("gemini", "2.0-flash", EvaluatorRole.VALIDATOR, role_id="d"),
        ]

        with patch("bmad_assist.benchmarking.reports.list_evaluation_records") as mock_list:
            with patch("bmad_assist.benchmarking.reports.load_evaluation_record") as mock_load:
                summaries = []
                for i, r in enumerate(records):
                    mock_summary = Mock()
                    mock_summary.path = tmp_path / f"record_{i}.yaml"
                    summaries.append(mock_summary)

                mock_list.return_value = summaries
                mock_load.side_effect = records

                result = _load_records_by_model(tmp_path)

        # Should have 3 groups: (claude, opus-4), (claude, sonnet-4), (gemini, 2.0-flash)
        assert len(result) == 3
        assert ("claude", "opus-4") in result
        assert ("claude", "sonnet-4") in result
        assert ("gemini", "2.0-flash") in result
        assert len(result[("claude", "opus-4")]) == 2
        assert len(result[("claude", "sonnet-4")]) == 1
        assert len(result[("gemini", "2.0-flash")]) == 1

    def test_empty_records(self, tmp_path: Path) -> None:
        """Test with no records found."""
        from bmad_assist.benchmarking.reports import _load_records_by_model

        with patch("bmad_assist.benchmarking.reports.list_evaluation_records") as mock_list:
            mock_list.return_value = []
            result = _load_records_by_model(tmp_path)

        assert result == {}

    def test_handles_storage_error(self, tmp_path: Path) -> None:
        """Test graceful handling of storage errors."""
        from bmad_assist.benchmarking.reports import _load_records_by_model

        good_record = _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR)

        with patch("bmad_assist.benchmarking.reports.list_evaluation_records") as mock_list:
            with patch("bmad_assist.benchmarking.reports.load_evaluation_record") as mock_load:
                mock_summary1 = Mock()
                mock_summary1.path = tmp_path / "good.yaml"
                mock_summary2 = Mock()
                mock_summary2.path = tmp_path / "bad.yaml"
                mock_list.return_value = [mock_summary1, mock_summary2]

                # First call succeeds, second raises error
                mock_load.side_effect = [good_record, StorageError("Load failed")]

                result = _load_records_by_model(tmp_path)

        # Should still have one good record
        assert len(result) == 1
        assert ("claude", "opus-4") in result

    def test_date_range_filtering(self, tmp_path: Path) -> None:
        """Test date range parameters are passed to storage layer."""
        from bmad_assist.benchmarking.reports import _load_records_by_model

        date_from = datetime(2025, 12, 1, tzinfo=UTC)
        date_to = datetime(2025, 12, 20, tzinfo=UTC)

        with patch("bmad_assist.benchmarking.reports.list_evaluation_records") as mock_list:
            mock_list.return_value = []

            _load_records_by_model(tmp_path, date_from, date_to)

            call_args = mock_list.call_args
            filters = call_args[0][1]
            assert filters.date_from == date_from
            assert filters.date_to == date_to


# =============================================================================
# Task 3: Per-Model Metrics Aggregation Tests (AC3)
# =============================================================================


class TestAggregateModelMetrics:
    """Test _aggregate_model_metrics function (AC3)."""

    def test_empty_records(self) -> None:
        """Test aggregation with empty record list."""
        from bmad_assist.benchmarking.reports import _aggregate_model_metrics

        metrics = _aggregate_model_metrics([], "claude", "opus-4")

        assert metrics.provider == "claude"
        assert metrics.model == "opus-4"
        assert metrics.total_evaluations == 0
        assert metrics.validator_count == 0
        assert metrics.synthesizer_count == 0
        assert metrics.mean_findings_count is None
        assert metrics.mean_char_count is None
        assert metrics.low_confidence is True

    def test_validator_records_aggregation(self) -> None:
        """Test aggregation with validator records."""
        from bmad_assist.benchmarking.reports import _aggregate_model_metrics

        records = [
            _create_model_test_record(
                "claude",
                "opus-4",
                EvaluatorRole.VALIDATOR,
                findings_count=10,
                char_count=5000,
                include_reasoning=True,
                role_id="a",
            ),
            _create_model_test_record(
                "claude",
                "opus-4",
                EvaluatorRole.VALIDATOR,
                findings_count=14,
                char_count=6000,
                include_reasoning=True,
                role_id="b",
            ),
        ]

        metrics = _aggregate_model_metrics(records, "claude", "opus-4")

        assert metrics.total_evaluations == 2
        assert metrics.validator_count == 2
        assert metrics.synthesizer_count == 0
        assert metrics.mean_findings_count == 12.0
        assert metrics.mean_char_count == 5500.0

    def test_none_findings_excluded(self) -> None:
        """Test that records with None findings are excluded."""
        from bmad_assist.benchmarking.reports import _aggregate_model_metrics

        records = [
            _create_model_test_record(
                "claude", "opus-4", EvaluatorRole.VALIDATOR, findings_count=10, role_id="a"
            ),
            _create_model_test_record(
                "claude",
                "opus-4",
                EvaluatorRole.VALIDATOR,
                findings_count=None,
                role_id="b",  # No findings
            ),
        ]

        metrics = _aggregate_model_metrics(records, "claude", "opus-4")

        assert metrics.mean_findings_count == 10.0  # Only one record

    def test_none_reasoning_excluded(self) -> None:
        """Test that records with None reasoning are handled correctly."""
        from bmad_assist.benchmarking.reports import _aggregate_model_metrics

        records = [
            _create_model_test_record(
                "claude", "opus-4", EvaluatorRole.VALIDATOR, include_reasoning=True, role_id="a"
            ),
            _create_model_test_record(
                "claude",
                "opus-4",
                EvaluatorRole.VALIDATOR,
                include_reasoning=False,
                role_id="b",  # No reasoning
            ),
        ]

        metrics = _aggregate_model_metrics(records, "claude", "opus-4")

        # Both records count towards total
        assert metrics.total_evaluations == 2

    def test_ground_truth_calculation(self) -> None:
        """Test false positive rate calculation."""
        from bmad_assist.benchmarking.reports import _aggregate_model_metrics

        records = [
            _create_model_test_record(
                "claude",
                "opus-4",
                EvaluatorRole.VALIDATOR,
                ground_truth_populated=True,
                findings_confirmed=8,
                findings_false_alarm=2,
                role_id="a",
            ),
            _create_model_test_record(
                "claude",
                "opus-4",
                EvaluatorRole.VALIDATOR,
                ground_truth_populated=True,
                findings_confirmed=6,
                findings_false_alarm=4,
                role_id="b",
            ),
        ]

        metrics = _aggregate_model_metrics(records, "claude", "opus-4")

        assert metrics.ground_truth_count == 2
        # Total: 14 confirmed, 6 false alarm = 6/(6+14) = 0.3
        assert metrics.false_positive_rate is not None
        assert abs(metrics.false_positive_rate - 0.3) < 0.01

    def test_low_confidence_flag(self) -> None:
        """Test low_confidence flag for <5 evaluations."""
        from bmad_assist.benchmarking.reports import _aggregate_model_metrics

        # 3 records = low confidence
        records = [
            _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR, role_id="a"),
            _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR, role_id="b"),
            _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR, role_id="c"),
        ]

        metrics = _aggregate_model_metrics(records, "claude", "opus-4")

        assert metrics.low_confidence is True

    def test_not_low_confidence_with_sufficient_samples(self) -> None:
        """Test low_confidence is False with >=5 evaluations."""
        from bmad_assist.benchmarking.reports import _aggregate_model_metrics

        records = [
            _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR, role_id="a"),
            _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR, role_id="b"),
            _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR, role_id="c"),
            _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR, role_id="d"),
            _create_model_test_record("claude", "opus-4", EvaluatorRole.VALIDATOR, role_id="e"),
        ]

        metrics = _aggregate_model_metrics(records, "claude", "opus-4")

        assert metrics.low_confidence is False


# =============================================================================
# Task 4: Severity Distribution Tests (AC4)
# =============================================================================


class TestCalculateSeverityDistribution:
    """Test _calculate_severity_distribution function (AC4)."""

    def test_empty_records(self) -> None:
        """Test with empty records returns None distribution."""
        from bmad_assist.benchmarking.reports import _calculate_severity_distribution

        dist = _calculate_severity_distribution([])

        assert dist is None

    def test_no_findings(self) -> None:
        """Test with records that have no findings."""
        from bmad_assist.benchmarking.reports import _calculate_severity_distribution

        records = [
            _create_model_test_record(
                "claude", "opus-4", EvaluatorRole.VALIDATOR, findings_count=None
            ),
        ]

        dist = _calculate_severity_distribution(records)

        assert dist is None

    def test_severity_percentages(self) -> None:
        """Test severity percentage calculation."""
        from bmad_assist.benchmarking.reports import _calculate_severity_distribution

        records = [
            _create_model_test_record(
                "claude",
                "opus-4",
                EvaluatorRole.VALIDATOR,
                findings_count=10,
                by_severity={"critical": 1, "major": 3, "minor": 4, "nit": 2},
            ),
        ]

        dist = _calculate_severity_distribution(records)

        assert dist is not None
        assert abs(dist.critical_pct - 0.10) < 0.01
        assert abs(dist.major_pct - 0.30) < 0.01
        assert abs(dist.minor_pct - 0.40) < 0.01
        assert abs(dist.nit_pct - 0.20) < 0.01
        assert dist.other_pct == 0.0

    def test_unknown_severity_grouped_as_other(self) -> None:
        """Test unknown severity levels are grouped under other."""
        from bmad_assist.benchmarking.reports import _calculate_severity_distribution

        records = [
            _create_model_test_record(
                "claude",
                "opus-4",
                EvaluatorRole.VALIDATOR,
                findings_count=10,
                by_severity={"critical": 2, "major": 3, "unknown_level": 5},
            ),
        ]

        dist = _calculate_severity_distribution(records)

        assert dist is not None
        assert abs(dist.critical_pct - 0.20) < 0.01
        assert abs(dist.major_pct - 0.30) < 0.01
        assert dist.minor_pct == 0.0
        assert dist.nit_pct == 0.0
        assert abs(dist.other_pct - 0.50) < 0.01

    def test_multiple_records_aggregation(self) -> None:
        """Test severity aggregation across multiple records."""
        from bmad_assist.benchmarking.reports import _calculate_severity_distribution

        records = [
            _create_model_test_record(
                "claude",
                "opus-4",
                EvaluatorRole.VALIDATOR,
                findings_count=10,
                by_severity={"critical": 2, "major": 8},
                role_id="a",
            ),
            _create_model_test_record(
                "claude",
                "opus-4",
                EvaluatorRole.VALIDATOR,
                findings_count=10,
                by_severity={"critical": 0, "minor": 10},
                role_id="b",
            ),
        ]

        dist = _calculate_severity_distribution(records)

        # Total: 20 findings, critical=2, major=8, minor=10
        assert dist is not None
        assert abs(dist.critical_pct - 0.10) < 0.01
        assert abs(dist.major_pct - 0.40) < 0.01
        assert abs(dist.minor_pct - 0.50) < 0.01


# =============================================================================
# Task 5: Tendencies Analysis Tests (AC5)
# =============================================================================


class TestAnalyzeModelTendencies:
    """Test _analyze_model_tendencies function (AC5)."""

    def test_returns_none_for_few_models(self) -> None:
        """Test returns None when fewer than 3 models."""
        from bmad_assist.benchmarking.reports import (
            ModelMetrics,
            _analyze_model_tendencies,
        )

        metrics = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=10,
            validator_count=8,
            synthesizer_count=2,
            mean_findings_count=8.0,
            std_findings_count=2.0,
            severity_distribution=None,
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=5000.0,
            low_confidence=False,
            tendencies=None,
        )

        all_metrics = [metrics, metrics]  # Only 2 models

        result = _analyze_model_tendencies(metrics, all_metrics)

        assert result is None

    def test_verbose_detection(self) -> None:
        """Test verbose tendency detection (>1.4x median char_count)."""
        from bmad_assist.benchmarking.reports import (
            ModelMetrics,
            _analyze_model_tendencies,
        )

        # Create metrics with different char counts
        verbose_model = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=10,
            validator_count=8,
            synthesizer_count=2,
            mean_findings_count=8.0,
            std_findings_count=2.0,
            severity_distribution=None,
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=8000.0,  # > 1.4x median
            low_confidence=False,
            tendencies=None,
        )

        normal_models = [
            ModelMetrics(
                provider="gemini",
                model="2.0",
                total_evaluations=10,
                validator_count=8,
                synthesizer_count=2,
                mean_findings_count=6.0,
                std_findings_count=1.0,
                severity_distribution=None,
                false_positive_rate=None,
                ground_truth_count=0,
                mean_char_count=5000.0,
                low_confidence=False,
                tendencies=None,
            ),
            ModelMetrics(
                provider="gpt",
                model="4o",
                total_evaluations=10,
                validator_count=8,
                synthesizer_count=2,
                mean_findings_count=7.0,
                std_findings_count=1.5,
                severity_distribution=None,
                false_positive_rate=None,
                ground_truth_count=0,
                mean_char_count=5000.0,
                low_confidence=False,
                tendencies=None,
            ),
        ]

        all_metrics = [verbose_model] + normal_models

        result = _analyze_model_tendencies(verbose_model, all_metrics)

        assert result is not None
        assert result.tendency is not None
        assert "Verbose" in result.tendency

    def test_terse_detection(self) -> None:
        """Test terse tendency detection (<0.6x median char_count)."""
        from bmad_assist.benchmarking.reports import (
            ModelMetrics,
            _analyze_model_tendencies,
        )

        terse_model = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=10,
            validator_count=8,
            synthesizer_count=2,
            mean_findings_count=8.0,
            std_findings_count=2.0,
            severity_distribution=None,
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=2500.0,  # < 0.6x median
            low_confidence=False,
            tendencies=None,
        )

        normal_models = [
            ModelMetrics(
                provider="gemini",
                model="2.0",
                total_evaluations=10,
                validator_count=8,
                synthesizer_count=2,
                mean_findings_count=6.0,
                std_findings_count=1.0,
                severity_distribution=None,
                false_positive_rate=None,
                ground_truth_count=0,
                mean_char_count=5000.0,
                low_confidence=False,
                tendencies=None,
            ),
            ModelMetrics(
                provider="gpt",
                model="4o",
                total_evaluations=10,
                validator_count=8,
                synthesizer_count=2,
                mean_findings_count=7.0,
                std_findings_count=1.5,
                severity_distribution=None,
                false_positive_rate=None,
                ground_truth_count=0,
                mean_char_count=5000.0,
                low_confidence=False,
                tendencies=None,
            ),
        ]

        all_metrics = [terse_model] + normal_models

        result = _analyze_model_tendencies(terse_model, all_metrics)

        assert result is not None
        assert result.tendency is not None
        assert "Concise" in result.tendency


class TestDetectCategoryBias:
    """Test _detect_category_bias function (AC5)."""

    def test_over_reports_critical(self) -> None:
        """Test detection of over-reporting critical issues."""
        from bmad_assist.benchmarking.reports import (
            ModelMetrics,
            SeverityDistribution,
            _detect_category_bias,
        )

        # Model with high critical percentage
        high_critical = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=10,
            validator_count=8,
            synthesizer_count=2,
            mean_findings_count=8.0,
            std_findings_count=2.0,
            severity_distribution=SeverityDistribution(
                critical_pct=0.30, major_pct=0.30, minor_pct=0.30, nit_pct=0.10, other_pct=0.0
            ),
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=5000.0,
            low_confidence=False,
            tendencies=None,
        )

        normal_models = [
            ModelMetrics(
                provider="gemini",
                model="2.0",
                total_evaluations=10,
                validator_count=8,
                synthesizer_count=2,
                mean_findings_count=6.0,
                std_findings_count=1.0,
                severity_distribution=SeverityDistribution(
                    critical_pct=0.10, major_pct=0.30, minor_pct=0.40, nit_pct=0.20, other_pct=0.0
                ),
                false_positive_rate=None,
                ground_truth_count=0,
                mean_char_count=5000.0,
                low_confidence=False,
                tendencies=None,
            ),
            ModelMetrics(
                provider="gpt",
                model="4o",
                total_evaluations=10,
                validator_count=8,
                synthesizer_count=2,
                mean_findings_count=7.0,
                std_findings_count=1.5,
                severity_distribution=SeverityDistribution(
                    critical_pct=0.10, major_pct=0.35, minor_pct=0.35, nit_pct=0.20, other_pct=0.0
                ),
                false_positive_rate=None,
                ground_truth_count=0,
                mean_char_count=5000.0,
                low_confidence=False,
                tendencies=None,
            ),
        ]

        all_metrics = [high_critical] + normal_models

        bias = _detect_category_bias(high_critical, all_metrics)

        assert bias is not None
        assert "Over-reports critical" in bias

    def test_none_when_no_severity_distribution(self) -> None:
        """Test returns None when model has no severity distribution."""
        from bmad_assist.benchmarking.reports import (
            ModelMetrics,
            _detect_category_bias,
        )

        no_dist = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=10,
            validator_count=8,
            synthesizer_count=2,
            mean_findings_count=8.0,
            std_findings_count=2.0,
            severity_distribution=None,
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=5000.0,
            low_confidence=False,
            tendencies=None,
        )

        bias = _detect_category_bias(no_dist, [no_dist])

        assert bias is None

    def test_priority_order(self) -> None:
        """Test bias detection follows priority order (critical > major > minor > nit)."""
        from bmad_assist.benchmarking.reports import (
            ModelMetrics,
            SeverityDistribution,
            _detect_category_bias,
        )

        # Model over-reports both critical AND major
        over_reports_both = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=10,
            validator_count=8,
            synthesizer_count=2,
            mean_findings_count=8.0,
            std_findings_count=2.0,
            severity_distribution=SeverityDistribution(
                critical_pct=0.30, major_pct=0.50, minor_pct=0.10, nit_pct=0.10, other_pct=0.0
            ),
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=5000.0,
            low_confidence=False,
            tendencies=None,
        )

        normal = ModelMetrics(
            provider="gemini",
            model="2.0",
            total_evaluations=10,
            validator_count=8,
            synthesizer_count=2,
            mean_findings_count=6.0,
            std_findings_count=1.0,
            severity_distribution=SeverityDistribution(
                critical_pct=0.10, major_pct=0.20, minor_pct=0.40, nit_pct=0.30, other_pct=0.0
            ),
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=5000.0,
            low_confidence=False,
            tendencies=None,
        )

        all_metrics = [over_reports_both, normal, normal]  # 3 models needed

        bias = _detect_category_bias(over_reports_both, all_metrics)

        # Should report critical first (higher priority)
        assert bias is not None
        assert "critical" in bias.lower()


# =============================================================================
# Task 6-8: Report Generation and Main Function Tests (AC6, AC7)
# =============================================================================


class TestGenerateModelReportMarkdown:
    """Test generate_model_report_markdown function (AC6)."""

    def test_full_report_structure(self) -> None:
        """Test that report has all required sections."""
        from bmad_assist.benchmarking.reports import (
            ModelComparisonResult,
            ModelMetrics,
            SeverityDistribution,
            generate_model_report_markdown,
        )

        model = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=45,
            validator_count=40,
            synthesizer_count=5,
            mean_findings_count=8.2,
            std_findings_count=2.1,
            severity_distribution=SeverityDistribution(
                critical_pct=0.10, major_pct=0.30, minor_pct=0.40, nit_pct=0.20, other_pct=0.0
            ),
            false_positive_rate=0.12,
            ground_truth_count=10,
            mean_char_count=4500.0,
            low_confidence=False,
            tendencies=None,
        )

        result = ModelComparisonResult(
            models=[model],
            generated_at=datetime.now(UTC),
            total_records=45,
            date_range=(datetime(2025, 12, 1, tzinfo=UTC), datetime(2025, 12, 20, tzinfo=UTC)),
            notes=["Test note"],
        )

        report = generate_model_report_markdown(result)

        # Check required sections
        assert "# Model Comparison Report" in report
        assert "## Summary" in report
        assert "## Model Tendencies" in report
        assert "## Severity Distribution" in report
        assert "## Notes" in report

        # Check model data appears
        assert "claude/opus-4" in report
        assert "12%" in report  # FP rate

    def test_empty_models(self) -> None:
        """Test report with no models."""
        from bmad_assist.benchmarking.reports import (
            ModelComparisonResult,
            generate_model_report_markdown,
        )

        result = ModelComparisonResult(
            models=[],
            generated_at=datetime.now(UTC),
            total_records=0,
            date_range=None,
            notes=["No records found"],
        )

        report = generate_model_report_markdown(result)

        assert "No models to compare" in report


class TestGenerateModelReportJson:
    """Test generate_model_report_json function (AC7)."""

    def test_valid_json_structure(self) -> None:
        """Test that output is valid JSON with correct structure."""
        import json

        from bmad_assist.benchmarking.reports import (
            ModelComparisonResult,
            ModelMetrics,
            generate_model_report_json,
        )

        model = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=10,
            validator_count=8,
            synthesizer_count=2,
            mean_findings_count=5.0,
            std_findings_count=1.0,
            severity_distribution=None,
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=3000.0,
            low_confidence=False,
            tendencies=None,
        )

        result = ModelComparisonResult(
            models=[model],
            generated_at=datetime.now(UTC),
            total_records=10,
            date_range=None,
            notes=[],
        )

        json_str = generate_model_report_json(result)

        # Parse and validate structure
        data = json.loads(json_str)

        assert "generated_at" in data
        assert "total_records" in data
        assert "models" in data
        assert len(data["models"]) == 1

        model_data = data["models"][0]
        assert model_data["provider"] == "claude"
        assert model_data["model"] == "opus-4"
        assert model_data["total_evaluations"] == 10

    def test_serializes_severity_distribution(self) -> None:
        """Test that severity distribution is properly serialized."""
        import json

        from bmad_assist.benchmarking.reports import (
            ModelComparisonResult,
            ModelMetrics,
            SeverityDistribution,
            generate_model_report_json,
        )

        model = ModelMetrics(
            provider="claude",
            model="opus-4",
            total_evaluations=10,
            validator_count=8,
            synthesizer_count=2,
            mean_findings_count=5.0,
            std_findings_count=1.0,
            severity_distribution=SeverityDistribution(
                critical_pct=0.1, major_pct=0.2, minor_pct=0.3, nit_pct=0.3, other_pct=0.1
            ),
            false_positive_rate=None,
            ground_truth_count=0,
            mean_char_count=3000.0,
            low_confidence=False,
            tendencies=None,
        )

        result = ModelComparisonResult(
            models=[model],
            generated_at=datetime.now(UTC),
            total_records=10,
            date_range=None,
            notes=[],
        )

        json_str = generate_model_report_json(result)
        data = json.loads(json_str)

        sev = data["models"][0]["severity_distribution"]
        assert sev is not None
        assert sev["critical_pct"] == 0.1
        assert sev["major_pct"] == 0.2


class TestCompareModels:
    """Test compare_models main function (AC1, AC2)."""

    def test_aggregates_by_model(self, tmp_path: Path) -> None:
        """Test records are grouped by model correctly."""
        from bmad_assist.benchmarking.reports import compare_models

        # Create records for different models
        records = [
            _create_model_test_record(
                "claude", "opus-4", EvaluatorRole.VALIDATOR, findings_count=10, role_id="a"
            ),
            _create_model_test_record(
                "claude", "opus-4", EvaluatorRole.VALIDATOR, findings_count=12, role_id="b"
            ),
            _create_model_test_record(
                "gemini", "2.0-flash", EvaluatorRole.VALIDATOR, findings_count=8, role_id="c"
            ),
        ]

        with patch("bmad_assist.benchmarking.reports.list_evaluation_records") as mock_list:
            with patch("bmad_assist.benchmarking.reports.load_evaluation_record") as mock_load:
                summaries = []
                for i, r in enumerate(records):
                    mock_summary = Mock()
                    mock_summary.path = tmp_path / f"record_{i}.yaml"
                    summaries.append(mock_summary)

                mock_list.return_value = summaries
                mock_load.side_effect = records

                result = compare_models(tmp_path)

        assert len(result.models) == 2
        assert result.total_records == 3

        # Find the claude model
        claude = next(m for m in result.models if m.provider == "claude")
        assert claude.total_evaluations == 2
        assert claude.mean_findings_count == 11.0  # (10+12)/2

    def test_empty_records(self, tmp_path: Path) -> None:
        """Test with no records."""
        from bmad_assist.benchmarking.reports import compare_models

        with patch("bmad_assist.benchmarking.reports.list_evaluation_records") as mock_list:
            mock_list.return_value = []

            result = compare_models(tmp_path)

        assert result.total_records == 0
        assert len(result.models) == 0
        assert "No evaluation records found" in result.notes


# =============================================================================
# Task 9: CLI Tests (AC8)
# =============================================================================


@pytest.mark.skipif(os.environ.get("CI") == "true", reason="Rich/Typer help rendering unreliable in CI")
class TestCLIBenchmarkModels:
    """Test CLI benchmark models command (AC8)."""

    def test_cli_help(self) -> None:
        """Test that CLI help shows models subcommand."""
        from typer.testing import CliRunner

        from bmad_assist.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "--help"])

        assert result.exit_code == 0
        assert "models" in result.output

    def test_models_help(self, cli_isolated_env: Path) -> None:
        """Test that models subcommand help shows all options."""
        from typer.testing import CliRunner

        from bmad_assist.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "models", "--help"])

        assert result.exit_code == 0
        assert "--output" in result.output
        assert "--from" in result.output
        assert "--to" in result.output
        assert "--format" in result.output

    def test_models_basic_execution(self, tmp_path: Path) -> None:
        """Test basic CLI execution with mocked comparison."""
        from typer.testing import CliRunner

        from bmad_assist.cli import app

        runner = CliRunner()

        # Create project structure
        (tmp_path / "docs" / "sprint-artifacts").mkdir(parents=True)

        with patch("bmad_assist.benchmarking.reports.compare_models") as mock_compare:
            with patch(
                "bmad_assist.benchmarking.reports.generate_model_report_markdown"
            ) as mock_report:
                from bmad_assist.benchmarking.reports import (
                    ModelComparisonResult,
                    ModelMetrics,
                )

                mock_metrics = ModelMetrics(
                    provider="claude",
                    model="opus-4",
                    total_evaluations=10,
                    validator_count=8,
                    synthesizer_count=2,
                    mean_findings_count=5.0,
                    std_findings_count=1.0,
                    severity_distribution=None,
                    false_positive_rate=None,
                    ground_truth_count=0,
                    mean_char_count=3000.0,
                    low_confidence=False,
                    tendencies=None,
                )
                mock_result = ModelComparisonResult(
                    models=[mock_metrics],
                    generated_at=datetime.now(UTC),
                    total_records=10,
                    date_range=None,
                    notes=[],
                )
                mock_compare.return_value = mock_result
                mock_report.return_value = "# Model Report"

                result = runner.invoke(
                    app,
                    [
                        "benchmark",
                        "models",
                        "--project",
                        str(tmp_path),
                    ],
                )

        assert result.exit_code == 0
        assert "# Model Report" in result.output

    def test_models_json_output(self, tmp_path: Path) -> None:
        """Test JSON output format."""
        from typer.testing import CliRunner

        from bmad_assist.cli import app

        runner = CliRunner()

        (tmp_path / "docs" / "sprint-artifacts").mkdir(parents=True)

        with patch("bmad_assist.benchmarking.reports.compare_models") as mock_compare:
            with patch("bmad_assist.benchmarking.reports.generate_model_report_json") as mock_json:
                from bmad_assist.benchmarking.reports import (
                    ModelComparisonResult,
                    ModelMetrics,
                )

                mock_metrics = ModelMetrics(
                    provider="claude",
                    model="opus-4",
                    total_evaluations=10,
                    validator_count=8,
                    synthesizer_count=2,
                    mean_findings_count=5.0,
                    std_findings_count=1.0,
                    severity_distribution=None,
                    false_positive_rate=None,
                    ground_truth_count=0,
                    mean_char_count=3000.0,
                    low_confidence=False,
                    tendencies=None,
                )
                mock_result = ModelComparisonResult(
                    models=[mock_metrics],
                    generated_at=datetime.now(UTC),
                    total_records=10,
                    date_range=None,
                    notes=[],
                )
                mock_compare.return_value = mock_result
                mock_json.return_value = '{"models": []}'

                result = runner.invoke(
                    app,
                    [
                        "benchmark",
                        "models",
                        "--format",
                        "json",
                        "--project",
                        str(tmp_path),
                    ],
                )

        assert result.exit_code == 0
        mock_json.assert_called_once()

    def test_models_output_to_file(self, tmp_path: Path) -> None:
        """Test CLI writes to file when --output specified."""
        from typer.testing import CliRunner

        from bmad_assist.cli import app

        runner = CliRunner()

        (tmp_path / "docs" / "sprint-artifacts").mkdir(parents=True)
        output_file = tmp_path / "report.md"

        with patch("bmad_assist.benchmarking.reports.compare_models") as mock_compare:
            with patch(
                "bmad_assist.benchmarking.reports.generate_model_report_markdown"
            ) as mock_report:
                from bmad_assist.benchmarking.reports import (
                    ModelComparisonResult,
                    ModelMetrics,
                )

                mock_metrics = ModelMetrics(
                    provider="claude",
                    model="opus-4",
                    total_evaluations=10,
                    validator_count=8,
                    synthesizer_count=2,
                    mean_findings_count=5.0,
                    std_findings_count=1.0,
                    severity_distribution=None,
                    false_positive_rate=None,
                    ground_truth_count=0,
                    mean_char_count=3000.0,
                    low_confidence=False,
                    tendencies=None,
                )
                mock_result = ModelComparisonResult(
                    models=[mock_metrics],
                    generated_at=datetime.now(UTC),
                    total_records=10,
                    date_range=None,
                    notes=[],
                )
                mock_compare.return_value = mock_result
                mock_report.return_value = "# Test Model Report"

                result = runner.invoke(
                    app,
                    [
                        "benchmark",
                        "models",
                        "--output",
                        str(output_file),
                        "--project",
                        str(tmp_path),
                    ],
                )

        assert result.exit_code == 0
        assert output_file.exists()
        assert output_file.read_text() == "# Test Model Report"

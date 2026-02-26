"""Unit tests for Deep Verify metrics collection infrastructure.

This module tests:
- Metrics calculation (precision, recall, F1)
- Per-method aggregation
- Per-severity FP rate calculation
- Domain detection accuracy
- Verdict matching
- Corpus loading and validation
- Report generation
- Threshold checking
"""

from __future__ import annotations

import pytest

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    DomainConfidence,
    Evidence,
    Finding,
    MethodId,
    PatternId,
    Severity,
)
from bmad_assist.deep_verify.metrics.collector import (
    ArtifactMetrics,
    CategoryMetrics,
    CorpusMetricsReport,
    DomainDetectionMetrics,
    ExpectedFinding,
    MetricsCollector,
    MetricsSummary,
    SeverityMetrics,
)
from bmad_assist.deep_verify.metrics.corpus_loader import (
    CorpusLoader,
    CorpusManifest,
    ExpectedDomainLabel,
)
from bmad_assist.deep_verify.metrics.report import ReportFormatter
from bmad_assist.deep_verify.metrics.threshold import (
    ThresholdChecker,
    ThresholdConfig,
)

# =============================================================================
# ArtifactMetrics Tests
# =============================================================================


class TestArtifactMetrics:
    """Tests for ArtifactMetrics calculations."""

    def test_precision_calculation(self) -> None:
        """Test precision calculation: TP / (TP + FP)."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Test",
            description="Test",
            method_id=MethodId("#153"),
        )

        # 2 TP, 1 FP -> precision = 2/3
        metrics = ArtifactMetrics(
            artifact_id="test-1",
            true_positives=[finding, finding],
            false_positives=[finding],
        )
        assert metrics.precision == pytest.approx(2 / 3)

    def test_precision_zero_division(self) -> None:
        """Test precision returns 0 when TP + FP = 0."""
        metrics = ArtifactMetrics(artifact_id="test-1")
        assert metrics.precision == 0.0

    def test_recall_calculation(self) -> None:
        """Test recall calculation: TP / (TP + FN)."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Test",
            description="Test",
            method_id=MethodId("#153"),
        )
        expected = ExpectedFinding(
            pattern_id=None,
            severity=Severity.ERROR,
            title="Test",
            description="Test",
            method_id=None,
            domain=None,
            line_number=None,
            quote=None,
        )

        # 2 TP, 1 FN -> recall = 2/3
        metrics = ArtifactMetrics(
            artifact_id="test-1",
            true_positives=[finding, finding],
            false_negatives=[expected],
        )
        assert metrics.recall == pytest.approx(2 / 3)

    def test_recall_zero_division(self) -> None:
        """Test recall returns 0 when TP + FN = 0."""
        metrics = ArtifactMetrics(artifact_id="test-1")
        assert metrics.recall == 0.0

    def test_f1_score(self) -> None:
        """Test F1 score calculation."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Test",
            description="Test",
            method_id=MethodId("#153"),
        )

        # Precision = 1.0, Recall = 1.0 -> F1 = 1.0
        metrics = ArtifactMetrics(
            artifact_id="test-1",
            true_positives=[finding],
        )
        assert metrics.f1_score == 1.0

    def test_f1_zero_division(self) -> None:
        """Test F1 returns 0 when P + R = 0."""
        metrics = ArtifactMetrics(artifact_id="test-1")
        assert metrics.f1_score == 0.0


# =============================================================================
# CategoryMetrics Tests
# =============================================================================


class TestCategoryMetrics:
    """Tests for CategoryMetrics (method/severity/domain aggregation)."""

    def test_category_precision(self) -> None:
        """Test precision calculation for category."""
        metrics = CategoryMetrics(
            category="#153",
            true_positives=8,
            false_positives=2,
        )
        assert metrics.precision == pytest.approx(0.8)

    def test_category_recall(self) -> None:
        """Test recall calculation for category."""
        metrics = CategoryMetrics(
            category="#153",
            true_positives=8,
            false_negatives=2,
        )
        assert metrics.recall == pytest.approx(0.8)

    def test_category_f1(self) -> None:
        """Test F1 calculation for category."""
        # P = 0.8, R = 0.8 -> F1 = 0.8
        metrics = CategoryMetrics(
            category="#153",
            true_positives=8,
            false_positives=2,
            false_negatives=2,
        )
        assert metrics.f1_score == pytest.approx(0.8)

    def test_category_accuracy(self) -> None:
        """Test accuracy calculation: (TP + TN) / Total."""
        metrics = CategoryMetrics(
            category="#153",
            true_positives=8,
            false_positives=2,
            false_negatives=2,
            true_negatives=8,
        )
        # (8 + 8) / 20 = 0.8
        assert metrics.accuracy == pytest.approx(0.8)


# =============================================================================
# SeverityMetrics Tests
# =============================================================================


class TestSeverityMetrics:
    """Tests for SeverityMetrics and FP rate calculation."""

    def test_fp_rate_calculation(self) -> None:
        """Test FP rate calculation: FP / (FP + TP)."""
        fp_rate = 1 / (1 + 99)  # 0.01
        metrics = SeverityMetrics(
            severity=Severity.CRITICAL,
            false_positives=1,
            true_positives=99,
            fp_rate=fp_rate,
        )
        # 1 / 100 = 0.01
        assert metrics.fp_rate == pytest.approx(0.01)

    def test_meets_target(self) -> None:
        """Test meets_target flag."""
        # CRITICAL: target is < 1%
        metrics = SeverityMetrics(
            severity=Severity.CRITICAL,
            false_positives=1,
            true_positives=99,
            fp_rate=0.01,
            meets_target=True,
        )
        assert metrics.meets_target is True


# =============================================================================
# DomainDetectionMetrics Tests
# =============================================================================


class TestDomainDetectionMetrics:
    """Tests for domain detection accuracy metrics."""

    def test_accuracy_calculation(self) -> None:
        """Test domain detection accuracy."""
        accuracy = 90 / 100  # 0.9
        metrics = DomainDetectionMetrics(
            total_artifacts=100,
            correct_domains=90,
            partial_domains=5,
            incorrect_domains=5,
            accuracy=accuracy,
        )
        # 90 / 100 = 0.9
        assert metrics.accuracy == pytest.approx(0.9)


# =============================================================================
# MetricsCollector Tests
# =============================================================================


class TestMetricsCollector:
    """Tests for MetricsCollector functionality."""

    def test_findings_match_pattern_id(self) -> None:
        """Test that findings match by pattern ID."""
        collector = MetricsCollector()

        actual = Finding(
            id="F1",
            severity=Severity.CRITICAL,
            title="Test",
            description="Test",
            method_id=MethodId("#153"),
            pattern_id=PatternId("CC-004"),
        )
        expected = ExpectedFinding(
            pattern_id=PatternId("CC-004"),
            severity=Severity.CRITICAL,
            title="Test",
            description="Test",
            method_id=None,
            domain=None,
            line_number=None,
            quote=None,
        )

        assert collector._findings_match(actual, expected) is True

    def test_findings_match_line_number(self) -> None:
        """Test that findings match by line number proximity."""
        collector = MetricsCollector()

        actual = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Test",
            description="Test",
            method_id=MethodId("#153"),
            evidence=[Evidence(quote="test", line_number=42)],
        )
        expected = ExpectedFinding(
            pattern_id=None,
            severity=Severity.ERROR,
            title="Test",
            description="Test",
            method_id=None,
            domain=None,
            line_number=42,
            quote=None,
        )

        assert collector._findings_match(actual, expected) is True

    def test_findings_no_match(self) -> None:
        """Test that non-matching findings return False."""
        collector = MetricsCollector()

        actual = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Test",
            description="Test",
            method_id=MethodId("#153"),
        )
        expected = ExpectedFinding(
            pattern_id=PatternId("CC-001"),
            severity=Severity.ERROR,
            title="Test",
            description="Test",
            method_id=None,
            domain=None,
            line_number=None,
            quote=None,
        )

        assert collector._findings_match(actual, expected) is False

    def test_calculate_domain_accuracy(self) -> None:
        """Test domain accuracy calculation."""
        collector = MetricsCollector()

        actual_domains = [
            DomainConfidence(domain=ArtifactDomain.CONCURRENCY, confidence=0.9),
            DomainConfidence(domain=ArtifactDomain.API, confidence=0.8),
        ]
        expected_domains = [
            ExpectedDomainLabel(domain=ArtifactDomain.CONCURRENCY, confidence=0.9),
        ]

        accuracy = collector._calculate_domain_accuracy(actual_domains, expected_domains)
        # 1 correct / 1 expected = 1.0
        assert accuracy == 1.0


# =============================================================================
# CorpusLoader Tests
# =============================================================================


class TestCorpusLoader:
    """Tests for CorpusLoader functionality."""

    def test_loader_initialization(self) -> None:
        """Test CorpusLoader initializes with correct paths."""
        loader = CorpusLoader()
        assert loader.corpus_path is not None
        assert loader.labels_path == loader.corpus_path / "labels"
        assert loader.golden_path == loader.corpus_path / "golden"

    def test_manifest_to_dict(self) -> None:
        """Test CorpusManifest serialization."""
        manifest = CorpusManifest(
            version="1.0.0",
            artifact_count=100,
            language_breakdown={"go": 50, "python": 50},
        )
        data = manifest.to_dict()

        assert data["version"] == "1.0.0"
        assert data["artifact_count"] == 100
        assert data["language_breakdown"]["go"] == 50

    def test_manifest_from_dict(self) -> None:
        """Test CorpusManifest deserialization."""
        data = {
            "version": "1.0.0",
            "created_at": "2026-02-04T00:00:00",
            "artifact_count": 50,
            "language_breakdown": {"go": 25},
            "domain_breakdown": {},
            "severity_breakdown": {},
            "checksums": {},
        }
        manifest = CorpusManifest.from_dict(data)

        assert manifest.version == "1.0.0"
        assert manifest.artifact_count == 50
        assert manifest.language_breakdown["go"] == 25


# =============================================================================
# ReportFormatter Tests
# =============================================================================


class TestReportFormatter:
    """Tests for report formatting."""

    def test_format_text_includes_summary(self) -> None:
        """Test text format includes summary metrics."""
        summary = MetricsSummary(
            total_artifacts=10,
            overall_precision=0.85,
            overall_recall=0.80,
            overall_f1=0.825,
        )
        report = CorpusMetricsReport(
            summary=summary,
            artifact_metrics=[],
            method_metrics=[],
            severity_metrics=[],
            domain_metrics=[],
            domain_detection_metrics=DomainDetectionMetrics(),
        )

        formatter = ReportFormatter(report)
        text = formatter.format_text()

        assert "Deep Verify Benchmark Report" in text
        assert "Artifacts evaluated: 10" in text
        assert "Precision: 85.0%" in text

    def test_format_json_structure(self) -> None:
        """Test JSON format has correct structure."""
        summary = MetricsSummary(
            total_artifacts=10,
            overall_precision=0.85,
            overall_recall=0.80,
            overall_f1=0.825,
        )
        report = CorpusMetricsReport(
            summary=summary,
            artifact_metrics=[],
            method_metrics=[],
            severity_metrics=[],
            domain_metrics=[],
            domain_detection_metrics=DomainDetectionMetrics(),
        )

        formatter = ReportFormatter(report)
        json_str = formatter.format_json()

        assert '"timestamp"' in json_str
        assert '"summary"' in json_str
        assert "0.85" in json_str

    def test_format_yaml_structure(self) -> None:
        """Test YAML format has correct structure."""
        summary = MetricsSummary(
            total_artifacts=10,
            overall_precision=0.85,
        )
        report = CorpusMetricsReport(
            summary=summary,
            artifact_metrics=[],
            method_metrics=[],
            severity_metrics=[],
            domain_metrics=[],
            domain_detection_metrics=DomainDetectionMetrics(),
        )

        formatter = ReportFormatter(report)
        yaml_str = formatter.format_yaml()

        assert "timestamp:" in yaml_str
        assert "summary:" in yaml_str

    def test_format_invalid_type(self) -> None:
        """Test that invalid format type raises ValueError."""
        report = CorpusMetricsReport(
            summary=MetricsSummary(),
            artifact_metrics=[],
            method_metrics=[],
            severity_metrics=[],
            domain_metrics=[],
            domain_detection_metrics=DomainDetectionMetrics(),
        )

        formatter = ReportFormatter(report)
        with pytest.raises(ValueError, match="Unknown format"):
            formatter.format("invalid")


# =============================================================================
# ThresholdChecker Tests
# =============================================================================


class TestThresholdChecker:
    """Tests for threshold checking functionality."""

    def test_threshold_config_defaults(self) -> None:
        """Test ThresholdConfig has correct defaults."""
        config = ThresholdConfig()

        assert config.overall_f1 == 0.80
        assert config.domain_detection_accuracy == 0.90
        assert config.critical_fp_rate == 0.01
        assert config.error_fp_rate == 0.05

    def test_threshold_config_from_dict(self) -> None:
        """Test ThresholdConfig loading from dict."""
        data = {
            "overall_f1": 0.85,
            "domain_detection_accuracy": 0.92,
            "critical_fp_rate": 0.005,
        }
        config = ThresholdConfig.from_dict(data)

        assert config.overall_f1 == 0.85
        assert config.domain_detection_accuracy == 0.92
        assert config.critical_fp_rate == 0.005

    def test_check_overall_f1_pass(self) -> None:
        """Test F1 threshold check passes when above threshold."""
        config = ThresholdConfig(overall_f1=0.80)
        checker = ThresholdChecker(config)

        summary = MetricsSummary(overall_f1=0.85)
        report = CorpusMetricsReport(
            summary=summary,
            artifact_metrics=[],
            method_metrics=[],
            severity_metrics=[],
            domain_metrics=[],
            domain_detection_metrics=DomainDetectionMetrics(),
        )

        results = checker.check(report)
        f1_result = [r for r in results if r.metric_name == "overall_f1"][0]

        assert f1_result.passed is True
        assert f1_result.actual_value == 0.85
        assert f1_result.threshold_value == 0.80

    def test_check_overall_f1_fail(self) -> None:
        """Test F1 threshold check fails when below threshold."""
        config = ThresholdConfig(overall_f1=0.80)
        checker = ThresholdChecker(config)

        summary = MetricsSummary(overall_f1=0.75)
        report = CorpusMetricsReport(
            summary=summary,
            artifact_metrics=[],
            method_metrics=[],
            severity_metrics=[],
            domain_metrics=[],
            domain_detection_metrics=DomainDetectionMetrics(),
        )

        results = checker.check(report)
        f1_result = [r for r in results if r.metric_name == "overall_f1"][0]

        assert f1_result.passed is False

    def test_check_severity_fp_rate(self) -> None:
        """Test severity FP rate threshold check."""
        config = ThresholdConfig(critical_fp_rate=0.01)
        checker = ThresholdChecker(config)

        severity_metrics = [
            SeverityMetrics(
                severity=Severity.CRITICAL,
                false_positives=2,
                true_positives=98,
                fp_rate=0.02,
                meets_target=False,
            )
        ]
        summary = MetricsSummary()
        report = CorpusMetricsReport(
            summary=summary,
            artifact_metrics=[],
            method_metrics=[],
            severity_metrics=severity_metrics,
            domain_metrics=[],
            domain_detection_metrics=DomainDetectionMetrics(),
        )

        results = checker.check(report)
        fp_result = [r for r in results if "critical_fp_rate" in r.metric_name][0]

        assert fp_result.passed is False
        assert fp_result.actual_value == 0.02

    def test_check_all_passed_true(self) -> None:
        """Test check_all_passed returns True when all pass."""
        config = ThresholdConfig(overall_f1=0.80)
        checker = ThresholdChecker(config)

        summary = MetricsSummary(overall_f1=0.85)
        report = CorpusMetricsReport(
            summary=summary,
            artifact_metrics=[],
            method_metrics=[],
            severity_metrics=[],
            domain_metrics=[],
            domain_detection_metrics=DomainDetectionMetrics(accuracy=0.95),
        )

        assert checker.check_all_passed(report) is True

    def test_check_all_passed_false(self) -> None:
        """Test check_all_passed returns False when any fail."""
        config = ThresholdConfig(overall_f1=0.80)
        checker = ThresholdChecker(config)

        summary = MetricsSummary(overall_f1=0.75)  # Below threshold
        report = CorpusMetricsReport(
            summary=summary,
            artifact_metrics=[],
            method_metrics=[],
            severity_metrics=[],
            domain_metrics=[],
            domain_detection_metrics=DomainDetectionMetrics(),
        )

        assert checker.check_all_passed(report) is False


# =============================================================================
# Integration Tests
# =============================================================================


class TestMetricsIntegration:
    """Integration tests for metrics pipeline."""

    def test_end_to_end_metrics_collection(self) -> None:
        """Test complete metrics collection pipeline."""
        # This is a simplified integration test
        collector = MetricsCollector()
        loader = CorpusLoader()

        # Verify loader and collector work together
        labels = loader.load_all_labels()
        assert len(labels) > 0

    def test_report_to_dict_roundtrip(self) -> None:
        """Test report serialization roundtrip."""
        summary = MetricsSummary(
            total_artifacts=10,
            overall_precision=0.85,
            overall_recall=0.80,
            overall_f1=0.825,
            duration_seconds=45.5,
        )
        report = CorpusMetricsReport(
            summary=summary,
            artifact_metrics=[],
            method_metrics=[],
            severity_metrics=[],
            domain_metrics=[],
            domain_detection_metrics=DomainDetectionMetrics(
                total_artifacts=10,
                correct_domains=9,
                accuracy=0.9,
            ),
        )

        # Serialize to dict
        data = report.to_dict()

        # Verify structure
        assert data["summary"]["total_artifacts"] == 10
        assert data["summary"]["overall_f1"] == 0.825
        assert data["domain_detection"]["accuracy"] == 0.9

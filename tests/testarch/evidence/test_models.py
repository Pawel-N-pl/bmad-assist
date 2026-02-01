"""Tests for evidence data models."""

from datetime import datetime, timezone

import pytest

from bmad_assist.testarch.evidence.models import (
    CoverageEvidence,
    EvidenceContext,
    PerformanceEvidence,
    SecurityEvidence,
    SourceConfig,
    TestResultsEvidence,
)


class TestSourceConfig:
    """Tests for SourceConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SourceConfig()
        assert config.enabled is True
        assert config.patterns == ()
        assert config.command is None
        assert config.timeout == 30

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = SourceConfig(
            enabled=False,
            patterns=("*.json", "*.xml"),
            command="npm audit --json",
            timeout=60,
        )
        assert config.enabled is False
        assert config.patterns == ("*.json", "*.xml")
        assert config.command == "npm audit --json"
        assert config.timeout == 60

    def test_frozen(self) -> None:
        """Test that SourceConfig is immutable."""
        config = SourceConfig()
        with pytest.raises(AttributeError):
            config.enabled = False  # type: ignore[misc]


class TestCoverageEvidence:
    """Tests for CoverageEvidence dataclass."""

    def test_valid_coverage(self) -> None:
        """Test valid coverage evidence creation."""
        evidence = CoverageEvidence(
            total_lines=1000,
            covered_lines=850,
            coverage_percent=85.0,
            uncovered_files=("src/legacy.py",),
            source="coverage/lcov.info",
        )
        assert evidence.total_lines == 1000
        assert evidence.covered_lines == 850
        assert evidence.coverage_percent == 85.0
        assert evidence.uncovered_files == ("src/legacy.py",)
        assert evidence.source == "coverage/lcov.info"

    def test_zero_coverage(self) -> None:
        """Test zero coverage is valid."""
        evidence = CoverageEvidence(
            total_lines=100,
            covered_lines=0,
            coverage_percent=0.0,
            uncovered_files=(),
            source="test.info",
        )
        assert evidence.coverage_percent == 0.0

    def test_full_coverage(self) -> None:
        """Test 100% coverage is valid."""
        evidence = CoverageEvidence(
            total_lines=100,
            covered_lines=100,
            coverage_percent=100.0,
            uncovered_files=(),
            source="test.info",
        )
        assert evidence.coverage_percent == 100.0

    def test_invalid_coverage_percent_negative(self) -> None:
        """Test negative coverage percent raises ValueError."""
        with pytest.raises(ValueError, match="coverage_percent must be 0-100"):
            CoverageEvidence(
                total_lines=100,
                covered_lines=80,
                coverage_percent=-5.0,
                uncovered_files=(),
                source="test.info",
            )

    def test_invalid_coverage_percent_over_100(self) -> None:
        """Test coverage percent over 100 raises ValueError."""
        with pytest.raises(ValueError, match="coverage_percent must be 0-100"):
            CoverageEvidence(
                total_lines=100,
                covered_lines=80,
                coverage_percent=105.0,
                uncovered_files=(),
                source="test.info",
            )

    def test_invalid_negative_total_lines(self) -> None:
        """Test negative total_lines raises ValueError."""
        with pytest.raises(ValueError, match="total_lines must be non-negative"):
            CoverageEvidence(
                total_lines=-1,
                covered_lines=0,
                coverage_percent=0.0,
                uncovered_files=(),
                source="test.info",
            )

    def test_invalid_negative_covered_lines(self) -> None:
        """Test negative covered_lines raises ValueError."""
        with pytest.raises(ValueError, match="covered_lines must be non-negative"):
            CoverageEvidence(
                total_lines=100,
                covered_lines=-1,
                coverage_percent=0.0,
                uncovered_files=(),
                source="test.info",
            )

    def test_empty_source_raises_error(self) -> None:
        """Test empty source raises ValueError."""
        with pytest.raises(ValueError, match="source cannot be empty"):
            CoverageEvidence(
                total_lines=100,
                covered_lines=80,
                coverage_percent=80.0,
                uncovered_files=(),
                source="",
            )

    def test_to_dict(self) -> None:
        """Test to_dict serialization."""
        evidence = CoverageEvidence(
            total_lines=1000,
            covered_lines=850,
            coverage_percent=85.0,
            uncovered_files=("src/a.py", "src/b.py"),
            source="lcov.info",
        )
        result = evidence.to_dict()
        assert result["total_lines"] == 1000
        assert result["covered_lines"] == 850
        assert result["coverage_percent"] == 85.0
        assert result["uncovered_files"] == ["src/a.py", "src/b.py"]
        assert result["source"] == "lcov.info"

    def test_frozen(self) -> None:
        """Test that CoverageEvidence is immutable."""
        evidence = CoverageEvidence(
            total_lines=100,
            covered_lines=80,
            coverage_percent=80.0,
            uncovered_files=(),
            source="test.info",
        )
        with pytest.raises(AttributeError):
            evidence.total_lines = 200  # type: ignore[misc]


class TestTestResultsEvidence:
    """Tests for TestResultsEvidence dataclass."""

    def test_valid_test_results(self) -> None:
        """Test valid test results creation."""
        evidence = TestResultsEvidence(
            total=100,
            passed=95,
            failed=3,
            errors=1,
            skipped=1,
            duration_ms=45000,
            failed_tests=("test_a", "test_b", "test_c"),
            source="junit.xml",
        )
        assert evidence.total == 100
        assert evidence.passed == 95
        assert evidence.failed == 3
        assert evidence.errors == 1
        assert evidence.skipped == 1
        assert evidence.duration_ms == 45000
        assert len(evidence.failed_tests) == 3
        assert evidence.source == "junit.xml"

    def test_all_passed(self) -> None:
        """Test all tests passed scenario."""
        evidence = TestResultsEvidence(
            total=50,
            passed=50,
            failed=0,
            errors=0,
            skipped=0,
            duration_ms=10000,
            failed_tests=(),
            source="results.json",
        )
        assert evidence.passed == 50
        assert evidence.failed == 0

    def test_invalid_negative_total(self) -> None:
        """Test negative total raises ValueError."""
        with pytest.raises(ValueError, match="total must be non-negative"):
            TestResultsEvidence(
                total=-1,
                passed=0,
                failed=0,
                errors=0,
                skipped=0,
                duration_ms=0,
                failed_tests=(),
                source="test.xml",
            )

    def test_invalid_negative_passed(self) -> None:
        """Test negative passed raises ValueError."""
        with pytest.raises(ValueError, match="passed must be non-negative"):
            TestResultsEvidence(
                total=10,
                passed=-1,
                failed=0,
                errors=0,
                skipped=0,
                duration_ms=0,
                failed_tests=(),
                source="test.xml",
            )

    def test_invalid_negative_duration(self) -> None:
        """Test negative duration raises ValueError."""
        with pytest.raises(ValueError, match="duration_ms must be non-negative"):
            TestResultsEvidence(
                total=10,
                passed=10,
                failed=0,
                errors=0,
                skipped=0,
                duration_ms=-1000,
                failed_tests=(),
                source="test.xml",
            )

    def test_empty_source_raises_error(self) -> None:
        """Test empty source raises ValueError."""
        with pytest.raises(ValueError, match="source cannot be empty"):
            TestResultsEvidence(
                total=10,
                passed=10,
                failed=0,
                errors=0,
                skipped=0,
                duration_ms=0,
                failed_tests=(),
                source="",
            )

    def test_to_dict(self) -> None:
        """Test to_dict serialization."""
        evidence = TestResultsEvidence(
            total=10,
            passed=8,
            failed=1,
            errors=1,
            skipped=0,
            duration_ms=5000,
            failed_tests=("test_fail",),
            source="junit.xml",
        )
        result = evidence.to_dict()
        assert result["total"] == 10
        assert result["passed"] == 8
        assert result["failed"] == 1
        assert result["errors"] == 1
        assert result["skipped"] == 0
        assert result["duration_ms"] == 5000
        assert result["failed_tests"] == ["test_fail"]


class TestSecurityEvidence:
    """Tests for SecurityEvidence dataclass."""

    def test_valid_security_evidence(self) -> None:
        """Test valid security evidence creation."""
        evidence = SecurityEvidence(
            critical=1,
            high=2,
            moderate=3,
            low=4,
            info=0,
            total=10,
            fix_available=8,
            vulnerabilities=("[HIGH] lodash: Prototype Pollution",),
            source="npm audit --json",
        )
        assert evidence.critical == 1
        assert evidence.high == 2
        assert evidence.moderate == 3
        assert evidence.low == 4
        assert evidence.total == 10
        assert evidence.fix_available == 8

    def test_no_vulnerabilities(self) -> None:
        """Test no vulnerabilities scenario."""
        evidence = SecurityEvidence(
            critical=0,
            high=0,
            moderate=0,
            low=0,
            info=0,
            total=0,
            fix_available=0,
            vulnerabilities=(),
            source="npm-audit.json",
        )
        assert evidence.total == 0

    def test_invalid_negative_critical(self) -> None:
        """Test negative critical raises ValueError."""
        with pytest.raises(ValueError, match="critical must be non-negative"):
            SecurityEvidence(
                critical=-1,
                high=0,
                moderate=0,
                low=0,
                info=0,
                total=0,
                fix_available=0,
                vulnerabilities=(),
                source="test.json",
            )

    def test_empty_source_raises_error(self) -> None:
        """Test empty source raises ValueError."""
        with pytest.raises(ValueError, match="source cannot be empty"):
            SecurityEvidence(
                critical=0,
                high=0,
                moderate=0,
                low=0,
                info=0,
                total=0,
                fix_available=0,
                vulnerabilities=(),
                source="",
            )

    def test_to_dict(self) -> None:
        """Test to_dict serialization."""
        evidence = SecurityEvidence(
            critical=1,
            high=2,
            moderate=3,
            low=4,
            info=0,
            total=10,
            fix_available=8,
            vulnerabilities=("vuln1", "vuln2"),
            source="npm-audit.json",
        )
        result = evidence.to_dict()
        assert result["critical"] == 1
        assert result["high"] == 2
        assert result["total"] == 10
        assert result["vulnerabilities"] == ["vuln1", "vuln2"]


class TestPerformanceEvidence:
    """Tests for PerformanceEvidence dataclass."""

    def test_lighthouse_evidence(self) -> None:
        """Test Lighthouse performance evidence."""
        evidence = PerformanceEvidence(
            lighthouse_scores={"performance": 0.89, "accessibility": 0.95},
            k6_metrics=None,
            source="lighthouse-report.json",
        )
        assert evidence.lighthouse_scores is not None
        assert evidence.lighthouse_scores["performance"] == 0.89
        assert evidence.k6_metrics is None

    def test_k6_evidence(self) -> None:
        """Test k6 performance evidence."""
        evidence = PerformanceEvidence(
            lighthouse_scores=None,
            k6_metrics={
                "requests_per_sec": 100,
                "response_time_p95_ms": 250,
            },
            source="k6-summary.json",
        )
        assert evidence.lighthouse_scores is None
        assert evidence.k6_metrics is not None
        assert evidence.k6_metrics["requests_per_sec"] == 100

    def test_empty_source_raises_error(self) -> None:
        """Test empty source raises ValueError."""
        with pytest.raises(ValueError, match="source cannot be empty"):
            PerformanceEvidence(
                lighthouse_scores=None,
                k6_metrics=None,
                source="",
            )

    def test_to_dict(self) -> None:
        """Test to_dict serialization."""
        evidence = PerformanceEvidence(
            lighthouse_scores={"performance": 0.85},
            k6_metrics={"rps": 100},
            source="test.json",
        )
        result = evidence.to_dict()
        assert result["lighthouse_scores"] == {"performance": 0.85}
        assert result["k6_metrics"] == {"rps": 100}
        assert result["source"] == "test.json"


class TestEvidenceContext:
    """Tests for EvidenceContext dataclass."""

    def test_full_context(self) -> None:
        """Test full context with all evidence types."""
        collected_at = datetime.now(timezone.utc).isoformat()
        context = EvidenceContext(
            coverage=CoverageEvidence(
                total_lines=100,
                covered_lines=80,
                coverage_percent=80.0,
                uncovered_files=(),
                source="lcov.info",
            ),
            test_results=TestResultsEvidence(
                total=50,
                passed=48,
                failed=2,
                errors=0,
                skipped=0,
                duration_ms=10000,
                failed_tests=(),
                source="junit.xml",
            ),
            security=SecurityEvidence(
                critical=0,
                high=1,
                moderate=2,
                low=0,
                info=0,
                total=3,
                fix_available=2,
                vulnerabilities=(),
                source="npm-audit.json",
            ),
            performance=PerformanceEvidence(
                lighthouse_scores={"performance": 0.9},
                k6_metrics=None,
                source="lighthouse.json",
            ),
            collected_at=collected_at,
        )
        assert context.coverage is not None
        assert context.test_results is not None
        assert context.security is not None
        assert context.performance is not None

    def test_partial_context(self) -> None:
        """Test partial context with some None evidence."""
        collected_at = datetime.now(timezone.utc).isoformat()
        context = EvidenceContext(
            coverage=CoverageEvidence(
                total_lines=100,
                covered_lines=80,
                coverage_percent=80.0,
                uncovered_files=(),
                source="lcov.info",
            ),
            test_results=None,
            security=None,
            performance=None,
            collected_at=collected_at,
        )
        assert context.coverage is not None
        assert context.test_results is None
        assert context.security is None
        assert context.performance is None

    def test_empty_context(self) -> None:
        """Test context with all None evidence."""
        collected_at = datetime.now(timezone.utc).isoformat()
        context = EvidenceContext(
            coverage=None,
            test_results=None,
            security=None,
            performance=None,
            collected_at=collected_at,
        )
        assert context.coverage is None

    def test_empty_collected_at_raises_error(self) -> None:
        """Test empty collected_at raises ValueError."""
        with pytest.raises(ValueError, match="collected_at cannot be empty"):
            EvidenceContext(
                coverage=None,
                test_results=None,
                security=None,
                performance=None,
                collected_at="",
            )

    def test_invalid_collected_at_raises_error(self) -> None:
        """Test invalid collected_at format raises ValueError."""
        with pytest.raises(ValueError, match="collected_at must be valid ISO 8601"):
            EvidenceContext(
                coverage=None,
                test_results=None,
                security=None,
                performance=None,
                collected_at="not-a-datetime",
            )

    def test_to_dict(self) -> None:
        """Test to_dict serialization."""
        collected_at = datetime.now(timezone.utc).isoformat()
        context = EvidenceContext(
            coverage=CoverageEvidence(
                total_lines=100,
                covered_lines=80,
                coverage_percent=80.0,
                uncovered_files=(),
                source="lcov.info",
            ),
            test_results=None,
            security=None,
            performance=None,
            collected_at=collected_at,
        )
        result = context.to_dict()
        assert result["coverage"] is not None
        assert result["coverage"]["total_lines"] == 100
        assert result["test_results"] is None
        assert result["security"] is None
        assert result["performance"] is None
        assert result["collected_at"] == collected_at

    def test_to_markdown_full(self) -> None:
        """Test to_markdown with all evidence."""
        collected_at = "2026-01-31T10:30:00+00:00"
        context = EvidenceContext(
            coverage=CoverageEvidence(
                total_lines=1000,
                covered_lines=850,
                coverage_percent=85.0,
                uncovered_files=("src/legacy.py", "src/old.py"),
                source="lcov.info",
            ),
            test_results=TestResultsEvidence(
                total=100,
                passed=95,
                failed=3,
                errors=1,
                skipped=1,
                duration_ms=45000,
                failed_tests=("test_a", "test_b"),
                source="junit.xml",
            ),
            security=SecurityEvidence(
                critical=0,
                high=2,
                moderate=3,
                low=1,
                info=0,
                total=6,
                fix_available=5,
                vulnerabilities=("[HIGH] lodash: Pollution", "[HIGH] axios: SSRF"),
                source="npm-audit.json",
            ),
            performance=PerformanceEvidence(
                lighthouse_scores={"performance": 0.89, "accessibility": 0.95},
                k6_metrics=None,
                source="lighthouse.json",
            ),
            collected_at=collected_at,
        )
        md = context.to_markdown()

        # Check sections exist
        assert "## Evidence Context" in md
        assert "### Coverage Evidence" in md
        assert "### Test Results" in md
        assert "### Security Evidence" in md
        assert "### Performance Evidence" in md

        # Check data is present
        assert "850" in md
        assert "1,000" in md
        assert "85.0%" in md
        assert "src/legacy.py" in md
        assert "test_a" in md
        assert "[HIGH] lodash: Pollution" in md
        assert "89%" in md  # Lighthouse performance

    def test_to_markdown_partial(self) -> None:
        """Test to_markdown with missing evidence."""
        collected_at = "2026-01-31T10:30:00+00:00"
        context = EvidenceContext(
            coverage=None,
            test_results=None,
            security=None,
            performance=None,
            collected_at=collected_at,
        )
        md = context.to_markdown()

        # Check all sections show "Evidence not available"
        assert md.count("Evidence not available") == 4

    def test_to_markdown_truncates_long_lists(self) -> None:
        """Test to_markdown truncates long file/test lists."""
        collected_at = "2026-01-31T10:30:00+00:00"

        # Create 25 uncovered files (max is 20)
        uncovered_files = tuple(f"src/file{i}.py" for i in range(25))
        failed_tests = tuple(f"test_{i}" for i in range(25))
        vulnerabilities = tuple(f"[HIGH] vuln{i}" for i in range(15))

        context = EvidenceContext(
            coverage=CoverageEvidence(
                total_lines=1000,
                covered_lines=800,
                coverage_percent=80.0,
                uncovered_files=uncovered_files,
                source="lcov.info",
            ),
            test_results=TestResultsEvidence(
                total=100,
                passed=75,
                failed=25,
                errors=0,
                skipped=0,
                duration_ms=10000,
                failed_tests=failed_tests,
                source="junit.xml",
            ),
            security=SecurityEvidence(
                critical=0,
                high=15,
                moderate=0,
                low=0,
                info=0,
                total=15,
                fix_available=10,
                vulnerabilities=vulnerabilities,
                source="npm-audit.json",
            ),
            performance=None,
            collected_at=collected_at,
        )
        md = context.to_markdown()

        # Check truncation messages
        assert "showing 20 of 25" in md
        assert "... and 5 more" in md
        assert "showing 10 of 15" in md  # Vulnerabilities max is 10

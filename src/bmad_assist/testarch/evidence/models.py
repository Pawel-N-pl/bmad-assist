"""Data models for Evidence Context System.

This module provides immutable data classes for evidence types collected
from test artifacts, coverage data, security scans, and performance metrics.

Usage:
    from bmad_assist.testarch.evidence.models import CoverageEvidence, EvidenceContext

    coverage = CoverageEvidence(
        total_lines=1000,
        covered_lines=850,
        coverage_percent=85.0,
        uncovered_files=("src/legacy.py",),
        source="coverage/lcov.info",
    )
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SourceConfig:
    """Configuration for an evidence source.

    Attributes:
        enabled: Whether this source is enabled.
        patterns: Glob patterns to search for evidence files.
        command: Optional command to run for evidence collection.
        timeout: Command execution timeout in seconds.

    """

    enabled: bool = True
    patterns: tuple[str, ...] = ()
    command: str | None = None
    timeout: int = 30


@dataclass(frozen=True)
class CoverageEvidence:
    """Immutable coverage evidence data.

    Attributes:
        total_lines: Total lines in codebase.
        covered_lines: Number of lines covered by tests.
        coverage_percent: Coverage percentage (0-100).
        uncovered_files: Tuple of file paths with zero coverage.
        source: Source file path or "command".

    """

    total_lines: int
    covered_lines: int
    coverage_percent: float
    uncovered_files: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        """Validate coverage data."""
        if self.coverage_percent < 0 or self.coverage_percent > 100:
            raise ValueError(
                f"coverage_percent must be 0-100, got {self.coverage_percent}"
            )
        if self.total_lines < 0:
            raise ValueError(f"total_lines must be non-negative, got {self.total_lines}")
        if self.covered_lines < 0:
            raise ValueError(f"covered_lines must be non-negative, got {self.covered_lines}")
        if not self.source:
            raise ValueError("source cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for YAML/JSON serialization.

        """
        return {
            "total_lines": self.total_lines,
            "covered_lines": self.covered_lines,
            "coverage_percent": self.coverage_percent,
            "uncovered_files": list(self.uncovered_files),
            "source": self.source,
        }


@dataclass(frozen=True)
class TestResultsEvidence:
    """Immutable test results evidence data.

    Attributes:
        total: Total number of tests.
        passed: Number of passed tests.
        failed: Number of failed tests.
        errors: Number of tests with errors.
        skipped: Number of skipped tests.
        duration_ms: Test execution duration in milliseconds.
        failed_tests: Tuple of failed test names.
        source: Source file path.

    """

    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_ms: int
    failed_tests: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        """Validate test results data."""
        if self.total < 0:
            raise ValueError(f"total must be non-negative, got {self.total}")
        if self.passed < 0:
            raise ValueError(f"passed must be non-negative, got {self.passed}")
        if self.failed < 0:
            raise ValueError(f"failed must be non-negative, got {self.failed}")
        if self.errors < 0:
            raise ValueError(f"errors must be non-negative, got {self.errors}")
        if self.skipped < 0:
            raise ValueError(f"skipped must be non-negative, got {self.skipped}")
        if self.duration_ms < 0:
            raise ValueError(f"duration_ms must be non-negative, got {self.duration_ms}")
        if not self.source:
            raise ValueError("source cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for YAML/JSON serialization.

        """
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "duration_ms": self.duration_ms,
            "failed_tests": list(self.failed_tests),
            "source": self.source,
        }


@dataclass(frozen=True)
class SecurityEvidence:
    """Immutable security scan evidence data.

    Attributes:
        critical: Number of critical vulnerabilities.
        high: Number of high severity vulnerabilities.
        moderate: Number of moderate severity vulnerabilities.
        low: Number of low severity vulnerabilities.
        info: Number of informational findings.
        total: Total number of vulnerabilities.
        fix_available: Number of vulnerabilities with available fixes.
        vulnerabilities: Tuple of vulnerability descriptions.
        source: Source file path or "command".

    """

    critical: int
    high: int
    moderate: int
    low: int
    info: int
    total: int
    fix_available: int
    vulnerabilities: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        """Validate security data."""
        if self.critical < 0:
            raise ValueError(f"critical must be non-negative, got {self.critical}")
        if self.high < 0:
            raise ValueError(f"high must be non-negative, got {self.high}")
        if self.moderate < 0:
            raise ValueError(f"moderate must be non-negative, got {self.moderate}")
        if self.low < 0:
            raise ValueError(f"low must be non-negative, got {self.low}")
        if self.info < 0:
            raise ValueError(f"info must be non-negative, got {self.info}")
        if self.total < 0:
            raise ValueError(f"total must be non-negative, got {self.total}")
        if self.fix_available < 0:
            raise ValueError(f"fix_available must be non-negative, got {self.fix_available}")
        if not self.source:
            raise ValueError("source cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for YAML/JSON serialization.

        """
        return {
            "critical": self.critical,
            "high": self.high,
            "moderate": self.moderate,
            "low": self.low,
            "info": self.info,
            "total": self.total,
            "fix_available": self.fix_available,
            "vulnerabilities": list(self.vulnerabilities),
            "source": self.source,
        }


@dataclass(frozen=True)
class PerformanceEvidence:
    """Immutable performance metrics evidence data.

    Attributes:
        lighthouse_scores: Lighthouse performance scores by category, or None.
        k6_metrics: k6 load test metrics, or None.
        source: Source file path.

    """

    lighthouse_scores: dict[str, float] | None
    k6_metrics: dict[str, Any] | None
    source: str

    def __post_init__(self) -> None:
        """Validate performance data."""
        if not self.source:
            raise ValueError("source cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for YAML/JSON serialization.

        """
        return {
            "lighthouse_scores": self.lighthouse_scores,
            "k6_metrics": self.k6_metrics,
            "source": self.source,
        }


@dataclass(frozen=True)
class EvidenceContext:
    """Immutable container for all collected evidence.

    Attributes:
        coverage: Coverage evidence, or None if not available.
        test_results: Test results evidence, or None if not available.
        security: Security scan evidence, or None if not available.
        performance: Performance metrics evidence, or None if not available.
        collected_at: ISO 8601 datetime when evidence was collected.

    """

    coverage: CoverageEvidence | None
    test_results: TestResultsEvidence | None
    security: SecurityEvidence | None
    performance: PerformanceEvidence | None
    collected_at: str

    def __post_init__(self) -> None:
        """Validate evidence context."""
        if not self.collected_at:
            raise ValueError("collected_at cannot be empty")
        # Validate ISO 8601 format
        try:
            datetime.fromisoformat(self.collected_at)
        except ValueError as e:
            raise ValueError(f"collected_at must be valid ISO 8601 datetime: {e}") from e

    def to_dict(self) -> dict[str, Any]:
        """Convert all evidence to dicts for serialization.

        Returns:
            Dictionary representation suitable for YAML/JSON serialization.

        """
        return {
            "coverage": self.coverage.to_dict() if self.coverage else None,
            "test_results": self.test_results.to_dict() if self.test_results else None,
            "security": self.security.to_dict() if self.security else None,
            "performance": self.performance.to_dict() if self.performance else None,
            "collected_at": self.collected_at,
        }

    def to_markdown(self) -> str:
        """Format evidence for LLM consumption.

        Returns:
            Markdown formatted evidence report with all sections.

        """
        lines = ["## Evidence Context", "", f"Collected at: {self.collected_at}", ""]

        # Coverage section
        lines.append("### Coverage Evidence")
        lines.append("")
        if self.coverage:
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(
                f"| Lines Covered | {self.coverage.covered_lines:,} / "
                f"{self.coverage.total_lines:,} |"
            )
            lines.append(f"| Coverage | {self.coverage.coverage_percent:.1f}% |")
            lines.append(f"| Source | {self.coverage.source} |")
            lines.append("")

            if self.coverage.uncovered_files:
                max_files = 20
                file_count = len(self.coverage.uncovered_files)
                if file_count > max_files:
                    lines.append(f"**Uncovered Files (showing {max_files} of {file_count}):**")
                else:
                    lines.append("**Uncovered Files:**")
                for f in self.coverage.uncovered_files[:max_files]:
                    lines.append(f"- {f}")
                if file_count > max_files:
                    lines.append(f"- ... and {file_count - max_files} more")
        else:
            lines.append("Evidence not available")
        lines.append("")

        # Test Results section
        lines.append("### Test Results")
        lines.append("")
        if self.test_results:
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| Total Tests | {self.test_results.total:,} |")
            lines.append(f"| Passed | {self.test_results.passed:,} |")
            lines.append(f"| Failed | {self.test_results.failed:,} |")
            lines.append(f"| Errors | {self.test_results.errors:,} |")
            lines.append(f"| Skipped | {self.test_results.skipped:,} |")
            lines.append(f"| Duration | {self.test_results.duration_ms / 1000:.1f}s |")
            lines.append(f"| Source | {self.test_results.source} |")
            lines.append("")

            if self.test_results.failed_tests:
                max_tests = 20
                test_count = len(self.test_results.failed_tests)
                if test_count > max_tests:
                    lines.append(f"**Failed Tests (showing {max_tests} of {test_count}):**")
                else:
                    lines.append("**Failed Tests:**")
                for t in self.test_results.failed_tests[:max_tests]:
                    lines.append(f"- {t}")
                if test_count > max_tests:
                    lines.append(f"- ... and {test_count - max_tests} more")
        else:
            lines.append("Evidence not available")
        lines.append("")

        # Security section
        lines.append("### Security Evidence")
        lines.append("")
        if self.security:
            lines.append("| Severity | Count |")
            lines.append("|----------|-------|")
            lines.append(f"| Critical | {self.security.critical} |")
            lines.append(f"| High | {self.security.high} |")
            lines.append(f"| Moderate | {self.security.moderate} |")
            lines.append(f"| Low | {self.security.low} |")
            lines.append(f"| Source | {self.security.source} |")
            lines.append("")

            if self.security.vulnerabilities:
                max_vulns = 10
                vuln_count = len(self.security.vulnerabilities)
                if vuln_count > max_vulns:
                    lines.append(
                        f"**Top Vulnerabilities (showing {max_vulns} of {vuln_count}):**"
                    )
                else:
                    lines.append("**Top Vulnerabilities:**")
                for i, v in enumerate(self.security.vulnerabilities[:max_vulns], 1):
                    lines.append(f"{i}. {v}")
                if vuln_count > max_vulns:
                    lines.append(f"- ... and {vuln_count - max_vulns} more")
        else:
            lines.append("Evidence not available")
        lines.append("")

        # Performance section
        lines.append("### Performance Evidence")
        lines.append("")
        if self.performance:
            if self.performance.lighthouse_scores:
                lines.append("**Lighthouse Scores:**")
                lines.append("")
                lines.append("| Category | Score |")
                lines.append("|----------|-------|")
                for cat, score in self.performance.lighthouse_scores.items():
                    lines.append(f"| {cat.title()} | {score:.0%} |")
                lines.append("")

            if self.performance.k6_metrics:
                lines.append("**k6 Metrics:**")
                lines.append("")
                for key, value in self.performance.k6_metrics.items():
                    lines.append(f"- {key}: {value}")
                lines.append("")

            lines.append(f"Source: {self.performance.source}")
        else:
            lines.append("Evidence not available")

        return "\n".join(lines)

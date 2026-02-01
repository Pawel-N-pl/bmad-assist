"""Tests for PerformanceSource."""

from pathlib import Path

import pytest

from bmad_assist.testarch.evidence.models import SourceConfig
from bmad_assist.testarch.evidence.sources.performance import (
    DEFAULT_PERFORMANCE_PATTERNS,
    PerformanceSource,
)


class TestPerformanceSourceProperties:
    """Tests for PerformanceSource properties."""

    def test_source_type(self) -> None:
        """Test source_type property."""
        source = PerformanceSource()
        assert source.source_type == "performance"

    def test_default_patterns(self) -> None:
        """Test default_patterns property."""
        source = PerformanceSource()
        assert source.default_patterns == DEFAULT_PERFORMANCE_PATTERNS
        assert "**/lighthouse-report.json" in source.default_patterns
        assert "**/k6-summary.json" in source.default_patterns


class TestLighthouseParsing:
    """Tests for Lighthouse JSON format parsing."""

    def test_parse_lighthouse_json(self, tmp_path: Path) -> None:
        """Test parsing a valid Lighthouse report."""
        lighthouse_content = """{
  "lighthouseVersion": "10.0.0",
  "categories": {
    "performance": {"id": "performance", "score": 0.89},
    "accessibility": {"id": "accessibility", "score": 0.95},
    "best-practices": {"id": "best-practices", "score": 0.92},
    "seo": {"id": "seo", "score": 0.98}
  }
}"""
        lighthouse_file = tmp_path / "lighthouse-report.json"
        lighthouse_file.write_text(lighthouse_content)

        source = PerformanceSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.lighthouse_scores is not None
        assert evidence.lighthouse_scores["performance"] == 0.89
        assert evidence.lighthouse_scores["accessibility"] == 0.95
        assert evidence.lighthouse_scores["best-practices"] == 0.92
        assert evidence.lighthouse_scores["seo"] == 0.98
        assert evidence.k6_metrics is None

    def test_parse_lighthouse_empty_categories(self, tmp_path: Path) -> None:
        """Test parsing Lighthouse with empty categories."""
        lighthouse_content = """{
  "lighthouseVersion": "10.0.0",
  "categories": {}
}"""
        lighthouse_file = tmp_path / "lighthouse-report.json"
        lighthouse_file.write_text(lighthouse_content)

        source = PerformanceSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.lighthouse_scores is None
        assert evidence.k6_metrics is None


class TestK6Parsing:
    """Tests for k6 JSON format parsing."""

    def test_parse_k6_json(self, tmp_path: Path) -> None:
        """Test parsing a valid k6 summary."""
        k6_content = """{
  "metrics": {
    "http_reqs": {
      "values": {"count": 1000, "rate": 50.5}
    },
    "http_req_duration": {
      "values": {"avg": 123.45, "p(95)": 234.56}
    },
    "http_req_failed": {
      "values": {"rate": 0.01}
    },
    "iterations": {
      "values": {"count": 500, "rate": 25.0}
    }
  }
}"""
        k6_file = tmp_path / "k6-summary.json"
        k6_file.write_text(k6_content)

        source = PerformanceSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.k6_metrics is not None
        assert evidence.k6_metrics["requests_count"] == 1000
        assert evidence.k6_metrics["requests_per_sec"] == 50.5
        assert evidence.k6_metrics["response_time_avg_ms"] == 123.45
        assert evidence.k6_metrics["response_time_p95_ms"] == 234.56
        assert evidence.k6_metrics["error_rate"] == 0.01
        assert evidence.k6_metrics["iterations_count"] == 500
        assert evidence.lighthouse_scores is None

    def test_parse_k6_empty_metrics(self, tmp_path: Path) -> None:
        """Test parsing k6 with empty metrics."""
        k6_content = """{
  "metrics": {}
}"""
        k6_file = tmp_path / "k6-summary.json"
        k6_file.write_text(k6_content)

        source = PerformanceSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.lighthouse_scores is None
        assert evidence.k6_metrics is None


class TestFileDiscovery:
    """Tests for evidence file discovery."""

    def test_no_files_returns_none(self, tmp_path: Path) -> None:
        """Test when no performance files exist."""
        source = PerformanceSource()
        evidence = source.collect(tmp_path)
        assert evidence is None

    def test_prefers_most_recent_file(self, tmp_path: Path) -> None:
        """Test that most recently modified file is used."""
        import time

        # Create older lighthouse file
        old_file = tmp_path / "lighthouse-report.json"
        old_file.write_text("""{
  "categories": {"performance": {"score": 0.5}}
}""")

        time.sleep(0.1)

        # Create newer k6 file
        new_file = tmp_path / "k6-summary.json"
        new_file.write_text("""{
  "metrics": {
    "http_reqs": {"values": {"count": 9999, "rate": 100}}
  }
}""")

        source = PerformanceSource()
        evidence = source.collect(tmp_path)

        # Should use the newer file (k6)
        assert evidence is not None
        assert evidence.k6_metrics is not None
        assert evidence.k6_metrics["requests_count"] == 9999
        assert evidence.lighthouse_scores is None

    def test_custom_patterns(self, tmp_path: Path) -> None:
        """Test using custom patterns from config."""
        custom_file = tmp_path / "my-perf.json"
        custom_file.write_text("""{
  "categories": {"performance": {"score": 0.99}}
}""")

        config = SourceConfig(patterns=("my-perf.json",))
        source = PerformanceSource()
        evidence = source.collect(tmp_path, config)

        assert evidence is not None
        assert evidence.lighthouse_scores is not None
        assert evidence.lighthouse_scores["performance"] == 0.99

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        """Test that invalid JSON returns None."""
        invalid_file = tmp_path / "lighthouse-report.json"
        invalid_file.write_text("not valid json {{{")

        source = PerformanceSource()
        evidence = source.collect(tmp_path)

        assert evidence is None

    def test_unknown_format_returns_none(self, tmp_path: Path) -> None:
        """Test that unknown JSON format returns None."""
        unknown_file = tmp_path / "lighthouse-report.json"
        unknown_file.write_text('{"unknown": "format"}')

        source = PerformanceSource()
        evidence = source.collect(tmp_path)

        assert evidence is None


class TestFromFixtures:
    """Tests using fixture files."""

    def test_parse_sample_lighthouse(self, evidence_fixtures_dir: Path) -> None:
        """Test parsing sample-lighthouse.json fixture."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shutil.copy(
                evidence_fixtures_dir / "sample-lighthouse.json",
                tmp_path / "lighthouse-report.json",
            )

            source = PerformanceSource()
            evidence = source.collect(tmp_path)

            assert evidence is not None
            assert evidence.lighthouse_scores is not None
            assert evidence.lighthouse_scores["performance"] == 0.89
            assert evidence.lighthouse_scores["accessibility"] == 0.95
            assert evidence.lighthouse_scores["best-practices"] == 0.92
            assert evidence.lighthouse_scores["seo"] == 0.98

    def test_parse_sample_k6(self, evidence_fixtures_dir: Path) -> None:
        """Test parsing sample-k6-summary.json fixture."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shutil.copy(
                evidence_fixtures_dir / "sample-k6-summary.json",
                tmp_path / "k6-summary.json",
            )

            source = PerformanceSource()
            evidence = source.collect(tmp_path)

            assert evidence is not None
            assert evidence.k6_metrics is not None
            assert evidence.k6_metrics["requests_count"] == 15000
            assert evidence.k6_metrics["requests_per_sec"] == 125.5
            assert evidence.k6_metrics["response_time_avg_ms"] == 234.56
            assert evidence.k6_metrics["response_time_p95_ms"] == 567.89
            assert evidence.k6_metrics["error_rate"] == 0.0025

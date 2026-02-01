"""Tests for EvidenceContextCollector."""

import shutil
from pathlib import Path

import pytest

from bmad_assist.testarch.evidence import (
    EvidenceContextCollector,
    clear_all_collectors,
    get_evidence_collector,
)


@pytest.fixture(autouse=True)
def cleanup_collectors() -> None:
    """Clear singleton collectors before each test."""
    clear_all_collectors()


class TestGetEvidenceCollector:
    """Tests for get_evidence_collector factory function."""

    def test_returns_collector(self, tmp_path: Path) -> None:
        """Test that factory returns a collector."""
        collector = get_evidence_collector(tmp_path)
        assert isinstance(collector, EvidenceContextCollector)
        assert collector.project_root == tmp_path.resolve()

    def test_singleton_per_project(self, tmp_path: Path) -> None:
        """Test singleton pattern - same project returns same instance."""
        collector1 = get_evidence_collector(tmp_path)
        collector2 = get_evidence_collector(tmp_path)
        assert collector1 is collector2

    def test_different_projects_different_instances(self, tmp_path: Path) -> None:
        """Test different projects get different instances."""
        project1 = tmp_path / "project1"
        project2 = tmp_path / "project2"
        project1.mkdir()
        project2.mkdir()

        collector1 = get_evidence_collector(project1)
        collector2 = get_evidence_collector(project2)

        assert collector1 is not collector2

    def test_resolves_path(self, tmp_path: Path) -> None:
        """Test that paths are resolved."""
        subdir = tmp_path / "sub"
        subdir.mkdir()

        # Use relative-like path
        collector = get_evidence_collector(subdir)
        assert collector.project_root == subdir.resolve()


class TestClearAllCollectors:
    """Tests for clear_all_collectors function."""

    def test_clears_singletons(self, tmp_path: Path) -> None:
        """Test that clearing singletons creates new instances."""
        collector1 = get_evidence_collector(tmp_path)

        clear_all_collectors()

        collector2 = get_evidence_collector(tmp_path)
        assert collector1 is not collector2


class TestEvidenceContextCollector:
    """Tests for EvidenceContextCollector class."""

    def test_project_root_property(self, tmp_path: Path) -> None:
        """Test project_root property."""
        collector = EvidenceContextCollector(tmp_path)
        assert collector.project_root == tmp_path.resolve()

    def test_collect_all_empty_project(self, tmp_path: Path) -> None:
        """Test collecting from empty project returns context with all None."""
        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all()

        assert evidence is not None
        assert evidence.coverage is None
        assert evidence.test_results is None
        assert evidence.security is None
        assert evidence.performance is None
        assert evidence.collected_at  # Should have timestamp

    def test_collect_all_with_coverage(
        self,
        tmp_path: Path,
        evidence_fixtures_dir: Path,
    ) -> None:
        """Test collecting coverage evidence."""
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        shutil.copy(
            evidence_fixtures_dir / "sample-lcov.info",
            coverage_dir / "lcov.info",
        )

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all()

        assert evidence.coverage is not None
        assert evidence.coverage.total_lines > 0

    def test_collect_all_with_test_results(
        self,
        tmp_path: Path,
        evidence_fixtures_dir: Path,
    ) -> None:
        """Test collecting test results evidence."""
        shutil.copy(
            evidence_fixtures_dir / "sample-junit.xml",
            tmp_path / "junit.xml",
        )

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all()

        assert evidence.test_results is not None
        assert evidence.test_results.total == 10

    def test_collect_all_with_security(
        self,
        tmp_path: Path,
        evidence_fixtures_dir: Path,
    ) -> None:
        """Test collecting security evidence."""
        shutil.copy(
            evidence_fixtures_dir / "sample-npm-audit.json",
            tmp_path / "npm-audit.json",
        )

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all()

        assert evidence.security is not None
        assert evidence.security.total == 5

    def test_collect_all_with_performance(
        self,
        tmp_path: Path,
        evidence_fixtures_dir: Path,
    ) -> None:
        """Test collecting performance evidence."""
        shutil.copy(
            evidence_fixtures_dir / "sample-lighthouse.json",
            tmp_path / "lighthouse-report.json",
        )

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all()

        assert evidence.performance is not None
        assert evidence.performance.lighthouse_scores is not None

    def test_collect_all_complete(
        self,
        tmp_path: Path,
        evidence_fixtures_dir: Path,
    ) -> None:
        """Test collecting all evidence types."""
        # Setup all evidence files
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        shutil.copy(
            evidence_fixtures_dir / "sample-lcov.info",
            coverage_dir / "lcov.info",
        )
        shutil.copy(
            evidence_fixtures_dir / "sample-junit.xml",
            tmp_path / "junit.xml",
        )
        shutil.copy(
            evidence_fixtures_dir / "sample-npm-audit.json",
            tmp_path / "npm-audit.json",
        )
        shutil.copy(
            evidence_fixtures_dir / "sample-lighthouse.json",
            tmp_path / "lighthouse-report.json",
        )

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all()

        assert evidence.coverage is not None
        assert evidence.test_results is not None
        assert evidence.security is not None
        assert evidence.performance is not None
        assert evidence.collected_at

    def test_collect_all_iso_timestamp(self, tmp_path: Path) -> None:
        """Test that collected_at is valid ISO 8601."""
        from datetime import datetime

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all()

        # Should be parseable as ISO 8601
        dt = datetime.fromisoformat(evidence.collected_at)
        assert dt is not None

    def test_collect_all_returns_new_context(self, tmp_path: Path) -> None:
        """Test that each call returns cached context when files unchanged."""
        collector = EvidenceContextCollector(tmp_path)

        evidence1 = collector.collect_all()
        evidence2 = collector.collect_all()

        # Same object due to caching (AC1: mtime-based cache invalidation)
        assert evidence1 is evidence2


class TestCollectorIntegration:
    """Integration tests for the collector."""

    def test_full_workflow(
        self,
        tmp_path: Path,
        evidence_fixtures_dir: Path,
    ) -> None:
        """Test full workflow: collect → to_dict → to_markdown."""
        # Setup evidence
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        shutil.copy(
            evidence_fixtures_dir / "sample-lcov.info",
            coverage_dir / "lcov.info",
        )
        shutil.copy(
            evidence_fixtures_dir / "sample-junit.xml",
            tmp_path / "junit.xml",
        )

        # Collect
        collector = get_evidence_collector(tmp_path)
        evidence = collector.collect_all()

        # Serialize
        data = evidence.to_dict()
        assert "coverage" in data
        assert "test_results" in data
        assert "collected_at" in data

        # Format for LLM
        markdown = evidence.to_markdown()
        assert "## Evidence Context" in markdown
        assert "### Coverage Evidence" in markdown
        assert "### Test Results" in markdown


class TestCollectorWithEvidenceConfig:
    """Tests for EvidenceContextCollector with EvidenceConfig (Story 25.5)."""

    def test_collect_all_with_evidence_config(
        self,
        tmp_path: Path,
        evidence_fixtures_dir: Path,
    ) -> None:
        """Test collect_all accepts EvidenceConfig."""
        from bmad_assist.testarch.config import EvidenceConfig, SourceConfigModel

        # Setup evidence files
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        shutil.copy(
            evidence_fixtures_dir / "sample-lcov.info",
            coverage_dir / "lcov.info",
        )

        # Create config with custom coverage patterns
        config = EvidenceConfig(
            enabled=True,
            coverage=SourceConfigModel(
                enabled=True,
                patterns=["coverage/lcov.info"],
            ),
        )

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all(config)

        assert evidence is not None
        assert evidence.coverage is not None
        assert evidence.coverage.total_lines > 0

    def test_collect_all_disabled_master_switch(self, tmp_path: Path) -> None:
        """Test collect_all returns empty context when master switch disabled."""
        from bmad_assist.testarch.config import EvidenceConfig

        config = EvidenceConfig(enabled=False)

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all(config)

        assert evidence is not None
        assert evidence.coverage is None
        assert evidence.test_results is None
        assert evidence.security is None
        assert evidence.performance is None
        assert evidence.collected_at  # Should still have timestamp

    def test_collect_all_disabled_source(
        self,
        tmp_path: Path,
        evidence_fixtures_dir: Path,
    ) -> None:
        """Test collect_all skips disabled sources."""
        from bmad_assist.testarch.config import EvidenceConfig, SourceConfigModel

        # Setup coverage file
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        shutil.copy(
            evidence_fixtures_dir / "sample-lcov.info",
            coverage_dir / "lcov.info",
        )

        # Disable coverage source
        config = EvidenceConfig(
            enabled=True,
            coverage=SourceConfigModel(enabled=False),
        )

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all(config)

        # Coverage should be None even though file exists
        assert evidence.coverage is None

    def test_collect_all_custom_patterns(
        self,
        tmp_path: Path,
    ) -> None:
        """Test collect_all uses custom patterns from config."""
        from bmad_assist.testarch.config import EvidenceConfig, SourceConfigModel

        # Create custom named coverage file
        custom_coverage = tmp_path / "my-custom-coverage.info"
        custom_coverage.write_text("""TN:Custom
SF:/custom.js
LF:100
LH:90
end_of_record
""")

        config = EvidenceConfig(
            enabled=True,
            coverage=SourceConfigModel(
                enabled=True,
                patterns=["my-custom-coverage.info"],
            ),
        )

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all(config)

        assert evidence.coverage is not None
        assert evidence.coverage.total_lines == 100
        assert evidence.coverage.covered_lines == 90

    def test_collect_all_none_config_uses_defaults(
        self,
        tmp_path: Path,
        evidence_fixtures_dir: Path,
    ) -> None:
        """Test collect_all with None config uses default patterns."""
        # Setup evidence with default location
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        shutil.copy(
            evidence_fixtures_dir / "sample-lcov.info",
            coverage_dir / "lcov.info",
        )

        collector = EvidenceContextCollector(tmp_path)
        evidence = collector.collect_all(None)

        assert evidence.coverage is not None

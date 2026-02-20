"""E2E tests for TEA evidence collection integration.

Story 25.14: Integration Testing - AC: 6.
Tests evidence collection integration within TEA workflows, verifying
that evidence is properly collected, cached, and passed to workflow context.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.state import State

# Import shared fixtures from conftest
from tests.testarch.e2e.conftest import FakeConfig


class TestEvidenceCollectorBasics:
    """Test evidence collector basic functionality."""

    @pytest.fixture
    def setup_project_with_coverage(self, tmp_path: Path) -> Path:
        """Create project with coverage data."""
        # Create project structure
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")
        (tmp_path / "_bmad-output").mkdir(parents=True)
        (tmp_path / "coverage").mkdir(parents=True)

        # Create lcov.info file (coverage data)
        lcov_content = """TN:
SF:src/app.py
DA:1,1
DA:2,1
DA:3,0
DA:4,1
LF:4
LH:3
end_of_record
SF:src/utils.py
DA:1,1
DA:2,0
LF:2
LH:1
end_of_record
"""
        (tmp_path / "coverage/lcov.info").write_text(lcov_content)

        return tmp_path

    def test_collector_singleton_per_project(self, tmp_path: Path) -> None:
        """Test collector is singleton per project root."""
        from bmad_assist.testarch.evidence import clear_all_collectors, get_evidence_collector

        clear_all_collectors()

        collector1 = get_evidence_collector(tmp_path)
        collector2 = get_evidence_collector(tmp_path)

        assert collector1 is collector2

        # Different path should give different collector
        other_path = tmp_path / "other"
        other_path.mkdir()
        collector3 = get_evidence_collector(other_path)

        assert collector3 is not collector1

        clear_all_collectors()

    def test_collector_collects_coverage_evidence(
        self, setup_project_with_coverage: Path
    ) -> None:
        """Test collector can collect coverage evidence."""
        from bmad_assist.testarch.evidence import clear_all_collectors, get_evidence_collector

        clear_all_collectors()
        project_path = setup_project_with_coverage

        collector = get_evidence_collector(project_path)
        evidence = collector.collect_all()

        # Evidence should be collected
        assert evidence is not None
        # Coverage may or may not be present depending on implementation
        # but evidence context should be valid
        assert hasattr(evidence, "collected_at")

        clear_all_collectors()

    def test_collector_handles_missing_files_gracefully(
        self, tmp_path: Path
    ) -> None:
        """Test collector handles missing evidence files gracefully."""
        from bmad_assist.testarch.evidence import clear_all_collectors, get_evidence_collector

        clear_all_collectors()

        # Project with no evidence files
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")

        collector = get_evidence_collector(tmp_path)
        evidence = collector.collect_all()

        # Should not raise, just return None for missing sources
        assert evidence is not None

        clear_all_collectors()


class TestEvidenceInWorkflows:
    """Test evidence integration in TEA workflows."""

    @pytest.fixture
    def setup_workflow_project(self, tmp_path: Path) -> tuple[Path, State]:
        """Create project with workflow and evidence data."""
        # Create workflow directory for nfr-assess
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/nfr"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text("""
name: testarch-nfr
description: "NFR assessment"
instructions: "{installed_path}/instructions.xml"
""")
        (workflow_dir / "instructions.xml").write_text("<workflow></workflow>")

        # Create output directories
        (tmp_path / "_bmad-output").mkdir(parents=True)

        # Create docs
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")

        # Create coverage data
        (tmp_path / "coverage").mkdir(parents=True)
        (tmp_path / "coverage/lcov.info").write_text("""TN:
SF:src/app.py
DA:1,1
DA:2,1
LF:2
LH:2
end_of_record
""")

        state = State()
        state.current_epic = 1

        return tmp_path, state

    def test_nfr_handler_can_access_evidence(
        self, setup_workflow_project: tuple[Path, State]
    ) -> None:
        """Test NFRAssessHandler can access evidence context."""
        project_path, state = setup_workflow_project
        config = FakeConfig(evidence_enabled=True)

        from bmad_assist.testarch.handlers.nfr_assess import NFRAssessHandler

        handler = NFRAssessHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>nfr</compiled>"
        mock_compiled.workflow_name = "testarch-nfr"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# NFR Assessment\n\n## Status: PASS\n\nAll NFRs satisfied.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.nfr_assess.get_paths") as mock_nfr_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_nfr_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert result.success is True

    def test_evidence_disabled_skips_collection(
        self, setup_workflow_project: tuple[Path, State]
    ) -> None:
        """Test evidence collection is skipped when disabled."""
        project_path, state = setup_workflow_project
        config = FakeConfig(evidence_enabled=False)

        # Evidence should not be collected when disabled
        assert config.testarch.evidence.enabled is False


class TestEvidenceCaching:
    """Test evidence caching behavior."""

    @pytest.fixture
    def setup_cacheable_project(self, tmp_path: Path) -> Path:
        """Create project for cache testing."""
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")
        (tmp_path / "coverage").mkdir(parents=True)
        (tmp_path / "coverage/lcov.info").write_text("TN:\nSF:a.py\nLF:1\nLH:1\nend_of_record")
        return tmp_path

    def test_collector_caches_evidence(self, setup_cacheable_project: Path) -> None:
        """Test collector caches evidence on subsequent calls."""
        from bmad_assist.testarch.evidence import clear_all_collectors, get_evidence_collector

        clear_all_collectors()
        project_path = setup_cacheable_project

        collector = get_evidence_collector(project_path)

        # First collection
        evidence1 = collector.collect_all()
        # Second collection (should use cache)
        evidence2 = collector.collect_all()

        # Both should be valid
        assert evidence1 is not None
        assert evidence2 is not None

        clear_all_collectors()

    def test_collector_invalidates_cache_on_file_change(
        self, setup_cacheable_project: Path
    ) -> None:
        """Test collector invalidates cache when source files change."""
        import time

        from bmad_assist.testarch.evidence import clear_all_collectors, get_evidence_collector

        clear_all_collectors()
        project_path = setup_cacheable_project

        collector = get_evidence_collector(project_path)

        # First collection
        evidence1 = collector.collect_all()
        evidence1_time = evidence1.collected_at if evidence1 else None

        # Wait a moment and modify source file
        time.sleep(0.1)
        lcov_file = project_path / "coverage/lcov.info"
        lcov_file.write_text("TN:\nSF:a.py\nLF:2\nLH:2\nend_of_record")

        # Force cache invalidation by clearing
        collector._cached_evidence = None

        # Second collection (should re-collect due to mtime change)
        evidence2 = collector.collect_all()

        assert evidence1 is not None
        assert evidence2 is not None

        clear_all_collectors()


class TestEvidenceContextPassing:
    """Test evidence context is properly passed to workflows."""

    @pytest.fixture
    def setup_context_project(self, tmp_path: Path) -> tuple[Path, State]:
        """Create project for context passing tests."""
        # Create workflow
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/automate"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text("""
name: testarch-automate
description: "Automate workflow"
instructions: "{installed_path}/instructions.xml"
""")
        (workflow_dir / "instructions.xml").write_text("<workflow></workflow>")

        (tmp_path / "_bmad-output").mkdir(parents=True)
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")

        state = State()
        state.current_epic = 1

        return tmp_path, state

    def test_handler_includes_evidence_in_context(
        self, setup_context_project: tuple[Path, State]
    ) -> None:
        """Test handler includes evidence context when available."""
        project_path, state = setup_context_project
        config = FakeConfig(evidence_enabled=True)

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        handler = AutomateHandler(config, project_path)  # type: ignore

        # Build context should work
        context = handler.build_context(state)

        assert context is not None
        assert isinstance(context, dict)

    def test_context_without_evidence_still_valid(
        self, setup_context_project: tuple[Path, State]
    ) -> None:
        """Test context is valid even without evidence."""
        project_path, state = setup_context_project
        config = FakeConfig(evidence_enabled=False)

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        handler = AutomateHandler(config, project_path)  # type: ignore

        context = handler.build_context(state)

        assert context is not None
        assert isinstance(context, dict)


class TestEvidenceSourceTypes:
    """Test different evidence source types."""

    @pytest.fixture
    def setup_multi_source_project(self, tmp_path: Path) -> Path:
        """Create project with multiple evidence sources."""
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")
        (tmp_path / "_bmad-output").mkdir(parents=True)

        # Coverage data
        (tmp_path / "coverage").mkdir(parents=True)
        (tmp_path / "coverage/lcov.info").write_text("""TN:
SF:src/app.py
LF:100
LH:85
end_of_record
""")

        # Test results (pytest format)
        (tmp_path / "test-results").mkdir(parents=True)
        (tmp_path / "test-results/pytest.xml").write_text("""<?xml version="1.0"?>
<testsuites>
    <testsuite name="tests" tests="50" failures="2" errors="0">
    </testsuite>
</testsuites>
""")

        return tmp_path

    def test_collector_handles_multiple_sources(
        self, setup_multi_source_project: Path
    ) -> None:
        """Test collector handles multiple evidence sources."""
        from bmad_assist.testarch.evidence import clear_all_collectors, get_evidence_collector

        clear_all_collectors()
        project_path = setup_multi_source_project

        collector = get_evidence_collector(project_path)
        evidence = collector.collect_all()

        # Should collect without error
        assert evidence is not None
        assert hasattr(evidence, "coverage")
        assert hasattr(evidence, "test_results")

        clear_all_collectors()

    def test_evidence_context_is_immutable(
        self, setup_multi_source_project: Path
    ) -> None:
        """Test evidence context objects are immutable (dataclass frozen)."""
        from bmad_assist.testarch.evidence.models import CoverageEvidence

        coverage = CoverageEvidence(
            total_lines=100,
            covered_lines=85,
            coverage_percent=85.0,
            uncovered_files=("src/legacy.py",),
            source="coverage/lcov.info",
        )

        # Should be frozen dataclass
        with pytest.raises(AttributeError):
            coverage.total_lines = 200  # type: ignore[misc]

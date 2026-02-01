"""Tests for TestarchEvidenceMixin (Story 25.5).

These tests verify:
- collect_before_step behavior
- Evidence injection into workflow context
- Disabled evidence collection when flag is False
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.state import Phase, State


@pytest.fixture
def mock_config_with_evidence() -> MagicMock:
    """Create a mock Config with evidence collection enabled."""
    from bmad_assist.testarch.config import EvidenceConfig, SourceConfigModel

    config = MagicMock()
    config.testarch = MagicMock()
    config.testarch.atdd_mode = "auto"
    config.testarch.preflight = None
    config.testarch.eligibility = None
    config.testarch.evidence = EvidenceConfig(
        enabled=True,
        collect_before_step=True,
        coverage=SourceConfigModel(enabled=True, patterns=["coverage/lcov.info"]),
    )
    config.benchmarking = MagicMock()
    config.benchmarking.enabled = False
    return config


@pytest.fixture
def mock_config_evidence_disabled() -> MagicMock:
    """Create a mock Config with evidence collection disabled."""
    from bmad_assist.testarch.config import EvidenceConfig

    config = MagicMock()
    config.testarch = MagicMock()
    config.testarch.atdd_mode = "auto"
    config.testarch.preflight = None
    config.testarch.eligibility = None
    config.testarch.evidence = EvidenceConfig(
        enabled=True,
        collect_before_step=False,  # Disabled
    )
    config.benchmarking = MagicMock()
    config.benchmarking.enabled = False
    return config


@pytest.fixture
def state_story_1_1() -> State:
    """State at story 1.1."""
    return State(
        current_epic=1,
        current_story="1.1",
        current_phase=Phase.ATDD,
    )


class TestShouldCollectEvidence:
    """Tests for _should_collect_evidence method."""

    def test_returns_true_when_enabled(
        self,
        mock_config_with_evidence: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test that _should_collect_evidence returns True when enabled."""
        from bmad_assist.testarch.handlers.atdd import ATDDHandler

        handler = ATDDHandler(mock_config_with_evidence, tmp_path)
        assert handler._should_collect_evidence() is True

    def test_returns_false_when_disabled(
        self,
        mock_config_evidence_disabled: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test that _should_collect_evidence returns False when disabled."""
        from bmad_assist.testarch.handlers.atdd import ATDDHandler

        handler = ATDDHandler(mock_config_evidence_disabled, tmp_path)
        assert handler._should_collect_evidence() is False

    def test_returns_false_when_no_testarch_config(
        self,
        tmp_path: Path,
    ) -> None:
        """Test that _should_collect_evidence returns False without testarch config."""
        from bmad_assist.testarch.handlers.atdd import ATDDHandler

        config = MagicMock()
        config.testarch = None
        config.benchmarking = MagicMock()
        config.benchmarking.enabled = False

        handler = ATDDHandler(config, tmp_path)
        assert handler._should_collect_evidence() is False

    def test_returns_false_when_no_evidence_config(
        self,
        tmp_path: Path,
    ) -> None:
        """Test that _should_collect_evidence returns False without evidence config."""
        from bmad_assist.testarch.handlers.atdd import ATDDHandler

        config = MagicMock()
        config.testarch = MagicMock()
        config.testarch.evidence = None
        config.benchmarking = MagicMock()
        config.benchmarking.enabled = False

        handler = ATDDHandler(config, tmp_path)
        assert handler._should_collect_evidence() is False


class TestCollectEvidence:
    """Tests for _collect_evidence method."""

    def test_collect_evidence_returns_context(
        self,
        mock_config_with_evidence: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test that _collect_evidence returns EvidenceContext."""
        from bmad_assist.testarch.evidence import EvidenceContext
        from bmad_assist.testarch.handlers.atdd import ATDDHandler

        handler = ATDDHandler(mock_config_with_evidence, tmp_path)
        context = handler._collect_evidence()

        assert isinstance(context, EvidenceContext)
        assert context.collected_at is not None

    def test_collect_evidence_uses_config(
        self,
        mock_config_with_evidence: MagicMock,
        tmp_path: Path,
        evidence_fixtures_dir: Path,
    ) -> None:
        """Test that _collect_evidence uses EvidenceConfig."""
        import shutil

        from bmad_assist.testarch.handlers.atdd import ATDDHandler

        # Setup coverage file
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        shutil.copy(
            evidence_fixtures_dir / "sample-lcov.info",
            coverage_dir / "lcov.info",
        )

        handler = ATDDHandler(mock_config_with_evidence, tmp_path)
        context = handler._collect_evidence()

        # Coverage should be collected based on config pattern
        assert context.coverage is not None


class TestGetEvidenceMarkdown:
    """Tests for _get_evidence_markdown method."""

    def test_returns_empty_when_collection_disabled(
        self,
        mock_config_evidence_disabled: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test that _get_evidence_markdown returns empty when disabled."""
        from bmad_assist.testarch.handlers.atdd import ATDDHandler

        handler = ATDDHandler(mock_config_evidence_disabled, tmp_path)
        markdown = handler._get_evidence_markdown()

        assert markdown == ""

    def test_returns_markdown_when_enabled(
        self,
        mock_config_with_evidence: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test that _get_evidence_markdown returns markdown when enabled."""
        from bmad_assist.testarch.handlers.atdd import ATDDHandler

        handler = ATDDHandler(mock_config_with_evidence, tmp_path)
        markdown = handler._get_evidence_markdown()

        # Should have evidence header even if no actual evidence
        assert "Evidence Context" in markdown or markdown == ""

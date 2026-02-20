"""Tests for LoopConfig model and DEFAULT_LOOP_CONFIG.

Story 25.12: Loop Configuration & Phase Registration
Tests for:
- DEFAULT_LOOP_CONFIG is minimal (no TEA phases)
- TEA_FULL_LOOP_CONFIG has all TEA phases
- Phase ordering validation
- LoopConfig model validation
"""

import logging
import pytest
from pydantic import ValidationError

from bmad_assist.core.config.models.loop import (
    LoopConfig,
    DEFAULT_LOOP_CONFIG,
    TEA_FULL_LOOP_CONFIG,
)


# =============================================================================
# Test DEFAULT_LOOP_CONFIG
# =============================================================================


class TestDefaultLoopConfig:
    """Test DEFAULT_LOOP_CONFIG constant (minimal, no TEA phases)."""

    def test_is_loop_config_instance(self) -> None:
        """DEFAULT_LOOP_CONFIG is a LoopConfig instance."""
        assert isinstance(DEFAULT_LOOP_CONFIG, LoopConfig)

    def test_epic_setup_is_empty(self) -> None:
        """DEFAULT_LOOP_CONFIG epic_setup is empty (no TEA setup phases)."""
        assert DEFAULT_LOOP_CONFIG.epic_setup == []

    def test_story_phases_no_atdd(self) -> None:
        """DEFAULT_LOOP_CONFIG story phases exclude 'atdd' (TEA phase)."""
        assert "atdd" not in DEFAULT_LOOP_CONFIG.story

    def test_story_phases_no_test_review(self) -> None:
        """DEFAULT_LOOP_CONFIG story phases exclude 'test_review' (TEA phase)."""
        assert "test_review" not in DEFAULT_LOOP_CONFIG.story

    def test_story_phases_include_core_phases(self) -> None:
        """DEFAULT_LOOP_CONFIG story phases include core workflow phases."""
        expected_core = [
            "create_story",
            "validate_story",
            "validate_story_synthesis",
            "dev_story",
            "code_review",
            "code_review_synthesis",
        ]
        assert DEFAULT_LOOP_CONFIG.story == expected_core

    def test_epic_teardown_includes_retrospective(self) -> None:
        """DEFAULT_LOOP_CONFIG epic_teardown includes 'retrospective' and 'hardening'."""
        assert DEFAULT_LOOP_CONFIG.epic_teardown == ["retrospective", "hardening"]

    def test_epic_teardown_no_trace(self) -> None:
        """DEFAULT_LOOP_CONFIG epic_teardown excludes 'trace' (TEA phase)."""
        assert "trace" not in DEFAULT_LOOP_CONFIG.epic_teardown

    def test_epic_teardown_no_tea_nfr_assess(self) -> None:
        """DEFAULT_LOOP_CONFIG epic_teardown excludes 'tea_nfr_assess' (TEA phase)."""
        assert "tea_nfr_assess" not in DEFAULT_LOOP_CONFIG.epic_teardown


# =============================================================================
# Test TEA_FULL_LOOP_CONFIG
# =============================================================================


class TestTeaFullLoopConfig:
    """Test TEA_FULL_LOOP_CONFIG constant (all TEA phases enabled)."""

    def test_is_loop_config_instance(self) -> None:
        """TEA_FULL_LOOP_CONFIG is a LoopConfig instance."""
        assert isinstance(TEA_FULL_LOOP_CONFIG, LoopConfig)

    # --- epic_setup tests ---

    def test_epic_setup_includes_tea_framework(self) -> None:
        """TEA_FULL_LOOP_CONFIG epic_setup includes 'tea_framework'."""
        assert "tea_framework" in TEA_FULL_LOOP_CONFIG.epic_setup

    def test_epic_setup_includes_tea_ci(self) -> None:
        """TEA_FULL_LOOP_CONFIG epic_setup includes 'tea_ci'."""
        assert "tea_ci" in TEA_FULL_LOOP_CONFIG.epic_setup

    def test_epic_setup_includes_tea_test_design(self) -> None:
        """TEA_FULL_LOOP_CONFIG epic_setup includes 'tea_test_design'."""
        assert "tea_test_design" in TEA_FULL_LOOP_CONFIG.epic_setup

    def test_epic_setup_includes_tea_automate(self) -> None:
        """TEA_FULL_LOOP_CONFIG epic_setup includes 'tea_automate'."""
        assert "tea_automate" in TEA_FULL_LOOP_CONFIG.epic_setup

    def test_tea_framework_before_tea_ci(self) -> None:
        """tea_framework comes before tea_ci in epic_setup."""
        setup = TEA_FULL_LOOP_CONFIG.epic_setup
        framework_idx = setup.index("tea_framework")
        ci_idx = setup.index("tea_ci")
        assert framework_idx < ci_idx

    # --- story tests ---

    def test_story_phases_include_atdd(self) -> None:
        """TEA_FULL_LOOP_CONFIG story phases include 'atdd'."""
        assert "atdd" in TEA_FULL_LOOP_CONFIG.story

    def test_story_phases_include_test_review(self) -> None:
        """TEA_FULL_LOOP_CONFIG story phases include 'test_review'."""
        assert "test_review" in TEA_FULL_LOOP_CONFIG.story

    def test_atdd_before_dev_story(self) -> None:
        """ATDD comes before dev_story in TEA story phases."""
        story = TEA_FULL_LOOP_CONFIG.story
        atdd_idx = story.index("atdd")
        dev_idx = story.index("dev_story")
        assert atdd_idx < dev_idx

    def test_test_review_after_code_review_synthesis(self) -> None:
        """test_review comes after code_review_synthesis in TEA story phases."""
        story = TEA_FULL_LOOP_CONFIG.story
        test_review_idx = story.index("test_review")
        code_review_synthesis_idx = story.index("code_review_synthesis")
        assert test_review_idx > code_review_synthesis_idx

    # --- epic_teardown tests ---

    def test_epic_teardown_includes_trace(self) -> None:
        """TEA_FULL_LOOP_CONFIG epic_teardown includes 'trace'."""
        assert "trace" in TEA_FULL_LOOP_CONFIG.epic_teardown

    def test_epic_teardown_includes_tea_nfr_assess(self) -> None:
        """TEA_FULL_LOOP_CONFIG epic_teardown includes 'tea_nfr_assess'."""
        assert "tea_nfr_assess" in TEA_FULL_LOOP_CONFIG.epic_teardown

    def test_epic_teardown_includes_retrospective(self) -> None:
        """TEA_FULL_LOOP_CONFIG epic_teardown includes 'retrospective'."""
        assert "retrospective" in TEA_FULL_LOOP_CONFIG.epic_teardown

    def test_trace_before_retrospective(self) -> None:
        """trace comes before retrospective in TEA epic_teardown."""
        teardown = TEA_FULL_LOOP_CONFIG.epic_teardown
        trace_idx = teardown.index("trace")
        retro_idx = teardown.index("retrospective")
        assert trace_idx < retro_idx

    def test_tea_nfr_assess_before_retrospective(self) -> None:
        """tea_nfr_assess comes before retrospective in epic_teardown."""
        teardown = TEA_FULL_LOOP_CONFIG.epic_teardown
        nfr_idx = teardown.index("tea_nfr_assess")
        retro_idx = teardown.index("retrospective")
        assert nfr_idx < retro_idx


# =============================================================================
# Test Phase Ordering Validation
# =============================================================================


class TestPhaseOrderingValidation:
    """Test LoopConfig phase ordering validation."""

    def test_valid_ordering_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Valid phase ordering produces no warnings."""
        with caplog.at_level(logging.WARNING):
            LoopConfig(
                epic_setup=[],
                story=["atdd", "dev_story", "code_review", "code_review_synthesis", "test_review"],
                epic_teardown=["trace", "retrospective"],
            )

        # No warnings about ordering
        ordering_warnings = [r for r in caplog.records if "ordering" in r.message.lower()]
        assert len(ordering_warnings) == 0

    def test_warns_atdd_after_dev_story(self, caplog: pytest.LogCaptureFixture) -> None:
        """Logs warning when atdd comes after dev_story."""
        with caplog.at_level(logging.WARNING):
            LoopConfig(
                epic_setup=[],
                story=["dev_story", "atdd"],  # Wrong order!
                epic_teardown=[],
            )

        assert any("atdd" in r.message.lower() and "dev_story" in r.message.lower() for r in caplog.records)

    def test_warns_test_review_before_code_review_synthesis(self, caplog: pytest.LogCaptureFixture) -> None:
        """Logs warning when test_review comes before code_review_synthesis."""
        with caplog.at_level(logging.WARNING):
            LoopConfig(
                epic_setup=[],
                story=["test_review", "code_review_synthesis"],  # Wrong order!
                epic_teardown=[],
            )

        assert any("test_review" in r.message.lower() and "code_review_synthesis" in r.message.lower() for r in caplog.records)

    def test_warns_retrospective_before_trace(self, caplog: pytest.LogCaptureFixture) -> None:
        """Logs warning when retrospective comes before trace."""
        with caplog.at_level(logging.WARNING):
            LoopConfig(
                epic_setup=[],
                story=["dev_story"],  # Required at least one
                epic_teardown=["retrospective", "trace"],  # Wrong order!
            )

        assert any("trace" in r.message.lower() and "retrospective" in r.message.lower() for r in caplog.records)

    def test_no_warning_when_both_phases_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        """No warning when both phases of a pair are missing."""
        with caplog.at_level(logging.WARNING):
            LoopConfig(
                epic_setup=[],
                story=["dev_story"],  # No atdd, no test_review
                epic_teardown=[],
            )

        # Should not warn about missing phases
        ordering_warnings = [r for r in caplog.records if "ordering" in r.message.lower()]
        assert len(ordering_warnings) == 0


# =============================================================================
# Test LoopConfig Model
# =============================================================================


class TestLoopConfigModel:
    """Test LoopConfig Pydantic model."""

    def test_requires_at_least_one_story_phase(self) -> None:
        """LoopConfig requires at least one story phase."""
        with pytest.raises(ValidationError) as exc_info:
            LoopConfig()
        assert "must contain at least one phase" in str(exc_info.value)

    def test_accepts_valid_phases(self) -> None:
        """LoopConfig accepts valid phase names."""
        config = LoopConfig(
            epic_setup=["tea_framework", "tea_ci"],
            story=["create_story", "dev_story"],
            epic_teardown=["retrospective"],
        )
        assert "tea_framework" in config.epic_setup
        assert "dev_story" in config.story
        assert "retrospective" in config.epic_teardown

    def test_frozen_model(self) -> None:
        """LoopConfig is immutable."""
        config = LoopConfig(story=["dev_story"])
        with pytest.raises(ValidationError):
            config.epic_setup = ["new_phase"]  # type: ignore[misc]

    def test_from_dict(self) -> None:
        """LoopConfig can be created from dictionary."""
        config = LoopConfig.model_validate({
            "epic_setup": ["tea_framework"],
            "story": ["atdd", "dev_story"],
            "epic_teardown": ["trace"],
        })
        assert config.epic_setup == ["tea_framework"]
        assert config.story == ["atdd", "dev_story"]
        assert config.epic_teardown == ["trace"]


# =============================================================================
# Test Exports
# =============================================================================


class TestLoopConfigExports:
    """Test LoopConfig exports from config package."""

    def test_default_loop_config_exported_from_models(self) -> None:
        """DEFAULT_LOOP_CONFIG is exported from config.models."""
        from bmad_assist.core.config.models import DEFAULT_LOOP_CONFIG as exported
        assert exported is DEFAULT_LOOP_CONFIG

    def test_tea_full_loop_config_exported_from_models(self) -> None:
        """TEA_FULL_LOOP_CONFIG is exported from config.models."""
        from bmad_assist.core.config.models import TEA_FULL_LOOP_CONFIG as exported
        assert exported is TEA_FULL_LOOP_CONFIG

    def test_default_loop_config_exported_from_config(self) -> None:
        """DEFAULT_LOOP_CONFIG is exported from core.config."""
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG as exported
        assert exported is DEFAULT_LOOP_CONFIG

    def test_tea_full_loop_config_exported_from_config(self) -> None:
        """TEA_FULL_LOOP_CONFIG is exported from core.config."""
        from bmad_assist.core.config import TEA_FULL_LOOP_CONFIG as exported
        assert exported is TEA_FULL_LOOP_CONFIG

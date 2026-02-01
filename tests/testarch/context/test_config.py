"""Tests for TEA context configuration models."""

import pytest
from pydantic import ValidationError

from bmad_assist.testarch.context.config import (
    TEAContextConfig,
    TEAContextWorkflowConfig,
)


class TestTEAContextWorkflowConfig:
    """Tests for TEAContextWorkflowConfig model."""

    def test_default_is_empty_list(self) -> None:
        """Test that default include is empty list."""
        config = TEAContextWorkflowConfig()
        assert config.include == []

    def test_valid_artifact_types(self) -> None:
        """Test that valid artifact types are accepted."""
        config = TEAContextWorkflowConfig(include=["test-design", "atdd"])
        assert config.include == ["test-design", "atdd"]

    def test_invalid_artifact_type_raises_error(self) -> None:
        """Test that invalid artifact types raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TEAContextWorkflowConfig(include=["test-design", "invalid-type"])

        assert "Invalid artifact types" in str(exc_info.value)
        assert "invalid-type" in str(exc_info.value)

    def test_empty_include_is_valid(self) -> None:
        """Test that empty include list is valid (F12 Fix)."""
        config = TEAContextWorkflowConfig(include=[])
        assert config.include == []

    def test_frozen_model(self) -> None:
        """Test that model is frozen (immutable)."""
        config = TEAContextWorkflowConfig(include=["atdd"])
        with pytest.raises(ValidationError):
            config.include = ["test-design"]  # type: ignore[misc]


class TestTEAContextConfig:
    """Tests for TEAContextConfig model."""

    def test_default_values(self) -> None:
        """Test default configuration values (F4 backward compat)."""
        config = TEAContextConfig()

        # enabled=True by default (F4 Fix)
        assert config.enabled is True
        assert config.budget == 8000
        assert config.max_tokens_per_artifact == 4000
        assert config.max_files_per_resolver == 10

    def test_default_workflows(self) -> None:
        """Test default workflow configurations match current behavior."""
        config = TEAContextConfig()

        # dev_story gets test-design + atdd
        dev_config = config.get_workflow_config("dev_story")
        assert dev_config is not None
        assert "test-design" in dev_config.include
        assert "atdd" in dev_config.include

        # code_review gets test-design only
        review_config = config.get_workflow_config("code_review")
        assert review_config is not None
        assert "test-design" in review_config.include

        # code_review_synthesis gets test-review
        synth_config = config.get_workflow_config("code_review_synthesis")
        assert synth_config is not None
        assert "test-review" in synth_config.include

        # retrospective gets trace
        retro_config = config.get_workflow_config("retrospective")
        assert retro_config is not None
        assert "trace" in retro_config.include

    def test_get_workflow_config_unknown_returns_none(self) -> None:
        """Test that unknown workflow returns None (lenient)."""
        config = TEAContextConfig()
        result = config.get_workflow_config("unknown_workflow")
        assert result is None

    def test_disabled_config(self) -> None:
        """Test explicitly disabled config."""
        config = TEAContextConfig(enabled=False)
        assert config.enabled is False

    def test_zero_budget(self) -> None:
        """Test zero budget is valid (disables loading)."""
        config = TEAContextConfig(budget=0)
        assert config.budget == 0

    def test_custom_workflows(self) -> None:
        """Test custom workflow configuration."""
        custom_workflows = {
            "dev_story": TEAContextWorkflowConfig(include=["atdd"]),  # No test-design
            "custom_workflow": TEAContextWorkflowConfig(include=["trace"]),
        }
        config = TEAContextConfig(workflows=custom_workflows)

        dev_config = config.get_workflow_config("dev_story")
        assert dev_config is not None
        assert dev_config.include == ["atdd"]

        custom_config = config.get_workflow_config("custom_workflow")
        assert custom_config is not None
        assert custom_config.include == ["trace"]

    def test_budget_validation(self) -> None:
        """Test budget must be non-negative."""
        with pytest.raises(ValidationError):
            TEAContextConfig(budget=-1)

    def test_max_files_validation(self) -> None:
        """Test max_files must be at least 1."""
        with pytest.raises(ValidationError):
            TEAContextConfig(max_files_per_resolver=0)

    def test_frozen_model(self) -> None:
        """Test that model is frozen (immutable)."""
        config = TEAContextConfig()
        with pytest.raises(ValidationError):
            config.enabled = False  # type: ignore[misc]

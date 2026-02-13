"""Tests for strategic context config validation."""

import pytest
from pydantic import ValidationError

from bmad_assist.core.config.models.strategic_context import StrategicContextConfig


class TestStrategicContextValidation:
    """Test cases for StrategicContextConfig validation."""

    def test_tree_budget_within_budget(self) -> None:
        """Test that tree_budget <= budget is valid."""
        config = StrategicContextConfig(
            budget=10000,
            tree_budget=5000,
        )
        assert config.budget == 10000
        assert config.tree_budget == 5000

    def test_tree_budget_equals_budget(self) -> None:
        """Test that tree_budget == budget is valid."""
        config = StrategicContextConfig(
            budget=5000,
            tree_budget=5000,
        )
        assert config.budget == 5000
        assert config.tree_budget == 5000

    def test_tree_budget_exceeds_budget_raises_error(self) -> None:
        """Test that tree_budget > budget raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            StrategicContextConfig(
                budget=5000,
                tree_budget=8000,
            )

        error_msg = str(exc_info.value)
        assert "tree_budget" in error_msg
        assert "cannot exceed" in error_msg

    def test_tree_budget_with_zero_budget(self) -> None:
        """Test that tree_budget can exceed budget when budget is 0 (disabled)."""
        # When budget is 0, strategic context is disabled, so tree_budget doesn't matter
        config = StrategicContextConfig(
            budget=0,
            tree_budget=5000,
        )
        assert config.budget == 0
        assert config.tree_budget == 5000

    def test_default_tree_budget(self) -> None:
        """Test default tree_budget value."""
        config = StrategicContextConfig()
        # Default tree_budget should be <= default budget (8000)
        assert config.tree_budget <= config.budget
        assert config.tree_budget == 5000  # Default value

    def test_tree_budget_zero_disables_project_tree(self) -> None:
        """Test tree_budget=0 disables project tree entirely."""
        config = StrategicContextConfig(
            tree_budget=0,
        )
        assert config.tree_budget == 0

    def test_valid_config_with_workflow_overrides(self) -> None:
        """Test that validation works with workflow-specific overrides."""
        config = StrategicContextConfig(
            budget=10000,
            tree_budget=5000,
            dev_story={
                "include": ("project-tree", "project-context"),
            },
        )

        include, main_only = config.get_workflow_config("dev_story")
        assert "project-tree" in include
        assert "project-context" in include

    def test_project_tree_in_include(self) -> None:
        """Test that 'project-tree' is a valid StrategicDocType."""
        from bmad_assist.core.config.models.strategic_context import StrategicDocType

        # Verify project-tree is in the valid types
        valid_types = StrategicDocType.__args__
        assert "project-tree" in valid_types

        # Test creating config with project-tree
        config = StrategicContextConfig(
            defaults={
                "include": ("project-tree", "project-context"),
            },
        )

        include, _ = config.get_workflow_config("any_workflow")
        assert "project-tree" in include

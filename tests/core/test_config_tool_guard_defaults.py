"""Tests for ToolCallGuard config defaults (Fix #2)."""

import pytest
from pydantic import ValidationError

from bmad_assist.core.config.models.features import ToolGuardConfig


class TestToolGuardDefaults:
    """Verify ToolGuardConfig defaults after Fix #2."""

    def test_default_max_interactions_per_file_is_40(self) -> None:
        """Fix #2: Default raised from 25 to 40."""
        config = ToolGuardConfig()
        assert config.max_interactions_per_file == 40

    def test_default_max_total_calls_unchanged(self) -> None:
        """max_total_calls default remains 300."""
        config = ToolGuardConfig()
        assert config.max_total_calls == 300

    def test_default_max_calls_per_minute_unchanged(self) -> None:
        """max_calls_per_minute default remains 90."""
        config = ToolGuardConfig()
        assert config.max_calls_per_minute == 90

    def test_custom_max_interactions_per_file(self) -> None:
        """Custom value overrides default."""
        config = ToolGuardConfig(max_interactions_per_file=50)
        assert config.max_interactions_per_file == 50

    def test_min_validation_rejects_zero(self) -> None:
        """max_interactions_per_file must be >= 1."""
        with pytest.raises(ValidationError):
            ToolGuardConfig(max_interactions_per_file=0)

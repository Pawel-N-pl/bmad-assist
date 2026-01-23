"""Tests for TimeoutsConfig and get_phase_timeout().

Story: Per-phase timeout configuration.
"""

import pytest

from bmad_assist.core.config import (
    Config,
    MasterProviderConfig,
    ProviderConfig,
    TimeoutsConfig,
    get_phase_timeout,
)


class TestTimeoutsConfig:
    """Tests for TimeoutsConfig model."""

    def test_default_values(self) -> None:
        """TimeoutsConfig uses sensible defaults."""
        tc = TimeoutsConfig()
        assert tc.default == 3600
        assert tc.create_story is None
        assert tc.validate_story is None
        assert tc.code_review is None

    def test_get_timeout_returns_phase_specific(self) -> None:
        """get_timeout returns phase-specific timeout when set."""
        tc = TimeoutsConfig(default=3600, validate_story=600, code_review=900)
        assert tc.get_timeout("validate_story") == 600
        assert tc.get_timeout("code_review") == 900

    def test_get_timeout_returns_default_for_unset_phase(self) -> None:
        """get_timeout returns default for phases without specific timeout."""
        tc = TimeoutsConfig(default=3600, validate_story=600)
        assert tc.get_timeout("dev_story") == 3600
        assert tc.get_timeout("create_story") == 3600

    def test_get_timeout_returns_default_for_unknown_phase(self) -> None:
        """get_timeout returns default for unknown phase names."""
        tc = TimeoutsConfig(default=3600)
        assert tc.get_timeout("unknown_phase") == 3600
        assert tc.get_timeout("nonexistent") == 3600

    def test_get_timeout_normalizes_hyphens(self) -> None:
        """get_timeout normalizes hyphens to underscores."""
        tc = TimeoutsConfig(default=3600, code_review=900, validate_story=600)
        assert tc.get_timeout("code-review") == 900
        assert tc.get_timeout("validate-story") == 600
        assert tc.get_timeout("validate-story-synthesis") == 3600  # not set

    def test_minimum_timeout_validation(self) -> None:
        """Timeout values must be at least 60 seconds."""
        with pytest.raises(ValueError):
            TimeoutsConfig(default=30)  # Below minimum

    def test_all_phases_can_be_configured(self) -> None:
        """All known phases can have custom timeouts."""
        tc = TimeoutsConfig(
            default=3600,
            create_story=1800,
            validate_story=600,
            validate_story_synthesis=900,
            dev_story=7200,
            code_review=900,
            code_review_synthesis=1200,
            retrospective=1800,
        )
        assert tc.get_timeout("create_story") == 1800
        assert tc.get_timeout("validate_story") == 600
        assert tc.get_timeout("validate_story_synthesis") == 900
        assert tc.get_timeout("dev_story") == 7200
        assert tc.get_timeout("code_review") == 900
        assert tc.get_timeout("code_review_synthesis") == 1200
        assert tc.get_timeout("retrospective") == 1800


class TestGetPhaseTimeout:
    """Tests for get_phase_timeout helper function."""

    def _make_config(
        self,
        timeout: int = 300,
        timeouts: TimeoutsConfig | None = None,
    ) -> Config:
        """Create a minimal Config for testing."""
        return Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus")
            ),
            timeout=timeout,
            timeouts=timeouts,
        )

    def test_uses_timeouts_when_set(self) -> None:
        """get_phase_timeout uses TimeoutsConfig when available."""
        tc = TimeoutsConfig(default=3600, validate_story=600)
        config = self._make_config(timeout=300, timeouts=tc)

        assert get_phase_timeout(config, "validate_story") == 600
        assert get_phase_timeout(config, "dev_story") == 3600  # uses tc.default

    def test_falls_back_to_legacy_timeout(self) -> None:
        """get_phase_timeout uses legacy timeout when timeouts is None."""
        config = self._make_config(timeout=500, timeouts=None)

        assert get_phase_timeout(config, "validate_story") == 500
        assert get_phase_timeout(config, "code_review") == 500
        assert get_phase_timeout(config, "any_phase") == 500

    def test_normalizes_hyphen_phase_names(self) -> None:
        """get_phase_timeout normalizes hyphens in phase names."""
        tc = TimeoutsConfig(default=3600, code_review=900)
        config = self._make_config(timeouts=tc)

        # Both formats work
        assert get_phase_timeout(config, "code_review") == 900
        assert get_phase_timeout(config, "code-review") == 900

    def test_backward_compatibility(self) -> None:
        """Configs without timeouts section still work."""
        # This simulates old config format with just 'timeout'
        config = self._make_config(timeout=1800, timeouts=None)

        # All phases get the legacy timeout
        assert get_phase_timeout(config, "create_story") == 1800
        assert get_phase_timeout(config, "validate_story") == 1800
        assert get_phase_timeout(config, "dev_story") == 1800
        assert get_phase_timeout(config, "code_review") == 1800

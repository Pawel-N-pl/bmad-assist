"""Tests for Cost Tracker.

This module tests the CostTracker class which tracks LLM costs
across different models and verification methods.
"""

from __future__ import annotations

import pytest

from bmad_assist.deep_verify.infrastructure.cost_tracker import (
    MODEL_PRICING,
    CostTracker,
    CostTrackingConfig,
    NoOpCostTracker,
    calculate_cost,
    create_cost_tracker,
    estimate_tokens,
    get_model_pricing,
)

# =============================================================================
# Tests for Cost Calculation Functions
# =============================================================================

class TestCalculateCost:
    """Test suite for calculate_cost function."""

    def test_calculate_cost_haiku(self):
        """Test cost calculation for haiku model."""
        # Haiku: $0.25 per 1M input, $1.25 per 1M output
        cost = calculate_cost(input_tokens=1000, output_tokens=500, model="haiku")

        # Expected: (1000/1M * 0.25) + (500/1M * 1.25) = 0.00025 + 0.000625 = 0.000875
        expected = (1000 / 1_000_000 * 0.25) + (500 / 1_000_000 * 1.25)
        assert cost == pytest.approx(expected, abs=1e-9)

    def test_calculate_cost_opus(self):
        """Test cost calculation for opus model."""
        # Opus: $15.00 per 1M input, $75.00 per 1M output
        cost = calculate_cost(input_tokens=1000, output_tokens=500, model="opus")

        # Expected: (1000/1M * 15) + (500/1M * 75) = 0.015 + 0.0375 = 0.0525
        expected = (1000 / 1_000_000 * 15.0) + (500 / 1_000_000 * 75.0)
        assert cost == pytest.approx(expected, abs=1e-9)

    def test_calculate_cost_zero_tokens(self):
        """Test cost calculation with zero tokens."""
        cost = calculate_cost(input_tokens=0, output_tokens=0, model="haiku")
        assert cost == 0.0

    def test_calculate_cost_unknown_model_uses_default(self):
        """Test that unknown model uses default pricing."""
        cost = calculate_cost(input_tokens=1000, output_tokens=500, model="unknown-model")

        # Default: $1.00 per 1M input, $3.00 per 1M output
        expected = (1000 / 1_000_000 * 1.0) + (500 / 1_000_000 * 3.0)
        assert cost == pytest.approx(expected, abs=1e-9)


class TestGetModelPricing:
    """Test suite for get_model_pricing function."""

    def test_get_known_model_pricing(self):
        """Test getting pricing for known models."""
        pricing = get_model_pricing("haiku")
        assert pricing == (0.25, 1.25)

        pricing = get_model_pricing("opus")
        assert pricing == (15.0, 75.0)

    def test_get_unknown_model_pricing(self):
        """Test getting pricing for unknown model returns defaults."""
        pricing = get_model_pricing("unknown-model-v123")
        assert pricing == (1.0, 3.0)


class TestEstimateTokens:
    """Test suite for estimate_tokens function."""

    def test_estimate_empty_string(self):
        """Test token estimation for empty string."""
        assert estimate_tokens("") == 0

    def test_estimate_english_text(self):
        """Test token estimation for English text."""
        # Rule of thumb: ~4 characters per token
        text = "word " * 100  # 500 characters
        estimated = estimate_tokens(text)
        assert estimated == 125  # 500 / 4

    def test_estimate_short_text(self):
        """Test token estimation for short text."""
        text = "Hello world"
        estimated = estimate_tokens(text)
        assert estimated == 2  # 11 / 4 = 2.75 -> 2


# =============================================================================
# Tests for CostTracker
# =============================================================================

class TestCostTracker:
    """Test suite for CostTracker class."""

    def test_record_call_updates_totals(self):
        """Test that record_call updates totals correctly."""
        tracker = CostTracker()

        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500)

        summary = tracker.get_summary()
        assert summary.total_calls == 1
        assert summary.total_input_tokens == 1000
        assert summary.total_output_tokens == 500
        assert summary.total_tokens == 1500
        assert summary.estimated_cost_usd > 0

    def test_record_call_returns_cost(self):
        """Test that record_call returns the cost of the call."""
        tracker = CostTracker()

        cost = tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500)

        expected_cost = calculate_cost(1000, 500, "haiku")
        assert cost == pytest.approx(expected_cost, abs=1e-9)

    def test_record_call_tracks_by_model(self):
        """Test that record_call tracks costs by model."""
        tracker = CostTracker()

        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500)
        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500)
        tracker.record_call(model="opus", input_tokens=1000, output_tokens=500)

        haiku_cost = tracker.get_model_cost("haiku")
        assert haiku_cost is not None
        assert haiku_cost.calls == 2

        opus_cost = tracker.get_model_cost("opus")
        assert opus_cost is not None
        assert opus_cost.calls == 1

    def test_record_call_tracks_by_method(self):
        """Test that record_call tracks costs by method."""
        tracker = CostTracker()

        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500, method_id="#153")
        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500, method_id="#153")
        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500, method_id="#154")

        method_153_cost = tracker.get_method_cost("#153")
        assert method_153_cost is not None
        assert method_153_cost.calls == 2

        method_154_cost = tracker.get_method_cost("#154")
        assert method_154_cost is not None
        assert method_154_cost.calls == 1

    def test_record_call_without_method(self):
        """Test that record_call works without method_id."""
        tracker = CostTracker()

        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500)

        summary = tracker.get_summary()
        assert summary.total_calls == 1
        # Should not be in by_method since no method_id provided
        assert "unknown" not in summary.by_method

    def test_get_summary_empty_tracker(self):
        """Test get_summary on empty tracker."""
        tracker = CostTracker()

        summary = tracker.get_summary()

        assert summary.total_calls == 0
        assert summary.total_input_tokens == 0
        assert summary.total_output_tokens == 0
        assert summary.total_tokens == 0
        assert summary.estimated_cost_usd == 0.0
        assert summary.by_model == {}
        assert summary.by_method == {}

    def test_get_model_cost_unknown_returns_none(self):
        """Test that get_model_cost returns None for unknown model."""
        tracker = CostTracker()

        assert tracker.get_model_cost("unknown") is None

    def test_get_method_cost_unknown_returns_none(self):
        """Test that get_method_cost returns None for unknown method."""
        tracker = CostTracker()

        assert tracker.get_method_cost("#999") is None

    def test_reset_clears_all_data(self):
        """Test that reset clears all tracking data."""
        tracker = CostTracker()
        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500, method_id="#153")

        assert tracker.get_summary().total_calls == 1

        tracker.reset()

        summary = tracker.get_summary()
        assert summary.total_calls == 0
        assert summary.estimated_cost_usd == 0.0
        assert summary.by_model == {}
        assert summary.by_method == {}

    def test_to_dict_serialization(self):
        """Test that to_dict serializes correctly."""
        tracker = CostTracker()
        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500, method_id="#153")

        data = tracker.to_dict()

        assert data["total_calls"] == 1
        assert data["total_input_tokens"] == 1000
        assert data["total_output_tokens"] == 500
        assert "estimated_cost_usd" in data
        assert "haiku" in data["by_model"]
        assert "#153" in data["by_method"]

    def test_from_dict_deserialization(self):
        """Test that from_dict deserializes correctly."""
        tracker = CostTracker()
        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500, method_id="#153")

        data = tracker.to_dict()
        restored = CostTracker.from_dict(data)

        summary = restored.get_summary()
        assert summary.total_calls == 1
        assert summary.total_input_tokens == 1000
        assert summary.total_output_tokens == 500
        assert "haiku" in summary.by_model
        assert "#153" in summary.by_method


# =============================================================================
# Tests for CostTrackingConfig
# =============================================================================

class TestCostTrackingConfig:
    """Test suite for CostTrackingConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = CostTrackingConfig()

        assert config.enabled is True
        assert config.track_by_method is True
        assert config.track_by_model is True

    def test_disabled_config(self):
        """Test disabled configuration."""
        config = CostTrackingConfig(enabled=False)

        assert config.enabled is False


class TestCostTrackerWithConfig:
    """Test CostTracker with different configurations."""

    def test_tracking_disabled_does_not_record(self):
        """Test that disabled tracker doesn't record calls."""
        config = CostTrackingConfig(enabled=False)
        tracker = CostTracker(config)

        cost = tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500)

        assert cost == 0.0
        assert tracker.get_summary().total_calls == 0

    def test_track_by_model_disabled(self):
        """Test that track_by_model=False skips model tracking."""
        config = CostTrackingConfig(track_by_model=False)
        tracker = CostTracker(config)

        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500)

        summary = tracker.get_summary()
        assert summary.total_calls == 1
        assert "haiku" not in summary.by_model

    def test_track_by_method_disabled(self):
        """Test that track_by_method=False skips method tracking."""
        config = CostTrackingConfig(track_by_method=False)
        tracker = CostTracker(config)

        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500, method_id="#153")

        summary = tracker.get_summary()
        assert summary.total_calls == 1
        assert "#153" not in summary.by_method


# =============================================================================
# Tests for NoOpCostTracker
# =============================================================================

class TestNoOpCostTracker:
    """Test suite for NoOpCostTracker."""

    def test_record_call_returns_zero(self):
        """Test that record_call always returns 0."""
        tracker = NoOpCostTracker()

        cost = tracker.record_call(model="haiku", input_tokens=1000000, output_tokens=1000000)

        assert cost == 0.0

    def test_get_summary_returns_empty(self):
        """Test that get_summary returns empty summary."""
        tracker = NoOpCostTracker()
        tracker.record_call(model="haiku", input_tokens=1000, output_tokens=500)

        summary = tracker.get_summary()

        assert summary.total_calls == 0
        assert summary.estimated_cost_usd == 0.0

    def test_get_model_cost_returns_none(self):
        """Test that get_model_cost always returns None."""
        tracker = NoOpCostTracker()

        assert tracker.get_model_cost("any-model") is None

    def test_get_method_cost_returns_none(self):
        """Test that get_method_cost always returns None."""
        tracker = NoOpCostTracker()

        assert tracker.get_method_cost("#153") is None

    def test_reset_does_nothing(self):
        """Test that reset does nothing."""
        tracker = NoOpCostTracker()

        # Should not raise
        tracker.reset()

    def test_to_dict_returns_empty(self):
        """Test that to_dict returns empty dict."""
        tracker = NoOpCostTracker()

        data = tracker.to_dict()

        assert data == {}


# =============================================================================
# Tests for Factory Function
# =============================================================================

class TestCreateCostTracker:
    """Test suite for create_cost_tracker factory."""

    def test_create_enabled_returns_cost_tracker(self):
        """Test that enabled=True returns CostTracker."""
        tracker = create_cost_tracker(enabled=True)

        assert isinstance(tracker, CostTracker)

    def test_create_disabled_returns_noop(self):
        """Test that enabled=False returns NoOpCostTracker."""
        tracker = create_cost_tracker(enabled=False)

        assert isinstance(tracker, NoOpCostTracker)


# =============================================================================
# Tests for Model Pricing Constants
# =============================================================================

class TestModelPricing:
    """Test suite for MODEL_PRICING constants."""

    def test_all_models_have_two_prices(self):
        """Test that all models have input and output prices."""
        for model, pricing in MODEL_PRICING.items():
            assert len(pricing) == 2
            assert pricing[0] >= 0  # input
            assert pricing[1] >= 0  # output

    def test_haiku_is_cheapest_claude(self):
        """Test that haiku is the cheapest Claude model."""
        haiku_input, haiku_output = MODEL_PRICING["haiku"]

        for model, (input_price, output_price) in MODEL_PRICING.items():
            # Only check Claude models (not GPT models)
            if model.startswith(("claude-", "haiku", "sonnet", "opus")) and model != "haiku":
                assert input_price >= haiku_input, f"{model} is cheaper than haiku"

    def test_opus_is_most_expensive(self):
        """Test that opus is among the most expensive models."""
        opus_input, opus_output = MODEL_PRICING["opus"]

        # Check that opus is more expensive than most models
        expensive_models = [
            model for model, (inp, _) in MODEL_PRICING.items()
            if inp >= opus_input
        ]
        assert "opus" in expensive_models


# =============================================================================
# Integration Tests
# =============================================================================

def test_cost_tracker_integration():
    """Integration test for cost tracking across multiple calls."""
    tracker = CostTracker()

    # Simulate a verification run with multiple methods and models
    tracker.record_call(model="haiku", input_tokens=2000, output_tokens=500, method_id="#153")
    tracker.record_call(model="haiku", input_tokens=2000, output_tokens=800, method_id="#154")
    tracker.record_call(model="haiku", input_tokens=1500, output_tokens=400, method_id="#155")
    tracker.record_call(model="sonnet", input_tokens=3000, output_tokens=1000, method_id="#201")

    summary = tracker.get_summary()

    # Verify totals
    assert summary.total_calls == 4
    assert summary.total_input_tokens == 8500
    assert summary.total_output_tokens == 2700
    assert summary.total_tokens == 11200

    # Verify by_model breakdown
    assert summary.by_model["haiku"].calls == 3
    assert summary.by_model["sonnet"].calls == 1

    # Verify by_method breakdown
    assert summary.by_method["#153"].calls == 1
    assert summary.by_method["#154"].calls == 1
    assert summary.by_method["#155"].calls == 1
    assert summary.by_method["#201"].calls == 1

    # Verify cost is positive
    assert summary.estimated_cost_usd > 0

    # Verify serialization roundtrip
    data = tracker.to_dict()
    restored = CostTracker.from_dict(data)
    restored_summary = restored.get_summary()

    assert restored_summary.total_calls == summary.total_calls
    assert restored_summary.estimated_cost_usd == pytest.approx(
        summary.estimated_cost_usd, abs=1e-9
    )

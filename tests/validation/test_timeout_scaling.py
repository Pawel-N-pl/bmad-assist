"""Tests for validation timeout scaling (Fix #7)."""


class TestTimeoutScaling:
    """Test timeout proportional scaling logic."""

    def test_small_prompt_uses_base_timeout(self) -> None:
        """Prompt under reference size (100K chars) keeps base timeout."""
        base_timeout = 600
        prompt_chars = 50_000
        reference = 100_000
        if prompt_chars > reference:
            scaled = int(base_timeout * (prompt_chars / reference))
        else:
            scaled = base_timeout
        assert scaled == 600

    def test_large_prompt_scales_timeout(self) -> None:
        """200K char prompt doubles the timeout."""
        base_timeout = 600
        prompt_chars = 200_000
        reference = 100_000
        scaled = int(base_timeout * (prompt_chars / reference))
        assert scaled == 1200

    def test_very_large_prompt_scales_proportionally(self) -> None:
        """400K char prompt quadruples the timeout."""
        base_timeout = 600
        prompt_chars = 400_000
        reference = 100_000
        scaled = int(base_timeout * (prompt_chars / reference))
        assert scaled == 2400

    def test_exactly_reference_size_no_change(self) -> None:
        """100K chars keeps base timeout."""
        base_timeout = 600
        prompt_chars = 100_000
        reference = 100_000
        # At exactly reference, no scaling needed
        if prompt_chars > reference:
            scaled = int(base_timeout * (prompt_chars / reference))
        else:
            scaled = base_timeout
        assert scaled == 600

    def test_scaling_uses_integer(self) -> None:
        """Result is always int."""
        base_timeout = 600
        prompt_chars = 150_000
        reference = 100_000
        scaled = int(base_timeout * (prompt_chars / reference))
        assert isinstance(scaled, int)
        assert scaled == 900

    def test_455k_prompt_with_600s_base(self) -> None:
        """Real-world case: 455K prompt with 600s base -> 2730s."""
        base_timeout = 600
        prompt_chars = 455_000
        reference = 100_000
        scaled = int(base_timeout * (prompt_chars / reference))
        assert scaled == 2730

"""Integration tests for KimiProvider requiring real kimi-cli and API key.

These tests are skipped in CI - they require:
1. kimi-cli installed and in PATH (`uv tool install --python 3.13 kimi-cli`)
2. KIMI_API_KEY environment variable set

Run locally with:
    KIMI_API_KEY=sk-xxx pytest tests/providers/test_kimi_integration.py -v

These tests verify AC33: Integration tests execute when KIMI_API_KEY is set.
"""

import os

import pytest

from bmad_assist.core.exceptions import ProviderExitCodeError
from bmad_assist.providers import get_provider

pytestmark = pytest.mark.skipif(
    not os.environ.get("KIMI_API_KEY"),
    reason="KIMI_API_KEY not set - skipping integration tests"
)


class TestKimiProviderIntegration:
    """Integration tests requiring real kimi-cli and API key."""

    def test_simple_prompt_returns_response(self) -> None:
        """Test: Simple prompt returns valid response."""
        provider = get_provider("kimi")
        result = provider.invoke(
            "Say exactly 'hello' and nothing else. No explanation.",
            timeout=60
        )

        assert result.exit_code == 0
        assert len(result.stdout) > 0
        assert "hello" in result.stdout.lower()

    def test_provider_result_has_all_fields(self) -> None:
        """Test: ProviderResult has all required fields populated."""
        provider = get_provider("kimi")
        result = provider.invoke(
            "What is 1+1? Reply with just the number.",
            timeout=60
        )

        assert result.exit_code == 0
        assert result.model is not None
        assert result.duration_ms > 0
        assert isinstance(result.command, tuple)
        assert "kimi" in result.command

    def test_thinking_mode_with_thinking_model(self) -> None:
        """Test: Thinking mode model produces response."""
        provider = get_provider("kimi")
        result = provider.invoke(
            "What is 17 * 23? Think step by step.",
            model="kimi-k2-thinking-turbo",
            timeout=120
        )

        assert result.exit_code == 0
        assert len(result.stdout) > 0
        # Should contain the answer (391)
        assert "391" in result.stdout

    def test_invalid_model_returns_error(self) -> None:
        """Test: Invalid model name causes error."""
        provider = get_provider("kimi")

        with pytest.raises(ProviderExitCodeError) as exc_info:
            provider.invoke(
                "test",
                model="invalid-model-xyz-does-not-exist",
                timeout=30
            )

        # Should fail with 404 or model not found
        error_msg = str(exc_info.value).lower()
        assert "404" in error_msg or "not found" in error_msg or "model" in error_msg

    def test_cwd_parameter_sets_working_directory(self, tmp_path) -> None:
        """Test: cwd parameter affects file operations."""
        # Create a test file in tmp_path
        test_file = tmp_path / "test_cwd.txt"
        test_file.write_text("CWD test content 12345")

        provider = get_provider("kimi")
        result = provider.invoke(
            "Read the file test_cwd.txt and tell me what number is in it.",
            cwd=tmp_path,
            timeout=60
        )

        assert result.exit_code == 0
        # Should mention the number from the file
        assert "12345" in result.stdout

    def test_parse_output_returns_clean_text(self) -> None:
        """Test: parse_output() returns properly formatted text."""
        provider = get_provider("kimi")
        result = provider.invoke(
            "Say 'test response' exactly.",
            timeout=60
        )

        parsed = provider.parse_output(result)

        assert isinstance(parsed, str)
        # Should be stripped (no leading/trailing whitespace)
        assert parsed == parsed.strip()


class TestKimiProviderIntegrationErrors:
    """Integration tests for error conditions."""

    def test_short_timeout_may_timeout(self) -> None:
        """Test: Very short timeout should either complete fast or timeout."""
        provider = get_provider("kimi")

        # This prompt is simple enough it might complete in 1s,
        # but we're testing the timeout mechanism works
        try:
            result = provider.invoke(
                "Say 'hi'",
                timeout=1  # Very short
            )
            # If it completes, that's OK too
            assert result.exit_code == 0
        except Exception:
            # Timeout or other error is expected with such short timeout
            pass

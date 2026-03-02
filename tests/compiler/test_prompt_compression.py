"""Tests for LLM-based prompt compression module."""

from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.compiler.prompt_compression import (
    compress_context_files,
    compress_document,
)


class TestCompressDocument:
    """Tests for compress_document()."""

    def _make_provider(self, stdout: str = "compressed content", exit_code: int = 0):
        """Create a mock provider that returns the given output."""
        provider = MagicMock()
        result = MagicMock()
        result.exit_code = exit_code
        result.stdout = stdout
        result.stderr = ""
        provider.invoke.return_value = result
        return provider

    def test_successful_compression(self):
        """Successful compression returns compressed content and token estimate."""
        provider = self._make_provider("# Compressed\nKey info preserved.")
        content = "# Original\nVery long document. " * 100

        compressed, tokens = compress_document(content, 500, provider, "haiku")

        assert compressed == "# Compressed\nKey info preserved."
        assert tokens > 0
        provider.invoke.assert_called_once()

        # Verify invoke was called with correct kwargs
        call_kwargs = provider.invoke.call_args
        assert call_kwargs.kwargs["model"] == "haiku"
        assert call_kwargs.kwargs["timeout"] == 120
        assert call_kwargs.kwargs["disable_tools"] is True

    def test_provider_failure_raises(self):
        """Provider returning non-zero exit code raises RuntimeError."""
        provider = self._make_provider(exit_code=1)
        provider.invoke.return_value.stderr = "API error"

        with pytest.raises(RuntimeError, match="Compression provider failed"):
            compress_document("content", 500, provider, "haiku")

    def test_empty_response_raises(self):
        """Empty provider response raises RuntimeError."""
        provider = self._make_provider(stdout="   ")

        with pytest.raises(RuntimeError, match="empty content"):
            compress_document("content", 500, provider, "haiku")

    def test_custom_timeout(self):
        """Custom timeout is passed to provider."""
        provider = self._make_provider("compressed")

        compress_document("content", 500, provider, "haiku", timeout=60)

        call_kwargs = provider.invoke.call_args
        assert call_kwargs.kwargs["timeout"] == 60

    def test_prompt_includes_target_tokens(self):
        """Compression prompt includes target token count and char count."""
        provider = self._make_provider("compressed")

        compress_document("content", 500, provider, "haiku")

        prompt_arg = provider.invoke.call_args.args[0]
        assert "500 tokens" in prompt_arg
        assert "2000 characters" in prompt_arg  # 500 * 4


class TestCompressContextFiles:
    """Tests for compress_context_files()."""

    def _make_provider(self, stdout: str = "compressed file content", exit_code: int = 0):
        """Create a mock provider."""
        provider = MagicMock()
        result = MagicMock()
        result.exit_code = exit_code
        result.stdout = stdout
        result.stderr = ""
        provider.invoke.return_value = result
        return provider

    def _make_xml(self, *file_contents: str) -> str:
        """Build a minimal compiled XML prompt with file elements."""
        files = "\n".join(
            f'<file id="f{i}" path="doc{i}.md"><![CDATA[{content}]]></file>'
            for i, content in enumerate(file_contents)
        )
        return f"<compiled-workflow>\n<context>\n{files}\n</context>\n</compiled-workflow>"

    def test_no_compression_needed(self):
        """Returns unchanged XML when already within budget."""
        provider = self._make_provider()
        xml = self._make_xml("short content")

        result, tokens = compress_context_files(xml, 999999, provider, "haiku")

        assert result == xml
        provider.invoke.assert_not_called()

    def test_compresses_large_files(self):
        """Large files are compressed, small files are left alone."""
        provider = self._make_provider("short")
        # Create a large file (>2000 tokens = >8000 chars) and a small file
        large_content = "A" * 10000
        small_content = "B" * 100
        xml = self._make_xml(large_content, small_content)

        result, tokens = compress_context_files(
            xml, 100, provider, "haiku", min_file_tokens=2000
        )

        # Provider should be called once (only for the large file)
        provider.invoke.assert_called_once()
        # Large file content should be replaced
        assert large_content not in result
        assert "short" in result
        # Small file should be preserved
        assert small_content in result

    def test_no_file_elements(self):
        """Returns unchanged XML when no <file> elements found."""
        provider = self._make_provider()
        xml = "<compiled-workflow><instructions>Do stuff</instructions></compiled-workflow>"

        result, tokens = compress_context_files(xml, 10, provider, "haiku")

        assert result == xml
        provider.invoke.assert_not_called()

    def test_skips_small_files(self):
        """Files below min_file_tokens are not compressed."""
        provider = self._make_provider()
        # Content below threshold (500 tokens = 2000 chars)
        small_content = "C" * 1000
        xml = self._make_xml(small_content)

        result, tokens = compress_context_files(
            xml, 10, provider, "haiku", min_file_tokens=2000
        )

        assert result == xml
        provider.invoke.assert_not_called()

    def test_stops_when_within_budget(self):
        """Stops compressing after reaching target tokens."""
        provider = self._make_provider("tiny")

        # Two large files
        large1 = "X" * 10000
        large2 = "Y" * 10000
        xml = self._make_xml(large1, large2)

        # Set target so that compressing just one file is enough.
        # Original XML ~20000+ chars = ~5000+ tokens.
        # After compressing the largest file to "tiny" (4 chars), total drops
        # by ~10000 chars = ~2500 tokens. Target set just below original.
        original_tokens = len(xml) // 4
        # After first compression, tokens drop by ~(10000 - 4) / 4 = ~2500
        target = original_tokens - 2000  # only need to drop one file

        compress_context_files(xml, target, provider, "haiku", min_file_tokens=2000)

        # Should have stopped after first compression brought us under budget
        assert provider.invoke.call_count == 1

    def test_handles_provider_failure_gracefully(self):
        """Provider failure for one file doesn't prevent others from being compressed."""
        call_count = 0
        provider = MagicMock()

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.exit_code = 1  # First call fails
                result.stderr = "API error"
            else:
                result.exit_code = 0
                result.stdout = "compressed"
                result.stderr = ""
            return result

        provider.invoke.side_effect = side_effect

        large1 = "A" * 10000
        large2 = "B" * 10000
        xml = self._make_xml(large1, large2)

        result, tokens = compress_context_files(
            xml, 10, provider, "haiku", min_file_tokens=2000
        )

        # Both files should have been attempted
        assert call_count == 2
        # Second file's content should be replaced
        assert "compressed" in result

    def test_compression_ratio_applied(self):
        """Custom compression_ratio is applied to file targets."""
        provider = self._make_provider("compressed")
        large_content = "D" * 12000  # 3000 tokens

        xml = self._make_xml(large_content)

        compress_context_files(
            xml, 10, provider, "haiku",
            min_file_tokens=2000, compression_ratio=0.3,
        )

        # Check that the prompt passed to compress_document targets 30% of original
        prompt_arg = provider.invoke.call_args.args[0]
        # 3000 * 0.3 = 900 tokens
        assert "900 tokens" in prompt_arg


class TestCompressOrTruncate:
    """Tests for _compress_or_truncate() in strategic_context.py."""

    @patch("bmad_assist.providers.get_provider")
    @patch("bmad_assist.core.config.loaders.get_config")
    def test_compression_enabled_uses_llm(self, mock_get_config, mock_get_provider):
        """When compression is enabled and helper configured, uses LLM."""
        from bmad_assist.compiler.strategic_context import _compress_or_truncate

        # Setup config mock
        config = MagicMock()
        config.compiler.prompt_compression.enabled = True
        config.compiler.prompt_compression.timeout = 120
        config.providers.helper.provider = "claude"
        config.providers.helper.model = "haiku"
        mock_get_config.return_value = config

        # Setup provider mock
        provider = MagicMock()
        result = MagicMock()
        result.exit_code = 0
        result.stdout = "# Compressed content"
        result.stderr = ""
        provider.invoke.return_value = result
        mock_get_provider.return_value = provider

        content = "# Full document\n" + "Long content. " * 500
        compressed, tokens = _compress_or_truncate(content, 500, "ux")

        assert compressed == "# Compressed content"
        provider.invoke.assert_called_once()

    @patch("bmad_assist.core.config.loaders.get_config")
    def test_compression_disabled_uses_truncation(self, mock_get_config):
        """When compression is disabled, falls back to truncation."""
        from bmad_assist.compiler.strategic_context import (
            TRUNCATION_NOTICE,
            _compress_or_truncate,
        )

        config = MagicMock()
        config.compiler.prompt_compression.enabled = False
        mock_get_config.return_value = config

        # Content must be long enough to actually get truncated
        # 200 tokens budget = ~800 chars, content must exceed 880 chars (with 10% overrun)
        content = "# Document\n" + "Content word. " * 200  # ~2800 chars
        result, tokens = _compress_or_truncate(content, 200, "ux")

        assert TRUNCATION_NOTICE in result

    @patch("bmad_assist.providers.get_provider")
    @patch("bmad_assist.core.config.loaders.get_config")
    def test_provider_failure_falls_back_to_truncation(
        self, mock_get_config, mock_get_provider
    ):
        """When LLM compression fails, falls back to truncation."""
        from bmad_assist.compiler.strategic_context import (
            TRUNCATION_NOTICE,
            _compress_or_truncate,
        )

        config = MagicMock()
        config.compiler.prompt_compression.enabled = True
        config.compiler.prompt_compression.timeout = 120
        config.providers.helper.provider = "claude"
        config.providers.helper.model = "haiku"
        mock_get_config.return_value = config

        # Provider raises an error
        mock_get_provider.side_effect = RuntimeError("No connection")

        content = "# Document\n" + "Content word. " * 200
        result, tokens = _compress_or_truncate(content, 200, "ux")

        # Should fall back to truncation
        assert TRUNCATION_NOTICE in result

    @patch("bmad_assist.core.config.loaders.get_config")
    def test_no_helper_provider_falls_back_to_truncation(self, mock_get_config):
        """When no helper provider configured, falls back to truncation."""
        from bmad_assist.compiler.strategic_context import (
            TRUNCATION_NOTICE,
            _compress_or_truncate,
        )

        config = MagicMock()
        config.compiler.prompt_compression.enabled = True
        config.providers.helper = None
        mock_get_config.return_value = config

        content = "# Document\n" + "Content word. " * 200
        result, tokens = _compress_or_truncate(content, 200, "ux")

        assert TRUNCATION_NOTICE in result

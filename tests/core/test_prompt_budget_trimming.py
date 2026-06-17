"""Tests for post-compilation prompt budget trimming (Fix #3 and #6)."""

import logging

from bmad_assist.core.loop.handlers.base import _trim_source_context


def _make_prompt(file_count: int, content_size: int = 1000) -> str:
    """Build a fake compiled prompt XML with file blocks.

    Files are named file_1.py through file_N.py (highest priority first).
    """
    files = []
    for i in range(1, file_count + 1):
        content = "x" * content_size
        files.append(
            f'<file id="f{i}" path="src/file_{i}.py" label="file_{i}">'
            f"<![CDATA[{content}]]></file>"
        )
    context = "<context>\n" + "\n".join(files) + "\n</context>"
    return (
        f"<compiled-workflow>\n<mission>Do something</mission>\n"
        f"{context}\n</compiled-workflow>"
    )


class TestTrimSourceContext:
    """Test _trim_source_context budget enforcement."""

    def test_no_trimming_when_within_budget(self) -> None:
        """Prompt within budget returned unchanged with empty removed/compressed lists."""
        prompt = _make_prompt(3, content_size=100)
        current_tokens = len(prompt) // 4
        budget = current_tokens + 1000  # Well within budget
        result, removed, compressed = _trim_source_context(
            prompt, current_tokens, budget
        )
        assert result == prompt
        assert removed == []
        assert compressed == []

    def test_trims_last_file_when_over_budget(self) -> None:
        """Slightly over budget removes last (lowest priority) file."""
        prompt = _make_prompt(3, content_size=2000)
        current_tokens = len(prompt) // 4
        # Set budget to be less than current but achievable by removing 1 file
        budget = current_tokens - 400  # ~2000/4 = 500 tokens per file
        result, removed, compressed = _trim_source_context(
            prompt, current_tokens, budget
        )
        assert "file_3.py" not in result
        assert "file_1.py" in result
        assert "file_2.py" in result
        assert "src/file_3.py" in removed
        assert compressed == []  # .py files never compressed

    def test_trims_multiple_files_when_significantly_over(self) -> None:
        """Significantly over budget removes multiple lowest-priority files."""
        prompt = _make_prompt(5, content_size=2000)
        current_tokens = len(prompt) // 4
        # Budget achievable only by removing 3+ files
        budget = current_tokens - 1200
        result, removed, _compressed = _trim_source_context(
            prompt, current_tokens, budget
        )
        # file_1 should always survive (highest priority)
        assert "file_1.py" in result
        # At least one file was removed
        assert len(result) < len(prompt)
        assert len(removed) >= 1
        # Lowest-priority files trimmed first (reverse order of source list).
        assert "src/file_5.py" in removed

    def test_preserves_non_source_content(self) -> None:
        """Strategic context and mission are never trimmed."""
        prompt = _make_prompt(3, content_size=2000)
        current_tokens = len(prompt) // 4
        budget = current_tokens - 800
        result, _removed, _compressed = _trim_source_context(
            prompt, current_tokens, budget
        )
        assert "<mission>Do something</mission>" in result
        assert "<compiled-workflow>" in result

    def test_no_crash_on_missing_context(self) -> None:
        """Prompt without any <file> blocks returns unchanged + empty lists."""
        prompt = "<compiled-workflow><mission>test</mission></compiled-workflow>"
        result, removed, compressed = _trim_source_context(prompt, 100, 50)
        assert result == prompt
        assert removed == []
        assert compressed == []

    def test_logs_removed_files(self, caplog) -> None:
        """Each removed file is logged."""
        prompt = _make_prompt(3, content_size=2000)
        current_tokens = len(prompt) // 4
        budget = current_tokens - 800
        with caplog.at_level(logging.INFO):
            _trim_source_context(prompt, current_tokens, budget)
        assert "Budget trim: removed source file" in caplog.text
        assert "Trimmed" in caplog.text

    def test_trim_result_estimates_lower_tokens(self) -> None:
        """After trimming, len(result)//4 should be closer to budget."""
        prompt = _make_prompt(4, content_size=4000)
        current_tokens = len(prompt) // 4
        budget = current_tokens // 2
        result, _removed, _compressed = _trim_source_context(
            prompt, current_tokens, budget
        )
        new_tokens = len(result) // 4
        assert new_tokens < current_tokens

    def test_returns_removed_paths_in_trim_order(self) -> None:
        """Return value's `removed` list reflects the order paths were trimmed.

        Paths are trimmed from the lowest-priority end of the file list,
        so file_N is removed before file_(N-1). Callers (e.g. handler base)
        feed this list into ToolCallGuard so the model can read the trimmed
        files via tool calls without hitting the per-file cap.
        """
        prompt = _make_prompt(4, content_size=2000)
        current_tokens = len(prompt) // 4
        budget = current_tokens - 1200  # forces ~2 trims
        _result, removed, _compressed = _trim_source_context(
            prompt, current_tokens, budget
        )
        assert removed, "expected at least one trim"
        # Lowest-priority (highest index) trimmed first.
        assert removed[0] == "src/file_4.py"
        # All entries are repo-relative paths from the XML path attribute.
        assert all(p.startswith("src/file_") for p in removed)


# =============================================================================
# Markdown compression in budget trim (compression follow-up)
# =============================================================================
#
# Compression delegates to compiler.strategic_context._compress_or_truncate,
# which is fail-safe (no helper provider → truncation, exception → truncation).
# Tests mock it where needed so we don't depend on a live LLM.


from pathlib import Path
from unittest.mock import patch


def _wrap_cdata(content: str) -> str:
    """Match the wrapping done by compiler.output._wrap_cdata."""
    if "]]>" in content:
        parts = content.split("]]>")
        return "<![CDATA[\n\n" + "\n\n]]]]><![CDATA[\n\n".join(parts) + "\n\n]]>"
    return "<![CDATA[\n\n" + content + "\n\n]]>"


def _make_md_prompt(files: list[tuple[str, str]]) -> str:
    """Build a fake prompt with one ``<file>`` block per (path, content) tuple.

    Files appear in the order given; trim iterates them in REVERSE so
    later entries are dropped/compressed first.
    """
    blocks = []
    for i, (path, content) in enumerate(files, start=1):
        label = "markdown" if path.endswith((".md", ".markdown", ".mdx")) else "source"
        blocks.append(
            f'<file id="f{i}" path="{path}" label="{label}">{_wrap_cdata(content)}</file>'
        )
    body = "<context>\n" + "\n".join(blocks) + "\n</context>"
    return f"<compiled-workflow>\n<mission>Test</mission>\n{body}\n</compiled-workflow>"


class TestExtractFileBlockContent:
    """Round-trip helpers for CDATA wrapping."""

    def test_round_trip_simple_content(self) -> None:
        from bmad_assist.core.loop.handlers.base import _extract_file_block_content

        block = '<file id="f1" path="docs/foo.md" label="markdown">' + _wrap_cdata("Hello world") + "</file>"
        assert _extract_file_block_content(block) == "Hello world"

    def test_round_trip_content_with_cdata_close_marker(self) -> None:
        """Content that itself contains ``]]>`` survives the round-trip."""
        from bmad_assist.core.loop.handlers.base import _extract_file_block_content

        original = "Pre]]>Post"
        block = (
            '<file id="f1" path="docs/foo.md" label="markdown">'
            + _wrap_cdata(original)
            + "</file>"
        )
        # Recovered text should match the original (the CDATA split is reversed).
        assert _extract_file_block_content(block) == original

    def test_returns_none_for_malformed_block(self) -> None:
        from bmad_assist.core.loop.handlers.base import _extract_file_block_content

        # Missing closing tag
        assert _extract_file_block_content("<file>incomplete") is None
        # No CDATA wrapping
        assert (
            _extract_file_block_content('<file id="f1" path="x">raw</file>') is None
        )


class TestSanitizeDocTypeFromPath:
    """Cache key derivation."""

    def test_alphanumerics_preserved(self) -> None:
        from bmad_assist.core.loop.handlers.base import _sanitize_doc_type_from_path

        result = _sanitize_doc_type_from_path("docs/api/v1.md")
        assert result == "srcmd-docs-api-v1-md"

    def test_special_chars_collapsed(self) -> None:
        from bmad_assist.core.loop.handlers.base import _sanitize_doc_type_from_path

        result = _sanitize_doc_type_from_path("a/b//c..d")
        # Multiple separators → single dash; no leading/trailing dashes.
        assert "--" not in result
        assert result.startswith("srcmd-")
        assert not result.endswith("-")


class TestMarkdownCompressionInTrim:
    """Markdown files are compressed in place before being dropped."""

    def _patch_compress(self, return_content: str):
        """Patch _compress_or_truncate to return a fixed compressed result."""
        return patch(
            "bmad_assist.compiler.strategic_context._compress_or_truncate",
            return_value=(return_content, len(return_content) // 4),
        )

    def test_markdown_is_compressed_not_dropped(self, tmp_path: Path) -> None:
        """A markdown file over budget gets compressed in place."""
        # Big enough to trip the >= 500 token compression threshold
        big_md_content = "x" * 4000  # ~1000 tokens
        prompt = _make_md_prompt(
            [
                ("src/main.py", "y" * 200),
                ("docs/big.md", big_md_content),
            ]
        )
        current_tokens = len(prompt) // 4
        budget = current_tokens - 500  # forces a trim

        compressed_payload = "compressed summary of big.md"
        with self._patch_compress(compressed_payload):
            result, removed, compressed = _trim_source_context(
                prompt, current_tokens, budget, project_root=tmp_path
            )

        # The markdown file is STILL in the prompt (compressed in place).
        assert "docs/big.md" in result
        assert compressed_payload in result
        # Annotation tells the model it's compressed.
        assert "compressed from" in result
        # Original content is gone (replaced).
        assert big_md_content not in result
        # Tracked as compressed, not removed.
        assert compressed == ["docs/big.md"]
        assert removed == []

    def test_source_code_never_compressed_even_if_eligible_size(
        self, tmp_path: Path
    ) -> None:
        """A .py file over budget is dropped, never compressed."""
        big_py_content = "x" * 4000
        prompt = _make_md_prompt(
            [
                ("src/keep.py", "y" * 200),
                ("src/big.py", big_py_content),
            ]
        )
        current_tokens = len(prompt) // 4
        budget = current_tokens - 500

        with patch(
            "bmad_assist.compiler.strategic_context._compress_or_truncate"
        ) as mock_compress:
            result, removed, compressed = _trim_source_context(
                prompt, current_tokens, budget, project_root=tmp_path
            )

        # Compression must NEVER be attempted for source code.
        mock_compress.assert_not_called()
        assert big_py_content not in result
        assert compressed == []
        assert "src/big.py" in removed

    def test_markdown_dropped_when_compression_no_op(self, tmp_path: Path) -> None:
        """If compression doesn't actually shrink, the file is dropped."""
        big_md = "z" * 4000
        prompt = _make_md_prompt(
            [
                ("src/keep.md", "a" * 200),
                ("docs/noop.md", big_md),
            ]
        )
        current_tokens = len(prompt) // 4
        budget = current_tokens - 500

        # Mock returns content of equal size → no real shrinkage.
        with self._patch_compress(big_md):
            result, removed, compressed = _trim_source_context(
                prompt, current_tokens, budget, project_root=tmp_path
            )

        assert compressed == []
        assert "docs/noop.md" in removed
        assert big_md not in result

    def test_tiny_markdown_skips_compression(self, tmp_path: Path) -> None:
        """Files under MIN_COMPRESSIBLE_TOKENS bypass compression entirely."""
        tiny_md = "tiny"  # << 500 tokens
        prompt = _make_md_prompt(
            [
                ("src/keep.md", "a" * 200),
                ("docs/tiny.md", tiny_md),
            ]
        )
        current_tokens = len(prompt) // 4
        budget = current_tokens - 50  # force trim of tiny.md

        with patch(
            "bmad_assist.compiler.strategic_context._compress_or_truncate"
        ) as mock_compress:
            _result, removed, compressed = _trim_source_context(
                prompt, current_tokens, budget, project_root=tmp_path
            )

        # Tiny → don't even try compressing → drop straight away.
        mock_compress.assert_not_called()
        assert "docs/tiny.md" in removed
        assert compressed == []

    def test_compression_disabled_without_project_root(self) -> None:
        """When project_root=None, markdown files fall through to drop."""
        big_md = "x" * 4000
        prompt = _make_md_prompt(
            [
                ("src/keep.md", "a" * 200),
                ("docs/big.md", big_md),
            ]
        )
        current_tokens = len(prompt) // 4
        budget = current_tokens - 500

        with patch(
            "bmad_assist.compiler.strategic_context._compress_or_truncate"
        ) as mock_compress:
            _result, removed, compressed = _trim_source_context(
                prompt, current_tokens, budget, project_root=None
            )

        # No project_root → no compression attempt → drop fallback.
        mock_compress.assert_not_called()
        assert "docs/big.md" in removed
        assert compressed == []

    def test_mixed_compresses_md_and_drops_source(self, tmp_path: Path) -> None:
        """Mixed prompt: markdown compressed, source code dropped."""
        big_md = "m" * 4000
        big_py = "p" * 4000
        prompt = _make_md_prompt(
            [
                ("src/keep.py", "a" * 200),
                ("docs/info.md", big_md),
                ("src/big.py", big_py),  # last → trimmed first
            ]
        )
        current_tokens = len(prompt) // 4
        # Budget tight enough to force trimming both lower-priority files.
        budget = current_tokens - 1500

        compressed_payload = "summary of info.md"
        with self._patch_compress(compressed_payload):
            result, removed, compressed = _trim_source_context(
                prompt, current_tokens, budget, project_root=tmp_path
            )

        # big.py is dropped (last → first to go).
        assert "src/big.py" in removed
        assert big_py not in result
        # info.md is compressed in place.
        assert "docs/info.md" in compressed
        assert compressed_payload in result
        assert big_md not in result

    def test_compression_failure_falls_back_to_drop(self, tmp_path: Path) -> None:
        """If _compress_or_truncate raises, the file is dropped silently."""
        big_md = "x" * 4000
        prompt = _make_md_prompt(
            [
                ("src/keep.md", "a" * 200),
                ("docs/broken.md", big_md),
            ]
        )
        current_tokens = len(prompt) // 4
        budget = current_tokens - 500

        with patch(
            "bmad_assist.compiler.strategic_context._compress_or_truncate",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            _result, removed, compressed = _trim_source_context(
                prompt, current_tokens, budget, project_root=tmp_path
            )

        assert "docs/broken.md" in removed
        assert compressed == []

    def test_compression_logs_indicate_compression(
        self, tmp_path: Path, caplog
    ) -> None:
        """Compression path emits its own info log distinct from drop."""
        big_md = "x" * 4000
        prompt = _make_md_prompt(
            [
                ("src/keep.md", "a" * 200),
                ("docs/big.md", big_md),
            ]
        )
        current_tokens = len(prompt) // 4
        budget = current_tokens - 500

        with self._patch_compress("smaller"), caplog.at_level(logging.INFO):
            _trim_source_context(
                prompt, current_tokens, budget, project_root=tmp_path
            )

        assert "Budget compress" in caplog.text
        assert "docs/big.md" in caplog.text
        # Summary line should report 1 compressed.
        assert "compressed 1" in caplog.text

    def test_mdx_and_markdown_extensions_recognized(self, tmp_path: Path) -> None:
        """Compression covers .md, .markdown, and .mdx extensions."""
        big = "x" * 4000
        prompt = _make_md_prompt(
            [
                ("a.md", big),
                ("b.markdown", big),
                ("c.mdx", big),
            ]
        )
        current_tokens = len(prompt) // 4
        # Force EVERY file to be considered for trim.
        budget = max(current_tokens // 5, 1)

        with self._patch_compress("tiny"):
            _result, removed, compressed = _trim_source_context(
                prompt, current_tokens, budget, project_root=tmp_path
            )

        # All three extensions must be on the compressed path, not removed.
        assert "a.md" in compressed
        assert "b.markdown" in compressed
        assert "c.mdx" in compressed
        assert removed == []

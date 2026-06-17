"""Tests for the source_context module.

Tests the SourceContextService class and utility functions for
configurable source file collection in workflow compilers.
"""

from pathlib import Path

import pytest

from bmad_assist.compiler.source_context import (
    GitDiffFile,
    ScoredFile,
    SourceContextService,
    _extract_file_list_section,
    extract_file_paths_from_section,
    extract_file_paths_from_story,
    get_git_diff_files,
    is_binary_file,
    safe_read_file,
)
from bmad_assist.compiler.types import CompilerContext
from bmad_assist.core.config import (
    SourceContextBudgetsConfig,
    SourceContextConfig,
    SourceContextExtractionConfig,
    SourceContextScoringConfig,
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project structure for testing."""
    # Create directory structure
    docs = tmp_path / "docs"
    docs.mkdir()

    sprint_artifacts = docs / "sprint-artifacts"
    sprint_artifacts.mkdir()

    src = tmp_path / "src"
    src.mkdir()

    # Create project_context.md
    (docs / "project-context.md").write_text("# Project Context\n")

    return tmp_path


def create_test_context(project: Path) -> CompilerContext:
    """Create a test CompilerContext."""
    return CompilerContext(
        project_root=project,
        output_folder=project / "docs",
        resolved_variables={},
    )


class TestSourceContextBudgetsConfig:
    """Tests for SourceContextBudgetsConfig."""

    def test_default_budgets(self) -> None:
        """Default budgets match tech-spec."""
        config = SourceContextBudgetsConfig()

        assert config.code_review == 15000
        assert config.code_review_synthesis == 5000
        assert config.create_story == 20000
        assert config.dev_story == 20000
        assert config.validate_story == 10000
        assert config.validate_story_synthesis == 10000
        assert config.default == 20000

    def test_get_budget_by_name(self) -> None:
        """get_budget returns correct budget by name."""
        config = SourceContextBudgetsConfig()

        assert config.get_budget("code_review") == 15000
        assert config.get_budget("dev_story") == 20000
        assert config.get_budget("unknown_workflow") == 20000  # Falls back to default

    def test_get_budget_normalizes_hyphens(self) -> None:
        """get_budget handles hyphenated names."""
        config = SourceContextBudgetsConfig()

        assert config.get_budget("code-review") == 15000
        assert config.get_budget("dev-story") == 20000


class TestSourceContextScoringConfig:
    """Tests for SourceContextScoringConfig."""

    def test_default_scoring_weights(self) -> None:
        """Default scoring weights match tech-spec."""
        config = SourceContextScoringConfig()

        assert config.in_file_list == 50
        assert config.in_git_diff == 50
        assert config.is_test_file == -10
        assert config.is_config_file == -5
        assert config.change_lines_factor == 1
        assert config.change_lines_cap == 50


class TestSourceContextExtractionConfig:
    """Tests for SourceContextExtractionConfig."""

    def test_default_extraction_settings(self) -> None:
        """Default extraction settings match tech-spec."""
        config = SourceContextExtractionConfig()

        assert config.adaptive_threshold == 0.25
        assert config.hunk_context_lines == 20
        assert config.hunk_context_scale == 0.3
        assert config.max_files == 15


class TestSourceContextConfig:
    """Tests for SourceContextConfig nested configuration."""

    def test_nested_defaults(self) -> None:
        """Nested configs have correct defaults."""
        config = SourceContextConfig()

        assert config.budgets.code_review == 15000
        assert config.scoring.in_file_list == 50
        assert config.extraction.max_files == 15


class TestExtractFilePathsFromStory:
    """Tests for extract_file_paths_from_story function."""

    def test_extracts_basic_paths(self) -> None:
        """Extracts file paths from standard File List section."""
        story = """# Story 1.1

## File List

- `src/module.py` - Main module
- `tests/test_module.py` - Tests

## Other Section
"""
        paths = extract_file_paths_from_story(story)

        assert len(paths) == 2
        assert "src/module.py" in paths
        assert "tests/test_module.py" in paths

    def test_handles_h3_header(self) -> None:
        """Handles ### File List header."""
        story = """### File List

- `src/file.py`
"""
        paths = extract_file_paths_from_story(story)

        assert len(paths) == 1
        assert "src/file.py" in paths

    def test_handles_paths_without_backticks(self) -> None:
        """Extracts paths without backticks."""
        story = """## File List

- src/plain/path.ts
* tests/another.py
"""
        paths = extract_file_paths_from_story(story)

        assert "src/plain/path.ts" in paths
        assert "tests/another.py" in paths

    def test_numbered_list_format(self) -> None:
        """Numbered lists (1. `file`) are extracted."""
        story = """## File List

1. `src/module.py` - Main module
2. `src/utils.py` - Utility functions

## Other
"""
        paths = extract_file_paths_from_story(story)

        assert len(paths) == 2
        assert "src/module.py" in paths
        assert "src/utils.py" in paths

    def test_table_format(self) -> None:
        """Markdown table entries (| `file` |) are extracted."""
        story = """## File List

| File | Description |
|------|-------------|
| `src/main.py` | Entry point |
| `src/config.py` | Configuration |

## Other
"""
        paths = extract_file_paths_from_story(story)

        assert len(paths) == 2
        assert "src/main.py" in paths
        assert "src/config.py" in paths

    def test_subheaders_within_file_list(self) -> None:
        """Sub-headers (### Modified Files under ## File List) don't terminate section."""
        story = """## File List

### Modified Files
- `src/module.py`

### New Files
- `src/new_module.py`

## Other Section
"""
        paths = extract_file_paths_from_story(story)

        assert len(paths) == 2
        assert "src/module.py" in paths
        assert "src/new_module.py" in paths

    def test_h4_header(self) -> None:
        """#### File List is matched."""
        story = """#### File List

- `src/deep.py`

#### Other
"""
        paths = extract_file_paths_from_story(story)

        assert len(paths) == 1
        assert "src/deep.py" in paths

    def test_mixed_formats(self) -> None:
        """Mix of bullets, numbered, and table entries in same section."""
        story = """## File List

- `src/bullet.py` - From bullet
1. `src/numbered.py` - From numbered
| `src/table.py` | From table |

## Other
"""
        paths = extract_file_paths_from_story(story)

        assert len(paths) == 3
        assert "src/bullet.py" in paths
        assert "src/numbered.py" in paths
        assert "src/table.py" in paths

    def test_returns_empty_for_no_section(self) -> None:
        """Returns empty list when no File List section."""
        story = """# Story

## Implementation
Some code here.
"""
        paths = extract_file_paths_from_story(story)
        assert paths == []


class TestIsBinaryFile:
    """Tests for is_binary_file function."""

    def test_detects_binary_by_extension(self, tmp_path: Path) -> None:
        """Detects binary files by extension."""
        png = tmp_path / "image.png"
        png.write_bytes(b"fake png content")

        assert is_binary_file(png) is True

    def test_detects_binary_by_null_bytes(self, tmp_path: Path) -> None:
        """Detects binary files by null bytes."""
        binary = tmp_path / "data.bin"
        binary.write_bytes(b"some\x00binary\x00data")

        assert is_binary_file(binary) is True

    def test_allows_text_files(self, tmp_path: Path) -> None:
        """Returns False for text files."""
        text = tmp_path / "file.txt"
        text.write_text("hello world")

        assert is_binary_file(text) is False


class TestSourceContextService:
    """Tests for SourceContextService class."""

    def test_initialization_with_defaults(self, tmp_project: Path) -> None:
        """Service initializes with default config when not loaded."""
        context = create_test_context(tmp_project)
        service = SourceContextService(context, "code_review")

        assert service.budget == 15000
        assert service.is_enabled()

    def test_is_enabled_with_low_budget(
        self, tmp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_enabled returns False for budget < 100."""
        # Create custom budgets config with a disabled workflow
        custom_budgets = SourceContextBudgetsConfig(
            code_review=15000,
            code_review_synthesis=15000,
            create_story=20000,
            dev_story=20000,
            validate_story=0,  # Explicitly disabled for this test
            validate_story_synthesis=0,
            default=20000,
        )

        # Patch the service to use our custom budget
        context = create_test_context(tmp_project)
        service = SourceContextService(context, "validate_story")
        monkeypatch.setattr(service, "budget", custom_budgets.validate_story)

        assert service.budget == 0
        assert service.is_enabled() is False

    def test_collect_files_basic(self, tmp_project: Path) -> None:
        """Collects files from File List."""
        src = tmp_project / "src"
        (src / "main.py").write_text("def main():\n    pass")

        context = create_test_context(tmp_project)
        service = SourceContextService(context, "dev_story")

        result = service.collect_files(["src/main.py"], None)

        assert len(result) == 1
        assert "def main():" in list(result.values())[0]

    def test_collect_files_skips_missing(self, tmp_project: Path) -> None:
        """Skips non-existent files."""
        context = create_test_context(tmp_project)
        service = SourceContextService(context, "dev_story")

        result = service.collect_files(["nonexistent.py"], None)

        assert len(result) == 0

    def test_collect_files_skips_binary(self, tmp_project: Path) -> None:
        """Skips binary files."""
        src = tmp_project / "src"
        (src / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        context = create_test_context(tmp_project)
        service = SourceContextService(context, "dev_story")

        result = service.collect_files(["src/image.png"], None)

        assert len(result) == 0

    def test_collect_files_uses_intersection(self, tmp_project: Path) -> None:
        """Uses intersection when both File List and git diff provided."""
        src = tmp_project / "src"
        (src / "in_both.py").write_text("# in both")
        (src / "file_list_only.py").write_text("# file list only")
        (src / "git_only.py").write_text("# git only")

        context = create_test_context(tmp_project)
        service = SourceContextService(context, "code_review")

        file_list = ["src/in_both.py", "src/file_list_only.py"]
        git_diff = [
            GitDiffFile(path="src/in_both.py", change_lines=10, hunk_ranges=[(1, 5)]),
            GitDiffFile(path="src/git_only.py", change_lines=5, hunk_ranges=[(1, 3)]),
        ]

        result = service.collect_files(file_list, git_diff)

        # Only "in_both.py" should be included (intersection)
        assert len(result) == 1
        paths = list(result.keys())
        assert "in_both.py" in paths[0]

    def test_disabled_returns_empty(
        self, tmp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns empty when budget is disabled."""
        src = tmp_project / "src"
        (src / "main.py").write_text("content")

        context = create_test_context(tmp_project)
        service = SourceContextService(context, "dev_story")  # Use any workflow
        # Disable the service by setting budget to 0
        monkeypatch.setattr(service, "budget", 0)

        result = service.collect_files(["src/main.py"], None)

        assert len(result) == 0


class TestScoring:
    """Tests for file scoring logic."""

    def test_file_list_bonus(self, tmp_project: Path) -> None:
        """Files in File List get bonus score."""
        src = tmp_project / "src"
        (src / "a.py").write_text("# file a")
        (src / "b.py").write_text("# file b")

        context = create_test_context(tmp_project)
        service = SourceContextService(context, "dev_story")

        # b.py is in file_list only
        result = service.collect_files(["src/b.py"], None)

        assert len(result) == 1
        assert "b.py" in list(result.keys())[0]

    def test_test_files_penalty(self, tmp_project: Path) -> None:
        """Test files get negative score adjustment."""
        src = tmp_project / "tests"
        src.mkdir()
        (src / "test_main.py").write_text("# test file")

        context = create_test_context(tmp_project)
        service = SourceContextService(context, "dev_story")

        result = service.collect_files(["tests/test_main.py"], None)

        # Still included if only file available
        assert len(result) == 1


class TestTruncation:
    """Tests for content truncation."""

    def test_truncates_large_files(self, tmp_project: Path) -> None:
        """Large files are truncated to fit budget."""
        src = tmp_project / "src"
        large_content = "x" * 200000  # Much larger than default budget
        (src / "large.py").write_text(large_content)

        context = create_test_context(tmp_project)
        service = SourceContextService(context, "code_review")  # 15000 budget

        result = service.collect_files(["src/large.py"], None)

        assert len(result) == 1
        content = list(result.values())[0]
        assert len(content) < len(large_content)
        assert "truncated" in content.lower()


# =============================================================================
# Synthesis source file capping with compression
# =============================================================================
#
# Tests for cap_synthesis_source_files — replaces the old hard-cap-and-drop
# behavior in validate_story_synthesis / code_review_synthesis with
# compression-aware trimming for markdown and drop-only for source code.


from unittest.mock import patch

from bmad_assist.compiler.source_context import (
    SynthesisCapResult,
    cap_synthesis_source_files,
)


class TestCapSynthesisSourceFiles:
    """cap_synthesis_source_files compresses every eligible file."""

    def _patch_compress(self, return_content: str):
        """Mock _compress_or_truncate to return a fixed compressed result."""
        return patch(
            "bmad_assist.compiler.strategic_context._compress_or_truncate",
            return_value=(return_content, max(len(return_content) // 4, 1)),
        )

    # ------------------------------------------------------------------
    # Core behavior: compress all files above threshold, regardless of
    # type and regardless of position in the score order
    # ------------------------------------------------------------------

    def test_all_eligible_files_compressed_including_top_n(
        self, tmp_path: Path
    ) -> None:
        """Every file above the compressibility threshold is compressed.

        This is the key semantic change: synthesis doesn't keep the
        top-N verbatim, it compresses everything because the agent is
        reasoning over reviewer output, not writing code that needs
        byte-exact source.
        """
        big = "x" * 4000  # > 500 token threshold
        files = {
            "src/main.py": big,
            "src/util.py": big,
            "docs/api.md": big,
        }
        with self._patch_compress("compressed body"):
            result = cap_synthesis_source_files(
                files, max_files=5, project_root=tmp_path
            )
        # All three compressed (including the .py files!)
        assert set(result.compressed_paths) == {
            "src/main.py",
            "src/util.py",
            "docs/api.md",
        }
        assert result.dropped_paths == []
        # Every result file contains the compressed body + annotation
        for path, content in result.files.items():
            assert "compressed body" in content
            assert "compressed from" in content
            assert big not in content, f"{path} still contains original content"

    def test_source_code_compressed_in_synthesis_context(
        self, tmp_path: Path
    ) -> None:
        """A .py file over threshold IS compressed (synthesis policy).

        Contrast with the base-handler trim path in dev_story, which
        would drop .py files — synthesis doesn't write code so it's
        safe to summarize.
        """
        big_py = "x" * 4000
        files = {"src/big.py": big_py}
        with self._patch_compress("py summary"):
            result = cap_synthesis_source_files(
                files, max_files=5, project_root=tmp_path
            )
        assert result.compressed_paths == ["src/big.py"]
        assert "py summary" in result.files["src/big.py"]

    def test_tiny_files_pass_through_verbatim(self, tmp_path: Path) -> None:
        """Files below the compressibility threshold are kept as-is.

        LLM round-trip overhead outweighs the token savings for small
        files, so tiny files are included WITHOUT compression.
        """
        tiny_py = "def f(): return 1"
        tiny_md = "# Title\nShort."
        files = {
            "a.py": tiny_py,
            "b.md": tiny_md,
        }
        with patch(
            "bmad_assist.compiler.strategic_context._compress_or_truncate"
        ) as mock_compress:
            result = cap_synthesis_source_files(
                files, max_files=5, project_root=tmp_path
            )
        # No LLM calls for tiny files
        mock_compress.assert_not_called()
        # Both kept verbatim
        assert result.files["a.py"] == tiny_py
        assert result.files["b.md"] == tiny_md
        assert result.compressed_paths == []
        assert result.included_paths == ["a.py", "b.md"]

    def test_mixed_tiny_and_large_files(self, tmp_path: Path) -> None:
        """Small files pass through, large files get compressed."""
        big = "x" * 4000
        tiny = "tiny"
        files = {
            "big.py": big,
            "tiny.py": tiny,
            "big.md": big,
            "tiny.md": tiny,
        }
        with self._patch_compress("summary"):
            result = cap_synthesis_source_files(
                files, max_files=10, project_root=tmp_path
            )
        assert set(result.compressed_paths) == {"big.py", "big.md"}
        assert result.files["tiny.py"] == tiny
        assert result.files["tiny.md"] == tiny

    # ------------------------------------------------------------------
    # max_files still caps the result as an upper bound
    # ------------------------------------------------------------------

    def test_max_files_applied_after_compression(self, tmp_path: Path) -> None:
        """Even with compression, max_files caps the total count.

        Input has 5 files, max_files=3 — the 2 lowest-priority entries
        should be dropped after compression, leaving 3 in the result.
        """
        big = "x" * 4000
        files = {
            "a.py": big,
            "b.py": big,
            "c.py": big,
            "d.py": big,  # overflow
            "e.py": big,  # overflow
        }
        with self._patch_compress("summary"):
            result = cap_synthesis_source_files(
                files, max_files=3, project_root=tmp_path
            )
        assert result.included_paths == ["a.py", "b.py", "c.py"]
        assert set(result.dropped_paths) == {"d.py", "e.py"}
        # Top 3 still compressed
        assert set(result.compressed_paths) == {"a.py", "b.py", "c.py"}

    def test_under_cap_all_compressed_none_dropped(
        self, tmp_path: Path
    ) -> None:
        """If input <= max_files, all files are included (but still compressed)."""
        big = "x" * 4000
        files = {
            "a.py": big,
            "b.md": big,
        }
        with self._patch_compress("summary"):
            result = cap_synthesis_source_files(
                files, max_files=5, project_root=tmp_path
            )
        assert len(result.included_paths) == 2
        assert result.dropped_paths == []
        assert set(result.compressed_paths) == {"a.py", "b.md"}

    def test_order_preserved_through_cap(self, tmp_path: Path) -> None:
        """included_paths reflects the input dict (score ranking)."""
        files = {
            "top.py": "x" * 4000,
            "mid.py": "x" * 4000,
            "low.py": "x" * 4000,
            "drop.py": "x" * 4000,
        }
        with self._patch_compress("s"):
            result = cap_synthesis_source_files(
                files, max_files=3, project_root=tmp_path
            )
        assert result.included_paths == ["top.py", "mid.py", "low.py"]
        assert result.dropped_paths == ["drop.py"]

    # ------------------------------------------------------------------
    # Fallback paths: no compression available, compression no-op, etc.
    # ------------------------------------------------------------------

    def test_project_root_none_falls_back_to_legacy_drop(self) -> None:
        """When project_root is None, no compression → legacy drop behavior.

        This preserves unit-test ergonomics where callers don't want to
        depend on the compression machinery.
        """
        files = {
            "a.py": "x" * 4000,
            "b.py": "y" * 4000,
            "c.py": "z" * 4000,
            "d.py": "w" * 4000,
        }
        with patch(
            "bmad_assist.compiler.strategic_context._compress_or_truncate"
        ) as mock_compress:
            result = cap_synthesis_source_files(
                files, max_files=3, project_root=None
            )
        mock_compress.assert_not_called()
        assert result.compressed_paths == []
        assert result.included_paths == ["a.py", "b.py", "c.py"]
        assert result.dropped_paths == ["d.py"]

    def test_compression_no_op_keeps_file_verbatim(self, tmp_path: Path) -> None:
        """If compression didn't shrink, file stays in result (unchanged).

        Previous policy dropped no-op files; new policy keeps them
        because with the "compress all" approach we haven't lost
        anything by NOT compressing — we still have the original.
        """
        content = "y" * 4000
        files = {"docs/stubborn.md": content}
        with self._patch_compress(content):  # same-size mock = no-op
            result = cap_synthesis_source_files(
                files, max_files=5, project_root=tmp_path
            )
        assert result.compressed_paths == []
        assert result.dropped_paths == []
        assert result.files["docs/stubborn.md"] == content

    def test_compression_failure_keeps_file_verbatim(
        self, tmp_path: Path
    ) -> None:
        """If _compress_or_truncate raises, the file is kept verbatim (not dropped).

        Best-effort compression: a failure on one file shouldn't lose
        the file entirely. The verbatim content is still useful.
        """
        content = "x" * 4000
        files = {"docs/broken.md": content}
        with patch(
            "bmad_assist.compiler.strategic_context._compress_or_truncate",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            result = cap_synthesis_source_files(
                files, max_files=5, project_root=tmp_path
            )
        assert result.compressed_paths == []
        assert result.dropped_paths == []
        assert result.files["docs/broken.md"] == content

    def test_compression_logs_info_line(
        self, tmp_path: Path, caplog
    ) -> None:
        """Successful compression emits an info log."""
        import logging

        big_md = "x" * 4000
        files = {"docs/big.md": big_md}
        with self._patch_compress("short"), caplog.at_level(logging.INFO):
            cap_synthesis_source_files(
                files, max_files=3, project_root=tmp_path
            )
        assert "Synthesis compress" in caplog.text
        assert "docs/big.md" in caplog.text

    # ------------------------------------------------------------------
    # Validation / edge cases
    # ------------------------------------------------------------------

    def test_negative_max_files_raises(self, tmp_path: Path) -> None:
        """max_files must be non-negative."""
        with pytest.raises(ValueError, match="max_files"):
            cap_synthesis_source_files(
                {"a.py": "x"}, max_files=-1, project_root=tmp_path
            )

    def test_zero_max_files_drops_everything(self, tmp_path: Path) -> None:
        """max_files=0 drops all files regardless of type."""
        files = {
            "a.py": "x" * 4000,
            "b.md": "y" * 4000,
        }
        with self._patch_compress("tiny"):
            result = cap_synthesis_source_files(
                files, max_files=0, project_root=tmp_path
            )
        assert result.included_paths == []
        assert set(result.dropped_paths) == {"a.py", "b.md"}

    def test_compressed_then_dropped_not_in_compressed_list(
        self, tmp_path: Path
    ) -> None:
        """A file compressed but then dropped by max_files is NOT listed as compressed.

        ``compressed_paths`` is a subset of ``included_paths`` — if we
        paid the LLM cost but then had to drop the file anyway because
        of max_files, that path appears in ``dropped_paths`` only.
        """
        big = "x" * 4000
        files = {
            "top.py": big,
            "mid.py": big,
            "low.py": big,
            "overflow.py": big,  # gets compressed then dropped
        }
        with self._patch_compress("summary"):
            result = cap_synthesis_source_files(
                files, max_files=3, project_root=tmp_path
            )
        assert "overflow.py" not in result.compressed_paths
        assert "overflow.py" in result.dropped_paths
        assert set(result.compressed_paths) == {"top.py", "mid.py", "low.py"}

    def test_isinstance_result_type(self, tmp_path: Path) -> None:
        """Result is a SynthesisCapResult dataclass."""
        result = cap_synthesis_source_files(
            {}, max_files=3, project_root=tmp_path
        )
        assert isinstance(result, SynthesisCapResult)
        assert result.files == {}
        assert result.included_paths == []
        assert result.compressed_paths == []
        assert result.dropped_paths == []

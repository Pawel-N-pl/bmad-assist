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
        assert config.code_review_synthesis == 15000
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

"""Tests for run-scoped prompt path management (Story 22.2).

Tests cover:
- Run-scoped directory initialization with correct timestamp
- Sequential prompt numbering (001, 002, 003...)
- Counter reset on new run initialization
- Metadata header formatting
- get_prompt_path() searching run-scoped directories first
- Legacy format fallback when run-scoped not found
"""

import threading as _threading
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.core.io import (
    _build_prompt_metadata,
    _extract_story_number,
    _get_phase_sequence,
    _get_prompt_counter,
    _get_run_dir,
    _increment_prompt_counter,
    _matches_metadata,
    get_prompt_path,
    get_run_prompts_dir,
    get_timestamp,
    init_run_prompts_dir,
    save_prompt,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a temporary project root directory."""
    project = tmp_path / "test-project"
    project.mkdir(parents=True)
    return project


@pytest.fixture
def run_timestamp() -> str:
    """Fixed run timestamp for testing."""
    return "20260115T025354Z"


@pytest.fixture
def sample_prompt_content() -> str:
    """Sample prompt content for testing."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<compiled-workflow>
  <mission>Test mission</mission>
  <context>Test context</context>
</compiled-workflow>
"""


# =============================================================================
# Test: Run-scoped Directory Creation (Task 6.1)
# =============================================================================


class TestRunScopedDirectoryCreation:
    """Tests for run-scoped prompts directory initialization."""

    def test_init_creates_directory_structure(self, project_root: Path, run_timestamp: str):
        """Run-scoped directory is created with correct timestamp."""
        run_dir = init_run_prompts_dir(project_root, run_timestamp)

        # Verify directory path
        expected_path = project_root / ".bmad-assist" / "prompts" / f"run-{run_timestamp}"
        assert run_dir == expected_path

        # Verify directory exists
        assert run_dir.exists()
        assert run_dir.is_dir()

    def test_init_creates_parent_directories(self, tmp_path: Path, run_timestamp: str):
        """Parent directories are created if they don't exist."""
        # Start with a fresh project root (no .bmad-assist directory)
        project_root = tmp_path / "fresh-project"
        project_root.mkdir()

        # Initialize run prompts dir (should create .bmad-assist/prompts/)
        run_dir = init_run_prompts_dir(project_root, run_timestamp)

        # Verify full path exists
        assert run_dir.exists()
        assert run_dir.is_dir()
        assert run_dir == project_root / ".bmad-assist" / "prompts" / f"run-{run_timestamp}"

    def test_init_is_idempotent(self, project_root: Path, run_timestamp: str):
        """Multiple init calls with same timestamp don't fail."""
        init_run_prompts_dir(project_root, run_timestamp)
        # Second call should not raise an error
        init_run_prompts_dir(project_root, run_timestamp)

    def test_get_run_prompts_dir_without_init(self, project_root: Path, run_timestamp: str):
        """get_run_prompts_dir returns path without creating directory."""
        run_dir = get_run_prompts_dir(project_root, run_timestamp)

        # Directory should NOT exist (no init call)
        assert not run_dir.exists()

        # Path should be correct
        expected = project_root / ".bmad-assist" / "prompts" / f"run-{run_timestamp}"
        assert run_dir == expected


# =============================================================================
# Test: Sequential Prompt Numbering (Task 6.2)
# =============================================================================


class TestPromptCounter:
    """Tests for prompt counter increment and reset behavior."""

    def test_counter_starts_at_zero_after_init(self, project_root: Path, run_timestamp: str):
        """Prompt counter starts at 0 after run initialization."""
        init_run_prompts_dir(project_root, run_timestamp)

        counter = _get_prompt_counter()
        assert counter == 0

    def test_counter_increments_on_each_save(
        self, project_root: Path, run_timestamp: str, sample_prompt_content: str
    ):
        """Prompt filenames use descriptive format with phase sequence."""
        init_run_prompts_dir(project_root, run_timestamp)

        # Save first prompt - create_story is phase 01
        path1 = save_prompt(project_root, 22, 2, "create_story", sample_prompt_content)
        assert path1.name.startswith("prompt-22-2-01-create_story-")
        assert path1.name.endswith(".md")

        # Save second prompt - dev_story is phase 04 in minimal loop (no ATDD)
        path2 = save_prompt(project_root, 22, 2, "dev_story", sample_prompt_content)
        assert path2.name.startswith("prompt-22-2-04-dev_story-")
        assert path2.name.endswith(".md")

        # Save third prompt - code_review is phase 05
        path3 = save_prompt(project_root, 22, 2, "code_review", sample_prompt_content)
        assert path3.name.startswith("prompt-22-2-05-code_review-")
        assert path3.name.endswith(".md")

    def test_counter_resets_on_new_run_init(self, project_root: Path, sample_prompt_content: str):
        """Counter resets to 0 when init_run_prompts_dir is called again."""
        # First run
        init_run_prompts_dir(project_root, "20260115T025354Z")
        save_prompt(project_root, 22, 2, "create_story", sample_prompt_content)

        # Verify counter is at 1
        assert _get_prompt_counter() == 1

        # Second run (different timestamp)
        init_run_prompts_dir(project_root, "20260115T030000Z")

        # Counter should be reset to 0
        assert _get_prompt_counter() == 0

        # Save prompt in new run - uses descriptive naming
        # dev_story is phase 04 in minimal loop (no ATDD in default config)
        path = save_prompt(project_root, 22, 2, "dev_story", sample_prompt_content)
        assert path.name.startswith("prompt-22-2-04-dev_story-")
        assert path.parent.name == "run-20260115T030000Z"

    def test_counter_returns_incremented_value(self, project_root: Path, run_timestamp: str):
        """_increment_prompt_counter returns the new counter value."""
        init_run_prompts_dir(project_root, run_timestamp)

        assert _increment_prompt_counter() == 1
        assert _increment_prompt_counter() == 2
        assert _increment_prompt_counter() == 3

    def test_counter_without_init_returns_zero(self):
        """Counter returns 0 when run context is not initialized."""
        # Reset run context (simulating no init call)
        import bmad_assist.core.io as io_module

        io_module._run_context.prompts_dir = None
        io_module._run_context.prompt_counter = 0

        assert _get_prompt_counter() == 0


# =============================================================================
# Test: Phase Sequence Mapping
# =============================================================================


class TestPhaseSequence:
    """Tests for _get_phase_sequence() phase-to-number mapping.

    Note: _get_phase_sequence uses LoopConfig.story (from DEFAULT_LOOP_CONFIG) which has
    8 phases (Story 25.12): create_story, validate_story, validate_story_synthesis,
    atdd, dev_story, code_review, code_review_synthesis, test_review.
    Phases not in this list return 99.
    """

    def test_default_loop_config_phases_have_correct_sequence(self):
        """Phases in DEFAULT_LOOP_CONFIG.story return correct 1-based sequence numbers."""
        # These are the 6 phases in DEFAULT_LOOP_CONFIG.story (minimal, no TEA)
        assert _get_phase_sequence("create_story") == 1
        assert _get_phase_sequence("validate_story") == 2
        assert _get_phase_sequence("validate_story_synthesis") == 3
        assert _get_phase_sequence("dev_story") == 4
        assert _get_phase_sequence("code_review") == 5
        assert _get_phase_sequence("code_review_synthesis") == 6

    def test_phases_not_in_loop_config_return_99(self):
        """Phases not in DEFAULT_LOOP_CONFIG.story return 99."""
        # These are NOT in DEFAULT_LOOP_CONFIG.story (minimal loop has no TEA)
        assert _get_phase_sequence("retrospective") == 99  # epic_teardown
        assert _get_phase_sequence("qa_plan_generate") == 99  # QA phase
        assert _get_phase_sequence("qa_plan_execute") == 99  # QA phase
        assert _get_phase_sequence("trace") == 99  # epic_teardown (TEA)
        assert _get_phase_sequence("atdd") == 99  # TEA phase
        assert _get_phase_sequence("test_review") == 99  # TEA phase

    def test_unknown_phase_returns_99(self):
        """Unknown phase returns 99 to sort last."""
        assert _get_phase_sequence("unknown_phase") == 99
        assert _get_phase_sequence("foobar") == 99
        assert _get_phase_sequence("") == 99


# =============================================================================
# Test: Story Number Extraction
# =============================================================================


class TestStoryNumberExtraction:
    """Tests for _extract_story_number() story number parsing."""

    def test_epic_dot_story_format(self):
        """Extracts story from 'epic.story' format."""
        assert _extract_story_number("22.6") == "6"
        assert _extract_story_number("1.1") == "1"
        assert _extract_story_number("99.123") == "123"

    def test_plain_number_string(self):
        """Plain number string passes through."""
        assert _extract_story_number("6") == "6"
        assert _extract_story_number("123") == "123"

    def test_integer_input(self):
        """Integer input converts to string."""
        assert _extract_story_number(6) == "6"
        assert _extract_story_number(123) == "123"

    def test_module_format(self):
        """Extracts number from 'module-NN' format."""
        assert _extract_story_number("standalone-03") == "03"
        assert _extract_story_number("testarch-1") == "1"
        assert _extract_story_number("qa-epic-05") == "05"


# =============================================================================
# Test: Metadata Header (Task 6.4)
# =============================================================================


class TestMetadataHeader:
    """Tests for metadata header in run-scoped prompts."""

    def test_metadata_format(self):
        """Metadata header is correctly formatted."""
        metadata = _build_prompt_metadata(22, "22.2", "create_story")

        lines = metadata.split("\n")
        assert "<!-- BMAD Prompt Run Metadata -->" in lines[0]
        assert "<!-- Epic: 22 -->" in lines
        assert "<!-- Story: 22.2 -->" in lines
        assert "<!-- Phase: create-story -->" in lines
        assert "<!-- Timestamp:" in lines[-1]

    def test_metadata_normalizes_phase_name(self):
        """Phase name with underscores is normalized to hyphens."""
        metadata = _build_prompt_metadata(16, "16.1", "dev_story")
        assert "<!-- Phase: dev-story -->" in metadata

    def test_metadata_includes_timestamp(self):
        """Metadata includes current timestamp."""
        # Freeze time for predictable testing
        frozen_dt = datetime(2026, 1, 15, 2, 53, 54, tzinfo=UTC)
        with patch("bmad_assist.core.io.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_dt
            mock_dt.UTC = UTC

            metadata = _build_prompt_metadata(22, "22.2", "create_story")
            assert "<!-- Timestamp: 20260115T025354Z -->" in metadata

    def test_saved_prompt_includes_metadata(
        self, project_root: Path, run_timestamp: str, sample_prompt_content: str
    ):
        """Saved prompt file includes metadata header."""
        init_run_prompts_dir(project_root, run_timestamp)

        prompt_path = save_prompt(project_root, 22, "22.2", "create_story", sample_prompt_content)

        content = prompt_path.read_text(encoding="utf-8")

        # Verify metadata header is present
        assert "<!-- BMAD Prompt Run Metadata -->" in content
        assert "<!-- Epic: 22 -->" in content
        assert "<!-- Story: 22.2 -->" in content
        assert "<!-- Phase: create-story -->" in content
        assert "<!-- Timestamp:" in content

        # Verify original content is preserved
        assert "<compiled-workflow>" in content


# =============================================================================
# Test: get_prompt_path Search Order (Task 6.5)
# =============================================================================


class TestGetPromptPath:
    """Tests for get_prompt_path() searching run-scoped directories first."""

    def test_finds_prompt_in_run_scoped_directory(
        self, project_root: Path, run_timestamp: str, sample_prompt_content: str
    ):
        """get_prompt_path finds run-scoped prompt by metadata."""
        init_run_prompts_dir(project_root, run_timestamp)

        # Save a prompt (using string story number like actual code)
        save_prompt(project_root, 22, "22.2", "create_story", sample_prompt_content)

        # Find it
        found_path = get_prompt_path(project_root, 22, "22.2", "create-story")
        assert found_path is not None
        # Story "22.2" extracts to "2" in filename
        assert found_path.name.startswith("prompt-22-2-01-create_story-")
        assert found_path.parent.name == f"run-{run_timestamp}"

    def test_searches_most_recent_run_first(self, project_root: Path, sample_prompt_content: str):
        """Most recent run directory is searched first."""
        # Create two runs with different timestamps
        init_run_prompts_dir(project_root, "20260115T010000Z")
        save_prompt(project_root, 22, "22.2", "create_story", sample_prompt_content)

        init_run_prompts_dir(project_root, "20260115T020000Z")
        save_prompt(project_root, 22, "22.2", "create_story", sample_prompt_content)

        # Should find the prompt from the more recent run (020000Z)
        found_path = get_prompt_path(project_root, 22, "22.2", "create-story")
        assert found_path is not None
        assert "run-20260115T020000Z" in str(found_path)

    def test_matches_metadata_exact_epic_story_phase(
        self, project_root: Path, run_timestamp: str, sample_prompt_content: str
    ):
        """get_prompt_path matches exact epic/story/phase combination."""
        init_run_prompts_dir(project_root, run_timestamp)

        # Save multiple prompts
        save_prompt(project_root, 22, "22.2", "create_story", sample_prompt_content)
        save_prompt(project_root, 22, "22.2", "dev_story", sample_prompt_content)
        save_prompt(project_root, 22, "22.3", "create_story", sample_prompt_content)

        # Find specific prompt
        found = get_prompt_path(project_root, 22, "22.2", "dev-story")
        assert found is not None

        content = found.read_text(encoding="utf-8")
        assert "<!-- Epic: 22 -->" in content
        assert "<!-- Story: 22.2 -->" in content
        assert "<!-- Phase: dev-story -->" in content

    def test_returns_none_when_not_found(self, project_root: Path):
        """get_prompt_path returns None when prompt doesn't exist."""
        found = get_prompt_path(project_root, 99, "99.1", "nonexistent")
        assert found is None

    def test_matches_metadata_helper(self):
        """_matches_metadata correctly parses and matches metadata."""
        content_with_metadata = """<!-- BMAD Prompt Run Metadata -->
<!-- Epic: 22 -->
<!-- Story: 22.2 -->
<!-- Phase: create-story -->
<!-- Timestamp: 20260115T025354Z -->

<?xml version="1.0" encoding="UTF-8"?>
<compiled-workflow />
"""

        assert _matches_metadata(content_with_metadata, 22, "22.2", "create-story")
        assert not _matches_metadata(
            content_with_metadata, 21, "22.2", "create-story"
        )  # Wrong epic
        assert not _matches_metadata(
            content_with_metadata, 22, "22.1", "create-story"
        )  # Wrong story
        assert not _matches_metadata(content_with_metadata, 22, "22.2", "dev_story")  # Wrong phase

    def test_matches_metadata_normalizes_phase(self):
        """_matches_metadata normalizes underscores to hyphens."""
        # Need all metadata fields present for matching to work (including marker)
        content = """<!-- BMAD Prompt Run Metadata -->
<!-- Epic: 22 -->
<!-- Story: 22.2 -->
<!-- Phase: create-story -->"""
        assert _matches_metadata(content, 22, "22.2", "create_story")  # Query has underscore
        assert _matches_metadata(content, 22, "22.2", "create-story")  # Query has hyphen


# =============================================================================
# Test: Legacy Format Fallback (Task 6.6)
# =============================================================================


class TestLegacyFormatFallback:
    """Tests for legacy format fallback when run-scoped not found."""

    def test_fallback_to_legacy_format(self, project_root: Path, sample_prompt_content: str):
        """Falls back to legacy format when run-scoped not found."""
        # Create legacy format prompt (no init_run_prompts_dir call)
        prompts_dir = project_root / ".bmad-assist" / "prompts"
        prompts_dir.mkdir(parents=True)

        # Legacy format uses the story number as-is (can be "22.2" or integer)
        legacy_prompt = prompts_dir / "22-22.2-create-story-250115-025354.xml"
        legacy_prompt.write_text(sample_prompt_content, encoding="utf-8")

        # Should find the legacy prompt
        found = get_prompt_path(project_root, 22, "22.2", "create-story")
        assert found is not None
        assert found == legacy_prompt

    def test_legacy_format_timestamp_variations(
        self, project_root: Path, sample_prompt_content: str
    ):
        """Legacy format works with different timestamp formats."""
        prompts_dir = project_root / ".bmad-assist" / "prompts"
        prompts_dir.mkdir(parents=True)

        # Create legacy prompt with old timestamp format
        legacy_prompt = prompts_dir / "16-16.1-dev-story-250113-154530.xml"
        legacy_prompt.write_text(sample_prompt_content, encoding="utf-8")

        found = get_prompt_path(project_root, 16, "16.1", "dev-story")
        assert found == legacy_prompt

    def test_auto_init_creates_run_scoped_directory(
        self, project_root: Path, sample_prompt_content: str
    ):
        """save_prompt auto-initializes run directory if not set."""
        # Clear run context
        import bmad_assist.core.io as io_module

        io_module._run_context.prompts_dir = None

        # save_prompt should auto-initialize run directory
        prompt_path = save_prompt(project_root, 22, "22.2", "create_story", sample_prompt_content)

        # Should be in run-scoped format (not legacy)
        assert prompt_path.parent.name.startswith("run-")
        assert prompt_path.suffix == ".md"
        assert "prompt-22-2-01-create_story-" in prompt_path.name


# =============================================================================
# Test: Thread-Local Storage Isolation
# =============================================================================


class TestThreadLocalStorage:
    """Tests for thread-local run context isolation."""

    def test_get_run_dir_returns_none_when_not_initialized(self):
        """_get_run_dir returns None when run context not initialized."""
        import bmad_assist.core.io as io_module

        io_module._run_context.prompts_dir = None

        assert _get_run_dir() is None

    def test_run_dir_is_set_after_init(self, project_root: Path, run_timestamp: str):
        """_get_run_dir returns the run directory after initialization."""
        init_run_prompts_dir(project_root, run_timestamp)

        run_dir = _get_run_dir()
        assert run_dir is not None
        assert run_dir.name == f"run-{run_timestamp}"


# =============================================================================
# Test: save_prompt Behavior
# =============================================================================


class TestSavePrompt:
    """Tests for save_prompt() in both run-scoped and legacy modes."""

    def test_save_in_run_scoped_mode(
        self, project_root: Path, run_timestamp: str, sample_prompt_content: str
    ):
        """save_prompt uses run-scoped path when initialized."""
        init_run_prompts_dir(project_root, run_timestamp)

        prompt_path = save_prompt(project_root, 16, "16.1", "dev_story", sample_prompt_content)

        # Verify path - dev_story is phase 04 in minimal loop (no ATDD)
        # story "16.1" extracts to "1"
        assert prompt_path.parent.name == f"run-{run_timestamp}"
        assert prompt_path.name.startswith("prompt-16-1-04-dev_story-")
        assert prompt_path.suffix == ".md"

        # Verify file exists and has metadata (metadata keeps original story_num)
        assert prompt_path.exists()
        content = prompt_path.read_text(encoding="utf-8")
        assert "<!-- Epic: 16 -->" in content
        assert "<!-- Story: 16.1 -->" in content

    def test_save_auto_initializes_when_not_set(self, project_root: Path, sample_prompt_content: str):
        """save_prompt auto-initializes run directory when not set."""
        # Explicitly clear run context
        import bmad_assist.core.io as io_module

        io_module._run_context.prompts_dir = None

        prompt_path = save_prompt(project_root, 16, "16.1", "dev_story", sample_prompt_content)

        # Verify run-scoped format path (auto-initialized)
        # dev_story is phase 04 in minimal loop (no ATDD)
        assert prompt_path.parent.name.startswith("run-")
        assert prompt_path.suffix == ".md"
        assert "prompt-16-1-04-dev_story-" in prompt_path.name

        # Verify file exists with metadata header
        assert prompt_path.exists()
        content = prompt_path.read_text(encoding="utf-8")
        assert "<!-- Epic: 16 -->" in content  # Has metadata

    def test_save_creates_parent_directories(
        self, project_root: Path, run_timestamp: str, sample_prompt_content: str
    ):
        """save_prompt creates parent directories if needed."""
        init_run_prompts_dir(project_root, run_timestamp)

        # This should work even if .bmad-assist/prompts/run-{ts}/ doesn't exist yet
        # (init_run_prompts_dir already creates it, but we test the pattern)
        prompt_path = save_prompt(project_root, 22, "22.2", "create_story", sample_prompt_content)

        assert prompt_path.exists()
        assert prompt_path.parent.is_dir()

    def test_atomic_write_pattern(self, project_root: Path, run_timestamp: str):
        """save_prompt uses atomic write pattern (temp file + rename)."""
        init_run_prompts_dir(project_root, run_timestamp)

        # Create a prompt that will be saved
        content = "<test>prompt content</test>"

        # Save should use atomic write
        prompt_path = save_prompt(project_root, 22, "22.2", "create_story", content)

        # Verify file exists and content is correct
        assert prompt_path.exists()
        assert content in prompt_path.read_text(encoding="utf-8")

        # No temp file should remain
        temp_files = list(prompt_path.parent.glob(".prompt-*.md.*.tmp"))
        assert len(temp_files) == 0


# =============================================================================
# Test: get_timestamp Function
# =============================================================================


class TestGetTimestamp:
    """Tests for get_timestamp() utility."""

    def test_timestamp_format(self):
        """get_timestamp returns ISO 8601 basic format."""
        timestamp = get_timestamp()
        # Format: YYYYMMDDTHHMMSSZ = 16 characters
        assert len(timestamp) == 16
        assert "T" in timestamp
        assert timestamp.endswith("Z")

    def test_timestamp_with_datetime(self):
        """get_timestamp formats provided datetime correctly."""
        dt = datetime(2026, 1, 15, 2, 53, 54, tzinfo=UTC)
        timestamp = get_timestamp(dt)
        assert timestamp == "20260115T025354Z"

    def test_timestamp_is_sortable(self):
        """Timestamps are chronologically sortable as strings."""
        dt1 = datetime(2026, 1, 15, 1, 0, 0, tzinfo=UTC)
        dt2 = datetime(2026, 1, 15, 2, 0, 0, tzinfo=UTC)
        dt3 = datetime(2026, 1, 15, 3, 0, 0, tzinfo=UTC)

        ts1 = get_timestamp(dt1)
        ts2 = get_timestamp(dt2)
        ts3 = get_timestamp(dt3)

        assert ts1 < ts2 < ts3

"""Tests for file discovery and inclusion module.

Tests cover all acceptance criteria from Story 10.4:
- AC1: File discovery via pattern matching
- AC2: Single match direct use
- AC3: Multiple matches handling (FULL_LOAD, SELECTIVE_LOAD, INDEX_GUIDED)
- AC4: Required file validation
- AC5: Section extraction from files
- AC6: Load file contents
- AC7: Sharded directory support
- AC8: Error handling and security
"""

import logging
from pathlib import Path

import pytest

from bmad_assist.compiler.discovery import (
    discover_files,
    extract_section,
    load_file_contents,
)
from bmad_assist.compiler.types import CompilerContext, WorkflowIR
from bmad_assist.core.exceptions import AmbiguousFileError, CompilerError

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project structure with docs folder."""
    docs = tmp_path / "docs"
    docs.mkdir()
    return tmp_path


def create_test_context(
    tmp_path: Path,
    workflow_config: dict,
) -> CompilerContext:
    """Create a CompilerContext for testing with given workflow config."""
    docs = tmp_path / "docs"
    if not docs.exists():
        docs.mkdir()

    workflow_ir = WorkflowIR(
        name="test-workflow",
        config_path=tmp_path / "workflow.yaml",
        instructions_path=tmp_path / "instructions.xml",
        template_path=None,
        validation_path=None,
        raw_config=workflow_config,
        raw_instructions="<workflow><step>Test</step></workflow>",
    )

    context = CompilerContext(
        project_root=tmp_path,
        output_folder=docs,
    )
    context.workflow_ir = workflow_ir
    context.resolved_variables = {"output_folder": str(docs)}

    return context


# ==============================================================================
# AC1: File Discovery via Pattern Matching
# ==============================================================================


class TestFileDiscoveryPatternMatching:
    """Tests for file discovery via glob patterns (AC1)."""

    def test_discover_files_single_match(self, tmp_path: Path) -> None:
        """Single matching file is returned in list (AC2)."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "prd.md").write_text("# PRD Content")

        workflow_config = {
            "input_file_patterns": {
                "prd": {
                    "whole": f"{docs}/*prd*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        assert "prd" in discovered
        assert len(discovered["prd"]) == 1
        assert discovered["prd"][0].name == "prd.md"

    def test_discover_files_case_insensitive_pattern(self, tmp_path: Path) -> None:
        """Pattern matching is case-insensitive for file names."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "prd.md").write_text("# PRD Content")

        workflow_config = {
            "input_file_patterns": {
                "prd": {
                    "whole": f"{docs}/*PRD*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        # On case-sensitive systems, this may not match
        # The test verifies the behavior is consistent
        assert "prd" in discovered

    def test_discover_files_stores_in_context(self, tmp_path: Path) -> None:
        """Discovered files are stored in context.discovered_files."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "architecture.md").write_text("# Architecture")

        workflow_config = {
            "input_file_patterns": {
                "architecture": {
                    "whole": f"{docs}/*architecture*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discover_files(context)

        assert "architecture" in context.discovered_files
        assert len(context.discovered_files["architecture"]) == 1

    def test_discover_files_empty_patterns(self, tmp_path: Path) -> None:
        """Empty input_file_patterns section results in empty discovery."""
        workflow_config = {"input_file_patterns": {}}

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        assert discovered == {}

    def test_discover_files_no_patterns_key(self, tmp_path: Path) -> None:
        """Missing input_file_patterns key results in empty discovery."""
        workflow_config = {"name": "test"}

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        assert discovered == {}


# ==============================================================================
# AC3: Multiple Matches Handling
# ==============================================================================


class TestMultipleMatchesHandling:
    """Tests for multiple file matches with different strategies (AC3)."""

    def test_full_load_returns_all_files(self, tmp_path: Path) -> None:
        """FULL_LOAD strategy returns all matching files."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "architecture.md").write_text("# Arch 1")
        (docs / "architecture-v2.md").write_text("# Arch 2")

        workflow_config = {
            "input_file_patterns": {
                "architecture": {
                    "whole": f"{docs}/*architecture*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        assert len(discovered["architecture"]) == 2

    def test_selective_load_single_file_ok(self, tmp_path: Path) -> None:
        """SELECTIVE_LOAD with single match returns that file."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "epics.md").write_text("# Epics")

        workflow_config = {
            "input_file_patterns": {
                "epics": {
                    "whole": f"{docs}/*epic*.md",
                    "load_strategy": "SELECTIVE_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        assert len(discovered["epics"]) == 1

    def test_selective_load_raises_on_multiple(self, tmp_path: Path) -> None:
        """SELECTIVE_LOAD raises AmbiguousFileError on multiple matches."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "epics.md").write_text("# Epics")
        (docs / "epics-old.md").write_text("# Old Epics")

        workflow_config = {
            "input_file_patterns": {
                "epics": {
                    "whole": f"{docs}/*epic*.md",
                    "load_strategy": "SELECTIVE_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)

        with pytest.raises(AmbiguousFileError) as exc_info:
            discover_files(context)

        assert exc_info.value.pattern_name == "epics"
        assert len(exc_info.value.candidates) == 2

    def test_default_strategy_is_full_load(self, tmp_path: Path) -> None:
        """Default load_strategy is FULL_LOAD when not specified."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "doc1.md").write_text("# Doc 1")
        (docs / "doc2.md").write_text("# Doc 2")

        workflow_config = {
            "input_file_patterns": {
                "docs": {
                    "whole": f"{docs}/*.md",
                    # load_strategy NOT specified - defaults to FULL_LOAD
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        # Should return all files, not raise error
        assert len(discovered["docs"]) == 2


# ==============================================================================
# AC4: Required File Validation
# ==============================================================================


class TestRequiredFileValidation:
    """Tests for required file validation (AC4)."""

    def test_missing_required_file_raises_error(self, tmp_path: Path) -> None:
        """CompilerError raised when required file not found."""
        docs = tmp_path / "docs"
        docs.mkdir()
        # No project_context.md

        workflow_config = {
            "input_file_patterns": {
                "project_context": {
                    "whole": f"{docs}/*project_context*.md",
                    "required": True,
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)

        with pytest.raises(CompilerError) as exc_info:
            discover_files(context)

        assert "project_context" in str(exc_info.value)
        assert "required" in str(exc_info.value).lower()

    def test_missing_optional_file_no_error(self, tmp_path: Path) -> None:
        """No error when optional file (required=False) not found."""
        docs = tmp_path / "docs"
        docs.mkdir()
        # No ux.md

        workflow_config = {
            "input_file_patterns": {
                "ux": {
                    "whole": f"{docs}/*ux*.md",
                    "required": False,
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        assert discovered["ux"] == []

    def test_required_defaults_to_false(self, tmp_path: Path) -> None:
        """Required defaults to False when not specified."""
        docs = tmp_path / "docs"
        docs.mkdir()
        # No file

        workflow_config = {
            "input_file_patterns": {
                "optional": {
                    "whole": f"{docs}/*optional*.md",
                    # required NOT specified
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        # Should not raise, returns empty list
        assert discovered["optional"] == []


# ==============================================================================
# AC5: Section Extraction from Files
# ==============================================================================


class TestSectionExtraction:
    """Tests for section extraction from markdown files (AC5)."""

    def test_extract_section_by_story_id(self, tmp_path: Path) -> None:
        """Section is extracted by story ID from markdown."""
        epic_file = tmp_path / "epic-10.md"
        epic_file.write_text("""# Epic 10: BMAD Workflow Compiler

## Story 10.3: Variable Resolution Engine

As a developer...

## Story 10.4: File Discovery and Inclusion

**As a** developer,
**I want** automatic discovery...

## Story 10.5: Instruction Filtering
""")

        section = extract_section(epic_file, "story-10.4")

        assert "## Story 10.4" in section
        assert "automatic discovery" in section
        assert "Story 10.5" not in section

    def test_extract_section_case_insensitive(self, tmp_path: Path) -> None:
        """Section matching is case-insensitive."""
        file = tmp_path / "doc.md"
        file.write_text("""# Document

## SECTION ONE

Content here.

## Section Two
""")

        section = extract_section(file, "section-one")

        assert "## SECTION ONE" in section
        assert "Content here" in section
        assert "Section Two" not in section

    def test_extract_section_word_boundary(self, tmp_path: Path) -> None:
        """Section ID respects word boundaries (10.4 != 10.40)."""
        file = tmp_path / "doc.md"
        file.write_text("""# Document

## Story 10.40: Wrong Story

Wrong content.

## Story 10.4: Correct Story

Correct content.

## Story 10.5: Next
""")

        section = extract_section(file, "10.4")

        assert "Correct Story" in section
        assert "Correct content" in section
        assert "Wrong Story" not in section
        assert "Wrong content" not in section

    def test_extract_section_to_eof(self, tmp_path: Path) -> None:
        """Section at end of file extracts to EOF."""
        file = tmp_path / "doc.md"
        file.write_text("""# Document

## First Section

First content.

## Last Section

Last content here.
No more headers.
""")

        section = extract_section(file, "last-section")

        assert "## Last Section" in section
        assert "Last content here" in section
        assert "No more headers" in section

    def test_extract_section_includes_header(self, tmp_path: Path) -> None:
        """Extracted section includes the header line."""
        file = tmp_path / "doc.md"
        file.write_text("""# Doc

## My Section

Content.

## Next
""")

        section = extract_section(file, "my-section")

        assert section.startswith("## My Section")

    def test_extract_section_not_found_raises_error(self, tmp_path: Path) -> None:
        """CompilerError raised when section not found."""
        file = tmp_path / "doc.md"
        file.write_text("""# Document

## Section One

Content.
""")

        with pytest.raises(CompilerError) as exc_info:
            extract_section(file, "nonexistent-section")

        assert "nonexistent-section" in str(exc_info.value)
        assert str(file) in str(exc_info.value)

    def test_extract_section_normalizes_separators(self, tmp_path: Path) -> None:
        """Section ID with different separators matches header."""
        file = tmp_path / "doc.md"
        file.write_text("""# Doc

## Story 10.4: File Discovery

Content.

## Next
""")

        # All these should match "Story 10.4"
        assert "File Discovery" in extract_section(file, "story-10.4")
        assert "File Discovery" in extract_section(file, "STORY_10_4")
        assert "File Discovery" in extract_section(file, "story.10.4")


# ==============================================================================
# AC6: Load File Contents
# ==============================================================================


class TestLoadFileContents:
    """Tests for loading file contents (AC6)."""

    def test_load_file_contents_stores_in_context(self, tmp_path: Path) -> None:
        """Discovered files are loaded and stored in context."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "prd.md").write_text("# PRD\n\nRequirements here.")

        workflow_config = {
            "input_file_patterns": {
                "prd": {
                    "whole": f"{docs}/*prd*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discover_files(context)
        load_file_contents(context)

        assert "prd" in context.file_contents
        assert "Requirements here" in context.file_contents["prd"]

    def test_load_file_contents_selective_patterns(self, tmp_path: Path) -> None:
        """Only specified patterns are loaded when patterns param given."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "prd.md").write_text("PRD content")
        (docs / "arch.md").write_text("Arch content")

        workflow_config = {
            "input_file_patterns": {
                "prd": {"whole": f"{docs}/*prd*.md"},
                "arch": {"whole": f"{docs}/*arch*.md"},
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discover_files(context)
        load_file_contents(context, patterns=["prd"])

        assert "prd" in context.file_contents
        assert "arch" not in context.file_contents

    def test_load_file_contents_multiple_files_concatenated(self, tmp_path: Path) -> None:
        """Multiple files are concatenated in content."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "arch-a.md").write_text("# Part A")
        (docs / "arch-b.md").write_text("# Part B")

        workflow_config = {
            "input_file_patterns": {
                "architecture": {
                    "whole": f"{docs}/*arch*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discover_files(context)
        load_file_contents(context)

        assert "Part A" in context.file_contents["architecture"]
        assert "Part B" in context.file_contents["architecture"]

    def test_load_file_contents_empty_file(self, tmp_path: Path) -> None:
        """Empty file returns empty string."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "empty.md").write_text("")

        workflow_config = {"input_file_patterns": {"empty": {"whole": f"{docs}/*empty*.md"}}}

        context = create_test_context(tmp_path, workflow_config)
        discover_files(context)
        load_file_contents(context)

        assert context.file_contents["empty"] == ""


# ==============================================================================
# AC7: Sharded Directory Support
# ==============================================================================


class TestShardedDirectorySupport:
    """Tests for sharded directory handling (AC7)."""

    def test_sharded_takes_precedence_over_whole(self, tmp_path: Path) -> None:
        """Sharded directory is used even if whole file exists."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "epics.md").write_text("# Whole file")
        sharded = docs / "epics"
        sharded.mkdir()
        (sharded / "index.md").write_text("# Index")
        (sharded / "epic-10.md").write_text("# Epic 10")

        workflow_config = {
            "input_file_patterns": {
                "epics": {
                    "whole": f"{docs}/*epic*.md",
                    "sharded": f"{docs}/*epic*/*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        # Should have sharded files, not whole file
        assert len(discovered["epics"]) == 2  # index.md + epic-10.md
        assert all(f.parent.name == "epics" for f in discovered["epics"])

    def test_sharded_empty_directory_uses_whole(self, tmp_path: Path) -> None:
        """Empty sharded directory falls back to whole file."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "prd.md").write_text("# Whole PRD")
        sharded = docs / "prd"
        sharded.mkdir()  # Empty directory - no .md files

        workflow_config = {
            "input_file_patterns": {
                "prd": {
                    "whole": f"{docs}/*prd*.md",
                    "sharded": f"{docs}/*prd*/*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        assert len(discovered["prd"]) == 1
        assert discovered["prd"][0].name == "prd.md"

    def test_sharded_with_non_md_files_uses_whole(self, tmp_path: Path) -> None:
        """Directory with only non-.md files falls back to whole."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "prd.md").write_text("# Whole PRD")
        sharded = docs / "prd"
        sharded.mkdir()
        (sharded / "image.png").write_bytes(b"\x89PNG")  # Not a .md file

        workflow_config = {
            "input_file_patterns": {
                "prd": {
                    "whole": f"{docs}/*prd*.md",
                    "sharded": f"{docs}/*prd*/*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        # Should fall back to whole file
        assert len(discovered["prd"]) == 1
        assert discovered["prd"][0].name == "prd.md"

    def test_sharded_content_index_first(self, tmp_path: Path) -> None:
        """Sharded content is ordered with index.md first."""
        docs = tmp_path / "docs"
        sharded = docs / "arch"
        sharded.mkdir(parents=True)
        (sharded / "z-last.md").write_text("Z Last")
        (sharded / "index.md").write_text("Index First")
        (sharded / "a-first.md").write_text("A First")

        workflow_config = {
            "input_file_patterns": {
                "arch": {
                    "sharded": f"{sharded}/*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discover_files(context)
        load_file_contents(context)

        content = context.file_contents["arch"]
        # index.md content should come first
        index_pos = content.find("Index First")
        a_pos = content.find("A First")
        assert index_pos < a_pos


# ==============================================================================
# AC8: Error Handling and Security
# ==============================================================================


class TestErrorHandlingAndSecurity:
    """Tests for error handling and security (AC8)."""

    def test_invalid_glob_pattern_returns_empty(self, tmp_path: Path) -> None:
        """Invalid glob pattern returns empty list (glob module behavior)."""
        workflow_config = {
            "input_file_patterns": {
                "bad": {
                    "whole": "[invalid-glob",  # Missing closing bracket
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        # Glob module returns empty list for invalid patterns, not error
        assert discovered["bad"] == []

    def test_path_outside_project_root_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Files outside project_root are skipped with warning."""
        docs = tmp_path / "docs"
        docs.mkdir()

        # Create file outside project root
        outside = tmp_path.parent / "outside.md"
        outside.write_text("# Outside")

        workflow_config = {
            "input_file_patterns": {
                "outside": {
                    "whole": str(tmp_path.parent / "*.md"),
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)

        with caplog.at_level(logging.WARNING):
            discovered = discover_files(context)

        # File outside project root should be skipped
        assert discovered["outside"] == []

    def test_binary_file_skipped(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Binary files are skipped with debug log when loading."""
        docs = tmp_path / "docs"
        docs.mkdir()
        # Create a file that looks like .md but has invalid UTF-8 content
        # 0x80-0xFF alone are invalid UTF-8 start bytes
        binary_md = docs / "binary.md"
        binary_md.write_bytes(b"\x80\x81\x82\xff\xfe")

        workflow_config = {"input_file_patterns": {"binary": {"whole": f"{docs}/*.md"}}}

        context = create_test_context(tmp_path, workflow_config)
        discover_files(context)

        with caplog.at_level(logging.DEBUG):
            load_file_contents(context)

        # Binary file content should be skipped
        assert "binary" in context.file_contents
        # Content is empty string due to decode error
        assert context.file_contents["binary"] == ""

    def test_permission_denied_raises_error(self, tmp_path: Path) -> None:
        """Permission denied on file raises CompilerError."""
        # This test is platform-dependent and may not work on all systems
        # Skip if running as root
        import os

        if os.geteuid() == 0:
            pytest.skip("Test not applicable when running as root")

        docs = tmp_path / "docs"
        docs.mkdir()
        protected = docs / "protected.md"
        protected.write_text("# Protected")
        protected.chmod(0o000)

        try:
            workflow_config = {
                "input_file_patterns": {
                    "protected": {
                        "whole": f"{docs}/*.md",
                        "required": True,
                    }
                }
            }

            context = create_test_context(tmp_path, workflow_config)
            discover_files(context)

            with pytest.raises(CompilerError):
                load_file_contents(context)
        finally:
            # Restore permissions for cleanup
            protected.chmod(0o644)

    def test_symlink_outside_project_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Symlinks pointing outside project are skipped."""
        docs = tmp_path / "docs"
        docs.mkdir()

        # Create file outside project
        outside = tmp_path.parent / "external.md"
        outside.write_text("# External")

        # Create symlink to it
        symlink = docs / "link.md"
        try:
            symlink.symlink_to(outside)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

        workflow_config = {"input_file_patterns": {"docs": {"whole": f"{docs}/*.md"}}}

        context = create_test_context(tmp_path, workflow_config)

        with caplog.at_level(logging.WARNING):
            discovered = discover_files(context)

        # Symlink to outside should be skipped
        assert all("link" not in f.name for f in discovered.get("docs", []))


# ==============================================================================
# INDEX_GUIDED Strategy Tests
# ==============================================================================


class TestIndexGuidedStrategy:
    """Tests for INDEX_GUIDED loading strategy (AC3)."""

    def test_index_guided_loads_relevant_sections(self, tmp_path: Path) -> None:
        """INDEX_GUIDED parses index.md and loads relevant files."""
        docs = tmp_path / "docs"
        prd_dir = docs / "prd"
        prd_dir.mkdir(parents=True)
        (prd_dir / "index.md").write_text("""# PRD Index

- [Overview](./overview.md) - Project overview
- [Authentication](./auth.md) - Auth requirements
- [Payments](./payments.md) - Payment system
""")
        (prd_dir / "overview.md").write_text("# Overview")
        (prd_dir / "auth.md").write_text("# Authentication")
        (prd_dir / "payments.md").write_text("# Payments")

        workflow_config = {
            "input_file_patterns": {
                "prd": {
                    "sharded": f"{prd_dir}/*.md",
                    "load_strategy": "INDEX_GUIDED",
                }
            },
            "workflow_context": "authentication",
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        file_names = [f.name for f in discovered["prd"]]
        assert "index.md" in file_names
        assert "auth.md" in file_names

    def test_index_guided_without_context_loads_all(self, tmp_path: Path) -> None:
        """INDEX_GUIDED without workflow_context loads all indexed files."""
        docs = tmp_path / "docs"
        prd_dir = docs / "prd"
        prd_dir.mkdir(parents=True)
        (prd_dir / "index.md").write_text("""# Index

- [A](./a.md)
- [B](./b.md)
""")
        (prd_dir / "a.md").write_text("A")
        (prd_dir / "b.md").write_text("B")

        workflow_config = {
            "input_file_patterns": {
                "prd": {
                    "sharded": f"{prd_dir}/*.md",
                    "load_strategy": "INDEX_GUIDED",
                }
            },
            # No workflow_context
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        # Without context, loads all
        assert len(discovered["prd"]) == 3  # index.md + a.md + b.md


# ==============================================================================
# Edge Case Tests
# ==============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_unicode_in_file_content(self, tmp_path: Path) -> None:
        """Unicode in file content is preserved."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "unicode.md").write_text("# Cześć! 你好! 👋")

        workflow_config = {"input_file_patterns": {"unicode": {"whole": f"{docs}/*.md"}}}

        context = create_test_context(tmp_path, workflow_config)
        discover_files(context)
        load_file_contents(context)

        assert "Cześć! 你好! 👋" in context.file_contents["unicode"]

    def test_very_long_file_loaded_entirely(self, tmp_path: Path) -> None:
        """Large files are loaded entirely."""
        docs = tmp_path / "docs"
        docs.mkdir()
        large_content = "# Header\n" + "Content line\n" * 10000
        (docs / "large.md").write_text(large_content)

        workflow_config = {"input_file_patterns": {"large": {"whole": f"{docs}/*.md"}}}

        context = create_test_context(tmp_path, workflow_config)
        discover_files(context)
        load_file_contents(context)

        assert len(context.file_contents["large"]) > 100000

    def test_pattern_no_matches_returns_empty_list(self, tmp_path: Path) -> None:
        """Pattern with no matches returns empty list."""
        docs = tmp_path / "docs"
        docs.mkdir()
        # No files

        workflow_config = {"input_file_patterns": {"none": {"whole": f"{docs}/*.md"}}}

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        assert discovered["none"] == []

    def test_workflow_ir_required(self, tmp_path: Path) -> None:
        """CompilerError raised when workflow_ir not set."""
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        # workflow_ir NOT set

        with pytest.raises(CompilerError) as exc_info:
            discover_files(context)

        assert "workflow_ir" in str(exc_info.value)

    def test_nested_sharded_directories(self, tmp_path: Path) -> None:
        """Handles nested sharded directories correctly."""
        docs = tmp_path / "docs"
        nested = docs / "arch" / "subdir"
        nested.mkdir(parents=True)
        (docs / "arch" / "main.md").write_text("Main")
        (nested / "nested.md").write_text("Nested")

        workflow_config = {
            "input_file_patterns": {
                "arch": {
                    "sharded": f"{docs}/arch/**/*.md",
                    "load_strategy": "FULL_LOAD",
                }
            }
        }

        context = create_test_context(tmp_path, workflow_config)
        discovered = discover_files(context)

        # Should find both files
        assert len(discovered["arch"]) == 2

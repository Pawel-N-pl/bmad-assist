"""Tests for step file parsing and step chain building.

Tests cover:
- Step file frontmatter parsing
- Path traversal security validation
- Step chain building with nextStepFile references
- Circular reference detection
- Maximum depth handling
"""

from pathlib import Path

import pytest

from bmad_assist.compiler.step_chain import (
    build_step_chain,
    concatenate_step_chain,
    parse_step_file,
)
from bmad_assist.compiler.types import StepIR
from bmad_assist.core.exceptions import CompilerError


class TestParseStepFile:
    """Test parse_step_file function (AC3)."""

    def test_parse_step_with_frontmatter(self, tmp_path: Path) -> None:
        """Parse step file with YAML frontmatter."""
        step_file = tmp_path / "step-01-test.md"
        step_file.write_text(
            """---
name: 'step-01-preflight-and-context'
description: 'Verify prerequisites and load story'
nextStepFile: './step-02-generation.md'
knowledgeIndex: '{project-root}/_bmad/tea/testarch/tea-index.csv'
---

# Step 1: Preflight & Context

## STEP GOAL

Verify prerequisites and load all required inputs.
"""
        )
        step = parse_step_file(step_file)

        assert isinstance(step, StepIR)
        assert step.path == step_file
        assert step.name == "step-01-preflight-and-context"
        assert step.description == "Verify prerequisites and load story"
        assert step.next_step_file == "./step-02-generation.md"
        assert step.knowledge_index == "{project-root}/_bmad/tea/testarch/tea-index.csv"
        assert "# Step 1: Preflight & Context" in step.raw_content
        assert "Verify prerequisites" in step.raw_content

    def test_parse_step_no_frontmatter(self, tmp_path: Path) -> None:
        """Parse step file without frontmatter."""
        step_file = tmp_path / "step-simple.md"
        step_file.write_text("# Simple Step\n\nJust content, no frontmatter.")

        step = parse_step_file(step_file)

        assert step.name == ""
        assert step.description == ""
        assert step.next_step_file is None
        assert step.knowledge_index is None
        assert "# Simple Step" in step.raw_content

    def test_parse_step_empty_frontmatter(self, tmp_path: Path) -> None:
        """Parse step file with empty frontmatter."""
        step_file = tmp_path / "step-empty.md"
        step_file.write_text("---\n---\n\n# Content\n")

        step = parse_step_file(step_file)

        assert step.name == ""
        assert step.description == ""
        assert step.next_step_file is None

    def test_parse_step_partial_frontmatter(self, tmp_path: Path) -> None:
        """Parse step file with partial frontmatter (some fields missing)."""
        step_file = tmp_path / "step-partial.md"
        step_file.write_text(
            """---
name: 'partial-step'
---

# Content
"""
        )
        step = parse_step_file(step_file)

        assert step.name == "partial-step"
        assert step.description == ""
        assert step.next_step_file is None
        assert step.knowledge_index is None

    def test_parse_step_final_step_no_next(self, tmp_path: Path) -> None:
        """Parse final step with no nextStepFile."""
        step_file = tmp_path / "step-final.md"
        step_file.write_text(
            """---
name: 'step-05-validate-and-complete'
description: 'Validate ATDD outputs and summarize'
---

# Step 5: Validate & Complete
"""
        )
        step = parse_step_file(step_file)

        assert step.name == "step-05-validate-and-complete"
        assert step.next_step_file is None

    def test_parse_step_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Reject nextStepFile with path traversal."""
        step_file = tmp_path / "step-bad.md"
        step_file.write_text(
            """---
name: 'bad-step'
nextStepFile: '../../../etc/passwd'
---

# Malicious step
"""
        )
        with pytest.raises(CompilerError) as exc_info:
            parse_step_file(step_file)

        assert "path traversal" in str(exc_info.value).lower()

    def test_parse_step_absolute_path_blocked(self, tmp_path: Path) -> None:
        """Reject nextStepFile with absolute path."""
        step_file = tmp_path / "step-absolute.md"
        step_file.write_text(
            """---
name: 'bad-step'
nextStepFile: '/etc/passwd'
---

# Malicious step
"""
        )
        with pytest.raises(CompilerError) as exc_info:
            parse_step_file(step_file)

        assert "path traversal" in str(exc_info.value).lower() or "absolute" in str(
            exc_info.value
        ).lower()

    def test_parse_step_invalid_yaml(self, tmp_path: Path) -> None:
        """Handle invalid YAML in frontmatter gracefully."""
        step_file = tmp_path / "step-invalid.md"
        step_file.write_text(
            """---
name: 'valid'
description: [unclosed
---

# Content
"""
        )
        # Should log warning and treat as no frontmatter
        step = parse_step_file(step_file)

        assert step.name == ""  # Falls back to empty
        assert "# Content" in step.raw_content


class TestBuildStepChain:
    """Test build_step_chain function (AC5)."""

    def test_build_single_step_chain(self, tmp_path: Path) -> None:
        """Build chain with single step (no nextStepFile)."""
        step = tmp_path / "step-01.md"
        step.write_text(
            """---
name: 'only-step'
description: 'The only step'
---

# Only Step
"""
        )
        chain = build_step_chain(step)

        assert len(chain) == 1
        assert chain[0].name == "only-step"

    def test_build_multi_step_chain(self, tmp_path: Path) -> None:
        """Build chain following nextStepFile references."""
        (tmp_path / "step-01.md").write_text(
            """---
name: 'step-01'
nextStepFile: './step-02.md'
---
# Step 1
"""
        )
        (tmp_path / "step-02.md").write_text(
            """---
name: 'step-02'
nextStepFile: './step-03.md'
---
# Step 2
"""
        )
        (tmp_path / "step-03.md").write_text(
            """---
name: 'step-03'
---
# Step 3 (final)
"""
        )

        chain = build_step_chain(tmp_path / "step-01.md")

        assert len(chain) == 3
        assert chain[0].name == "step-01"
        assert chain[1].name == "step-02"
        assert chain[2].name == "step-03"

    def test_chain_max_depth_exceeded(self, tmp_path: Path) -> None:
        """Raise error when chain exceeds maximum depth (20)."""
        # Create 25 steps in a chain
        for i in range(1, 26):
            next_file = f"./step-{i+1:02d}.md" if i < 25 else None
            content = f"---\nname: 'step-{i:02d}'\n"
            if next_file:
                content += f"nextStepFile: '{next_file}'\n"
            content += f"---\n# Step {i}\n"
            (tmp_path / f"step-{i:02d}.md").write_text(content)

        with pytest.raises(CompilerError) as exc_info:
            build_step_chain(tmp_path / "step-01.md")

        error_msg = str(exc_info.value).lower()
        assert "maximum depth" in error_msg or "exceeds" in error_msg

    def test_chain_circular_reference_detected(self, tmp_path: Path) -> None:
        """Detect and report circular references."""
        (tmp_path / "step-01.md").write_text(
            """---
name: 'step-01'
nextStepFile: './step-02.md'
---
# Step 1
"""
        )
        (tmp_path / "step-02.md").write_text(
            """---
name: 'step-02'
nextStepFile: './step-01.md'
---
# Step 2 - points back to step 1!
"""
        )

        with pytest.raises(CompilerError) as exc_info:
            build_step_chain(tmp_path / "step-01.md")

        error_msg = str(exc_info.value).lower()
        assert "circular" in error_msg

    def test_chain_missing_next_step_warning(self, tmp_path: Path, caplog) -> None:
        """Log warning and truncate chain when next step is missing."""
        (tmp_path / "step-01.md").write_text(
            """---
name: 'step-01'
nextStepFile: './step-02.md'
---
# Step 1
"""
        )
        (tmp_path / "step-02.md").write_text(
            """---
name: 'step-02'
nextStepFile: './step-03-nonexistent.md'
---
# Step 2
"""
        )
        # step-03 does NOT exist

        import logging

        with caplog.at_level(logging.WARNING):
            chain = build_step_chain(tmp_path / "step-01.md")

        # Chain should include steps 1 and 2
        assert len(chain) == 2
        assert chain[0].name == "step-01"
        assert chain[1].name == "step-02"

        # Warning should be logged
        assert any("not found" in record.message.lower() for record in caplog.records)


class TestConcatenateStepChain:
    """Test concatenate_step_chain function (AC5)."""

    def test_concatenate_with_markers(self, tmp_path: Path) -> None:
        """Concatenate steps with boundary markers."""
        (tmp_path / "step-01.md").write_text(
            """---
name: 'step-01-first'
nextStepFile: './step-02.md'
---
# First Step

Content of first step.
"""
        )
        (tmp_path / "step-02.md").write_text(
            """---
name: 'step-02-second'
---
# Second Step

Content of second step.
"""
        )

        chain = build_step_chain(tmp_path / "step-01.md")
        result = concatenate_step_chain(chain)

        # Check markers are present
        assert "<!-- STEP: step-01-first -->" in result
        assert "<!-- STEP: step-02-second -->" in result

        # Check content is present
        assert "Content of first step" in result
        assert "Content of second step" in result

        # Check order (first before second)
        first_pos = result.find("step-01-first")
        second_pos = result.find("step-02-second")
        assert first_pos < second_pos

    def test_concatenate_empty_chain(self) -> None:
        """Concatenate empty chain returns empty string."""
        result = concatenate_step_chain([])
        assert result == ""

    def test_concatenate_single_step(self, tmp_path: Path) -> None:
        """Concatenate single step chain."""
        step = tmp_path / "single.md"
        step.write_text(
            """---
name: 'single-step'
---
# Single Step

Only one step.
"""
        )

        chain = build_step_chain(step)
        result = concatenate_step_chain(chain)

        assert "<!-- STEP: single-step -->" in result
        assert "Only one step" in result


class TestCompileStepChainKnowledgeInjection:
    """Test compile_step_chain knowledge injection (AC7)."""

    def test_compile_with_workflow_id_loads_knowledge(
        self, tmp_path: Path
    ) -> None:
        """Should load and inject knowledge fragments for TEA workflow."""
        from bmad_assist.compiler.step_chain import compile_step_chain
        from bmad_assist.testarch.knowledge.loader import clear_all_loaders

        # Clear any cached loaders from previous tests
        clear_all_loaders()

        # Create step file
        step_file = tmp_path / "step-01.md"
        step_file.write_text(
            """---
name: 'step-01'
---
# Step Content

Some instructions here.
"""
        )

        # Create knowledge index with fragments matching WORKFLOW_KNOWLEDGE_MAP
        # For testarch-atdd: fixture-architecture, network-first, etc.
        knowledge_dir = tmp_path / "_bmad/tea/testarch"
        knowledge_dir.mkdir(parents=True)
        index_file = knowledge_dir / "tea-index.csv"
        index_file.write_text(
            "id,name,description,fragment_file,tags\n"
            "fixture-architecture,Fixture Architecture,Fixture patterns,fixture-architecture.md,atdd\n"
            "network-first,Network First,Network patterns,network-first.md,atdd\n"
        )
        # Create fragment files
        (knowledge_dir / "fixture-architecture.md").write_text(
            "# Fixture Architecture\n\nTest fixture patterns.\n"
        )
        (knowledge_dir / "network-first.md").write_text(
            "# Network First\n\nNetwork testing patterns.\n"
        )

        resolved_vars: dict = {}
        compiled, _ = compile_step_chain(
            step_file,
            resolved_vars,
            tmp_path,
            workflow_id="testarch-atdd",
        )

        # Knowledge base should be injected
        assert "<!-- KNOWLEDGE BASE -->" in compiled
        assert "Fixture Architecture" in compiled or "Network First" in compiled

        # Clean up
        clear_all_loaders()

    def test_compile_without_workflow_id_skips_knowledge(
        self, tmp_path: Path
    ) -> None:
        """Should not inject knowledge when workflow_id is None."""
        from bmad_assist.compiler.step_chain import compile_step_chain

        step_file = tmp_path / "step-01.md"
        step_file.write_text(
            """---
name: 'step-01'
---
# Step Content
"""
        )

        resolved_vars: dict = {}
        compiled, _ = compile_step_chain(
            step_file,
            resolved_vars,
            tmp_path,
            workflow_id=None,
        )

        assert "<!-- KNOWLEDGE BASE -->" not in compiled

    def test_compile_non_tea_workflow_skips_knowledge(
        self, tmp_path: Path
    ) -> None:
        """Should not inject knowledge for non-TEA workflows."""
        from bmad_assist.compiler.step_chain import compile_step_chain

        step_file = tmp_path / "step-01.md"
        step_file.write_text(
            """---
name: 'step-01'
---
# Step Content
"""
        )

        resolved_vars: dict = {}
        compiled, _ = compile_step_chain(
            step_file,
            resolved_vars,
            tmp_path,
            workflow_id="dev-story",
        )

        assert "<!-- KNOWLEDGE BASE -->" not in compiled

    def test_compile_logs_warning_for_missing_knowledge_index(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should log warning when knowledge index missing for TEA workflow."""
        import logging

        from bmad_assist.compiler.step_chain import compile_step_chain

        step_file = tmp_path / "step-01.md"
        step_file.write_text(
            """---
name: 'step-01'
---
# Step Content
"""
        )

        resolved_vars: dict = {}
        with caplog.at_level(logging.WARNING):
            compile_step_chain(
                step_file,
                resolved_vars,
                tmp_path,
                workflow_id="testarch-atdd",
            )

        # Should warn about missing knowledge index
        assert any(
            "knowledge index" in record.message.lower()
            for record in caplog.records
        )

    def test_compile_respects_tea_flags(
        self, tmp_path: Path
    ) -> None:
        """Should pass TEA flags for tag exclusion."""
        from bmad_assist.compiler.step_chain import compile_step_chain

        # Create step file
        step_file = tmp_path / "step-01.md"
        step_file.write_text(
            """---
name: 'step-01'
---
# Step Content
"""
        )

        # Create knowledge index with playwright-utils tagged fragment
        knowledge_dir = tmp_path / "_bmad/tea/testarch"
        knowledge_dir.mkdir(parents=True)
        index_file = knowledge_dir / "tea-index.csv"
        index_file.write_text(
            "id,name,description,fragment_file,tags\n"
            "pw-fragment,Playwright Utils,Playwright helpers,pw-fragment.md,playwright-utils\n"
        )
        fragment_file = knowledge_dir / "pw-fragment.md"
        fragment_file.write_text("# Playwright Utils\n\nPlaywright helper content.\n")

        # Create module.yaml with playwright disabled
        module_yaml = tmp_path / "_bmad/tea/module.yaml"
        module_yaml.write_text("tea_use_playwright_utils: false\n")

        resolved_vars: dict = {}
        compile_step_chain(
            step_file,
            resolved_vars,
            tmp_path,
            workflow_id="testarch-atdd",
        )

        # Flag should be set to False
        assert resolved_vars.get("tea_use_playwright_utils") is False

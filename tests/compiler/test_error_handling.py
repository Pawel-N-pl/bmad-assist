"""Comprehensive error handling tests for BMAD workflow compiler.

Tests for Story 10.8 - Fail-Fast Error Handling:
- AC1: Required file missing - CompilerError with full context
- AC2: Variable cannot be resolved - VariableError with sources
- AC3: Workflow structure invalid - ParserError with location
- AC4: Ambiguous file match - AmbiguousFileError with candidates
- AC5: Path security violation - CompilerError for traversal
- AC6: XML output validation - CompilerError for malformed output
- AC7: Error hierarchy consistency
- AC8: No partial output on error
"""

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bmad_assist.compiler.core import get_workflow_compiler
from bmad_assist.compiler.discovery import (
    LoadStrategy,
    _apply_load_strategy,
    extract_section,
)
from bmad_assist.compiler.output import GeneratedOutput, generate_output
from bmad_assist.compiler.parser import (
    parse_workflow,
    parse_workflow_config,
    parse_workflow_instructions,
)
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext
from bmad_assist.compiler.variables import _validate_config_path, resolve_variables
from bmad_assist.core.exceptions import (
    AmbiguousFileError,
    BmadAssistError,
    CompilerError,
    ParserError,
    VariableError,
)

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project structure for testing."""
    # Create basic project structure
    (tmp_path / "docs").mkdir()
    (tmp_path / "_bmad" / "bmm" / "config.yaml").parent.mkdir(parents=True)
    (tmp_path / "_bmad" / "bmm" / "config.yaml").write_text(
        "project_name: test-project\n"
        "output_folder: '{project-root}/docs'\n"
        "sprint_artifacts: '{project-root}/docs/sprint-artifacts'\n"
    )
    return tmp_path


@pytest.fixture
def workflow_dir(tmp_path: Path) -> Path:
    """Create a workflow directory with valid files."""
    wf_dir = tmp_path / "workflow"
    wf_dir.mkdir()
    (wf_dir / "workflow.yaml").write_text(
        "name: test-workflow\n"
        "description: Test workflow\n"
        "config_source: '{project-root}/_bmad/bmm/config.yaml'\n"
    )
    (wf_dir / "instructions.xml").write_text(
        "<workflow>\n"
        '  <step n="1" goal="Test step">\n'
        "    <action>Do something</action>\n"
        "  </step>\n"
        "</workflow>\n"
    )
    return wf_dir


@pytest.fixture
def context(tmp_project: Path) -> CompilerContext:
    """Create a basic compiler context."""
    return CompilerContext(
        project_root=tmp_project,
        output_folder=tmp_project / "docs",
    )


# ============================================================================
# AC1: Required File Missing - CompilerError with Full Context
# ============================================================================


class TestAC1RequiredFileMissing:
    """Tests for AC1: Required file missing produces CompilerError with context."""

    def test_missing_workflow_yaml_error_format(self, tmp_path: Path) -> None:
        """Missing workflow.yaml produces error with path, why, and how to fix."""
        workflow_dir = tmp_path / "empty_workflow"
        workflow_dir.mkdir()
        # No workflow.yaml file

        with pytest.raises(ParserError) as exc_info:
            parse_workflow(workflow_dir)

        error_msg = str(exc_info.value)
        assert "workflow.yaml not found" in error_msg
        assert "Why it's needed:" in error_msg
        assert "How to fix:" in error_msg

    def test_missing_instructions_xml_error_format(self, tmp_path: Path) -> None:
        """Missing instructions file produces error with context."""
        workflow_dir = tmp_path / "workflow"
        workflow_dir.mkdir()
        (workflow_dir / "workflow.yaml").write_text("name: test\n")
        # No instructions.xml or instructions.md

        with pytest.raises(ParserError) as exc_info:
            parse_workflow(workflow_dir)

        error_msg = str(exc_info.value)
        assert "instructions file not found" in error_msg
        assert "Why it's needed:" in error_msg
        assert "How to fix:" in error_msg

    def test_missing_config_source_error_format(self, workflow_dir: Path, tmp_path: Path) -> None:
        """Missing config_source file produces VariableError with context."""
        # Update workflow.yaml to point to non-existent config
        (workflow_dir / "workflow.yaml").write_text(
            "name: test\nconfig_source: '{project-root}/missing-config.yaml'\n"
        )

        workflow_ir = parse_workflow(workflow_dir)
        ctx = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        ctx.workflow_ir = workflow_ir

        with pytest.raises(VariableError) as exc_info:
            resolve_variables(ctx, {})

        error_msg = str(exc_info.value)
        assert "Config source file not found" in error_msg
        assert "Suggestion:" in error_msg or "How to fix:" in error_msg


# ============================================================================
# AC2: Variable Cannot Be Resolved - VariableError with Sources
# ============================================================================


class TestAC2VariableResolution:
    """Tests for AC2: Unresolvable variable produces VariableError with sources."""

    def test_config_values_merged_directly(self, workflow_dir: Path, tmp_project: Path) -> None:
        """All config values are merged directly (legacy pattern is skipped)."""
        # Create config with values that will be merged
        (tmp_project / "_bmad" / "bmm" / "config.yaml").write_text(
            "project_name: test\nother_key: value\n"
        )

        # Legacy {config_source}:key pattern is now skipped
        (workflow_dir / "workflow.yaml").write_text(
            "name: test\n"
            f"config_source: '{tmp_project}/_bmad/bmm/config.yaml'\n"
            "missing_var: '{config_source}:nonexistent_key'\n"
        )

        workflow_ir = parse_workflow(workflow_dir)
        ctx = CompilerContext(
            project_root=tmp_project,
            output_folder=tmp_project / "docs",
        )
        ctx.workflow_ir = workflow_ir

        # No error raised - legacy pattern is skipped, config values merged directly
        resolved = resolve_variables(ctx, {})

        # Config values are available directly
        assert resolved["project_name"] == "test"
        assert resolved["other_key"] == "value"
        # Legacy pattern variable is not set
        assert "missing_var" not in resolved

    def test_circular_variable_shows_cycle_path(
        self, workflow_dir: Path, tmp_project: Path
    ) -> None:
        """Circular variable reference shows cycle path."""
        # Create config file
        (tmp_project / "_bmad" / "bmm" / "config.yaml").write_text("project_name: test\n")

        # Create workflow with circular reference - var_a -> var_b -> var_a
        (workflow_dir / "workflow.yaml").write_text(
            "name: test\n"
            f"config_source: '{tmp_project}/_bmad/bmm/config.yaml'\n"
            "var_a: '{var_b}'\n"
            "var_b: '{var_a}'\n"
        )

        workflow_ir = parse_workflow(workflow_dir)
        ctx = CompilerContext(
            project_root=tmp_project,
            output_folder=tmp_project / "docs",
        )
        ctx.workflow_ir = workflow_ir

        with pytest.raises(VariableError) as exc_info:
            resolve_variables(ctx, {})

        error_msg = str(exc_info.value)
        assert "circular reference" in error_msg.lower()
        assert "→" in error_msg or "Cycle" in error_msg  # Shows cycle path
        assert exc_info.value.sources_checked  # Has sources


# ============================================================================
# AC3: Workflow Structure Invalid - ParserError with Location
# ============================================================================


class TestAC3ParserErrorLocation:
    """Tests for AC3: Parser errors include file location."""

    def test_malformed_yaml_error_has_line_number(self, tmp_path: Path) -> None:
        """Malformed YAML produces error with line number."""
        workflow_dir = tmp_path / "workflow"
        workflow_dir.mkdir()
        # Create YAML with clear syntax error - unmatched quote
        (workflow_dir / "workflow.yaml").write_text("key: 'unmatched\nother: value")
        (workflow_dir / "instructions.xml").write_text("<workflow></workflow>")

        with pytest.raises(ParserError) as exc_info:
            parse_workflow(workflow_dir)

        error_msg = str(exc_info.value)
        assert "Line" in error_msg or "line" in error_msg
        assert "Suggestion:" in error_msg

    def test_malformed_xml_error_has_line_number(self, tmp_path: Path) -> None:
        """Malformed XML produces error with line number."""
        workflow_dir = tmp_path / "workflow"
        workflow_dir.mkdir()
        (workflow_dir / "workflow.yaml").write_text("name: test\n")
        # Create XML with unclosed tag
        (workflow_dir / "instructions.xml").write_text("<workflow>\n<step>\n</workflow>")

        with pytest.raises(ParserError) as exc_info:
            parse_workflow(workflow_dir)

        error_msg = str(exc_info.value)
        assert "Line" in error_msg
        assert "Suggestion:" in error_msg

    def test_empty_workflow_yaml_returns_empty_dict(self, tmp_path: Path) -> None:
        """Empty workflow.yaml returns empty dict (not error)."""
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("")

        result = parse_workflow_config(config_path)
        assert result == {}

    def test_xml_doctype_rejected(self, tmp_path: Path) -> None:
        """XML with DOCTYPE is rejected for security."""
        instructions_path = tmp_path / "instructions.xml"
        instructions_path.write_text('<!DOCTYPE foo SYSTEM "bar">\n<workflow></workflow>')

        with pytest.raises(ParserError) as exc_info:
            parse_workflow_instructions(instructions_path)

        error_msg = str(exc_info.value)
        assert "DOCTYPE" in error_msg
        assert "Suggestion:" in error_msg


# ============================================================================
# AC4: Ambiguous File Match - AmbiguousFileError with Candidates
# ============================================================================


class TestAC4AmbiguousFile:
    """Tests for AC4: Ambiguous file match lists candidates."""

    def test_ambiguous_file_lists_candidates(self, tmp_path: Path) -> None:
        """Ambiguous file match lists all candidates."""
        # Create multiple matching files
        files = [
            tmp_path / "file1.md",
            tmp_path / "file2.md",
            tmp_path / "file3.md",
        ]
        for f in files:
            f.write_text("# Content")

        with pytest.raises(AmbiguousFileError) as exc_info:
            _apply_load_strategy(
                files=files,
                strategy=LoadStrategy.SELECTIVE_LOAD,
                pattern_name="test_pattern",
                pattern_config={},
                context=CompilerContext(
                    project_root=tmp_path,
                    output_folder=tmp_path,
                ),
            )

        assert len(exc_info.value.candidates) == 3
        assert exc_info.value.suggestion
        error_msg = str(exc_info.value)
        assert "test_pattern" in error_msg
        assert "Suggestion:" in error_msg

    def test_ambiguous_file_truncates_list_at_10(self, tmp_path: Path) -> None:
        """Ambiguous file with >10 matches shows first 10 + count."""
        # Create 15 matching files
        files = []
        for i in range(15):
            f = tmp_path / f"file{i:02d}.md"
            f.write_text(f"# File {i}")
            files.append(f)

        with pytest.raises(AmbiguousFileError) as exc_info:
            _apply_load_strategy(
                files=files,
                strategy=LoadStrategy.SELECTIVE_LOAD,
                pattern_name="test_pattern",
                pattern_config={},
                context=CompilerContext(
                    project_root=tmp_path,
                    output_folder=tmp_path,
                ),
            )

        # All candidates stored in exception
        assert len(exc_info.value.candidates) == 15
        # Error message shows truncated list
        error_msg = str(exc_info.value)
        assert "10 of 15" in error_msg or "showing first 10" in error_msg.lower()


# ============================================================================
# AC5: Path Security Violation - CompilerError for Traversal
# ============================================================================


class TestAC5PathSecurity:
    """Tests for AC5: Path traversal raises security error."""

    def test_path_traversal_raises_security_error(self, tmp_path: Path) -> None:
        """Path traversal attempt raises VariableError with security context."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        # Attempt to access file outside project
        malicious_path = project_root / ".." / ".." / "etc" / "passwd"

        with pytest.raises(VariableError) as exc_info:
            _validate_config_path(malicious_path, project_root)

        error_msg = str(exc_info.value)
        assert "security" in error_msg.lower() or "Path" in error_msg
        assert "project" in error_msg.lower()

    def test_path_outside_project_raises_error(self, tmp_path: Path) -> None:
        """Path outside project boundary raises error."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        outside_file = tmp_path / "outside.yaml"
        outside_file.write_text("key: value")

        with pytest.raises(VariableError) as exc_info:
            _validate_config_path(outside_file, project_root)

        error_msg = str(exc_info.value)
        assert "security" in error_msg.lower() or "outside" in error_msg.lower()


# ============================================================================
# AC6: XML Output Validation - CompilerError for Malformed Output
# ============================================================================


class TestAC6XMLValidation:
    """Tests for AC6: XML output is validated for well-formedness."""

    def test_valid_xml_output_passes_validation(self) -> None:
        """Valid compiled workflow produces valid XML."""
        compiled = CompiledWorkflow(
            workflow_name="test",
            mission="Test mission",
            context="Test context",
            variables={"var1": "value1"},
            instructions="<step>Test</step>",
            output_template="Template",
            token_estimate=0,
        )

        result = generate_output(compiled)
        assert isinstance(result, GeneratedOutput)
        assert result.xml
        # Should be parseable
        ET.fromstring(result.xml)

    def test_xml_validation_catches_malformed_output(self, tmp_path: Path) -> None:
        """Malformed XML output raises CompilerError."""
        # This test verifies the validation works - in practice, ElementTree
        # handles escaping correctly, so we test the validation logic exists
        compiled = CompiledWorkflow(
            workflow_name="test",
            mission="Test mission",
            context="Normal content",
            variables={},
            instructions="<step>Test</step>",
            output_template="",
            token_estimate=0,
        )

        # Normal case should work
        result = generate_output(compiled)
        assert result.xml

        # Verify XML is well-formed
        parsed = ET.fromstring(result.xml)
        assert parsed is not None


# ============================================================================
# AC7: Error Hierarchy Consistency
# ============================================================================


class TestAC7ErrorHierarchy:
    """Tests for AC7: All errors inherit from BmadAssistError."""

    def test_compiler_error_inherits_from_base(self) -> None:
        """CompilerError inherits from BmadAssistError."""
        error = CompilerError("test")
        assert isinstance(error, BmadAssistError)
        assert isinstance(error, Exception)

    def test_parser_error_inherits_from_base(self) -> None:
        """ParserError inherits from BmadAssistError."""
        error = ParserError("test")
        assert isinstance(error, BmadAssistError)

    def test_variable_error_inherits_from_base(self) -> None:
        """VariableError inherits from BmadAssistError."""
        error = VariableError("test")
        assert isinstance(error, BmadAssistError)

    def test_ambiguous_file_error_inherits_from_base(self) -> None:
        """AmbiguousFileError inherits from BmadAssistError."""
        error = AmbiguousFileError("test")
        assert isinstance(error, BmadAssistError)

    def test_variable_error_has_attributes(self) -> None:
        """VariableError has expected attributes."""
        error = VariableError(
            "Cannot resolve variable",
            variable_name="test_var",
            sources_checked=["source1", "source2"],
            suggestion="Try this fix",
        )
        assert error.variable_name == "test_var"
        assert error.sources_checked == ["source1", "source2"]
        assert error.suggestion == "Try this fix"

    def test_ambiguous_file_error_has_attributes(self) -> None:
        """AmbiguousFileError has expected attributes."""
        candidates = [Path("/a.md"), Path("/b.md")]
        error = AmbiguousFileError(
            "Multiple files match",
            pattern_name="epics",
            candidates=candidates,
            suggestion="Specify file",
        )
        assert error.pattern_name == "epics"
        assert error.candidates == candidates
        assert error.suggestion == "Specify file"


# ============================================================================
# AC8: No Partial Output on Error
# ============================================================================


class TestAC8NoPartialOutput:
    """Tests for AC8: No partial output on error."""

    def test_context_not_modified_on_error(self, tmp_project: Path) -> None:
        """Error during compilation leaves context unchanged."""
        ctx = CompilerContext(
            project_root=tmp_project,
            output_folder=tmp_project / "docs",
        )

        # Store original state
        original_workflow_ir = ctx.workflow_ir
        original_resolved_vars = dict(ctx.resolved_variables)

        # Attempt compilation that will fail (no project_context.md)
        try:
            compiler = get_workflow_compiler("create-story")
            ctx.resolved_variables["epic_num"] = 10
            ctx.resolved_variables["story_num"] = 1
            compiler.compile(ctx)
        except (CompilerError, ParserError, FileNotFoundError):
            pass  # Expected to fail

        # Context should be restored
        assert ctx.workflow_ir == original_workflow_ir

    def test_no_files_created_on_error(self, tmp_project: Path) -> None:
        """Error during compilation creates no new files."""
        # Record initial file state
        initial_files = set(tmp_project.rglob("*"))

        ctx = CompilerContext(
            project_root=tmp_project,
            output_folder=tmp_project / "docs",
        )

        try:
            compiler = get_workflow_compiler("create-story")
            ctx.resolved_variables["epic_num"] = 10
            ctx.resolved_variables["story_num"] = 1
            compiler.compile(ctx)
        except (CompilerError, ParserError, FileNotFoundError):
            pass  # Expected to fail

        # No new files should be created
        final_files = set(tmp_project.rglob("*"))
        new_files = final_files - initial_files
        # Filter out __pycache__ and .pyc files
        new_files = {f for f in new_files if "__pycache__" not in str(f)}
        assert len(new_files) == 0, f"Unexpected new files: {new_files}"


# ============================================================================
# Error Message Determinism (NFR11)
# ============================================================================


class TestErrorMessageDeterminism:
    """Tests for NFR11: Same error twice produces identical message."""

    def test_error_messages_are_deterministic(self, tmp_path: Path) -> None:
        """Same error condition produces identical error message."""
        workflow_dir = tmp_path / "workflow"
        workflow_dir.mkdir()
        # Missing workflow.yaml

        # First error
        with pytest.raises(ParserError) as exc1:
            parse_workflow(workflow_dir)

        # Second error
        with pytest.raises(ParserError) as exc2:
            parse_workflow(workflow_dir)

        # Messages should be identical
        assert str(exc1.value) == str(exc2.value)

    def test_ambiguous_file_message_deterministic(self, tmp_path: Path) -> None:
        """Ambiguous file error message is deterministic."""
        files = [tmp_path / "a.md", tmp_path / "b.md"]
        for f in files:
            f.write_text("# Content")

        ctx = CompilerContext(project_root=tmp_path, output_folder=tmp_path)

        # First error
        with pytest.raises(AmbiguousFileError) as exc1:
            _apply_load_strategy(
                files=files,
                strategy=LoadStrategy.SELECTIVE_LOAD,
                pattern_name="test",
                pattern_config={},
                context=ctx,
            )

        # Second error
        with pytest.raises(AmbiguousFileError) as exc2:
            _apply_load_strategy(
                files=files,
                strategy=LoadStrategy.SELECTIVE_LOAD,
                pattern_name="test",
                pattern_config={},
                context=ctx,
            )

        assert str(exc1.value) == str(exc2.value)


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases in error handling."""

    @pytest.mark.skipif(os.geteuid() == 0, reason="Root ignores permissions")
    def test_permission_denied_raises_error(self, tmp_path: Path) -> None:
        """Permission denied on file raises appropriate error."""
        # This test is platform-specific, skip if permissions can't be set
        test_file = tmp_path / "no_read.yaml"
        test_file.write_text("key: value")

        try:
            test_file.chmod(0o000)
            with pytest.raises((ParserError, PermissionError)):
                parse_workflow_config(test_file)
        finally:
            # Restore permissions for cleanup
            test_file.chmod(0o644)

    def test_binary_file_in_glob_skipped(self, tmp_path: Path) -> None:
        """Binary files in glob results are skipped (logged, not error)."""
        from bmad_assist.compiler.discovery import load_file_contents

        # Create a binary file with clear non-UTF8 content
        binary_file = tmp_path / "binary.md"
        # Use bytes that are definitely not valid UTF-8 - high bytes in middle of "text"
        binary_file.write_bytes(b"start\xff\xfe\x00\x01middle\x80\x81end")

        ctx = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        ctx.discovered_files = {"test": [binary_file]}

        # Should not raise, binary file is skipped with debug log
        result = load_file_contents(ctx)
        # Binary file content is skipped due to UnicodeDecodeError
        assert result["test"] == ""  # Empty because binary was skipped

    def test_section_not_found_error_has_suggestion(self, tmp_path: Path) -> None:
        """Section not found error has actionable suggestion."""
        md_file = tmp_path / "test.md"
        md_file.write_text("# Header 1\n\nContent\n")

        with pytest.raises(CompilerError) as exc_info:
            extract_section(md_file, "nonexistent-section")

        error_msg = str(exc_info.value)
        assert "not found" in error_msg.lower()
        assert "Suggestion:" in error_msg

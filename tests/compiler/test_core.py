"""Tests for compiler core module.

Tests cover:
- Module structure and public API exports
- Dynamic workflow loading (success and failure cases)
- Workflow name normalization
- WorkflowCompiler protocol compliance
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.compiler import (
    CompiledWorkflow,
    CompilerContext,
    CompilerError,
    WorkflowCompiler,
    WorkflowIR,
    compile_workflow,
    get_workflow_compiler,
    parse_workflow,
)
from bmad_assist.compiler.core import WorkflowCompiler as CoreWorkflowCompiler
from bmad_assist.compiler.workflows.create_story import CreateStoryCompiler


class TestModuleStructure:
    """Test compiler module structure and public API exports."""

    def test_compiler_module_structure(self) -> None:
        """Verify compiler module exports public API."""
        from bmad_assist import compiler

        assert hasattr(compiler, "compile_workflow")
        assert hasattr(compiler, "CompilerError")
        assert hasattr(compiler, "WorkflowCompiler")
        assert hasattr(compiler, "get_workflow_compiler")

    def test_compiler_all_exports(self) -> None:
        """Verify __all__ matches actual exports."""
        from bmad_assist import compiler

        for name in compiler.__all__:
            assert hasattr(compiler, name), f"Missing export: {name}"

    def test_compiler_all_is_complete(self) -> None:
        """Verify __all__ contains all expected public symbols."""
        from bmad_assist import compiler

        expected = {
            "compile_workflow",
            "get_workflow_compiler",
            "parse_workflow",
            "resolve_variables",
            "discover_files",
            "load_file_contents",
            "extract_section",
            "filter_instructions",
            "generate_output",
            "validate_token_budget",
            "LoadStrategy",
            "WorkflowCompiler",
            "CompilerError",
            "ParserError",
            "VariableError",
            "AmbiguousFileError",
            "CompilerContext",
            "CompiledWorkflow",
            "WorkflowIR",
            "GeneratedOutput",
            "DEFAULT_SOFT_LIMIT_TOKENS",
            "DEFAULT_HARD_LIMIT_TOKENS",
            "SOFT_LIMIT_RATIO",
            "ValidateStoryCompiler",
        }
        assert set(compiler.__all__) == expected

    def test_compiler_error_importable_from_core_exceptions(self) -> None:
        """CompilerError should be importable from core.exceptions."""
        from bmad_assist.core.exceptions import BmadAssistError
        from bmad_assist.core.exceptions import CompilerError as CoreCompilerError

        assert issubclass(CoreCompilerError, BmadAssistError)

    def test_types_importable(self) -> None:
        """Verify types are importable from compiler module."""
        assert CompilerContext is not None
        assert CompiledWorkflow is not None
        assert WorkflowIR is not None


class TestDynamicWorkflowLoading:
    """Test dynamic workflow compiler loading."""

    def test_get_workflow_compiler_success(self) -> None:
        """get_workflow_compiler returns compiler for valid workflow."""
        compiler = get_workflow_compiler("create-story")
        assert compiler.workflow_name == "create-story"

    def test_workflow_name_normalization_hyphen(self) -> None:
        """Workflow names with hyphens map to underscore modules."""
        compiler = get_workflow_compiler("create-story")
        assert compiler.workflow_name == "create-story"
        assert isinstance(compiler, CreateStoryCompiler)

    def test_workflow_name_normalization_underscore(self) -> None:
        """Workflow names with underscores also work."""
        compiler = get_workflow_compiler("create_story")
        assert compiler.workflow_name == "create-story"

    def test_workflow_name_with_whitespace_stripped(self) -> None:
        """Whitespace around workflow name is stripped."""
        compiler = get_workflow_compiler("  create-story  ")
        assert compiler.workflow_name == "create-story"

    def test_get_workflow_compiler_unknown_workflow(self) -> None:
        """get_workflow_compiler raises CompilerError for unknown workflow."""
        with pytest.raises(CompilerError) as exc_info:
            get_workflow_compiler("nonexistent-workflow")
        assert "nonexistent-workflow" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()
        # Verify the attempted import path is included
        assert "bmad_assist.compiler.workflows.nonexistent_workflow" in str(exc_info.value)

    def test_get_workflow_compiler_empty_name(self) -> None:
        """get_workflow_compiler raises CompilerError for empty name."""
        with pytest.raises(CompilerError) as exc_info:
            get_workflow_compiler("")
        assert "empty" in str(exc_info.value).lower()

    def test_get_workflow_compiler_whitespace_only(self) -> None:
        """get_workflow_compiler raises CompilerError for whitespace-only name."""
        with pytest.raises(CompilerError) as exc_info:
            get_workflow_compiler("   ")
        assert "empty" in str(exc_info.value).lower()

    def test_get_workflow_compiler_syntax_error(self) -> None:
        """get_workflow_compiler raises CompilerError for module with syntax error."""
        # Mock importlib to raise SyntaxError
        with patch("bmad_assist.compiler.core.importlib.import_module") as mock_import:
            mock_import.side_effect = SyntaxError("invalid syntax")
            with pytest.raises(CompilerError) as exc_info:
                get_workflow_compiler("broken-workflow")
            assert "broken-workflow" in str(exc_info.value)
            assert "errors" in str(exc_info.value).lower()

    def test_get_workflow_compiler_import_error(self) -> None:
        """get_workflow_compiler raises CompilerError for module with import error."""
        # Mock importlib to raise ImportError
        with patch("bmad_assist.compiler.core.importlib.import_module") as mock_import:
            mock_import.side_effect = ImportError("No module named 'missing_dep'")
            with pytest.raises(CompilerError) as exc_info:
                get_workflow_compiler("broken-workflow")
            assert "broken-workflow" in str(exc_info.value)
            assert "import errors" in str(exc_info.value).lower()

    def test_get_workflow_compiler_missing_dependency_distinguished(self) -> None:
        """Missing dependency inside workflow is distinguished from missing workflow."""
        # ModuleNotFoundError with name pointing to dependency, not workflow
        err = ModuleNotFoundError("No module named 'missing_dep'")
        err.name = "missing_dep"  # type: ignore[attr-defined]
        with patch("bmad_assist.compiler.core.importlib.import_module") as mock_import:
            mock_import.side_effect = err
            with pytest.raises(CompilerError) as exc_info:
                get_workflow_compiler("create-story")
            # Should mention "missing dependency" not "not found"
            assert "missing dependency" in str(exc_info.value).lower()
            assert "missing_dep" in str(exc_info.value)

    def test_get_workflow_compiler_invalid_name_with_dot(self) -> None:
        """Workflow names with dots are rejected (import path security)."""
        with pytest.raises(CompilerError) as exc_info:
            get_workflow_compiler("create.story")
        assert "invalid workflow name" in str(exc_info.value).lower()

    def test_get_workflow_compiler_invalid_name_with_slash(self) -> None:
        """Workflow names with slashes are rejected."""
        with pytest.raises(CompilerError) as exc_info:
            get_workflow_compiler("../malicious")
        assert "invalid workflow name" in str(exc_info.value).lower()

    def test_get_workflow_compiler_invalid_name_uppercase(self) -> None:
        """Workflow names must be lowercase."""
        with pytest.raises(CompilerError) as exc_info:
            get_workflow_compiler("CreateStory")
        assert "invalid workflow name" in str(exc_info.value).lower()

    def test_get_workflow_compiler_invalid_name_starting_with_number(self) -> None:
        """Workflow names must start with a letter."""
        with pytest.raises(CompilerError) as exc_info:
            get_workflow_compiler("123-workflow")
        assert "invalid workflow name" in str(exc_info.value).lower()

    def test_get_workflow_compiler_instantiation_error(self) -> None:
        """Constructor errors are wrapped in CompilerError."""
        # Create a mock module with a class that fails on instantiation
        mock_module = type("M", (), {})()

        class FailingCompiler:
            def __init__(self) -> None:
                raise TypeError("Missing required argument")

        mock_module.CreateStoryCompiler = FailingCompiler  # type: ignore[attr-defined]

        with patch("bmad_assist.compiler.core.importlib.import_module") as mock_import:
            mock_import.return_value = mock_module
            with pytest.raises(CompilerError) as exc_info:
                get_workflow_compiler("create-story")
            assert "failed to instantiate" in str(exc_info.value).lower()
            assert "CreateStoryCompiler" in str(exc_info.value)


class TestWorkflowCompilerProtocol:
    """Test WorkflowCompiler protocol compliance."""

    def test_create_story_compiler_protocol(self) -> None:
        """CreateStoryCompiler implements WorkflowCompiler protocol."""
        compiler = CreateStoryCompiler()
        # Protocol is runtime_checkable
        assert isinstance(compiler, WorkflowCompiler)
        assert isinstance(compiler, CoreWorkflowCompiler)
        assert compiler.workflow_name == "create-story"

    def test_create_story_compiler_has_required_methods(self) -> None:
        """CreateStoryCompiler has all required protocol methods."""
        compiler = CreateStoryCompiler()

        # Check property
        assert hasattr(compiler, "workflow_name")
        assert isinstance(compiler.workflow_name, str)

        # Check methods
        assert callable(compiler.get_required_files)
        assert callable(compiler.get_variables)
        assert callable(compiler.validate_context)
        assert callable(compiler.compile)

    def test_create_story_compiler_get_required_files(self) -> None:
        """get_required_files returns list of glob patterns."""
        compiler = CreateStoryCompiler()
        files = compiler.get_required_files()

        assert isinstance(files, list)
        assert len(files) > 0
        assert all(isinstance(f, str) for f in files)
        # Should include epics pattern
        assert any("epic" in f for f in files)

    def test_create_story_compiler_get_variables(self) -> None:
        """get_variables returns dict of workflow variables."""
        compiler = CreateStoryCompiler()
        variables = compiler.get_variables()

        assert isinstance(variables, dict)
        # Should include standard story variables
        assert "epic_num" in variables
        assert "story_num" in variables

    def test_create_story_compiler_validate_context_success(self, tmp_path: Path) -> None:
        """validate_context passes for valid context with required files."""
        # Create required directory structure
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "project_context.md").write_text("# Project Context\n")

        # Create workflow directory
        workflow_dir = (
            tmp_path / "_bmad" / "bmm" / "workflows" / "4-implementation" / "create-story"
        )
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text("name: create-story\n")
        (workflow_dir / "instructions.xml").write_text("<workflow></workflow>\n")

        compiler = CreateStoryCompiler()
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=docs,
            resolved_variables={"epic_num": 10, "story_num": 1},
        )
        # Should not raise
        compiler.validate_context(context)

    def test_create_story_compiler_validate_context_missing_project_root(self) -> None:
        """validate_context raises for missing project_root."""
        compiler = CreateStoryCompiler()
        context = CompilerContext(
            project_root=None,  # type: ignore[arg-type]
            output_folder=Path("/tmp/project/docs"),
        )
        with pytest.raises(CompilerError) as exc_info:
            compiler.validate_context(context)
        assert "project_root" in str(exc_info.value)

    def test_create_story_compiler_validate_context_missing_output_folder(self) -> None:
        """validate_context raises for missing output_folder."""
        compiler = CreateStoryCompiler()
        context = CompilerContext(
            project_root=Path("/tmp/project"),
            output_folder=None,  # type: ignore[arg-type]
        )
        with pytest.raises(CompilerError) as exc_info:
            compiler.validate_context(context)
        assert "output_folder" in str(exc_info.value)

    def test_create_story_compiler_compile_returns_compiled_workflow(self, tmp_path: Path) -> None:
        """Compile returns CompiledWorkflow instance."""
        # Create required directory structure
        docs = tmp_path / "docs"
        docs.mkdir()
        sprint_artifacts = docs / "sprint-artifacts"
        sprint_artifacts.mkdir()
        epics = docs / "epics"
        epics.mkdir()

        (docs / "project_context.md").write_text("# Project Context\n")
        (epics / "epic-10.md").write_text("# Epic 10\n\n## Story 10.1: Test\n\nContent.")

        # Create workflow directory
        workflow_dir = (
            tmp_path / "_bmad" / "bmm" / "workflows" / "4-implementation" / "create-story"
        )
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text(f'''name: create-story
description: Test workflow
config_source: "{tmp_path}/_bmad/bmm/config.yaml"
template: "{{installed_path}}/template.md"
instructions: "{{installed_path}}/instructions.xml"
''')
        (workflow_dir / "instructions.xml").write_text(
            '<workflow><step n="1"><action>Test</action></step></workflow>\n'
        )
        (workflow_dir / "template.md").write_text("# Story {{epic_num}}.{{story_num}}\n")

        # Create config
        config_dir = tmp_path / "_bmad" / "bmm"
        (config_dir / "config.yaml").write_text(f"""project_name: test
output_folder: '{docs}'
sprint_artifacts: '{sprint_artifacts}'
""")

        compiler = CreateStoryCompiler()
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=docs,
            resolved_variables={"epic_num": 10, "story_num": 1},
        )
        # Pre-load workflow_ir (normally done by core.compile_workflow)
        context.workflow_ir = parse_workflow(workflow_dir)
        compiler.validate_context(context)
        result = compiler.compile(context)

        assert isinstance(result, CompiledWorkflow)
        assert result.workflow_name == "create-story"


class TestCompileWorkflowFunction:
    """Test the compile_workflow convenience function."""

    def test_compile_workflow_success(self, tmp_path: Path) -> None:
        """compile_workflow loads compiler and executes pipeline."""
        # Create required directory structure
        docs = tmp_path / "docs"
        docs.mkdir()
        sprint_artifacts = docs / "sprint-artifacts"
        sprint_artifacts.mkdir()
        epics = docs / "epics"
        epics.mkdir()

        (docs / "project_context.md").write_text("# Project Context\n")
        (epics / "epic-10.md").write_text("# Epic 10\n\n## Story 10.1: Test\n\nContent.")

        # Create workflow directory
        workflow_dir = (
            tmp_path / "_bmad" / "bmm" / "workflows" / "4-implementation" / "create-story"
        )
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text(f'''name: create-story
description: Test workflow
config_source: "{tmp_path}/_bmad/bmm/config.yaml"
template: "{{installed_path}}/template.md"
instructions: "{{installed_path}}/instructions.xml"
''')
        (workflow_dir / "instructions.xml").write_text(
            '<workflow><step n="1"><action>Test</action></step></workflow>\n'
        )
        (workflow_dir / "template.md").write_text("# Story {{epic_num}}.{{story_num}}\n")

        # Create config
        config_dir = tmp_path / "_bmad" / "bmm"
        (config_dir / "config.yaml").write_text(f"""project_name: test
output_folder: '{docs}'
sprint_artifacts: '{sprint_artifacts}'
""")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=docs,
            resolved_variables={"epic_num": 10, "story_num": 1},
        )
        # Mock discover_patch to avoid finding global/CWD patches (requires config)
        with patch("bmad_assist.compiler.patching.compiler.discover_patch", return_value=None):
            result = compile_workflow("create-story", context)

        assert isinstance(result, CompiledWorkflow)
        assert result.workflow_name == "create-story"

    def test_compile_workflow_unknown_workflow(self) -> None:
        """compile_workflow raises CompilerError for unknown workflow."""
        context = CompilerContext(
            project_root=Path("/tmp/project"),
            output_folder=Path("/tmp/project/docs"),
        )
        with pytest.raises(CompilerError) as exc_info:
            compile_workflow("nonexistent", context)
        assert "nonexistent" in str(exc_info.value)

    def test_compile_workflow_invalid_context(self) -> None:
        """compile_workflow raises CompilerError for invalid context."""
        context = CompilerContext(
            project_root=None,  # type: ignore[arg-type]
            output_folder=Path("/tmp/project/docs"),
        )
        with pytest.raises(CompilerError):
            compile_workflow("create-story", context)


class TestDataModels:
    """Test compiler data models (types)."""

    def test_workflow_ir_frozen(self) -> None:
        """WorkflowIR is immutable (frozen dataclass)."""
        ir = WorkflowIR(
            name="test",
            config_path=Path("/config.yaml"),
            instructions_path=Path("/instructions.xml"),
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="",
        )
        with pytest.raises(AttributeError):
            ir.name = "modified"  # type: ignore[misc]

    def test_compiled_workflow_frozen(self) -> None:
        """CompiledWorkflow is immutable (frozen dataclass)."""
        cw = CompiledWorkflow(
            workflow_name="test",
            mission="Test mission",
            context="",
            variables={},
            instructions="",
            output_template="",
        )
        with pytest.raises(AttributeError):
            cw.workflow_name = "modified"  # type: ignore[misc]

    def test_compiler_context_mutable(self) -> None:
        """CompilerContext is mutable for accumulating data."""
        ctx = CompilerContext(
            project_root=Path("/tmp"),
            output_folder=Path("/tmp/docs"),
        )
        # Should be able to modify
        ctx.resolved_variables["key"] = "value"
        assert ctx.resolved_variables["key"] == "value"

    def test_compiler_context_default_factories(self) -> None:
        """CompilerContext has proper default factories for dicts."""
        ctx1 = CompilerContext(
            project_root=Path("/tmp"),
            output_folder=Path("/tmp/docs"),
        )
        ctx2 = CompilerContext(
            project_root=Path("/tmp"),
            output_folder=Path("/tmp/docs"),
        )
        # Each instance should have its own dict
        ctx1.resolved_variables["key"] = "value"
        assert "key" not in ctx2.resolved_variables


class TestInteractiveElementDetection:
    """Test detection of interactive <ask> elements without patch."""

    def test_ask_element_without_patch_logs_critical(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Workflow with <ask> and no patch logs CRITICAL warning."""
        import logging

        from bmad_assist.compiler.core import _check_interactive_elements

        instructions = "<workflow><ask>What do you want?</ask><action>Do it</action></workflow>"

        with caplog.at_level(logging.CRITICAL):
            _check_interactive_elements("test-workflow", instructions, patch_path=None)

        assert "contains <ask> elements but no patch" in caplog.text
        assert "test-workflow" in caplog.text

    def test_ask_with_patch_no_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Workflow with <ask> but with patch does not log warning."""
        import logging

        from bmad_assist.compiler.core import _check_interactive_elements

        instructions = "<workflow><ask>Question</ask></workflow>"
        patch_path = tmp_path / "test.patch.yaml"

        with caplog.at_level(logging.CRITICAL):
            _check_interactive_elements("test-workflow", instructions, patch_path=patch_path)

        assert "contains <ask> elements" not in caplog.text

    def test_no_ask_element_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Workflow without <ask> does not log CRITICAL."""
        import logging

        from bmad_assist.compiler.core import _check_interactive_elements

        instructions = "<workflow><action>Do something</action><output>Show result</output></workflow>"

        with caplog.at_level(logging.CRITICAL):
            _check_interactive_elements("test-workflow", instructions, patch_path=None)

        assert "contains <ask> elements" not in caplog.text

    def test_empty_instructions_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Empty instructions do not cause warning."""
        import logging

        from bmad_assist.compiler.core import _check_interactive_elements

        with caplog.at_level(logging.CRITICAL):
            _check_interactive_elements("test-workflow", "", patch_path=None)
            _check_interactive_elements("test-workflow", None, patch_path=None)

        assert "contains <ask> elements" not in caplog.text

    def test_ask_pattern_variations(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Various <ask> tag formats are detected."""
        import logging

        from bmad_assist.compiler.core import _check_interactive_elements

        test_cases = [
            "<ask>Simple</ask>",
            "<ASK>Uppercase</ASK>",
            "<Ask>Mixed case</Ask>",
            '<ask attr="value">With attribute</ask>',
            "<ask\n>Newline</ask>",
        ]

        for instructions in test_cases:
            caplog.clear()
            with caplog.at_level(logging.CRITICAL):
                _check_interactive_elements("test", instructions, patch_path=None)
            assert "contains <ask> elements" in caplog.text, f"Failed for: {instructions}"

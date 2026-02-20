"""Tests for the security-review workflow compiler.

Tests the SecurityReviewCompiler class which implements the WorkflowCompiler
protocol for CWE-based security analysis with embedded git diff, source files,
and CWE patterns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext, WorkflowIR
from bmad_assist.compiler.workflows.security_review import (
    _CHARS_PER_TOKEN,
    SecurityReviewCompiler,
)
from bmad_assist.core.exceptions import CompilerError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def compiler() -> SecurityReviewCompiler:
    """Return a fresh SecurityReviewCompiler instance."""
    return SecurityReviewCompiler()


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal temporary project directory."""
    docs = tmp_path / "docs"
    docs.mkdir()
    return tmp_path


@pytest.fixture
def workflow_ir() -> WorkflowIR:
    """Return a minimal WorkflowIR suitable for security-review tests."""
    return WorkflowIR(
        name="security-review",
        config_path=Path("/fake/workflow.yaml"),
        instructions_path=Path("/fake/instructions.xml"),
        template_path=None,
        validation_path=None,
        raw_config={"name": "security-review"},
        raw_instructions="<workflow><step n=\"1\" goal=\"Analyze\"><action>Review code</action></step></workflow>",
    )


@pytest.fixture
def context(tmp_project: Path, workflow_ir: WorkflowIR) -> CompilerContext:
    """Return a CompilerContext with workflow_ir set."""
    return CompilerContext(
        project_root=tmp_project,
        output_folder=tmp_project / "_bmad-output",
        workflow_ir=workflow_ir,
    )


# ---------------------------------------------------------------------------
# Property and static-method tests
# ---------------------------------------------------------------------------


class TestWorkflowName:
    """Tests for the workflow_name property."""

    def test_workflow_name_returns_security_review(
        self, compiler: SecurityReviewCompiler
    ) -> None:
        """workflow_name property should return 'security-review'."""
        assert compiler.workflow_name == "security-review"


class TestGetRequiredFiles:
    """Tests for get_required_files()."""

    def test_returns_empty_list(self, compiler: SecurityReviewCompiler) -> None:
        """Security review needs no pre-glob files (diff is embedded directly)."""
        assert compiler.get_required_files() == []


class TestGetVariables:
    """Tests for get_variables()."""

    def test_returns_expected_keys(self, compiler: SecurityReviewCompiler) -> None:
        """get_variables() must contain detected_languages and security_patterns."""
        variables = compiler.get_variables()
        assert "detected_languages" in variables
        assert "security_patterns" in variables

    def test_default_values_are_empty_strings(
        self, compiler: SecurityReviewCompiler
    ) -> None:
        """Default variable values should be empty strings."""
        variables = compiler.get_variables()
        assert variables["detected_languages"] == ""
        assert variables["security_patterns"] == ""


# ---------------------------------------------------------------------------
# validate_context()
# ---------------------------------------------------------------------------


class TestValidateContext:
    """Tests for validate_context()."""

    def test_raises_for_none_project_root(
        self, compiler: SecurityReviewCompiler
    ) -> None:
        """Should raise CompilerError when project_root is None."""
        ctx = CompilerContext(
            project_root=None,  # type: ignore[arg-type]
            output_folder=Path("/tmp"),
        )
        with pytest.raises(CompilerError, match="valid directory"):
            compiler.validate_context(ctx)

    def test_raises_for_nonexistent_project_root(
        self, compiler: SecurityReviewCompiler, tmp_path: Path
    ) -> None:
        """Should raise CompilerError when project_root does not exist."""
        ctx = CompilerContext(
            project_root=tmp_path / "nonexistent",
            output_folder=tmp_path,
        )
        with pytest.raises(CompilerError, match="valid directory"):
            compiler.validate_context(ctx)

    def test_raises_for_file_as_project_root(
        self, compiler: SecurityReviewCompiler, tmp_path: Path
    ) -> None:
        """Should raise CompilerError when project_root is a file, not a dir."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("content")
        ctx = CompilerContext(
            project_root=file_path,
            output_folder=tmp_path,
        )
        with pytest.raises(CompilerError, match="valid directory"):
            compiler.validate_context(ctx)

    def test_passes_for_valid_directory(
        self, compiler: SecurityReviewCompiler, tmp_project: Path
    ) -> None:
        """Should not raise when project_root is a valid directory."""
        ctx = CompilerContext(
            project_root=tmp_project,
            output_folder=tmp_project / "_bmad-output",
        )
        # No exception means success
        compiler.validate_context(ctx)


# ---------------------------------------------------------------------------
# get_workflow_dir()
# ---------------------------------------------------------------------------


class TestGetWorkflowDir:
    """Tests for get_workflow_dir()."""

    @patch("bmad_assist.compiler.workflows.security_review.discover_workflow_dir")
    def test_returns_discovered_dir(
        self,
        mock_discover: MagicMock,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        tmp_path: Path,
    ) -> None:
        """Should return the path from discover_workflow_dir when found."""
        expected = tmp_path / "workflows" / "security-review"
        mock_discover.return_value = expected

        result = compiler.get_workflow_dir(context)

        assert result == expected
        mock_discover.assert_called_once_with(
            "security-review", context.project_root
        )

    @patch("bmad_assist.compiler.workflows.security_review.discover_workflow_dir")
    def test_raises_when_not_found(
        self,
        mock_discover: MagicMock,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
    ) -> None:
        """Should raise CompilerError when discover_workflow_dir returns None."""
        mock_discover.return_value = None

        with pytest.raises(CompilerError, match="not found"):
            compiler.get_workflow_dir(context)


# ---------------------------------------------------------------------------
# compile() — error paths
# ---------------------------------------------------------------------------


class TestCompileErrors:
    """Tests for compile() error conditions."""

    def test_raises_when_workflow_ir_is_none(
        self, compiler: SecurityReviewCompiler, tmp_project: Path
    ) -> None:
        """Should raise CompilerError when workflow_ir is not set."""
        ctx = CompilerContext(
            project_root=tmp_project,
            output_folder=tmp_project / "_bmad-output",
            workflow_ir=None,
        )
        with pytest.raises(CompilerError, match="workflow_ir not set"):
            compiler.compile(ctx)


# ---------------------------------------------------------------------------
# compile() — success path (heavy deps mocked)
# ---------------------------------------------------------------------------


class TestCompileSuccess:
    """Tests for compile() happy path with mocked heavy dependencies."""

    @pytest.fixture
    def mock_deps(self) -> dict[str, Any]:
        """Patch all heavy dependencies used by compile().

        Returns a dict of mock objects keyed by short name.
        """
        patches = {
            "capture_diff": patch(
                "bmad_assist.compiler.workflows.security_review._capture_git_diff",
                return_value="diff --git a/foo.py b/foo.py\n+import os\n",
            ),
            "detect_stack": patch(
                "bmad_assist.compiler.workflows.security_review.detect_tech_stack",
                return_value=["python", "javascript"],
            ),
            "load_patterns": patch(
                "bmad_assist.compiler.workflows.security_review.load_security_patterns",
                return_value=[
                    {"cwe_id": "CWE-79", "name": "XSS", "severity": "HIGH"},
                    {"cwe_id": "CWE-89", "name": "SQL Injection", "severity": "HIGH"},
                ],
            ),
            "filter_instr": patch(
                "bmad_assist.compiler.workflows.security_review.filter_instructions",
                return_value="<workflow><step n=\"1\"><action>Review</action></step></workflow>",
            ),
            "gen_output": patch(
                "bmad_assist.compiler.workflows.security_review.generate_output",
            ),
            "get_diff_files": patch(
                "bmad_assist.compiler.workflows.security_review.get_git_diff_files",
                return_value=["foo.py"],
            ),
            "source_ctx": patch(
                "bmad_assist.compiler.workflows.security_review.SourceContextService",
            ),
            "post_process": patch(
                "bmad_assist.compiler.workflows.security_review.apply_post_process",
                return_value="<post-processed/>",
            ),
        }
        return patches

    def _enter_patches(self, patches: dict[str, Any]) -> dict[str, MagicMock]:
        """Enter all patches and return the mock objects."""
        mocks: dict[str, MagicMock] = {}
        for key, p in patches.items():
            mocks[key] = p.start()
        return mocks

    def _exit_patches(self, patches: dict[str, Any]) -> None:
        """Stop all patches."""
        for p in patches.values():
            p.stop()

    def test_compile_returns_compiled_workflow(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
    ) -> None:
        """compile() should return a CompiledWorkflow instance."""
        mocks = self._enter_patches(mock_deps)
        try:
            # Configure generate_output to return an object with .xml
            gen_output_result = MagicMock()
            gen_output_result.xml = "<compiled-security-review>output</compiled-security-review>"
            mocks["gen_output"].return_value = gen_output_result

            # Configure SourceContextService mock
            svc_instance = MagicMock()
            svc_instance.collect_files.return_value = {"foo.py": "import os\n"}
            mocks["source_ctx"].return_value = svc_instance

            result = compiler.compile(context)

            assert isinstance(result, CompiledWorkflow)
        finally:
            self._exit_patches(mock_deps)

    def test_compiled_workflow_name_is_security_review(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
    ) -> None:
        """Compiled result must have workflow_name='security-review'."""
        mocks = self._enter_patches(mock_deps)
        try:
            gen_output_result = MagicMock()
            gen_output_result.xml = "<compiled/>"
            mocks["gen_output"].return_value = gen_output_result

            svc_instance = MagicMock()
            svc_instance.collect_files.return_value = {}
            mocks["source_ctx"].return_value = svc_instance

            result = compiler.compile(context)

            assert result.workflow_name == "security-review"
        finally:
            self._exit_patches(mock_deps)

    def test_mission_includes_detected_languages(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
    ) -> None:
        """Mission text should contain the detected language names."""
        mocks = self._enter_patches(mock_deps)
        try:
            gen_output_result = MagicMock()
            gen_output_result.xml = "<compiled/>"
            mocks["gen_output"].return_value = gen_output_result

            svc_instance = MagicMock()
            svc_instance.collect_files.return_value = {}
            mocks["source_ctx"].return_value = svc_instance

            result = compiler.compile(context)

            assert "python" in result.mission
            assert "javascript" in result.mission
        finally:
            self._exit_patches(mock_deps)

    def test_mission_includes_pattern_count(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
    ) -> None:
        """Mission text should state how many patterns were loaded."""
        mocks = self._enter_patches(mock_deps)
        try:
            gen_output_result = MagicMock()
            gen_output_result.xml = "<compiled/>"
            mocks["gen_output"].return_value = gen_output_result

            svc_instance = MagicMock()
            svc_instance.collect_files.return_value = {}
            mocks["source_ctx"].return_value = svc_instance

            result = compiler.compile(context)

            # 2 patterns loaded from mock
            assert "Patterns loaded: 2" in result.mission
        finally:
            self._exit_patches(mock_deps)

    def test_token_estimate_is_set(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
    ) -> None:
        """token_estimate should be computed from the XML result length."""
        mocks = self._enter_patches(mock_deps)
        try:
            xml_content = "x" * 400  # 400 chars -> 100 tokens at 4 chars/token
            gen_output_result = MagicMock()
            gen_output_result.xml = xml_content
            mocks["gen_output"].return_value = gen_output_result

            svc_instance = MagicMock()
            svc_instance.collect_files.return_value = {}
            mocks["source_ctx"].return_value = svc_instance

            result = compiler.compile(context)

            assert result.token_estimate == len(xml_content) // _CHARS_PER_TOKEN
            assert result.token_estimate == 100
        finally:
            self._exit_patches(mock_deps)

    def test_variables_include_detected_languages(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
    ) -> None:
        """Resolved variables should contain detected_languages as comma-separated string."""
        mocks = self._enter_patches(mock_deps)
        try:
            gen_output_result = MagicMock()
            gen_output_result.xml = "<compiled/>"
            mocks["gen_output"].return_value = gen_output_result

            svc_instance = MagicMock()
            svc_instance.collect_files.return_value = {}
            mocks["source_ctx"].return_value = svc_instance

            result = compiler.compile(context)

            assert result.variables["detected_languages"] == "python, javascript"
        finally:
            self._exit_patches(mock_deps)

    def test_variables_include_languages_list_and_patterns_count(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
    ) -> None:
        """Resolved variables should expose detected_languages_list and patterns_loaded_count."""
        mocks = self._enter_patches(mock_deps)
        try:
            gen_output_result = MagicMock()
            gen_output_result.xml = "<compiled/>"
            mocks["gen_output"].return_value = gen_output_result

            svc_instance = MagicMock()
            svc_instance.collect_files.return_value = {}
            mocks["source_ctx"].return_value = svc_instance

            result = compiler.compile(context)

            assert result.variables["detected_languages_list"] == ["python", "javascript"]
            assert result.variables["patterns_loaded_count"] == 2
        finally:
            self._exit_patches(mock_deps)

    def test_compile_with_no_diff(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
    ) -> None:
        """compile() should handle empty diff gracefully."""
        mocks = self._enter_patches(mock_deps)
        try:
            # Override diff to return empty string
            mocks["capture_diff"].return_value = ""
            mocks["detect_stack"].return_value = []

            gen_output_result = MagicMock()
            gen_output_result.xml = "<compiled/>"
            mocks["gen_output"].return_value = gen_output_result

            result = compiler.compile(context)

            assert result.workflow_name == "security-review"
            # No languages detected -> "unknown"
            assert "unknown" in result.mission
        finally:
            self._exit_patches(mock_deps)

    def test_compile_applies_post_process_when_patch_path_set(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """When context.patch_path is set, apply_post_process should be called."""
        mocks = self._enter_patches(mock_deps)
        try:
            gen_output_result = MagicMock()
            gen_output_result.xml = "<original/>"
            mocks["gen_output"].return_value = gen_output_result

            svc_instance = MagicMock()
            svc_instance.collect_files.return_value = {}
            mocks["source_ctx"].return_value = svc_instance

            # Set patch_path to trigger post-processing
            context.patch_path = tmp_path / "security-review.patch.yaml"

            result = compiler.compile(context)

            mocks["post_process"].assert_called_once()
            # The context field should contain the post-processed result
            assert result.context == "<post-processed/>"
        finally:
            self._exit_patches(mock_deps)

    def test_compile_skips_post_process_when_no_patch_path(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
    ) -> None:
        """When context.patch_path is None, apply_post_process should not be called."""
        mocks = self._enter_patches(mock_deps)
        try:
            gen_output_result = MagicMock()
            gen_output_result.xml = "<original/>"
            mocks["gen_output"].return_value = gen_output_result

            svc_instance = MagicMock()
            svc_instance.collect_files.return_value = {}
            mocks["source_ctx"].return_value = svc_instance

            # Ensure no patch path
            context.patch_path = None

            result = compiler.compile(context)

            mocks["post_process"].assert_not_called()
            # context should be the raw XML
            assert result.context == "<original/>"
        finally:
            self._exit_patches(mock_deps)

    def test_generate_output_called_with_context_files(
        self,
        compiler: SecurityReviewCompiler,
        context: CompilerContext,
        mock_deps: dict[str, Any],
    ) -> None:
        """generate_output should receive context_files including patterns and diff."""
        mocks = self._enter_patches(mock_deps)
        try:
            gen_output_result = MagicMock()
            gen_output_result.xml = "<compiled/>"
            mocks["gen_output"].return_value = gen_output_result

            svc_instance = MagicMock()
            svc_instance.collect_files.return_value = {"foo.py": "import os\n"}
            mocks["source_ctx"].return_value = svc_instance

            compiler.compile(context)

            # Verify generate_output was called
            mocks["gen_output"].assert_called_once()
            call_kwargs = mocks["gen_output"].call_args
            context_files = call_kwargs.kwargs.get("context_files") or call_kwargs[1].get("context_files")

            # Should have security-patterns, source file, and git diff
            assert "security-patterns" in context_files
            assert "foo.py" in context_files
            assert "[git-diff]" in context_files
        finally:
            self._exit_patches(mock_deps)

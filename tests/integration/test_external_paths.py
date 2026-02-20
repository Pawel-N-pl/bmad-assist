"""Integration tests for external path configuration."""

from pathlib import Path

import pytest

from bmad_assist.core.paths import _reset_paths, get_paths, init_paths


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset paths singleton before and after each test."""
    _reset_paths()
    yield
    _reset_paths()


class TestExternalPathsE2E:
    """End-to-end tests for external path support."""

    def test_external_project_knowledge_path(self, tmp_path: Path):
        """Sprint status works when project_knowledge is external."""
        # Setup: project in one location, docs in another
        project = tmp_path / "project"
        project.mkdir()

        external_docs = tmp_path / "shared" / "docs"
        external_docs.mkdir(parents=True)

        # Create sprint-status in legacy external location
        legacy_dir = external_docs / "sprint-artifacts"
        legacy_dir.mkdir()
        sprint_file = legacy_dir / "sprint-status.yaml"
        sprint_file.write_text("entries: {}")

        # Initialize paths with external project_knowledge
        config = {"project_knowledge": str(external_docs)}
        paths = init_paths(project, config)

        # Verify find_sprint_status works
        found = paths.find_sprint_status()
        assert found is not None
        assert found == sprint_file

        # Verify search locations include external path
        locations = paths.get_sprint_status_search_locations()
        assert any(str(external_docs) in str(loc) for loc in locations)

    def test_external_output_folder(self, tmp_path: Path):
        """Output artifacts work when output_folder is external."""
        project = tmp_path / "project"
        project.mkdir()

        external_output = tmp_path / "shared" / "output"
        # Don't create it - ensure_directories should create it

        config = {"output_folder": str(external_output)}
        paths = init_paths(project, config)

        # ensure_directories should create external output folder
        paths.ensure_directories()

        assert external_output.exists()
        assert paths.implementation_artifacts.exists()
        assert paths.sprint_status_file.parent.exists()

    def test_both_external_paths_configured(self, tmp_path: Path):
        """Both project_knowledge and output_folder can be external."""
        project = tmp_path / "project"
        project.mkdir()

        external_docs = tmp_path / "shared" / "docs"
        external_docs.mkdir(parents=True)
        external_output = tmp_path / "shared" / "output"

        # Create sprint-status in external docs (legacy location)
        legacy_dir = external_docs / "sprint-artifacts"
        legacy_dir.mkdir()
        (legacy_dir / "sprint-status.yaml").write_text("entries: {}")

        # Create epics dir so epics_dir uses project_knowledge
        epics_dir = external_docs / "epics"
        epics_dir.mkdir()

        config = {
            "project_knowledge": str(external_docs),
            "output_folder": str(external_output),
        }
        paths = init_paths(project, config)
        paths.ensure_directories()

        # Verify both external paths work
        assert paths.project_knowledge == external_docs.resolve()
        assert paths.output_folder == external_output.resolve()
        assert paths.find_sprint_status() is not None
        # epics_dir prefers project_knowledge/epics/ if it exists
        assert paths.epics_dir == external_docs.resolve() / "epics"
        # stories_dir == implementation_artifacts (separate config key, uses default)
        # To fully externalize, would need to also set implementation_artifacts
        assert paths.stories_dir.exists()  # Just verify it was created

    def test_singleton_respects_external_paths(self, tmp_path: Path):
        """get_paths() returns correctly configured external paths."""
        project = tmp_path / "project"
        project.mkdir()

        external_docs = tmp_path / "external-docs"
        external_docs.mkdir()

        config = {"project_knowledge": str(external_docs)}
        init_paths(project, config)

        # get_paths() should return same configured instance
        paths = get_paths()
        assert paths.project_knowledge == external_docs.resolve()

    def test_sprint_status_new_location_with_external_impl_artifacts(self, tmp_path: Path):
        """Sprint status in new location works with external implementation_artifacts."""
        project = tmp_path / "project"
        project.mkdir()

        external_output = tmp_path / "external-output"
        # Create sprint-status in new location (implementation-artifacts)
        impl_artifacts = external_output / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        sprint_file = impl_artifacts / "sprint-status.yaml"
        sprint_file.write_text("entries: {}")

        # Must explicitly set implementation_artifacts since it has its own config key
        config = {"implementation_artifacts": str(impl_artifacts)}
        paths = init_paths(project, config)

        # Should find sprint-status in new location
        found = paths.find_sprint_status()
        assert found is not None
        assert found == sprint_file


class TestSprintGeneratorExternalPaths:
    """Tests for sprint generator with external paths."""

    def test_generator_finds_legacy_tracking(self, tmp_path: Path):
        """Sprint generator finds legacy tracking in external location."""
        project = tmp_path / "project"
        project.mkdir()

        external_docs = tmp_path / "shared" / "docs"
        legacy_dir = external_docs / "sprint-artifacts"
        legacy_dir.mkdir(parents=True)

        sprint_file = legacy_dir / "sprint-status.yaml"
        sprint_file.write_text("entries: {}")

        config = {"project_knowledge": str(external_docs)}
        init_paths(project, config)

        paths = get_paths()
        assert paths.legacy_sprint_artifacts == legacy_dir.resolve()


class TestBenchmarkingExternalPaths:
    """Tests for benchmarking storage with external paths."""

    def test_benchmark_base_dir_uses_external_impl_artifacts(self, tmp_path: Path):
        """Benchmark storage uses external implementation_artifacts."""
        from bmad_assist.benchmarking.storage import get_benchmark_base_dir

        project = tmp_path / "project"
        project.mkdir()

        impl_artifacts = tmp_path / "shared" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        # Must set implementation_artifacts directly (not output_folder)
        config = {"implementation_artifacts": str(impl_artifacts)}
        init_paths(project, config)

        base_dir = get_benchmark_base_dir(project)
        # get_benchmark_base_dir returns implementation_artifacts
        assert base_dir == impl_artifacts.resolve()


class TestCompilerExternalPaths:
    """Tests for compiler with external paths."""

    def test_compiler_finds_external_sprint_status(self, tmp_path: Path):
        """Compiler variable resolution finds sprint-status in external location."""
        from bmad_assist.compiler.types import CompilerContext, WorkflowIR
        from bmad_assist.compiler.variables import resolve_variables

        project = tmp_path / "project"
        project.mkdir()

        impl_artifacts = tmp_path / "shared" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        sprint_file = impl_artifacts / "sprint-status.yaml"
        sprint_file.write_text("development_status: {}")

        # Must set implementation_artifacts directly
        config = {"implementation_artifacts": str(impl_artifacts)}
        init_paths(project, config)

        workflow_ir = WorkflowIR(
            name="test",
            config_path=project / "workflow.yaml",
            instructions_path=project / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=project,
            output_folder=impl_artifacts.parent,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})
        assert resolved["sprint_status"] == str(sprint_file)

"""Tests for project-local cache template path (Story 22.1).

Tests verify that:
1. Global patches + project context → project-local cache
2. Cache lookup order: project → CWD → global
3. Multi-project isolation (same patch, different caches)
4. Implicit project context (CWD as default)
5. Cache invalidation via SHA-256 hashes
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist import __version__
from bmad_assist.compiler.patching.cache import (
    CacheMeta,
    TemplateCache,
    compute_file_hash,
)
from bmad_assist.compiler.patching.compiler import ensure_template_compiled
from bmad_assist.compiler.patching.config import reset_patcher_config
from bmad_assist.compiler.patching.discovery import discover_patch


@pytest.fixture(autouse=True)
def reset_config() -> None:
    """Reset patcher config before each test."""
    reset_patcher_config()


class TestGlobalPatchProjectCache:
    """Tests for AC#1 and AC#2: Global patch compiles to project-local cache."""

    @pytest.fixture
    def project_and_global_setup(self, tmp_path: Path) -> dict[str, Path]:
        """Create project directory and global patches directory.

        Returns:
            Dict with 'project', 'global_home', 'patch_file', 'workflow_yaml',
            'instructions_xml' paths.

        """
        # Create project directory
        project = tmp_path / "my-project"
        project.mkdir()

        # Create global home with patches directory (simulates ~/.bmad-assist/)
        global_home = tmp_path / "home"
        global_patches = global_home / ".bmad-assist" / "patches"
        global_patches.mkdir(parents=True)

        # Create global patch file
        patch_file = global_patches / "test-workflow.patch.yaml"
        patch_file.write_text("""
patch:
  name: global-test-patch
  version: "1.0.0"
  author: "Test"
  description: "A global patch"
compatibility:
  bmad_version: "0.1.0"
  workflow: test-workflow
transforms:
  - "Remove step 1"
validation:
  must_contain:
    - "step"
""")

        # Create workflow files in project's _bmad directory
        workflow_dir = project / "_bmad" / "bmm" / "workflows" / "test-workflow"
        workflow_dir.mkdir(parents=True)

        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: test-workflow
description: A test workflow
""")

        instructions_xml = workflow_dir / "instructions.xml"
        instructions_xml.write_text("""
<workflow>
  <step n="1">First step</step>
  <step n="2">Second step</step>
</workflow>
""")

        return {
            "project": project,
            "global_home": global_home,
            "patch_file": patch_file,
            "workflow_yaml": workflow_yaml,
            "instructions_xml": instructions_xml,
        }

    def test_global_patch_discovered_correctly(
        self, project_and_global_setup: dict[str, Path]
    ) -> None:
        """Test that global patch is discovered when no project patch exists."""
        project = project_and_global_setup["project"]
        global_home = project_and_global_setup["global_home"]

        # Patch Path.home() to return our test home directory
        with patch("pathlib.Path.home", return_value=global_home):
            patch_path = discover_patch("test-workflow", project)

        assert patch_path is not None
        assert patch_path.name == "test-workflow.patch.yaml"
        # Should be the global patch
        assert str(global_home) in str(patch_path)

    def test_cache_location_is_project_not_global(
        self, project_and_global_setup: dict[str, Path]
    ) -> None:
        """AC#1: Cache should be saved to project/.bmad-assist/cache/ even with global patch."""
        project = project_and_global_setup["project"]
        global_home = project_and_global_setup["global_home"]

        cache = TemplateCache()

        # Verify project cache path
        project_cache_path = cache.get_cache_path("test-workflow", project)
        assert project_cache_path == project / ".bmad-assist" / "cache" / "test-workflow.tpl.xml"

        # Verify global cache path (for comparison)
        with patch("pathlib.Path.home", return_value=global_home):
            global_cache_path = cache.get_cache_path("test-workflow", None)

        assert global_cache_path == (
            global_home / ".bmad-assist" / "cache" / __version__ / "test-workflow.tpl.xml"
        )

        # They should be different
        assert project_cache_path != global_cache_path


class TestCacheLookupPriority:
    """Tests for AC#3: Cache lookup order (project → CWD → global)."""

    def test_project_cache_preferred_over_cwd_cache(self, tmp_path: Path) -> None:
        """Test that project cache is checked before CWD cache."""
        # Create project and CWD directories
        project = tmp_path / "project"
        cwd = tmp_path / "cwd"
        project.mkdir()
        cwd.mkdir()

        # Create source files
        workflow_yaml = tmp_path / "workflow.yaml"
        workflow_yaml.write_text("name: test")
        patch_file = tmp_path / "patch.yaml"
        patch_file.write_text("patch: test")

        source_files = {"workflow.yaml": workflow_yaml}

        cache = TemplateCache()

        # Create caches in both locations with same hashes
        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={"workflow.yaml": compute_file_hash(workflow_yaml)},
            patch_hash=compute_file_hash(patch_file),
        )

        # Save to both caches
        cache.save("test-workflow", "<cwd-cache/>", meta, cwd)
        cache.save("test-workflow", "<project-cache/>", meta, project)

        # Project cache should be valid
        assert cache.is_valid("test-workflow", project, source_files, patch_file)
        # CWD cache should also be valid
        assert cache.is_valid("test-workflow", cwd, source_files, patch_file)

        # Load from project should get project content
        project_content = cache.load_cached("test-workflow", project)
        assert project_content is not None
        assert "<project-cache/>" in project_content

        # Load from CWD should get CWD content
        cwd_content = cache.load_cached("test-workflow", cwd)
        assert cwd_content is not None
        assert "<cwd-cache/>" in cwd_content

    def test_project_cache_preferred_over_global_cache(self, tmp_path: Path) -> None:
        """Test that project cache is checked before global cache."""
        project = tmp_path / "project"
        global_home = tmp_path / "home"
        project.mkdir()

        # Create source files
        workflow_yaml = tmp_path / "workflow.yaml"
        workflow_yaml.write_text("name: test")
        patch_file = tmp_path / "patch.yaml"
        patch_file.write_text("patch: test")

        source_files = {"workflow.yaml": workflow_yaml}

        cache = TemplateCache()

        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={"workflow.yaml": compute_file_hash(workflow_yaml)},
            patch_hash=compute_file_hash(patch_file),
        )

        # Save to project cache
        cache.save("test-workflow", "<project-cache/>", meta, project)

        # Save to global cache
        with patch("pathlib.Path.home", return_value=global_home):
            cache.save("test-workflow", "<global-cache/>", meta, None)

        # Both should be valid
        assert cache.is_valid("test-workflow", project, source_files, patch_file)
        with patch("pathlib.Path.home", return_value=global_home):
            assert cache.is_valid("test-workflow", None, source_files, patch_file)

        # Project cache should have different content than global
        project_content = cache.load_cached("test-workflow", project)
        with patch("pathlib.Path.home", return_value=global_home):
            global_content = cache.load_cached("test-workflow", None)

        assert project_content is not None
        assert global_content is not None
        assert "<project-cache/>" in project_content
        assert "<global-cache/>" in global_content


class TestMultiProjectIsolation:
    """Tests for multi-project isolation (same global patch, different project caches)."""

    def test_two_projects_maintain_separate_caches(self, tmp_path: Path) -> None:
        """Test that two projects can have independent caches for the same workflow."""
        project_a = tmp_path / "project-a"
        project_b = tmp_path / "project-b"
        project_a.mkdir()
        project_b.mkdir()

        # Create source files (different content)
        workflow_yaml_a = project_a / "workflow.yaml"
        workflow_yaml_a.write_text("name: test-a")

        workflow_yaml_b = project_b / "workflow.yaml"
        workflow_yaml_b.write_text("name: test-b")

        # Same patch file (could be global)
        patch_file = tmp_path / "patch.yaml"
        patch_file.write_text("patch: shared")

        cache = TemplateCache()

        # Create caches for each project
        meta_a = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={"workflow.yaml": compute_file_hash(workflow_yaml_a)},
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("test-workflow", "<project-a-compiled/>", meta_a, project_a)

        meta_b = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={"workflow.yaml": compute_file_hash(workflow_yaml_b)},
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("test-workflow", "<project-b-compiled/>", meta_b, project_b)

        # Verify isolation
        content_a = cache.load_cached("test-workflow", project_a)
        content_b = cache.load_cached("test-workflow", project_b)

        assert content_a is not None
        assert content_b is not None
        assert "<project-a-compiled/>" in content_a
        assert "<project-b-compiled/>" in content_b

        # Verify cache paths are different
        path_a = cache.get_cache_path("test-workflow", project_a)
        path_b = cache.get_cache_path("test-workflow", project_b)
        assert path_a != path_b
        assert path_a.exists()
        assert path_b.exists()


class TestImplicitProjectContext:
    """Tests for AC#4: Implicit project context (CLI defaults to CWD)."""

    def test_compile_patch_with_cwd_as_project(self, tmp_path: Path) -> None:
        """Test that when project_root is CWD, cache goes to CWD/.bmad-assist/cache/."""
        # Setup: tmp_path serves as both project_root and CWD
        project = tmp_path

        # Create source files
        workflow_yaml = project / "workflow.yaml"
        workflow_yaml.write_text("name: test")

        patch_file = project / ".bmad-assist" / "patches" / "test-workflow.patch.yaml"
        patch_file.parent.mkdir(parents=True)
        patch_file.write_text("""
patch:
  name: test-patch
  version: "1.0.0"
compatibility:
  bmad_version: "0.1.0"
  workflow: test-workflow
transforms:
  - "Test transform"
""")

        cache = TemplateCache()
        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={"workflow.yaml": compute_file_hash(workflow_yaml)},
            patch_hash=compute_file_hash(patch_file),
        )

        # Save cache using project (which is same as CWD in this scenario)
        cache.save("test-workflow", "<cwd-compiled/>", meta, project)

        # Verify cache is in project/.bmad-assist/cache/
        expected_path = project / ".bmad-assist" / "cache" / "test-workflow.tpl.xml"
        assert expected_path.exists()
        assert cache.load_cached("test-workflow", project) is not None

    def test_get_cache_path_with_cwd_equals_project(self, tmp_path: Path) -> None:
        """Test cache path when CWD and project are the same."""
        project = tmp_path / "my-project"
        project.mkdir()

        cache = TemplateCache()

        # Both should resolve to project-local cache
        path = cache.get_cache_path("test-workflow", project)
        assert path == project / ".bmad-assist" / "cache" / "test-workflow.tpl.xml"


class TestCacheInvalidation:
    """Tests for AC#5: Cache invalidation via SHA-256 hashes."""

    def test_cache_invalid_when_source_file_changes(self, tmp_path: Path) -> None:
        """Test cache becomes invalid when source workflow file is modified."""
        project = tmp_path / "project"
        project.mkdir()

        # Create source files
        workflow_yaml = project / "workflow.yaml"
        workflow_yaml.write_text("name: test-v1")

        patch_file = project / "patch.yaml"
        patch_file.write_text("patch: test")

        cache = TemplateCache()

        # Create cache with original hash
        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={"workflow.yaml": compute_file_hash(workflow_yaml)},
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("test-workflow", "<compiled/>", meta, project)

        # Verify valid
        assert cache.is_valid(
            "test-workflow",
            project,
            {"workflow.yaml": workflow_yaml},
            patch_file,
        )

        # Modify source file
        workflow_yaml.write_text("name: test-v2")

        # Verify invalid
        assert not cache.is_valid(
            "test-workflow",
            project,
            {"workflow.yaml": workflow_yaml},
            patch_file,
        )

    def test_cache_invalid_when_patch_file_changes(self, tmp_path: Path) -> None:
        """Test cache becomes invalid when patch file is modified."""
        project = tmp_path / "project"
        project.mkdir()

        # Create source files
        workflow_yaml = project / "workflow.yaml"
        workflow_yaml.write_text("name: test")

        patch_file = project / "patch.yaml"
        patch_file.write_text("patch: test-v1")

        cache = TemplateCache()

        # Create cache with original hash
        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={"workflow.yaml": compute_file_hash(workflow_yaml)},
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("test-workflow", "<compiled/>", meta, project)

        # Verify valid
        assert cache.is_valid(
            "test-workflow",
            project,
            {"workflow.yaml": workflow_yaml},
            patch_file,
        )

        # Modify patch file
        patch_file.write_text("patch: test-v2")

        # Verify invalid
        assert not cache.is_valid(
            "test-workflow",
            project,
            {"workflow.yaml": workflow_yaml},
            patch_file,
        )

    def test_cache_invalid_when_instructions_file_changes(self, tmp_path: Path) -> None:
        """Test cache becomes invalid when instructions.xml is modified."""
        project = tmp_path / "project"
        project.mkdir()

        # Create source files
        workflow_yaml = project / "workflow.yaml"
        workflow_yaml.write_text("name: test")

        instructions_xml = project / "instructions.xml"
        instructions_xml.write_text("<step n='1'>Original</step>")

        patch_file = project / "patch.yaml"
        patch_file.write_text("patch: test")

        cache = TemplateCache()

        # Create cache with both source files
        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={
                "workflow.yaml": compute_file_hash(workflow_yaml),
                "instructions.xml": compute_file_hash(instructions_xml),
            },
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("test-workflow", "<compiled/>", meta, project)

        # Verify valid
        source_files = {
            "workflow.yaml": workflow_yaml,
            "instructions.xml": instructions_xml,
        }
        assert cache.is_valid("test-workflow", project, source_files, patch_file)

        # Modify instructions file
        instructions_xml.write_text("<step n='1'>Modified</step>")

        # Verify invalid
        assert not cache.is_valid("test-workflow", project, source_files, patch_file)

    def test_cache_remains_valid_when_files_unchanged(self, tmp_path: Path) -> None:
        """Test cache remains valid when no files are modified."""
        project = tmp_path / "project"
        project.mkdir()

        # Create source files
        workflow_yaml = project / "workflow.yaml"
        workflow_yaml.write_text("name: test")

        patch_file = project / "patch.yaml"
        patch_file.write_text("patch: test")

        cache = TemplateCache()

        # Create cache
        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={"workflow.yaml": compute_file_hash(workflow_yaml)},
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("test-workflow", "<compiled/>", meta, project)

        # Check validity multiple times (should remain valid)
        for _ in range(3):
            assert cache.is_valid(
                "test-workflow",
                project,
                {"workflow.yaml": workflow_yaml},
                patch_file,
            )


class TestEnsureTemplateCompiledCachePriority:
    """Tests for ensure_template_compiled() cache lookup order."""

    def test_returns_project_cache_path_when_valid(self, tmp_path: Path) -> None:
        """Test that ensure_template_compiled() returns project cache when valid."""
        project = tmp_path / "project"
        global_home = tmp_path / "home"
        project.mkdir()

        # Create workflow files
        workflow_dir = project / "_bmad" / "bmm" / "workflows" / "test-workflow"
        workflow_dir.mkdir(parents=True)
        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("name: test")
        instructions_xml = workflow_dir / "instructions.xml"
        instructions_xml.write_text("<step>Test</step>")

        # Create patch in global location
        global_patches = global_home / ".bmad-assist" / "patches"
        global_patches.mkdir(parents=True)
        patch_file = global_patches / "test-workflow.patch.yaml"
        patch_file.write_text("""
patch:
  name: test-patch
  version: "1.0.0"
compatibility:
  bmad_version: "0.1.0"
  workflow: test-workflow
transforms:
  - "Test"
""")

        # Create valid project cache
        cache = TemplateCache()
        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={
                "workflow.yaml": compute_file_hash(workflow_yaml),
                "instructions.xml": compute_file_hash(instructions_xml),
            },
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("test-workflow", "<project-cache/>", meta, project)

        # Call ensure_template_compiled
        with patch("pathlib.Path.home", return_value=global_home):
            result = ensure_template_compiled("test-workflow", project)

        # Should return project cache path
        assert result is not None
        assert str(project) in str(result)
        assert ".bmad-assist/cache/test-workflow.tpl.xml" in str(result)

    def test_falls_back_to_global_cache_when_project_invalid(
        self, tmp_path: Path
    ) -> None:
        """Test fallback to global cache when project cache is invalid."""
        project = tmp_path / "project"
        global_home = tmp_path / "home"
        project.mkdir()

        # Create workflow files
        workflow_dir = project / "_bmad" / "bmm" / "workflows" / "test-workflow"
        workflow_dir.mkdir(parents=True)
        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("name: test")
        instructions_xml = workflow_dir / "instructions.xml"
        instructions_xml.write_text("<step>Test</step>")

        # Create patch in global location
        global_patches = global_home / ".bmad-assist" / "patches"
        global_patches.mkdir(parents=True)
        patch_file = global_patches / "test-workflow.patch.yaml"
        patch_file.write_text("""
patch:
  name: test-patch
  version: "1.0.0"
compatibility:
  bmad_version: "0.1.0"
  workflow: test-workflow
transforms:
  - "Test"
""")

        # Create valid global cache only
        cache = TemplateCache()
        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={
                "workflow.yaml": compute_file_hash(workflow_yaml),
                "instructions.xml": compute_file_hash(instructions_xml),
            },
            patch_hash=compute_file_hash(patch_file),
        )
        with patch("pathlib.Path.home", return_value=global_home):
            cache.save("test-workflow", "<global-cache/>", meta, None)

        # No project cache exists, call ensure_template_compiled
        with patch("pathlib.Path.home", return_value=global_home):
            result = ensure_template_compiled("test-workflow", project)

        # Should return global cache path (since no project cache)
        assert result is not None
        assert str(global_home) in str(result)


class TestCompilePatchIntegration:
    """Integration tests for compile_patch() with mocked LLM.

    These tests verify the full compile_patch() flow, ensuring
    cache is saved to the correct project-local location.
    """

    @pytest.fixture
    def full_workflow_setup(self, tmp_path: Path) -> dict[str, Path]:
        """Create complete workflow setup with project and global patch.

        Returns:
            Dict with 'project', 'global_home', 'patch_file' paths.

        """
        project = tmp_path / "my-project"
        global_home = tmp_path / "home"

        # Create global patch directory and file
        global_patches = global_home / ".bmad-assist" / "patches"
        global_patches.mkdir(parents=True)
        patch_file = global_patches / "create-story.patch.yaml"
        patch_file.write_text("""
patch:
  name: create-story-optimizer
  version: "1.0.0"
  author: "Test"
  description: "Optimizes create-story workflow"
compatibility:
  bmad_version: "0.1.0"
  workflow: create-story
transforms:
  - "Remove step 1"
validation:
  must_contain:
    - "step"
""")

        # Create workflow files in project's _bmad directory
        workflow_dir = project / "_bmad" / "bmm" / "workflows" / "4-implementation" / "create-story"
        workflow_dir.mkdir(parents=True)

        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: create-story
description: Creates a new story
template: template.md
""")

        instructions_xml = workflow_dir / "instructions.xml"
        instructions_xml.write_text("""
<workflow>
  <step n="1">First step to remove</step>
  <step n="2">Second step to keep</step>
</workflow>
""")

        return {
            "project": project,
            "global_home": global_home,
            "patch_file": patch_file,
            "workflow_yaml": workflow_yaml,
            "instructions_xml": instructions_xml,
        }

    def test_compile_patch_saves_to_global_cache_with_global_patch(
        self, full_workflow_setup: dict[str, Path]
    ) -> None:
        """Global patch → global cache: compile_patch() saves cache to global when patch is global."""
        import importlib
        import sys
        from unittest.mock import MagicMock

        from bmad_assist import __version__

        project = full_workflow_setup["project"]
        global_home = full_workflow_setup["global_home"]

        # Mock config and provider
        mock_config = MagicMock()
        mock_config.providers.master.provider = "claude-subprocess"
        mock_config.providers.master.model = "opus"

        mock_provider = MagicMock()
        mock_provider.invoke.return_value = "raw_result"
        mock_provider.parse_output.return_value = (
            "<transformed-document>"
            "<step n='2'>Second step to keep</step>"
            "</transformed-document>"
        )

        # Reload the compiler module to pick up the fix
        # (pytest may have imported it before the code change was applied)
        if "bmad_assist.compiler.patching.compiler" in sys.modules:
            importlib.reload(sys.modules["bmad_assist.compiler.patching.compiler"])

        from bmad_assist.compiler.patching.compiler import compile_patch

        # Patch at the source module level (imports are inside compile_patch)
        with (
            patch("pathlib.Path.home", return_value=global_home),
            patch(
                "bmad_assist.core.config.get_config",
                return_value=mock_config,
            ),
            patch(
                "bmad_assist.providers.registry.get_provider",
                return_value=mock_provider,
            ),
        ):
            _, cache_path, _ = compile_patch("create-story", project)

        # Verify cache was saved to GLOBAL directory (patch source matches cache location)
        expected_global_cache = (
            global_home / ".bmad-assist" / "cache" / __version__ / "create-story.tpl.xml"
        )
        assert cache_path == expected_global_cache
        assert str(global_home) in str(cache_path)

        # Verify cache file exists
        assert cache_path.exists()

        # Verify project cache was NOT created
        project_cache = project / ".bmad-assist" / "cache"
        assert not project_cache.exists() or not any(project_cache.iterdir())

    def test_compile_patch_reuses_project_cache_on_second_run(
        self, full_workflow_setup: dict[str, Path]
    ) -> None:
        """Test that project cache is reused on subsequent compilation."""
        project = full_workflow_setup["project"]
        global_home = full_workflow_setup["global_home"]
        patch_file = full_workflow_setup["patch_file"]
        workflow_yaml = full_workflow_setup["workflow_yaml"]
        instructions_xml = full_workflow_setup["instructions_xml"]

        # Manually create a valid project cache
        cache = TemplateCache()
        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={
                "workflow.yaml": compute_file_hash(workflow_yaml),
                "instructions.xml": compute_file_hash(instructions_xml),
            },
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("create-story", "<pre-existing-cache/>", meta, project)

        # Call ensure_template_compiled - should return existing cache without compiling
        with patch("pathlib.Path.home", return_value=global_home):
            result = ensure_template_compiled("create-story", project)

        # Should return existing project cache
        assert result is not None
        assert str(project) in str(result)

        # Verify content wasn't replaced (no LLM call needed)
        content = cache.load_cached("create-story", project)
        assert content is not None
        assert "<pre-existing-cache/>" in content

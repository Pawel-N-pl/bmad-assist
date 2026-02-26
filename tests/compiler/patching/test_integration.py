"""End-to-end integration tests for patch compilation."""

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bmad_assist.compiler.patching import (
    CacheMeta,
    PatchSession,
    TemplateCache,
    TemplateMetadata,
    TransformResult,
    Validation,
    check_threshold,
    compute_file_hash,
    discover_patch,
    generate_template,
    load_patch,
    validate_output,
)
from bmad_assist.compiler.patching.config import reset_patcher_config
from bmad_assist.core.exceptions import PatchError


@pytest.fixture(autouse=True)
def reset_config() -> None:
    """Reset patcher config before each test."""
    reset_patcher_config()


class TestFullPipeline:
    """Tests for full patch compilation pipeline."""

    def test_load_to_session_pipeline(self, tmp_path: Path) -> None:
        """Test loading a patch and running a session."""
        # Create patch file
        patch_dir = tmp_path / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "test-workflow.patch.yaml"
        patch_file.write_text("""
patch:
  name: test-patch
  version: "1.0.0"
  author: "Test Author"
  description: "Test patch"
compatibility:
  bmad_version: "0.1.0"
  workflow: test-workflow
transforms:
  - "Remove step 1 completely"
validation:
  must_contain:
    - "step"
  must_not_contain:
    - "removed"
""")

        # Discover and load patch
        patch_path = discover_patch("test-workflow", tmp_path)
        assert patch_path is not None

        patch = load_patch(patch_path)
        assert patch.config.name == "test-patch"
        assert len(patch.transforms) == 1
        assert patch.transforms[0] == "Remove step 1 completely"
        assert patch.validation is not None
        assert len(patch.validation.must_contain) == 1

    def test_session_with_mocked_provider(self, tmp_path: Path) -> None:
        """Test full session with mocked LLM provider."""
        # Create workflow content
        workflow_content = "<step n='1'>First</step><step n='2'>Second</step>"

        # Create instructions
        instructions = ["Remove step 1 completely"]

        # Mock provider - batch mode: single invoke call, returns transformed doc
        mock_provider = MagicMock()
        mock_provider.invoke.return_value = "raw_result"
        mock_provider.parse_output.return_value = (
            "<transformed-document><step n='2'>Second</step></transformed-document>"
        )

        # Run session
        session = PatchSession(workflow_content, instructions, mock_provider)
        result, transform_results = session.run()

        # Verify - batch mode: single LLM call with disable_tools=True
        assert mock_provider.invoke.call_count == 1
        call_kwargs = mock_provider.invoke.call_args.kwargs
        assert call_kwargs.get("disable_tools") is True
        assert "<step n='2'>Second</step>" in result
        assert len(transform_results) == 1
        assert transform_results[0].success is True

    def test_validation_after_session(self) -> None:
        """Test validation runs correctly after session."""
        compiled = "<workflow><step n='2'>Second</step></workflow>"

        validation = Validation(
            must_contain=["step", "Second"],
            must_not_contain=["First", "removed"],
        )

        errors = validate_output(compiled, validation)
        assert len(errors) == 0

    def test_validation_failure_after_session(self) -> None:
        """Test validation fails when must_contain missing."""
        compiled = "<workflow><action>Do something</action></workflow>"

        validation = Validation(
            must_contain=["step"],
            must_not_contain=[],
        )

        errors = validate_output(compiled, validation)
        assert len(errors) == 1
        assert "step" in errors[0]

    def test_threshold_check_success(self) -> None:
        """Test 75% threshold passes."""
        results = [
            TransformResult(success=True, reason=None, transform_index=0),
            TransformResult(success=True, reason=None, transform_index=1),
            TransformResult(success=True, reason=None, transform_index=2),
            TransformResult(success=False, reason="Failed", transform_index=3),
        ]

        # 3/4 = 75% - should pass
        assert check_threshold(results) is True

    def test_threshold_check_failure(self) -> None:
        """Test below 75% threshold fails."""
        results = [
            TransformResult(success=True, reason=None, transform_index=0),
            TransformResult(success=True, reason=None, transform_index=1),
            TransformResult(success=False, reason="Failed", transform_index=2),
            TransformResult(success=False, reason="Failed", transform_index=3),
        ]

        # 2/4 = 50% - should fail
        assert check_threshold(results) is False

    def test_cache_save_and_validate(self, tmp_path: Path) -> None:
        """Test cache save and validation cycle."""
        # Create source files
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text("name: test")

        patch_file = tmp_path / "patch.yaml"
        patch_file.write_text("patch: test")

        # Create cache
        cache = TemplateCache()
        content = "<workflow>Compiled content</workflow>"
        compiled_at = datetime.now(UTC).isoformat()

        meta = CacheMeta(
            compiled_at=compiled_at,
            bmad_version="0.1.0",
            source_hashes={"workflow.yaml": compute_file_hash(workflow_file)},
            patch_hash=compute_file_hash(patch_file),
        )

        # Save
        cache.save("test-workflow", content, meta, tmp_path)

        # Validate
        is_valid = cache.is_valid(
            "test-workflow",
            tmp_path,
            source_files={"workflow.yaml": workflow_file},
            patch_path=patch_file,
        )
        assert is_valid is True

        # Load
        loaded = cache.load_cached("test-workflow", tmp_path)
        assert loaded is not None
        assert "Compiled content" in loaded

    def test_cache_invalidation_on_source_change(self, tmp_path: Path) -> None:
        """Test cache becomes invalid when source file changes."""
        # Create source files
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text("name: test")

        patch_file = tmp_path / "patch.yaml"
        patch_file.write_text("patch: test")

        # Create and save cache
        cache = TemplateCache()
        meta = CacheMeta(
            compiled_at=datetime.now(UTC).isoformat(),
            bmad_version="0.1.0",
            source_hashes={"workflow.yaml": compute_file_hash(workflow_file)},
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("test-workflow", "<workflow/>", meta, tmp_path)

        # Verify valid
        assert cache.is_valid(
            "test-workflow",
            tmp_path,
            {"workflow.yaml": workflow_file},
            patch_file,
        )

        # Modify source file
        workflow_file.write_text("name: modified")

        # Verify invalid
        assert not cache.is_valid(
            "test-workflow",
            tmp_path,
            {"workflow.yaml": workflow_file},
            patch_file,
        )

    def test_output_generation(self) -> None:
        """Test template output generation with metadata."""
        content = "<workflow><step>Content</step></workflow>"
        meta = TemplateMetadata(
            workflow="test-workflow",
            patch_name="test-patch",
            patch_version="1.0.0",
            bmad_version="0.1.0",
            compiled_at="2025-01-01T12:00:00Z",
            source_hash="abc123",
        )

        result = generate_template(content, meta)

        # Check header
        assert "<!--" in result
        assert "test-workflow" in result
        assert "test-patch" in result
        assert "1.0.0" in result
        assert "0.1.0" in result
        assert "2025-01-01T12:00:00Z" in result
        assert "abc123" in result

        # Check content preserved
        assert content in result


class TestErrorScenarios:
    """Tests for error handling scenarios."""

    def test_invalid_patch_yaml(self, tmp_path: Path) -> None:
        """Test error on malformed YAML."""
        patch_dir = tmp_path / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "bad.patch.yaml"
        patch_file.write_text("patch:\n  name: [unclosed")

        with pytest.raises(PatchError) as exc_info:
            load_patch(patch_file)

        assert "Invalid patch YAML" in str(exc_info.value)

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        """Test error on missing required patch fields."""
        patch_dir = tmp_path / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "incomplete.patch.yaml"
        patch_file.write_text("""
patch:
  name: test
  # missing version
compatibility:
  bmad_version: "0.1.0"
  workflow: test
transforms:
  - "Remove step 1"
""")

        with pytest.raises(PatchError) as exc_info:
            load_patch(patch_file)

        assert "version" in str(exc_info.value).lower() or "required" in str(exc_info.value).lower()

    def test_llm_response_missing_transformed_document_tag(self) -> None:
        """Test handling of LLM response without transformed-document tag."""
        workflow_content = "<step>Test</step>"
        instructions = ["Remove step completely"]

        # Mock provider returns response without proper tag (all retry attempts)
        mock_provider = MagicMock()
        mock_provider.invoke.return_value = "raw_result"
        mock_provider.parse_output.return_value = "This is a response without proper tags"

        session = PatchSession(workflow_content, instructions, mock_provider)
        result, transform_results = session.run()

        # Should mark transform as failed (batch mode: all fail together)
        assert len(transform_results) == 1
        assert transform_results[0].success is False
        assert (
            "transformed-document" in transform_results[0].reason.lower()
            or "tag" in transform_results[0].reason.lower()
        )

    def test_llm_response_no_change(self) -> None:
        """Test detection of no-change response."""
        workflow_content = "<step>Test</step>"
        instructions = ["Remove nonexistent element"]

        # Mock provider returns identical content (wrapped in transformed-document tags)
        mock_provider = MagicMock()
        mock_provider.invoke.return_value = "raw_result"
        mock_provider.parse_output.return_value = (
            "<transformed-document><step>Test</step></transformed-document>"
        )

        session = PatchSession(workflow_content, instructions, mock_provider)
        result, transform_results = session.run()

        # Should mark as failed - the logs show "no transformation applied" but
        # after retries the fallback message is about missing tag.
        # Either way, the transform should be marked as failed.
        assert len(transform_results) == 1
        assert transform_results[0].success is False
        # The reason could be about no change, transformation, or tag
        reason = transform_results[0].reason.lower()
        assert (
            "no" in reason and ("change" in reason or "transformation" in reason)
        ) or "transformed-document" in reason

    def test_validation_regex_failure(self) -> None:
        """Test regex validation failure."""
        content = "<workflow><step n='1'>Content</step></workflow>"
        validation = Validation(
            must_contain=['/step\\s+n="10"/'],  # Regex pattern - n="10" not present
            must_not_contain=[],
        )

        errors = validate_output(content, validation)
        assert len(errors) == 1

    @pytest.mark.skipif(os.geteuid() == 0, reason="Root ignores permissions")
    def test_cache_not_writable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test error when cache directory not writable."""
        cache = TemplateCache()
        meta = CacheMeta(
            compiled_at="2025-01-01T00:00:00Z",
            bmad_version="0.1.0",
            source_hashes={},
            patch_hash="abc",
        )

        # Create read-only directory
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)
        os.chmod(cache_dir, 0o444)

        try:
            with pytest.raises(PatchError) as exc_info:
                cache.save("test", "<workflow/>", meta, tmp_path)

            assert (
                "permission" in str(exc_info.value).lower()
                or "write" in str(exc_info.value).lower()
            )
        finally:
            os.chmod(cache_dir, 0o755)


class TestFixturesIntegration:
    """Tests using fixture files."""

    @pytest.fixture
    def sample_patch_dir(self, tmp_path: Path) -> Path:
        """Create a sample patch directory structure."""
        # Create project structure
        project = tmp_path / "project"
        project.mkdir()

        # Create patch directory
        patch_dir = project / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)

        # Create sample patch with string instructions
        patch_content = """
patch:
  name: create-story-optimizer
  version: "1.0.0"
  author: "BMAD Team"
  description: "Optimizes create-story workflow for reduced tokens"
compatibility:
  bmad_version: "0.1.0"
  workflow: create-story
transforms:
  - "Remove step 1 (initialization) - context is provided by compiler"
  - "Simplify instructions section - condense to essential text"
validation:
  must_contain:
    - "step"
  must_not_contain:
    - "PLACEHOLDER"
"""
        (patch_dir / "create-story.patch.yaml").write_text(patch_content)

        return project

    def test_discover_project_patch(self, sample_patch_dir: Path) -> None:
        """Test discovering patch in project directory."""
        patch_path = discover_patch("create-story", sample_patch_dir)
        assert patch_path is not None
        assert patch_path.exists()
        assert "create-story.patch.yaml" in str(patch_path)

    def test_load_sample_patch(self, sample_patch_dir: Path) -> None:
        """Test loading sample patch file."""
        patch_path = discover_patch("create-story", sample_patch_dir)
        patch = load_patch(patch_path)

        assert patch.config.name == "create-story-optimizer"
        assert patch.config.version == "1.0.0"
        assert patch.config.author == "BMAD Team"
        assert patch.compatibility.workflow == "create-story"
        assert len(patch.transforms) == 2
        assert "Remove step 1" in patch.transforms[0]
        assert "Simplify" in patch.transforms[1]
        assert patch.validation is not None
        assert "step" in patch.validation.must_contain
        assert "PLACEHOLDER" in patch.validation.must_not_contain
        assert len(patch.validation.must_contain) == 1

    def test_full_compilation_flow_mocked(self, sample_patch_dir: Path) -> None:
        """Test full compilation flow with mocked LLM."""
        # Discover and load patch
        patch_path = discover_patch("create-story", sample_patch_dir)
        patch = load_patch(patch_path)

        # Sample workflow content
        workflow = """<step n='1'>Initialize context</step>
<step n='2'>Create story</step>
<instructions>Create a new story following the template</instructions>"""

        # Mock provider response - batch mode: single call applies all transforms
        mock_provider = MagicMock()
        mock_provider.invoke.return_value = "raw_result"
        mock_provider.parse_output.return_value = (
            "<transformed-document>"
            "<step n='2'>Create story</step>"
            "<instructions>Create story from template</instructions>"
            "</transformed-document>"
        )

        # Run session with string instructions
        session = PatchSession(workflow, patch.transforms, mock_provider)
        result, transform_results = session.run()

        # Verify - batch mode: single LLM call, all transforms succeed together
        assert mock_provider.invoke.call_count == 1
        assert len(transform_results) == 2
        assert all(r.success for r in transform_results)

        # Validate output
        errors = validate_output(result, patch.validation)
        assert len(errors) == 0

        # Check threshold
        assert check_threshold(transform_results) is True

        # Generate template
        meta = TemplateMetadata(
            workflow="create-story",
            patch_name=patch.config.name,
            patch_version=patch.config.version,
            bmad_version="0.1.0",
            compiled_at=datetime.now(UTC).isoformat(),
            source_hash=compute_file_hash(patch_path),
        )
        template = generate_template(result, meta)

        # Verify template
        assert "<!--" in template
        assert "create-story" in template
        assert "create-story-optimizer" in template
        assert "<step n='2'>" in template

        # Save to cache
        cache = TemplateCache()
        cache_meta = CacheMeta(
            compiled_at=meta.compiled_at,
            bmad_version=meta.bmad_version,
            source_hashes={"patch": meta.source_hash},
            patch_hash=meta.source_hash,
        )
        cache.save("create-story", template, cache_meta, sample_patch_dir)

        # Verify cache
        cached = cache.load_cached("create-story", sample_patch_dir)
        assert cached is not None
        assert "create-story-optimizer" in cached

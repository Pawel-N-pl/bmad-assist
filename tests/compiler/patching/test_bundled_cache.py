"""Tests for bundled pre-compiled template cache."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from bmad_assist.compiler.patching.cache import (
    CacheMeta,
    TemplateCache,
    compute_file_hash,
)
from bmad_assist.core.exceptions import PatchError


class TestGetBundledCache:
    """Tests for get_bundled_cache() in workflows package."""

    def test_returns_content_when_bundled_exists(self) -> None:
        """Bundled tpl.xml + meta.yaml should return (tpl, meta) tuple."""
        from bmad_assist.workflows import get_bundled_cache

        mock_tpl = MagicMock()
        mock_tpl.is_file.return_value = True
        mock_tpl.read_text.return_value = "<compiled>test</compiled>"

        mock_meta = MagicMock()
        mock_meta.is_file.return_value = True
        mock_meta.read_text.return_value = "patch_hash: abc123"

        mock_cache_dir = MagicMock()
        mock_cache_dir.__truediv__ = lambda self, name: (
            mock_tpl if name.endswith(".tpl.xml") and not name.endswith(".meta.yaml")
            else mock_meta
        )

        mock_pkg = MagicMock()
        mock_pkg.__truediv__ = lambda self, name: mock_cache_dir if name == "cache" else MagicMock()

        with patch("bmad_assist.workflows.files", return_value=mock_pkg):
            result = get_bundled_cache("test-workflow")

        assert result is not None
        tpl, meta = result
        assert tpl == "<compiled>test</compiled>"
        assert meta == "patch_hash: abc123"

    def test_returns_none_when_not_bundled(self) -> None:
        """Non-existent workflow should return None."""
        from bmad_assist.workflows import get_bundled_cache

        mock_tpl = MagicMock()
        mock_tpl.is_file.return_value = False

        mock_meta = MagicMock()
        mock_meta.is_file.return_value = False

        mock_cache_dir = MagicMock()
        mock_cache_dir.__truediv__ = lambda self, name: mock_tpl

        mock_pkg = MagicMock()
        mock_pkg.__truediv__ = lambda self, name: mock_cache_dir if name == "cache" else MagicMock()

        with patch("bmad_assist.workflows.files", return_value=mock_pkg):
            result = get_bundled_cache("nonexistent-workflow")

        assert result is None

    def test_both_files_required(self) -> None:
        """Returns None if tpl.xml exists but meta.yaml missing."""
        from bmad_assist.workflows import get_bundled_cache

        mock_tpl = MagicMock()
        mock_tpl.is_file.return_value = True

        mock_meta = MagicMock()
        mock_meta.is_file.return_value = False

        mock_cache_dir = MagicMock()
        mock_cache_dir.__truediv__ = lambda self, name: (
            mock_tpl if not name.endswith(".meta.yaml") else mock_meta
        )

        mock_pkg = MagicMock()
        mock_pkg.__truediv__ = lambda self, name: mock_cache_dir if name == "cache" else MagicMock()

        with patch("bmad_assist.workflows.files", return_value=mock_pkg):
            result = get_bundled_cache("test-workflow")

        assert result is None

    def test_reads_via_traversable_read_text(self) -> None:
        """Content should be read via Traversable.read_text(), not Path conversion."""
        from bmad_assist.workflows import get_bundled_cache

        mock_tpl = MagicMock()
        mock_tpl.is_file.return_value = True
        mock_tpl.read_text.return_value = "<tpl/>"

        mock_meta = MagicMock()
        mock_meta.is_file.return_value = True
        mock_meta.read_text.return_value = "meta"

        mock_cache_dir = MagicMock()
        mock_cache_dir.__truediv__ = lambda self, name: (
            mock_tpl if name.endswith(".tpl.xml") and not name.endswith(".meta.yaml")
            else mock_meta
        )

        mock_pkg = MagicMock()
        mock_pkg.__truediv__ = lambda self, name: mock_cache_dir if name == "cache" else MagicMock()

        with patch("bmad_assist.workflows.files", return_value=mock_pkg):
            get_bundled_cache("test-workflow")

        # Verify read_text was called (not __str__ or Path conversion)
        mock_tpl.read_text.assert_called_once_with(encoding="utf-8")
        mock_meta.read_text.assert_called_once_with(encoding="utf-8")


class TestBundledCachePriority:
    """Integration tests for bundled cache priority in ensure_template_compiled."""

    def _create_workflow_files(
        self, project_root: Path, workflow: str = "create-story"
    ) -> tuple[Path, Path]:
        """Create minimal workflow source files."""
        workflow_dir = project_root / "_bmad" / "bmm" / "workflows" / "4-implementation" / workflow
        workflow_dir.mkdir(parents=True)
        wf_yaml = workflow_dir / "workflow.yaml"
        wf_yaml.write_text("name: test\ntemplate: null\nvalidation: null\n")
        instructions = workflow_dir / "instructions.xml"
        instructions.write_text("<instructions>test</instructions>")
        return wf_yaml, instructions

    def _create_patch_file(
        self, project_root: Path, workflow: str = "create-story"
    ) -> Path:
        """Create a minimal patch file."""
        patches_dir = project_root / ".bmad-assist" / "patches"
        patches_dir.mkdir(parents=True, exist_ok=True)
        patch_file = patches_dir / f"{workflow}.patch.yaml"
        patch_file.write_text(
            "patch:\n  name: test\n  version: '1.0'\n"
            "compatibility:\n  bmad_version: '6.0'\n  workflow: test\n"
            "transforms:\n  - 'Do nothing'\n"
        )
        return patch_file

    def test_bundled_used_when_patch_hash_matches(self, tmp_path: Path) -> None:
        """Default patch → bundled content written to local cache."""
        wf_yaml, instructions = self._create_workflow_files(tmp_path)
        patch_file = self._create_patch_file(tmp_path)

        # Create bundled meta that matches current state
        bundled_tpl = "<compiled>bundled content</compiled>"
        bundled_meta = {
            "patch_hash": compute_file_hash(patch_file),
            "source_hashes": {
                "workflow.yaml": compute_file_hash(wf_yaml),
                "instructions.xml": compute_file_hash(instructions),
            },
            "compiled_at": "2026-01-01T00:00:00Z",
            "bmad_version": "6.0",
        }
        bundled_meta_str = yaml.dump(bundled_meta)

        with (
            patch(
                "bmad_assist.workflows.get_bundled_cache",
                return_value=(bundled_tpl, bundled_meta_str),
            ),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            from bmad_assist.compiler.patching.compiler import ensure_template_compiled

            result = ensure_template_compiled("create-story", tmp_path)

        assert result is not None
        assert result.read_text(encoding="utf-8") == bundled_tpl

    def test_local_cache_used_when_patch_hash_differs(self, tmp_path: Path) -> None:
        """Custom patch → bundled skipped, falls through to local cache check."""
        wf_yaml, instructions = self._create_workflow_files(tmp_path)
        patch_file = self._create_patch_file(tmp_path)

        # Create local cache with matching hashes
        cache = TemplateCache()
        cache_meta = CacheMeta(
            compiled_at="2026-01-01T00:00:00Z",
            bmad_version="6.0",
            source_hashes={
                "workflow.yaml": compute_file_hash(wf_yaml),
                "instructions.xml": compute_file_hash(instructions),
            },
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("create-story", "<compiled>local</compiled>", cache_meta, tmp_path)

        # Bundled has DIFFERENT patch_hash
        bundled_meta = {
            "patch_hash": "different_hash_from_custom_patch",
            "source_hashes": {},
            "compiled_at": "2026-01-01T00:00:00Z",
            "bmad_version": "6.0",
        }

        with (
            patch(
                "bmad_assist.workflows.get_bundled_cache",
                return_value=("<bundled/>", yaml.dump(bundled_meta)),
            ),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            from bmad_assist.compiler.patching.compiler import ensure_template_compiled

            result = ensure_template_compiled("create-story", tmp_path)

        assert result is not None
        # Should use local cache, not bundled
        content = result.read_text(encoding="utf-8")
        assert "local" in content

    def test_stale_bundled_skipped_source_hash_mismatch(self, tmp_path: Path) -> None:
        """Bundled with old source_hashes → falls through to compile."""
        wf_yaml, instructions = self._create_workflow_files(tmp_path)
        patch_file = self._create_patch_file(tmp_path)

        # Bundled meta has matching patch_hash but STALE source_hashes
        bundled_meta = {
            "patch_hash": compute_file_hash(patch_file),
            "source_hashes": {
                "workflow.yaml": "stale_hash",
                "instructions.xml": "stale_hash",
            },
            "compiled_at": "2026-01-01T00:00:00Z",
            "bmad_version": "6.0",
        }

        with (
            patch(
                "bmad_assist.workflows.get_bundled_cache",
                return_value=("<bundled/>", yaml.dump(bundled_meta)),
            ),
            patch(
                "bmad_assist.compiler.patching.compiler.compile_patch",
                side_effect=PatchError("Should not compile in this test"),
            ),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            from bmad_assist.compiler.patching.compiler import ensure_template_compiled

            # No local cache, bundled stale, compile would fail
            # Should return None (fall through to original files)
            result = ensure_template_compiled("create-story", tmp_path)

        assert result is None

    def test_no_bundled_falls_through(self, tmp_path: Path) -> None:
        """No bundled cache → existing flow unchanged."""
        wf_yaml, instructions = self._create_workflow_files(tmp_path)
        patch_file = self._create_patch_file(tmp_path)

        # Create local cache
        cache = TemplateCache()
        cache_meta = CacheMeta(
            compiled_at="2026-01-01T00:00:00Z",
            bmad_version="6.0",
            source_hashes={
                "workflow.yaml": compute_file_hash(wf_yaml),
                "instructions.xml": compute_file_hash(instructions),
            },
            patch_hash=compute_file_hash(patch_file),
        )
        cache.save("create-story", "<compiled>local</compiled>", cache_meta, tmp_path)

        with (
            patch(
                "bmad_assist.workflows.get_bundled_cache",
                return_value=None,
            ),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            from bmad_assist.compiler.patching.compiler import ensure_template_compiled

            result = ensure_template_compiled("create-story", tmp_path)

        assert result is not None
        assert "local" in result.read_text(encoding="utf-8")

    def test_defaults_hash_mismatch_triggers_recompile(self, tmp_path: Path) -> None:
        """Bundled defaults_hash differs from current → fall through."""
        wf_yaml, instructions = self._create_workflow_files(tmp_path)
        patch_file = self._create_patch_file(tmp_path)

        bundled_meta = {
            "patch_hash": compute_file_hash(patch_file),
            "source_hashes": {
                "workflow.yaml": compute_file_hash(wf_yaml),
                "instructions.xml": compute_file_hash(instructions),
            },
            "defaults_hash": "bundled_defaults_hash_old",
            "compiled_at": "2026-01-01T00:00:00Z",
            "bmad_version": "6.0",
        }

        # Create defaults.yaml so compute_defaults_hash returns non-None
        defaults_dir = patch_file.parent
        (defaults_dir / "defaults.yaml").write_text("post_process: []")

        with (
            patch(
                "bmad_assist.workflows.get_bundled_cache",
                return_value=("<bundled/>", yaml.dump(bundled_meta)),
            ),
            patch(
                "bmad_assist.compiler.patching.compiler.compile_patch",
                side_effect=PatchError("no LLM"),
            ),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            from bmad_assist.compiler.patching.compiler import ensure_template_compiled

            result = ensure_template_compiled("create-story", tmp_path)

        # Falls through, no local cache, compile fails → None
        assert result is None

    def test_corrupted_bundled_meta_graceful_skip(self, tmp_path: Path) -> None:
        """Malformed YAML in bundled meta → log warning, fall through."""
        wf_yaml, instructions = self._create_workflow_files(tmp_path)
        patch_file = self._create_patch_file(tmp_path)

        with (
            patch(
                "bmad_assist.workflows.get_bundled_cache",
                return_value=("<bundled/>", "invalid: yaml: [broken"),
            ),
            patch(
                "bmad_assist.compiler.patching.compiler.compile_patch",
                side_effect=PatchError("no LLM"),
            ),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            from bmad_assist.compiler.patching.compiler import ensure_template_compiled

            # Should not raise, just fall through
            result = ensure_template_compiled("create-story", tmp_path)

        assert result is None

    def test_bundled_content_written_to_local_cache(self, tmp_path: Path) -> None:
        """Verify bundled tpl content is physically written to local cache dir."""
        wf_yaml, instructions = self._create_workflow_files(tmp_path)
        patch_file = self._create_patch_file(tmp_path)

        bundled_tpl = "<compiled>BUNDLED_CONTENT_MARKER</compiled>"
        bundled_meta = {
            "patch_hash": compute_file_hash(patch_file),
            "source_hashes": {
                "workflow.yaml": compute_file_hash(wf_yaml),
                "instructions.xml": compute_file_hash(instructions),
            },
            "compiled_at": "2026-01-01T00:00:00Z",
            "bmad_version": "6.0",
        }
        bundled_meta_str = yaml.dump(bundled_meta)

        with (
            patch(
                "bmad_assist.workflows.get_bundled_cache",
                return_value=(bundled_tpl, bundled_meta_str),
            ),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            from bmad_assist.compiler.patching.compiler import ensure_template_compiled

            result = ensure_template_compiled("create-story", tmp_path)

        assert result is not None
        # Verify file physically exists in local cache
        expected_cache = tmp_path / ".bmad-assist" / "cache" / "create-story.tpl.xml"
        assert expected_cache.exists()
        assert "BUNDLED_CONTENT_MARKER" in expected_cache.read_text(encoding="utf-8")
        # Meta file also written
        meta_path = expected_cache.with_suffix(expected_cache.suffix + ".meta.yaml")
        assert meta_path.exists()

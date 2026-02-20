"""Tests for patch discovery and loading."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from bmad_assist.compiler.patching.discovery import (
    compute_defaults_hash,
    determine_patch_source_level,
    discover_patch,
    load_defaults,
    load_patch,
)
from bmad_assist.compiler.patching.types import WorkflowPatch
from bmad_assist.core.exceptions import PatchError


@pytest.fixture
def sample_patch_yaml() -> dict:
    """Return a valid sample patch YAML structure."""
    return {
        "patch": {
            "name": "test-patch",
            "version": "1.0.0",
            "author": "Test Author",
            "description": "Test patch for testing",
        },
        "compatibility": {
            "bmad_version": "0.1.0",
            "workflow": "create-story",
        },
        "transforms": [
            "Remove step 1 completely",
            "Inject new action after step 2",
        ],
        "validation": {
            "must_contain": ["<step", "action"],
            "must_not_contain": ["<ask>", "HALT"],
        },
    }


class TestDiscoverPatch:
    """Tests for discover_patch function."""

    def test_discover_project_patch(self, tmp_path: Path, sample_patch_yaml: dict) -> None:
        """Test discovering patch from project path."""
        # Create project patch directory
        patch_dir = tmp_path / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "create-story.patch.yaml"
        patch_file.write_text(yaml.dump(sample_patch_yaml))

        result = discover_patch("create-story", tmp_path)

        assert result is not None
        assert result == patch_file
        assert result.exists()

    def test_discover_global_patch(self, tmp_path: Path, sample_patch_yaml: dict) -> None:
        """Test discovering patch from global path when project patch doesn't exist."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create global patch directory
        global_dir = tmp_path / "global" / ".bmad-assist" / "patches"
        global_dir.mkdir(parents=True)
        patch_file = global_dir / "create-story.patch.yaml"
        patch_file.write_text(yaml.dump(sample_patch_yaml))

        # Mock home to point to our tmp global
        with patch("pathlib.Path.home", return_value=tmp_path / "global"):
            result = discover_patch("create-story", project_dir)

        assert result is not None
        assert result == patch_file

    def test_project_patch_overrides_global(self, tmp_path: Path, sample_patch_yaml: dict) -> None:
        """Test that project patch takes precedence over global patch."""
        project_dir = tmp_path / "project"

        # Create project patch
        project_patch_dir = project_dir / ".bmad-assist" / "patches"
        project_patch_dir.mkdir(parents=True)
        project_patch = project_patch_dir / "create-story.patch.yaml"
        project_patch.write_text(yaml.dump(sample_patch_yaml))

        # Create global patch
        global_dir = tmp_path / "global" / ".bmad-assist" / "patches"
        global_dir.mkdir(parents=True)
        global_patch = global_dir / "create-story.patch.yaml"
        global_patch.write_text(yaml.dump({"different": "content"}))

        with patch("pathlib.Path.home", return_value=tmp_path / "global"):
            result = discover_patch("create-story", project_dir)

        assert result == project_patch

    def test_no_patch_returns_none(self, tmp_path: Path) -> None:
        """Test that missing patch returns None."""
        with patch("pathlib.Path.home", return_value=tmp_path / "global"):
            # Use a workflow that doesn't exist in default_patches
            result = discover_patch("nonexistent-workflow", tmp_path)

        assert result is None

    def test_custom_patch_path_from_config(self, tmp_path: Path, sample_patch_yaml: dict) -> None:
        """Test using custom patch path from config."""
        custom_dir = tmp_path / "custom-patches"
        custom_dir.mkdir()
        patch_file = custom_dir / "create-story.patch.yaml"
        patch_file.write_text(yaml.dump(sample_patch_yaml))

        result = discover_patch(
            "create-story",
            tmp_path,
            patch_path=str(custom_dir),
        )

        assert result == patch_file

    def test_logs_debug_when_no_patch(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that DEBUG is logged when no patch found (not an error for custom workflows)."""
        with patch("pathlib.Path.home", return_value=tmp_path / "global"):
            with caplog.at_level(logging.DEBUG):
                # Use a workflow that doesn't exist in default_patches
                result = discover_patch("nonexistent-workflow", tmp_path)

        assert result is None
        assert "No patch found for 'nonexistent-workflow'" in caplog.text

    def test_package_fallback_finds_default_patches(self, tmp_path: Path) -> None:
        """Test that patches are found in package default_patches directory."""
        # When no project/global patches exist, should find package default
        with patch("pathlib.Path.home", return_value=tmp_path / "global"):
            result = discover_patch("create-story", tmp_path)

        # Should find the default patch from package
        assert result is not None
        assert "default_patches" in str(result)
        assert result.name == "create-story.patch.yaml"


class TestLoadPatch:
    """Tests for load_patch function."""

    def test_load_valid_patch(self, tmp_path: Path, sample_patch_yaml: dict) -> None:
        """Test loading a valid patch file."""
        patch_file = tmp_path / "test.patch.yaml"
        patch_file.write_text(yaml.dump(sample_patch_yaml))

        result = load_patch(patch_file)

        assert isinstance(result, WorkflowPatch)
        assert result.config.name == "test-patch"
        assert result.config.version == "1.0.0"
        assert result.compatibility.workflow == "create-story"
        assert len(result.transforms) == 2
        assert result.transforms[0] == "Remove step 1 completely"
        assert result.transforms[1] == "Inject new action after step 2"

    def test_load_patch_with_validation(self, tmp_path: Path, sample_patch_yaml: dict) -> None:
        """Test loading patch with validation rules."""
        patch_file = tmp_path / "test.patch.yaml"
        patch_file.write_text(yaml.dump(sample_patch_yaml))

        result = load_patch(patch_file)

        assert result.validation is not None
        assert result.validation.must_contain == ["<step", "action"]
        assert result.validation.must_not_contain == ["<ask>", "HALT"]

    def test_load_patch_minimal(self, tmp_path: Path) -> None:
        """Test loading minimal valid patch."""
        minimal_patch = {
            "patch": {"name": "minimal", "version": "1.0"},
            "compatibility": {"bmad_version": "0.1.0", "workflow": "test"},
            "transforms": ["Remove step 1"],
        }
        patch_file = tmp_path / "minimal.patch.yaml"
        patch_file.write_text(yaml.dump(minimal_patch))

        result = load_patch(patch_file)

        assert result.config.name == "minimal"
        assert len(result.transforms) == 1
        assert result.transforms[0] == "Remove step 1"
        assert result.validation is None

    def test_load_malformed_yaml_raises_error(self, tmp_path: Path) -> None:
        """Test that malformed YAML raises PatchError."""
        patch_file = tmp_path / "bad.patch.yaml"
        patch_file.write_text("invalid: yaml: content: [unclosed")

        with pytest.raises(PatchError) as exc_info:
            load_patch(patch_file)

        assert "Invalid patch YAML" in str(exc_info.value)
        assert str(patch_file) in str(exc_info.value)

    def test_load_malformed_yaml_includes_line_number(self, tmp_path: Path) -> None:
        """Test that YAML error includes line number when available."""
        patch_file = tmp_path / "bad.patch.yaml"
        # Create YAML with a syntax error on line 3
        patch_file.write_text("patch:\n  name: test\n  version: [invalid\n")

        with pytest.raises(PatchError) as exc_info:
            load_patch(patch_file)

        # yaml.YAMLError should include line info
        assert "line" in str(exc_info.value).lower() or "Invalid patch YAML" in str(exc_info.value)

    def test_load_missing_required_field_raises_error(self, tmp_path: Path) -> None:
        """Test that missing required field raises PatchError."""
        invalid_patch = {
            "patch": {"name": "test"},  # Missing version
            "compatibility": {"bmad_version": "0.1.0", "workflow": "test"},
            "transforms": ["Remove step 1"],
        }
        patch_file = tmp_path / "invalid.patch.yaml"
        patch_file.write_text(yaml.dump(invalid_patch))

        with pytest.raises(PatchError) as exc_info:
            load_patch(patch_file)

        assert "version" in str(exc_info.value).lower()

    def test_load_invalid_transform_type_raises_error(self, tmp_path: Path) -> None:
        """Test that non-string transform raises PatchError."""
        invalid_patch = {
            "patch": {"name": "test", "version": "1.0"},
            "compatibility": {"bmad_version": "0.1.0", "workflow": "test"},
            "transforms": [{"action": "remove", "target": "//step"}],  # dict instead of string
        }
        patch_file = tmp_path / "invalid.patch.yaml"
        patch_file.write_text(yaml.dump(invalid_patch))

        with pytest.raises(PatchError) as exc_info:
            load_patch(patch_file)

        assert (
            "string" in str(exc_info.value).lower() or "instruction" in str(exc_info.value).lower()
        )

    def test_load_nonexistent_file_raises_error(self, tmp_path: Path) -> None:
        """Test that nonexistent file raises appropriate error."""
        patch_file = tmp_path / "nonexistent.patch.yaml"

        with pytest.raises(PatchError) as exc_info:
            load_patch(patch_file)

        assert "not found" in str(exc_info.value).lower() or "exist" in str(exc_info.value).lower()

    def test_load_patch_multiple_instructions(self, tmp_path: Path) -> None:
        """Test loading patch with multiple instruction strings."""
        multi_patch = {
            "patch": {"name": "multi-instructions", "version": "1.0"},
            "compatibility": {"bmad_version": "0.1.0", "workflow": "test"},
            "transforms": [
                "Remove step 1 completely",
                "Remove step 2 if redundant",
                "Remove all <ask> elements using pattern matching",
                "Replace step 3 content with simplified version",
                "Inject new action before step 4",
                "Reorder steps to be more logical",
                "Simplify instruction text to be more concise",
            ],
        }
        patch_file = tmp_path / "multi.patch.yaml"
        patch_file.write_text(yaml.dump(multi_patch))

        result = load_patch(patch_file)

        assert len(result.transforms) == 7
        assert "Remove step 1" in result.transforms[0]
        assert "redundant" in result.transforms[1]
        assert "pattern" in result.transforms[2]
        assert "Replace" in result.transforms[3]
        assert "Inject" in result.transforms[4]
        assert "Reorder" in result.transforms[5]
        assert "Simplify" in result.transforms[6]

    def test_load_empty_transforms_raises_error(self, tmp_path: Path) -> None:
        """Test that empty transforms list raises error."""
        empty_patch = {
            "patch": {"name": "empty", "version": "1.0"},
            "compatibility": {"bmad_version": "0.1.0", "workflow": "test"},
            "transforms": [],
        }
        patch_file = tmp_path / "empty.patch.yaml"
        patch_file.write_text(yaml.dump(empty_patch))

        with pytest.raises(PatchError) as exc_info:
            load_patch(patch_file)

        assert "empty" in str(exc_info.value).lower() or "transforms" in str(exc_info.value).lower()


class TestLoadDefaults:
    """Tests for load_defaults function."""

    def test_load_defaults_from_same_directory(self, tmp_path: Path) -> None:
        """Test loading defaults from same directory as patch."""
        defaults_yaml = {
            "post_process": [
                {"pattern": "foo", "replacement": "bar"},
                {"pattern": "baz", "replacement": "qux", "flags": "IGNORECASE"},
            ]
        }
        defaults_file = tmp_path / "defaults.yaml"
        defaults_file.write_text(yaml.dump(defaults_yaml))

        patch_file = tmp_path / "test.patch.yaml"
        patch_file.touch()

        rules = load_defaults(patch_file)

        assert len(rules) == 2
        assert rules[0].pattern == "foo"
        assert rules[0].replacement == "bar"
        assert rules[1].pattern == "baz"
        assert rules[1].flags == "IGNORECASE"

    def test_load_defaults_fallback_to_global(self, tmp_path: Path) -> None:
        """Test fallback to global defaults when not in patch directory."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        global_dir = tmp_path / "global" / ".bmad-assist" / "patches"
        global_dir.mkdir(parents=True)
        defaults_yaml = {"post_process": [{"pattern": "global", "replacement": "rule"}]}
        (global_dir / "defaults.yaml").write_text(yaml.dump(defaults_yaml))

        patch_file = project_dir / "test.patch.yaml"
        patch_file.touch()

        with patch("pathlib.Path.home", return_value=tmp_path / "global"):
            rules = load_defaults(patch_file)

        assert len(rules) == 1
        assert rules[0].pattern == "global"

    def test_load_defaults_returns_empty_if_not_found(self, tmp_path: Path) -> None:
        """Test that empty list is returned if no defaults found."""
        patch_file = tmp_path / "test.patch.yaml"
        patch_file.touch()

        with (
            patch("pathlib.Path.home", return_value=tmp_path / "nonexistent"),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            rules = load_defaults(patch_file)

        assert rules == []

    def test_load_defaults_invalid_yaml_returns_empty(self, tmp_path: Path) -> None:
        """Test that invalid YAML returns empty list."""
        defaults_file = tmp_path / "defaults.yaml"
        defaults_file.write_text("invalid: yaml: [unclosed")

        patch_file = tmp_path / "test.patch.yaml"
        patch_file.touch()

        rules = load_defaults(patch_file)

        assert rules == []

    def test_load_defaults_no_post_process_returns_empty(self, tmp_path: Path) -> None:
        """Test that missing post_process section returns empty list."""
        defaults_yaml = {"other_config": "value"}
        defaults_file = tmp_path / "defaults.yaml"
        defaults_file.write_text(yaml.dump(defaults_yaml))

        patch_file = tmp_path / "test.patch.yaml"
        patch_file.touch()

        rules = load_defaults(patch_file)

        assert rules == []


class TestLoadPatchWithDefaults:
    """Tests for load_patch merging with defaults."""

    @pytest.fixture
    def minimal_patch_yaml(self) -> dict:
        """Return minimal valid patch YAML."""
        return {
            "patch": {"name": "test", "version": "1.0"},
            "compatibility": {"bmad_version": "0.1.0", "workflow": "test"},
            "transforms": ["Remove step 1"],
        }

    def test_load_patch_merges_defaults(self, tmp_path: Path, minimal_patch_yaml: dict) -> None:
        """Test that patch loads and merges defaults post_process rules."""
        # Create defaults
        defaults_yaml = {"post_process": [{"pattern": "default", "replacement": "rule"}]}
        (tmp_path / "defaults.yaml").write_text(yaml.dump(defaults_yaml))

        # Create patch with its own rules
        minimal_patch_yaml["post_process"] = [{"pattern": "patch", "replacement": "specific"}]
        patch_file = tmp_path / "test.patch.yaml"
        patch_file.write_text(yaml.dump(minimal_patch_yaml))

        result = load_patch(patch_file)

        # Should have both: defaults first, then patch-specific
        assert result.post_process is not None
        assert len(result.post_process) == 2
        assert result.post_process[0].pattern == "default"
        assert result.post_process[1].pattern == "patch"

    def test_load_patch_defaults_only(self, tmp_path: Path, minimal_patch_yaml: dict) -> None:
        """Test that patch without post_process still gets defaults."""
        # Create defaults
        defaults_yaml = {
            "post_process": [
                {"pattern": "default1", "replacement": "r1"},
                {"pattern": "default2", "replacement": "r2"},
            ]
        }
        (tmp_path / "defaults.yaml").write_text(yaml.dump(defaults_yaml))

        # Create patch without post_process
        patch_file = tmp_path / "test.patch.yaml"
        patch_file.write_text(yaml.dump(minimal_patch_yaml))

        result = load_patch(patch_file)

        assert result.post_process is not None
        assert len(result.post_process) == 2
        assert result.post_process[0].pattern == "default1"
        assert result.post_process[1].pattern == "default2"

    def test_load_patch_no_defaults_patch_rules_only(
        self, tmp_path: Path, minimal_patch_yaml: dict
    ) -> None:
        """Test patch with post_process but no defaults file."""
        minimal_patch_yaml["post_process"] = [{"pattern": "only", "replacement": "patch"}]
        patch_file = tmp_path / "test.patch.yaml"
        patch_file.write_text(yaml.dump(minimal_patch_yaml))

        with (
            patch("pathlib.Path.home", return_value=tmp_path / "nonexistent"),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            result = load_patch(patch_file)

        assert result.post_process is not None
        assert len(result.post_process) == 1
        assert result.post_process[0].pattern == "only"

    def test_load_patch_no_defaults_no_rules(
        self, tmp_path: Path, minimal_patch_yaml: dict
    ) -> None:
        """Test patch without defaults and without post_process."""
        patch_file = tmp_path / "test.patch.yaml"
        patch_file.write_text(yaml.dump(minimal_patch_yaml))

        with (
            patch("pathlib.Path.home", return_value=tmp_path / "nonexistent"),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            result = load_patch(patch_file)

        assert result.post_process is None


class TestDeterminePatchSourceLevel:
    """Tests for determine_patch_source_level function."""

    def test_patch_in_project_returns_project_root(self, tmp_path: Path) -> None:
        """Test that patch in project returns project_root for cache."""
        project = tmp_path / "project"
        patch_dir = project / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "test.patch.yaml"
        patch_file.touch()

        result = determine_patch_source_level(patch_file, project)

        assert result == project

    def test_patch_in_cwd_returns_cwd(self, tmp_path: Path) -> None:
        """Test that patch in CWD returns CWD for cache."""
        project = tmp_path / "project"
        project.mkdir()
        cwd = tmp_path / "cwd"
        patch_dir = cwd / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "test.patch.yaml"
        patch_file.touch()

        result = determine_patch_source_level(patch_file, project, cwd=cwd)

        assert result == cwd

    def test_patch_in_global_returns_none(self, tmp_path: Path) -> None:
        """Test that global patch returns None for cache (global cache)."""
        project = tmp_path / "project"
        project.mkdir()
        home = tmp_path / "home"
        patch_dir = home / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "test.patch.yaml"
        patch_file.touch()

        with patch("pathlib.Path.home", return_value=home):
            result = determine_patch_source_level(patch_file, project)

        assert result is None

    def test_project_takes_priority_over_cwd(self, tmp_path: Path) -> None:
        """Test that project patch location is detected even when cwd is set."""
        project = tmp_path / "project"
        patch_dir = project / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "test.patch.yaml"
        patch_file.touch()

        cwd = tmp_path / "cwd"
        cwd.mkdir()

        result = determine_patch_source_level(patch_file, project, cwd=cwd)

        assert result == project

    def test_cwd_same_as_project_returns_project(self, tmp_path: Path) -> None:
        """Test that when CWD equals project, project is returned."""
        project = tmp_path / "project"
        patch_dir = project / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "test.patch.yaml"
        patch_file.touch()

        # CWD is same as project
        result = determine_patch_source_level(patch_file, project, cwd=project)

        assert result == project

    def test_unknown_source_defaults_to_project(self, tmp_path: Path) -> None:
        """Test that unknown patch source defaults to project_root."""
        project = tmp_path / "project"
        project.mkdir()
        # Patch in random location (not project, cwd, or home)
        random_dir = tmp_path / "random" / "patches"
        random_dir.mkdir(parents=True)
        patch_file = random_dir / "test.patch.yaml"
        patch_file.touch()

        with patch("pathlib.Path.home", return_value=tmp_path / "home"):
            result = determine_patch_source_level(patch_file, project)

        assert result == project

    def test_custom_patch_path_outside_standard_locations(self, tmp_path: Path) -> None:
        """Test patch from custom path (via config) defaults to project."""
        project = tmp_path / "project"
        project.mkdir()
        custom_dir = project / "custom-patches"
        custom_dir.mkdir()
        patch_file = custom_dir / "test.patch.yaml"
        patch_file.touch()

        with patch("pathlib.Path.home", return_value=tmp_path / "home"):
            result = determine_patch_source_level(patch_file, project)

        # Custom path inside project but not in .bmad-assist/patches
        # Should default to project
        assert result == project


class TestComputeDefaultsHash:
    """Tests for compute_defaults_hash function."""

    def test_compute_hash_with_defaults_yaml(self, tmp_path: Path) -> None:
        """Returns hash when defaults.yaml exists."""
        defaults = tmp_path / "defaults.yaml"
        defaults.write_text("post_process:\n  - pattern: test\n")
        patch_file = tmp_path / "test.patch.yaml"
        patch_file.touch()

        result = compute_defaults_hash(patch_file)

        assert result is not None
        assert len(result) == 64  # SHA-256 hex digest

    def test_compute_hash_with_tea_defaults(self, tmp_path: Path) -> None:
        """Returns combined hash for TEA workflow (defaults + defaults-testarch)."""
        defaults = tmp_path / "defaults.yaml"
        defaults.write_text("post_process: []\n")
        tea_defaults = tmp_path / "defaults-testarch.yaml"
        tea_defaults.write_text("post_process: []\n")
        patch_file = tmp_path / "testarch-ci.patch.yaml"
        patch_file.touch()

        result = compute_defaults_hash(patch_file, "testarch-ci")

        assert result is not None

        # Should be different from non-TEA hash (which only uses defaults.yaml)
        non_tea = compute_defaults_hash(patch_file, "create-story")
        assert result != non_tea

    def test_compute_hash_tea_missing_testarch(self, tmp_path: Path) -> None:
        """TEA workflow with defaults.yaml but no defaults-testarch → hashes only defaults."""
        defaults = tmp_path / "defaults.yaml"
        defaults.write_text("post_process: []\n")
        patch_file = tmp_path / "testarch-ci.patch.yaml"
        patch_file.touch()

        with (
            patch("pathlib.Path.home", return_value=tmp_path / "nonexistent"),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            result = compute_defaults_hash(patch_file, "testarch-ci")

        assert result is not None
        # Same as non-TEA since no testarch defaults found
        with (
            patch("pathlib.Path.home", return_value=tmp_path / "nonexistent"),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            non_tea = compute_defaults_hash(patch_file, "create-story")
        assert result == non_tea

    def test_compute_hash_no_defaults(self, tmp_path: Path) -> None:
        """Returns None when no defaults files exist."""
        patch_file = tmp_path / "test.patch.yaml"
        patch_file.touch()

        with (
            patch("pathlib.Path.home", return_value=tmp_path / "nonexistent"),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                tmp_path / "nonexistent_pkg",
            ),
        ):
            result = compute_defaults_hash(patch_file)

        assert result is None

    def test_compute_hash_deterministic(self, tmp_path: Path) -> None:
        """Same files → same hash across calls."""
        defaults = tmp_path / "defaults.yaml"
        defaults.write_text("post_process: []\n")
        patch_file = tmp_path / "test.patch.yaml"
        patch_file.touch()

        h1 = compute_defaults_hash(patch_file)
        h2 = compute_defaults_hash(patch_file)
        assert h1 == h2

    def test_compute_hash_uses_raw_bytes(self, tmp_path: Path) -> None:
        """Verifies hashing raw file bytes - different whitespace means different hash."""
        defaults1 = tmp_path / "dir1"
        defaults1.mkdir()
        (defaults1 / "defaults.yaml").write_text("post_process: []\n")
        patch_file1 = defaults1 / "test.patch.yaml"
        patch_file1.touch()

        defaults2 = tmp_path / "dir2"
        defaults2.mkdir()
        (defaults2 / "defaults.yaml").write_text("post_process:  []\n")  # extra space
        patch_file2 = defaults2 / "test.patch.yaml"
        patch_file2.touch()

        h1 = compute_defaults_hash(patch_file1)
        h2 = compute_defaults_hash(patch_file2)
        assert h1 != h2  # Raw bytes differ


class TestLoadDefaultsPackageFallback:
    """Tests for _load_defaults_file package fallback."""

    def test_load_defaults_testarch_package_fallback(self, tmp_path: Path) -> None:
        """Defaults-testarch.yaml is found via package fallback for TEA workflows."""
        # Create a patch dir without any defaults
        patch_file = tmp_path / "patches" / "testarch-ci.patch.yaml"
        patch_file.parent.mkdir(parents=True)
        patch_file.touch()

        # Set up package fallback dir with testarch defaults
        pkg_dir = tmp_path / "package_defaults"
        pkg_dir.mkdir()
        (pkg_dir / "defaults.yaml").write_text(
            "post_process:\n  - pattern: base\n    replacement: base_r\n"
        )
        (pkg_dir / "defaults-testarch.yaml").write_text(
            "post_process:\n  - pattern: tea\n    replacement: tea_r\n"
        )

        with (
            patch("pathlib.Path.home", return_value=tmp_path / "nonexistent"),
            patch(
                "bmad_assist.compiler.patching.discovery._PACKAGE_DEFAULTS_DIR",
                pkg_dir,
            ),
        ):
            rules = load_defaults(patch_file, "testarch-ci")

        # Should find both: base + TEA rules
        assert len(rules) == 2
        patterns = [r.pattern for r in rules]
        assert "base" in patterns
        assert "tea" in patterns

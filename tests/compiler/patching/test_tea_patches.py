"""Tests for TEA patch discovery and merging.

Tests the TEA-specific patch discovery functionality including:
- defaults-testarch.yaml loading
- Patch merging with workflow-specific patches
- Cache invalidation for merged patches
"""

from pathlib import Path

import pytest
import yaml


class TestDefaultsTestarchYaml:
    """Tests for defaults-testarch.yaml structure and loading."""

    def test_file_exists(self) -> None:
        """Should have defaults-testarch.yaml in patches directory."""
        patches_dir = Path(".bmad-assist/patches")
        defaults_path = patches_dir / "defaults-testarch.yaml"
        assert defaults_path.exists(), f"Expected {defaults_path} to exist"

    def test_valid_yaml_structure(self) -> None:
        """Should be valid YAML with expected structure."""
        patches_dir = Path(".bmad-assist/patches")
        defaults_path = patches_dir / "defaults-testarch.yaml"

        content = defaults_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        assert isinstance(data, dict)
        assert "post_process" in data

    def test_post_process_is_list(self) -> None:
        """Should have post_process as a list of rules."""
        patches_dir = Path(".bmad-assist/patches")
        defaults_path = patches_dir / "defaults-testarch.yaml"

        content = defaults_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        assert isinstance(data["post_process"], list)
        assert len(data["post_process"]) > 0

    def test_all_rules_have_required_fields(self) -> None:
        """Each rule should have pattern and replacement fields."""
        patches_dir = Path(".bmad-assist/patches")
        defaults_path = patches_dir / "defaults-testarch.yaml"

        content = defaults_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        for i, rule in enumerate(data["post_process"]):
            assert "pattern" in rule, f"Rule {i} missing 'pattern'"
            assert "replacement" in rule, f"Rule {i} missing 'replacement'"

    def test_has_installed_path_cleanup(self) -> None:
        """Should have rule for {installed_path} cleanup."""
        patches_dir = Path(".bmad-assist/patches")
        defaults_path = patches_dir / "defaults-testarch.yaml"

        content = defaults_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        patterns = [rule["pattern"] for rule in data["post_process"]]
        has_installed_path = any("installed_path" in p for p in patterns)
        assert has_installed_path, "Should have {installed_path} cleanup rule"

    def test_has_source_marker_cleanup(self) -> None:
        """Should have rule for [Source: ...] cleanup."""
        patches_dir = Path(".bmad-assist/patches")
        defaults_path = patches_dir / "defaults-testarch.yaml"

        content = defaults_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        patterns = [rule["pattern"] for rule in data["post_process"]]
        has_source_cleanup = any("Source:" in p for p in patterns)
        assert has_source_cleanup, "Should have [Source: ...] cleanup rule"

    def test_has_line_ending_normalization(self) -> None:
        """Should have rules for line ending normalization."""
        patches_dir = Path(".bmad-assist/patches")
        defaults_path = patches_dir / "defaults-testarch.yaml"

        content = defaults_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        patterns = [rule["pattern"] for rule in data["post_process"]]
        has_crlf = any(r"\r\n" in p or "\\r\\n" in p for p in patterns)
        has_cr = any(r"\r" in p or "\\r" in p for p in patterns)
        assert has_crlf or has_cr, "Should have line ending normalization rules"


class TestTeaPatchDiscovery:
    """Tests for TEA-specific patch discovery."""

    def test_discover_patch_finds_testarch_atdd(self, tmp_path: Path) -> None:
        """Should discover testarch-atdd.patch.yaml if it exists."""
        from bmad_assist.compiler.patching.discovery import discover_patch

        # Create patch file
        patches_dir = tmp_path / ".bmad-assist/patches"
        patches_dir.mkdir(parents=True)
        patch_file = patches_dir / "testarch-atdd.patch.yaml"
        patch_file.write_text(
            """
patch:
  name: testarch-atdd-patch
  version: "1.0.0"
compatibility:
  bmad_version: "6.0.0"
  workflow: testarch-atdd
transforms:
  - "Test transform"
"""
        )

        result = discover_patch("testarch-atdd", tmp_path)
        assert result is not None
        assert result == patch_file

    def test_discover_patch_returns_none_for_missing(self, tmp_path: Path) -> None:
        """Should return None if patch doesn't exist."""
        from bmad_assist.compiler.patching.discovery import discover_patch

        result = discover_patch("testarch-nonexistent", tmp_path)
        assert result is None


class TestLoadDefaults:
    """Tests for load_defaults function."""

    def test_loads_defaults_from_same_directory(self, tmp_path: Path) -> None:
        """Should load defaults.yaml from same directory as patch."""
        from bmad_assist.compiler.patching.discovery import load_defaults

        # Create patch directory
        patches_dir = tmp_path / ".bmad-assist/patches"
        patches_dir.mkdir(parents=True)

        # Create defaults.yaml
        defaults_file = patches_dir / "defaults.yaml"
        defaults_file.write_text(
            """
post_process:
  - pattern: "test-pattern"
    replacement: "test-replacement"
    flags: ""
"""
        )

        # Create a dummy patch file
        patch_file = patches_dir / "test-workflow.patch.yaml"
        patch_file.write_text("")

        result = load_defaults(patch_file)

        assert len(result) == 1
        assert result[0].pattern == "test-pattern"
        assert result[0].replacement == "test-replacement"

    def test_returns_empty_list_when_no_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return empty list when no defaults.yaml exists anywhere."""
        from bmad_assist.compiler.patching.discovery import load_defaults

        # Patch home to avoid loading global defaults
        monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))

        # Create patch file without defaults.yaml
        patches_dir = tmp_path / ".bmad-assist/patches"
        patches_dir.mkdir(parents=True)
        patch_file = patches_dir / "test-workflow.patch.yaml"
        patch_file.write_text("")

        result = load_defaults(patch_file)

        assert result == []

    def test_handles_invalid_yaml(self, tmp_path: Path) -> None:
        """Should return empty list for invalid YAML."""
        from bmad_assist.compiler.patching.discovery import load_defaults

        patches_dir = tmp_path / ".bmad-assist/patches"
        patches_dir.mkdir(parents=True)

        # Create invalid defaults.yaml
        defaults_file = patches_dir / "defaults.yaml"
        defaults_file.write_text("not: valid: yaml: [")

        patch_file = patches_dir / "test-workflow.patch.yaml"
        patch_file.write_text("")

        result = load_defaults(patch_file)

        assert result == []


class TestLoadDefaultsTeaMerging:
    """Tests for TEA defaults merging behavior."""

    def test_merges_tea_defaults_for_testarch_workflow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should merge defaults-testarch.yaml for testarch-* workflows."""
        from bmad_assist.compiler.patching.discovery import load_defaults

        # Patch home to control global defaults
        monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))

        patches_dir = tmp_path / ".bmad-assist/patches"
        patches_dir.mkdir(parents=True)

        # Create defaults.yaml (base)
        defaults_file = patches_dir / "defaults.yaml"
        defaults_file.write_text(
            """
post_process:
  - pattern: "base-pattern"
    replacement: "base"
    flags: ""
"""
        )

        # Create defaults-testarch.yaml (TEA overlay)
        tea_defaults_file = patches_dir / "defaults-testarch.yaml"
        tea_defaults_file.write_text(
            """
post_process:
  - pattern: "tea-pattern"
    replacement: "tea"
    flags: ""
"""
        )

        patch_file = patches_dir / "testarch-atdd.patch.yaml"
        patch_file.write_text("")

        # Load with TEA workflow name
        result = load_defaults(patch_file, workflow_name="testarch-atdd")

        # Should have both base and TEA rules
        assert len(result) == 2
        patterns = [r.pattern for r in result]
        assert "base-pattern" in patterns
        assert "tea-pattern" in patterns

    def test_does_not_merge_tea_defaults_for_non_tea_workflow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should NOT merge defaults-testarch.yaml for non-TEA workflows."""
        from bmad_assist.compiler.patching.discovery import load_defaults

        monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))

        patches_dir = tmp_path / ".bmad-assist/patches"
        patches_dir.mkdir(parents=True)

        defaults_file = patches_dir / "defaults.yaml"
        defaults_file.write_text(
            """
post_process:
  - pattern: "base-pattern"
    replacement: "base"
    flags: ""
"""
        )

        tea_defaults_file = patches_dir / "defaults-testarch.yaml"
        tea_defaults_file.write_text(
            """
post_process:
  - pattern: "tea-pattern"
    replacement: "tea"
    flags: ""
"""
        )

        patch_file = patches_dir / "dev-story.patch.yaml"
        patch_file.write_text("")

        # Load with non-TEA workflow name
        result = load_defaults(patch_file, workflow_name="dev-story")

        # Should only have base rules
        assert len(result) == 1
        assert result[0].pattern == "base-pattern"

    def test_merge_order_base_then_tea(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEA rules should come after base rules (for precedence)."""
        from bmad_assist.compiler.patching.discovery import load_defaults

        monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))

        patches_dir = tmp_path / ".bmad-assist/patches"
        patches_dir.mkdir(parents=True)

        defaults_file = patches_dir / "defaults.yaml"
        defaults_file.write_text(
            """
post_process:
  - pattern: "first"
    replacement: "1"
    flags: ""
"""
        )

        tea_defaults_file = patches_dir / "defaults-testarch.yaml"
        tea_defaults_file.write_text(
            """
post_process:
  - pattern: "second"
    replacement: "2"
    flags: ""
"""
        )

        patch_file = patches_dir / "testarch-ci.patch.yaml"
        patch_file.write_text("")

        result = load_defaults(patch_file, workflow_name="testarch-ci")

        # Order should be: base first, then TEA
        assert len(result) == 2
        assert result[0].pattern == "first"
        assert result[1].pattern == "second"


class TestIsTeaWorkflow:
    """Tests for is_tea_workflow helper."""

    def test_testarch_prefix_returns_true(self) -> None:
        """Should return True for testarch-* workflows."""
        from bmad_assist.compiler.patching.discovery import is_tea_workflow

        assert is_tea_workflow("testarch-atdd") is True
        assert is_tea_workflow("testarch-test-review") is True
        assert is_tea_workflow("testarch-ci") is True

    def test_non_tea_returns_false(self) -> None:
        """Should return False for non-TEA workflows."""
        from bmad_assist.compiler.patching.discovery import is_tea_workflow

        assert is_tea_workflow("dev-story") is False
        assert is_tea_workflow("create-story") is False
        assert is_tea_workflow("code-review") is False

    def test_empty_returns_false(self) -> None:
        """Should return False for empty string."""
        from bmad_assist.compiler.patching.discovery import is_tea_workflow

        assert is_tea_workflow("") is False


class TestTeaWorkflowPatches:
    """Tests for per-workflow TEA patch files."""

    def test_testarch_atdd_patch_exists(self) -> None:
        """Should have testarch-atdd.patch.yaml."""
        patches_dir = Path(".bmad-assist/patches")
        patch_path = patches_dir / "testarch-atdd.patch.yaml"
        assert patch_path.exists(), f"Expected {patch_path} to exist"

    def test_testarch_test_review_patch_exists(self) -> None:
        """Should have testarch-test-review.patch.yaml."""
        patches_dir = Path(".bmad-assist/patches")
        patch_path = patches_dir / "testarch-test-review.patch.yaml"
        assert patch_path.exists(), f"Expected {patch_path} to exist"

    def test_testarch_ci_patch_exists(self) -> None:
        """Should have testarch-ci.patch.yaml."""
        patches_dir = Path(".bmad-assist/patches")
        patch_path = patches_dir / "testarch-ci.patch.yaml"
        assert patch_path.exists(), f"Expected {patch_path} to exist"

    def test_testarch_test_design_patch_exists(self) -> None:
        """Should have testarch-test-design.patch.yaml."""
        patches_dir = Path(".bmad-assist/patches")
        patch_path = patches_dir / "testarch-test-design.patch.yaml"
        assert patch_path.exists(), f"Expected {patch_path} to exist"

    def test_all_patches_have_valid_structure(self) -> None:
        """All TEA patches should have valid YAML structure."""
        patches_dir = Path(".bmad-assist/patches")
        tea_patches = [
            "testarch-atdd.patch.yaml",
            "testarch-test-review.patch.yaml",
            "testarch-ci.patch.yaml",
            "testarch-test-design.patch.yaml",
        ]

        for patch_name in tea_patches:
            patch_path = patches_dir / patch_name
            if not patch_path.exists():
                continue

            content = patch_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            assert isinstance(data, dict), f"{patch_name} should be a dict"
            assert "patch" in data, f"{patch_name} should have 'patch' section"
            assert "compatibility" in data, f"{patch_name} should have 'compatibility'"
            assert "transforms" in data, f"{patch_name} should have 'transforms'"

    def test_all_patches_have_git_intelligence(self) -> None:
        """All TEA patches should have git_intelligence configured."""
        patches_dir = Path(".bmad-assist/patches")
        tea_patches = [
            "testarch-atdd.patch.yaml",
            "testarch-test-review.patch.yaml",
            "testarch-ci.patch.yaml",
            "testarch-test-design.patch.yaml",
        ]

        for patch_name in tea_patches:
            patch_path = patches_dir / patch_name
            if not patch_path.exists():
                continue

            content = patch_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            assert "git_intelligence" in data, f"{patch_name} should have git_intelligence"
            git_intel = data["git_intelligence"]
            assert git_intel.get("enabled", True), f"{patch_name} git_intelligence should be enabled"
            assert "commands" in git_intel, f"{patch_name} should have git commands"


class TestPostProcessRuleApplication:
    """Tests for post_process rule application."""

    def test_installed_path_removal(self) -> None:
        """Should remove {installed_path} placeholders."""
        from bmad_assist.compiler.patching.transforms import post_process_compiled
        from bmad_assist.compiler.patching.types import PostProcessRule

        rules = [
            PostProcessRule(
                pattern=r"\{installed_path\}",
                replacement="",
                flags="",
            )
        ]

        content = "Path is {installed_path}/workflow.yaml"
        result = post_process_compiled(content, rules)

        assert result == "Path is /workflow.yaml"

    def test_source_marker_removal(self) -> None:
        """Should remove [Source: ...] markers."""
        from bmad_assist.compiler.patching.transforms import post_process_compiled
        from bmad_assist.compiler.patching.types import PostProcessRule

        rules = [
            PostProcessRule(
                pattern=r"\[Source:\s*[^\]]+\]",
                replacement="",
                flags="IGNORECASE",
            )
        ]

        content = "Some text [Source: docs/readme.md] more text"
        result = post_process_compiled(content, rules)

        assert result == "Some text  more text"

    def test_line_ending_normalization(self) -> None:
        """Should normalize CRLF to LF."""
        from bmad_assist.compiler.patching.transforms import post_process_compiled
        from bmad_assist.compiler.patching.types import PostProcessRule

        rules = [
            PostProcessRule(
                pattern=r"\r\n",
                replacement="\n",
                flags="",
            ),
            PostProcessRule(
                pattern=r"\r",
                replacement="\n",
                flags="",
            ),
        ]

        content = "line1\r\nline2\rline3"
        result = post_process_compiled(content, rules)

        assert result == "line1\nline2\nline3"

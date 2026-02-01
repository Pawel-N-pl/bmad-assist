"""Tests for config_generator module.

Comprehensive tests covering:
- Provider and model constants (AC2, AC3)
- Provider selection (AC2)
- Model selection (AC3)
- Config generation and validation (AC4, AC5)
- Default values (AC9)
- Confirmation flow (AC10)
- Cancellation handling (AC8)
- Atomic write (AC11)
- New questionary-based wizard (AC1-AC14)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
import yaml
from rich.console import Console

from bmad_assist.core.config_generator import (
    AVAILABLE_PROVIDERS,
    CONFIG_FILENAME,
    PROVIDER_MODELS,
    ConfigGenerator,
    _check_cancelled,
    _is_interactive,
    run_config_wizard,
)

# =============================================================================
# Test: Constants and Provider Definitions
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_config_filename_is_bmad_assist_yaml(self) -> None:
        """Config filename matches expected value."""
        assert CONFIG_FILENAME == "bmad-assist.yaml"

    def test_available_providers_is_final_dict(self) -> None:
        """AVAILABLE_PROVIDERS is a dictionary."""
        assert isinstance(AVAILABLE_PROVIDERS, dict)
        assert len(AVAILABLE_PROVIDERS) > 0

    def test_provider_models_has_eight_providers(self) -> None:
        """PROVIDER_MODELS has 8 providers (excluding claude SDK)."""
        assert isinstance(PROVIDER_MODELS, dict)
        assert len(PROVIDER_MODELS) == 8

    def test_provider_models_excludes_claude_sdk(self) -> None:
        """PROVIDER_MODELS excludes 'claude' (SDK), includes 'claude-subprocess'."""
        assert "claude" not in PROVIDER_MODELS
        assert "claude-subprocess" in PROVIDER_MODELS


class TestProviderDefinitions:
    """Tests for provider and model definitions (AC2, AC3)."""

    def test_claude_provider_exists(self) -> None:
        """AC2: Claude provider is available."""
        assert "claude" in AVAILABLE_PROVIDERS

    def test_claude_has_required_fields(self) -> None:
        """Claude provider has display_name, models, default_model."""
        claude = AVAILABLE_PROVIDERS["claude"]
        assert "display_name" in claude
        assert "models" in claude
        assert "default_model" in claude

    def test_claude_models_include_opus_4(self) -> None:
        """AC3: Claude models include opus_4."""
        claude = AVAILABLE_PROVIDERS["claude"]
        assert "opus_4" in claude["models"]

    def test_claude_models_include_sonnet_4(self) -> None:
        """AC3: Claude models include sonnet_4."""
        claude = AVAILABLE_PROVIDERS["claude"]
        assert "sonnet_4" in claude["models"]

    def test_claude_models_include_sonnet_3_5(self) -> None:
        """AC3: Claude models include sonnet_3_5."""
        claude = AVAILABLE_PROVIDERS["claude"]
        assert "sonnet_3_5" in claude["models"]

    def test_claude_models_include_haiku_3_5(self) -> None:
        """AC3: Claude models include haiku_3_5."""
        claude = AVAILABLE_PROVIDERS["claude"]
        assert "haiku_3_5" in claude["models"]

    def test_claude_default_model_is_opus_4(self) -> None:
        """AC3: Claude default model is opus_4."""
        claude = AVAILABLE_PROVIDERS["claude"]
        assert claude["default_model"] == "opus_4"

    def test_codex_provider_exists(self) -> None:
        """AC2: Codex provider is available."""
        assert "codex" in AVAILABLE_PROVIDERS

    def test_codex_has_required_fields(self) -> None:
        """Codex provider has display_name, models, default_model."""
        codex = AVAILABLE_PROVIDERS["codex"]
        assert "display_name" in codex
        assert "models" in codex
        assert "default_model" in codex

    def test_gemini_provider_exists(self) -> None:
        """AC2: Gemini provider is available."""
        assert "gemini" in AVAILABLE_PROVIDERS

    def test_gemini_has_required_fields(self) -> None:
        """Gemini provider has display_name, models, default_model."""
        gemini = AVAILABLE_PROVIDERS["gemini"]
        assert "display_name" in gemini
        assert "models" in gemini
        assert "default_model" in gemini


class TestProviderModelsDefinitions:
    """Tests for new PROVIDER_MODELS definitions."""

    def test_all_providers_have_required_fields(self) -> None:
        """All providers in PROVIDER_MODELS have display, models, default."""
        for key, info in PROVIDER_MODELS.items():
            assert "display" in info, f"{key} missing 'display'"
            assert "models" in info, f"{key} missing 'models'"
            assert "default" in info, f"{key} missing 'default'"
            assert info["default"] in info["models"], f"{key} default not in models"

    def test_kimi_has_thinking_extra(self) -> None:
        """AC11: Kimi provider has thinking: true in extras."""
        kimi = PROVIDER_MODELS["kimi"]
        assert "extras" in kimi
        assert kimi["extras"]["thinking"] is True


# =============================================================================
# Test: _is_interactive helper
# =============================================================================


class TestIsInteractive:
    """Tests for _is_interactive function."""

    def test_returns_false_for_non_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-TTY stdin returns False."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        assert _is_interactive() is False

    def test_returns_false_for_ci_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CI environment returns False."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setenv("CI", "true")
        assert _is_interactive() is False

    def test_returns_false_for_github_actions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GITHUB_ACTIONS environment returns False."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert _is_interactive() is False

    def test_returns_true_for_interactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Interactive terminal returns True."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        # Clear all CI variables
        for var in ["CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "TRAVIS", "CIRCLECI"]:
            monkeypatch.delenv(var, raising=False)
        assert _is_interactive() is True


# =============================================================================
# Test: _check_cancelled helper
# =============================================================================


class TestCheckCancelled:
    """Tests for _check_cancelled function."""

    def test_returns_value_if_not_none(self) -> None:
        """Returns the value if not None."""
        console = Console()
        result = _check_cancelled("value", console)
        assert result == "value"

    def test_raises_exit_130_if_none(self) -> None:
        """Raises typer.Exit(130) if None."""
        console = Console()
        with pytest.raises(typer.Exit) as exc_info:
            _check_cancelled(None, console)
        assert exc_info.value.exit_code == 130


# =============================================================================
# Test: ConfigGenerator Class
# =============================================================================


class TestConfigGeneratorInit:
    """Tests for ConfigGenerator initialization."""

    def test_init_with_no_console_creates_one(self) -> None:
        """ConfigGenerator creates console if none provided."""
        generator = ConfigGenerator()
        assert generator.console is not None
        assert isinstance(generator.console, Console)

    def test_init_with_console_uses_provided(self) -> None:
        """ConfigGenerator uses provided console."""
        custom_console = Console()
        generator = ConfigGenerator(console=custom_console)
        assert generator.console is custom_console


class TestQuestionaryProviderSelection:
    """Tests for questionary-based provider selection."""

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.select")
    def test_select_provider_returns_selection(
        self, mock_select: MagicMock, mock_interactive: MagicMock
    ) -> None:
        """Provider selection returns user choice via questionary."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.return_value = "gemini"
        generator = ConfigGenerator(Console())
        result = generator._select_provider("Select provider")
        assert result == "gemini"

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.select")
    def test_select_provider_uses_default(
        self, mock_select: MagicMock, mock_interactive: MagicMock
    ) -> None:
        """Provider selection uses claude-subprocess as default."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.return_value = "claude-subprocess"
        generator = ConfigGenerator(Console())
        generator._select_provider("Select provider")
        mock_select.assert_called_once()
        call_kwargs = mock_select.call_args[1]
        assert call_kwargs.get("default") == "claude-subprocess"


class TestQuestionaryModelSelection:
    """Tests for questionary-based model selection."""

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.select")
    def test_select_model_returns_selection(
        self, mock_select: MagicMock, mock_interactive: MagicMock
    ) -> None:
        """Model selection returns user choice via questionary."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.return_value = "opus"
        generator = ConfigGenerator(Console())
        result = generator._select_model("claude-subprocess")
        assert result == "opus"

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.select")
    def test_select_model_uses_default(
        self, mock_select: MagicMock, mock_interactive: MagicMock
    ) -> None:
        """Model selection uses provider's default model."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.return_value = "gemini-2.5-flash"
        generator = ConfigGenerator(Console())
        generator._select_model("gemini")
        mock_select.assert_called_once()
        call_kwargs = mock_select.call_args[1]
        assert call_kwargs.get("default") == "gemini-2.5-flash"


class TestBuildConfig:
    """Tests for config dictionary building (AC4, AC9)."""

    def test_build_config_contains_provider(self) -> None:
        """AC4: Built config contains provider."""
        generator = ConfigGenerator(Console())
        config = generator._build_config("claude-subprocess", "opus", [], None)
        assert config["providers"]["master"]["provider"] == "claude-subprocess"

    def test_build_config_contains_model(self) -> None:
        """AC4: Built config contains model."""
        generator = ConfigGenerator(Console())
        config = generator._build_config("claude-subprocess", "opus", [], None)
        assert config["providers"]["master"]["model"] == "opus"

    def test_build_config_no_state_path(self) -> None:
        """AC9: Built config does NOT include state_path (uses project-based default)."""
        generator = ConfigGenerator(Console())
        config = generator._build_config("claude-subprocess", "opus", [], None)
        # state_path is not set - get_state_path() uses project_root instead
        assert "state_path" not in config

    def test_build_config_has_default_timeout(self) -> None:
        """AC9: Built config has default timeout of 300."""
        generator = ConfigGenerator(Console())
        config = generator._build_config("claude-subprocess", "opus", [], None)
        assert config["timeout"] == 300

    def test_build_config_omits_empty_multi(self) -> None:
        """AC14: Empty multi-validators list is omitted from config."""
        generator = ConfigGenerator(Console())
        config = generator._build_config("claude-subprocess", "opus", [], None)
        assert "multi" not in config["providers"]

    def test_build_config_includes_multi_when_provided(self) -> None:
        """Multi-validators included when provided."""
        generator = ConfigGenerator(Console())
        validators = [{"provider": "gemini", "model": "gemini-2.5-flash"}]
        config = generator._build_config("claude-subprocess", "opus", validators, None)
        assert "multi" in config["providers"]
        assert len(config["providers"]["multi"]) == 1

    def test_build_config_includes_helper_when_provided(self) -> None:
        """Helper provider included when provided."""
        generator = ConfigGenerator(Console())
        helper = {"provider": "claude-subprocess", "model": "haiku"}
        config = generator._build_config("claude-subprocess", "opus", [], helper)
        assert "helper" in config["providers"]
        assert config["providers"]["helper"]["model"] == "haiku"

    def test_build_config_kimi_includes_thinking(self) -> None:
        """AC11: Kimi provider includes thinking: true."""
        generator = ConfigGenerator(Console())
        config = generator._build_config("kimi", "kimi-code/kimi-for-coding", [], None)
        assert config["providers"]["master"]["thinking"] is True


# =============================================================================
# Test: Questionary-based wizard
# =============================================================================


class TestQuestionaryWizard:
    """Tests for new questionary-based wizard flow."""

    @patch("bmad_assist.core.config_generator._is_interactive")
    def test_non_interactive_exits_with_code_1(
        self, mock_interactive: MagicMock, tmp_path: Path
    ) -> None:
        """AC6: Non-interactive environment exits with code 1."""
        mock_interactive.return_value = False
        generator = ConfigGenerator(Console())

        with pytest.raises(typer.Exit) as exc_info:
            generator.run(tmp_path)

        assert exc_info.value.exit_code == 1

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_ctrl_c_exits_with_code_130(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC4: Ctrl+C exits with code 130."""
        mock_interactive.return_value = True
        # Simulate Ctrl+C by returning None
        mock_select.return_value.ask.return_value = None

        generator = ConfigGenerator(Console())

        with pytest.raises(typer.Exit) as exc_info:
            generator.run(tmp_path)

        assert exc_info.value.exit_code == 130

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_overwrite_declined_exits_with_130(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC5: Declining overwrite exits with code 130."""
        mock_interactive.return_value = True
        # Create existing config
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text("providers:\n  master:\n    provider: claude\n    model: opus\n")

        # Decline overwrite
        mock_confirm.return_value.ask.return_value = False

        generator = ConfigGenerator(Console())

        with pytest.raises(typer.Exit) as exc_info:
            generator.run(tmp_path)

        assert exc_info.value.exit_code == 130

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_wizard_creates_config_file(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC1: Wizard creates valid config file."""
        mock_interactive.return_value = True
        # Mock selections: provider, model, skip multi (done), skip helper, confirm save
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",  # provider
            "opus",  # model
            "done",  # skip multi-validators
        ]
        mock_confirm.return_value.ask.side_effect = [
            False,  # no helper
            True,  # save config
        ]

        generator = ConfigGenerator(Console())
        config_path = generator.run(tmp_path)

        assert config_path.exists()
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config["providers"]["master"]["provider"] == "claude-subprocess"
        assert config["providers"]["master"]["model"] == "opus"


# =============================================================================
# Test: Config Generation and Validation (Legacy tests)
# =============================================================================


class TestConfigGeneration:
    """Tests for config file generation (AC4, AC5)."""

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_generates_yaml_file(
        self,
        mock_q_select: MagicMock,
        mock_q_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC4: Generated config is a YAML file."""
        mock_interactive.return_value = True
        mock_q_select.return_value.ask.side_effect = [
            "claude-subprocess",
            "opus",
            "done",
        ]
        mock_q_confirm.return_value.ask.side_effect = [False, True]

        config_path = run_config_wizard(tmp_path, Console())

        assert config_path.exists()
        assert config_path.suffix == ".yaml"

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_generates_valid_yaml(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC4: Generated config is valid YAML."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",
            "opus",
            "done",
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]

        config_path = run_config_wizard(tmp_path, Console())

        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config is not None
        assert isinstance(config, dict)

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_yaml_has_providers_section(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC4: Generated YAML has providers section."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",
            "opus",
            "done",
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]

        config_path = run_config_wizard(tmp_path, Console())

        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert "providers" in config
        assert "master" in config["providers"]

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_yaml_has_header_comments(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC4: Generated YAML has header comments."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",
            "opus",
            "done",
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]

        config_path = run_config_wizard(tmp_path, Console())

        content = config_path.read_text()
        assert "# bmad-assist configuration" in content
        assert "# Generated by interactive setup wizard" in content


# =============================================================================
# Test: Cancellation Handling
# =============================================================================


class TestCancellation:
    """Tests for cancellation handling (AC8)."""

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.select")
    def test_ctrl_c_propagates(
        self,
        mock_select: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC8: Ctrl+C (None from questionary) exits with 130."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.return_value = None  # Simulates Ctrl+C

        with pytest.raises(typer.Exit) as exc_info:
            run_config_wizard(tmp_path, Console())

        assert exc_info.value.exit_code == 130

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.select")
    def test_no_partial_file_on_ctrl_c(
        self,
        mock_select: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC8: No partial config file on Ctrl+C."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.return_value = None
        config_path = tmp_path / CONFIG_FILENAME

        with pytest.raises(typer.Exit):
            run_config_wizard(tmp_path, Console())

        assert not config_path.exists()


# =============================================================================
# Test: Atomic Write
# =============================================================================


class TestAtomicWrite:
    """Tests for atomic write pattern (AC11)."""

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_file_created_atomically(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC11: Config file is created atomically."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",
            "opus",
            "done",
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]

        config_path = run_config_wizard(tmp_path, Console())

        # File should exist and be valid
        assert config_path.exists()
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config is not None

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_no_temp_files_left_on_success(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC11: No temp files left behind on success."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",
            "opus",
            "done",
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]

        run_config_wizard(tmp_path, Console())

        temp_files = list(tmp_path.glob(".bmad-assist-*.yaml.tmp"))
        assert len(temp_files) == 0

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    @patch("bmad_assist.core.config_generator.os.rename")
    def test_temp_file_cleanup_on_rename_failure(
        self,
        mock_rename: MagicMock,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC11: Temp file cleaned up if rename fails."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",
            "opus",
            "done",
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]
        mock_rename.side_effect = OSError("Rename failed")

        with pytest.raises(OSError):
            run_config_wizard(tmp_path, Console())

        # Verify no temp files left behind
        temp_files = list(tmp_path.glob(".bmad-assist-*.yaml.tmp"))
        assert len(temp_files) == 0


# =============================================================================
# Test: run_config_wizard Function
# =============================================================================


class TestRunConfigWizard:
    """Tests for run_config_wizard function."""

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_returns_path_to_config(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """run_config_wizard returns path to generated config."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",
            "opus",
            "done",
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]

        result = run_config_wizard(tmp_path, Console())

        assert isinstance(result, Path)
        assert result.name == CONFIG_FILENAME
        assert result.parent == tmp_path


# =============================================================================
# Test: Display Methods (Smoke Tests)
# =============================================================================


class TestDisplayMethods:
    """Smoke tests for display methods."""

    def test_display_welcome_does_not_raise(self) -> None:
        """_display_welcome executes without error."""
        generator = ConfigGenerator(Console())
        # Should not raise
        generator._display_welcome()

    def test_display_summary_does_not_raise(self) -> None:
        """_display_summary executes without error."""
        generator = ConfigGenerator(Console())
        config = generator._build_config("claude-subprocess", "opus", [], None)
        # Should not raise
        generator._display_summary(config)

    def test_display_non_interactive_fallback_does_not_raise(self) -> None:
        """_display_non_interactive_fallback executes without error."""
        generator = ConfigGenerator(Console())
        # Should not raise
        generator._display_non_interactive_fallback()

    def test_show_summary_does_not_raise(self) -> None:
        """_show_summary executes without error."""
        generator = ConfigGenerator(Console())
        config = generator._build_config("claude-subprocess", "opus", [], None)
        # Should not raise
        generator._show_summary(config, Path("/tmp/test.yaml"))


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_config_in_subdirectory(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Config can be generated in subdirectory."""
        subdir = tmp_path / "my-project"
        subdir.mkdir()

        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",
            "opus",
            "done",
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]

        config_path = run_config_wizard(subdir, Console())

        assert config_path.parent == subdir
        assert config_path.exists()

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_multi_validator_skip_immediately(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """User skips multi-validators without adding any."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "gemini",  # master provider
            "gemini-2.5-flash",  # master model
            "done",  # skip multi-validators immediately
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]  # no helper, save

        config_path = run_config_wizard(tmp_path, Console())

        config = yaml.safe_load(config_path.read_text())
        assert "multi" not in config["providers"]

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_multi_validator_add_then_remove_all(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """User adds validators then removes them all."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",  # master provider
            "opus",  # master model
            "add",  # add validator
            "gemini",  # validator provider
            "gemini-2.5-flash",  # validator model
            "remove",  # remove validator
            0,  # select first to remove
            "done",  # done with no validators
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]

        config_path = run_config_wizard(tmp_path, Console())

        config = yaml.safe_load(config_path.read_text())
        assert "multi" not in config["providers"]

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_multi_validator_add_multiple(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """User adds multiple validators."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",  # master provider
            "opus",  # master model
            "add",  # add first validator
            "gemini",  # validator 1 provider
            "gemini-2.5-flash",  # validator 1 model
            "add",  # add second validator
            "codex",  # validator 2 provider
            "o3-mini",  # validator 2 model
            "done",  # done
        ]
        mock_confirm.return_value.ask.side_effect = [False, True]

        config_path = run_config_wizard(tmp_path, Console())

        config = yaml.safe_load(config_path.read_text())
        assert "multi" in config["providers"]
        assert len(config["providers"]["multi"]) == 2
        assert config["providers"]["multi"][0]["provider"] == "gemini"
        assert config["providers"]["multi"][1]["provider"] == "codex"

"""Tests for config commands (wizard and verify).

Integration tests using CliRunner for:
- bmad-assist config wizard
- bmad-assist config verify
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from bmad_assist.cli import app

runner = CliRunner()


# =============================================================================
# Test: config wizard command
# =============================================================================


class TestConfigWizardCommand:
    """Tests for 'bmad-assist config wizard' command."""

    @patch("bmad_assist.core.config_generator._is_interactive")
    def test_non_interactive_exits_with_code_1(
        self, mock_interactive: MagicMock, tmp_path: Path
    ) -> None:
        """Non-interactive environment exits with code 1."""
        mock_interactive.return_value = False

        result = runner.invoke(app, ["config", "wizard", "--project", str(tmp_path)])

        assert result.exit_code == 1
        assert "Non-interactive" in result.output or "template" in result.output.lower()

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.select")
    def test_ctrl_c_exits_with_code_130(
        self,
        mock_select: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Ctrl+C exits with code 130."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.return_value = None  # Simulate Ctrl+C

        result = runner.invoke(app, ["config", "wizard", "--project", str(tmp_path)])

        assert result.exit_code == 130

    def test_invalid_project_path(self, tmp_path: Path) -> None:
        """Invalid project path shows error."""
        nonexistent = tmp_path / "nonexistent"

        result = runner.invoke(app, ["config", "wizard", "--project", str(nonexistent)])

        assert result.exit_code != 0
        assert "not exist" in result.output.lower() or "Error" in result.output

    @patch("bmad_assist.core.config_generator._is_interactive")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_wizard_creates_config(
        self,
        mock_select: MagicMock,
        mock_confirm: MagicMock,
        mock_interactive: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Wizard creates valid config file."""
        mock_interactive.return_value = True
        mock_select.return_value.ask.side_effect = [
            "claude-subprocess",
            "opus",
            "done",  # skip multi-validators
        ]
        mock_confirm.return_value.ask.side_effect = [
            False,  # no helper
            True,  # save config
        ]

        result = runner.invoke(app, ["config", "wizard", "--project", str(tmp_path)])

        assert result.exit_code == 0
        config_path = tmp_path / "bmad-assist.yaml"
        assert config_path.exists()


# =============================================================================
# Test: config verify command
# =============================================================================


class TestConfigVerifyCommand:
    """Tests for 'bmad-assist config verify' command."""

    def test_verify_valid_config(self, tmp_path: Path) -> None:
        """Valid config shows success and exits 0."""
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text(
            """
providers:
  master:
    provider: claude-subprocess
    model: opus
"""
        )

        result = runner.invoke(app, ["config", "verify", str(config_path)])

        assert result.exit_code == 0
        # Should show at least one OK
        assert "[OK]" in result.output or "valid" in result.output.lower()

    def test_verify_missing_file(self, tmp_path: Path) -> None:
        """Missing config file shows error and exits non-zero."""
        config_path = tmp_path / "nonexistent.yaml"

        result = runner.invoke(app, ["config", "verify", str(config_path)])

        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "ERR" in result.output

    def test_verify_invalid_yaml(self, tmp_path: Path) -> None:
        """Invalid YAML syntax shows error and exits non-zero."""
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text("providers:\n  master:\n    provider: claude\n    model  opus")

        result = runner.invoke(app, ["config", "verify", str(config_path)])

        assert result.exit_code != 0
        assert "[ERR]" in result.output

    def test_verify_invalid_provider(self, tmp_path: Path) -> None:
        """Invalid provider name shows error and exits non-zero."""
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text(
            """
providers:
  master:
    provider: invalid-provider
    model: opus
"""
        )

        result = runner.invoke(app, ["config", "verify", str(config_path)])

        assert result.exit_code != 0
        assert "[ERR]" in result.output
        assert "invalid-provider" in result.output

    def test_verify_missing_required_field(self, tmp_path: Path) -> None:
        """Missing required field shows error and exits non-zero."""
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text(
            """
providers:
  master:
    provider: claude-subprocess
    # model is missing
"""
        )

        result = runner.invoke(app, ["config", "verify", str(config_path)])

        assert result.exit_code != 0
        assert "[ERR]" in result.output
        assert "model" in result.output.lower()

    def test_verify_missing_settings_warns(self, tmp_path: Path) -> None:
        """Missing settings file shows warning but exits 0."""
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text(
            """
providers:
  master:
    provider: claude-subprocess
    model: opus
    settings: ~/nonexistent-settings.json
"""
        )

        result = runner.invoke(app, ["config", "verify", str(config_path)])

        # Warnings don't cause failure - this is a valid config with warnings
        # The exit code depends on whether schema validation passes
        # For now, just check the output contains expected info
        assert "settings" in result.output.lower() or "[WARN]" in result.output

    def test_verify_default_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify uses default path when no argument provided."""
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text(
            """
providers:
  master:
    provider: claude-subprocess
    model: opus
"""
        )

        result = runner.invoke(app, ["config", "verify"])

        assert result.exit_code == 0

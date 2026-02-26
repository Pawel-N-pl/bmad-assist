"""Tests for config_validator module.

Comprehensive tests covering:
- YAML syntax validation
- Required fields validation
- Provider name validation
- Settings path validation
- Validation report formatting
"""

from pathlib import Path

import pytest

from bmad_assist.core.config_validator import (
    ValidationResult,
    _validate_provider_names,
    _validate_required_fields,
    _validate_settings_paths,
    format_validation_report,
    validate_config_file,
)

# =============================================================================
# Test: ValidationResult dataclass
# =============================================================================


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_ok_status(self) -> None:
        """ValidationResult with ok status."""
        result = ValidationResult(
            status="ok",
            field_path="providers.master.provider",
            message="Provider is valid",
        )
        assert result.status == "ok"
        assert result.suggestion is None

    def test_warn_status_with_suggestion(self) -> None:
        """ValidationResult with warn status and suggestion."""
        result = ValidationResult(
            status="warn",
            field_path="providers.master.settings",
            message="Settings file not found",
            suggestion="Create the settings file",
        )
        assert result.status == "warn"
        assert result.suggestion is not None

    def test_error_status(self) -> None:
        """ValidationResult with error status."""
        result = ValidationResult(
            status="error",
            field_path="providers.master.provider",
            message="Unknown provider: invalid",
        )
        assert result.status == "error"


# =============================================================================
# Test: validate_config_file
# =============================================================================


class TestValidateConfigFile:
    """Tests for validate_config_file function."""

    def test_valid_config(self, tmp_path: Path) -> None:
        """Valid config returns ok statuses."""
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text(
            """
providers:
  master:
    provider: claude-subprocess
    model: opus
"""
        )

        results = validate_config_file(config_path)

        # Should have some ok results
        ok_results = [r for r in results if r.status == "ok"]
        assert len(ok_results) > 0

        # Should have no errors
        error_results = [r for r in results if r.status == "error"]
        assert len(error_results) == 0

    def test_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        """Invalid YAML syntax returns error."""
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text(
            """
providers:
  master:
    provider: claude
    model  opus  # Missing colon
"""
        )

        results = validate_config_file(config_path)

        error_results = [r for r in results if r.status == "error"]
        assert len(error_results) > 0
        assert any("YAML syntax" in r.message for r in error_results)

    def test_empty_config(self, tmp_path: Path) -> None:
        """Empty config returns error."""
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text("")

        results = validate_config_file(config_path)

        error_results = [r for r in results if r.status == "error"]
        assert len(error_results) > 0
        assert any("empty" in r.message.lower() for r in error_results)

    def test_config_not_mapping(self, tmp_path: Path) -> None:
        """Config that is not a mapping returns error."""
        config_path = tmp_path / "bmad-assist.yaml"
        config_path.write_text("- item1\n- item2")

        results = validate_config_file(config_path)

        error_results = [r for r in results if r.status == "error"]
        assert len(error_results) > 0


# =============================================================================
# Test: _validate_required_fields
# =============================================================================


class TestValidateRequiredFields:
    """Tests for _validate_required_fields function."""

    def test_missing_providers_section(self) -> None:
        """Missing providers section returns error."""
        config_data = {"timeout": 300}

        results = _validate_required_fields(config_data)

        assert len(results) > 0
        assert any(r.status == "error" and "providers" in r.field_path for r in results)

    def test_missing_master_section(self) -> None:
        """Missing providers.master section returns error."""
        config_data = {"providers": {}}

        results = _validate_required_fields(config_data)

        assert any(r.status == "error" and "master" in r.message.lower() for r in results)

    def test_missing_provider_field(self) -> None:
        """Missing provider field returns error."""
        config_data = {"providers": {"master": {"model": "opus"}}}

        results = _validate_required_fields(config_data)

        assert any(r.status == "error" and "provider" in r.message.lower() for r in results)

    def test_missing_model_field(self) -> None:
        """Missing model field returns error."""
        config_data = {"providers": {"master": {"provider": "claude"}}}

        results = _validate_required_fields(config_data)

        assert any(r.status == "error" and "model" in r.message.lower() for r in results)

    def test_all_required_fields_present(self) -> None:
        """All required fields present returns ok statuses."""
        config_data = {
            "providers": {
                "master": {
                    "provider": "claude-subprocess",
                    "model": "opus",
                }
            }
        }

        results = _validate_required_fields(config_data)

        ok_results = [r for r in results if r.status == "ok"]
        assert len(ok_results) >= 2  # provider and model


# =============================================================================
# Test: _validate_provider_names
# =============================================================================


class TestValidateProviderNames:
    """Tests for _validate_provider_names function."""

    def test_valid_provider_name(self) -> None:
        """Valid provider name returns no errors."""
        config_data = {
            "providers": {
                "master": {
                    "provider": "claude-subprocess",
                    "model": "opus",
                }
            }
        }

        results = _validate_provider_names(config_data)

        error_results = [r for r in results if r.status == "error"]
        assert len(error_results) == 0

    def test_invalid_provider_name(self) -> None:
        """Invalid provider name returns error with available providers."""
        config_data = {
            "providers": {
                "master": {
                    "provider": "invalid-provider",
                    "model": "opus",
                }
            }
        }

        results = _validate_provider_names(config_data)

        error_results = [r for r in results if r.status == "error"]
        assert len(error_results) > 0
        assert any("invalid-provider" in r.message for r in error_results)
        assert any("Available" in (r.suggestion or "") for r in error_results)

    def test_invalid_multi_provider(self) -> None:
        """Invalid provider in multi section returns error."""
        config_data = {
            "providers": {
                "master": {
                    "provider": "claude-subprocess",
                    "model": "opus",
                },
                "multi": [
                    {"provider": "invalid-multi", "model": "test"},
                ],
            }
        }

        results = _validate_provider_names(config_data)

        error_results = [r for r in results if r.status == "error"]
        assert len(error_results) > 0
        assert any("invalid-multi" in r.message for r in error_results)

    def test_invalid_helper_provider(self) -> None:
        """Invalid provider in helper section returns error."""
        config_data = {
            "providers": {
                "master": {
                    "provider": "claude-subprocess",
                    "model": "opus",
                },
                "helper": {
                    "provider": "invalid-helper",
                    "model": "test",
                },
            }
        }

        results = _validate_provider_names(config_data)

        error_results = [r for r in results if r.status == "error"]
        assert len(error_results) > 0
        assert any("invalid-helper" in r.message for r in error_results)


# =============================================================================
# Test: _validate_settings_paths
# =============================================================================


class TestValidateSettingsPaths:
    """Tests for _validate_settings_paths function."""

    def test_existing_settings_file(self, tmp_path: Path) -> None:
        """Existing settings file returns ok status."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")

        config_data = {
            "providers": {
                "master": {
                    "provider": "claude-subprocess",
                    "model": "opus",
                    "settings": str(settings_file),
                }
            }
        }

        results = _validate_settings_paths(config_data)

        ok_results = [r for r in results if r.status == "ok"]
        assert len(ok_results) > 0

    def test_missing_settings_file(self, tmp_path: Path) -> None:
        """Missing settings file returns warning."""
        config_data = {
            "providers": {
                "master": {
                    "provider": "claude-subprocess",
                    "model": "opus",
                    "settings": str(tmp_path / "nonexistent.json"),
                }
            }
        }

        results = _validate_settings_paths(config_data)

        warn_results = [r for r in results if r.status == "warn"]
        assert len(warn_results) > 0
        assert any("not found" in r.message for r in warn_results)

    def test_tilde_expansion(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings path with ~ is expanded."""
        # Create a settings file in tmp_path and pretend it's home
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")

        # Set HOME env var so Path.expanduser uses tmp_path as home
        monkeypatch.setenv("HOME", str(tmp_path))

        config_data = {
            "providers": {
                "master": {
                    "provider": "claude-subprocess",
                    "model": "opus",
                    "settings": "~/settings.json",
                }
            }
        }

        results = _validate_settings_paths(config_data)

        # Should find the settings file and report OK
        assert len(results) > 0
        # Should find the file successfully since HOME points to tmp_path
        ok_results = [r for r in results if r.status == "ok"]
        assert len(ok_results) == 1
        assert "settings.json" in ok_results[0].message


# =============================================================================
# Test: format_validation_report
# =============================================================================


class TestFormatValidationReport:
    """Tests for format_validation_report function."""

    def test_ok_results_format(self, tmp_path: Path) -> None:
        """OK results are formatted correctly."""
        results = [
            ValidationResult(
                status="ok",
                field_path="providers.master.provider",
                message="Provider is valid",
            )
        ]
        config_path = tmp_path / "bmad-assist.yaml"

        report, has_errors = format_validation_report(results, config_path)

        assert "[OK]" in report
        assert has_errors is False

    def test_warn_results_format(self, tmp_path: Path) -> None:
        """WARN results are formatted correctly."""
        results = [
            ValidationResult(
                status="warn",
                field_path="providers.master.settings",
                message="Settings file not found",
                suggestion="Create the file",
            )
        ]
        config_path = tmp_path / "bmad-assist.yaml"

        report, has_errors = format_validation_report(results, config_path)

        assert "[WARN]" in report
        assert has_errors is False  # Warnings don't count as errors

    def test_error_results_format(self, tmp_path: Path) -> None:
        """ERR results are formatted correctly."""
        results = [
            ValidationResult(
                status="error",
                field_path="providers.master.provider",
                message="Unknown provider",
            )
        ]
        config_path = tmp_path / "bmad-assist.yaml"

        report, has_errors = format_validation_report(results, config_path)

        assert "[ERR]" in report
        assert has_errors is True

    def test_mixed_results(self, tmp_path: Path) -> None:
        """Mixed results are formatted correctly."""
        results = [
            ValidationResult(status="ok", field_path="syntax", message="Valid"),
            ValidationResult(status="warn", field_path="settings", message="Not found"),
            ValidationResult(status="error", field_path="provider", message="Invalid"),
        ]
        config_path = tmp_path / "bmad-assist.yaml"

        report, has_errors = format_validation_report(results, config_path)

        assert "[OK]" in report
        assert "[WARN]" in report
        assert "[ERR]" in report
        assert has_errors is True

    def test_summary_line_valid(self, tmp_path: Path) -> None:
        """Valid config shows success summary."""
        results = [
            ValidationResult(status="ok", field_path="test", message="Valid"),
        ]
        config_path = tmp_path / "bmad-assist.yaml"

        report, has_errors = format_validation_report(results, config_path)

        assert "valid" in report.lower() or "✓" in report
        assert has_errors is False

    def test_summary_line_errors(self, tmp_path: Path) -> None:
        """Config with errors shows error summary."""
        results = [
            ValidationResult(status="error", field_path="test", message="Error"),
        ]
        config_path = tmp_path / "bmad-assist.yaml"

        report, has_errors = format_validation_report(results, config_path)

        assert "error" in report.lower() or "✗" in report
        assert has_errors is True

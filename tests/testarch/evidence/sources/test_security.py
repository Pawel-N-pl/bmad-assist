"""Tests for SecuritySource."""

from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.testarch.evidence.models import SourceConfig
from bmad_assist.testarch.evidence.sources.security import (
    ALLOWED_COMMANDS,
    DEFAULT_SECURITY_PATTERNS,
    SecuritySource,
)


class TestSecuritySourceProperties:
    """Tests for SecuritySource properties."""

    def test_source_type(self) -> None:
        """Test source_type property."""
        source = SecuritySource()
        assert source.source_type == "security"

    def test_default_patterns(self) -> None:
        """Test default_patterns property."""
        source = SecuritySource()
        assert source.default_patterns == DEFAULT_SECURITY_PATTERNS
        assert "**/npm-audit.json" in source.default_patterns
        assert "**/security-audit.json" in source.default_patterns

    def test_allowed_commands_frozenset(self) -> None:
        """Test that ALLOWED_COMMANDS is a frozenset."""
        assert isinstance(ALLOWED_COMMANDS, frozenset)
        assert ("npm", "audit", "--json") in ALLOWED_COMMANDS


class TestNpmAuditFileParsing:
    """Tests for npm audit JSON file parsing."""

    def test_parse_npm_audit_new_format(self, tmp_path: Path) -> None:
        """Test parsing npm audit JSON (new format with vulnerabilities at root)."""
        audit_content = """{
  "vulnerabilities": {
    "lodash": {
      "name": "lodash",
      "severity": "high",
      "range": "<4.17.21",
      "fixAvailable": true,
      "via": [{"title": "Prototype Pollution"}]
    },
    "minimist": {
      "name": "minimist",
      "severity": "moderate",
      "range": "<1.2.6",
      "fixAvailable": false,
      "via": ["Prototype Pollution"]
    }
  }
}"""
        audit_file = tmp_path / "npm-audit.json"
        audit_file.write_text(audit_content)

        source = SecuritySource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.high == 1
        assert evidence.moderate == 1
        assert evidence.total == 2
        assert evidence.fix_available == 1
        assert any("lodash" in v for v in evidence.vulnerabilities)

    def test_parse_npm_audit_old_format(self, tmp_path: Path) -> None:
        """Test parsing npm audit JSON (old format with metadata.vulnerabilities)."""
        audit_content = """{
  "metadata": {
    "vulnerabilities": {
      "critical": 1,
      "high": 2,
      "moderate": 3,
      "low": 1,
      "info": 0,
      "total": 7
    }
  },
  "advisories": {
    "123": {
      "title": "Critical Issue",
      "severity": "critical",
      "module_name": "bad-pkg",
      "patched_versions": ">=2.0.0"
    }
  }
}"""
        audit_file = tmp_path / "npm-audit.json"
        audit_file.write_text(audit_content)

        source = SecuritySource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.critical == 1
        assert evidence.high == 2
        assert evidence.moderate == 3
        assert evidence.low == 1
        assert evidence.total == 7
        assert evidence.fix_available == 1  # patched_versions != <0.0.0

    def test_parse_npm_audit_invalid_json(self, tmp_path: Path) -> None:
        """Test parsing invalid JSON returns None."""
        audit_file = tmp_path / "npm-audit.json"
        audit_file.write_text("not valid json {{{")

        source = SecuritySource()
        evidence = source.collect(tmp_path)

        assert evidence is None


class TestNpmAuditCommand:
    """Tests for npm audit command execution."""

    def test_runs_command_when_package_json_exists(self, tmp_path: Path) -> None:
        """Test that npm audit command is run when package.json exists."""
        # Create package.json
        package_json = tmp_path / "package.json"
        package_json.write_text('{"name": "test"}')

        # Mock subprocess.run
        mock_output = """{
  "vulnerabilities": {
    "test-pkg": {
      "severity": "low",
      "fixAvailable": true,
      "via": ["issue"]
    }
  }
}"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = mock_output
            mock_run.return_value.returncode = 0

            source = SecuritySource()
            evidence = source.collect(tmp_path)

            assert evidence is not None
            assert evidence.low == 1
            mock_run.assert_called_once()
            # Verify command was in allowlist format (now tuple, not list)
            call_args = mock_run.call_args
            assert call_args[0][0] == ("npm", "audit", "--json")
            assert call_args[1]["shell"] is False

    def test_no_command_without_package_json(self, tmp_path: Path) -> None:
        """Test that command is not run without package.json."""
        source = SecuritySource()
        evidence = source.collect(tmp_path)
        assert evidence is None

    def test_handles_command_timeout(self, tmp_path: Path) -> None:
        """Test handling of command timeout."""
        import subprocess

        package_json = tmp_path / "package.json"
        package_json.write_text('{"name": "test"}')

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("npm", 30)

            source = SecuritySource()
            evidence = source.collect(tmp_path)

            assert evidence is None

    def test_handles_command_not_found(self, tmp_path: Path) -> None:
        """Test handling when npm is not installed."""
        package_json = tmp_path / "package.json"
        package_json.write_text('{"name": "test"}')

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            source = SecuritySource()
            evidence = source.collect(tmp_path)

            assert evidence is None


class TestSecurityAllowlist:
    """Tests for command allowlist security."""

    def test_only_allowed_commands_run(self) -> None:
        """Verify allowlist contains only expected commands."""
        # The allowlist should be minimal
        assert len(ALLOWED_COMMANDS) == 1
        assert ("npm", "audit", "--json") in ALLOWED_COMMANDS

    def test_custom_command_from_config(self, tmp_path: Path) -> None:
        """Test that custom command from config is used and validated."""
        from bmad_assist.testarch.config import SourceConfigModel

        package_json = tmp_path / "package.json"
        package_json.write_text('{"name": "test"}')

        # Use default command from allowlist (should work)
        config = SourceConfigModel(command="npm audit --json")
        mock_output = '{"vulnerabilities": {"pkg": {"severity": "low", "via": [], "fixAvailable": false}}}'

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = mock_output
            mock_run.return_value.returncode = 0

            source = SecuritySource()
            evidence = source.collect(tmp_path, config)

            assert evidence is not None
            # Verify command passed from config was used (now a tuple)
            call_args = mock_run.call_args
            assert call_args[0][0] == ("npm", "audit", "--json")

    def test_command_not_in_allowlist_is_rejected(self, tmp_path: Path) -> None:
        """Test that commands not in allowlist are rejected."""
        from bmad_assist.testarch.config import SourceConfigModel

        package_json = tmp_path / "package.json"
        package_json.write_text('{"name": "test"}')

        # Use command not in allowlist (should be rejected)
        config = SourceConfigModel(command="rm -rf /")

        with patch("subprocess.run") as mock_run:
            source = SecuritySource()
            evidence = source.collect(tmp_path, config)

            # Should return None because command is not in allowlist
            assert evidence is None
            # Command should NOT have been run
            mock_run.assert_not_called()


class TestFileDiscovery:
    """Tests for evidence file discovery."""

    def test_prefers_file_over_command(self, tmp_path: Path) -> None:
        """Test that existing file is used instead of running command."""
        # Create both package.json and audit file
        package_json = tmp_path / "package.json"
        package_json.write_text('{"name": "test"}')

        audit_file = tmp_path / "npm-audit.json"
        audit_file.write_text("""{
  "vulnerabilities": {},
  "metadata": {"vulnerabilities": {"total": 0, "critical": 0, "high": 0, "moderate": 0, "low": 0, "info": 0}}
}""")

        with patch("subprocess.run") as mock_run:
            source = SecuritySource()
            evidence = source.collect(tmp_path)

            # Should not run command since file exists
            mock_run.assert_not_called()
            assert evidence is not None
            assert evidence.total == 0

    def test_custom_patterns(self, tmp_path: Path) -> None:
        """Test using custom patterns from config."""
        custom_file = tmp_path / "my-audit.json"
        custom_file.write_text("""{
  "vulnerabilities": {"pkg": {"severity": "critical", "via": ["issue"], "fixAvailable": false}}
}""")

        config = SourceConfig(patterns=("my-audit.json",))
        source = SecuritySource()
        evidence = source.collect(tmp_path, config)

        assert evidence is not None
        assert evidence.critical == 1


class TestFromFixtures:
    """Tests using fixture files."""

    def test_parse_sample_npm_audit(self, evidence_fixtures_dir: Path) -> None:
        """Test parsing sample-npm-audit.json fixture."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shutil.copy(
                evidence_fixtures_dir / "sample-npm-audit.json",
                tmp_path / "npm-audit.json",
            )

            source = SecuritySource()
            evidence = source.collect(tmp_path)

            assert evidence is not None
            assert evidence.critical == 0
            assert evidence.high == 2
            assert evidence.moderate == 2
            assert evidence.low == 1
            assert evidence.total == 5
            assert evidence.fix_available == 4  # 4 have fixAvailable: true
            # Check vulnerability descriptions are sorted by severity
            assert evidence.vulnerabilities[0].startswith("[HIGH]")

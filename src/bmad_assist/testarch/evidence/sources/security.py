"""Security evidence source.

This module provides the SecuritySource class for collecting security
scan results from npm audit JSON files or by running npm audit command.

Usage:
    from bmad_assist.testarch.evidence.sources.security import SecuritySource

    source = SecuritySource()
    evidence = source.collect(project_root)
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.testarch.evidence.models import SecurityEvidence
from bmad_assist.testarch.evidence.sources.base import EvidenceSource

if TYPE_CHECKING:
    from bmad_assist.testarch.config import SourceConfigModel
    from bmad_assist.testarch.evidence.models import SourceConfig

logger = logging.getLogger(__name__)

# Default patterns for security files
DEFAULT_SECURITY_PATTERNS = (
    "**/npm-audit.json",
    "**/security-audit.json",
)

# Command execution allowlist - exact command tuples only
ALLOWED_COMMANDS: frozenset[tuple[str, ...]] = frozenset({
    ("npm", "audit", "--json"),
})

# Default timeout for command execution
DEFAULT_COMMAND_TIMEOUT = 30


class SecuritySource(EvidenceSource):
    """Evidence source for security scan results.

    Supports:
    - npm audit JSON format (from file)
    - Running npm audit --json command

    """

    @property
    def source_type(self) -> str:
        """Return the type of evidence this source collects."""
        return "security"

    @property
    def default_patterns(self) -> tuple[str, ...]:
        """Return default glob patterns for file discovery."""
        return DEFAULT_SECURITY_PATTERNS

    def collect(
        self,
        project_root: Path,
        config: SourceConfigModel | SourceConfig | None = None,
    ) -> SecurityEvidence | None:
        """Collect security evidence from the project.

        Args:
            project_root: Root directory of the project.
            config: Optional source configuration. Accepts either:
                - SourceConfigModel (Pydantic model from YAML config)
                - SourceConfig (frozen dataclass for internal use)
                - None (use default patterns)

        Returns:
            SecurityEvidence if found, None otherwise.

        """
        patterns = self._get_patterns(config)
        timeout = self._get_timeout(config, DEFAULT_COMMAND_TIMEOUT)

        # Extract command from config for use in _run_npm_audit
        command_str = config.command if config else None

        # First try to find existing audit files
        best_file: Path | None = None
        best_mtime: float = 0.0

        for pattern in patterns:
            for match in project_root.glob(pattern):
                if match.is_file():
                    try:
                        mtime = match.stat().st_mtime
                        if mtime > best_mtime:
                            best_mtime = mtime
                            best_file = match
                    except OSError:
                        continue

        if best_file is not None:
            logger.debug("Parsing security file: %s", best_file)
            return self._parse_npm_audit(best_file)

        # If no file found and package.json exists, try running npm audit
        if (project_root / "package.json").exists():
            logger.debug("Running npm audit command in %s", project_root)
            return self._run_npm_audit(project_root, timeout, command_str)

        logger.debug("No security evidence sources found in %s", project_root)
        return None

    def _parse_npm_audit(self, file_path: Path) -> SecurityEvidence | None:
        """Parse npm audit JSON format.

        Format:
        {
          "metadata": {
            "vulnerabilities": {
              "critical": 1, "high": 3, "moderate": 5, "low": 2, "total": 11
            }
          },
          "vulnerabilities": { ... }
        }

        """
        try:
            content = file_path.read_text(encoding="utf-8")
            data = json.loads(content)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to parse npm audit JSON %s: %s", file_path, e)
            return None

        return self._parse_npm_audit_data(data, str(file_path))

    def _parse_npm_audit_data(
        self,
        data: dict[str, Any],
        source: str,
    ) -> SecurityEvidence | None:
        """Parse npm audit data structure."""
        # Handle both old and new npm audit formats
        # New format has detailed vulnerabilities at root level with fixAvailable
        # Old format only has metadata.vulnerabilities summary (and advisories)

        # Check if we have detailed vulnerability info (new format)
        # The new format has vulnerabilities dict with severity and fixAvailable fields
        vulns = data.get("vulnerabilities", {})
        has_detailed_vulns = vulns and isinstance(vulns, dict) and any(
            isinstance(v, dict) and "severity" in v for v in vulns.values()
        )

        if has_detailed_vulns:
            critical = 0
            high = 0
            moderate = 0
            low = 0
            info = 0
            fix_available = 0
            vulnerability_descs: list[str] = []

            for name, vuln_data in vulns.items():
                severity = vuln_data.get("severity", "low")
                if severity == "critical":
                    critical += 1
                elif severity == "high":
                    high += 1
                elif severity == "moderate":
                    moderate += 1
                elif severity == "low":
                    low += 1
                else:
                    info += 1

                if vuln_data.get("fixAvailable"):
                    fix_available += 1

                # Build vulnerability description
                range_str = vuln_data.get("range", "")
                via = vuln_data.get("via", [])
                if isinstance(via, list) and via:
                    first_via = via[0]
                    if isinstance(first_via, dict):
                        title = first_via.get("title", name)
                    else:
                        title = str(first_via)
                else:
                    title = name
                vulnerability_descs.append(f"[{severity.upper()}] {name} {range_str}: {title}")

            total = critical + high + moderate + low + info

            # Sort by severity (critical first)
            severity_order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3, "INFO": 4}
            vulnerability_descs.sort(
                key=lambda x: severity_order.get(x.split("]")[0][1:], 5)
            )

            return SecurityEvidence(
                critical=critical,
                high=high,
                moderate=moderate,
                low=low,
                info=info,
                total=total,
                fix_available=fix_available,
                vulnerabilities=tuple(vulnerability_descs),
                source=source,
            )

        # Old format with metadata.vulnerabilities
        metadata = data.get("metadata", {})
        vuln_summary = metadata.get("vulnerabilities", {})
        critical = vuln_summary.get("critical", 0)
        high = vuln_summary.get("high", 0)
        moderate = vuln_summary.get("moderate", 0)
        low = vuln_summary.get("low", 0)
        info = vuln_summary.get("info", 0)
        total = vuln_summary.get("total", 0)

        # Count fix_available from advisories
        advisories = data.get("advisories", {})
        fix_available = sum(
            1 for adv in advisories.values()
            if adv.get("patched_versions", "") != "<0.0.0"
        )

        # Build vulnerability descriptions for old format
        old_vulnerability_descs: list[str] = []
        for adv in advisories.values():
            severity = adv.get("severity", "low")
            title = adv.get("title", "Unknown")
            module_name = adv.get("module_name", "unknown")
            old_vulnerability_descs.append(f"[{severity.upper()}] {module_name}: {title}")

        # Sort by severity
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3, "INFO": 4}
        old_vulnerability_descs.sort(
            key=lambda x: severity_order.get(x.split("]")[0][1:], 5)
        )

        return SecurityEvidence(
            critical=critical,
            high=high,
            moderate=moderate,
            low=low,
            info=info,
            total=total,
            fix_available=fix_available,
            vulnerabilities=tuple(old_vulnerability_descs),
            source=source,
        )

    def _run_npm_audit(
        self,
        project_root: Path,
        timeout: int,
        command_str: str | None = None,
    ) -> SecurityEvidence | None:
        """Run npm audit command and parse output.

        Security: Only runs commands from the allowlist.

        Args:
            project_root: Root directory to run command in.
            timeout: Command timeout in seconds.
            command_str: Optional command string from config. If provided,
                will be parsed and validated against ALLOWED_COMMANDS.

        """
        # Use configured command or default
        if command_str:
            # Parse command string into tuple for allowlist check
            command = tuple(command_str.split())
        else:
            command = ("npm", "audit", "--json")

        # Verify command is in allowlist
        if command not in ALLOWED_COMMANDS:
            logger.warning("Command not in allowlist: %s", command)
            return None

        try:
            result = subprocess.run(
                command,
                shell=False,  # Security: prevent shell injection
                cwd=project_root,
                timeout=timeout,
                capture_output=True,
                text=True,
                check=False,  # npm audit returns non-zero on vulnerabilities
            )

            # npm audit returns exit code 1 if vulnerabilities found
            # but still outputs valid JSON
            if result.stdout:
                try:
                    data = json.loads(result.stdout)
                    return self._parse_npm_audit_data(data, "npm audit --json")
                except json.JSONDecodeError as e:
                    logger.warning("Failed to parse npm audit output: %s", e)
                    return None

            return None

        except subprocess.TimeoutExpired:
            logger.warning("npm audit command timed out after %ds", timeout)
            return None
        except FileNotFoundError:
            logger.warning("npm command not found")
            return None
        except OSError as e:
            logger.warning("Failed to run npm audit: %s", e)
            return None

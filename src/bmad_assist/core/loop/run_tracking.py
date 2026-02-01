"""Run tracking for CLI observability.

This module provides:
- RunStatus, PhaseStatus enums for tracking run/phase state
- PhaseInvocation model for individual phase execution records
- RunLog model for complete run session tracking
- mask_cli_args function for sensitive argument masking
- save_run_log function for atomic YAML persistence
- CSV export utilities
"""

import csv
import logging
import os
import re
import time
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)


class RunStatus(str, Enum):
    """Status of an entire run session."""

    RUNNING = "running"
    COMPLETED = "completed"
    CRASHED = "crashed"


class PhaseStatus(str, Enum):
    """Status of a single phase execution."""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class PhaseInvocation(BaseModel):
    """Single phase execution record."""

    phase: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    provider: str
    model: str
    status: PhaseStatus
    error_type: str | None = None


class RunLog(BaseModel):
    """Complete run session log."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    status: RunStatus = RunStatus.RUNNING
    cli_args: list[str] = Field(default_factory=list)
    cli_args_masked: list[str] = Field(default_factory=list)
    epic: EpicId | None = None
    story: int | str | None = None
    project_path: str | None = None
    phases: list[PhaseInvocation] = Field(default_factory=list)


# F3: Sensitive flag patterns (for two-pass masking)
SENSITIVE_FLAGS = re.compile(
    r"^--?(?:key|token|secret|password|credential|auth)$",
    re.IGNORECASE,
)

# F16: Max arg length to prevent regex DoS
MAX_ARG_LENGTH = 10000


def mask_cli_args(args: list[str]) -> list[str]:
    """Mask sensitive CLI arguments.

    Uses two-pass masking to handle both:
    - Inline: --token=secret
    - Space-separated: --token secret

    Args:
        args: List of CLI arguments.

    Returns:
        List with sensitive values replaced by '***'.

    """
    masked: list[str] = []
    mask_next = False

    for arg in args:
        # F16: Skip overly long args (DoS prevention)
        if len(arg) > MAX_ARG_LENGTH:
            masked.append(arg[:50] + "...[TRUNCATED]")
            mask_next = False
            continue

        if mask_next:
            masked.append("***")
            mask_next = False
        elif SENSITIVE_FLAGS.match(arg):
            # Flag without value - mask next arg
            masked.append(arg)
            mask_next = True
        elif "=" in arg:
            # Check for --token=value pattern
            flag_part = arg.split("=")[0]
            if SENSITIVE_FLAGS.match(flag_part):
                masked.append(f"{flag_part}=***")
            else:
                masked.append(arg)
        else:
            masked.append(arg)

    return masked


class SecurityError(Exception):
    """Security violation detected."""

    pass


def _cleanup_old_tmp_files(directory: Path, max_age_hours: int = 1) -> None:
    """Remove orphaned .tmp files older than max_age_hours.

    Args:
        directory: Directory to clean.
        max_age_hours: Maximum age in hours before removal.

    """
    cutoff = time.time() - (max_age_hours * 3600)
    for tmp_file in directory.glob("*.tmp"):
        try:
            if tmp_file.stat().st_mtime < cutoff:
                tmp_file.unlink()
        except OSError:
            pass  # Ignore cleanup errors


def _format_datetime(dt: datetime | None) -> str:
    """Safely serialize datetime to ISO string.

    Args:
        dt: Datetime to format, or None.

    Returns:
        ISO format string, or empty string if None.

    """
    if dt is None:
        return ""
    return dt.isoformat()


def _sanitize_csv_value(value: str | None) -> str:
    """Prevent CSV injection by escaping formula characters.

    Excel/Sheets interpret cells starting with =, +, -, @, | as formulas.
    Prefix with single quote to force text interpretation.

    Args:
        value: Value to sanitize.

    Returns:
        Sanitized value safe for CSV.

    """
    if value is None:
        return ""
    s = str(value)
    # F6 FIX: Added pipe | to dangerous characters (Excel DDE injection)
    if s and s[0] in ("=", "+", "-", "@", "|", "\t", "\r", "\n"):
        return f"'{s}"  # Prefix with single quote
    return s


def _write_csv(run_log: RunLog, path: Path) -> None:
    """Write run log as CSV with run-level metadata and phase rows.

    Args:
        run_log: Run log to export.
        path: Path to write CSV file.

    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        # F19 FIX: Write run-level metadata as header comment
        f.write(f"# Run ID: {run_log.run_id}\n")
        f.write(f"# Started: {_format_datetime(run_log.started_at)}\n")
        f.write(f"# Project: {_sanitize_csv_value(run_log.project_path)}\n")
        f.write(f"# CLI Args (masked): {' '.join(run_log.cli_args_masked)}\n")
        f.write(f"# Status: {run_log.status.value}\n")

        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)

        # Column headers
        writer.writerow(
            [
                "run_id",
                "run_started_at",
                "run_status",
                "epic",
                "story",
                "phase",
                "phase_started",
                "phase_ended",
                "duration_ms",
                "provider",
                "model",
                "phase_status",
                "error_type",
            ]
        )

        # Phase rows
        for phase in run_log.phases:
            writer.writerow(
                [
                    run_log.run_id,
                    _format_datetime(run_log.started_at),
                    run_log.status.value,
                    _sanitize_csv_value(str(run_log.epic)),
                    _sanitize_csv_value(str(run_log.story)),
                    phase.phase,
                    _format_datetime(phase.started_at),
                    _format_datetime(phase.ended_at),
                    phase.duration_ms or 0,
                    phase.provider,
                    phase.model,
                    phase.status.value,
                    phase.error_type or "",
                ]
            )


def save_run_log(run_log: RunLog, project_path: Path, as_csv: bool = False) -> Path:
    """Save run log to .bmad-assist/runs/ with atomic write.

    Args:
        run_log: Run log to save.
        project_path: Project root path.
        as_csv: If True, also write CSV file.

    Returns:
        Path to the saved YAML file.

    Raises:
        SecurityError: If symlink attack detected.

    """
    runs_dir = project_path / ".bmad-assist" / "runs"

    # F3 FIX: Prevent symlink TOCTOU - check before AND after mkdir
    if runs_dir.exists() and runs_dir.is_symlink():
        raise SecurityError(f"Symlink detected at {runs_dir} - refusing to write")

    runs_dir.mkdir(parents=True, exist_ok=True)

    # F3 FIX: Re-check after mkdir (prevents race condition)
    if runs_dir.is_symlink():
        raise SecurityError(f"Symlink race detected at {runs_dir} - refusing to write")

    # F18 FIX: Clean up orphaned .tmp files older than 1 hour
    _cleanup_old_tmp_files(runs_dir, max_age_hours=1)

    filename = f"run-{run_log.started_at.strftime('%Y%m%dT%H%M%SZ')}-{run_log.run_id}"

    # Always write YAML with atomic write
    yaml_path = runs_dir / f"{filename}.yaml"
    temp_path = yaml_path.with_suffix(".yaml.tmp")

    # Serialize datetime objects properly
    data = run_log.model_dump(mode="json")

    with open(temp_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    os.rename(temp_path, yaml_path)

    # F4 FIX: Write CSV with atomic write (temp file + rename)
    if as_csv:
        csv_path = runs_dir / f"{filename}.csv"
        csv_temp_path = csv_path.with_suffix(".csv.tmp")
        _write_csv(run_log, csv_temp_path)
        os.rename(csv_temp_path, csv_path)
        logger.debug("Saved run log CSV: %s", csv_path)

    logger.debug("Saved run log: %s", yaml_path)
    return yaml_path

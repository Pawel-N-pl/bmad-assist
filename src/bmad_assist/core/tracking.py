"""Agent tracking for provider invocations.

Writes START/END records to .bmad-assist/agent-tracking.csv when
BMAD_TRACK_AGENTS environment variable is set.

cli_params column is only populated when BMAD_TRACK_AGENTS_PARAMS is also set.
"""

from __future__ import annotations

import fcntl
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HEADER = (
    '"date","epic","story","phase","provider","model",'
    '"cli_params","context_tokens","event","elapsed"\n'
)


def _is_enabled() -> bool:
    return bool(os.environ.get("BMAD_TRACK_AGENTS"))


def _params_enabled() -> bool:
    return bool(os.environ.get("BMAD_TRACK_AGENTS_PARAMS"))


def _csv_path(project_path: Path) -> Path:
    return project_path / ".bmad-assist" / "agent-tracking.csv"


def reset_tracking_file(project_path: Path) -> None:
    """Delete the tracking CSV so a fresh run starts clean."""
    csv = _csv_path(project_path)
    if csv.exists():
        csv.unlink()


def _format_cli_params(params: dict[str, Any] | None) -> str:
    """Format invoke kwargs (excluding prompt) as a compact string."""
    if not params:
        return ""
    parts: list[str] = []
    for key, val in sorted(params.items()):
        if val is None or val is False:
            continue
        if isinstance(val, list):
            parts.append(f"--{key} {','.join(str(v) for v in val)}")
        elif isinstance(val, bool):
            parts.append(f"--{key}")
        elif isinstance(val, Path):
            parts.append(f"--{key} {val}")
        else:
            parts.append(f"--{key} {val}")
    return " ".join(parts)


def _escape_csv(value: str) -> str:
    """Escape double quotes inside a CSV field."""
    return value.replace('"', '""')


def _write_row(
    project_path: Path,
    epic: str | int,
    story: str | int,
    phase: str,
    provider: str,
    model: str,
    cli_params: str,
    prompt: str,
    event: str,
    elapsed: str,
    ts: datetime,
) -> None:
    csv = _csv_path(project_path)
    csv.parent.mkdir(parents=True, exist_ok=True)
    context_tokens = len(prompt) // 4
    iso = ts.isoformat()
    safe_params = _escape_csv(cli_params)
    line = (
        f'"{iso}","{epic}","{story}","{phase}",'
        f'"{provider}","{model}","{safe_params}",'
        f'"{context_tokens}","{event}","{elapsed}"\n'
    )
    with open(csv, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            if f.tell() == 0:
                f.write(_HEADER)
            f.write(line)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def track_agent_start(
    project_path: Path,
    epic: str | int,
    story: str | int,
    phase: str,
    provider: str,
    model: str,
    prompt: str,
    cli_params: dict[str, Any] | None = None,
) -> datetime | None:
    """Write a START record. Returns start timestamp, or None if disabled."""
    if not _is_enabled():
        return None
    ts = datetime.now(UTC)
    params_str = _format_cli_params(cli_params) if _params_enabled() else ""
    _write_row(
        project_path, epic, story, phase, provider, model,
        params_str, prompt, "START", "", ts,
    )
    return ts


def track_agent_end(
    project_path: Path,
    epic: str | int,
    story: str | int,
    phase: str,
    provider: str,
    model: str,
    prompt: str,
    start_time: datetime | None,
    cli_params: dict[str, Any] | None = None,
) -> None:
    """Write an END record. No-op if disabled or start_time is None."""
    if not _is_enabled() or start_time is None:
        return
    ts = datetime.now(UTC)
    elapsed = str(int((ts - start_time).total_seconds()))
    params_str = _format_cli_params(cli_params) if _params_enabled() else ""
    _write_row(
        project_path, epic, story, phase, provider, model,
        params_str, prompt, "END", elapsed, ts,
    )

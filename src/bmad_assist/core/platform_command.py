"""Cross-platform command execution utilities.

This module provides utilities for executing subprocess commands in a
cross-platform manner, handling differences between Windows and POSIX systems.

Key differences between platforms:
- POSIX (Linux/macOS): Has ARG_MAX limit (~128KB-2MB) for execve()
- Windows: CreateProcess has 32KB command line limit, but subprocess handles
  arguments differently, often avoiding the need for shell workarounds

The strategy:
1. On Windows: Try direct argument passing first, fall back to temp file if needed
2. On POSIX: Use shell with temp file for large prompts to avoid ARG_MAX
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import tempfile
from typing import Literal

logger = logging.getLogger(__name__)

# Platform detection
IS_WINDOWS = sys.platform == "win32"
IS_POSIX = not IS_WINDOWS

# Threshold for using temp file approach (in characters)
# On Linux, ARG_MAX is typically 128KB-2MB. We use 100KB as safe threshold.
TEMP_FILE_THRESHOLD = 100_000


def build_cross_platform_command(
    executable: str,
    args: list[str],
    prompt: str,
    *,
    use_shell: bool = False,
) -> tuple[list[str], str | None]:
    """Build a cross-platform command that handles large prompts.

    On POSIX systems with large prompts, writes the prompt to a temp file
    and uses shell command substitution to avoid ARG_MAX limits.

    On Windows, uses direct argument passing (Windows doesn't have the
    same ARG_MAX limitations in the same way).

    Args:
        executable: The command to run (e.g., "codex", "copilot").
        args: Additional arguments to pass to the command (excluding prompt).
        prompt: The prompt text to pass to the command.
        use_shell: If True, force use of shell wrapper even for short prompts.

    Returns:
        A tuple of (command_list, temp_file_path):
        - command_list: List suitable for subprocess.Popen()
        - temp_file_path: Path to temp file if created, None otherwise.
            Caller is responsible for cleanup.

    Examples:
        >>> cmd, temp_file = build_cross_platform_command(
        ...     "codex",
        ...     ["--json", "--full-auto", "-m", "o3-mini"],
        ...     "Hello"
        ... )
        >>> cmd
        ['codex', '--json', '--full-auto', '-m', 'o3-mini', 'Hello']
        >>> temp_file
        None

    """
    # On POSIX with large prompts or use_shell=True, use temp file approach
    if IS_POSIX and (use_shell or len(prompt) > TEMP_FILE_THRESHOLD):
        return _build_shell_command(executable, args, prompt)
    else:
        # Direct argument passing (works well on Windows and for short prompts on POSIX)
        return _build_direct_command(executable, args, prompt), None


def _build_direct_command(
    executable: str,
    args: list[str],
    prompt: str,
) -> list[str]:
    """Build command with direct argument passing.

    Args:
        executable: The command to run.
        args: Additional arguments (excluding prompt).
        prompt: The prompt text.

    Returns:
        Command list for subprocess.Popen().

    """
    return [executable] + args + [prompt]


def _build_shell_command(
    executable: str,
    args: list[str],
    prompt: str,
) -> tuple[list[str], str]:
    """Build command using shell with temp file for large prompts.

    Writes prompt to a temp file and uses shell command substitution.

    Args:
        executable: The command to run.
        args: Additional arguments (excluding prompt).
        prompt: The prompt text.

    Returns:
        Tuple of (command_list, temp_file_path) where temp_file_path
        must be cleaned up by the caller.

    """
    # Create temp file for prompt
    prompt_fd, prompt_file_path = tempfile.mkstemp(
        suffix=".txt", prefix=f"{executable}_prompt_"
    )
    try:
        os.write(prompt_fd, prompt.encode("utf-8"))
    finally:
        os.close(prompt_fd)

    # Build shell command with command substitution
    # Note: We escape the temp file path for safety
    shell_cmd = f'{executable} "$(cat {prompt_file_path})" ' + " ".join(
        _shell_quote(arg) for arg in args
    )

    return ["/bin/sh", "-c", shell_cmd], prompt_file_path


def _shell_quote(arg: str) -> str:
    """Quote an argument for safe use in a shell command.

    Uses single quotes which protect against all special characters
    except single quotes themselves.

    Args:
        arg: The argument to quote.

    Returns:
        Safely quoted argument for shell use.

    """
    # If the argument contains only safe characters, no quoting needed
    if arg.isalnum() or arg in ("_", "-", ".", "/"):
        return arg

    # Use single quotes, escaping any embedded single quotes
    # ' becomes '\''
    return "'" + arg.replace("'", "'\\''") + "'"


def cleanup_temp_file(temp_file_path: str | None) -> None:
    """Clean up a temporary file created by build_cross_platform_command.

    Args:
        temp_file_path: Path to temp file, or None if no file was created.

    """
    if temp_file_path is None:
        return
    with contextlib.suppress(OSError):
        os.unlink(temp_file_path)


PlatformType = Literal["windows", "posix", "unknown"]


def get_platform() -> PlatformType:
    """Get the current platform type.

    Returns:
        'windows' for Windows, 'posix' for Linux/macOS, 'unknown' otherwise.

    """
    if IS_WINDOWS:
        return "windows"
    elif IS_POSIX:
        return "posix"
    return "unknown"


def get_shell_command() -> list[str] | None:
    """Get the appropriate shell command for the current platform.

    Returns:
        List of shell command and args (e.g., ['/bin/sh', '-c']) or None.

    Examples:
        >>> get_shell_command()
        ['/bin/sh', '-c']  # on POSIX
        None  # on Windows

    """
    if IS_POSIX:
        return ["/bin/sh", "-c"]
    return None

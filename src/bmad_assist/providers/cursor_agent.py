"""Cursor Agent CLI subprocess-based provider implementation.

This module implements the CursorAgentProvider class that adapts Cursor Agent CLI
for use within bmad-assist via subprocess invocation. Cursor Agent serves as
a Multi LLM validator for story validation and code review phases.

File Access:
    When cwd is provided, Popen runs Cursor Agent from that directory, which
    becomes its workspace. This allows file access to the target project
    directory for code review and validation tasks.

Output Format:
    Uses --print flag for plain text output (no JSON streaming).
    Response is captured directly from stdout.

Command Format:
    cursor-agent --print --model "<MODEL>" --force "<PROMPT>"

Large Prompt Handling:
    Uses platform_command module for prompts >=100KB to avoid ARG_MAX limits
    on POSIX systems. Large prompts are written to a temp file and read via
    shell command substitution.

Example:
    >>> from bmad_assist.providers import CursorAgentProvider
    >>> provider = CursorAgentProvider()
    >>> result = provider.invoke("Review this code", model="claude-sonnet-4")
    >>> response = provider.parse_output(result)

"""

import logging
import os
import threading
import time
from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.core.platform_command import (
    build_cross_platform_command,
    cleanup_temp_file,
)
from bmad_assist.providers.base import (
    MAX_RETRIES,
    BaseProvider,
    ExitStatus,
    ProviderResult,
    calculate_retry_delay,
    format_tag,
    get_popen_kwargs_for_new_session,
    is_full_stream,
    is_transient_error,
    should_print_progress,
    start_stream_reader_threads,
    validate_settings_file,
    write_progress,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT: int = 300
PROMPT_TRUNCATE_LENGTH: int = 100
STDERR_TRUNCATE_LENGTH: int = 200


def _truncate_prompt(prompt: str) -> str:
    """Truncate prompt for error messages."""
    if len(prompt) <= PROMPT_TRUNCATE_LENGTH:
        return prompt
    return prompt[:PROMPT_TRUNCATE_LENGTH] + "..."


class CursorAgentProvider(BaseProvider):
    """Cursor Agent CLI subprocess-based provider implementation.

    Adapts Cursor Agent CLI for use within bmad-assist via subprocess invocation.
    Cursor Agent serves as a Multi LLM validator for parallel validation phases.

    Thread Safety:
        CursorAgentProvider is stateless and thread-safe. Multiple instances can
        invoke() concurrently without interference.

    Example:
        >>> provider = CursorAgentProvider()
        >>> result = provider.invoke("Review this code", timeout=60)
        >>> print(provider.parse_output(result))

    """

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider."""
        return "cursor-agent"

    @property
    def default_model(self) -> str | None:
        """Return default model when none specified."""
        return "claude-sonnet-4"

    def supports_model(self, model: str) -> bool:
        """Check if this provider supports the given model.

        Args:
            model: Model identifier to check.

        Returns:
            Always True - let Cursor Agent CLI validate model names.

        """
        return True

    def _resolve_settings(
        self,
        settings_file: Path | None,
        model: str,
    ) -> Path | None:
        """Resolve and validate settings file for invocation."""
        if settings_file is None:
            return None

        return validate_settings_file(
            settings_file=settings_file,
            provider_name=self.provider_name,
            model=model,
        )

    def invoke(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout: int | None = None,
        settings_file: Path | None = None,
        cwd: Path | None = None,
        disable_tools: bool = False,
        allowed_tools: list[str] | None = None,
        no_cache: bool = False,
        color_index: int | None = None,
        display_model: str | None = None,
        thinking: bool | None = None,
        cancel_token: threading.Event | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderResult:
        """Execute Cursor Agent CLI with the given prompt.

        Command Format:
            cursor-agent --print --model "<MODEL>" --force "<PROMPT>"

        For large prompts (>=100KB), uses temp file to avoid ARG_MAX limits.

        Args:
            prompt: The prompt text to send to Cursor Agent.
            model: Model to use. If None, uses default_model.
            timeout: Timeout in seconds. Must be positive (>= 1) if specified.
            settings_file: Path to settings file (validated but not used by CLI).
            cwd: Working directory for Cursor Agent CLI.
            disable_tools: Ignored - Cursor Agent CLI doesn't support this flag.
            allowed_tools: Ignored - Cursor Agent CLI doesn't support this flag.
            no_cache: Ignored - Cursor Agent CLI doesn't support this flag.
            color_index: Color index for terminal output differentiation.
            display_model: Display name for the model (used in logs/benchmarks).

        Returns:
            ProviderResult containing extracted text, stderr, exit code, and timing.

        Raises:
            ValueError: If timeout is not positive (<=0).
            ProviderError: If CLI execution fails.
            ProviderExitCodeError: If CLI returns non-zero exit code.
            ProviderTimeoutError: If CLI execution exceeds timeout.

        """
        _ = disable_tools, allowed_tools, no_cache

        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        effective_model = model or self.default_model or "claude-sonnet-4"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        validated_settings = self._resolve_settings(settings_file, effective_model)
        if validated_settings is not None:
            logger.debug(
                "Settings file validated but not passed to Cursor Agent CLI: %s",
                validated_settings,
            )

        logger.debug(
            "Invoking Cursor Agent CLI: model=%s, timeout=%ds, prompt_len=%d, cwd=%s",
            effective_model,
            effective_timeout,
            len(prompt),
            cwd,
        )

        # Build command with platform-aware large prompt handling
        # Args before prompt: --print, --model, <model>, --force
        base_args = ["--print", "--model", effective_model, "--force"]
        command, temp_file = build_cross_platform_command("cursor-agent", base_args, prompt)

        # For ProviderResult, we need original command structure (without shell wrapper)
        original_command: tuple[str, ...] = (
            "cursor-agent",
            "--print",
            "--model",
            effective_model,
            "--force",
            prompt,
        )

        last_error: ProviderExitCodeError | None = None
        returncode: int = 0
        duration_ms: int = 0
        stderr_content: str = ""
        stdout_content: str = ""

        try:
            for attempt in range(MAX_RETRIES):
                if attempt > 0:
                    delay = calculate_retry_delay(attempt - 1)
                    logger.warning(
                        "Cursor Agent CLI retry %d/%d after %.1fs delay (previous: %s)",
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                        last_error,
                    )
                    time.sleep(delay)

                stdout_chunks: list[str] = []
                stderr_chunks: list[str] = []
                start_time = time.perf_counter()

                # Create callbacks for stream readers (check log level dynamically)
                def _stdout_cb(line: str) -> None:
                    if should_print_progress():
                        stripped = line.rstrip()
                        tag = format_tag("OUT", color_index)
                        if is_full_stream():
                            write_progress(f"{tag} {stripped}")
                        else:
                            preview = stripped[:200]
                            if len(stripped) > 200:
                                preview += "..."
                            write_progress(f"{tag} {preview}")

                def _stderr_cb(line: str) -> None:
                    if should_print_progress():
                        stripped = line.rstrip()
                        tag = format_tag("ERR", color_index)
                        write_progress(f"{tag} {stripped}")

                try:
                    env = os.environ.copy()
                    if cwd is not None:
                        env["PWD"] = str(cwd)

                    # Get platform-specific kwargs for process isolation
                    popen_kwargs = get_popen_kwargs_for_new_session()

                    process = Popen(
                        command,
                        stdin=PIPE,
                        stdout=PIPE,
                        stderr=PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        cwd=cwd,
                        env=env,
                        **popen_kwargs,
                    )

                    if process.stdin:
                        process.stdin.close()

                    # Use shared helper for stream reader threads
                    stdout_thread, stderr_thread = start_stream_reader_threads(
                        process,
                        stdout_chunks,
                        stderr_chunks,
                        stdout_callback=_stdout_cb,
                        stderr_callback=_stderr_cb,
                    )

                    if should_print_progress():
                        shown_model = display_model or effective_model
                        tag = format_tag("START", color_index)
                        write_progress(f"{tag} Invoking Cursor Agent CLI (model={shown_model})...")

                    try:
                        returncode = process.wait(timeout=effective_timeout)
                    except TimeoutExpired:
                        process.kill()
                        stdout_thread.join(timeout=2)
                        stderr_thread.join(timeout=2)
                        duration_ms = int((time.perf_counter() - start_time) * 1000)
                        truncated = _truncate_prompt(prompt)

                        partial_result = ProviderResult(
                            stdout="".join(stdout_chunks),
                            stderr="".join(stderr_chunks),
                            exit_code=-1,
                            duration_ms=duration_ms,
                            model=effective_model,
                            command=original_command,
                        )

                        raise ProviderTimeoutError(
                            f"Cursor Agent CLI timeout after {effective_timeout}s: {truncated}",
                            partial_result=partial_result,
                        ) from None

                    stdout_thread.join(timeout=10)
                    stderr_thread.join(timeout=10)

                except FileNotFoundError as e:
                    logger.error("Cursor Agent CLI not found in PATH")
                    raise ProviderError(
                        "Cursor Agent CLI not found. Is 'cursor-agent' in PATH?"
                    ) from e

                duration_ms = int((time.perf_counter() - start_time) * 1000)
                stdout_content = "".join(stdout_chunks)
                stderr_content = "".join(stderr_chunks)

                if returncode != 0:
                    exit_status = ExitStatus.from_code(returncode)
                    stderr_truncated = (
                        stderr_content[:STDERR_TRUNCATE_LENGTH] if stderr_content else "(empty)"
                    )

                    logger.error(
                        "Cursor Agent CLI failed: exit_code=%d, status=%s, model=%s, stderr=%s",
                        returncode,
                        exit_status.name,
                        effective_model,
                        stderr_truncated,
                    )

                    message = (
                        f"Cursor Agent CLI failed with exit code {returncode}: {stderr_truncated}"
                    )
                    error = ProviderExitCodeError(
                        message,
                        exit_code=returncode,
                        exit_status=exit_status,
                        stderr=stderr_content,
                        command=original_command,
                    )

                    # Use shared helper for transient error detection
                    if (
                        is_transient_error(stderr_content, exit_status)
                        and attempt < MAX_RETRIES - 1
                    ):  # noqa: E501
                        last_error = error
                        continue

                    raise error

                break
        finally:
            # Always cleanup temp file if created
            cleanup_temp_file(temp_file)

        logger.info(
            "Cursor Agent CLI completed: duration=%dms, exit_code=%d, text_len=%d",
            duration_ms,
            returncode,
            len(stdout_content),
        )

        return ProviderResult(
            stdout=stdout_content,
            stderr=stderr_content,
            exit_code=returncode,
            duration_ms=duration_ms,
            model=effective_model,
            command=original_command,
        )

    def parse_output(self, result: ProviderResult) -> str:
        """Extract response text from Cursor Agent CLI output.

        Cursor Agent CLI with --print outputs plain text to stdout.
        No JSON parsing needed.

        Args:
            result: ProviderResult from invoke() containing raw output.

        Returns:
            Extracted response text with whitespace stripped.

        """
        return result.stdout.strip()

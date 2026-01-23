"""Codex CLI subprocess-based provider implementation.

This module implements the CodexProvider class that adapts Codex CLI
for use within bmad-assist via subprocess invocation. Codex serves as
a Multi LLM validator for story validation and code review phases.

⚠️ SECURITY WARNING: When CodexProvider is used as a Multi-LLM validator,
the orchestrator MUST ensure read-only behavior. The --full-auto flag
grants file modification permissions, but Multi-LLM validators MUST NOT
modify project files per docs/architecture.md.

JSON Streaming:
    Uses --json flag to capture JSONL event stream for debugging.
    Event types: thread.started, turn.started, turn.completed, item.*, error
    Text extracted from item.completed events with item.type="agent_message".

Example:
    >>> from bmad_assist.providers import CodexProvider
    >>> provider = CodexProvider()
    >>> result = provider.invoke("Review this code", model="o3-mini")
    >>> response = provider.parse_output(result)

"""

import json
import logging
import threading
import time
from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired
from typing import Any

from bmad_assist.core.debug_logger import DebugJsonLogger
from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers.base import (
    BaseProvider,
    ExitStatus,
    ProviderResult,
    format_tag,
    validate_settings_file,
    write_progress,
)

logger = logging.getLogger(__name__)

# Note: Model validation removed - Codex CLI accepts any model string.
# The CLI itself will validate and return an error for unknown models.

# Default timeout in seconds (5 minutes)
DEFAULT_TIMEOUT: int = 300

# Maximum prompt length in error messages before truncation
PROMPT_TRUNCATE_LENGTH: int = 100

# Maximum stderr length in error messages before truncation
STDERR_TRUNCATE_LENGTH: int = 500


def _truncate_prompt(prompt: str) -> str:
    """Truncate prompt for error messages.

    Args:
        prompt: The original prompt text.

    Returns:
        Original prompt if <= PROMPT_TRUNCATE_LENGTH chars,
        otherwise first PROMPT_TRUNCATE_LENGTH chars + "..."

    """
    if len(prompt) <= PROMPT_TRUNCATE_LENGTH:
        return prompt
    return prompt[:PROMPT_TRUNCATE_LENGTH] + "..."


class CodexProvider(BaseProvider):
    """Codex CLI subprocess-based provider implementation.

    Adapts Codex CLI for use within bmad-assist via subprocess invocation.
    Codex serves as a Multi LLM validator for parallel validation phases.

    Supported models (from Codex CLI, December 2025):
        ChatGPT subscription compatible:
        - gpt-5.1-codex-max: Optimized for agentic coding (default)
        - gpt-5.1-codex, gpt-5.1-codex-mini: Codex variants
        - gpt-5-codex, gpt-5, gpt-5-mini, gpt-5-nano: GPT-5 family
        - gpt-5.2: Latest general-purpose model

        API key required:
        - o3, o3-mini, o4-mini: Reasoning models
        - gpt-4.1, gpt-4.1-mini, gpt-4.1-nano: GPT-4.1 variants
        - gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-4: Legacy

    Settings File Handling:
        The settings_file parameter is accepted for API consistency with other
        providers but is NOT passed to Codex CLI, which uses environment
        variables (OPENAI_API_KEY, CODEX_API_KEY) and ~/.codex/ config files
        rather than CLI flags. When provided, the file is validated for
        existence (logging a warning if missing) but does not affect CLI
        execution.

    Example:
        >>> provider = CodexProvider()
        >>> result = provider.invoke("Review this code", timeout=60)
        >>> print(provider.parse_output(result))

    """

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider.

        Returns:
            The string "codex" as the provider identifier.

        """
        return "codex"

    @property
    def default_model(self) -> str | None:
        """Return default model when none specified.

        Returns:
            The string "gpt-5.1-codex-max" as the default for ChatGPT users.

        """
        return "gpt-5.1-codex-max"

    def supports_model(self, model: str) -> bool:
        """Check if this provider supports the given model.

        Args:
            model: Model identifier to check.

        Returns:
            Always True - let Codex CLI validate model names.

        Example:
            >>> provider = CodexProvider()
            >>> provider.supports_model("gpt-5.1-codex-max")
            True
            >>> provider.supports_model("gpt-5.2")
            True
            >>> provider.supports_model("any-model")
            True

        """
        # Always return True - let Codex CLI validate model names
        return True

    def _resolve_settings(
        self,
        settings_file: Path | None,
        model: str,
    ) -> Path | None:
        """Resolve and validate settings file for invocation.

        Internal helper that validates settings file existence and logs
        a warning if missing. Called after model validation, before
        command building.

        Args:
            settings_file: Settings file path from caller, or None.
            model: Model identifier for logging context.

        Returns:
            Validated settings file Path if exists and is a file,
            None otherwise (triggers graceful degradation to defaults).

        """
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
    ) -> ProviderResult:
        """Execute Codex CLI with the given prompt using JSON streaming.

        Invokes Codex CLI via Popen with --json flag for JSONL event streaming.
        This enables:
        - Debug logging of raw JSON events to ~/.bmad-assist/debug/json/
        - Real-time output processing
        - Consistent debugging across all providers

        Command Format:
            codex exec "<prompt>" --json --full-auto -m <model>     (normal mode)
            codex exec "<prompt>" --json --sandbox read-only -m <model>  (validator mode)

        JSON Event Types:
            - thread.started: Session initialization with thread_id
            - turn.started/turn.completed: Turn lifecycle with usage stats
            - item.started/item.completed: Individual items (messages, tools)
            - error: Error events

        Text Extraction:
            Response text is extracted from item.completed events where
            item.type === "agent_message" from the item.text field.

        Args:
            prompt: The prompt text to send to Codex.
            model: Model to use (gpt-5.1-codex-max, o3-mini, etc).
                If None, uses default_model.
            timeout: Timeout in seconds. Must be positive (>= 1) if specified.
                If None, uses DEFAULT_TIMEOUT (300s).
            settings_file: Path to settings file (validated but not used by CLI).
            cwd: Working directory (ignored - Codex CLI doesn't support).
            disable_tools: Disable tools (ignored - Codex CLI doesn't support).
            allowed_tools: List of allowed tools. When set, uses --sandbox read-only.
            no_cache: Disable caching (ignored - Codex CLI doesn't support).
            color_index: Color index for terminal output differentiation.

        Returns:
            ProviderResult containing extracted text, stderr, exit code, and timing.

        Raises:
            ValueError: If timeout is not positive (<=0).
            ProviderError: If CLI execution fails.
            ProviderExitCodeError: If CLI returns non-zero exit code.
            ProviderTimeoutError: If CLI execution exceeds timeout.

        """
        # Ignored parameters (Codex CLI doesn't support these flags)
        _ = disable_tools, no_cache

        # cwd IS used - passed to Popen to set working directory
        # This ensures file access is relative to the target project, not bmad-assist

        # Validate timeout parameter
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        # Resolve model with fallback chain: explicit -> default -> literal
        effective_model = model or self.default_model or "gpt-5.1-codex-max"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        # Validate and resolve settings file
        validated_settings = self._resolve_settings(settings_file, effective_model)

        # Codex CLI uses sandbox modes for tool restrictions
        use_sandbox = bool(allowed_tools)
        if use_sandbox:
            logger.debug(
                "Codex CLI: using --sandbox read-only for tool restriction (requested: %s)",
                allowed_tools,
            )

        logger.debug(
            "Invoking Codex CLI: model=%s, timeout=%ds, prompt_len=%d, settings=%s, sandbox=%s",
            effective_model,
            effective_timeout,
            len(prompt),
            validated_settings,
            "read-only" if use_sandbox else "none",
        )

        # Build command with --json for JSONL streaming
        if use_sandbox:
            command: list[str] = [
                "codex",
                "exec",
                prompt,
                "--json",
                "--sandbox",
                "read-only",
                "-m",
                effective_model,
            ]
        else:
            command = [
                "codex",
                "exec",
                prompt,
                "--json",
                "--full-auto",
                "-m",
                effective_model,
            ]

        if validated_settings is not None:
            logger.debug(
                "Settings file validated but not passed to Codex CLI: %s",
                validated_settings,
            )

        # Debug JSON logger for raw event stream
        debug_json_logger = DebugJsonLogger()

        # Accumulators for JSON stream parsing
        response_text_parts: list[str] = []
        stderr_chunks: list[str] = []
        raw_stdout_lines: list[str] = []
        thread_id: str | None = None

        start_time = time.perf_counter()

        try:
            process = Popen(
                command,
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,  # Use target project directory, not bmad-assist cwd
            )

            # Print output only in verbose/debug mode
            print_output = logger.isEnabledFor(logging.DEBUG)

            def process_json_stream(
                stream: Any,
                text_parts: list[str],
                raw_lines: list[str],
                print_progress: bool,
                json_logger: DebugJsonLogger,
                color_idx: int | None,
            ) -> None:
                """Process Codex --json output, extracting text and logging events."""
                nonlocal thread_id
                for line in iter(stream.readline, ""):
                    raw_lines.append(line)
                    stripped = line.strip()
                    if not stripped:
                        continue

                    # Log raw JSON immediately (survives crashes)
                    json_logger.append(stripped)

                    try:
                        msg = json.loads(stripped)
                        msg_type = msg.get("type", "")

                        if msg_type == "thread.started":
                            thread_id = msg.get("thread_id", "?")
                            if print_progress:
                                tag = format_tag("INIT", color_idx)
                                write_progress(f"{tag} Thread: {thread_id}")

                        elif msg_type == "item.completed":
                            item = msg.get("item", {})
                            item_type = item.get("type", "")
                            if item_type == "agent_message":
                                text = item.get("text", "")
                                if text:
                                    text_parts.append(text)
                                    if print_progress:
                                        preview = text[:200]
                                        if len(text) > 200:
                                            preview += "..."
                                        tag = format_tag("MESSAGE", color_idx)
                                        write_progress(f"{tag} {preview}")
                            elif item_type == "command_execution":
                                if print_progress:
                                    cmd = item.get("command", "?")
                                    tag = format_tag("CMD", color_idx)
                                    write_progress(f"{tag} {cmd}")

                        elif msg_type == "turn.completed":
                            if print_progress:
                                usage = msg.get("usage", {})
                                input_tokens = usage.get("input_tokens", 0)
                                output_tokens = usage.get("output_tokens", 0)
                                tag = format_tag("TURN", color_idx)
                                write_progress(f"{tag} in={input_tokens} out={output_tokens}")

                        elif msg_type == "error":
                            if print_progress:
                                error_msg = msg.get("message", str(msg))
                                tag = format_tag("ERROR", color_idx)
                                write_progress(f"{tag} {error_msg}")

                    except json.JSONDecodeError:
                        if print_progress:
                            tag = format_tag("RAW", color_idx)
                            write_progress(f"{tag} {stripped}")

                stream.close()

            def read_stderr(
                stream: Any,
                chunks: list[str],
                print_lines: bool,
                color_idx: int | None,
            ) -> None:
                """Read stderr stream."""
                for line in iter(stream.readline, ""):
                    chunks.append(line)
                    if print_lines:
                        tag = format_tag("ERR", color_idx)
                        write_progress(f"{tag} {line.rstrip()}")
                stream.close()

            # Start reader threads
            stdout_thread = threading.Thread(
                target=process_json_stream,
                args=(
                    process.stdout,
                    response_text_parts,
                    raw_stdout_lines,
                    print_output,
                    debug_json_logger,
                    color_index,
                ),
            )
            stderr_thread = threading.Thread(
                target=read_stderr,
                args=(process.stderr, stderr_chunks, print_output, color_index),
            )
            stdout_thread.start()
            stderr_thread.start()

            # Wait for process with timeout
            try:
                returncode = process.wait(timeout=effective_timeout)
            except TimeoutExpired:
                process.kill()
                stdout_thread.join(timeout=1)
                stderr_thread.join(timeout=1)
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                truncated = _truncate_prompt(prompt)

                partial_result = ProviderResult(
                    stdout="".join(response_text_parts),
                    stderr="".join(stderr_chunks),
                    exit_code=-1,
                    duration_ms=duration_ms,
                    model=effective_model,
                    command=tuple(command),
                )

                logger.warning(
                    "Provider timeout: provider=%s, model=%s, timeout=%ds, "
                    "duration_ms=%d, prompt=%s",
                    self.provider_name,
                    effective_model,
                    effective_timeout,
                    duration_ms,
                    truncated,
                )

                raise ProviderTimeoutError(
                    f"Codex CLI timeout after {effective_timeout}s: {truncated}",
                    partial_result=partial_result,
                ) from None

            # Wait for threads to finish
            stdout_thread.join()
            stderr_thread.join()

        except FileNotFoundError as e:
            logger.error("Codex CLI not found in PATH")
            raise ProviderError("Codex CLI not found. Is 'codex' in PATH?") from e
        finally:
            debug_json_logger.close()

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        stderr_content = "".join(stderr_chunks)

        if returncode != 0:
            exit_status = ExitStatus.from_code(returncode)
            stderr_truncated = (
                stderr_content[:STDERR_TRUNCATE_LENGTH] if stderr_content else "(empty)"
            )

            logger.error(
                "Codex CLI failed: exit_code=%d, status=%s, model=%s, stderr=%s",
                returncode,
                exit_status.name,
                effective_model,
                stderr_truncated,
            )

            if exit_status == ExitStatus.SIGNAL:
                signal_num = ExitStatus.get_signal_number(returncode)
                message = (
                    f"Codex CLI failed with exit code {returncode} "
                    f"(signal {signal_num}): {stderr_truncated}"
                )
            elif exit_status == ExitStatus.NOT_FOUND:
                message = (
                    f"Codex CLI failed with exit code {returncode} "
                    f"(command not found - check PATH): {stderr_truncated}"
                )
            elif exit_status == ExitStatus.CANNOT_EXECUTE:
                message = (
                    f"Codex CLI failed with exit code {returncode} "
                    f"(permission denied): {stderr_truncated}"
                )
            else:
                message = f"Codex CLI failed with exit code {returncode}: {stderr_truncated}"

            raise ProviderExitCodeError(
                message,
                exit_code=returncode,
                exit_status=exit_status,
                stderr=stderr_content,
                command=tuple(command),
            )

        # Combine extracted text parts
        response_text = "\n".join(response_text_parts)

        # Get provider session_id (thread_id for Codex)
        provider_session_id = debug_json_logger.provider_session_id

        logger.info(
            "Codex CLI completed: duration=%dms, exit_code=%d, text_len=%d",
            duration_ms,
            returncode,
            len(response_text),
        )

        return ProviderResult(
            stdout=response_text,
            stderr=stderr_content,
            exit_code=returncode,
            duration_ms=duration_ms,
            model=effective_model,
            command=tuple(command),
            provider_session_id=provider_session_id,
        )

    def parse_output(self, result: ProviderResult) -> str:
        r"""Extract response text from Codex CLI output.

        Codex CLI outputs progress to stderr and final message to stdout.
        No JSON parsing is needed - the response is the raw stdout with
        leading/trailing whitespace stripped.

        Args:
            result: ProviderResult from invoke() containing raw output.

        Returns:
            Extracted response text with whitespace stripped.
            Empty string if stdout is empty.

        Example:
            >>> result = ProviderResult(stdout="  Code review complete  \n", ...)
            >>> provider.parse_output(result)
            'Code review complete'

        """
        return result.stdout.strip()

"""Kimi CLI subprocess-based provider implementation.

This module implements the KimiProvider class that adapts kimi-cli (MoonshotAI)
for use within bmad-assist via subprocess invocation. Kimi serves as both a
Multi-LLM validator and an alternative Master LLM option.

File Access:
    When cwd is provided, Popen runs kimi-cli from that directory, which
    becomes kimi-cli's workspace. This allows file access to the target
    project directory for code review and validation tasks.

JSON Streaming:
    Uses --output-format stream-json flag to capture JSONL event stream.
    Uses OpenAI-style format: {"role": "assistant", "content": "..."}
    Text extracted from assistant messages.

Thinking Mode:
    Auto-detected from model name (if contains "thinking") or explicitly
    enabled via config param. Config override wins when specified.

Example:
    >>> from bmad_assist.providers import KimiProvider
    >>> provider = KimiProvider()
    >>> result = provider.invoke("Review this code", model="kimi-for-coding")
    >>> response = provider.parse_output(result)

"""

import json
import logging
import os
import random
import threading
import time
from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired

from bmad_assist.core.debug_logger import DebugJsonLogger
from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers.base import (
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    BaseProvider,
    ExitStatus,
    ProviderResult,
    extract_tool_details,
    format_tag,
    resolve_settings_file,
    validate_settings_file,
    write_progress,
)

logger = logging.getLogger(__name__)

# Default timeout in seconds (5 minutes)
DEFAULT_TIMEOUT: int = 300

# Maximum prompt length in error messages before truncation
PROMPT_TRUNCATE_LENGTH: int = 100

# Maximum stderr length in error messages before truncation
STDERR_TRUNCATE_LENGTH: int = 200

# Transient error patterns (RETRY on these)
KIMI_TRANSIENT_PATTERNS: tuple[str, ...] = (
    "429",
    "rate limit",
    "too many requests",
    "500",
    "502",
    "503",
    "504",
    "service unavailable",
    "connection timeout",
    "connection refused",
    "context too large",  # Can retry with truncated prompt
)

# Permanent error patterns (NO RETRY)
KIMI_PERMANENT_PATTERNS: tuple[str, ...] = (
    "401",
    "unauthorized",
    "invalid api key",
    "authentication failed",
    "404",
    "model not found",
    "invalid model",
    "bad request",
    "invalid json",
)


# Tool restriction prompt prefix for validators
KIMI_TOOL_RESTRICTION_PREFIX = """IMPORTANT: You are running as a VALIDATOR with restricted permissions.

ALLOWED TOOLS: {allowed_tools}

You MUST NOT use any other tools. If you need to use a restricted tool, explain what you would do instead.

DO NOT:
- Write or modify any files
- Execute shell commands that modify state
- Create, delete, or rename files

If you attempt restricted operations, the review will be invalidated.

---

"""


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


def _extract_text_from_content(content: str | list | None) -> str:
    """Extract text from kimi-cli content field.

    Kimi-cli can return content in two formats:
    1. Simple string: "Hello world"
    2. Array of content blocks: [{"type": "text", "text": "Hello"}, {"type": "think", "think": "..."}]

    Args:
        content: The content field from assistant message.

    Returns:
        Extracted text string. Empty string if no text found.

    """
    if content is None:
        return ""

    # Simple string format
    if isinstance(content, str):
        return content

    # Array of content blocks format
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            # Extract text from "text" type blocks
            if block_type == "text":
                text = block.get("text", "")
                if text:
                    text_parts.append(text)
            # Also extract thinking content if present (for debugging/logging)
            # Note: We skip "think" blocks for main output - only extract "text"
        return "\n".join(text_parts)

    return ""


def _is_kimi_transient_error(stderr: str, exit_code: int) -> bool:
    """Check if error is transient (should retry).

    Args:
        stderr: Standard error output from kimi-cli.
        exit_code: Process exit code.

    Returns:
        True if error appears transient and retry is appropriate.

    """
    if exit_code == 0:
        return False
    if exit_code in (2, 126, 127):  # BadParameter, permission, not found
        return False

    stderr_lower = stderr.lower()

    # Check permanent patterns first (no retry)
    for pattern in KIMI_PERMANENT_PATTERNS:
        if pattern in stderr_lower:
            return False

    # Check transient patterns (retry)
    for pattern in KIMI_TRANSIENT_PATTERNS:
        if pattern in stderr_lower:
            return True

    # Empty stderr with exit 1 = likely transient (network issue)
    if not stderr.strip() and exit_code == 1:
        return True

    return False  # Unknown error = don't retry


def _calculate_retry_delay(attempt: int) -> float:
    """Calculate delay with exponential backoff and jitter.

    Args:
        attempt: Zero-based attempt number.

    Returns:
        Delay in seconds with ±25% jitter applied.

    """
    base_delay = min(RETRY_BASE_DELAY * (2**attempt), RETRY_MAX_DELAY)
    # Add ±25% jitter
    jitter = base_delay * 0.25 * (random.random() * 2 - 1)
    return max(0.1, base_delay + jitter)


class KimiProvider(BaseProvider):
    """Kimi CLI subprocess-based provider implementation.

    Adapts kimi-cli (MoonshotAI) for use within bmad-assist via subprocess
    invocation. Kimi serves as both a Multi-LLM validator and an alternative
    Master LLM option with 256K context window.

    Supported models:
        - kimi-for-coding: Optimized for code generation and review
        - kimi-k2: K2 model series
        - kimi-k2-thinking-turbo: K2 with extended thinking mode
        - Any model string (CLI validates model names)

    Settings File Handling:
        The settings_file parameter is passed to kimi-cli via --config-file
        flag. If the file doesn't exist, a warning is logged and execution
        continues without the flag (graceful degradation).

    Thinking Mode:
        Auto-detected from model name (if contains "thinking") or explicitly
        enabled via config param. Config override wins when specified.

    Thread Safety:
        KimiProvider is stateless and thread-safe. Multiple instances can
        invoke() concurrently without interference because there is no mutable
        instance state and each subprocess.run() call is independent.

    Example:
        >>> provider = KimiProvider()
        >>> result = provider.invoke("Review this code", timeout=60)
        >>> print(provider.parse_output(result))

    """

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider.

        Returns:
            The string "kimi" as the provider identifier.

        """
        return "kimi"

    @property
    def default_model(self) -> str | None:
        """Return default model when none specified.

        Returns:
            The string "kimi-code/kimi-for-coding" as the default choice.

        """
        return "kimi-code/kimi-for-coding"

    def supports_model(self, model: str) -> bool:  # noqa: ARG002
        """Check if this provider supports the given model.

        Always returns True - kimi-cli validates model names internally.
        This avoids hardcoding a model list that becomes stale.

        Args:
            model: Model identifier to check (unused, always returns True).

        Returns:
            Always True - validation is delegated to CLI.

        Example:
            >>> provider = KimiProvider()
            >>> provider.supports_model("kimi-for-coding")
            True
            >>> provider.supports_model("any-model")
            True

        """
        return True

    def _should_enable_thinking(
        self,
        model: str | None,
        config_thinking: bool | None,
    ) -> bool:
        """Determine if --thinking flag should be added.

        Args:
            model: Model name from invoke(), may be None.
            config_thinking: Explicit config param, None for auto-detect.

        Returns:
            True if thinking mode should be enabled.

        """
        # 1. Config override always wins
        if config_thinking is not None:
            return config_thinking

        # 2. No model specified = use default, check default
        if not model:
            model = self.default_model or ""

        # 3. Auto-detect from model name (case-insensitive)
        return "thinking" in model.lower()

    def _build_prompt_with_restrictions(
        self,
        prompt: str,
        allowed_tools: list[str] | None,
    ) -> str:
        """Build prompt with tool restriction prefix for validators.

        Args:
            prompt: Original prompt text.
            allowed_tools: List of allowed tool names, or None for no restrictions.

        Returns:
            Prompt with restriction prefix prepended if allowed_tools is set.

        """
        if allowed_tools is None:
            return prompt  # Master mode - no restrictions

        tools_str = ", ".join(allowed_tools) if allowed_tools else "NONE"
        prefix = KIMI_TOOL_RESTRICTION_PREFIX.format(allowed_tools=tools_str)
        return prefix + prompt

    def _parse_kimi_jsonl(self, stdout: str) -> str:
        """Parse OpenAI-style JSONL and extract assistant content.

        Args:
            stdout: Raw JSONL output from kimi-cli.

        Returns:
            Concatenated assistant message content.

        """
        content_parts: list[str] = []

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                # Log includes the problematic line for debugging
                truncated_line = line[:100] + "..." if len(line) > 100 else line
                logger.warning("Malformed JSON line (skipping): %r - %s", truncated_line, e)
                continue

            if msg.get("role") != "assistant":
                continue

            # Extract content - handles both string and array formats
            content = _extract_text_from_content(msg.get("content"))
            # Fallback to reasoning_content if no content
            if not content and "reasoning_content" in msg:
                content = _extract_text_from_content(msg.get("reasoning_content"))

            if content:
                content_parts.append(content)

        # Join multiple messages with newline
        return "\n".join(content_parts)

    def _cleanup_process(
        self,
        process: Popen,
        stdout_thread: threading.Thread,
        stderr_thread: threading.Thread,
        timeout_occurred: bool = False,
    ) -> None:
        """Clean up process and threads safely.

        Args:
            process: The Popen process to clean up.
            stdout_thread: Thread reading stdout.
            stderr_thread: Thread reading stderr.
            timeout_occurred: True if cleanup is due to timeout.

        """
        # 1. Close stdin first (signals EOF to process)
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except Exception:
            pass

        # 2. If timeout, send SIGTERM first, then SIGKILL
        if timeout_occurred:
            try:
                process.terminate()  # SIGTERM
                process.wait(timeout=2)  # Give 2s to cleanup
            except TimeoutExpired:
                process.kill()  # SIGKILL
            except Exception:
                process.kill()

        # 3. Wait for stream readers to finish (with timeout)
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        # 4. Ensure process is dead
        try:
            process.wait(timeout=1)
        except TimeoutExpired:
            process.kill()
            process.wait()

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
    ) -> ProviderResult:
        """Execute kimi-cli with the given prompt using JSON streaming.

        Invokes kimi-cli via Popen with --output-format stream-json for
        JSONL event streaming. This enables:
        - Debug logging of raw JSON events to ~/.bmad-assist/debug/json/
        - Real-time output processing
        - Consistent debugging across all providers

        Command Format:
            kimi --print --output-format stream-json -m <model> [--thinking] [--config-file <path>]

        JSON Event Format (OpenAI-style):
            {"role": "assistant", "content": "Response text here"}
            {"role": "assistant", "content": "...", "tool_calls": [...]}
            {"role": "tool", "tool_call_id": "tc_1", "content": "Tool output"}

        Text Extraction:
            Response text is extracted from messages where role === "assistant"
            from the content field (or reasoning_content as fallback).

        Args:
            prompt: The prompt text to send to kimi-cli.
            model: Model to use (kimi-for-coding, kimi-k2, etc).
                If None, uses default_model.
            timeout: Timeout in seconds. Must be positive (>= 1) if specified.
                If None, uses DEFAULT_TIMEOUT (300s).
            settings_file: Path to config file for kimi-cli (--config-file).
            cwd: Working directory for kimi-cli. Sets the workspace for file access.
            disable_tools: Ignored (kimi-cli doesn't support this flag).
            allowed_tools: List of allowed tool names (e.g., ["Read", "Glob"]).
                When set, a prompt-level warning is injected restricting tools.
            no_cache: Ignored (kimi-cli doesn't support this flag).
            color_index: Color index for terminal output differentiation.
            display_model: Display name for the model (used in logs/benchmarks).
            thinking: Enable thinking mode (--thinking flag). If None, auto-detected
                from model name (enabled if model contains "thinking").

        Returns:
            ProviderResult containing extracted text, stderr, exit code, and timing.

        Raises:
            ValueError: If timeout is not positive (<=0).
            ProviderError: If CLI execution fails.
            ProviderExitCodeError: If CLI returns non-zero exit code.
            ProviderTimeoutError: If CLI execution exceeds timeout.

        """
        # Ignored parameters (kimi-cli doesn't support these flags)
        _ = disable_tools, no_cache

        # Validate timeout parameter
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        # Resolve model with fallback chain: explicit -> default -> literal
        effective_model = model or self.default_model or "kimi-for-coding"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        # Resolve and validate settings file using shared helpers
        resolved_settings = resolve_settings_file(
            str(settings_file) if settings_file else None,
            cwd or Path.cwd(),
        )
        validated_settings = validate_settings_file(
            resolved_settings, self.provider_name, effective_model
        )

        # Determine if thinking mode should be enabled
        thinking_enabled = self._should_enable_thinking(effective_model, thinking)

        # Build prompt with tool restrictions for validators
        final_prompt = self._build_prompt_with_restrictions(prompt, allowed_tools)

        logger.debug(
            "Invoking Kimi CLI: model=%s, timeout=%ds, prompt_len=%d, settings=%s, cwd=%s, thinking=%s",
            effective_model,
            effective_timeout,
            len(prompt),
            validated_settings,
            cwd,
            thinking_enabled,
        )

        # Build command with --output-format stream-json for JSONL streaming
        # Note: prompt passed via stdin to avoid "Argument list too long" error
        command: list[str] = [
            "kimi",
            "--print",
            "--output-format",
            "stream-json",
            "-m",
            effective_model,
        ]

        if thinking_enabled:
            command.append("--thinking")

        if cwd is not None:
            command.extend(["--work-dir", str(cwd)])

        if validated_settings is not None:
            command.extend(["--config-file", str(validated_settings)])

        # Retry loop for transient failures
        last_error: ProviderExitCodeError | None = None
        returncode = 0
        stderr_content = ""
        response_text_parts: list[str] = []
        debug_json_logger: DebugJsonLogger | None = None
        duration_ms = 0

        for attempt in range(MAX_RETRIES):
            if attempt > 0:
                delay = _calculate_retry_delay(attempt - 1)
                logger.warning(
                    "Kimi CLI retry %d/%d after %.1fs delay (previous: %s)",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                    last_error,
                )
                time.sleep(delay)

            # Debug JSON logger for raw event stream
            debug_json_logger = DebugJsonLogger()

            # Accumulators for JSON stream parsing
            response_text_parts = []
            stderr_chunks: list[str] = []
            raw_stdout_lines: list[str] = []

            start_time = time.perf_counter()

            try:
                # Set up environment
                env = os.environ.copy()

                # Use Popen directly with cwd parameter (NO shell=True for security)
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
                )

                # Write prompt to stdin and close it
                if process.stdin:
                    process.stdin.write(final_prompt)
                    process.stdin.close()

                # Print output only in verbose/debug mode
                print_output = logger.isEnabledFor(logging.DEBUG)

                def process_json_stream(
                    stream,
                    text_parts: list[str],
                    raw_lines: list[str],
                    print_progress: bool,
                    json_logger: DebugJsonLogger,
                    color_idx: int | None,
                ) -> None:
                    """Process kimi-cli stream-json output, extracting text and logging."""
                    for line in iter(stream.readline, ""):
                        raw_lines.append(line)
                        stripped = line.strip()
                        if not stripped:
                            continue

                        # Log raw JSON immediately (survives crashes)
                        json_logger.append(stripped)

                        try:
                            msg = json.loads(stripped)
                            role = msg.get("role", "")

                            if role == "assistant":
                                # Extract content - handles both string and array formats
                                content = _extract_text_from_content(msg.get("content"))
                                if not content and "reasoning_content" in msg:
                                    content = _extract_text_from_content(
                                        msg.get("reasoning_content")
                                    )

                                if content:
                                    text_parts.append(content)
                                    if print_progress:
                                        preview = content[:200]
                                        if len(content) > 200:
                                            preview += "..."
                                        tag = format_tag("ASSISTANT", color_idx)
                                        write_progress(f"{tag} {preview}")

                                # Log tool calls if present
                                tool_calls = msg.get("tool_calls", [])
                                for tc in tool_calls:
                                    if print_progress and isinstance(tc, dict):
                                        func = tc.get("function", {})
                                        tool_name = func.get("name", "?")
                                        try:
                                            args = json.loads(func.get("arguments", "{}"))
                                        except json.JSONDecodeError:
                                            args = {}
                                        details = extract_tool_details(tool_name, args)
                                        tag = format_tag(f"TOOL {tool_name}", color_idx)
                                        if details:
                                            write_progress(f"{tag} {details}")
                                        else:
                                            write_progress(f"{tag}")

                            elif role == "tool":
                                # Tool result - skip display (too verbose)
                                pass

                        except json.JSONDecodeError:
                            if print_progress:
                                tag = format_tag("RAW", color_idx)
                                write_progress(f"{tag} {stripped}")

                    stream.close()

                def read_stderr(
                    stream,
                    chunks: list[str],
                    print_lines: bool,
                    color_idx: int | None,
                ) -> None:
                    """Read stderr stream."""
                    for line in iter(stream.readline, ""):
                        chunks.append(line)
                        if print_lines:
                            stripped = line.rstrip()
                            tag = format_tag("ERR", color_idx)
                            write_progress(f"{tag} {stripped}")
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

                if print_output:
                    shown_model = display_model or effective_model
                    tag = format_tag("START", color_index)
                    write_progress(f"{tag} Invoking Kimi CLI (model={shown_model})...")
                    tag = format_tag("PROMPT", color_index)
                    write_progress(f"{tag} {len(prompt):,} chars")
                    tag = format_tag("WAITING", color_index)
                    write_progress(f"{tag} Streaming response...")

                # Wait for process with timeout
                try:
                    returncode = process.wait(timeout=effective_timeout)
                except TimeoutExpired:
                    self._cleanup_process(
                        process, stdout_thread, stderr_thread, timeout_occurred=True
                    )
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
                        f"Kimi CLI timeout after {effective_timeout}s: {truncated}",
                        partial_result=partial_result,
                    ) from None

                # Wait for threads to finish
                stdout_thread.join()
                stderr_thread.join()

            except FileNotFoundError as e:
                logger.error("Kimi CLI not found in PATH")
                raise ProviderError("Kimi CLI not found. Is 'kimi' in PATH?") from e
            finally:
                if debug_json_logger:
                    debug_json_logger.close()

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            stderr_content = "".join(stderr_chunks)

            if returncode != 0:
                exit_status = ExitStatus.from_code(returncode)
                stderr_truncated = (
                    stderr_content[:STDERR_TRUNCATE_LENGTH] if stderr_content else "(empty)"
                )

                logger.error(
                    "Kimi CLI failed: exit_code=%d, status=%s, model=%s, stderr=%s",
                    returncode,
                    exit_status.name,
                    effective_model,
                    stderr_truncated,
                )

                if exit_status == ExitStatus.SIGNAL:
                    signal_num = ExitStatus.get_signal_number(returncode)
                    message = (
                        f"Kimi CLI failed with exit code {returncode} "
                        f"(signal {signal_num}): {stderr_truncated}"
                    )
                elif exit_status == ExitStatus.NOT_FOUND:
                    message = (
                        f"Kimi CLI failed with exit code {returncode} "
                        f"(command not found - check PATH): {stderr_truncated}"
                    )
                elif exit_status == ExitStatus.CANNOT_EXECUTE:
                    message = (
                        f"Kimi CLI failed with exit code {returncode} "
                        f"(permission denied): {stderr_truncated}"
                    )
                else:
                    message = f"Kimi CLI failed with exit code {returncode}: {stderr_truncated}"

                error = ProviderExitCodeError(
                    message,
                    exit_code=returncode,
                    exit_status=exit_status,
                    stderr=stderr_content,
                    command=tuple(command),
                )

                # Check if transient error (should retry)
                is_transient = _is_kimi_transient_error(stderr_content, returncode)

                if is_transient and attempt < MAX_RETRIES - 1:
                    last_error = error
                    continue  # Retry

                # Not retryable or out of retries - raise the error
                raise error

            # Success - break out of retry loop
            break

        # Combine extracted text parts (no separator to avoid mid-word breaks if chunks split)
        response_text = "".join(response_text_parts)

        # Get provider session_id
        provider_session_id = debug_json_logger.provider_session_id if debug_json_logger else None

        logger.info(
            "Kimi CLI completed: duration=%dms, exit_code=%d, text_len=%d",
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
        r"""Extract response text from Kimi CLI output.

        Kimi CLI with stream-json outputs JSONL where text is extracted
        during invoke(). The ProviderResult.stdout already contains the
        extracted response text.

        Args:
            result: ProviderResult from invoke() containing extracted output.

        Returns:
            Extracted response text with whitespace stripped.
            Empty string if stdout is empty.

        Example:
            >>> result = ProviderResult(stdout="  Code review complete  \n", ...)
            >>> provider.parse_output(result)
            'Code review complete'

        """
        return result.stdout.strip()

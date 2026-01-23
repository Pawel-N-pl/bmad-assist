"""OpenCode CLI subprocess-based provider implementation.

This module implements the OpenCodeProvider class that adapts OpenCode CLI
for use within bmad-assist via subprocess invocation. OpenCode serves as
a Multi LLM validator for story validation and code review phases.

File Access:
    When cwd is provided, Popen runs OpenCode from that directory, which
    becomes OpenCode's workspace. This allows file access to the target
    project directory for code review and validation tasks.

JSON Streaming:
    Uses --format json flag to capture JSONL event stream.
    Event types: step_start, text, tool_use, step_finish
    Text extracted from text events: {"type": "text", "part": {"text": "..."}}

Example:
    >>> from bmad_assist.providers import OpenCodeProvider
    >>> provider = OpenCodeProvider()
    >>> result = provider.invoke("Review this code", model="opencode/claude-sonnet-4")
    >>> response = provider.parse_output(result)

"""

import json
import logging
import os
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
    extract_tool_details,
    format_tag,
    validate_settings_file,
    write_progress,
)

logger = logging.getLogger(__name__)

# OpenCode model format is "provider/model" - e.g., "opencode/claude-sonnet-4", "xai/grok-4"
# We don't hardcode supported models - let the OpenCode CLI validate them

# Default timeout in seconds (5 minutes)
DEFAULT_TIMEOUT: int = 300

# Maximum prompt length in error messages before truncation
PROMPT_TRUNCATE_LENGTH: int = 100

# Maximum stderr length in error messages before truncation
STDERR_TRUNCATE_LENGTH: int = 200

# Retry configuration for transient failures (rate limiting, API errors)
MAX_RETRIES: int = 5
RETRY_BASE_DELAY: float = 2.0  # Base delay in seconds (exponential backoff)
RETRY_MAX_DELAY: float = 30.0  # Maximum delay between retries

# Tool name mapping: OpenCode CLI uses lowercase names, we use display names
_OPENCODE_TOOL_NAME_MAP: dict[str, str] = {
    "bash": "Bash",
    "edit": "Edit",
    "write": "Write",
    "read": "Read",
    "glob": "Glob",
    "grep": "Grep",
    "webfetch": "WebFetch",
    "websearch": "WebSearch",
}

# Display names for common tools (used in restricted_tools list)
_COMMON_TOOL_NAMES: frozenset[str] = frozenset(
    {"Edit", "Write", "Bash", "Glob", "Grep", "WebFetch", "WebSearch", "Read"}
)


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


class OpenCodeProvider(BaseProvider):
    """OpenCode CLI subprocess-based provider implementation.

    Adapts OpenCode CLI for use within bmad-assist via subprocess invocation.
    OpenCode serves as a Multi LLM validator for parallel validation phases.

    Supported models (from OpenCode CLI):
        - opencode/claude-sonnet-4: Claude Sonnet 4 via OpenCode (default)
        - opencode/claude-opus-4-5: Claude Opus 4.5 via OpenCode
        - xai/grok-3: Grok 3 via xAI
        - xai/grok-4: Grok 4 via xAI
        - opencode/gemini-3-flash: Gemini 3 Flash via OpenCode
        - opencode/gemini-3-pro: Gemini 3 Pro via OpenCode

    Thread Safety:
        OpenCodeProvider is stateless and thread-safe. Multiple instances can
        invoke() concurrently without interference because there is no mutable
        instance state and each subprocess.run() call is independent.

    Example:
        >>> provider = OpenCodeProvider()
        >>> result = provider.invoke("Review this code", timeout=60)
        >>> print(provider.parse_output(result))

    """

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider.

        Returns:
            The string "opencode" as the provider identifier.

        """
        return "opencode"

    @property
    def default_model(self) -> str | None:
        """Return default model when none specified.

        Returns:
            The string "opencode/claude-sonnet-4" as the default choice.

        """
        return "opencode/claude-sonnet-4"

    def supports_model(self, model: str) -> bool:
        """Check if this provider supports the given model.

        OpenCode accepts any model in "provider/model" format.
        We don't validate the specific model - let the CLI handle that.

        Args:
            model: Model identifier to check (must contain "/").

        Returns:
            True if model has valid format (contains "/"), False otherwise.

        Example:
            >>> provider = OpenCodeProvider()
            >>> provider.supports_model("opencode/claude-sonnet-4")
            True
            >>> provider.supports_model("zai-coding-plan/glm-4.7")
            True
            >>> provider.supports_model("gpt-4")
            False

        """
        # OpenCode requires "provider/model" format
        return "/" in model

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
        display_model: str | None = None,
    ) -> ProviderResult:
        """Execute OpenCode CLI with the given prompt using JSON streaming.

        Invokes OpenCode CLI via Popen with --format json for JSONL event
        streaming. This enables:
        - Debug logging of raw JSON events to ~/.bmad-assist/debug/json/
        - Real-time output processing
        - Consistent debugging across all providers

        Command Format:
            opencode run -m <model> --format json
            (prompt via stdin)

        JSON Event Types:
            - step_start: Step initialization with session_id
            - text: Response text chunks {"part": {"text": "..."}}
            - tool_use: Tool call requests with parameters
            - step_finish: Step completion with reason, cost, tokens

        Text Extraction:
            Response text is extracted from text events where
            part.type === "text" from the part.text field.

        Args:
            prompt: The prompt text to send to OpenCode.
            model: Model to use (opencode/claude-sonnet-4, xai/grok-3, etc).
                If None, uses default_model.
            timeout: Timeout in seconds. Must be positive (>= 1) if specified.
                If None, uses DEFAULT_TIMEOUT (300s).
            settings_file: Path to settings file. NOTE: OpenCode CLI does not support
                settings files, so this parameter is validated but NOT passed to the CLI.
                Provided for API compatibility with other providers.
            cwd: Working directory for OpenCode CLI. Sets the workspace for file access.
            disable_tools: Disable tools (ignored - OpenCode CLI doesn't support).
            allowed_tools: List of allowed tool names (e.g., ["TodoWrite", "Read"]).
                When set, a prompt-level warning is injected restricting tools.
                WARNING: This is a soft restriction - OpenCode CLI may still execute
                restricted tools. Logging captures violations.
            no_cache: Disable caching (ignored - OpenCode CLI doesn't support).
            color_index: Color index for terminal output differentiation.
            display_model: Display name for the model (used in logs/benchmarks).

        Returns:
            ProviderResult containing extracted text, stderr, exit code, and timing.

        Raises:
            ValueError: If timeout is not positive (<=0).
            ProviderError: If CLI execution fails or model is unsupported.
            ProviderExitCodeError: If CLI returns non-zero exit code.
            ProviderTimeoutError: If CLI execution exceeds timeout.

        """
        # Ignored parameters (OpenCode CLI doesn't support these flags)
        _ = disable_tools, no_cache

        # Validate timeout parameter
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        # Resolve model with fallback chain: explicit -> default -> literal
        effective_model = model or self.default_model or "opencode/claude-sonnet-4"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        # Validate model format before building command (fail-fast)
        if not self.supports_model(effective_model):
            raise ProviderError(
                f"Invalid model format '{effective_model}' for OpenCode provider. "
                f"Expected 'provider/model' format (e.g., 'opencode/claude-sonnet-4', 'zai-coding-plan/glm-4.7')"
            )

        # Validate and resolve settings file
        validated_settings = self._resolve_settings(settings_file, effective_model)

        # Build list of restricted tools (tools NOT in allowed_tools)
        restricted_tools: list[str] | None = None
        if allowed_tools is not None:
            allowed_set = set(allowed_tools)
            restricted_tools = sorted(_COMMON_TOOL_NAMES - allowed_set)

            if restricted_tools:
                logger.info(
                    "OpenCode CLI: Tool restrictions applied (allowed=%s, restricted=%s)",
                    allowed_tools,
                    restricted_tools,
                )
            else:
                logger.debug(
                    "OpenCode CLI: allowed_tools=%s (all common tools allowed)",
                    allowed_tools,
                )

        logger.debug(
            "OpenCode CLI: cwd=%s (exists=%s, is_dir=%s)",
            cwd,
            cwd.exists() if cwd else "N/A",
            cwd.is_dir() if cwd else "N/A",
        )
        logger.debug(
            "Invoking OpenCode CLI: model=%s, timeout=%ds, prompt_len=%d, settings=%s, cwd=%s",
            effective_model,
            effective_timeout,
            len(prompt),
            validated_settings,
            cwd,
        )

        # Add prompt-level tool restriction warning if tools are restricted
        final_prompt = prompt
        if restricted_tools:
            allowed_str = ", ".join(allowed_tools) if allowed_tools else "none"
            restricted_str = ", ".join(restricted_tools)

            restriction_warning = (
                "\n\n**CRITICAL - TOOL ACCESS RESTRICTIONS (READ CAREFULLY):**\n"
                f"You are a CODE REVIEWER with LIMITED tool access.\n\n"
                f"✅ ALLOWED tools ONLY: {allowed_str}\n"
                f"❌ FORBIDDEN tools (NEVER USE): {restricted_str}\n\n"
                "**MANDATORY RULES:**\n"
                "1. Use `Read` to view file contents - NEVER use Bash for cat/head/tail\n"
                "2. Use `Glob` to find files by pattern - NEVER use Bash for ls/find commands\n"
                "3. Use `Grep` to search code content - NEVER use Bash for grep/rg/ag commands\n"
                "4. You CANNOT modify any files - this is a READ-ONLY code review\n"
                "5. If you need to see a file, use Read. If you need to find files, use Glob. If you need to search, use Grep.\n"
                "6. Using Bash will FAIL - these tools are disabled for reviewers.\n\n"
                "Your task: Produce a CODE REVIEW REPORT analyzing the implementation. No file modifications allowed.\n"
            )
            final_prompt = prompt + restriction_warning
            logger.debug("Added prompt-level tool restriction warning for OpenCode CLI")

        # Build command with --format json for JSONL streaming
        command: list[str] = [
            "opencode",
            "run",
            "-m",
            effective_model,
            "--format",
            "json",
        ]

        if validated_settings is not None:
            logger.debug(
                "Settings file validated but not passed to OpenCode CLI: %s",
                validated_settings,
            )

        # Retry loop for transient failures (rate limiting, API errors)
        last_error: ProviderExitCodeError | None = None
        returncode: int = 0
        duration_ms: int = 0
        stderr_content: str = ""
        response_text_parts: list[str] = []
        debug_json_logger = DebugJsonLogger()

        for attempt in range(MAX_RETRIES):
            if attempt > 0:
                delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
                logger.warning(
                    "OpenCode CLI retry %d/%d after %.1fs delay (previous: %s)",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                    last_error,
                )
                time.sleep(delay)

            # Reset accumulators for retry
            # Note: Previous iteration's threads are joined before we get here (either via
            # successful completion or timeout handling), so resetting logger is safe
            debug_json_logger = DebugJsonLogger()
            response_text_parts = []
            stderr_chunks: list[str] = []
            session_id: str | None = None

            start_time = time.perf_counter()

            try:
                # Set up environment
                env = os.environ.copy()

                if cwd is not None:
                    env["PWD"] = str(cwd)

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
                    stream: Any,
                    text_parts: list[str],
                    print_progress: bool,
                    json_logger: DebugJsonLogger,
                    color_idx: int | None,
                ) -> None:
                    """Process OpenCode stream-json output, extracting text and logging."""
                    nonlocal session_id
                    warned_tools: set[str] = set()  # Dedupe restricted tool warnings
                    for line in iter(stream.readline, ""):
                        stripped = line.strip()
                        if not stripped:
                            continue

                        # Log raw JSON immediately (survives crashes)
                        json_logger.append(stripped)

                        try:
                            msg = json.loads(stripped)
                            msg_type = msg.get("type", "")

                            if msg_type == "step_start":
                                session_id = msg.get("sessionID", "?")
                                if print_progress:
                                    tag = format_tag("INIT", color_idx)
                                    write_progress(f"{tag} Session: {session_id}")

                            elif msg_type == "text":
                                part = msg.get("part", {})
                                if part.get("type") == "text":
                                    text = part.get("text", "")
                                    if text:
                                        text_parts.append(text)
                                        if print_progress:
                                            preview = text[:200]
                                            if len(text) > 200:
                                                preview += "..."
                                            tag = format_tag("ASSISTANT", color_idx)
                                            write_progress(f"{tag} {preview}")

                            elif msg_type == "tool_use":
                                part = msg.get("part", {})
                                tool_name: str = part.get("tool") or "unknown"
                                # Normalize tool name for restriction check
                                normalized_tool_name: str = _OPENCODE_TOOL_NAME_MAP.get(
                                    tool_name.lower(), tool_name.capitalize()
                                )
                                # Log warning if restricted tools are attempted (once per tool)
                                if (
                                    restricted_tools
                                    and normalized_tool_name in restricted_tools
                                    and normalized_tool_name not in warned_tools
                                ):
                                    warned_tools.add(normalized_tool_name)
                                    logger.warning(
                                        "OpenCode CLI: Attempted to use restricted tool '%s' "
                                        "(normalized='%s', allowed=%s, restricted=%s). "
                                        "Tool may still execute - this is a prompt-level warning only.",
                                        tool_name,
                                        normalized_tool_name,
                                        allowed_tools,
                                        restricted_tools,
                                    )
                                if print_progress:
                                    state = part.get("state", {})
                                    tool_input = state.get("input", {})
                                    details = extract_tool_details(normalized_tool_name, tool_input)
                                    tag = format_tag(f"TOOL {normalized_tool_name}", color_idx)
                                    if details:
                                        write_progress(f"{tag} {details}")
                                    else:
                                        write_progress(f"{tag}")

                            elif msg_type == "step_finish":
                                if print_progress:
                                    part = msg.get("part", {})
                                    cost = part.get("cost", 0)
                                    tokens = part.get("tokens", {})
                                    tag = format_tag("RESULT", color_idx)
                                    write_progress(f"{tag} cost={cost:.4f} tokens={tokens}")

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
                    write_progress(f"{tag} Invoking OpenCode CLI (model={shown_model})...")
                    tag = format_tag("PROMPT", color_index)
                    write_progress(f"{tag} {len(prompt):,} chars")
                    tag = format_tag("WAITING", color_index)
                    write_progress(f"{tag} Streaming response...")

                # Wait for process with timeout
                try:
                    returncode = process.wait(timeout=effective_timeout)
                except TimeoutExpired:
                    process.kill()
                    # Join threads with timeout - they should terminate quickly after process is killed
                    stdout_thread.join(timeout=2)
                    stderr_thread.join(timeout=2)
                    if stdout_thread.is_alive() or stderr_thread.is_alive():
                        logger.warning(
                            "OpenCode CLI: Reader threads did not terminate cleanly after timeout"
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
                        f"OpenCode CLI timeout after {effective_timeout}s: {truncated}",
                        partial_result=partial_result,
                    ) from None

                # Wait for threads to finish
                stdout_thread.join()
                stderr_thread.join()

            except FileNotFoundError as e:
                logger.error("OpenCode CLI not found in PATH")
                raise ProviderError("OpenCode CLI not found. Is 'opencode' in PATH?") from e
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
                    "OpenCode CLI failed: exit_code=%d, status=%s, model=%s, stderr=%s",
                    returncode,
                    exit_status.name,
                    effective_model,
                    stderr_truncated,
                )

                if exit_status == ExitStatus.SIGNAL:
                    signal_num = ExitStatus.get_signal_number(returncode)
                    message = (
                        f"OpenCode CLI failed with exit code {returncode} "
                        f"(signal {signal_num}): {stderr_truncated}"
                    )
                elif exit_status == ExitStatus.NOT_FOUND:
                    message = (
                        f"OpenCode CLI failed with exit code {returncode} "
                        f"(command not found - check PATH): {stderr_truncated}"
                    )
                elif exit_status == ExitStatus.CANNOT_EXECUTE:
                    message = (
                        f"OpenCode CLI failed with exit code {returncode} "
                        f"(permission denied): {stderr_truncated}"
                    )
                else:
                    message = f"OpenCode CLI failed with exit code {returncode}: {stderr_truncated}"

                error = ProviderExitCodeError(
                    message,
                    exit_code=returncode,
                    exit_status=exit_status,
                    stderr=stderr_content,
                    command=tuple(command),
                )

                # Retry only on transient failures (empty stderr, general error status)
                is_transient = not stderr_content.strip() and exit_status == ExitStatus.ERROR

                if is_transient and attempt < MAX_RETRIES - 1:
                    last_error = error
                    continue  # Retry

                # Not retryable or out of retries - raise the error
                raise error

            # Success - break out of retry loop
            break

        # Combine extracted text parts (no separator - chunks may split words)
        response_text = "".join(response_text_parts)

        # Get provider session_id
        provider_session_id = debug_json_logger.provider_session_id

        logger.info(
            "OpenCode CLI completed: duration=%dms, exit_code=%d, text_len=%d",
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
        r"""Extract response text from OpenCode CLI output.

        OpenCode CLI outputs response to stdout as extracted text from
        JSON stream. No additional JSON parsing is needed - the response
        is the raw stdout with leading/trailing whitespace stripped.

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

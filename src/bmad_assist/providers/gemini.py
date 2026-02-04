"""Gemini CLI subprocess-based provider implementation.

This module implements the GeminiProvider class that adapts Gemini CLI
for use within bmad-assist via subprocess invocation. Gemini serves as
a Multi LLM validator for story validation and code review phases.

File Access:
    When cwd is provided, Popen runs Gemini from that directory, which
    becomes Gemini's workspace. This allows file access to the target
    project directory for code review and validation tasks.

JSON Streaming:
    Uses --output-format stream-json flag to capture JSONL event stream.
    Event types: init, message, tool_use, tool_result, error, result
    Text extracted from message events where role="assistant".

Example:
    >>> from bmad_assist.providers import GeminiProvider
    >>> provider = GeminiProvider()
    >>> result = provider.invoke("Review this code", model="gemini-2.5-flash")
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
    QuotaExhaustedError,
)
from bmad_assist.providers.base import (
    BaseProvider,
    ExitStatus,
    ProviderResult,
    extract_tool_details,
    format_tag,
    is_quota_error,
    should_print_progress,
    validate_settings_file,
    write_progress,
)

logger = logging.getLogger(__name__)

# Note: Model validation removed - Gemini CLI accepts any model string.
# The CLI itself will validate and return an error for unknown models.

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

# Tool name mapping: Gemini CLI uses technical names, we use display names
# This maps the raw tool_name from JSON stream to our display names
_GEMINI_TOOL_NAME_MAP: dict[str, str] = {
    "run_shell_command": "Bash",
    "edit_file": "Edit",
    "write_file": "Write",
    "read_file": "Read",
    "list_directory": "Glob",
    "glob": "Glob",
    "grep": "Grep",
    "search_file_content": "Grep",
    "web_fetch": "WebFetch",
    "google_web_search": "WebSearch",
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


class GeminiProvider(BaseProvider):
    """Gemini CLI subprocess-based provider implementation.

    Adapts Gemini CLI for use within bmad-assist via subprocess invocation.
    Gemini serves as a Multi LLM validator for parallel validation phases.

    Supported models (from Google Gemini CLI):
        - gemini-2.5-pro: Most capable, 1M token context window
        - gemini-2.5-flash: Fast, cost-effective (default)
        - gemini-3-pro: Latest model with enhanced performance
        - gemini-2.0-flash-exp: Experimental 2.0 features

    Settings File Handling:
        The settings_file parameter is accepted for API consistency with other
        providers but is NOT passed to Gemini CLI, which uses environment
        variables (GEMINI_API_KEY or Google OAuth) rather than CLI flags.
        When provided, the file is validated for existence (logging a warning
        if missing) but does not affect CLI execution.

    Thread Safety:
        GeminiProvider is stateless and thread-safe. Multiple instances can
        invoke() concurrently without interference because there is no mutable
        instance state and each subprocess.run() call is independent.

    Example:
        >>> provider = GeminiProvider()
        >>> result = provider.invoke("Review this code", timeout=60)
        >>> print(provider.parse_output(result))

    """

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider.

        Returns:
            The string "gemini" as the provider identifier.

        """
        return "gemini"

    @property
    def default_model(self) -> str | None:
        """Return default model when none specified.

        Returns:
            The string "gemini-2.5-flash" as the cost-effective default choice.

        """
        return "gemini-2.5-flash"

    def supports_model(self, model: str) -> bool:
        """Check if this provider supports the given model.

        Validates model names against the SUPPORTED_MODELS constant.

        Args:
            model: Model identifier to check.

        Returns:
            True if provider supports the model, False otherwise.

        Example:
            >>> provider = GeminiProvider()
            >>> provider.supports_model("gemini-2.5-flash")
            True
            >>> provider.supports_model("gemini-2.5-pro")
            True
            >>> provider.supports_model("any-model")
            True

        """
        # Always return True - let Gemini CLI validate model names
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
        display_model: str | None = None,
        thinking: bool | None = None,
        cancel_token: threading.Event | None = None,
    ) -> ProviderResult:
        """Execute Gemini CLI with the given prompt using JSON streaming.

        Invokes Gemini CLI via Popen with --output-format stream-json for
        JSONL event streaming. This enables:
        - Debug logging of raw JSON events to ~/.bmad-assist/debug/json/
        - Real-time output processing
        - Consistent debugging across all providers

        Command Format:
            gemini -p "<prompt>" -m <model> --output-format stream-json --yolo

        JSON Event Types:
            - init: Session initialization with session_id, model
            - message: User prompts and assistant responses
            - tool_use: Tool call requests with parameters
            - tool_result: Tool execution results
            - error: Non-fatal errors and warnings
            - result: Final session outcome with stats

        Text Extraction:
            Response text is extracted from message events where
            role === "assistant" from the content field.

        Args:
            prompt: The prompt text to send to Gemini.
            model: Model to use (gemini-2.5-flash, gemini-2.5-pro, etc).
                If None, uses default_model.
            timeout: Timeout in seconds. Must be positive (>= 1) if specified.
                If None, uses DEFAULT_TIMEOUT (300s).
            settings_file: Path to settings file (validated but not used by CLI).
            cwd: Working directory for Gemini CLI. Sets the workspace for file access.
            disable_tools: Disable tools (ignored - Gemini CLI doesn't support).
            allowed_tools: List of allowed tool names (e.g., ["TodoWrite", "Read"]).
                When set, a prompt-level warning is injected restricting tools.
                WARNING: This is a soft restriction - Gemini CLI may still execute
                restricted tools. Hard enforcement requires --sandbox flag which
                causes exit code 1. Security is primarily maintained via cwd.
            no_cache: Disable caching (ignored - Gemini CLI doesn't support).
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
        # Ignored parameters (Gemini CLI doesn't support these flags)
        _ = disable_tools, no_cache

        # cwd IS used - passed to Popen to set working directory
        # This ensures file access is relative to the target project, not bmad-assist

        # Validate timeout parameter
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        # Resolve model with fallback chain: explicit -> default -> literal
        effective_model = model or self.default_model or "gemini-2.5-flash"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        # Validate and resolve settings file
        validated_settings = self._resolve_settings(settings_file, effective_model)

        # Note: --sandbox flag is NOT used because it causes exit code 1 on all models
        # File access is controlled via cwd - Gemini uses it as workspace
        # However, we CAN add prompt-level tool restrictions
        restricted_tools: list[str] | None = None
        if allowed_tools is not None:
            # Build list of restricted tools (tools NOT in allowed_tools)
            # Use module-level constant for common tool names
            allowed_set = set(allowed_tools)
            restricted_tools = sorted(_COMMON_TOOL_NAMES - allowed_set)

            if restricted_tools:
                logger.info(
                    "Gemini CLI: Tool restrictions applied (allowed=%s, restricted=%s)",
                    allowed_tools,
                    restricted_tools,
                )
            else:
                logger.debug(
                    "Gemini CLI: allowed_tools=%s (all common tools allowed)",
                    allowed_tools,
                )

        logger.debug(
            "Gemini CLI: cwd=%s (exists=%s, is_dir=%s)",
            cwd,
            cwd.exists() if cwd else "N/A",
            cwd.is_dir() if cwd else "N/A",
        )
        logger.debug(
            "Invoking Gemini CLI: model=%s, timeout=%ds, prompt_len=%d, settings=%s, cwd=%s",
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
                "1. Use `Read` for files - NEVER use Bash for cat/head/tail\n"
                "2. Use `Glob` for patterns - NEVER use Bash for ls/find\n"
                "3. Use `Grep` for search - NEVER use Bash for grep/rg\n"
                "4. You CANNOT modify any files - this is READ-ONLY\n"
                "5. Need a file? Use Read. Find files? Use Glob. Search? Use Grep.\n"
                "6. Using run_shell_command/Bash will FAIL for reviewers.\n\n"
                "Your task: Produce a CODE REVIEW REPORT. No file modifications.\n"
            )
            final_prompt = prompt + restriction_warning
            logger.debug("Added prompt-level tool restriction warning for Gemini CLI")

        # Build command with --output-format stream-json for JSONL streaming
        # Note: prompt passed via stdin to avoid "Argument list too long" error
        command: list[str] = [
            "gemini",
            "-m",
            effective_model,
            "--output-format",
            "stream-json",
            "--yolo",
        ]

        # Note: --include-directories is NOT used because it doesn't work reliably
        # cwd parameter to Popen is sufficient - Gemini CLI uses cwd as workspace

        if validated_settings is not None:
            logger.debug(
                "Settings file validated but not passed to Gemini CLI: %s",
                validated_settings,
            )

        # Retry loop for transient failures (rate limiting, API errors)
        last_error: ProviderExitCodeError | None = None
        for attempt in range(MAX_RETRIES):
            if attempt > 0:
                # Exponential backoff with jitter
                delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
                logger.warning(
                    "Gemini CLI retry %d/%d after %.1fs delay (previous: %s)",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                    last_error,
                )
                time.sleep(delay)

            # Debug JSON logger for raw event stream
            debug_json_logger = DebugJsonLogger()

            # Accumulators for JSON stream parsing
            response_text_parts: list[str] = []
            stderr_chunks: list[str] = []
            raw_stdout_lines: list[str] = []
            session_id: str | None = None

            start_time = time.perf_counter()

            try:
                # Set up environment - configure git to point to target project
                env = os.environ.copy()

                if cwd is not None:
                    # Force git to see the target project as the workspace
                    # This is critical for Gemini CLI which uses git to detect project root
                    env["GIT_WORK_TREE"] = str(cwd)
                    env["GIT_DIR"] = str(cwd / ".git")
                    env["PWD"] = str(cwd)
                    # Remove any other git env vars that might interfere
                    for key in ["GIT_EDITOR", "GIT_PAGER", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL"]:
                        env.pop(key, None)

                # Use Popen directly with cwd parameter (NO shell=True for security)
                # Popen's cwd parameter sets the working directory for the subprocess
                process = Popen(
                    command,
                    stdin=PIPE,
                    stdout=PIPE,
                    stderr=PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=cwd,  # Popen handles chdir internally
                    env=env,
                    start_new_session=True,  # Own process group for safe termination
                )

                # Write prompt to stdin and close it
                if process.stdin:
                    process.stdin.write(final_prompt)
                    process.stdin.close()

                def process_json_stream(
                    stream: Any,
                    text_parts: list[str],
                    raw_lines: list[str],
                    json_logger: DebugJsonLogger,
                    color_idx: int | None,
                ) -> None:
                    """Process Gemini stream-json output, extracting text and logging."""
                    nonlocal session_id
                    warned_tools: set[str] = set()  # Dedupe restricted tool warnings
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

                            if msg_type == "init":
                                session_id = msg.get("session_id", "?")
                                if should_print_progress():
                                    tag = format_tag("INIT", color_idx)
                                    write_progress(f"{tag} Session: {session_id}")

                            elif msg_type == "message":
                                role = msg.get("role", "")
                                if role == "assistant":
                                    content = msg.get("content", "")
                                    if content:
                                        text_parts.append(content)
                                        if should_print_progress():
                                            preview = content[:200]
                                            if len(content) > 200:
                                                preview += "..."
                                            tag = format_tag("ASSISTANT", color_idx)
                                            write_progress(f"{tag} {preview}")

                            elif msg_type == "tool_use":
                                tool_name = msg.get("tool_name", "?")
                                # Normalize tool name for restriction check
                                # Map Gemini CLI technical names to display names
                                normalized_tool_name = _GEMINI_TOOL_NAME_MAP.get(
                                    tool_name, tool_name
                                )
                                # Log warning if restricted tools are attempted (once per tool)
                                if (
                                    restricted_tools
                                    and normalized_tool_name in restricted_tools
                                    and normalized_tool_name not in warned_tools
                                ):
                                    warned_tools.add(normalized_tool_name)
                                    logger.warning(
                                        "Gemini CLI: Restricted tool '%s' "
                                        "(norm='%s'). May still execute.",
                                        tool_name,
                                        normalized_tool_name,
                                    )
                                if should_print_progress():
                                    tool_params = msg.get("parameters", {})
                                    # Use shared extract_tool_details for consistent display
                                    details = extract_tool_details(tool_name, tool_params)
                                    # Format like Claude: [TOOL Bash] command...
                                    display_name = tool_name
                                    # Normalize tool names for display
                                    if tool_name == "run_shell_command":
                                        display_name = "Bash"
                                    elif tool_name == "read_file":
                                        display_name = "Read"
                                    elif tool_name == "list_directory":
                                        display_name = "Glob"
                                    tag = format_tag(f"TOOL {display_name}", color_idx)
                                    if details:
                                        write_progress(f"{tag} {details}")
                                    else:
                                        write_progress(f"{tag}")

                            elif msg_type == "tool_result":
                                # Skip tool_result display - too verbose
                                pass

                            elif msg_type == "result":
                                if should_print_progress():
                                    stats = msg.get("stats", {})
                                    total_tokens = stats.get("total_tokens", 0)
                                    duration_ms = stats.get("duration_ms", 0)
                                    tag = format_tag("RESULT", color_idx)
                                    write_progress(
                                        f"{tag} tokens={total_tokens} duration={duration_ms}ms"
                                    )

                            elif msg_type == "error":
                                if should_print_progress():
                                    error_msg = msg.get("message", str(msg))
                                    tag = format_tag("ERROR", color_idx)
                                    write_progress(f"{tag} {error_msg}")

                        except json.JSONDecodeError:
                            if should_print_progress():
                                tag = format_tag("RAW", color_idx)
                                write_progress(f"{tag} {stripped}")

                    stream.close()

                def read_stderr(
                    stream: Any,
                    chunks: list[str],
                    color_idx: int | None,
                ) -> None:
                    """Read stderr stream."""
                    # Gemini CLI outputs informational messages to stderr
                    info_prefixes = (
                        "YOLO mode",
                        "Loaded cached",
                        "Sandbox mode",
                        "File ",  # ripgrep cache messages
                    )
                    for line in iter(stream.readline, ""):
                        chunks.append(line)
                        if should_print_progress():
                            stripped = line.rstrip()
                            # Skip known informational messages
                            if any(stripped.startswith(p) for p in info_prefixes):
                                continue
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
                        debug_json_logger,
                        color_index,
                    ),
                )
                stderr_thread = threading.Thread(
                    target=read_stderr,
                    args=(process.stderr, stderr_chunks, color_index),
                )
                stdout_thread.start()
                stderr_thread.start()

                if should_print_progress():
                    shown_model = display_model or effective_model
                    tag = format_tag("START", color_index)
                    write_progress(f"{tag} Invoking Gemini CLI (model={shown_model})...")
                    tag = format_tag("PROMPT", color_index)
                    write_progress(f"{tag} {len(prompt):,} chars")
                    tag = format_tag("WAITING", color_index)
                    write_progress(f"{tag} Streaming response...")

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
                        f"Gemini CLI timeout after {effective_timeout}s: {truncated}",
                        partial_result=partial_result,
                    ) from None

                # Wait for threads to finish
                stdout_thread.join()
                stderr_thread.join()

            except FileNotFoundError as e:
                logger.error("Gemini CLI not found in PATH")
                raise ProviderError("Gemini CLI not found. Is 'gemini' in PATH?") from e
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
                    "Gemini CLI failed: exit_code=%d, status=%s, model=%s, stderr=%s",
                    returncode,
                    exit_status.name,
                    effective_model,
                    stderr_truncated,
                )

                if exit_status == ExitStatus.SIGNAL:
                    signal_num = ExitStatus.get_signal_number(returncode)
                    message = (
                        f"Gemini CLI failed with exit code {returncode} "
                        f"(signal {signal_num}): {stderr_truncated}"
                    )
                elif exit_status == ExitStatus.NOT_FOUND:
                    message = (
                        f"Gemini CLI failed with exit code {returncode} "
                        f"(command not found - check PATH): {stderr_truncated}"
                    )
                elif exit_status == ExitStatus.CANNOT_EXECUTE:
                    message = (
                        f"Gemini CLI failed with exit code {returncode} "
                        f"(permission denied): {stderr_truncated}"
                    )
                else:
                    message = f"Gemini CLI failed with exit code {returncode}: {stderr_truncated}"

                # Check if this is a retryable error (empty stderr suggests transient failure)
                error = ProviderExitCodeError(
                    message,
                    exit_code=returncode,
                    exit_status=exit_status,
                    stderr=stderr_content,
                    command=tuple(command),
                )

                # Check for quota exhaustion FIRST (non-retryable, triggers fallback)
                if is_quota_error(stderr_content):
                    raise QuotaExhaustedError(
                        f"Gemini quota exhausted for model {effective_model}",
                        provider_name="gemini",
                        model=effective_model,
                        stderr=stderr_content,
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
            "Gemini CLI completed: duration=%dms, exit_code=%d, text_len=%d",
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
        r"""Extract response text from Gemini CLI output.

        Gemini CLI outputs response to stdout in plain text format.
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

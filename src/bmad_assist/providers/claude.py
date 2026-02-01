"""Claude Code CLI subprocess-based provider implementation.

This module implements the ClaudeSubprocessProvider class that adapts Claude Code CLI
for use within bmad-assist via subprocess invocation. This provider is retained for
benchmarking and comparison purposes where fair subprocess-based comparison with
Codex and Gemini providers is required.

For the primary Claude integration, use ClaudeSDKProvider (claude_sdk.py) which
provides native async support, typed messages, and proper SDK error handling.

Example:
    >>> from bmad_assist.providers import ClaudeSubprocessProvider
    >>> provider = ClaudeSubprocessProvider()
    >>> result = provider.invoke("What is 2+2?", model="sonnet")
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

# Supported short model names accepted by Claude Code CLI
SUPPORTED_MODELS: frozenset[str] = frozenset({"opus", "sonnet", "haiku"})

# Default timeout in seconds (5 minutes)
DEFAULT_TIMEOUT: int = 300

# Maximum prompt length in error messages before truncation
PROMPT_TRUNCATE_LENGTH: int = 100

# Maximum stderr length in error messages before truncation (AC2)
STDERR_TRUNCATE_LENGTH: int = 200

# =============================================================================
# Concurrent Output Formatting
# =============================================================================


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


class ClaudeSubprocessProvider(BaseProvider):
    """Claude Code CLI subprocess-based provider implementation.

    Adapts Claude Code CLI for use within bmad-assist via subprocess invocation.
    This provider is retained for benchmarking and fair comparison with Codex
    and Gemini providers which only have subprocess interfaces.

    For the primary Claude integration with native async support and typed
    messages, use ClaudeSDKProvider (claude_sdk.py) instead.

    Claude Code supports these models:
        - opus: Most capable model
        - sonnet: Balanced model (default)
        - haiku: Fastest model
        - Any full identifier starting with "claude-"

    Settings File Handling:
        When settings_file is provided to invoke(), it is validated for
        existence before CLI execution. If the file is missing or is not
        a regular file, a warning is logged and --settings flag is omitted
        (graceful degradation). This ensures the CLI uses defaults rather
        than failing on missing settings files.

    Example:
        >>> provider = ClaudeSubprocessProvider()
        >>> result = provider.invoke("Hello", model="opus", timeout=60)
        >>> print(provider.parse_output(result))

    """

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider.

        Returns:
            The string "claude-subprocess" as the provider identifier.

        """
        return "claude-subprocess"

    @property
    def default_model(self) -> str | None:
        """Return default model when none specified.

        Returns:
            The string "sonnet" as the balanced default choice.

        """
        return "sonnet"

    def supports_model(self, model: str) -> bool:
        """Check if this provider supports the given model.

        Validates both short model names (opus, sonnet, haiku) and
        full Claude model identifiers (strings starting with "claude-").

        Args:
            model: Model identifier to check.

        Returns:
            True if provider supports the model, False otherwise.

        Example:
            >>> provider = ClaudeProvider()
            >>> provider.supports_model("sonnet")
            True
            >>> provider.supports_model("claude-3-5-sonnet-20241022")
            True
            >>> provider.supports_model("gpt-4")
            False

        """
        return model in SUPPORTED_MODELS or model.startswith("claude-")

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
    ) -> ProviderResult:
        """Execute Claude Code CLI with the given prompt.

        Invokes Claude Code CLI via Popen with streaming output capture.

        Output Encoding:
            Uses explicit encoding='utf-8' and errors='replace' for consistent
            cross-platform behavior. Invalid UTF-8 bytes are replaced with the
            Unicode replacement character (U+FFFD) rather than raising errors.
            Replacement characters are logged at DEBUG level when detected.

        Output Size:
            No artificial truncation is applied. Outputs are streamed line by
            line for immediate collection. Typical LLM CLI outputs are <10MB.

        Settings File Validation:
            The settings_file path is validated for existence before CLI
            execution using validate_settings_file(). If the file is missing
            or is a directory (not a regular file), a warning is logged with
            provider and model context, and --settings flag is omitted from
            the CLI command (graceful degradation to defaults per AC2-AC4).

        Args:
            prompt: The prompt text to send to Claude.
            model: Model to use (opus, sonnet, haiku, or claude-* identifier).
                If None, uses default_model ("sonnet").
            timeout: Timeout in seconds. Must be positive (>= 1) if specified.
                If None, uses DEFAULT_TIMEOUT (300s).
            settings_file: Path to Claude settings JSON file.
            cwd: Working directory for the CLI process. If None, uses current
                directory.
            disable_tools: If True, disables all tools (--tools ""). Useful for
                pure text transformation tasks where tool usage is unwanted.
            allowed_tools: List of tool names to allow (e.g., ["TodoWrite"]).
                Uses --allowedTools CLI flag. Mutually exclusive with disable_tools.
                When set, only specified tools are available to the agent.
            no_cache: If True, disables prompt caching. Useful for one-shot
                prompts where caching overhead is wasteful.
            color_index: Index for console output color (0-7). When multiple
                providers run concurrently, each gets a different color for
                easy visual distinction. None means no color.
            display_model: Human-readable model name for progress output.
                If provided, shown instead of the CLI model (e.g., "glm-4.7"
                instead of "sonnet" when using GLM via settings file).

        Returns:
            ProviderResult containing stdout, stderr, exit code, and timing.
            Both stdout and stderr are string type (never bytes), captured
            separately without mixing.

        Raises:
            ValueError: If timeout is not positive (<=0).
            ProviderError: If CLI execution fails due to:
                - Unsupported model specified
                - CLI executable not found (FileNotFoundError)
            ProviderExitCodeError: If CLI returns non-zero exit code.
                Contains exit_code, exit_status, stderr, and command context.
            ProviderTimeoutError: If CLI execution exceeds timeout.
                Contains partial_result if output was captured before timeout.

        Example:
            >>> provider = ClaudeProvider()
            >>> result = provider.invoke("Hello", model="sonnet", timeout=60)
            >>> result.exit_code
            0

        """
        # Validate timeout parameter (AC7)
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        # Resolve model with fallback chain: explicit -> default -> literal
        effective_model = model or self.default_model or "sonnet"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        # Validate and resolve settings file (AC2, AC3, AC4)
        # This happens AFTER model validation, BEFORE command building
        validated_settings = self._resolve_settings(settings_file, effective_model)

        # Build tools info for logging (distinguish empty list from None)
        tools_info: str
        if disable_tools:
            tools_info = "disabled"
        elif allowed_tools is not None:
            tools_info = ",".join(allowed_tools) if allowed_tools else "disabled (empty list)"
        else:
            tools_info = "all"
        logger.debug(
            "Invoking Claude CLI: model=%s, display_model=%s, timeout=%ds, "
            "prompt_len=%d, settings=%s, tools=%s",
            effective_model,
            display_model,
            effective_timeout,
            len(prompt),
            validated_settings,
            tools_info,
        )

        # Build command with stream-json for real-time output
        # Note: prompt passed via stdin to avoid "Argument list too long" error
        # --dangerously-skip-permissions: required for automated workflows
        # (slash commands, file edits, etc. need auto-approval)
        # --verbose: required when using --output-format=stream-json with --print
        command: list[str] = [
            "claude",
            "-p",
            "-",  # Read prompt from stdin
            "--model",
            effective_model,
            "--output-format",
            "stream-json",
            "--verbose",  # Required for stream-json with --print
            "--dangerously-skip-permissions",
        ]

        # Add settings file only if validated (exists and is a file)
        if validated_settings is not None:
            command.extend(["--settings", str(validated_settings)])

        # CRITICAL: Only add --add-dir for non-validator invocations!
        # Validators (allowed_tools != None) MUST NOT get file write access.
        # --add-dir gives LLM ability to Edit/Write files in the directory,
        # which validators should NOT have. They should only read via <file> embeds.
        # This prevents validators from modifying story files, code, etc.
        should_add_dir = cwd is not None and allowed_tools is None
        if should_add_dir:
            command.extend(["--add-dir", str(cwd)])

        # Disable all tools if requested (for pure text transformation)
        if disable_tools:
            command.extend(["--tools", ""])
        elif allowed_tools is not None:
            # Restrict to ONLY specified tools (e.g., ["TodoWrite"] for validators)
            # Use --tools to explicitly set the tool list, not --allowedTools which filters
            # Empty list [] means disable all tools (allowed_tools=[] is falsy but explicit)
            if allowed_tools:
                command.extend(["--tools", ",".join(allowed_tools)])
            else:
                command.extend(["--tools", ""])

        # Prepare environment (inherit current + optionally disable caching)
        env = os.environ.copy()
        if no_cache:
            env["DISABLE_PROMPT_CACHING"] = "1"

        start_time = time.perf_counter()
        print_output = logger.isEnabledFor(logging.DEBUG)

        # Debug JSON logger - writes raw JSON to file for debugging
        # Enabled only in DEBUG mode, writes immediately to survive crashes
        debug_json_logger = DebugJsonLogger()

        # Accumulators for stream-json parsing
        response_text_parts: list[str] = []
        stderr_chunks: list[str] = []
        raw_stdout_lines: list[str] = []

        try:
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
                process.stdin.write(prompt)
                process.stdin.close()

            def process_json_stream(
                stream: Any,
                text_parts: list[str],
                raw_lines: list[str],
                print_progress: bool,
                json_logger: DebugJsonLogger,
                color_idx: int | None,
            ) -> None:
                """Process stream-json output, extracting text and showing progress."""
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

                        if msg_type == "system" and msg.get("subtype") == "init":
                            # Session started
                            session_id = msg.get("session_id", "?")
                            if print_progress:
                                tag = format_tag("INIT", color_idx)
                                write_progress(f"{tag} Session: {session_id}")

                        elif msg_type == "assistant":
                            # Assistant message with content
                            message = msg.get("message", {})
                            for block in message.get("content", []):
                                if block.get("type") == "text":
                                    text = block.get("text", "")
                                    text_parts.append(text)
                                    if print_progress:
                                        # Show first 100 chars of each text block
                                        preview = text[:100].replace("\n", " ")
                                        if len(text) > 100:
                                            preview += "..."
                                        tag = format_tag("ASSISTANT", color_idx)
                                        write_progress(f"{tag} {preview}")
                                elif block.get("type") == "tool_use":
                                    tool_name = block.get("name", "?")
                                    tool_input = block.get("input", {})
                                    if print_progress:
                                        details = extract_tool_details(tool_name, tool_input)
                                        tag = format_tag(f"TOOL {tool_name}", color_idx)
                                        if details:
                                            write_progress(f"{tag} {details}")
                                        else:
                                            write_progress(f"{tag}")

                        elif msg_type == "result":
                            # Final result with stats
                            if print_progress:
                                cost = msg.get("total_cost_usd", 0)
                                duration = msg.get("duration_ms", 0)
                                turns = msg.get("num_turns", 0)
                                tag = format_tag("RESULT", color_idx)
                                write_progress(f"{tag} ${cost:.4f} | {duration}ms | {turns} turns")
                            # Extract final result text if present
                            if "result" in msg:
                                text_parts.append(msg["result"])

                    except json.JSONDecodeError:
                        # Non-JSON line, just accumulate
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

            if print_output:
                shown_model = display_model or effective_model
                tag = format_tag("START", color_index)
                write_progress(f"{tag} Invoking Claude CLI (model={shown_model})...")
                tag = format_tag("PROMPT", color_index)
                write_progress(f"{tag} {len(prompt):,} chars")
                tag = format_tag("WAITING", color_index)
                write_progress(f"{tag} Streaming response...")

            # Wait for process with timeout
            try:
                returncode = process.wait(timeout=effective_timeout)
            except TimeoutExpired as e:
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

                # Close debug logger before raising
                debug_json_logger.close()

                raise ProviderTimeoutError(
                    f"Claude CLI timeout after {effective_timeout}s: {truncated}",
                    partial_result=partial_result,
                ) from e

            # Wait for threads to finish
            stdout_thread.join()
            stderr_thread.join()

            # Store results for unified handling below
            final_returncode = returncode
            # Use extracted text parts, not raw JSON stream
            final_stdout = "".join(response_text_parts)
            final_stderr = "".join(stderr_chunks)

        except FileNotFoundError as e:
            logger.error("Claude CLI not found in PATH")
            debug_json_logger.close()
            raise ProviderError("Claude CLI not found. Is 'claude' in PATH?") from e

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        if final_returncode != 0:
            exit_status = ExitStatus.from_code(final_returncode)
            stderr_content = final_stderr or ""
            stderr_truncated = (
                stderr_content[:STDERR_TRUNCATE_LENGTH] if stderr_content else "(empty)"
            )

            logger.error(
                "Claude CLI failed: exit_code=%d, status=%s, model=%s, stderr=%s",
                final_returncode,
                exit_status.name,
                effective_model,
                stderr_truncated,
            )

            # Build human-readable message based on exit status
            # All messages include exit code per AC2 format requirement
            if exit_status == ExitStatus.SIGNAL:
                signal_num = ExitStatus.get_signal_number(final_returncode)
                message = (
                    f"Claude CLI failed with exit code {final_returncode} "
                    f"(signal {signal_num}): {stderr_truncated}"
                )
            elif exit_status == ExitStatus.NOT_FOUND:
                message = (
                    f"Claude CLI failed with exit code {final_returncode} "
                    f"(command not found - check PATH): {stderr_truncated}"
                )
            elif exit_status == ExitStatus.CANNOT_EXECUTE:
                message = (
                    f"Claude CLI failed with exit code {final_returncode} "
                    f"(permission denied): {stderr_truncated}"
                )
            else:
                message = f"Claude CLI failed with exit code {final_returncode}: {stderr_truncated}"

            debug_json_logger.close()
            raise ProviderExitCodeError(
                message,
                exit_code=final_returncode,
                exit_status=exit_status,
                stderr=stderr_content,
                stdout=final_stdout,  # Preserve output even on failure
                command=tuple(command),
            )

        # Log if replacement characters found in output (AC2, AC8)
        # Only scan if debug logging is enabled (performance optimization)
        if logger.isEnabledFor(logging.DEBUG):
            replacement_char = "\ufffd"
            stdout_has_replacement = replacement_char in final_stdout
            stderr_has_replacement = replacement_char in final_stderr
            if stdout_has_replacement or stderr_has_replacement:
                logger.debug(
                    "Encoding replacements in output: stdout=%s, stderr=%s",
                    stdout_has_replacement,
                    stderr_has_replacement,
                )

        logger.info(
            "Claude CLI completed: duration=%dms, exit_code=%d",
            duration_ms,
            final_returncode,
        )

        # Extract provider session_id before closing logger
        provider_session_id = debug_json_logger.provider_session_id

        # Close debug logger on success
        debug_json_logger.close()

        return ProviderResult(
            stdout=final_stdout,
            stderr=final_stderr,
            exit_code=final_returncode,
            duration_ms=duration_ms,
            model=effective_model,
            command=tuple(command),
            provider_session_id=provider_session_id,
        )

    def parse_output(self, result: ProviderResult) -> str:
        r"""Extract response text from Claude CLI output.

        Claude Code with --print flag returns plain text directly to stdout.
        No JSON parsing is needed - the response is the raw stdout with
        leading/trailing whitespace stripped.

        Args:
            result: ProviderResult from invoke() containing raw output.

        Returns:
            Extracted response text with whitespace stripped.
            Empty string if stdout is empty.

        Example:
            >>> result = ProviderResult(stdout="  Hello world  \n", ...)
            >>> provider.parse_output(result)
            'Hello world'

        """
        return result.stdout.strip()

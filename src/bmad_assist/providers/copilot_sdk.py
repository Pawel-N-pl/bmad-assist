"""GitHub Copilot SDK-based provider implementation.

This module implements the CopilotSDKProvider class - an alternative Copilot
integration for bmad-assist using the official github-copilot-sdk package.
Instead of shelling out to the Copilot CLI via subprocess, this provider uses
the SDK's JSON-RPC protocol for programmatic control.

Benefits over subprocess-based CopilotProvider:
- Native async/await support via JSON-RPC
- Streaming events for real-time progress
- Session lifecycle management (create/destroy)
- Proper error propagation instead of exit code parsing
- No command-line length limits (prompts sent via JSON-RPC)

Key Design Decision: NO FALLBACK
- If SDK fails, the operation fails immediately
- No silent fallback to subprocess - errors must be visible
- Subprocess provider only used when explicitly requested via config

Example:
    >>> from bmad_assist.providers import CopilotSDKProvider
    >>> provider = CopilotSDKProvider()
    >>> result = provider.invoke("Review this code", model="claude-opus-4.6")
    >>> response = provider.parse_output(result)

"""

import asyncio
import logging
import os
import threading
import time
from pathlib import Path

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderTimeoutError,
)
from bmad_assist.providers.base import (
    BaseProvider,
    ProviderResult,
    format_tag,
    is_full_stream,
    should_print_progress,
    validate_settings_file,
    write_progress,
)

logger = logging.getLogger(__name__)

# Default timeout in seconds (5 minutes)
DEFAULT_TIMEOUT: int = 300


class CopilotSDKProvider(BaseProvider):
    """GitHub Copilot SDK-based provider implementation.

    Uses the official github-copilot-sdk package for native async JSON-RPC
    communication with GitHub Copilot CLI, replacing subprocess invocation.

    This provider accepts any model name — model validation is delegated
    to the Copilot CLI server.

    Thread Safety:
        Each invoke() call creates its own CopilotClient and session.
        Multiple invoke() calls can run concurrently without interference.

    Example:
        >>> provider = CopilotSDKProvider()
        >>> result = provider.invoke("Hello", model="claude-opus-4.6", timeout=60)
        >>> print(provider.parse_output(result))

    """

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider.

        Returns:
            The string "copilot-sdk" as the provider identifier.

        """
        return "copilot-sdk"

    @property
    def default_model(self) -> str | None:
        """Return default model when none specified.

        Returns:
            The string "claude-sonnet-4.5" as the default model.

        """
        return "claude-sonnet-4.5"

    def supports_model(self, model: str) -> bool:
        """Check if this provider supports the given model.

        Args:
            model: Model identifier to check.

        Returns:
            Always True - model validation is delegated to Copilot CLI.

        """
        return True

    @staticmethod
    def _estimate_tokens(chars: int) -> int:
        """Estimate token count from character count (~4 chars/token)."""
        return max(1, chars // 4)

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

    async def _invoke_async(
        self,
        prompt: str,
        model: str,
        cwd: Path | None,
        timeout: int,
        color_index: int | None = None,
        display_model: str | None = None,
    ) -> str:
        """Execute SDK query asynchronously using CopilotClient.

        Internal async helper that performs the actual SDK call. Creates a
        CopilotClient, starts a session with the specified model, sends the
        prompt, and collects the response via event streaming.

        Args:
            prompt: The prompt text to send.
            model: Model identifier to use.
            cwd: Working directory for the CLI process.
            timeout: Timeout in seconds for the entire operation.
            color_index: Color index for progress output.
            display_model: Display name for the model (used in logs).

        Returns:
            Response text extracted from assistant messages.

        Raises:
            ProviderError: If SDK is not installed or communication fails.
            ProviderTimeoutError: If the operation exceeds the timeout.

        """
        try:
            from copilot import CopilotClient
        except ImportError as e:
            raise ProviderError(
                "github-copilot-sdk is not installed. "
                "Install it with: pip install github-copilot-sdk"
            ) from e

        shown_model = display_model or model
        input_tokens = self._estimate_tokens(len(prompt))
        logger.info(
            "Copilot SDK invoking: model=%s, input=~%d tokens (%d chars), cwd=%s",
            shown_model,
            input_tokens,
            len(prompt),
            cwd,
        )

        # Resolve CLI path from env or let SDK discover
        cli_path = os.environ.get("COPILOT_CLI_PATH")

        client_opts: dict[str, object] = {
            "log_level": "warning",
            "auto_start": True,
            "auto_restart": False,
        }
        if cli_path:
            client_opts["cli_path"] = cli_path
            logger.info("SDK using override CLI: %s", cli_path)
        if cwd:
            client_opts["cwd"] = str(cwd)

        client = CopilotClient(client_opts)
        response_parts: list[str] = []

        try:
            await asyncio.wait_for(client.start(), timeout=30)
            logger.debug("CopilotClient started")

            session_config: dict[str, object] = {
                "model": model,
                "infinite_sessions": {"enabled": False},
            }
            session = await asyncio.wait_for(
                client.create_session(session_config),
                timeout=30,
            )
            logger.debug("Session created")

            # Event collector
            done = asyncio.Event()

            def on_event(event: object) -> None:
                event_type = getattr(event, "type", None)
                if event_type is None:
                    return

                type_value = event_type.value if hasattr(event_type, "value") else str(event_type)

                if type_value == "assistant.message":
                    content = getattr(getattr(event, "data", None), "content", "")
                    if content:
                        response_parts.append(content)
                        if should_print_progress():
                            tag = format_tag("OUT", color_index)
                            preview = content[:200] + "..." if len(content) > 200 else content
                            if is_full_stream():
                                write_progress(f"{tag} {content.rstrip()}")
                            else:
                                write_progress(f"{tag} {preview.rstrip()}")

                elif type_value == "assistant.message_delta":
                    delta = getattr(getattr(event, "data", None), "delta_content", "")
                    if delta and should_print_progress() and is_full_stream():
                        tag = format_tag("STREAM", color_index)
                        write_progress(f"{tag} {delta}")

                elif type_value == "session.idle":
                    done.set()

            session.on(on_event)

            if should_print_progress():
                tag = format_tag("START", color_index)
                write_progress(f"{tag} Invoking Copilot SDK (model={shown_model})...")

            await session.send({"prompt": prompt})

            # Wait for session.idle with timeout
            try:
                await asyncio.wait_for(done.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                raise ProviderTimeoutError(
                    f"Copilot SDK timeout after {timeout}s",
                    partial_result=ProviderResult(
                        stdout="\n".join(response_parts),
                        stderr="",
                        exit_code=-1,
                        duration_ms=0,
                        model=model,
                        command=("copilot-sdk",),
                    ),
                ) from None

            await session.destroy()

        finally:
            try:
                await asyncio.wait_for(client.stop(), timeout=5)
            except Exception:
                logger.debug("Client stop timeout/error (non-fatal)")

        result = "\n".join(response_parts)
        if not result.strip():
            raise ProviderError(
                f"Copilot SDK returned empty response for model {model}"
            )

        return result

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
        """Execute Copilot SDK with the given prompt.

        Synchronous wrapper around the async SDK call. Creates an event loop
        if one is not running, otherwise uses asyncio.run().

        Args:
            prompt: The prompt text to send to Copilot.
            model: Model to use. If None, uses default_model.
            timeout: Timeout in seconds. Must be positive (>= 1) if specified.
            settings_file: Path to settings file (validated but unused by SDK).
            cwd: Working directory for Copilot CLI.
            disable_tools: Ignored by this provider.
            allowed_tools: Ignored by this provider.
            no_cache: Ignored by this provider.
            color_index: Color index for terminal output differentiation.
            display_model: Display name for the model (used in logs).
            thinking: Ignored by this provider.
            cancel_token: Ignored by this provider.
            reasoning_effort: Ignored by this provider.

        Returns:
            ProviderResult containing response text, timing, and metadata.

        Raises:
            ValueError: If timeout is not positive (<=0).
            ProviderError: If SDK execution fails.
            ProviderTimeoutError: If execution exceeds timeout.

        """
        _ = disable_tools, allowed_tools, no_cache, thinking, cancel_token, reasoning_effort

        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        effective_model = model or self.default_model or "gpt-4o"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        # Validate settings (informational — SDK doesn't use settings files)
        validated_settings = self._resolve_settings(settings_file, effective_model)
        if validated_settings is not None:
            logger.debug(
                "Settings file validated but not passed to Copilot SDK: %s",
                validated_settings,
            )

        logger.debug(
            "Invoking Copilot SDK: model=%s, timeout=%ds, prompt_len=%d, cwd=%s",
            effective_model,
            effective_timeout,
            len(prompt),
            cwd,
        )

        start_time = time.perf_counter()
        original_command: tuple[str, ...] = ("copilot-sdk", "--model", effective_model)

        try:
            # Run async SDK call — handle event loop lifecycle
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Already in an async context — run in a new thread to avoid
                # blocking the event loop.
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self._invoke_async(
                            prompt=prompt,
                            model=effective_model,
                            cwd=cwd,
                            timeout=effective_timeout,
                            color_index=color_index,
                            display_model=display_model,
                        ),
                    )
                    response_text = future.result(timeout=effective_timeout + 30)
            else:
                response_text = asyncio.run(
                    self._invoke_async(
                        prompt=prompt,
                        model=effective_model,
                        cwd=cwd,
                        timeout=effective_timeout,
                        color_index=color_index,
                        display_model=display_model,
                    ),
                )

        except ProviderTimeoutError:
            raise
        except ProviderError:
            raise
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            raise ProviderError(
                f"Copilot SDK error after {duration_ms}ms: {e}"
            ) from e

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        logger.info(
            "Copilot SDK completed: duration=%dms, text_len=%d",
            duration_ms,
            len(response_text),
        )

        return ProviderResult(
            stdout=response_text,
            stderr="",
            exit_code=0,
            duration_ms=duration_ms,
            model=effective_model,
            command=original_command,
        )

    def parse_output(self, result: ProviderResult) -> str:
        """Extract response text from Copilot SDK output.

        Args:
            result: ProviderResult from invoke() containing response text.

        Returns:
            Extracted response text with whitespace stripped.

        """
        return result.stdout.strip()

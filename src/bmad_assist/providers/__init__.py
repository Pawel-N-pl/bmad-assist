"""CLI provider integration module.

Provides the abstract base class and data structures for CLI provider
implementations. All providers (Claude Code, Codex, Gemini CLI, OpenCode, Amp,
Cursor Agent, Copilot) must implement the BaseProvider interface.

Provider Registry:
    - ClaudeSDKProvider: PRIMARY Claude integration using claude-agent-sdk (native async)
    - ClaudeSubprocessProvider: Subprocess-based, for benchmarking only
    - ClaudeProvider: Alias for ClaudeSDKProvider (default)
    - CodexProvider: Codex CLI subprocess provider for Multi-LLM validation
    - GeminiProvider: Gemini CLI subprocess provider for Multi-LLM validation
    - OpenCodeProvider: OpenCode CLI subprocess provider for Multi-LLM validation
    - AmpProvider: Amp CLI (Sourcegraph) subprocess provider for Multi-LLM validation
    - CursorAgentProvider: Cursor Agent CLI subprocess provider for Multi-LLM validation
    - CopilotProvider: GitHub Copilot CLI subprocess provider for Multi-LLM validation

Registry Functions:
    - get_provider(): Get provider instance by name
    - list_providers(): List all registered provider names
    - is_valid_provider(): Check if provider name is registered
    - register_provider(): Register custom provider
    - normalize_model_name(): Convert config model names to CLI format
    - denormalize_model_name(): Convert CLI model names to config format

Settings Loading:
    Two helper functions are provided for loading provider settings files:
    - resolve_settings_file(): Resolves paths from config (relative, tilde, absolute)
    - validate_settings_file(): Validates file exists and logs warnings if missing

Example:
    >>> from bmad_assist.providers import BaseProvider, ProviderResult, ExitStatus
    >>> from bmad_assist.providers import ClaudeProvider  # Alias for ClaudeSDKProvider
    >>> from bmad_assist.providers import ClaudeSDKProvider, ClaudeSubprocessProvider
    >>> from bmad_assist.providers import CodexProvider, GeminiProvider
    >>> from bmad_assist.providers import OpenCodeProvider, AmpProvider
    >>> from bmad_assist.providers import CursorAgentProvider, CopilotProvider
    >>> from bmad_assist.providers import get_provider, list_providers
    >>> from bmad_assist.providers import resolve_settings_file, validate_settings_file
    >>> from bmad_assist.core.exceptions import ProviderError, ProviderExitCodeError

NOTE: This module uses lazy loading for heavy provider imports (ClaudeSDKProvider)
to avoid slow startup times. The claude_agent_sdk package pulls in mcp, scipy,
and nltk which add ~1.5s to import time.

"""

from typing import TYPE_CHECKING

# Light imports - these are fast and always needed
from .base import (
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    TRANSIENT_ERROR_PATTERNS,
    BaseProvider,
    ExitStatus,
    ProviderResult,
    calculate_retry_delay,
    is_transient_error,
    read_stream_lines,
    resolve_settings_file,
    start_stream_reader_threads,
    validate_settings_file,
)
from .registry import (
    denormalize_model_name,
    get_provider,
    is_valid_provider,
    list_providers,
    normalize_model_name,
    register_provider,
)

# Type hints only - no runtime import
if TYPE_CHECKING:
    from .amp import AmpProvider as AmpProvider
    from .claude import ClaudeSubprocessProvider as ClaudeSubprocessProvider
    from .claude_sdk import ClaudeSDKProvider as ClaudeSDKProvider
    from .codex import CodexProvider as CodexProvider
    from .copilot import CopilotProvider as CopilotProvider
    from .cursor_agent import CursorAgentProvider as CursorAgentProvider
    from .gemini import GeminiProvider as GeminiProvider
    from .kimi import KimiProvider as KimiProvider
    from .opencode import OpenCodeProvider as OpenCodeProvider

    ClaudeProvider = ClaudeSDKProvider

__all__ = [
    "AmpProvider",
    "BaseProvider",
    "ClaudeProvider",  # Alias for ClaudeSDKProvider
    "ClaudeSDKProvider",
    "ClaudeSubprocessProvider",  # Deprecated: benchmarking only
    "CodexProvider",
    "CopilotProvider",
    "CursorAgentProvider",
    "ExitStatus",
    "GeminiProvider",
    "KimiProvider",
    "OpenCodeProvider",
    "ProviderResult",
    # Registry functions
    "denormalize_model_name",
    "get_provider",
    "is_valid_provider",
    "list_providers",
    "normalize_model_name",
    "register_provider",
    # Settings helpers
    "resolve_settings_file",
    "validate_settings_file",
    # Retry/stream helpers (shared by copilot.py, cursor_agent.py)
    "MAX_RETRIES",
    "RETRY_BASE_DELAY",
    "RETRY_MAX_DELAY",
    "TRANSIENT_ERROR_PATTERNS",
    "calculate_retry_delay",
    "is_transient_error",
    "read_stream_lines",
    "start_stream_reader_threads",
]

# Lazy loading for heavy provider imports
# ClaudeSDKProvider pulls in claude_agent_sdk -> mcp -> scipy/nltk (~1.5s)
_lazy_imports = {
    "AmpProvider": ".amp",
    "ClaudeSubprocessProvider": ".claude",
    "ClaudeSDKProvider": ".claude_sdk",
    "ClaudeProvider": ".claude_sdk",  # Alias
    "CodexProvider": ".codex",
    "CopilotProvider": ".copilot",
    "CursorAgentProvider": ".cursor_agent",
    "GeminiProvider": ".gemini",
    "KimiProvider": ".kimi",
    "OpenCodeProvider": ".opencode",
}


def __getattr__(name: str):
    """Lazy load provider classes on first access."""
    if name in _lazy_imports:
        import importlib

        module = importlib.import_module(_lazy_imports[name], __package__)
        # ClaudeProvider is an alias for ClaudeSDKProvider
        if name == "ClaudeProvider":
            return getattr(module, "ClaudeSDKProvider")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

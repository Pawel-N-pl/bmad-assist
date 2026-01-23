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

"""

from .amp import AmpProvider
from .base import (
    BaseProvider,
    ExitStatus,
    ProviderResult,
    resolve_settings_file,
    validate_settings_file,
)
from .claude import ClaudeSubprocessProvider
from .claude_sdk import ClaudeSDKProvider
from .codex import CodexProvider
from .copilot import CopilotProvider
from .cursor_agent import CursorAgentProvider
from .gemini import GeminiProvider
from .opencode import OpenCodeProvider
from .registry import (
    denormalize_model_name,
    get_provider,
    is_valid_provider,
    list_providers,
    normalize_model_name,
    register_provider,
)

# ClaudeProvider is an alias for ClaudeSDKProvider (primary implementation)
# Use ClaudeSubprocessProvider explicitly for benchmarking only
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
]

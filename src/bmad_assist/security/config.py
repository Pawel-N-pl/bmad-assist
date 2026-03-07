"""Configuration for Security Review Agent module.

Provides Pydantic configuration models for the security agent,
including provider override and detection settings.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SecurityAgentProviderConfig(BaseModel):
    """Provider configuration for Security Agent LLM calls.

    If specified in security_agent.provider_config, overrides master provider.
    All fields optional — None means use master fallback.

    Attributes:
        provider: Provider name (e.g., "claude-subprocess", "gemini").
        model: Model identifier for CLI invocation.
        model_name: Display name for the model in logs/reports.
        settings: Optional path to provider settings JSON file.
        thinking: Enable thinking mode for supported providers.
        reasoning_effort: Reasoning effort level for supported providers.

    """

    model_config = ConfigDict(frozen=True)

    provider: str = Field(
        ...,
        description="Provider name: claude-subprocess, claude-sdk, gemini, kimi, etc.",
    )
    model: str = Field(
        ...,
        description="Model identifier: haiku, sonnet, gemini-2.5-flash, etc.",
    )
    model_name: str | None = Field(
        None,
        description="Display name for model (used in logs/reports instead of model)",
    )
    settings: str | None = Field(
        None,
        description="Path to provider settings JSON (tilde expanded)",
    )
    thinking: bool = Field(
        False,
        description="Enable thinking mode for supported providers",
    )
    reasoning_effort: str | None = Field(
        None,
        description="Reasoning effort level (e.g., 'low', 'medium', 'high')",
    )

    @property
    def display_model(self) -> str:
        """Return model name for display (model_name if set, else model)."""
        return self.model_name or self.model

    @property
    def settings_path(self) -> Path | None:
        """Return expanded settings path, or None if not set."""
        if self.settings is None:
            return None
        return Path(self.settings).expanduser()


class SecurityAgentConfig(BaseModel):
    """Configuration for the Security Review Agent.

    This configuration controls:
    - Master enable/disable switch (disabled by default, opt-in)
    - Provider override (falls back to master when None)
    - Language override for tech-stack detection
    - Finding cap for synthesis prompt

    Uses default_factory in root Config so it's ALWAYS present (never None).
    This avoids the "None = enabled" confusion from DeepVerifyConfig.

    Attributes:
        enabled: Master enable/disable switch (False by default, opt-in).
        provider_config: Provider override. None means use master provider.
        languages: Override auto-detection with explicit language list.
        max_findings: Maximum findings to include in synthesis prompt.

    Example:
        >>> config = SecurityAgentConfig()
        >>> config.enabled
        False
        >>> config.provider_config is None
        True

    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=False,
        description="Master enable/disable switch for Security Agent (opt-in)",
    )
    provider_config: SecurityAgentProviderConfig | None = Field(
        default=None,
        description="Provider override for Security Agent. If None, uses master provider.",
    )
    languages: list[str] | None = Field(
        default=None,
        description="Override auto-detection with explicit language list (e.g., ['go', 'python'])",
    )
    max_findings: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Maximum findings to include in synthesis prompt",
    )
    retries: int | None = Field(
        default=None,
        ge=0,
        description="Retry provider invocation on timeout (None=no retry, 0=infinite, N=specific count)",
    )

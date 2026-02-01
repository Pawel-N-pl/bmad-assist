"""Configuration generator with interactive questionnaire.

This module provides interactive config generation via questionary prompts
with arrow-key navigation. When bmad-assist runs without a config file,
this wizard guides users through creating a valid bmad-assist.yaml.

Features:
- Scrollable provider/model selection with arrow keys
- Multi-validator add/remove loop
- Optional helper provider configuration
- CI/non-interactive environment detection
- Atomic file writes
- Ctrl+C handling at every step

Usage:
    from bmad_assist.core.config_generator import run_config_wizard

    # Run wizard and get path to generated config
    config_path = run_config_wizard(project_path)
"""

import contextlib
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final, TypeVar

import questionary
import typer
import yaml
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)

# Default config filename (same as PROJECT_CONFIG_NAME in config.py)
CONFIG_FILENAME: Final[str] = "bmad-assist.yaml"

# Type variable for _check_cancelled
T = TypeVar("T")

# Provider and model definitions for wizard
# Alphabetically ordered for consistent display
# Note: "claude" SDK provider is excluded (incomplete implementation)
# Note: "claude-subprocess" is the primary Claude provider for bmad-assist
PROVIDER_MODELS: Final[dict[str, dict[str, Any]]] = {
    "amp": {
        "display": "Amp (Sourcegraph)",
        "models": ["smart"],
        "default": "smart",
    },
    "claude-subprocess": {
        "display": "Claude (Anthropic)",
        "models": ["opus", "sonnet", "haiku"],
        "default": "opus",
    },
    "codex": {
        "display": "Codex (OpenAI)",
        "models": ["o3", "o3-mini", "gpt-4o"],
        "default": "o3-mini",
    },
    "copilot": {
        "display": "GitHub Copilot",
        "models": ["gpt-4o", "claude-haiku-4.5"],
        "default": "gpt-4o",
    },
    "cursor-agent": {
        "display": "Cursor Agent",
        "models": ["auto", "claude-sonnet-4"],
        "default": "auto",
    },
    "gemini": {
        "display": "Gemini (Google)",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-flash-preview"],
        "default": "gemini-2.5-flash",
    },
    "kimi": {
        "display": "Kimi (MoonshotAI)",
        "models": ["kimi-code/kimi-for-coding"],
        "default": "kimi-code/kimi-for-coding",
        "extras": {"thinking": True},
    },
    "opencode": {
        "display": "OpenCode",
        "models": ["opencode/claude-sonnet-4", "opencode/gemini-3-flash"],
        "default": "opencode/claude-sonnet-4",
    },
}

# Legacy mapping for backward compatibility with existing tests
AVAILABLE_PROVIDERS: Final[dict[str, dict[str, Any]]] = {
    "claude": {
        "display_name": "Claude (Anthropic)",
        "models": {
            "opus_4": "Claude Opus 4 (Most capable)",
            "sonnet_4": "Claude Sonnet 4 (Fast, capable)",
            "sonnet_3_5": "Claude Sonnet 3.5 (Balanced)",
            "haiku_3_5": "Claude Haiku 3.5 (Fast, economical)",
        },
        "default_model": "opus_4",
    },
    "codex": {
        "display_name": "Codex (OpenAI)",
        "models": {
            "gpt-4o": "GPT-4o (Multimodal)",
            "o3": "o3 (Advanced reasoning)",
        },
        "default_model": "gpt-4o",
    },
    "gemini": {
        "display_name": "Gemini (Google)",
        "models": {
            "gemini_2_5_pro": "Gemini 2.5 Pro",
            "gemini_2_5_flash": "Gemini 2.5 Flash (Fast)",
        },
        "default_model": "gemini_2_5_pro",
    },
}


def _is_interactive() -> bool:
    """Check if running in an interactive terminal environment.

    Returns False for:
    - Non-TTY stdin (piped input)
    - CI environments (GitHub Actions, GitLab CI, Jenkins, etc.)

    Returns:
        True if interactive terminal, False otherwise.

    """
    if not sys.stdin.isatty():
        return False

    # Check for CI environment variables
    ci_vars = [
        "CI",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "JENKINS_URL",
        "TRAVIS",
        "CIRCLECI",
        "BUILDKITE",
        "TF_BUILD",
        "CODEBUILD_BUILD_ID",
    ]
    return not any(os.environ.get(v) for v in ci_vars)


def _check_cancelled(result: T | None, console: Console) -> T:
    """Check if questionary returned None (Ctrl+C pressed).

    Args:
        result: Result from questionary.select/confirm.
        console: Rich console for output.

    Returns:
        The result if not None.

    Raises:
        typer.Exit: With code 130 if cancelled.

    """
    if result is None:
        console.print("[yellow]Cancelled[/yellow]")
        raise typer.Exit(130)
    return result


class ConfigGenerator:
    """Interactive configuration generator using questionary prompts.

    This class provides an interactive wizard for generating bmad-assist
    configuration files. It uses questionary for arrow-key navigation
    and Rich for formatted output.

    Attributes:
        console: Rich console for output.

    Example:
        >>> generator = ConfigGenerator()
        >>> config_path = generator.run(Path("./my-project"))
        >>> print(f"Config saved to {config_path}")

    """

    def __init__(self, console: Console | None = None) -> None:
        """Initialize ConfigGenerator.

        Args:
            console: Optional Rich console for output. Creates new if None.

        """
        self.console = console or Console()

    def run(self, project_path: Path) -> Path:
        """Run the configuration wizard.

        Guides user through provider/model selection, displays summary,
        confirms save, and writes the config file atomically.

        Args:
            project_path: Path to project directory where config will be saved.

        Returns:
            Path to the generated config file.

        Raises:
            typer.Exit: With code 1 for non-interactive, 130 for Ctrl+C.
            OSError: If config file cannot be written.

        """
        # Check for non-interactive environment first
        if not _is_interactive():
            self._display_non_interactive_fallback()
            raise typer.Exit(1)

        # Check if config already exists
        config_path = project_path / CONFIG_FILENAME
        if config_path.exists():
            overwrite = questionary.confirm(
                f"Config file already exists: {config_path}\nOverwrite?",
                default=False,
            ).ask()
            _check_cancelled(overwrite, self.console)
            if not overwrite:
                self.console.print("[yellow]Cancelled - existing config preserved[/yellow]")
                raise typer.Exit(130)

        self._display_welcome()

        # Prompt for master provider and model
        provider = self._select_provider("Select master provider")
        model = self._select_model(provider)

        # Prompt for multi-validators
        multi_validators = self._select_multi_validators()

        # Prompt for helper provider (optional)
        helper_config = self._select_helper_provider()

        # Build config dictionary
        config = self._build_config(provider, model, multi_validators, helper_config)

        # Display summary and confirm
        self._show_summary(config, config_path)

        save = questionary.confirm("Save this configuration?", default=True).ask()
        _check_cancelled(save, self.console)
        if not save:
            self.console.print("[yellow]Setup cancelled - no configuration saved[/yellow]")
            raise typer.Exit(0)  # User choice to not save is not an error

        # Save config with atomic write
        self._save_config(project_path, config)

        self.console.print(f"[green]✓[/green] Configuration saved to {config_path}")
        logger.info("Generated config at %s", config_path)

        return config_path

    def _display_welcome(self) -> None:
        """Display welcome message with Rich formatting."""
        self.console.print()
        self.console.print("[bold blue]bmad-assist Setup Wizard[/bold blue]")
        self.console.print("[dim]─────────────────────────[/dim]")
        self.console.print()
        self.console.print(
            "This wizard will create a [cyan]bmad-assist.yaml[/cyan] configuration file."
        )
        self.console.print("[dim]Use arrow keys to navigate, Enter to select.[/dim]")
        self.console.print()

    def _display_non_interactive_fallback(self) -> None:
        """Display message and example config for non-interactive environments."""
        self.console.print("[yellow]Non-interactive environment detected.[/yellow]")
        self.console.print()
        self.console.print("Create [cyan]bmad-assist.yaml[/cyan] manually with this template:")
        self.console.print()
        example = """# bmad-assist.yaml - minimal configuration
providers:
  master:
    provider: claude-subprocess
    model: opus
"""
        self.console.print(f"[dim]{example}[/dim]")
        self.console.print()
        self.console.print("Or run interactively: [cyan]bmad-assist config wizard[/cyan]")

    def _select_provider(self, message: str) -> str:
        """Select a provider using arrow-key navigation.

        Args:
            message: Prompt message to display.

        Returns:
            Selected provider key.

        """
        choices = [
            questionary.Choice(
                title=f"{info['display']}",
                value=key,
            )
            for key, info in PROVIDER_MODELS.items()
        ]

        result = questionary.select(
            message,
            choices=choices,
            default="claude-subprocess",
        ).ask()

        return _check_cancelled(result, self.console)

    def _select_model(self, provider: str) -> str:
        """Select a model for the chosen provider.

        Args:
            provider: Provider key.

        Returns:
            Selected model name.

        """
        provider_info = PROVIDER_MODELS[provider]
        models = provider_info["models"]
        default = provider_info["default"]

        choices = [questionary.Choice(title=model, value=model) for model in models]

        result = questionary.select(
            f"Select model for {provider_info['display']}",
            choices=choices,
            default=default,
        ).ask()

        return _check_cancelled(result, self.console)

    def _select_multi_validators(self) -> list[dict[str, Any]]:
        """Select multi-validators using add/remove loop.

        Returns:
            List of validator configurations (may be empty).

        """
        validators: list[dict[str, Any]] = []

        self.console.print()
        self.console.print("[bold]Multi-Validators[/bold] (optional)")
        self.console.print("[dim]Add validators for parallel code review/validation[/dim]")
        self.console.print()

        while True:
            # Build action choices
            action_choices = [
                questionary.Choice(title="Add validator", value="add"),
            ]
            if validators:
                action_choices.append(
                    questionary.Choice(
                        title=f"Remove validator ({len(validators)} configured)", value="remove"
                    )
                )
            action_choices.append(
                questionary.Choice(
                    title=f"Done ({len(validators)} validators)" if validators else "Skip",
                    value="done",
                )
            )

            action = questionary.select(
                "Multi-validator configuration:",
                choices=action_choices,
            ).ask()
            _check_cancelled(action, self.console)

            if action == "done":
                break
            elif action == "add":
                # Select provider
                provider = self._select_provider("Select validator provider")
                model = self._select_model(provider)

                validator_config: dict[str, Any] = {
                    "provider": provider,
                    "model": model,
                }

                # Add extras for specific providers
                if provider in PROVIDER_MODELS and "extras" in PROVIDER_MODELS[provider]:
                    validator_config.update(PROVIDER_MODELS[provider]["extras"])

                validators.append(validator_config)
                self.console.print(
                    f"[green]Added:[/green] {provider} / {model} "
                    f"[dim]({len(validators)} total)[/dim]"
                )
            elif action == "remove":
                # Build removal choices
                remove_choices = [
                    questionary.Choice(
                        title=f"{v['provider']} / {v['model']}",
                        value=i,
                    )
                    for i, v in enumerate(validators)
                ]
                remove_choices.append(questionary.Choice(title="Cancel", value=-1))

                remove_idx = questionary.select(
                    "Select validator to remove:",
                    choices=remove_choices,
                ).ask()
                _check_cancelled(remove_idx, self.console)

                if remove_idx >= 0:
                    removed = validators.pop(remove_idx)
                    self.console.print(
                        f"[yellow]Removed:[/yellow] {removed['provider']} / {removed['model']}"
                    )

        return validators

    def _select_helper_provider(self) -> dict[str, Any] | None:
        """Select optional helper provider.

        Returns:
            Helper configuration dict or None if skipped.

        """
        self.console.print()
        self.console.print("[bold]Helper Provider[/bold] (optional)")
        self.console.print("[dim]Used for LLM extraction and benchmarking[/dim]")
        self.console.print()

        configure = questionary.confirm(
            "Configure helper provider?",
            default=False,
        ).ask()
        _check_cancelled(configure, self.console)

        if not configure:
            return None

        provider = self._select_provider("Select helper provider")
        model = self._select_model(provider)

        helper_config: dict[str, Any] = {
            "provider": provider,
            "model": model,
        }

        # Add extras for specific providers
        if provider in PROVIDER_MODELS and "extras" in PROVIDER_MODELS[provider]:
            helper_config.update(PROVIDER_MODELS[provider]["extras"])

        return helper_config

    def _build_config(
        self,
        provider: str,
        model: str,
        multi_validators: list[dict[str, Any]],
        helper_config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build configuration dictionary with selected values.

        Args:
            provider: Master provider key.
            model: Master model name.
            multi_validators: List of validator configurations.
            helper_config: Helper provider configuration or None.

        Returns:
            Configuration dictionary ready for YAML serialization.

        """
        master_config: dict[str, Any] = {
            "provider": provider,
            "model": model,
        }

        # Add extras for specific providers (e.g., kimi.thinking)
        if provider in PROVIDER_MODELS and "extras" in PROVIDER_MODELS[provider]:
            master_config.update(PROVIDER_MODELS[provider]["extras"])

        providers_config: dict[str, Any] = {"master": master_config}

        # Only add multi section if validators were configured
        if multi_validators:
            providers_config["multi"] = multi_validators

        # Add helper if configured
        if helper_config:
            providers_config["helper"] = helper_config

        return {
            "providers": providers_config,
            "timeout": 300,
        }

    def _show_summary(self, config: dict[str, Any], config_path: Path) -> None:
        """Display configuration summary in a Rich table.

        Args:
            config: Configuration dictionary to summarize.
            config_path: Path where config will be saved.

        """
        self.console.print()

        table = Table(title="Configuration Summary", show_header=True)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        master = config["providers"]["master"]
        provider_display = PROVIDER_MODELS.get(master["provider"], {}).get(
            "display", master["provider"]
        )

        table.add_row("Master Provider", f"{master['provider']} ({provider_display})")
        table.add_row("Master Model", master["model"])

        # Multi-validators count
        multi = config["providers"].get("multi", [])
        if multi:
            table.add_row("Multi-Validators", f"{len(multi)} configured")
        else:
            table.add_row("Multi-Validators", "[dim]None[/dim]")

        # Helper provider
        helper = config["providers"].get("helper")
        if helper:
            helper_display = PROVIDER_MODELS.get(helper["provider"], {}).get(
                "display", helper["provider"]
            )
            table.add_row("Helper Provider", f"{helper['provider']} ({helper_display})")
        else:
            table.add_row("Helper Provider", "[dim]None[/dim]")

        table.add_row("Timeout", f"{config['timeout']} seconds")
        table.add_row("Output Path", str(config_path))

        self.console.print(table)
        self.console.print()

    def _display_summary(self, config: dict[str, Any]) -> None:
        """Display configuration summary in a Rich table (legacy method).

        Args:
            config: Configuration dictionary to summarize.

        """
        self.console.print()

        table = Table(title="Configuration Summary", show_header=True)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        master = config["providers"]["master"]
        provider_name = AVAILABLE_PROVIDERS.get(master["provider"], {}).get(
            "display_name", master["provider"]
        )

        table.add_row("Provider", f"{master['provider']} ({provider_name})")
        table.add_row("Model", master["model"])
        state_path = config.get("state_path", "{project}/.bmad-assist/state.yaml")
        table.add_row("State Path", state_path)
        table.add_row("Timeout", f"{config['timeout']} seconds")
        table.add_row("Config File", CONFIG_FILENAME)

        self.console.print(table)
        self.console.print()

    def _confirm_save(self) -> bool:
        """Ask user to confirm saving the configuration (legacy method).

        Returns:
            True if user confirms, False if user rejects.

        Raises:
            KeyboardInterrupt: If user presses Ctrl+C.
            EOFError: If no input available (piped input scenario).

        """
        from rich.prompt import Confirm

        return Confirm.ask(
            "[bold]Save this configuration?[/bold]",
            default=True,
        )

    def _prompt_provider(self) -> str:
        """Prompt user to select CLI provider (legacy method).

        Returns:
            Selected provider key (e.g., "claude", "codex", "gemini").

        Raises:
            KeyboardInterrupt: If user presses Ctrl+C.
            EOFError: If no input available (piped input scenario).

        """
        from rich.prompt import Prompt

        # Display provider options with descriptions
        self.console.print("[bold]Available CLI providers:[/bold]")
        for provider_key, provider_info in AVAILABLE_PROVIDERS.items():
            marker = "[green]→[/green]" if provider_key == "claude" else "  "
            display_name = provider_info["display_name"]
            self.console.print(f"  {marker} [cyan]{provider_key}[/cyan]: {display_name}")
        self.console.print()

        choices = list(AVAILABLE_PROVIDERS.keys())
        return Prompt.ask(
            "[bold]Select CLI provider[/bold]",
            choices=choices,
            default="claude",
        )

    def _prompt_model(self, provider: str) -> str:
        """Prompt user to select model for chosen provider (legacy method).

        Args:
            provider: Provider key (e.g., "claude").

        Returns:
            Selected model key (e.g., "opus_4").

        Raises:
            KeyboardInterrupt: If user presses Ctrl+C.
            EOFError: If no input available (piped input scenario).

        """
        from rich.prompt import Prompt

        provider_info = AVAILABLE_PROVIDERS[provider]
        models = provider_info["models"]
        default = provider_info["default_model"]

        # Display available models with descriptions
        self.console.print()
        self.console.print(f"[bold]Available models for {provider_info['display_name']}:[/bold]")
        for model_id, description in models.items():
            marker = "[green]→[/green]" if model_id == default else "  "
            self.console.print(f"  {marker} [cyan]{model_id}[/cyan]: {description}")
        self.console.print()

        return Prompt.ask(
            "[bold]Select model[/bold]",
            choices=list(models.keys()),
            default=default,
        )

    def _save_config(self, project_path: Path, config: dict[str, Any]) -> Path:
        """Save config to YAML file using atomic write pattern.

        Uses temp file + os.rename() per architecture.md NFR2 requirements
        to ensure no partial/corrupted config files can exist.

        Args:
            project_path: Directory where config file will be saved.
            config: Configuration dictionary to serialize.

        Returns:
            Path to the saved config file.

        Raises:
            OSError: If write fails (permission denied, disk full, etc.)

        """
        config_path = project_path / CONFIG_FILENAME

        # Build YAML content with header comments
        header = """# bmad-assist configuration
# Generated by interactive setup wizard
# See docs/architecture.md for full schema

"""
        content = header + yaml.dump(
            config,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

        # Atomic write: temp file in same directory + rename
        # Same directory ensures same filesystem for atomic rename
        fd: int | None = None
        tmp_path_str: str | None = None

        try:
            fd, tmp_path_str = tempfile.mkstemp(
                dir=project_path,
                prefix=".bmad-assist-",
                suffix=".yaml.tmp",
            )
            # Inner try/finally ensures fd is closed if fdopen fails
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    fd = None  # os.fdopen takes ownership
                    f.write(content)
            finally:
                # Close fd if fdopen failed before taking ownership
                if fd is not None:
                    os.close(fd)

            os.rename(tmp_path_str, config_path)
            logger.debug("Atomic write completed: %s -> %s", tmp_path_str, config_path)
            tmp_path_str = None  # Rename succeeded, no cleanup needed

        except Exception:
            # Clean up temp file on any failure
            if tmp_path_str is not None and os.path.exists(tmp_path_str):
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path_str)
            raise

        return config_path


def run_config_wizard(
    project_path: Path,
    console: Console | None = None,
) -> Path:
    """Run the configuration wizard and return path to generated config.

    This is the main entry point for config generation. It creates a
    ConfigGenerator instance and runs the interactive wizard.

    Args:
        project_path: Path to project directory.
        console: Optional Rich console for output.

    Returns:
        Path to the generated config file.

    Raises:
        typer.Exit: With code 1 for non-interactive/rejection, 130 for Ctrl+C.
        OSError: If config file cannot be written (permission denied, disk full).

    Example:
        >>> from pathlib import Path
        >>> from bmad_assist.core.config_generator import run_config_wizard
        >>> config_path = run_config_wizard(Path("./my-project"))

    """
    generator = ConfigGenerator(console)
    return generator.run(project_path)

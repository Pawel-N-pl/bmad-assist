"""Base handler class for phase execution.

Provides common functionality for all phase handlers:
- Provider invocation
- PhaseResult creation
- Optional timing tracking for benchmarking

DEPRECATION NOTICE:
-------------------
Handler YAML configuration files (~/.bmad-assist/handlers/*.yaml) are DEPRECATED.
The workflow compiler now handles prompt generation with bundled workflows.

The old YAML-based system is retained only for fallback compatibility but should
not be used for new development. All workflows should use the compiler system
with bundled workflow templates in src/bmad_assist/workflows/.

See: src/bmad_assist/compiler/workflow_discovery.py for the new discovery system.

"""

import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Template

from bmad_assist.core.config import Config, get_phase_timeout
from bmad_assist.core.config.models.providers import (
    MasterProviderConfig,
    MultiProviderConfig,
    get_phase_provider_config,
)
from bmad_assist.core.exceptions import ConfigError, ProviderExitCodeError
from bmad_assist.core.io import get_original_cwd
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.providers import get_provider
from bmad_assist.providers.base import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)

# Default handlers config directory
HANDLERS_CONFIG_DIR = Path.home() / ".bmad-assist" / "handlers"

# Patterns indicating Edit tool failures in provider output (Story 22.4 AC5)
# These patterns indicate the Edit tool couldn't find the old_string in the file
_EDIT_FAILURE_PATTERNS = (
    "0 occurrences found",
    "string not found",
    "no matches found",
    "old_string not found",
)


def check_for_edit_failures(stdout: str, target_hint: str | None = None) -> None:
    """Check provider output for Edit tool failures and log warnings.

    Story 22.4 AC5: Parse provider stdout for Edit failure patterns and
    emit warnings with guidance on using Read tool for fresh content.

    This is best-effort logging - synthesis continues regardless.

    Args:
        stdout: Provider stdout to scan.
        target_hint: Optional hint about target file (e.g., "story file").

    """
    stdout_lower = stdout.lower()
    for pattern in _EDIT_FAILURE_PATTERNS:
        if pattern.lower() in stdout_lower:
            # Try to extract context around the failure
            idx = stdout_lower.find(pattern.lower())
            start = max(0, idx - 100)
            end = min(len(stdout), idx + 200)
            context = stdout[start:end].strip()

            target_str = f" ({target_hint})" if target_hint else ""
            logger.warning(
                "Edit tool failure detected%s: '%s'\n"
                "Context: ...%s...\n"
                "GUIDANCE: Use Read tool to get current file content before Edit. "
                "Do NOT use embedded prompt content as old_string.",
                target_str,
                pattern,
                context[:200],
            )
            # Continue checking for other patterns - don't break, log all failures


@dataclass
class HandlerConfig:
    """Configuration loaded from handler YAML file.

    Attributes:
        prompt_template: Jinja2 template string for the prompt.
        provider_type: "master" or "multi" - which provider config to use.
        description: Human-readable description of the handler.

    """

    prompt_template: str
    provider_type: str = "master"
    description: str = ""


class BaseHandler(ABC):
    """Abstract base class for phase handlers.

    Handles common functionality:
    - Loading YAML config from ~/.bmad-assist/handlers/{phase_name}.yaml
    - Rendering Jinja2 prompt templates with state context
    - Invoking the appropriate provider
    - Creating PhaseResult from provider output

    Subclasses must implement:
    - phase_name: The name of the phase (used for config file lookup)
    - build_context(): Build template context from state

    """

    def __init__(self, config: Config, project_path: Path) -> None:
        """Initialize handler with config and project path.

        Args:
            config: Application configuration with provider settings.
            project_path: Path to the project root directory.

        """
        self.config = config
        self.project_path = project_path
        self._handler_config: HandlerConfig | None = None

    @property
    @abstractmethod
    def phase_name(self) -> str:
        """Return the phase name (e.g., 'create_story').

        Used to locate config file: ~/.bmad-assist/handlers/{phase_name}.yaml

        """
        ...

    @abstractmethod
    def build_context(self, state: State) -> dict[str, Any]:
        """Build Jinja2 template context from state.

        Args:
            state: Current loop state with epic/story information.

        Returns:
            Dictionary of variables available in the prompt template.

        """
        ...

    @property
    def track_timing(self) -> bool:
        """Whether to track timing for this handler.

        Override in subclass to enable timing tracking for benchmarking.
        Default is False.

        """
        return False

    @property
    def timing_workflow_id(self) -> str:
        """Workflow ID for timing records.

        Override in subclass to customize. Default is phase_name with
        underscores replaced by hyphens.

        """
        return self.phase_name.replace("_", "-")

    def get_config_path(self) -> Path:
        """Get path to handler's YAML config file."""
        return HANDLERS_CONFIG_DIR / f"{self.phase_name}.yaml"

    def _extract_story_num(self, story_id: str | None) -> str | None:
        """Extract story number from story ID.

        Args:
            story_id: Full story ID like "1.2" or None.

        Returns:
            Story number like "2", or None if invalid.

        """
        if story_id and "." in story_id:
            return story_id.split(".")[1]
        return None

    def _build_common_context(self, state: State) -> dict[str, Any]:
        """Build common context variables available to all handlers.

        Returns dict with:
        - epic_num: Current epic number (e.g., 1)
        - story_num: Story number within epic (e.g., "2" from "1.2")
        - story_id: Full story ID (e.g., "1.2")
        - project_path: Path to project root

        """
        return {
            "epic_num": state.current_epic,
            "story_num": self._extract_story_num(state.current_story),
            "story_id": state.current_story,
            "project_path": str(self.project_path),
        }

    def load_config(self) -> HandlerConfig:
        """Load handler configuration from YAML file.

        Returns:
            HandlerConfig with prompt template and settings.

        Raises:
            ConfigError: If config file is missing or invalid.

        """
        if self._handler_config is not None:
            return self._handler_config

        config_path = self.get_config_path()

        if not config_path.exists():
            raise ConfigError(
                f"Handler config not found: {config_path}\n\n"
                "Handler YAML files are deprecated - the compiler handles prompts now.\n"
                "If you see this error, the compiler is not loading the workflow.\n\n"
                "To fix:\n"
                "  1. Reinstall bmad-assist: pip install -e .\n"
                "  2. Or check workflow discovery: bmad-assist compile -w {workflow} --debug\n"
            )

        try:
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e

        if not data or "prompt_template" not in data:
            raise ConfigError(f"Handler config {config_path} must contain 'prompt_template'")

        self._handler_config = HandlerConfig(
            prompt_template=data["prompt_template"],
            provider_type=data.get("provider_type", "master"),
            description=data.get("description", ""),
        )

        return self._handler_config

    def render_prompt(self, state: State) -> str:
        """Render prompt using compiler with patching support.

        First tries to compile using the new BMAD compiler which supports:
        - Patched templates from global cache
        - Variable resolution
        - Optimized instructions

        Falls back to old handler YAML config if compilation fails
        (e.g., no compiler for this workflow, or compilation error).

        Set BMAD_FORCE_YAML=1 to skip compiler and use legacy YAML handlers.

        Args:
            state: Current loop state.

        Returns:
            Compiled or rendered prompt string ready for provider invocation.

        """
        import os

        # Allow forcing YAML fallback for testing/comparison
        if os.environ.get("BMAD_FORCE_YAML") == "1":
            logger.info("BMAD_FORCE_YAML=1, skipping compiler")
            return self._render_from_yaml(state)

        # Try new compiler first
        compiled_prompt = self._try_compile_workflow(state)
        if compiled_prompt is not None:
            return compiled_prompt

        # Fallback to old handler YAML config
        return self._render_from_yaml(state)

    def _try_compile_workflow(self, state: State) -> str | None:
        """Try to compile workflow using the new compiler.

        Args:
            state: Current loop state.

        Returns:
            Compiled prompt XML, or None if compilation not available/failed.

        """
        try:
            import os

            from bmad_assist.compiler import compile_workflow
            from bmad_assist.compiler.types import CompilerContext

            # Convert phase_name to workflow name (e.g., create_story -> create-story)
            workflow_name = self.phase_name.replace("_", "-")

            # Check for debug links mode
            links_only = os.environ.get("BMAD_DEBUG_LINKS") == "1"

            # Build resolved variables
            resolved_variables: dict[str, str | int | None] = {
                "epic_num": state.current_epic,
                "story_num": self._extract_story_num(state.current_story),
            }

            # Get configured paths
            paths = get_paths()

            # Build compiler context
            # Use get_original_cwd() to preserve original CWD when running as subprocess
            context = CompilerContext(
                project_root=self.project_path,
                output_folder=paths.implementation_artifacts,
                project_knowledge=paths.project_knowledge,
                cwd=get_original_cwd(),
                resolved_variables=resolved_variables,
                links_only=links_only,
            )

            # Compile workflow - returns CompiledWorkflow with full XML in context
            compiled = compile_workflow(workflow_name, context)

            # Add git intelligence if patch config specifies it
            prompt = compiled.context
            prompt = self._inject_git_intelligence(prompt, workflow_name, resolved_variables)

            logger.info(
                "Using compiled prompt for %s (tokens: ~%d)",
                workflow_name,
                compiled.token_estimate,
            )

            return prompt

        except Exception as e:
            logger.debug(
                "Compiler not available for %s, using handler YAML: %s",
                self.phase_name,
                e,
            )
            return None

    def _inject_git_intelligence(
        self,
        prompt: str,
        workflow_name: str,
        variables: dict[str, str | int | None],
    ) -> str:
        """Inject git intelligence into compiled prompt if configured.

        Loads patch config, extracts git intelligence at compile time,
        and injects it into the prompt. This prevents LLM from running
        expensive git archaeology at runtime.

        Args:
            prompt: Compiled prompt XML.
            workflow_name: Workflow name (e.g., 'create-story').
            variables: Resolved variables for command substitution.

        Returns:
            Prompt with git intelligence injected, or original if not configured.

        """
        try:
            from bmad_assist.compiler.patching import (
                discover_patch,
                extract_git_intelligence,
                load_patch,
            )

            # Find patch file for this workflow
            # Use get_original_cwd() to find patches in main project when running as subprocess
            patch_path = discover_patch(workflow_name, self.project_path, cwd=get_original_cwd())
            if patch_path is None:
                return prompt

            # Load patch config
            patch = load_patch(patch_path)
            if patch.git_intelligence is None or not patch.git_intelligence.enabled:
                return prompt

            # Extract git intelligence
            git_content = extract_git_intelligence(
                patch.git_intelligence,
                self.project_path,
                variables,
            )

            if not git_content:
                return prompt

            # Inject git intelligence as a file embed inside <context> section
            # Priority: 1. <context> (compiled-workflow format)
            #           2. <workflow-context> (legacy format)
            #           3. After <compiled-workflow> tag
            #           4. Prepend (last resort)
            marker = patch.git_intelligence.embed_marker
            git_embed = f'<file id="git-intel" path="[{marker}]"><![CDATA[{git_content}]]></file>'

            if "<context>" in prompt and "</context>" in prompt:
                # Insert as first file in context section
                prompt = prompt.replace(
                    "<context>",
                    f"<context>\n{git_embed}",
                    1,  # Only replace first occurrence
                )
            elif "<workflow-context>" in prompt:
                # Legacy format - insert after workflow-context opening tag
                prompt = prompt.replace(
                    "<workflow-context>",
                    f"<workflow-context>\n{git_content}\n",
                )
            elif "<compiled-workflow>" in prompt:
                # After compiled-workflow tag but before other content
                prompt = prompt.replace(
                    "<compiled-workflow>",
                    f"<compiled-workflow>\n{git_content}\n",
                )
            else:
                # Last resort - prepend
                prompt = f"{git_content}\n\n{prompt}"

            logger.debug(
                "Injected git intelligence for %s (%d chars)",
                workflow_name,
                len(git_content),
            )

            return prompt

        except Exception as e:
            logger.debug("Git intelligence injection failed: %s", e)
            return prompt

    def _render_from_yaml(self, state: State) -> str:
        """Render prompt from old handler YAML config.

        Args:
            state: Current loop state.

        Returns:
            Rendered prompt string from Jinja2 template.

        """
        handler_config = self.load_config()
        context = self.build_context(state)

        template = Template(handler_config.prompt_template)
        return template.render(**context)

    def _get_provider_type(self) -> str:
        """Get provider type, defaulting to 'master' if no handler config exists.

        When using the new compiler system, handler YAML files don't exist.
        In that case, we default to 'master' provider since compiled workflows
        are always executed by the master LLM.

        Returns:
            Provider type: 'master', 'helper', or 'multi'.

        """
        config_path = self.get_config_path()
        if not config_path.exists():
            # No handler YAML = using compiler = master provider
            return "master"
        handler_config = self.load_config()
        return handler_config.provider_type

    def _get_phase_config(self) -> MasterProviderConfig | list[MultiProviderConfig]:
        """Get provider config for this phase using phase_models resolution.

        Uses get_phase_provider_config() which checks phase_models first,
        then falls back to global providers.master/multi.

        Returns:
            MasterProviderConfig for single-LLM phases,
            list[MultiProviderConfig] for multi-LLM phases.

        """
        return get_phase_provider_config(self.config, self.phase_name)

    def get_provider(self) -> BaseProvider:
        """Get the provider instance based on handler config.

        Uses phase_models if configured for this phase, otherwise
        falls back to global providers.

        Returns:
            Provider instance (master, helper, or first multi provider).

        """
        provider_type = self._get_provider_type()

        # Helper provider bypasses phase_models - always use global config
        if provider_type == "helper":
            if not self.config.providers.helper:
                raise ConfigError("Helper provider not configured")
            provider_name = self.config.providers.helper.provider
            return get_provider(provider_name)

        # Use phase_models resolution for master and multi
        phase_config = self._get_phase_config()

        if isinstance(phase_config, list):
            # Multi-LLM: BaseHandler uses first provider
            if not phase_config:
                raise ConfigError("No multi providers configured")
            provider_name = phase_config[0].provider
        else:
            # Single-LLM: use directly
            provider_name = phase_config.provider

        return get_provider(provider_name)

    def get_model(self) -> str | None:
        """Get the display model name for logging (prefers model_name over model).

        Uses phase_models if configured for this phase.
        """
        provider_type = self._get_provider_type()

        # Helper bypasses phase_models
        if provider_type == "helper":
            helper = self.config.providers.helper
            if helper:
                return helper.model_name or helper.model
            return None

        # Use phase_models resolution
        phase_config = self._get_phase_config()

        if isinstance(phase_config, list):
            # Multi-LLM: use first provider
            if not phase_config:
                return None
            return phase_config[0].model_name or phase_config[0].model
        else:
            # Single-LLM: use directly
            return phase_config.model_name or phase_config.model

    def get_cli_model(self) -> str | None:
        """Get the CLI model identifier for provider invocation (always model, not model_name).

        Uses phase_models if configured for this phase.
        """
        provider_type = self._get_provider_type()

        # Helper bypasses phase_models
        if provider_type == "helper":
            helper = self.config.providers.helper
            return helper.model if helper else None

        # Use phase_models resolution
        phase_config = self._get_phase_config()

        if isinstance(phase_config, list):
            # Multi-LLM: use first provider
            if not phase_config:
                return None
            return phase_config[0].model
        else:
            # Single-LLM: use directly
            return phase_config.model

    def invoke_provider(
        self, prompt: str, retry_timeout_minutes: int = 30, retry_delay: int = 60
    ) -> ProviderResult:
        """Invoke the provider with the given prompt, with automatic retry on failure.

        Retries continuously for up to retry_timeout_minutes when provider fails.
        This handles transient API issues, rate limits, or temporary outages.

        Args:
            prompt: Rendered prompt string.
            retry_timeout_minutes: Total time to keep retrying (default: 30 minutes).
            retry_delay: Seconds to wait between retries (default: 60).

        Returns:
            ProviderResult with stdout, stderr, exit_code, etc.

        Raises:
            ProviderExitCodeError: If all retry attempts within timeout fail.

        """
        provider = self.get_provider()
        display_model = self.get_model()  # For logging (prefers model_name)
        cli_model = self.get_cli_model()  # For actual CLI invocation (always model)
        timeout = get_phase_timeout(self.config, self.phase_name)

        # Resolve settings file from provider config (phase_models or global)
        settings_file = None
        provider_type = self._get_provider_type()

        # Helper bypasses phase_models
        if provider_type == "helper" and self.config.providers.helper:
            settings_file = self.config.providers.helper.settings_path
        else:
            # Use phase_models resolution for master and multi
            phase_config = self._get_phase_config()
            if isinstance(phase_config, list):
                # Multi-LLM: use first provider
                if phase_config:
                    settings_file = phase_config[0].settings_path
            else:
                # Single-LLM: use directly
                settings_file = phase_config.settings_path

        logger.info(
            "Invoking %s provider with model=%s, timeout=%s, cwd=%s",
            provider.provider_name,
            display_model,
            timeout,
            self.project_path,
        )
        logger.debug("Prompt length: %d chars", len(prompt))
        if settings_file:
            logger.debug("Using settings file: %s", settings_file)

        last_error: ProviderExitCodeError | None = None
        start_time = time.time()
        max_duration = retry_timeout_minutes * 60  # Convert to seconds
        attempt = 0
        current_delay = retry_delay

        while True:
            attempt += 1
            elapsed = time.time() - start_time
            remaining = max_duration - elapsed

            # Double delay every 10 attempts (exponential backoff)
            if attempt > 1 and (attempt - 1) % 10 == 0:
                current_delay *= 2
                logger.info(
                    "Increasing retry delay to %ds after %d attempts",
                    current_delay,
                    attempt - 1,
                )

            try:
                return provider.invoke(
                    prompt,
                    model=cli_model,
                    timeout=timeout,
                    settings_file=settings_file,
                    cwd=self.project_path,
                )
            except ProviderExitCodeError as e:
                last_error = e

                if remaining <= current_delay:
                    # No time for another retry
                    logger.error(
                        "Provider failed after %d attempts over %.1f minutes: %s",
                        attempt,
                        elapsed / 60,
                        str(e)[:200],
                    )
                    break

                remaining_mins = remaining / 60
                logger.warning(
                    "Provider failed (attempt %d, %.1f min remaining): %s. Retrying in %ds...",
                    attempt,
                    remaining_mins,
                    str(e)[:100],
                    current_delay,
                )
                time.sleep(current_delay)

        # All retries exhausted - re-raise the last error
        if last_error:
            raise last_error
        # Should never reach here, but satisfy type checker
        raise RuntimeError("Unexpected state: no error captured but loop exited")

    def execute(self, state: State) -> PhaseResult:
        """Execute the handler for the given state.

        This is the main entry point called by the dispatch system.
        If track_timing is True, saves timing record for benchmarking.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        from bmad_assist.core.io import save_prompt

        # Capture start time for timing tracking
        start_time = datetime.now(UTC) if self.track_timing else None

        try:
            # Load config and render prompt
            prompt = self.render_prompt(state)

            # Save prompt to .bmad-assist/prompts/ (atomic write, always saved)
            epic = state.current_epic or "unknown"
            story = state.current_story or "unknown"
            save_prompt(self.project_path, epic, story, self.phase_name, prompt)

            # Agent tracking
            from bmad_assist.core.tracking import track_agent_end, track_agent_start

            phase_config = self._get_phase_config()
            if isinstance(phase_config, list):
                _track_provider = phase_config[0].provider if phase_config else "unknown"
                _cfg = phase_config[0] if phase_config else None
                _track_model = (_cfg.model_name or _cfg.model) if _cfg else "unknown"
            else:
                _track_provider = phase_config.provider
                _track_model = phase_config.model_name or phase_config.model or "unknown"
            _track_cli = {
                "model": self.get_cli_model(),
                "timeout": get_phase_timeout(self.config, self.phase_name),
                "settings_file": getattr(phase_config, "settings_path", None)
                if not isinstance(phase_config, list)
                else (phase_config[0].settings_path if phase_config else None),
                "cwd": self.project_path,
            }
            _track_start = track_agent_start(
                self.project_path, epic, story, self.phase_name,
                _track_provider, _track_model, prompt,
                cli_params=_track_cli,
            )

            # Invoke provider
            result = self.invoke_provider(prompt)

            # Check for errors
            if result.exit_code != 0:
                error_msg = result.stderr or f"Provider exited with code {result.exit_code}"
                logger.warning(
                    "Provider returned non-zero exit code: %d, stderr: %s",
                    result.exit_code,
                    result.stderr[:500] if result.stderr else "(empty)",
                )
                phase_result = PhaseResult.fail(error_msg)
            else:
                # Success - return output
                phase_result = PhaseResult.ok(
                    {
                        "response": result.stdout,
                        "model": result.model,
                        "duration_ms": result.duration_ms,
                    }
                )

            # Agent tracking END
            track_agent_end(
                self.project_path, epic, story, self.phase_name,
                _track_provider, _track_model, prompt, _track_start,
                cli_params=_track_cli,
            )

            # Save timing if enabled and successful
            if start_time and phase_result.success and self.config.benchmarking.enabled:
                self._save_timing_record(
                    state=state,
                    start_time=start_time,
                    end_time=datetime.now(UTC),
                    output=result.stdout,
                )

            return phase_result

        except ConfigError as e:
            logger.error("Handler config error: %s", e)
            return PhaseResult.fail(str(e))
        except Exception as e:
            logger.error("Handler execution failed: %s", e, exc_info=True)
            return PhaseResult.fail(f"Handler error: {e}")

    def _save_timing_record(
        self,
        state: State,
        start_time: datetime,
        end_time: datetime,
        output: str,
    ) -> None:
        """Save timing record for benchmarking.

        Called by execute() when track_timing is True.

        """
        try:
            from bmad_assist.benchmarking.master_tracking import save_master_timing

            # Guard: epic must be set for timing
            if state.current_epic is None:
                logger.debug("Skipping timing: current_epic is None")
                return

            # Extract story number (handle string-based IDs from Epic 22 TD-001)
            story_num = 1
            if state.current_story and "." in state.current_story:
                story_part = state.current_story.split(".")[-1]
                try:
                    # Try to convert to int, but handle string-based IDs like "6a"
                    # Extract leading numeric portion: "6a" -> 6, "test" -> 1 (fallback)
                    numeric_match = re.match(r"(\d+)", story_part)
                    story_num = int(numeric_match.group(1)) if numeric_match else 1
                except (ValueError, AttributeError):
                    # Conversion failed, use default
                    story_num = 1

            # Get provider name (not the provider object)
            provider = self.get_provider()
            provider_name = provider.provider_name

            # Guard: model must be set for timing
            model = self.get_model()
            if model is None:
                logger.debug("Skipping timing: model is None")
                return

            # CRITICAL: Pass explicit benchmarks_base to avoid get_paths() singleton fallback
            # The singleton is initialized for CLI working directory, not target project
            from bmad_assist.benchmarking.storage import get_benchmark_base_dir

            benchmarks_base = get_benchmark_base_dir(self.project_path)

            save_master_timing(
                workflow_id=self.timing_workflow_id,
                epic_num=state.current_epic,
                story_num=story_num,
                story_title=f"Story {state.current_story}",
                provider=provider_name,
                model=model,
                start_time=start_time,
                end_time=end_time,
                output=output,
                project_path=self.project_path,
                benchmarks_base=benchmarks_base,
            )
        except Exception as e:
            logger.warning("Failed to save timing for %s: %s", self.timing_workflow_id, e)

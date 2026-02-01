"""StandaloneRunner for TEA workflow execution without loop/state.yaml.

This module provides the core runner class for executing TEA workflows
in standalone mode, designed for TEA Solo/Lite engagement models.

Story 25.13: TEA Standalone Runner & CLI.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator

from rich.console import Console

if TYPE_CHECKING:
    from bmad_assist.core.config import Config
    from bmad_assist.core.loop.types import PhaseResult
    from bmad_assist.core.state import State

logger = logging.getLogger(__name__)
console = Console()


def _print_tea_banner(workflow_id: str, project_name: str | None = None) -> None:
    """Print TEA workflow banner (like loop runner phase banners).

    Formats workflow ID into display-friendly format:
    - "framework" → "[TEA FRAMEWORK]"
    - "test-design" → "[TEA TEST DESIGN]"
    - "nfr-assess" → "[TEA NFR ASSESS]"

    Args:
        workflow_id: TEA workflow identifier (e.g., "framework", "ci").
        project_name: Optional project name to display.

    """
    try:
        display_name = workflow_id.upper().replace("-", " ")
        banner = f"[TEA {display_name}]"
        if project_name:
            banner += f" {project_name}"
        console.print(banner, style="bold bright_white")
    except Exception:
        # Fallback without Rich formatting
        display_name = workflow_id.upper().replace("-", " ")
        print(f"[TEA {display_name}]")


def _dispatch_tea_notification(
    workflow_id: str,
    project_name: str,
    duration_ms: int,
) -> None:
    """Dispatch notification for TEA workflow completion.

    Uses PHASE_COMPLETED event with workflow_id as phase name.
    Fire-and-forget: failures are logged but don't interrupt workflow.

    Args:
        workflow_id: TEA workflow identifier (e.g., "framework").
        project_name: Project name for payload.
        duration_ms: Workflow duration in milliseconds.

    """
    try:
        from bmad_assist.notifications.dispatcher import get_dispatcher
        from bmad_assist.notifications.events import EventType, PhaseCompletedPayload

        dispatcher = get_dispatcher()
        if dispatcher is None:
            logger.debug("No notification dispatcher configured, skipping")
            return

        # Create payload with TEA workflow info
        # Use "standalone" as epic, workflow_id as phase
        payload = PhaseCompletedPayload(
            project=project_name,
            epic="standalone",
            story=None,
            phase=f"TEA_{workflow_id.upper().replace('-', '_')}",
            next_phase=None,
            duration_ms=duration_ms,
        )

        # Dispatch async in sync context
        asyncio.run(dispatcher.dispatch(EventType.PHASE_COMPLETED, payload))
        logger.debug("Dispatched TEA notification for %s", workflow_id)

    except Exception as e:
        # Fire-and-forget - log but don't fail workflow
        logger.warning("Failed to dispatch TEA notification: %s", e)


class StandaloneRunner:
    """Execute TEA workflows standalone (without loop/state.yaml).

    Designed for TEA Solo/Lite engagement models where users want
    quick test setup or code analysis without full project initialization.

    Example:
        >>> runner = StandaloneRunner(Path("."))
        >>> result = runner.run_framework()
        >>> print(result["output_path"])
        ./_bmad-output/standalone/framework/framework-20260131T140000.md

    """

    from bmad_assist.testarch.engagement import STANDALONE_WORKFLOWS

    SUPPORTED_WORKFLOWS: set[str] = STANDALONE_WORKFLOWS

    def __init__(
        self,
        project_root: Path,
        output_dir: Path | None = None,
        evidence_output: Path | None = None,
        provider_name: str | None = None,
    ) -> None:
        """Initialize standalone runner.

        Args:
            project_root: Project directory for evidence collection.
            output_dir: Artifact output directory (default: ./_bmad-output/standalone/).
            evidence_output: Optional evidence storage path.
            provider_name: Optional provider override (default: claude-subprocess).

        """
        self.project_root = project_root.resolve()
        self.output_dir = (
            output_dir or project_root / "_bmad-output" / "standalone"
        ).resolve()
        self.evidence_output = evidence_output
        self.provider_name = provider_name or "claude-subprocess"

    def _create_standalone_config(
        self,
        testarch_overrides: dict[str, Any] | None = None,
    ) -> "Config":
        """Create minimal Config for standalone execution.

        Attempts to load existing bmad-assist.yaml for provider settings.
        Falls back to defaults if not found.

        Args:
            testarch_overrides: Optional overrides for TestarchConfig fields.
                Used to pass workflow-specific parameters (e.g., test_design_level).

        Returns:
            Config object suitable for standalone execution.

        """
        from bmad_assist.core.config import Config, load_config_with_project
        from bmad_assist.core.config.models.providers import (
            MasterProviderConfig,
            ProviderConfig,
        )
        from bmad_assist.core.exceptions import ConfigError
        from bmad_assist.testarch.config import TestarchConfig

        # Default testarch settings for standalone execution
        # CRITICAL: Always enforce solo mode and enable all workflows for standalone
        base_testarch: dict[str, Any] = {
            "engagement_model": "solo",
            "framework_mode": "auto",
            "ci_mode": "auto",
            "test_design_mode": "auto",
            "automate_mode": "on",
            "nfr_assess_mode": "on",
        }

        # Try to load existing config first
        config_path = self.project_root / "bmad-assist.yaml"
        if config_path.exists():
            try:
                config = load_config_with_project(project_path=self.project_root)
                logger.debug("Loaded existing config from %s", config_path)

                # CRITICAL: Apply provider override if specified
                # This ensures --provider flag works even when existing config exists
                provider_overrides: dict[str, Any] = {}
                if self.provider_name != "claude-subprocess":
                    provider_overrides["provider"] = self.provider_name

                # CRITICAL: Always enforce engagement_model="solo" for standalone
                existing_testarch = config.testarch.model_dump() if config.testarch else {}
                existing_testarch["engagement_model"] = "solo"

                # Apply testarch overrides (mode settings, level, etc.)
                if testarch_overrides:
                    existing_testarch.update(testarch_overrides)

                # Build update dict - apply provider override if needed
                update_dict: dict[str, Any] = {
                    "testarch": TestarchConfig(**existing_testarch)
                }
                if provider_overrides:
                    update_dict["providers"] = config.providers.model_copy(
                        update={"master": config.providers.master.model_copy(update=provider_overrides)}
                    )

                return config.model_copy(update=update_dict)
            except ConfigError as e:
                logger.debug(
                    "Failed to load existing config, using defaults: %s", e
                )
            except Exception as e:
                logger.debug(
                    "Unexpected error loading config, using defaults: %s", e
                )

        # Apply overrides to base testarch settings
        if testarch_overrides:
            base_testarch.update(testarch_overrides)

        # Create minimal config with defaults
        logger.debug(
            "Creating minimal standalone config with provider=%s",
            self.provider_name,
        )
        return Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(
                    provider=self.provider_name,
                    model="opus",
                ),
            ),
            testarch=TestarchConfig(**base_testarch),
        )

    def _create_standalone_state(self) -> "State":
        """Create minimal State for standalone execution.

        State is NOT persisted - exists only during workflow execution.
        Uses "standalone" as epic ID for identification in reports.

        Returns:
            State object suitable for handler execute() calls.

        """
        from bmad_assist.core.state import State

        return State(
            current_epic="standalone",
            current_story=None,
            current_phase=None,
            atdd_ran_in_epic=False,
            framework_ran_in_epic=False,
            ci_ran_in_epic=False,
            test_design_ran_in_epic=False,
            automate_ran_in_epic=False,
            nfr_assess_ran_in_epic=False,
            epic_setup_complete=False,
        )

    @contextmanager
    def _standalone_paths_context(self) -> Generator[None, None, None]:
        """Context manager for standalone paths initialization.

        Initializes paths for standalone execution, yields, then resets.
        This ensures standalone runs don't pollute global paths state.

        Note: _reset_paths() is used here for isolation (approved production use).

        """
        from bmad_assist.core.paths import _reset_paths, init_paths

        # Ensure docs directory exists (handlers expect it)
        docs_dir = self.project_root / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        paths_config = {
            "output_folder": str(self.output_dir),
            "planning_artifacts": str(docs_dir),
            "implementation_artifacts": str(self.output_dir),
            "project_knowledge": str(docs_dir),
        }

        init_paths(self.project_root, paths_config)
        try:
            yield
        finally:
            _reset_paths()

    def _execute_handler(
        self,
        handler_class: type,
        workflow_id: str,
        testarch_overrides: dict[str, Any] | None = None,
        extra_state_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a TEA handler in standalone mode.

        Args:
            handler_class: The handler class to instantiate and execute.
            workflow_id: Workflow identifier for logging and output naming.
            testarch_overrides: TestarchConfig field overrides for this workflow.
                Used to pass workflow parameters (e.g., test_design_level).
            extra_state_fields: Additional state fields to set before execution.
                Only valid State fields (e.g., framework_ran_in_epic) can be used.

        Returns:
            Dict with execution results: success, output_path, error, metrics.

        """
        # Print banner (like loop runner does for standard phases)
        project_name = self.project_root.name
        _print_tea_banner(workflow_id, project_name)

        logger.info("Executing standalone %s workflow", workflow_id)

        # Create config with workflow-specific overrides
        config = self._create_standalone_config(testarch_overrides)

        # Create fresh state for this execution
        state = self._create_standalone_state()

        # Apply extra state fields if provided (must be valid State fields)
        if extra_state_fields:
            for key, value in extra_state_fields.items():
                setattr(state, key, value)

        # Track timing for notifications
        start_time = time.monotonic()

        # Execute with paths context
        with self._standalone_paths_context():
            try:
                # Instantiate and execute handler
                handler = handler_class(config, self.project_root)
                result: PhaseResult = handler.execute(state)

                # Calculate duration
                duration_ms = int((time.monotonic() - start_time) * 1000)

                if result.success:
                    # Handlers store LLM output in "response" key
                    output_content = result.outputs.get("response", "")

                    # Check for skip result - handler may skip if already run
                    if not output_content and result.outputs.get("skipped"):
                        # Still dispatch notification for skipped workflows
                        _dispatch_tea_notification(
                            workflow_id, project_name, duration_ms
                        )
                        return {
                            "success": True,
                            "output_path": None,
                            "error": None,
                            "metrics": dict(result.outputs),
                        }

                    # Fallback to string representation if no response
                    if not output_content:
                        output_content = str(result.outputs)

                    # Save report
                    report_path = self._save_standalone_report(
                        workflow_id, output_content
                    )

                    # Dispatch completion notification
                    _dispatch_tea_notification(
                        workflow_id, project_name, duration_ms
                    )

                    return {
                        "success": True,
                        "output_path": report_path,
                        "error": None,
                        "metrics": dict(result.outputs),
                    }
                else:
                    # Dispatch notification even for failures
                    _dispatch_tea_notification(
                        workflow_id, project_name, duration_ms
                    )
                    return {
                        "success": False,
                        "output_path": None,
                        "error": result.error or "Unknown error",
                        "metrics": dict(result.outputs),
                    }

            except Exception as e:
                # Calculate duration even for exceptions
                duration_ms = int((time.monotonic() - start_time) * 1000)
                _dispatch_tea_notification(
                    workflow_id, project_name, duration_ms
                )
                logger.error("Standalone %s failed: %s", workflow_id, e)
                return {
                    "success": False,
                    "output_path": None,
                    "error": str(e),
                    "metrics": {},
                }

    def _save_standalone_report(
        self,
        workflow_id: str,
        content: str,
    ) -> Path:
        """Save workflow output as standalone report with atomic write.

        Output structure:
            {output_dir}/{workflow}/{workflow}-{timestamp}.md

        Example:
            _bmad-output/standalone/framework/framework-20260131T140000.md

        Args:
            workflow_id: Workflow identifier for directory and filename.
            content: Report content to save.

        Returns:
            Path to saved report file.

        """
        # Create workflow-specific output directory
        workflow_dir = self.output_dir / workflow_id
        workflow_dir.mkdir(parents=True, exist_ok=True)

        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        filename = f"{workflow_id}-{timestamp}.md"
        filepath = workflow_dir / filename

        # Atomic write: temp file -> rename
        fd, temp_path = tempfile.mkstemp(
            suffix=".md",
            prefix=f"{workflow_id}_",
            dir=str(workflow_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.rename(temp_path, filepath)
            logger.info("Standalone report saved: %s", filepath)
            return filepath
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def run_workflow(
        self,
        workflow_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a TEA workflow by ID (generic entry point).

        Args:
            workflow_id: Workflow identifier (framework, ci, test-design, automate, nfr-assess).
            **kwargs: Workflow-specific parameters.

        Returns:
            Dict with execution results: success, output_path, error, metrics.

        Raises:
            ValueError: If workflow_id is not supported.

        """
        if workflow_id not in self.SUPPORTED_WORKFLOWS:
            raise ValueError(
                f"Unsupported workflow: {workflow_id}. "
                f"Supported: {', '.join(sorted(self.SUPPORTED_WORKFLOWS))}"
            )

        # Check if TEA is enabled in project config
        config_path = self.project_root / "bmad-assist.yaml"
        if config_path.exists():
            from bmad_assist.core.config import load_config_with_project

            try:
                config = load_config_with_project(project_path=self.project_root)
                if config.testarch is not None and not config.testarch.enabled:
                    logger.warning("TEA is disabled (testarch.enabled=false)")
                    return {
                        "success": False,
                        "error": "TEA is disabled in config (testarch.enabled=false)",
                        "skipped": True,
                    }
            except Exception as e:
                logger.debug("Could not check testarch.enabled: %s", e)

        # Route to appropriate method
        method_map: dict[str, Any] = {
            "framework": self.run_framework,
            "ci": self.run_ci,
            "test-design": self.run_test_design,
            "automate": self.run_automate,
            "nfr-assess": self.run_nfr_assess,
        }

        return method_map[workflow_id](**kwargs)

    def run_framework(self, mode: str = "create") -> dict[str, Any]:
        """Run framework workflow standalone.

        Initializes test framework (Playwright/Cypress) configuration.

        Args:
            mode: Workflow mode - "create" (default), "validate", or "edit".

        Returns:
            Dict with execution results.

        """
        from bmad_assist.testarch.handlers import FrameworkHandler

        # Map CLI mode to TestarchConfig mode setting
        # "create" -> "on" (force execution), other modes pass through for handler checking
        testarch_overrides: dict[str, Any] = {"framework_mode": "on"} if mode == "create" else {"framework_mode": mode}
        return self._execute_handler(
            FrameworkHandler, "framework", testarch_overrides=testarch_overrides
        )

    def run_ci(
        self,
        ci_platform: str | None = None,
        mode: str = "create",
    ) -> dict[str, Any]:
        """Run CI workflow standalone.

        Creates CI pipeline configuration for detected or specified platform.

        Args:
            ci_platform: CI platform override (github|gitlab|circleci|auto).
                Passed via state field for handler to read.
            mode: Workflow mode - "create" (default), "validate", or "edit".

        Returns:
            Dict with execution results.

        """
        from bmad_assist.testarch.handlers import CIHandler

        # Map CLI mode to TestarchConfig mode setting
        testarch_overrides: dict[str, Any] = {"ci_mode": "on"} if mode == "create" else {"ci_mode": mode}

        # Pass ci_platform via extra_state_fields for handler access
        extra_state_fields: dict[str, Any] | None = None
        if ci_platform:
            extra_state_fields = {"ci_platform_override": ci_platform}

        return self._execute_handler(
            CIHandler, "ci",
            testarch_overrides=testarch_overrides,
            extra_state_fields=extra_state_fields,
        )

    def run_test_design(
        self,
        level: str = "system",
        mode: str = "create",
    ) -> dict[str, Any]:
        """Run test-design workflow standalone.

        Creates test design documents at system or epic level.

        Args:
            level: Design level - "system" for architecture docs, "epic" for per-epic.
            mode: Workflow mode - "create" (default), "validate", or "edit".

        Returns:
            Dict with execution results.

        """
        from bmad_assist.testarch.handlers import TestDesignHandler

        # Pass level and mode via testarch config
        testarch_overrides: dict[str, Any] = {
            "test_design_level": level,
            "test_design_mode": "on" if mode == "create" else mode,
        }
        return self._execute_handler(
            TestDesignHandler, "test-design", testarch_overrides=testarch_overrides
        )

    def run_automate(
        self,
        component: str | None = None,
        mode: str = "create",
    ) -> dict[str, Any]:
        """Run automate workflow standalone.

        Generates test automation specifications.

        Args:
            component: Optional component/feature to focus on.
                Passed via state field for handler to read.
            mode: Workflow mode - "create" (default), "validate", or "edit".

        Returns:
            Dict with execution results.

        """
        from bmad_assist.testarch.handlers import AutomateHandler

        # Map CLI mode to TestarchConfig mode setting
        testarch_overrides: dict[str, Any] = {"automate_mode": "on"} if mode == "create" else {"automate_mode": mode}

        # Pass component via extra_state_fields for handler access
        extra_state_fields: dict[str, Any] | None = None
        if component:
            extra_state_fields = {"automation_component": component}

        return self._execute_handler(
            AutomateHandler, "automate",
            testarch_overrides=testarch_overrides,
            extra_state_fields=extra_state_fields,
        )

    def run_nfr_assess(
        self,
        category: str | None = None,
        mode: str = "create",
    ) -> dict[str, Any]:
        """Run nfr-assess workflow standalone.

        Assesses non-functional requirements with quality gate decision.

        Args:
            category: NFR category (performance|security|reliability|maintainability|all).
                Passed via state field for handler to read.
            mode: Workflow mode - "create" (default), "validate", or "edit".

        Returns:
            Dict with execution results.

        """
        from bmad_assist.testarch.handlers import NFRAssessHandler

        # Map CLI mode to TestarchConfig mode setting
        testarch_overrides: dict[str, Any] = {"nfr_assess_mode": "on"} if mode == "create" else {"nfr_assess_mode": mode}

        # Pass category via extra_state_fields for handler access
        extra_state_fields: dict[str, Any] | None = None
        if category:
            extra_state_fields = {"nfr_category": category}

        return self._execute_handler(
            NFRAssessHandler, "nfr-assess",
            testarch_overrides=testarch_overrides,
            extra_state_fields=extra_state_fields,
        )

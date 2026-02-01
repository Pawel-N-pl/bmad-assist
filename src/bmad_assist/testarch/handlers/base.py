"""Base handler for Testarch workflows.

This module provides the TestarchBaseHandler class, which serves as the
foundation for all Test Architect handlers (ATDD, Test Review, Trace, etc.).
It consolidates common functionality for:
- Evidence collection
- Knowledge loading
- Mode checking
- Output extraction
- Atomic file operations
- State management

"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from abc import abstractmethod
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.core.exceptions import CompilerError
from bmad_assist.core.io import get_original_cwd
from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.providers.base import ProviderResult

if TYPE_CHECKING:
    from bmad_assist.core.config import Config
    from bmad_assist.testarch.config import EvidenceConfig, KnowledgeConfig
    from bmad_assist.testarch.evidence.models import EvidenceContext
    from bmad_assist.compiler.types import CompiledWorkflow

logger = logging.getLogger(__name__)


class TestarchBaseHandler(BaseHandler):
    """Base handler for Testarch workflows.

    Extends BaseHandler to provide specialized capabilities for the Test
    Architect module, including standardized evidence collection, knowledge
    loading, and workflow invocation patterns.

    Subclasses must implement:
    - phase_name: The name of the phase.
    - build_context(): Build template context from state.

    """

    def __init__(self, config: Config, project_path: Path) -> None:
        """Initialize handler with config and project path.

        Args:
            config: Application configuration with provider settings.
            project_path: Path to the project root directory.

        """
        super().__init__(config, project_path)

    @property
    @abstractmethod
    def phase_name(self) -> str:
        """Return the phase name (e.g., 'atdd')."""
        ...

    @property
    @abstractmethod
    def workflow_id(self) -> str:
        """Return the workflow identifier for engagement model checks.

        This ID is used by should_run_workflow() to determine if the workflow
        should execute based on the configured engagement model.

        Workflow IDs use kebab-case and match WORKFLOW_MODE_FIELDS keys:
        - "atdd"
        - "test-review"
        - "trace"
        - "framework"
        - "ci"
        - "test-design"
        - "automate"
        - "nfr-assess"

        """
        ...

    def _check_engagement_model(self) -> tuple[bool, str | None]:
        """Check if workflow should run based on engagement model.

        Returns:
            Tuple of (should_run: bool, skip_reason: str | None).
            If should_run is False, skip_reason contains the explanation.

        """
        from bmad_assist.testarch.engagement import should_run_workflow

        testarch_config = getattr(self.config, "testarch", None)
        if testarch_config is None:
            return (True, None)  # No testarch config = run (backwards compatible)

        if should_run_workflow(self.workflow_id, testarch_config):
            return (True, None)

        model = testarch_config.engagement_model
        reason = f"TEA workflow {self.workflow_id} disabled by engagement_model: {model}"
        return (False, reason)

    def _make_engagement_skip_result(self, reason: str) -> PhaseResult:
        """Create a PhaseResult for skipping due to engagement model.

        Args:
            reason: The skip reason message.

        Returns:
            PhaseResult.ok() with skipped=True and engagement model info.

        """
        testarch_config = getattr(self.config, "testarch", None)
        model = testarch_config.engagement_model if testarch_config else "not_configured"
        return PhaseResult.ok(
            {
                "skipped": True,
                "reason": reason,
                "engagement_model": model,
            }
        )

    # =========================================================================
    # Evidence Collection Methods
    # =========================================================================

    def _get_evidence_config(self) -> "EvidenceConfig | None":
        """Get evidence configuration from testarch config.

        Returns:
            EvidenceConfig if configured, None otherwise.

        """
        if not hasattr(self.config, "testarch") or self.config.testarch is None:
            return None
        return getattr(self.config.testarch, "evidence", None)

    def _should_collect_evidence(self) -> bool:
        """Check if evidence should be collected before workflow step.

        Returns:
            True if evidence collection is enabled and collect_before_step is True.

        """
        evidence_config = self._get_evidence_config()
        if evidence_config is None:
            return False
        return evidence_config.enabled and evidence_config.collect_before_step

    def _collect_evidence(self) -> "EvidenceContext":
        """Collect evidence using EvidenceContextCollector.

        Returns:
            EvidenceContext with collected evidence.

        """
        from bmad_assist.testarch.evidence import get_evidence_collector

        collector = get_evidence_collector(self.project_path)
        evidence_config = self._get_evidence_config()

        return collector.collect_all(evidence_config)

    def _get_evidence_markdown(self) -> str:
        """Get evidence as markdown for workflow context injection.

        Returns:
            Markdown formatted evidence, or empty string if collection disabled
            or failed.

        """
        if not self._should_collect_evidence():
            return ""

        try:
            evidence = self._collect_evidence()
            return evidence.to_markdown()
        except Exception as e:
            logger.warning("Evidence collection failed: %s", e)
            return ""

    def _save_evidence(
        self,
        evidence: "EvidenceContext",
        story_id: str,
    ) -> Path | None:
        """Save collected evidence to configured storage path.

        Args:
            evidence: EvidenceContext to save.
            story_id: Current story ID for filename.

        Returns:
            Path to saved file, or None if storage not configured or failed.

        """
        evidence_config = self._get_evidence_config()
        if not evidence_config or not evidence_config.storage_path:
            return None

        try:
            # Resolve storage path
            from bmad_assist.core.paths import get_paths

            paths = get_paths()
            storage_path_str = evidence_config.storage_path.replace(
                "{implementation_artifacts}", str(paths.implementation_artifacts)
            )
            storage_path = Path(storage_path_str)

            # Convert to markdown content
            content = evidence.to_markdown()

            return self._save_report(
                output_dir=storage_path,
                filename_prefix="evidence",
                content=content,
                story_id=story_id,
            )
        except Exception as e:
            logger.warning("Failed to save evidence: %s", e)
            return None

    # =========================================================================
    # Knowledge Loading Methods
    # =========================================================================

    def _get_knowledge_config(self) -> "KnowledgeConfig | None":
        """Get knowledge configuration from testarch config.

        Returns:
            KnowledgeConfig if configured, None otherwise.

        """
        if not hasattr(self.config, "testarch") or self.config.testarch is None:
            return None
        return getattr(self.config.testarch, "knowledge", None)

    def _load_knowledge(self, workflow_id: str) -> str:
        """Load knowledge fragments for the given workflow.

        Args:
            workflow_id: Workflow identifier (e.g., "atdd").

        Returns:
            Concatenated knowledge fragments as markdown string.

        """
        from bmad_assist.testarch.knowledge import get_knowledge_loader

        loader = get_knowledge_loader(self.project_path)

        # Configure loader if config available
        knowledge_config = self._get_knowledge_config()
        if knowledge_config is not None:
            loader.configure(knowledge_config)

        # Build exclude tags from TEA flags
        tea_flags = {
            "tea_use_playwright_utils": (
                knowledge_config.playwright_utils if knowledge_config else True
            ),
        }

        return loader.load_for_workflow(workflow_id, tea_flags)

    def _load_knowledge_by_tags(
        self,
        tags: list[str],
        exclude_tags: list[str] | None = None,
    ) -> str:
        """Load knowledge fragments by tags.

        Args:
            tags: List of tags to include (OR logic).
            exclude_tags: List of tags to exclude.

        Returns:
            Concatenated knowledge fragments as markdown string.

        """
        from bmad_assist.testarch.knowledge import get_knowledge_loader

        loader = get_knowledge_loader(self.project_path)

        # Configure loader if config available
        knowledge_config = self._get_knowledge_config()
        if knowledge_config is not None:
            loader.configure(knowledge_config)

        return loader.load_by_tags(tags, exclude_tags)

    # =========================================================================
    # Mode Checking
    # =========================================================================

    def _check_mode(
        self,
        state: State,
        mode_field: str,
        state_flag: str | None = None,
    ) -> tuple[str, bool]:
        """Check operation mode and return (mode, should_run).

        Handles standard "off", "on", "auto" modes.

        Args:
            state: Current loop state (for checking state flags in auto mode).
            mode_field: Config field name (e.g., "atdd_mode").
            state_flag: State attribute to check in auto mode (e.g., "atdd_ran_for_story").

        Returns:
            Tuple of (mode: str, should_run: bool).
            - ("off", False): Disabled.
            - ("on", True): Enabled unconditionally.
            - ("auto", True/False): Enabled if state flag is True (or if flag is None).
            - ("not_configured", False): Testarch config missing.

        """
        if not hasattr(self.config, "testarch") or self.config.testarch is None:
            return ("not_configured", False)

        mode = getattr(self.config.testarch, mode_field, "off")

        if mode == "off":
            return ("off", False)
        elif mode == "on":
            return ("on", True)
        else:  # auto
            if state_flag is None:
                return ("auto", True)

            should_run = getattr(state, state_flag, False)
            return ("auto", should_run)

    # =========================================================================
    # Output Extraction
    # =========================================================================

    def _extract_numeric_score(
        self,
        output: str,
        patterns: list[str],
        max_value: int = 100,
    ) -> int | None:
        """Extract numeric score using regex patterns.

        Args:
            output: Text to search.
            patterns: Regex patterns with one capturing group.
            max_value: Maximum valid score (default 100).

        Returns:
            Extracted integer or None.

        """
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                try:
                    score = int(match.group(1))
                    if 0 <= score <= max_value:
                        return score
                except (ValueError, IndexError):
                    continue
        return None

    def _extract_with_priority(
        self,
        output: str,
        options: list[str],
        case_insensitive: bool = True,
    ) -> str | None:
        """Extract first matching option from text (priority order).

        Args:
            output: Text to search.
            options: List of options to search for (in priority order).
            case_insensitive: Whether search is case insensitive.

        Returns:
            Matched option string or None.

        """
        flags = re.IGNORECASE if case_insensitive else 0
        for option in options:
            pattern = rf"\b{re.escape(option)}\b"
            if re.search(pattern, output, flags):
                return option
        return None

    def _extract_file_path(self, output: str, patterns: list[str]) -> str | None:
        """Extract file path from output using patterns.

        Args:
            output: Text to search.
            patterns: Regex patterns with one capturing group.

        Returns:
            Extracted file path or None.

        """
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                path = match.group(1).strip()
                # Basic sanity check
                if "/" in path or "\\" in path or "." in path:
                    return path
        return None

    # =========================================================================
    # Atomic File Operations
    # =========================================================================

    def _save_report(
        self,
        output_dir: str | Path,
        filename_prefix: str,
        content: str,
        story_id: str,
    ) -> Path:
        """Save report with atomic write pattern.

        Args:
            output_dir: Target directory.
            filename_prefix: Prefix for filename.
            content: File content.
            story_id: Story ID for filename inclusion.

        Returns:
            Path to saved file.

        Raises:
            OSError: If write fails.

        """
        dir_path = Path(output_dir)
        dir_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"{filename_prefix}-{story_id}-{timestamp}.md"
        filepath = dir_path / filename

        # Atomic write: temp file -> rename
        fd, temp_path = tempfile.mkstemp(
            suffix=".md",
            prefix=f"{filename_prefix}_",
            dir=str(dir_path),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.rename(temp_path, filepath)
            logger.info("Report saved: %s", filepath)
            return filepath
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    # =========================================================================
    # State Helpers
    # =========================================================================

    def _is_first_story_in_epic(self, state: State) -> bool:
        """Check if current story is the first story in the epic.

        Supports numeric (1.1) and module (testarch.1) IDs.

        Args:
            state: Current state.

        Returns:
            True if story number is "1".

        """
        if state.current_story is None:
            return False

        parts = state.current_story.split(".")
        if len(parts) != 2:
            return False

        return parts[-1] == "1"

    def _get_story_file_path(self, state: State) -> Path | None:
        """Find story file by globbing for pattern.

        Args:
            state: Current state.

        Returns:
            Path to story file or None if not found.

        """
        if state.current_epic is None or state.current_story is None:
            return None

        story_parts = state.current_story.split(".")
        if len(story_parts) != 2:
            return None

        story_num = story_parts[-1]

        try:
            stories_dir = get_paths().stories_dir
        except RuntimeError:
            # Fallback
            stories_dir = self.project_path / "_bmad-output" / "implementation-artifacts"

        pattern = f"{state.current_epic}-{story_num}-*.md"
        matches = sorted(stories_dir.glob(pattern))

        return matches[0] if matches else None

    # =========================================================================
    # Workflow Invocation
    # =========================================================================

    def _compile_workflow(
        self,
        workflow_name: str,
        state: State,
    ) -> "CompiledWorkflow":
        """Compile workflow with proper context.

        Args:
            workflow_name: Name of workflow to compile.
            state: Current state.

        Returns:
            CompiledWorkflow object.

        Raises:
            CompilerError: If compilation fails.

        """
        from bmad_assist.compiler import compile_workflow
        from bmad_assist.compiler.types import CompilerContext

        paths = get_paths()
        context = CompilerContext(
            project_root=self.project_path,
            output_folder=paths.output_folder,
            project_knowledge=paths.project_knowledge,
            cwd=get_original_cwd(),
        )

        story_num = self._extract_story_num(state.current_story)
        context.resolved_variables = {
            "epic_num": state.current_epic,
            "story_num": story_num,
        }

        return compile_workflow(workflow_name, context)

    def _invoke_workflow(
        self,
        compiled: "CompiledWorkflow",
        timeout: int | None = None,
    ) -> ProviderResult | PhaseResult:
        """Invoke master provider with compiled workflow.

        Args:
            compiled: Compiled workflow.
            timeout: Optional timeout override.

        Returns:
            ProviderResult on success, or PhaseResult.fail() on error.
            Note: The return type is Union to satisfy AC8 requirements,
            but callers should be prepared for PhaseResult if invocation fails.

        """
        from bmad_assist.providers import get_provider

        try:
            provider_name = self.config.providers.master.provider
            provider = get_provider(provider_name)
            model = self.config.providers.master.model

            # Default timeout from config if not provided
            timeout_val = timeout or getattr(self.config, "timeout", 120)

            return provider.invoke(
                prompt=compiled.context,
                model=model,
                timeout=timeout_val,
                cwd=self.project_path,
            )
        except CompilerError as e:
            logger.error("Compiler error: %s", e)
            return PhaseResult.fail(f"Compiler error: {e}")
        except Exception as e:
            logger.error("Provider invocation failed: %s", e)
            return PhaseResult.fail(f"Provider invocation failed: {e}")

    # =========================================================================
    # Generic Workflow Invocation (AC1)
    # =========================================================================

    def _invoke_generic_workflow(
        self,
        workflow_name: str,
        state: State,
        extractor_fn: Callable[[str], Any],
        report_dir: Path,
        report_prefix: str,
        story_id: str | None = None,
        metric_key: str = "metric",
        file_key: str = "file",
    ) -> PhaseResult:
        """Generic workflow invocation template.

        Consolidates the common pattern across ATDD, TestReview, and Trace handlers:
        1. Compile workflow via _compile_workflow()
        2. Invoke via _invoke_workflow()
        3. Check for PhaseResult/ProviderResult errors
        4. Extract metrics via extractor_fn
        5. Save report via _save_report()
        6. Return PhaseResult with standardized keys

        Args:
            workflow_name: Name of workflow to compile (e.g., "testarch-atdd").
            state: Current loop state.
            extractor_fn: Function to extract metric from output (takes str, returns Any).
            report_dir: Directory to save reports.
            report_prefix: Prefix for report filename.
            story_id: Story/epic ID for filename (defaults to current_story or current_epic).
            metric_key: Key name for extracted metric in outputs (default: "metric").
            file_key: Key name for report file path in outputs (default: "file").

        Returns:
            PhaseResult with standardized output dict containing:
            - response: Raw provider output
            - <metric_key>: Extracted metric value
            - <file_key>: Path to saved report

        """
        # Determine story_id if not provided
        if story_id is None:
            story_id = state.current_story or str(state.current_epic) or "unknown"

        logger.info("Invoking %s workflow for %s", workflow_name, story_id)

        try:
            # 1. Compile workflow
            compiled = self._compile_workflow(workflow_name, state)
            logger.debug("%s workflow compiled successfully", workflow_name)

            # 2. Save prompt for debugging (ADR-1: fail-soft)
            # Note: compiled.context IS the prompt content sent to LLM
            try:
                from bmad_assist.core.io import save_prompt

                # Extract epic and story_num from state
                epic = state.current_epic if state.current_epic is not None else "unknown"

                # state.current_story is format "25.1" - extract just the story number
                story_num_for_save: int | str = "unknown"
                if state.current_story is not None:
                    story_str = str(state.current_story)
                    if "." in story_str:
                        story_num_for_save = story_str.split(".")[-1]  # "25.1" -> "1"
                    else:
                        story_num_for_save = story_str

                save_prompt(
                    self.project_path, epic, story_num_for_save, self.phase_name, compiled.context
                )
            except (OSError, IOError) as e:
                logger.warning("Failed to save prompt (continuing): %s", e)

            # 3. Invoke provider
            result = self._invoke_workflow(compiled)

            # 3. Check for PhaseResult failure (returned from _invoke_workflow on error)
            if isinstance(result, PhaseResult):
                return result

            # 4. Check for provider error (ProviderResult with non-zero exit)
            if result.exit_code != 0:
                logger.error(
                    "%s provider error for %s: %s",
                    workflow_name,
                    story_id,
                    result.stderr,
                )
                return PhaseResult.fail(f"Provider error: {result.stderr}")

            # 5. Extract metric from output
            metric_value = extractor_fn(result.stdout)
            logger.debug(
                "%s extracted %s=%s",
                workflow_name,
                metric_key,
                metric_value,
            )

            # 6. Save report
            report_path = self._save_report(
                output_dir=report_dir,
                filename_prefix=report_prefix,
                content=result.stdout,
                story_id=story_id,
            )

            logger.info("%s workflow completed for %s", workflow_name, story_id)

            return PhaseResult.ok(
                {
                    "response": result.stdout,
                    metric_key: metric_value,
                    file_key: str(report_path),
                }
            )

        except Exception as e:
            logger.error("%s workflow failed for %s: %s", workflow_name, story_id, e)
            return PhaseResult.fail(f"{workflow_name} workflow failed: {e}")

    # =========================================================================
    # Execute with Mode Check (AC2)
    # =========================================================================

    def _execute_with_mode_check(
        self,
        state: State,
        mode_field: str,
        state_flag: str | None,
        workflow_fn: Callable[[State], PhaseResult],
        mode_output_key: str = "mode",
        skip_reason_auto: str = "condition not met",
    ) -> PhaseResult:
        """Standard mode check wrapper for TEA handlers.

        Consolidates the skip logic pattern across ATDD, TestReview, and Trace handlers:
        1. Check mode via _check_mode()
        2. Return skipped PhaseResult for not_configured/off/auto+False
        3. Call workflow_fn when should run
        4. Include mode in output dict

        Args:
            state: Current loop state.
            mode_field: Config field name (e.g., "atdd_mode").
            state_flag: State attribute to check in auto mode (e.g., "atdd_ran_for_story").
            workflow_fn: Function to call when workflow should run.
            mode_output_key: Key name for mode in outputs (e.g., "atdd_mode", "trace_mode").
            skip_reason_auto: Reason message when skipping in auto mode.

        Returns:
            PhaseResult with mode included in outputs:
            - On skip: {"skipped": True, "reason": "...", mode_output_key: mode}
            - On run: workflow_fn result with mode_output_key added

        """
        mode, should_run = self._check_mode(state, mode_field, state_flag)

        # Handle not configured case
        if mode == "not_configured":
            logger.info("Skipped: testarch not configured")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": "testarch not configured",
                    mode_output_key: "not_configured",
                }
            )

        # Handle mode=off
        if mode == "off":
            logger.info("Skipped: %s=off", mode_field)
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": f"{mode_field}=off",
                    mode_output_key: "off",
                }
            )

        # Handle mode=auto with condition not met
        if not should_run:
            logger.info("Skipped: %s", skip_reason_auto)
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": skip_reason_auto,
                    mode_output_key: "auto",
                }
            )

        # Run workflow with exception handling
        try:
            result = workflow_fn(state)
        except Exception as e:
            logger.error("Workflow failed: %s", e)
            return PhaseResult.fail(f"Workflow failed: {e}")

        # Add mode to outputs (handle both success and failure)
        if result.success:
            outputs = dict(result.outputs)
            outputs[mode_output_key] = mode
            return PhaseResult.ok(outputs)
        else:
            return result

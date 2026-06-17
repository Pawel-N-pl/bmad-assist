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

from bmad_assist.core.config import Config, get_config, get_phase_retries, get_phase_timeout
from bmad_assist.core.config.models.providers import (
    MasterProviderConfig,
    MultiProviderConfig,
    get_phase_provider_config,
)
from bmad_assist.core.exceptions import (
    ConfigError,
    ProviderExitCodeError,
)
from bmad_assist.core.io import get_original_cwd
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.retry import invoke_with_timeout_retry
from bmad_assist.core.state import State
from bmad_assist.providers import get_provider
from bmad_assist.providers.base import BaseProvider, ProviderResult
from bmad_assist.providers.claude import ClaudeSubprocessProvider

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


# Regex to match <file ...>...</file> blocks within <context> section.
# Files are ordered by priority (highest-scored first) so we remove from the end.
_FILE_BLOCK_RE = re.compile(
    r'<file\s+id="[^"]*"\s+path="([^"]*)"[^>]*>.*?</file>',
    re.DOTALL,
)

# Markdown extensions eligible for compression instead of full drop.
# Source code files (.py/.rs/.ts/etc.) are intentionally excluded — LLM
# summarization of code can silently lose type signatures and exact API
# shapes, which is unacceptable for dev_story / code_review phases. They
# stay on the drop path and rely on the elevated ToolCallGuard cap so the
# model can read exact bytes via tools when needed.
_MARKDOWN_EXTENSIONS: tuple[str, ...] = (".md", ".markdown", ".mdx")

# Files smaller than this aren't worth compressing — LLM call latency
# dwarfs the byte savings.
_MIN_COMPRESSIBLE_TOKENS = 500

# Compress to ~50% of original (matches strategic-context defaults).
_COMPRESSION_TARGET_RATIO = 0.5

# Floor on compression target so we don't ask the LLM for an unrealistic
# size on borderline-eligible files.
_MIN_COMPRESSION_TARGET_TOKENS = 200

# CDATA wrapper format used by compiler.output._wrap_cdata. Kept here
# verbatim so the unwrap helper stays a pure inverse — if _wrap_cdata
# changes shape, both sides need updating together.
_CDATA_OPEN = "<![CDATA[\n\n"
_CDATA_CLOSE = "\n\n]]>"
_CDATA_SPLIT_REJOIN = "\n\n]]]]><![CDATA[\n\n"


def _extract_file_block_content(block: str) -> str | None:
    """Extract content from a CDATA-wrapped ``<file>`` block.

    Inverts the wrapping done by ``compiler.output._wrap_cdata`` and the
    ``<file>`` element. Returns None if the block doesn't match the
    expected shape (caller treats this as "compression not applicable").

    Handles split CDATA sections (when the original content contained
    ``]]>``, _wrap_cdata splits into multiple sections and rejoins with
    ``]]]]><![CDATA[``).

    Args:
        block: Full ``<file id=... path=...>...</file>`` block text.

    Returns:
        Original content string, or None if the block is malformed.

    """
    open_tag_end = block.find(">")
    if open_tag_end == -1:
        return None
    close_tag_start = block.rfind("</file>")
    if close_tag_start == -1 or close_tag_start <= open_tag_end:
        return None

    inner = block[open_tag_end + 1 : close_tag_start]
    if not inner.startswith(_CDATA_OPEN) or not inner.endswith(_CDATA_CLOSE):
        return None

    content = inner[len(_CDATA_OPEN) : -len(_CDATA_CLOSE)]
    # Reverse the _wrap_cdata splitting: rejoin split CDATA sections.
    return content.replace(_CDATA_SPLIT_REJOIN, "]]>")


def _build_file_block_with_content(original_block: str, new_content: str) -> str | None:
    """Re-wrap a ``<file>`` block with new content, preserving attributes.

    Lazy-imports ``_wrap_cdata`` to avoid a circular dep at module load.

    Args:
        original_block: The original full ``<file>`` block (used for the
            opening tag with id/path/label attributes).
        new_content: Replacement content to wrap in CDATA.

    Returns:
        The new full ``<file>`` block, or None if the original is malformed.

    """
    open_tag_end = original_block.find(">")
    close_tag_start = original_block.rfind("</file>")
    if open_tag_end == -1 or close_tag_start == -1 or close_tag_start <= open_tag_end:
        return None

    open_tag = original_block[: open_tag_end + 1]
    from bmad_assist.compiler.output import _wrap_cdata

    return open_tag + _wrap_cdata(new_content) + "</file>"


def _sanitize_doc_type_from_path(path: str) -> str:
    """Build a cache-friendly doc_type identifier from a file path.

    The compression cache (``compiler/strategic_context.py``) keys by
    ``doc_type`` — each doc_type stores at most one cached file, with
    stale entries auto-pruned when the source content changes. Using a
    per-path doc_type means each markdown file gets its own cache entry
    that's invalidated automatically on content change.

    Strategic doc cache uses bare prefixes like ``ux``, ``prd``. We use
    ``srcmd-`` to namespace source-tree markdown caches and avoid any
    collision with strategic doc cache files.

    Args:
        path: Repo-relative file path from the XML attribute.

    Returns:
        Sanitized doc_type identifier safe to use as a filename prefix.

    """
    sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "-", path).strip("-")
    return f"srcmd-{sanitized}"


def _try_compress_markdown_file_block(
    prompt: str,
    match: "re.Match[str]",
    path: str,
    project_root: Path,
) -> str | None:
    """Attempt to compress a markdown ``<file>`` block in place.

    Calls the existing ``_compress_or_truncate`` helper (LLM-based
    compression with disk caching, falling back to truncation). Annotates
    the compressed content so the model knows it's a summary and can read
    the full file via tools (the elevated ToolCallGuard cap covers it).

    Args:
        prompt: Current prompt text (will be spliced).
        match: Regex match for the ``<file>`` block (positions are
            relative to the ORIGINAL prompt — the caller must iterate
            in reverse so positions stay valid as later blocks change).
        path: Path attribute from the XML, used for cache key + logging.
        project_root: Project root for the disk cache.

    Returns:
        The new prompt text on success, or None if compression should
        be skipped (caller falls back to dropping the file).

    """
    block = match.group(0)
    content = _extract_file_block_content(block)
    if content is None:
        logger.debug("Compression skipped for %s: could not extract CDATA", path)
        return None

    original_tokens = len(content) // 4
    if original_tokens < _MIN_COMPRESSIBLE_TOKENS:
        logger.debug(
            "Compression skipped for %s: only %d tokens (< %d threshold)",
            path,
            original_tokens,
            _MIN_COMPRESSIBLE_TOKENS,
        )
        return None

    target_tokens = max(
        int(original_tokens * _COMPRESSION_TARGET_RATIO),
        _MIN_COMPRESSION_TARGET_TOKENS,
    )

    try:
        from bmad_assist.compiler.strategic_context import _compress_or_truncate
    except ImportError as e:  # pragma: no cover - defensive
        logger.debug("Compression module unavailable: %s", e)
        return None

    doc_type = _sanitize_doc_type_from_path(path)
    try:
        compressed_content, compressed_tokens = _compress_or_truncate(
            content, target_tokens, doc_type, project_root
        )
    except Exception as e:  # pragma: no cover - defensive, helper is fail-safe
        logger.debug("Compression failed for %s: %s", path, e)
        return None

    # If compression didn't actually shrink the content (e.g. helper LLM
    # echoed input, truncation floor hit), don't bother splicing — it
    # adds annotation noise without saving budget. Drop instead.
    if len(compressed_content) >= len(content):
        logger.debug(
            "Compression no-op for %s (%d → %d chars), falling through to drop",
            path,
            len(content),
            len(compressed_content),
        )
        return None

    annotated = (
        f"[note: this file was compressed from ~{original_tokens} to "
        f"~{compressed_tokens} tokens to fit prompt budget. Read the file "
        f"directly via your file tools if you need exact content.]\n\n"
        + compressed_content
    )

    new_block = _build_file_block_with_content(block, annotated)
    if new_block is None:  # pragma: no cover - extraction succeeded so rebuild should too
        return None

    logger.info(
        "Budget compress: shrank '%s' from %d to ~%d tokens",
        path,
        original_tokens,
        len(annotated) // 4,
    )

    return prompt[: match.start()] + new_block + prompt[match.end() :]


def _trim_source_context(
    prompt: str,
    current_tokens: int,
    budget: int,
    project_root: Path | None = None,
) -> tuple[str, list[str], list[str]]:
    """Trim or compress lowest-priority source files to fit the prompt budget.

    Source files in the <context> section are ordered by score (highest first).
    We process from the end (lowest priority) until estimated tokens are
    within budget. Each file's fate depends on its type:

    - **Markdown** (``.md``/``.markdown``/``.mdx``): tries LLM compression
      via ``_compress_or_truncate`` first (with disk cache). If compression
      shrinks the file, splice the compressed version in place. If the
      file is too small, compression is skipped with a debug log.
    - **Source code** (everything else): always dropped. LLM summarization
      of code can lose type signatures and exact API shapes, which is
      unacceptable for dev_story / code_review. The model gets the file
      via tool calls instead (elevated ToolCallGuard cap covers this).

    Reverse iteration: we modify text only at-or-after the current match's
    position, so earlier (still-pending) match offsets remain valid.

    Args:
        prompt: Full compiled prompt XML string.
        current_tokens: Current estimated token count (len/4).
        budget: Target token budget.
        project_root: Project root for the compression disk cache. When
            None, compression is skipped entirely (markdown files fall
            through to the drop path — used by tests that don't want to
            depend on the compression machinery).

    Returns:
        Tuple of ``(trimmed_prompt, removed_paths, compressed_paths)``.

        - ``removed_paths``: files fully dropped from the prompt.
        - ``compressed_paths``: markdown files compressed in place.

        Callers feed BOTH lists into the ToolCallGuard's elevated-cap set,
        because compressed files are still lossy summaries — the model
        may need to read exact bytes via tools.

    """
    # Find all file blocks
    file_blocks = list(_FILE_BLOCK_RE.finditer(prompt))
    if not file_blocks:
        return prompt, [], []

    trimmed = prompt
    removed_paths: list[str] = []
    compressed_paths: list[str] = []

    for match in reversed(file_blocks):
        if len(trimmed) // 4 <= budget:
            break

        path = match.group(1)

        # Markdown: try compression first.
        is_markdown = path.lower().endswith(_MARKDOWN_EXTENSIONS)
        if is_markdown and project_root is not None:
            new_trimmed = _try_compress_markdown_file_block(
                trimmed, match, path, project_root
            )
            if new_trimmed is not None:
                trimmed = new_trimmed
                compressed_paths.append(path)
                continue

        # Drop the file block (and any surrounding newline).
        start = match.start()
        end = match.end()
        if end < len(trimmed) and trimmed[end] == "\n":
            end += 1
        trimmed = trimmed[:start] + trimmed[end:]
        removed_paths.append(path)
        logger.info("Budget trim: removed source file '%s'", path)

    if removed_paths or compressed_paths:
        new_tokens = len(trimmed) // 4
        logger.info(
            "Trimmed %d / compressed %d source file(s): %d → %d estimated tokens (budget: %d)",
            len(removed_paths),
            len(compressed_paths),
            current_tokens,
            new_tokens,
            budget,
        )

    return trimmed, removed_paths, compressed_paths


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
        # Files that were budget-trimmed out of the most recent compiled
        # prompt. Reset on every compile_workflow_prompt call. invoke_provider
        # uses this set to elevate the ToolCallGuard per-file cap so the
        # model can read trimmed files via tools without hitting the base cap.
        self._budget_trimmed_paths: set[str] = set()

    def _record_budget_trimmed_paths(self, removed_paths: list[str]) -> None:
        """Record paths trimmed from the prompt during budget enforcement.

        Resolves each repo-relative path to a normalized realpath against
        the project root so the lookup matches whatever path the model
        passes to its file tools (which the guard normalizes the same way).

        Args:
            removed_paths: Paths from XML ``path="..."`` attributes as
                captured by _trim_source_context.

        """
        import os

        normalized: set[str] = set()
        for raw in removed_paths:
            try:
                # Repo-relative or absolute — resolve against project root.
                candidate = (self.project_path / raw).resolve(strict=False)
                normalized.add(os.path.realpath(candidate))
            except (OSError, ValueError) as exc:
                logger.debug(
                    "Could not normalize trimmed path %r: %s", raw, exc
                )
        self._budget_trimmed_paths = normalized

    def _reset_budget_trimmed_paths(self) -> None:
        """Clear trimmed-path tracking before a new compile."""
        self._budget_trimmed_paths = set()

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

        Uses the BMAD compiler which supports:
        - Patched templates from global cache
        - Variable resolution
        - Optimized instructions

        Legacy handler YAML files are deprecated and no longer supported.
        If compilation fails, raises ConfigError with clear instructions.

        Args:
            state: Current loop state.

        Returns:
            Compiled prompt string ready for provider invocation.

        Raises:
            ConfigError: If workflow compilation fails.

        """
        # Try compiler
        compiled_prompt = self._try_compile_workflow(state)
        if compiled_prompt is not None:
            return compiled_prompt

        # Compiler failed - give clear error message
        workflow_name = self.phase_name.replace("_", "-")
        raise ConfigError(
            f"Failed to compile workflow: {workflow_name}\n\n"
            "The workflow compiler could not load this workflow.\n"
            "Handler YAML files are deprecated and no longer supported.\n\n"
            "To fix:\n"
            "  1. Run 'bmad-assist init' in your project directory\n"
            "  2. If already initialized, reinstall: pip install -e .\n"
            "  3. Check workflow exists: bmad-assist compile -w {workflow_name} --debug\n"
        )

    def _try_compile_workflow(self, state: State) -> str | None:
        """Try to compile workflow using the compiler.

        Args:
            state: Current loop state.

        Returns:
            Compiled prompt XML, or None if workflow not found.

        Raises:
            ConfigError: If compilation fails for reasons other than workflow not found.

        """
        import os

        from bmad_assist.compiler import compile_workflow
        from bmad_assist.compiler.types import CompilerContext
        from bmad_assist.core.exceptions import CompilerError

        # Convert phase_name to workflow name (e.g., create_story -> create-story)
        workflow_name = self.phase_name.replace("_", "-")

        # Reset budget-trimmed path tracking — each compile starts fresh.
        # invoke_provider() reads this set after compile to elevate the
        # ToolCallGuard per-file cap for trimmed files.
        self._reset_budget_trimmed_paths()

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

        try:
            # Compile workflow - returns CompiledWorkflow with full XML in context
            compiled = compile_workflow(workflow_name, context)

            # Add git intelligence if patch config specifies it
            prompt = compiled.context
            prompt = self._inject_git_intelligence(prompt, workflow_name, resolved_variables)

            # F4-IMPL: Warn if prompt exceeds expected budget (but don't block)
            try:
                config = get_config()
                workflow_budget = config.compiler.source_context.budgets.get_budget(workflow_name)
                # Prompt is typically ~2x the token estimate due to XML overhead
                expected_prompt_tokens = len(prompt) // 4

                if expected_prompt_tokens > workflow_budget:
                    logger.warning(
                        "Prompt may exceed budget for %s: estimated %d tokens "
                        "(config budget: %d). Trimming lowest-priority source files.",
                        workflow_name,
                        expected_prompt_tokens,
                        workflow_budget,
                    )
                    prompt, removed_paths, compressed_paths = _trim_source_context(
                        prompt,
                        expected_prompt_tokens,
                        workflow_budget,
                        project_root=self.project_path,
                    )
                    # Track BOTH dropped and compressed paths for elevated
                    # ToolCallGuard cap. Compressed files are lossy summaries,
                    # so the model may still need to read exact bytes via
                    # tools — both cases warrant the higher per-file cap.
                    self._record_budget_trimmed_paths(removed_paths + compressed_paths)
            except Exception:
                # Config not loaded (e.g., in tests) - skip budget warning
                pass

            logger.info(
                "Using compiled prompt for %s (tokens: ~%d)",
                workflow_name,
                compiled.token_estimate,
            )

            return prompt

        except CompilerError as e:
            # Compilation failed - log and return None to trigger clear error message
            logger.warning("Workflow compilation failed for %s: %s", workflow_name, e)
            return None
        except FileNotFoundError as e:
            # Workflow files not found
            logger.warning("Workflow files not found for %s: %s", workflow_name, e)
            return None
        except Exception as e:
            # Unexpected error - log with full traceback for debugging
            logger.error(
                "Unexpected error compiling %s: %s",
                workflow_name,
                e,
                exc_info=True,
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

    def _get_reasoning_effort(self) -> str | None:
        """Get reasoning_effort from provider config if available."""
        provider_type = self._get_provider_type()

        if provider_type == "helper":
            return None

        phase_config = self._get_phase_config()

        if isinstance(phase_config, list):
            if not phase_config:
                return None
            return getattr(phase_config[0], "reasoning_effort", None)
        else:
            return getattr(phase_config, "reasoning_effort", None)

    def invoke_provider(
        self,
        prompt: str,
        retry_timeout_minutes: int = 30,
        retry_delay: int = 60,
        allowed_tools: list[str] | None = None,
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

        # Get timeout retry configuration
        timeout_retries = get_phase_retries(self.config, self.phase_name)

        last_error: ProviderExitCodeError | None = None
        start_time = time.time()
        max_duration = retry_timeout_minutes * 60  # Convert to seconds
        attempt = 0
        current_delay = retry_delay

        # Create guard ONCE — persists across outer retry loop (counters preserved)
        from bmad_assist.providers.tool_guard import (
            GUARD_TERMINATION_PREFIX,
            ToolCallGuard,
        )

        tg = self.config.tool_guard
        # Pass budget-trimmed files into the guard so they get the elevated
        # per-file cap. Empty set = no elevation, behavior unchanged.
        elevated_paths = set(self._budget_trimmed_paths)
        # Resolve max_total_calls per-phase. dev_story legitimately needs
        # many more tool calls than e.g. validation phases, so users can
        # set ``tool_guard.max_total_calls_per_phase: {dev_story: 600}``
        # in config to raise just the phase that needs it.
        phase_max_total_calls = tg.get_max_total_calls(self.phase_name)
        guard = ToolCallGuard(
            max_total_calls=phase_max_total_calls,
            max_interactions_per_file=tg.max_interactions_per_file,
            max_calls_per_minute=tg.max_calls_per_minute,
            elevated_file_paths=elevated_paths,
            max_interactions_per_file_elevated=(
                tg.max_interactions_per_file_trimmed
            ),
        )

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

            # Resolve reasoning_effort from provider config
            reasoning_effort = self._get_reasoning_effort()

            # Setup fallback for claude-sdk provider (SDK init timeout -> subprocess)
            fallback_invoke_fn = None
            fallback_timeout_retries = None
            if provider.provider_name == "claude":
                # Claude SDK can timeout on initialization, fallback to subprocess
                subprocess_provider = ClaudeSubprocessProvider()
                fallback_invoke_fn = subprocess_provider.invoke
                fallback_timeout_retries = timeout_retries  # Reset retry count for fallback
                logger.debug("Configured subprocess fallback for claude-sdk provider")

            # Reset guard for outer retries (preserves counters, clears rate window)
            if attempt > 1:
                guard.reset_for_retry()

            try:
                # Use shared timeout retry wrapper for provider invocation
                result = invoke_with_timeout_retry(
                    provider.invoke,
                    timeout_retries=timeout_retries,
                    phase_name=self.phase_name,
                    fallback_invoke_fn=fallback_invoke_fn,
                    fallback_timeout_retries=fallback_timeout_retries,
                    prompt=prompt,
                    model=cli_model,
                    display_model=display_model,
                    timeout=timeout,
                    settings_file=settings_file,
                    cwd=self.project_path,
                    reasoning_effort=reasoning_effort,
                    guard=guard,
                    allowed_tools=allowed_tools,
                )

                # Check for guard-triggered termination
                if (
                    result.termination_reason
                    and result.termination_reason.startswith(GUARD_TERMINATION_PREFIX)
                ):
                    stats = guard.get_stats()
                    # Capture reason BEFORE reset clears it
                    first_attempt_reason = result.termination_reason
                    logger.warning(
                        "ToolCallGuard triggered: %s (total_calls=%d, max_file=%s)",
                        first_attempt_reason,
                        stats.total_calls,
                        stats.max_file,
                    )

                    # Only retry for rate_exceeded — budget/file-cap
                    # exhaustion means counters are already spent
                    is_rate_only = stats.terminated_reason is not None and (
                        stats.terminated_reason.startswith("rate_exceeded")
                    )
                    if not is_rate_only:
                        logger.error(
                            "ToolCallGuard: non-retriable termination (%s) — "
                            "returning result as-is",
                            first_attempt_reason,
                        )
                        return result

                    guard.reset_for_retry()
                    logger.warning(
                        "ToolCallGuard: retrying invocation "
                        "(counters preserved, rate window cleared)"
                    )
                    result = invoke_with_timeout_retry(
                        provider.invoke,
                        timeout_retries=timeout_retries,
                        phase_name=self.phase_name,
                        fallback_invoke_fn=fallback_invoke_fn,
                        fallback_timeout_retries=fallback_timeout_retries,
                        prompt=prompt,
                        model=cli_model,
                        display_model=display_model,
                        timeout=timeout,
                        settings_file=settings_file,
                        cwd=self.project_path,
                        reasoning_effort=reasoning_effort,
                        guard=guard,
                        allowed_tools=allowed_tools,
                    )

                    if (
                        result.termination_reason
                        and result.termination_reason.startswith(
                            GUARD_TERMINATION_PREFIX
                        )
                    ):
                        stats = guard.get_stats()
                        logger.error(
                            "ToolCallGuard: retry also terminated — "
                            "failing phase (first: %s)",
                            first_attempt_reason,
                        )
                    else:
                        logger.info(
                            "ToolCallGuard: retry succeeded "
                            "(first attempt was terminated: %s)",
                            first_attempt_reason,
                        )

                return result

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

            # Invoke provider
            result = self.invoke_provider(prompt)

            # Check for errors
            # Build termination_metadata if guard was active
            term_metadata = None
            if result.termination_info:
                term_metadata = {
                    "termination_info": result.termination_info,
                    "termination_reason": result.termination_reason,
                }

            if result.exit_code != 0:
                error_msg = result.stderr or f"Provider exited with code {result.exit_code}"
                logger.warning(
                    "Provider returned non-zero exit code: %d, stderr: %s",
                    result.exit_code,
                    result.stderr[:500] if result.stderr else "(empty)",
                )
                fail_outputs: dict[str, Any] = {}
                if term_metadata:
                    fail_outputs["termination_metadata"] = term_metadata
                phase_result = PhaseResult(
                    success=False,
                    error=error_msg,
                    outputs=fail_outputs,
                )
            else:
                # Success - return output
                outputs: dict[str, Any] = {
                    "response": result.stdout,
                    "model": result.model,
                    "duration_ms": result.duration_ms,
                }
                if term_metadata:
                    outputs["termination_metadata"] = term_metadata
                phase_result = PhaseResult.ok(outputs)

            # Save timing if enabled and successful
            if start_time and phase_result.success and self.config.benchmarking.enabled:
                self._save_timing_record(
                    state=state,
                    start_time=start_time,
                    end_time=datetime.now(UTC),
                    output=result.stdout,
                )

            # NOTE: phase_completed notification is dispatched by the caller (runner.py
            # or epic_phases.py) to avoid duplicates. Handler should NOT dispatch here.
            # See tech-spec cli-observability-run-tracking.md Task 6.

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

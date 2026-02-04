"""Boundary Analysis Method (#154) for Deep Verify.

This module implements the Boundary Analysis verification method that detects
edge cases via domain-specific checklists analyzed by an LLM.

Method #154 is one of two methods that always run regardless of domain
detection results (the other being #153 Pattern Match).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    Evidence,
    Finding,
    MethodId,
    PatternId,
    Severity,
)
from bmad_assist.deep_verify.methods.base import BaseVerificationMethod
from bmad_assist.providers import ClaudeSDKProvider

logger = logging.getLogger(__name__)

__all__ = [
    "BoundaryAnalysisMethod",
    "ChecklistItem",
    "ChecklistLoader",
    "ChecklistItemYaml",
    "ChecklistYaml",
    "ChecklistAnalysisResponse",
    "BOUNDARY_ANALYSIS_SYSTEM_PROMPT",
]

# =============================================================================
# Constants
# =============================================================================

DEFAULT_MODEL = "haiku"
DEFAULT_TIMEOUT = 30
DEFAULT_THRESHOLD = 0.6
MAX_ARTIFACT_LENGTH = 3000
MAX_CONCURRENT_LLM_CALLS = 3

# =============================================================================
# System Prompt
# =============================================================================

BOUNDARY_ANALYSIS_SYSTEM_PROMPT = """You are a boundary analysis expert for code review.
Analyze the provided artifact against a specific edge case checklist item.

Your task:
1. Determine if the artifact properly handles the described edge case
2. If NOT handled (violated), provide evidence from the code
3. Return a structured JSON response

Response format:
{
    "violated": true/false,
    "confidence": 0.0-1.0,
    "evidence_quote": "Relevant code snippet showing the issue (if violated)",
    "line_number": 123,
    "explanation": "Brief explanation of why this is/isn't a concern"
}

Rules:
- "violated" = true means the edge case is NOT properly handled
- confidence should reflect how certain you are (0.5 = uncertain, 0.9 = very certain)
- evidence_quote must be verbatim from the artifact
- line_number should be accurate if identifiable (1-indexed)
- If the edge case is properly handled, set violated=false and provide brief explanation"""


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True)
class ChecklistItem:
    """Single checklist item for boundary analysis.

    The domain field is a string (not ArtifactDomain enum) to support:
    - "general" for always-applied checklists
    - "security", "storage", "messaging", etc. for domain-specific checklists

    Attributes:
        id: Unique identifier (e.g., "GEN-001", "SEC-BOUNDARY-001")
        category: Logical grouping (e.g., "empty_input", "auth_bypass")
        question: Yes/no question for LLM to answer
        description: Detailed explanation of the edge case
        severity: Severity level if this boundary case is violated
        domain: Domain this checklist belongs to ("general" or domain name)

    """

    id: str
    category: str
    question: str
    description: str
    severity: Severity
    domain: str

    def __repr__(self) -> str:
        """Return a string representation of the checklist item."""
        return f"ChecklistItem(id={self.id!r}, category={self.category!r}, domain={self.domain!r})"


# =============================================================================
# Pydantic Models for YAML Validation
# =============================================================================


class ChecklistItemYaml(BaseModel):
    """Pydantic model for validating checklist YAML structure."""

    id: str = Field(pattern=r"^[A-Z]+-[A-Z0-9-]+$")
    category: str
    question: str
    description: str
    severity_if_violated: str
    domain: str

    @field_validator("severity_if_violated")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        """Validate that severity is a valid Severity enum value."""
        valid = {s.value for s in Severity}
        if v not in valid:
            raise ValueError(f"Invalid severity: {v}. Must be one of: {valid}")
        return v

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        """Validate that domain is a valid domain string."""
        valid = {"general", "security", "storage", "messaging", "transform", "concurrency", "api"}
        if v not in valid:
            raise ValueError(f"Invalid domain: {v}. Must be one of: {valid}")
        return v

    def to_checklist_item(self) -> ChecklistItem:
        """Convert validated YAML to ChecklistItem dataclass."""
        return ChecklistItem(
            id=self.id,
            category=self.category,
            question=self.question,
            description=self.description,
            severity=Severity(self.severity_if_violated),
            domain=self.domain,
        )


class ChecklistYaml(BaseModel):
    """Root model for checklist YAML files."""

    checklist: list[ChecklistItemYaml]


# =============================================================================
# Pydantic Model for LLM Response
# =============================================================================


class ChecklistAnalysisResponse(BaseModel):
    """Expected LLM response structure for checklist analysis."""

    violated: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_quote: str = ""
    line_number: int | None = None
    explanation: str = ""


# =============================================================================
# Checklist Loader
# =============================================================================


class ChecklistLoader:
    """Loads and manages boundary analysis checklists from YAML files."""

    def __init__(self, checklist_dir: Path) -> None:
        """Initialize the checklist loader.

        Args:
            checklist_dir: Directory containing checklist YAML files.

        """
        self._checklist_dir = checklist_dir

    def __repr__(self) -> str:
        """Return a string representation of the checklist loader."""
        return f"ChecklistLoader(dir={self._checklist_dir!r})"

    def load(self, domains: list[ArtifactDomain] | None = None) -> list[ChecklistItem]:
        """Load checklists for specified domains plus general checklist.

        Always loads general.yaml first, then domain-specific checklists.
        Domain-specific items override general items with same ID.

        Args:
            domains: Optional list of domains to load domain-specific checklists.
                     If None, only general checklist is loaded.

        Returns:
            List of ChecklistItem objects.

        """
        items: list[ChecklistItem] = []

        # Always load general checklist first
        items.extend(self._load_checklist_file("general"))

        # Load domain-specific checklists
        if domains:
            domain_file_map = {
                ArtifactDomain.SECURITY: "security",
                ArtifactDomain.STORAGE: "storage",
                ArtifactDomain.MESSAGING: "messaging",
                ArtifactDomain.API: "api",
                ArtifactDomain.CONCURRENCY: "concurrency",
                ArtifactDomain.TRANSFORM: "transform",
            }

            loaded_files: set[str] = set()
            for domain in domains:
                file_name = domain_file_map.get(domain)
                if file_name and file_name not in loaded_files:
                    items.extend(self._load_checklist_file(file_name))
                    loaded_files.add(file_name)

        # Deduplicate by ID (later overrides earlier)
        seen: dict[str, ChecklistItem] = {}
        for item in items:
            seen[item.id] = item

        return list(seen.values())

    def _load_checklist_file(self, name: str) -> list[ChecklistItem]:
        """Load checklist items from a YAML file.

        Args:
            name: Base name of the checklist file (e.g., "general", "security").

        Returns:
            List of ChecklistItem objects from the file.

        """
        file_path = self._checklist_dir / f"{name}.yaml"

        if not file_path.exists():
            logger.debug("Checklist file not found: %s", file_path)
            return []

        try:
            with open(file_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data is None:
                logger.debug("Empty checklist file: %s", file_path)
                return []

            # Validate with Pydantic
            checklist_yaml = ChecklistYaml(**data)

            # Convert to ChecklistItem dataclasses
            items = [item_yaml.to_checklist_item() for item_yaml in checklist_yaml.checklist]

            logger.debug("Loaded %d items from %s", len(items), file_path)
            return items

        except yaml.YAMLError as e:
            logger.error("Failed to parse checklist YAML %s: %s", file_path, e)
            raise RuntimeError(f"Failed to parse checklist {file_path}: {e}") from e
        except Exception as e:
            logger.error("Failed to load checklist %s: %s", file_path, e)
            raise RuntimeError(f"Failed to load checklist {file_path}: {e}") from e


# =============================================================================
# Boundary Analysis Method
# =============================================================================


class BoundaryAnalysisMethod(BaseVerificationMethod):
    """Boundary Analysis Method (#154) - Edge case detection via checklists.

    This method analyzes artifact text against domain-specific checklists
    using LLM-based analysis to identify unhandled edge cases and boundary
    conditions that pattern matching might miss.

    Attributes:
        method_id: Unique method identifier "#154".
        _provider: ClaudeSDKProvider for LLM calls.
        _model: Model identifier for LLM calls.
        _threshold: Minimum confidence threshold for findings (0.0-1.0).
        _timeout: Timeout in seconds for LLM calls.
        _loader: ChecklistLoader for loading domain-specific checklists.

    Example:
        >>> from pathlib import Path
        >>> method = BoundaryAnalysisMethod()
        >>> findings = await method.analyze("code with potential edge cases")
        >>> for f in findings:
        ...     print(f"{f.id}: {f.title}")

    """

    method_id: MethodId

    def __init__(
        self,
        checklist_dir: Path | None = None,
        model: str = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        timeout: int = DEFAULT_TIMEOUT,
        llm_client: Any | None = None,
    ) -> None:
        """Initialize the Boundary Analysis Method.

        Args:
            checklist_dir: Optional directory containing checklist YAML files.
                          If None, uses default location.
            model: Model identifier for LLM calls (default: "haiku").
            threshold: Minimum confidence threshold for findings (default: 0.6).
            timeout: Timeout in seconds for LLM calls (default: 30).
            llm_client: Optional LLMClient for managed LLM calls. If provided,
                       uses LLMClient (with retry, rate limiting, cost tracking).
                       If None, creates direct ClaudeSDKProvider.

        Raises:
            ValueError: If threshold is not between 0.0 and 1.0.

        """
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be between 0.0 and 1.0, got {threshold}")

        self.method_id = MethodId("#154")
        self._llm_client = llm_client
        # Only create provider if LLMClient NOT provided
        self._provider: ClaudeSDKProvider | None
        if llm_client is None:
            self._provider = ClaudeSDKProvider()
        else:
            self._provider = None
        self._model = model
        self._threshold = threshold
        self._timeout = timeout

        # Initialize checklist loader
        if checklist_dir is None:
            checklist_dir = Path(__file__).parent.parent / "patterns" / "data" / "checklists"
        self._loader = ChecklistLoader(checklist_dir)

    def __repr__(self) -> str:
        """Return a string representation of the method."""
        return f"BoundaryAnalysisMethod(method_id={self.method_id!r}, model='{self._model}', threshold={self._threshold})"

    async def analyze(
        self,
        artifact_text: str,
        **kwargs: dict[str, object],
    ) -> list[Finding]:
        """Analyze artifact against boundary checklists.

        Args:
            artifact_text: The text content to analyze for boundary issues.
            **kwargs: Additional context including:
                - domains: Optional list[ArtifactDomain] to select checklists
                - config: Optional DeepVerifyConfig (not used currently)

        Returns:
            List of Finding objects for violated checklist items with
            confidence >= threshold. Findings have temporary IDs "#154-F1",
            "#154-F2", etc. which will be reassigned by DeepVerifyEngine.

        """
        if not artifact_text or not artifact_text.strip():
            logger.debug("Empty artifact text, returning no findings")
            return []

        try:
            # Extract domains from kwargs for checklist selection
            domains: list[ArtifactDomain] | None = kwargs.get("domains")  # type: ignore[assignment]

            # Load appropriate checklists
            checklist_items = self._loader.load(domains)

            if not checklist_items:
                logger.warning("No checklists available for analysis")
                return []

            logger.debug(
                "Analyzing artifact against %d checklist items (domains=%s)",
                len(checklist_items),
                domains,
            )

            # Analyze each checklist item in parallel with semaphore for rate limiting
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

            async def analyze_with_limit(
                item: ChecklistItem,
            ) -> tuple[ChecklistAnalysisResponse, ChecklistItem] | None:
                async with semaphore:
                    try:
                        # Run sync LLM call in thread pool to avoid blocking
                        result = await asyncio.to_thread(
                            self._analyze_checklist_item_sync, artifact_text, item
                        )
                        if result.violated and result.confidence >= self._threshold:
                            # Return tuple of (finding_data, item) for ID assignment later
                            return (result, item)
                    except Exception as e:
                        logger.warning("Checklist analysis failed for %s: %s", item.id, e)
                    return None

            # Run all analyses in parallel
            tasks = [analyze_with_limit(item) for item in checklist_items]
            results = await asyncio.gather(*tasks)

            # Collect results and assign sequential IDs to avoid gaps
            findings: list[Finding] = []
            finding_idx = 0
            for result in results:
                if result is not None:
                    result_data, item = result
                    finding_idx += 1
                    findings.append(self._create_finding(result_data, item, finding_idx))

            logger.debug(
                "Boundary analysis found %d violations (threshold=%.2f)",
                len(findings),
                self._threshold,
            )

            return findings

        except Exception as e:
            logger.warning("Boundary analysis failed: %s", e, exc_info=True)
            return []

    def _analyze_checklist_item_sync(
        self,
        artifact_text: str,
        item: ChecklistItem,
    ) -> ChecklistAnalysisResponse:
        """Analyze single checklist item using LLM.

        Uses LLMClient if available, otherwise falls back to direct provider.

        Args:
            artifact_text: The text to analyze.
            item: The checklist item to evaluate.

        Returns:
            ChecklistAnalysisResponse with analysis results.

        """
        prompt = self._build_prompt(artifact_text, item)

        if self._llm_client:
            # Use LLMClient for managed calls (async bridge)
            # CRITICAL: Use run_async_in_thread() instead of asyncio.run() to avoid
            # shutting down the default executor (which the outer event loop uses)
            from bmad_assist.core.async_utils import run_async_in_thread

            result = run_async_in_thread(
                self._llm_client.invoke(
                    prompt=prompt,
                    model=self._model,
                    timeout=self._timeout,
                    method_id=str(self.method_id),
                )
            )
            raw_response = result.stdout
        else:
            # Direct provider call (legacy fallback)
            assert self._provider is not None
            result = self._provider.invoke(
                prompt=prompt,
                model=self._model,
                timeout=self._timeout,
            )
            raw_response = self._provider.parse_output(result)

        return self._parse_response(raw_response)

    def _build_prompt(self, artifact_text: str, item: ChecklistItem) -> str:
        """Build the prompt for LLM checklist analysis.

        Args:
            artifact_text: The text to analyze.
            item: The checklist item to evaluate.

        Returns:
            Formatted prompt string.

        """
        truncated = artifact_text[:MAX_ARTIFACT_LENGTH]
        return (
            f"{BOUNDARY_ANALYSIS_SYSTEM_PROMPT}\n\n"
            f"Artifact to analyze:\n```\n{truncated}\n```\n\n"
            f"Checklist item to evaluate:\n"
            f"ID: {item.id}\n"
            f"Category: {item.category}\n"
            f"Question: {item.question}\n"
            f"Description: {item.description}\n\n"
            f"Analyze whether this artifact properly handles the described edge case. "
            f"Respond with JSON only."
        )

    def _parse_response(self, raw_response: str) -> ChecklistAnalysisResponse:
        """Parse LLM response with robust JSON extraction.

        Handles:
        - JSON inside markdown code blocks (```json...```)
        - Raw JSON objects
        - Nested braces by tracking depth

        Args:
            raw_response: Raw text response from LLM.

        Returns:
            Parsed ChecklistAnalysisResponse.

        Raises:
            ValueError: If response cannot be parsed.

        """
        # Try to extract from markdown code block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_response, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Find JSON by matching braces - handle nested objects
            brace_depth = 0
            start_idx = -1
            json_str = ""
            for i, char in enumerate(raw_response):
                if char == "{":
                    if brace_depth == 0:
                        start_idx = i
                    brace_depth += 1
                elif char == "}":
                    brace_depth -= 1
                    if brace_depth == 0 and start_idx >= 0:
                        json_str = raw_response[start_idx : i + 1]
                        break

            if not json_str:
                raise ValueError("No JSON found in response")

        # Parse with Pydantic validation
        data = json.loads(json_str)
        return ChecklistAnalysisResponse(**data)

    def _create_finding(
        self,
        result: ChecklistAnalysisResponse,
        item: ChecklistItem,
        index: int,
    ) -> Finding:
        """Convert checklist analysis result to Finding.

        Args:
            result: The analysis result from LLM.
            item: The checklist item that was evaluated.
            index: The index for generating finding ID.

        Returns:
            Finding object with all relevant details.

        """
        finding_id = f"#154-F{index + 1}"

        # Truncate title to 80 chars
        title = item.question
        if len(title) > 80:
            title = title[:77] + "..."

        # Build description
        description_parts = [item.description]
        if result.explanation:
            description_parts.append(f"\nAnalysis: {result.explanation}")
        description_parts.append(f"\nChecklist: {item.id} ({item.category})")
        description = "".join(description_parts)

        # Create evidence
        evidence = []
        if result.evidence_quote:
            evidence.append(
                Evidence(
                    quote=result.evidence_quote,
                    line_number=result.line_number,
                    source=item.id,
                    confidence=result.confidence,
                )
            )

        # Map domain string to ArtifactDomain enum if applicable
        domain: ArtifactDomain | None = None
        if item.domain != "general":
            with contextlib.suppress(ValueError):
                domain = ArtifactDomain(item.domain)

        return Finding(
            id=finding_id,
            severity=item.severity,
            title=title,
            description=description,
            method_id=MethodId("#154"),
            pattern_id=PatternId(item.id),
            domain=domain,
            evidence=evidence,
        )

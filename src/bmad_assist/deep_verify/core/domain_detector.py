"""Domain detection for Deep Verify using LLM-based classification.

This module provides the DomainDetector class that classifies software
implementation artifacts into domains (SECURITY, STORAGE, TRANSFORM, etc.)
using LLM-based classification with caching and fallback support.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from bmad_assist.core.exceptions import ProviderError, ProviderTimeoutError
from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    DomainConfidence,
    DomainDetectionResult,
)
from bmad_assist.providers import ClaudeSDKProvider

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

DEFAULT_MODEL = "haiku"
DEFAULT_TIMEOUT = 30
CACHE_TTL_SECONDS = 86400  # 24 hours
MAX_ARTIFACT_LENGTH = 2000

# =============================================================================
# Domain Keywords for Fallback
# =============================================================================

DOMAIN_KEYWORDS: dict[ArtifactDomain, list[str]] = {
    ArtifactDomain.SECURITY: [
        "auth",
        "authentication",
        "authorization",
        "crypto",
        "cryptography",
        "secret",
        "token",
        "jwt",
        "oauth",
        "password",
        "hash",
        "encrypt",
        "decrypt",
        "signature",
        "hmac",
        "certificate",
        "tls",
        "ssl",
        "xss",
        "csrf",
        "injection",
        "sanitize",
        "validate",
        "permission",
        "role",
    ],
    ArtifactDomain.STORAGE: [
        "database",
        "db",
        "sql",
        "query",
        "transaction",
        "migration",
        "persist",
        "storage",
        "repository",
        "dao",
        "orm",
        "table",
        "index",
        "column",
        "row",
        "record",
        "blob",
        "jsonb",
        "postgres",
        "mysql",
        "sqlite",
        "mongo",
        "redis",
        "cache",
        "pool",
        "connection",
    ],
    ArtifactDomain.TRANSFORM: [
        "parse",
        "serialize",
        "deserialize",
        "marshal",
        "unmarshal",
        "transform",
        "convert",
        "map",
        "mapping",
        "template",
        "render",
        "format",
        "encode",
        "decode",
        "compress",
        "decompress",
        "csv",
        "xml",
        "yaml",
        "toml",
        "protobuf",
        "avro",
        "parquet",
        "etl",
        "pipeline",
        "stream",
        "batch",
    ],
    ArtifactDomain.CONCURRENCY: [
        "goroutine",
        "async",
        "await",
        "thread",
        "worker",
        "pool",
        "concurrent",
        "parallel",
        "mutex",
        "lock",
        "semaphore",
        "channel",
        "routine",
        "spawn",
        "fork",
        "join",
        "race",
        "deadlock",
        "atomic",
        "context",
        "cancel",
        "timeout",
        "retry",
        "backoff",
        "schedule",
        "cron",
        "job",
        "queue",
        "background",
    ],
    ArtifactDomain.API: [
        "http",
        "rest",
        "api",
        "endpoint",
        "route",
        "handler",
        "controller",
        "middleware",
        "request",
        "response",
        "header",
        "query",
        "param",
        "json",
        "xml",
        "graphql",
        "grpc",
        "websocket",
        "hook",
        "webhook",
        "client",
        "server",
        "url",
        "path",
        "method",
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "status",
        "code",
        "error",
        "rate",
        "limit",
    ],
    ArtifactDomain.MESSAGING: [
        "message",
        "queue",
        "pub",
        "sub",
        "publish",
        "subscribe",
        "topic",
        "event",
        "stream",
        "kafka",
        "rabbitmq",
        "sqs",
        "sns",
        "nats",
        "broker",
        "consumer",
        "producer",
        "listener",
        "handler",
        "delivery",
        "ack",
        "nack",
        "retry",
        "dlq",
        "dead",
        "letter",
        "ordering",
        "partition",
        "offset",
        "commit",
        "rollback",
    ],
    ArtifactDomain.PRD: [
        "requirement",
        "requirements",
        "prd",
        "user story",
        "acceptance criteria",
        "scope",
        "stakeholder",
        "feature",
        "epic",
        "backlog",
        "priority",
        "milestone",
        "deliverable",
        "use case",
        "persona",
        "mvp",
        "specification",
    ],
    ArtifactDomain.DOCUMENTATION: [
        "documentation",
        "readme",
        "changelog",
        "docstring",
        "jsdoc",
        "javadoc",
        "swagger",
        "openapi",
        "tutorial",
        "guide",
        "reference",
        "manual",
        "wiki",
        "annotation",
        "comment",
        "example",
        "usage",
    ],
}

# =============================================================================
# Utility Functions
# =============================================================================


def _extract_json(text: str) -> str:
    """Extract JSON from text, handling markdown code blocks.

    Args:
        text: Raw text that may contain JSON.

    Returns:
        Extracted JSON string.

    """
    # Try to extract from markdown code block
    pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()

    # Try to find JSON object directly with proper brace matching
    start = text.find("{")
    if start == -1:
        return text.strip()

    # Count braces to find matching closing brace (handles nesting)
    brace_count = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            brace_count += 1
        elif text[i] == "}":
            brace_count -= 1
            if brace_count == 0:
                return text[start : i + 1]

    # Return as-is if no JSON markers found
    return text.strip()


# =============================================================================
# System Prompt
# =============================================================================

DOMAIN_DETECTION_SYSTEM_PROMPT = """You are a domain classifier for software implementation artifacts.
Analyze the artifact and classify it into 1-4 domains that best describe its primary concerns.

Domains:
- SECURITY: Authentication, authorization, cryptography, secrets, tokens, signatures, HMAC, JWT, OAuth, passwords, hashing, encryption, certificates, TLS/SSL, XSS/CSRF prevention, input sanitization, permission/role management
- STORAGE: Database operations, SQL, transactions, persistence, migrations, ORM, repositories, connection pooling, indexing, querying, caching, Redis, PostgreSQL, MySQL, SQLite, MongoDB
- TRANSFORM: Data transformation, parsing, serialization, deserialization, marshaling, templates, mapping, CSV/XML/JSON/YAML processing, ETL pipelines, batch processing, streaming
- CONCURRENCY: Parallel execution, goroutines, async/await, threads, workers, mutexes, locks, semaphores, channels, race conditions, deadlocks, atomic operations, context cancellation, scheduling
- API: HTTP endpoints, REST APIs, webhooks, external service integration, request/response handling, middleware, routing, GraphQL, gRPC, WebSockets, rate limiting
- MESSAGING: Message queues, pub/sub, events, retries, dead letter queues (DLQ), Kafka, RabbitMQ, SQS, ordering guarantees, partitioning, consumers, producers

Rules:
- Return 1-4 most relevant domains (only include domains with confidence >= 0.3)
- Confidence must be 0.3-1.0 (higher = more certain)
- Include signals: specific terms/patterns from the text that indicate each domain
- Be selective - only include domains that are clearly relevant

Return JSON in this exact format:
{
    "domains": [
        {"name": "security", "confidence": 0.95, "signals": ["hmac", "signature", "secret"]},
        {"name": "api", "confidence": 0.75, "signals": ["webhook", "endpoint"]}
    ],
    "reasoning": "Brief explanation of why these domains were selected",
    "ambiguity": "none"  // One of: "none", "low", "medium", "high"
}"""

# Language hint template for domain detection
LANGUAGE_HINT_TEMPLATE = """
Artifact language: {language}

Consider language-specific patterns when detecting domains:
- Go: goroutines, channels, defer patterns, interface types, error handling patterns
- Python: asyncio, threading, decorators, context managers, list/dict comprehensions
- TypeScript/JavaScript: async/await, Promise patterns, event emitters, callback patterns
- Rust: ownership, borrowing, lifetimes, unsafe blocks, Result/Option types
- Java: interfaces, abstract classes, generics, streams, annotations
- Ruby: blocks, metaprogramming, mixins, symbols

Adjust domain confidence based on language idioms.
"""

# =============================================================================
# Pydantic Models for Response Validation
# =============================================================================


class DomainDetectionItem(BaseModel):
    """Single domain detection item from LLM response."""

    name: str = Field(..., description="Domain name (lowercase)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence 0.0-1.0")
    signals: list[str] = Field(default_factory=list, description="Indicator signals")

    @field_validator("name")
    @classmethod
    def validate_domain_name(cls, v: str) -> str:
        """Normalize domain name to lowercase."""
        return v.lower()


class DomainDetectionResponse(BaseModel):
    """Expected LLM response structure."""

    domains: list[DomainDetectionItem] = Field(..., max_length=4)
    reasoning: str = Field(..., min_length=10)
    ambiguity: str = Field(default="none")

    @field_validator("domains")
    @classmethod
    def filter_low_confidence(cls, v: list[DomainDetectionItem]) -> list[DomainDetectionItem]:
        """Filter out domains with confidence < 0.3.

        May return empty list — caller falls back to keyword detection.
        """
        return [d for d in v if d.confidence >= 0.3]

    @field_validator("ambiguity")
    @classmethod
    def validate_ambiguity(cls, v: str) -> str:
        """Validate ambiguity is one of allowed values."""
        allowed = {"none", "low", "medium", "high"}
        if v not in allowed:
            return "none"
        return v


# =============================================================================
# Serialization Helpers
# =============================================================================


def serialize_domain_detection_result(result: DomainDetectionResult) -> dict[str, Any]:
    """Serialize DomainDetectionResult to a dictionary for caching."""
    return {
        "domains": [
            {
                "domain": dc.domain.value,
                "confidence": dc.confidence,
                "signals": dc.signals,
            }
            for dc in result.domains
        ],
        "reasoning": result.reasoning,
        "ambiguity": result.ambiguity,
        "duration_ms": result.duration_ms,
    }


def deserialize_domain_detection_result(data: dict[str, Any]) -> DomainDetectionResult:
    """Deserialize dictionary to DomainDetectionResult."""
    domains_data = data.get("domains", [])
    domains = []
    for d in domains_data:
        domain_name = d.get("domain", "")
        # Handle both old format (string) and new format (ArtifactDomain)
        if isinstance(domain_name, str):
            try:
                domain_enum = ArtifactDomain(domain_name.lower())
            except ValueError:
                logger.warning("Unknown domain in cache: %s", domain_name)
                continue
        else:
            domain_enum = domain_name

        domains.append(
            DomainConfidence(
                domain=domain_enum,
                confidence=d.get("confidence", 0.5),
                signals=d.get("signals", []),
            )
        )

    return DomainDetectionResult(
        domains=domains,
        reasoning=data.get("reasoning", ""),
        ambiguity=data.get("ambiguity", "none"),
        duration_ms=data.get("duration_ms", 0),
    )


# =============================================================================
# Domain Detector Class
# =============================================================================


class DomainDetector:
    """LLM-based artifact domain detector for Deep Verify.

    This class classifies software implementation artifacts into domains
    (SECURITY, STORAGE, TRANSFORM, CONCURRENCY, API, MESSAGING) using
    LLM-based classification with caching and keyword fallback support.

    Attributes:
        project_root: Path to project root for cache storage.
        model: Model identifier to use for classification (default: "haiku").
        timeout: Timeout in seconds for LLM calls (default: 30).
        cache_enabled: Whether to enable result caching (default: True).
        llm_client: Optional LLMClient for managed LLM calls (retry, rate limiting, cost tracking).

    Example:
        >>> from pathlib import Path
        >>> from bmad_assist.deep_verify.core.domain_detector import DomainDetector
        >>> detector = DomainDetector(project_root=Path("."))
        >>> result = detector.detect("Function to verify JWT tokens")
        >>> print(result.domains[0].domain)
        ArtifactDomain.SECURITY

    """

    def __init__(
        self,
        project_root: Path,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
        cache_enabled: bool = True,
        llm_client: Any | None = None,
    ):
        """Initialize the domain detector.

        Args:
            project_root: Path to project root for cache storage.
            model: Model identifier to use (default: "haiku").
            timeout: Timeout in seconds for LLM calls (default: 30).
            cache_enabled: Whether to enable caching (default: True).
            llm_client: Optional LLMClient for managed LLM calls. If provided,
                        uses LLMClient for all LLM calls (with retry, rate limiting,
                        cost tracking). If not provided, uses direct provider.

        """
        self.project_root = project_root
        self.model = model
        self.timeout = timeout
        self.cache_enabled = cache_enabled
        self._llm_client = llm_client
        self._cache_dir = (
            project_root / ".bmad-assist" / "cache" / "deep-verify" / "domain-detection"
        )

        if cache_enabled:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Only create provider if LLMClient NOT provided
        self._provider: ClaudeSDKProvider | None
        if llm_client is None:
            self._provider = ClaudeSDKProvider()
        else:
            self._provider = None

    def __repr__(self) -> str:
        """Return masked representation for logging."""
        cache_status = "enabled" if self.cache_enabled else "disabled"
        return (
            f"DomainDetector(model={self.model!r}, timeout={self.timeout}s, "
            f"cache={cache_status}, project_root=***)"
        )

    # ========================================================================
    # Core Detection Method
    # ========================================================================

    def detect(
        self,
        artifact_text: str,
        language_hint: str | None = None,
    ) -> DomainDetectionResult:
        """Detect domains from artifact text.

        This is a synchronous method that classifies the artifact into domains.
        It first checks the cache, then calls the LLM if needed, with keyword
        fallback on failure.

        Args:
            artifact_text: The text content to classify.
            language_hint: Optional programming language hint (e.g., "go", "python")
                          to improve domain detection accuracy.

        Returns:
            DomainDetectionResult with detected domains, reasoning, and ambiguity.

        Example:
            >>> detector = DomainDetector(project_root=Path("."))
            >>> result = detector.detect("Verify JWT tokens and check permissions")
            >>> len(result.domains) >= 1
            True

            >>> result = detector.detect("func main() { ... }", language_hint="go")
            >>> len(result.domains) >= 0  # May detect CONCURRENCY for Go
            True

        """
        import time as time_module

        start_time = time_module.time()

        # Handle empty input
        if not artifact_text or not artifact_text.strip():
            return DomainDetectionResult(
                domains=[],
                reasoning="Empty artifact text provided",
                ambiguity="high",
            )

        # Truncate input
        truncated_text = artifact_text[:MAX_ARTIFACT_LENGTH]

        # Check cache first
        if self.cache_enabled:
            cache_key = self._get_cache_key(truncated_text, language_hint)
            cached = self._load_cached(cache_key)
            if cached is not None:
                logger.debug("Domain detection cache hit for key %s", cache_key[:8])
                return cached

        # Call LLM
        try:
            result = self._call_llm(truncated_text, language_hint)
        except (ProviderTimeoutError, ProviderError, ValueError) as e:
            logger.debug("Domain detection LLM returned unusable result: %s, using keyword fallback", e)
            result = self._fallback_keyword_detection(artifact_text)

        # Add duration
        duration_ms = int((time_module.time() - start_time) * 1000)

        # Reconstruct result with duration
        result = DomainDetectionResult(
            domains=result.domains,
            reasoning=result.reasoning,
            ambiguity=result.ambiguity,
            duration_ms=duration_ms,
        )

        # Save to cache
        if self.cache_enabled:
            cache_key = self._get_cache_key(truncated_text, language_hint)
            self._save_cached(cache_key, result)

        logger.debug(
            "Domain detection completed in %dms: %d domains detected",
            duration_ms,
            len(result.domains),
        )

        return result

    # ========================================================================
    # LLM Call
    # ========================================================================

    def _call_llm(
        self, artifact_text: str, language_hint: str | None = None
    ) -> DomainDetectionResult:
        """Call LLM for domain detection.

        Args:
            artifact_text: The text to classify (already truncated).
            language_hint: Optional programming language hint.

        Returns:
            DomainDetectionResult from LLM response.

        Raises:
            ProviderError: If LLM call fails.
            ProviderTimeoutError: If LLM call times out.

        """
        prompt = self._build_prompt(artifact_text, language_hint)

        if self._llm_client:
            # Use LLMClient for managed calls (async bridge)
            # CRITICAL: Use run_async_in_thread() instead of asyncio.run() to avoid
            # shutting down ThreadPoolExecutor when called via asyncio.to_thread()
            from bmad_assist.core.async_utils import run_async_in_thread

            result = run_async_in_thread(
                self._llm_client.invoke(
                    prompt=prompt,
                    model=self.model,
                    timeout=self.timeout,
                    method_id="domain_detection",
                )
            )
            raw_response = result.stdout
        else:
            # Use direct provider (backward compatible)
            # _provider is always set when _llm_client is None (see __init__)
            assert self._provider is not None
            result = self._provider.invoke(
                prompt=prompt,
                model=self.model,
                timeout=self.timeout,
            )
            raw_response = self._provider.parse_output(result)

        return self._parse_response(raw_response)

    def _build_prompt(self, artifact_text: str, language_hint: str | None = None) -> str:
        """Build the prompt for LLM classification.

        Args:
            artifact_text: The text to classify.
            language_hint: Optional programming language hint.

        Returns:
            Formatted prompt string.

        """
        prompt_parts = [DOMAIN_DETECTION_SYSTEM_PROMPT]

        # Add language hint if provided
        if language_hint:
            prompt_parts.append(LANGUAGE_HINT_TEMPLATE.format(language=language_hint))

        prompt_parts.extend(
            [
                "",
                "Artifact to classify:",
                "---",
                artifact_text,
                "---",
            ]
        )

        return "\n".join(prompt_parts)

    def _parse_response(self, raw_response: str) -> DomainDetectionResult:
        """Parse LLM response into DomainDetectionResult.

        Args:
            raw_response: Raw text response from LLM.

        Returns:
            Parsed DomainDetectionResult.

        Raises:
            ValueError: If response cannot be parsed.

        """
        # Extract JSON from markdown code blocks if present
        json_str = _extract_json(raw_response)

        try:
            # Parse with Pydantic
            parsed = DomainDetectionResponse.model_validate_json(json_str)

            # Convert to DomainDetectionResult
            domains = []
            for item in parsed.domains:
                try:
                    domain_enum = ArtifactDomain(item.name)
                    domains.append(
                        DomainConfidence(
                            domain=domain_enum,
                            confidence=item.confidence,
                            signals=item.signals,
                        )
                    )
                except ValueError:
                    logger.debug("Unknown domain from LLM: %s", item.name)
                    continue

            # All domains filtered out (low confidence) — let caller use fallback
            if not domains:
                logger.debug(
                    "LLM returned no domains above confidence threshold, "
                    "falling back to keyword detection"
                )
                raise ValueError("No domains above confidence threshold")

            return DomainDetectionResult(
                domains=domains,
                reasoning=parsed.reasoning,
                ambiguity=parsed.ambiguity,  # type: ignore[arg-type]
            )

        except ValueError:
            raise
        except Exception as e:
            logger.debug("Failed to parse LLM response: %s", e)
            raise ValueError(f"Invalid LLM response format: {e}") from e

    # ========================================================================
    # Caching
    # ========================================================================

    def _get_cache_key(self, artifact_text: str, language_hint: str | None = None) -> str:
        """Generate SHA256 cache key from model + artifact text + language hint.

        Args:
            artifact_text: Text to hash.
            language_hint: Optional language hint to include in key.

        Returns:
            SHA256 hex digest string.

        """
        content = f"{self.model}:{language_hint or ''}:{artifact_text}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _load_cached(self, cache_key: str) -> DomainDetectionResult | None:
        """Load cached result if exists and not expired.

        Args:
            cache_key: Cache key to look up.

        Returns:
            Cached DomainDetectionResult or None if not found/expired.

        """
        cache_path = self._cache_dir / f"{cache_key}.json"
        if not cache_path.exists():
            return None

        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))

            # Check TTL
            cached_time_str = data.get("timestamp")
            if cached_time_str:
                cached_time = datetime.fromisoformat(cached_time_str)
                age_seconds = (datetime.now(UTC) - cached_time).total_seconds()
                if age_seconds > CACHE_TTL_SECONDS:
                    logger.debug("Cache entry expired for key %s", cache_key[:8])
                    return None

            # Deserialize result
            result_data = data.get("result", {})
            return deserialize_domain_detection_result(result_data)

        except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
            logger.warning("Cache load failed for key %s: %s", cache_key[:8], e)
            return None

    def _save_cached(self, cache_key: str, result: DomainDetectionResult) -> None:
        """Save result to cache with atomic write.

        Args:
            cache_key: Cache key to save under.
            result: Result to cache.

        """
        cache_path = self._cache_dir / f"{cache_key}.json"
        temp_path = cache_path.with_suffix(".tmp")

        data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "model": self.model,
            "result": serialize_domain_detection_result(result),
        }

        try:
            temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.rename(temp_path, cache_path)
            logger.debug("Cached result for key %s", cache_key[:8])
        except OSError as e:
            logger.warning("Cache save failed for key %s: %s", cache_key[:8], e)
            # Clean up temp file if it exists
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass

    # ========================================================================
    # Keyword Fallback
    # ========================================================================

    def _fallback_keyword_detection(self, text: str) -> DomainDetectionResult:
        """Fallback domain detection using keyword matching.

        Args:
            text: Artifact text to analyze.

        Returns:
            DomainDetectionResult from keyword analysis.

        """
        # Normalize text for keyword matching
        normalized = self._normalize_text(text)
        words = set(normalized.split())

        # Count matches per domain
        domain_scores: dict[ArtifactDomain, int] = {}
        domain_signals: dict[ArtifactDomain, list[str]] = {}

        for domain, keywords in DOMAIN_KEYWORDS.items():
            matches = []
            for keyword in keywords:
                # Check for exact keyword match in words (not substring)
                keyword_lower = keyword.lower()
                for word in words:
                    if keyword_lower == word.lower():
                        matches.append(keyword)
                        break

            if matches:
                domain_scores[domain] = len(matches)
                domain_signals[domain] = matches[:5]  # Limit signals

        # Calculate confidence based on match count (normalize, cap at 0.9 for fallback)
        domains = []
        if domain_scores:
            max_score = max(domain_scores.values())
            for domain, score in sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)[
                :4
            ]:  # Max 4 domains
                confidence = min(0.3 + (score / max(max_score, 1)) * 0.6, 0.9)
                domains.append(
                    DomainConfidence(
                        domain=domain,
                        confidence=confidence,
                        signals=domain_signals.get(domain, []),
                    )
                )

        reasoning = (
            "Domain detection via keyword-based fallback (LLM unavailable)"
            if domains
            else "No domains detected via keyword fallback"
        )

        return DomainDetectionResult(
            domains=domains,
            reasoning=reasoning,
            ambiguity="high",
        )

    def _normalize_text(self, text: str) -> str:
        """Normalize text for keyword matching.

        Args:
            text: Raw text.

        Returns:
            Normalized lowercase text.

        """
        # Normalize unicode
        normalized = unicodedata.normalize("NFKD", text)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        # Convert to lowercase
        normalized = normalized.lower()
        # Replace non-alphanumeric with spaces
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        return normalized.strip()


# =============================================================================
# Convenience Functions
# =============================================================================


def detect_domains(
    artifact_text: str,
    project_root: Path | None = None,
    model: str = DEFAULT_MODEL,
    language_hint: str | None = None,
) -> DomainDetectionResult:
    """Convenience function to detect domains without creating a detector instance.

    Args:
        artifact_text: Text to classify.
        project_root: Project root path for caching (default: current directory).
        model: Model to use (default: "haiku").
        language_hint: Optional programming language hint.

    Returns:
        DomainDetectionResult with detected domains.

    Example:
        >>> result = detect_domains("Verify JWT tokens")
        >>> len(result.domains) >= 0
        True

        >>> result = detect_domains("func main() {}", language_hint="go")
        >>> len(result.domains) >= 0
        True

    """
    if project_root is None:
        project_root = Path(".")

    detector = DomainDetector(project_root=project_root, model=model)
    return detector.detect(artifact_text, language_hint=language_hint)

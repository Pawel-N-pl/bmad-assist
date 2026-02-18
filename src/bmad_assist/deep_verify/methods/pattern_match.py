"""Pattern Match Method (#153) for Deep Verify.

This module implements the Pattern Match verification method that detects
known antipatterns via signal matching against a pattern library.

Method #153 is one of two methods that always run regardless of domain
detection results (the other being #154 Boundary Analysis).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bmad_assist.deep_verify.core.types import MethodId
from bmad_assist.deep_verify.methods.base import BaseVerificationMethod
from bmad_assist.deep_verify.patterns.library import PatternLibrary, get_default_pattern_library
from bmad_assist.deep_verify.patterns.matcher import PatternMatcher
from bmad_assist.deep_verify.patterns.types import PatternMatchResult

if TYPE_CHECKING:
    from bmad_assist.deep_verify.core.types import (
        ArtifactDomain,
        Evidence,
        Finding,
        Pattern,
    )

logger = logging.getLogger(__name__)


class PatternMatchMethod(BaseVerificationMethod):
    """Pattern Match Method (#153) - Detects known antipatterns via signal matching.

    This method analyzes artifact text against a library of patterns and returns
    findings for any patterns that match with sufficient confidence.

    Attributes:
        method_id: Unique method identifier "#153".
        _library: PatternLibrary containing patterns to match against.
        _threshold: Minimum confidence threshold for matches (0.0-1.0).

    Example:
        >>> from bmad_assist.deep_verify.patterns import get_default_pattern_library
        >>> library = get_default_pattern_library()
        >>> method = PatternMatchMethod(patterns=library.get_all_patterns())
        >>> findings = await method.analyze("code with race condition")
        >>> for f in findings:
        ...     print(f"{f.id}: {f.title}")

    """

    method_id: MethodId

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        threshold: float = 0.25,
    ) -> None:
        """Initialize the Pattern Match Method.

        Args:
            patterns: Optional list of patterns to use. If None, loads default
                patterns from the pattern library.
            threshold: Minimum confidence threshold for matches (default 0.25).
                Must be between 0.0 and 1.0.

        Raises:
            ValueError: If threshold is not between 0.0 and 1.0.

        """
        self.method_id = MethodId("#153")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be between 0.0 and 1.0, got {threshold}")
        self._threshold = threshold

        if patterns is not None:
            # Create a library from provided patterns
            self._library = PatternLibrary()
            self._library._patterns = {p.id: p for p in patterns}
        else:
            # Load default patterns
            self._library = get_default_pattern_library()

    def __repr__(self) -> str:
        """Return a string representation of the method."""
        pattern_count = len(self._library)
        return f"PatternMatchMethod(method_id='#153', patterns={pattern_count}, threshold={self._threshold:.2f})"

    async def analyze(
        self,
        artifact_text: str,
        **kwargs: dict[str, object],
    ) -> list[Finding]:
        """Analyze artifact text and return pattern match findings.

        Args:
            artifact_text: The text content to analyze for patterns.
            **kwargs: Additional context including:
                - domains: Optional list[ArtifactDomain] to filter patterns
                - context: Optional VerificationContext with language hint
                - config: Optional DeepVerifyConfig (not used currently)

        Returns:
            List of Finding objects for patterns that matched with
            confidence >= threshold. Findings have temporary IDs "#153-F1",
            "#153-F2", etc. which will be reassigned by DeepVerifyEngine.

        """
        if not artifact_text or not artifact_text.strip():
            logger.debug("Empty artifact text, returning no findings")
            return []

        try:
            # Extract domains and context from kwargs for filtering
            domains: list[ArtifactDomain] | None = kwargs.get("domains")  # type: ignore[assignment]
            context = kwargs.get("context")
            language = getattr(context, "language", None) if context else None

            # Get patterns - filtered by domain and/or language if specified
            if domains and language:
                patterns = self._library.get_patterns(domains=domains, language=language)
                logger.debug(
                    "Using %d patterns filtered by %d domains and language '%s' (from %d total)",
                    len(patterns),
                    len(domains),
                    language,
                    len(self._library),
                )
            elif domains:
                patterns = self._library.get_patterns(domains=domains)
                logger.debug(
                    "Using %d patterns filtered by %d domains (from %d total)",
                    len(patterns),
                    len(domains),
                    len(self._library),
                )
            elif language:
                patterns = self._library.get_patterns(language=language)
                logger.debug(
                    "Using %d patterns filtered by language '%s' (from %d total)",
                    len(patterns),
                    language,
                    len(self._library),
                )
            else:
                patterns = self._library.get_all_patterns()
                logger.debug("Using all %d patterns", len(patterns))

            if not patterns:
                return []

            # Create matcher and run pattern matching
            matcher = PatternMatcher(patterns, threshold=self._threshold)
            match_results = matcher.match(artifact_text)

            logger.debug(
                "Pattern matching found %d matches above threshold %.2f",
                len(match_results),
                self._threshold,
            )

            # Convert match results to findings
            findings: list[Finding] = []
            for idx, result in enumerate(match_results):
                finding = self._convert_match_to_finding(result, idx)
                findings.append(finding)

            return findings

        except (ValueError, TypeError, RuntimeError, AttributeError) as e:
            logger.warning("Pattern matching failed: %s", e, exc_info=True)
            return []

    def _convert_match_to_finding(
        self,
        result: PatternMatchResult,
        index: int,
    ) -> Finding:
        """Convert a PatternMatchResult to a Finding.

        Args:
            result: The pattern match result to convert.
            index: The finding index for ID generation.

        Returns:
            Finding object with evidence from matched signals.

        """
        from bmad_assist.deep_verify.core.types import Finding

        pattern = result.pattern

        # Generate temporary finding ID (Engine will reassign final IDs)
        finding_id = f"#153-F{index + 1}"

        # Build description - include remediation if available
        description = pattern.description or "Pattern matched"
        if pattern.remediation:
            description = f"{description}\n\nRemediation: {pattern.remediation}"

        # Create evidence from matched signals
        evidence = self._create_evidence_from_match(result)

        # Truncate title to 80 characters if needed (AC-2)
        title = pattern.description or f"Pattern {pattern.id} matched"
        if len(title) > 80:
            title = title[:77] + "..."

        return Finding(
            id=finding_id,
            severity=pattern.severity,
            title=title,
            description=description,
            method_id=MethodId("#153"),
            pattern_id=pattern.id,
            domain=pattern.domain,
            evidence=evidence,
        )

    def _create_evidence_from_match(
        self,
        result: PatternMatchResult,
    ) -> list[Evidence]:
        """Create Evidence objects from a PatternMatchResult.

        Args:
            result: The pattern match result containing matched signals.

        Returns:
            List of Evidence objects, one per matched signal.

        """
        from bmad_assist.deep_verify.core.types import Evidence

        evidence: list[Evidence] = []

        for matched_signal in result.matched_signals:
            # Use matched text as quote, fallback to pattern text if empty
            quote = matched_signal.matched_text or matched_signal.signal.pattern

            evidence.append(
                Evidence(
                    quote=quote,
                    line_number=matched_signal.line_number,
                    source=result.pattern.id,
                    confidence=result.confidence,
                )
            )

        return evidence

    # =========================================================================
    # Batch Interface
    # =========================================================================

    @property
    def supports_batch(self) -> bool:
        """Whether this method supports batch mode."""
        return True

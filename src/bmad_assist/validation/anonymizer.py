"""Validation output anonymizer for Multi-LLM synthesis.

This module anonymizes validation outputs from multiple LLM providers
(Claude, Gemini, GPT, Master) before Master LLM synthesizes them.
Anonymization prevents provider bias during evaluation.

Key features:
- Replaces provider names with Validator A, B, C, D (randomized per call)
- Neutralizes self-referential patterns in content
- Preserves code blocks and technical content
- Persists mapping for post-synthesis deanonymization

Usage:
    from bmad_assist.validation import anonymize_validations, ValidationOutput

    outputs = [
        ValidationOutput(provider="claude", model="claude-sonnet-4", ...),
        ValidationOutput(provider="gemini", model="gemini-2.5-pro", ...),
    ]

    anonymized, mapping = anonymize_validations(outputs)
    save_mapping(mapping, project_root)
"""

import json
import logging
import os
import random
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "ValidationOutput",
    "AnonymizedValidation",
    "AnonymizationMapping",
    "anonymize_validations",
    "save_mapping",
    "get_mapping",
]


@dataclass(frozen=True)
class ValidationOutput:
    """Output from a single LLM validation pass.

    Attributes:
        provider: Provider identifier (e.g., "claude", "gemini", "gpt", "master").
        model: Model identifier (e.g., "claude-sonnet-4", "gemini-2.5-pro").
        content: Full validation output text.
        timestamp: When validation completed.
        duration_ms: Validation execution time in milliseconds.
        token_count: Token count of validation output.
        provider_session_id: Session/thread ID from provider for traceability.
            Links to debug JSONL files at debug/json/{timestamp}-{session_id}.jsonl.

    """

    provider: str
    model: str
    content: str
    timestamp: datetime
    duration_ms: int
    token_count: int
    provider_session_id: str | None = None


@dataclass(frozen=True)
class AnonymizedValidation:
    """Anonymized validation ready for synthesis.

    Attributes:
        validator_id: Anonymous identifier (Validator A, Validator B, etc.).
        content: Anonymized content (provider references neutralized).
        original_ref: UUID for mapping lookup.

    """

    validator_id: str
    content: str
    original_ref: str


@dataclass(frozen=True)
class AnonymizationMapping:
    """Mapping from anonymous IDs to original providers.

    Attributes:
        session_id: Unique session identifier (UUID).
        timestamp: When anonymization occurred.
        mapping: Dictionary mapping validator IDs to provider metadata.

    """

    session_id: str
    timestamp: datetime
    mapping: dict[str, dict[str, Any]]


def anonymize_validations(
    outputs: list[ValidationOutput],
    run_timestamp: datetime | None = None,
) -> tuple[list[AnonymizedValidation], AnonymizationMapping]:
    """Anonymize validation outputs for synthesis.

    Randomizes assignment of Validator A/B/C/D to prevent bias.

    Args:
        outputs: List of validation outputs from different providers.
        run_timestamp: Unified timestamp for this validation run. If None, uses now().

    Returns:
        Tuple of (anonymized_validations, mapping).

    Raises:
        ValueError: If more than 26 validators provided.

    """
    logger.debug("Anonymizing %d validation outputs", len(outputs))

    # Use unified run timestamp for consistency across all validation artifacts
    timestamp = run_timestamp or datetime.now(UTC)

    # Maximum 26 validators (A-Z)
    max_validators = 26
    if len(outputs) > max_validators:
        raise ValueError(
            f"Cannot anonymize more than {max_validators} validators. Received {len(outputs)}."
        )

    # Handle empty input
    if not outputs:
        logger.debug("Empty input, returning empty result")
        return [], AnonymizationMapping(
            session_id=str(uuid.uuid4()),
            timestamp=timestamp,
            mapping={},
        )

    # Create shuffled validator IDs (Validator A, B, C, ...)
    # Shuffle prevents model bias - synthesizer doesn't know which provider is which
    validator_ids = [f"Validator {chr(65 + i)}" for i in range(len(outputs))]
    random.shuffle(validator_ids)

    anonymized: list[AnonymizedValidation] = []
    mapping_data: dict[str, dict[str, Any]] = {}

    for output, validator_id in zip(outputs, validator_ids, strict=True):
        # Use provider_session_id as original_ref for traceability to debug JSONL files
        # Falls back to UUID if provider didn't return session_id
        original_ref = output.provider_session_id or str(uuid.uuid4())
        logger.debug(
            "Assigned %s to %s/%s (ref=%s)",
            validator_id,
            output.provider,
            output.model,
            original_ref[:16],
        )

        # Neutralize provider patterns in content
        anonymized_content = _neutralize_provider_patterns(
            output.content, output.provider, output.model
        )

        anonymized.append(
            AnonymizedValidation(
                validator_id=validator_id,
                content=anonymized_content,
                original_ref=original_ref,
            )
        )

        mapping_data[validator_id] = {
            "provider": output.provider,
            "model": output.model,
            "original_ref": original_ref,
            "provider_session_id": output.provider_session_id,  # For debug JSONL lookup
            "timestamp": output.timestamp.isoformat(),
            "duration_ms": output.duration_ms,
            "token_count": output.token_count,
        }

    session_id = str(uuid.uuid4())
    logger.debug("Anonymization complete. Session ID: %s", session_id)
    return anonymized, AnonymizationMapping(
        session_id=session_id,
        timestamp=timestamp,
        mapping=mapping_data,
    )


def _get_provider_patterns(provider: str) -> list[tuple[str, str]]:
    """Return regex patterns specific to a provider.

    Args:
        provider: Provider identifier (e.g., "claude", "gemini", "gpt").

    Returns:
        List of (pattern, replacement) tuples for regex substitution.

    """
    patterns: list[tuple[str, str]] = []

    # Map provider names to pattern sets
    provider_names: dict[str, list[str]] = {
        "claude": ["Claude"],
        "gemini": ["Gemini"],
        "gpt": ["GPT"],
        "master": ["Claude", "GPT", "Gemini"],  # Master could be any, neutralize all
    }

    names = provider_names.get(provider.lower(), [provider.capitalize()])

    for name in names:
        # Self-referential patterns
        patterns.extend(
            [
                (rf"\bAs {name}\b", "As a validator"),
                (rf"\bI'm {name}\b", "I'm a validator"),
                (rf"\bI am {name}\b", "I am a validator"),
            ]
        )

        # Verb forms - common verbs validators might use
        verb_pattern = (
            rf"\b{name} (believes|notes|suggests|finds|identifies|recommends|detects|"
            rf"observes|thinks|points out|argues|claims|asserts|proposes|concludes|"
            rf"determines|discovers|notices|highlights)\b"
        )
        patterns.append((verb_pattern, r"The validator \1"))

        # Possessive patterns
        possessive_pattern = (
            rf"\b{name}'s (analysis|assessment|review|findings|view|opinion|approach|"
            rf"recommendation|conclusion|suggestion|evaluation|perspective|insight|"
            rf"critique|observation)\b"
        )
        patterns.append((possessive_pattern, r"The validator's \1"))

        # Attribution patterns
        patterns.extend(
            [
                (rf"\bAccording to {name}\b", "According to the validator"),
                (rf"\bIn {name}'s (view|opinion|analysis)\b", r"In the validator's \1"),
                (rf"\bPer {name}'s (analysis|assessment)\b", r"Per the validator's \1"),
            ]
        )

    # Generic AI patterns (always apply)
    patterns.extend(
        [
            (r"\bAs an AI developed by \w+\b", "As a validator"),
            (r"\bAs an AI language model\b", "As a validator"),
            (r"\bAs an AI\b", "As a validator"),
            (r"\bAs a language model\b", "As a validator"),
        ]
    )

    # Model name patterns - only apply to matching provider to preserve cross-validator refs
    # (e.g., if Claude mentions "GPT-5", that reference should be preserved)
    provider_lower = provider.lower()
    if provider_lower in {"claude", "master"}:
        patterns.append((r"\bClaude (Sonnet|Opus|Haiku) \d+(\.\d+)?\b", "the validation model"))
    if provider_lower in {"gpt", "master"}:
        patterns.append((r"\bGPT-?\d+(\.\d+)?(-\w+)?\b", "the validation model"))
    if provider_lower in {"gemini", "master"}:
        patterns.append((r"\bGemini \d+(\.\d+)?( Pro| Flash)?\b", "the validation model"))

    return patterns


def _neutralize_provider_patterns(content: str, provider: str, model: str) -> str:
    """Neutralize provider-identifying patterns in content.

    Preserves code blocks (```...```) and inline code (`...`) to avoid
    breaking code examples.

    Args:
        content: Original validation content.
        provider: Provider identifier (e.g., "claude", "gemini", "gpt").
        model: Model identifier (e.g., "claude-sonnet-4").

    Returns:
        Content with provider references neutralized.

    """
    if not content:
        return content

    patterns = _get_provider_patterns(provider)

    # Split by fenced code blocks first
    # Pattern matches ``` with optional language tag
    fenced_pattern = re.compile(r"(```[^\n]*\n[\s\S]*?```)")
    parts = fenced_pattern.split(content)

    result: list[str] = []

    for part in parts:
        if part.startswith("```"):
            # Fenced code block - preserve exactly
            result.append(part)
        else:
            # Non-fenced: also preserve inline code
            inline_pattern = re.compile(r"(`[^`]+`)")
            inline_parts = inline_pattern.split(part)
            processed: list[str] = []

            for inline_part in inline_parts:
                if inline_part.startswith("`") and inline_part.endswith("`"):
                    # Inline code - preserve exactly
                    processed.append(inline_part)
                else:
                    # Prose text - apply neutralization
                    text = inline_part
                    for pattern, replacement in patterns:
                        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
                    processed.append(text)

            result.append("".join(processed))

    return "".join(result)


def save_mapping(mapping: AnonymizationMapping, project_root: Path) -> Path:
    """Save anonymization mapping to cache directory.

    Uses atomic write pattern (temp + os.replace) for crash safety.
    Matches pattern from core/state.py for cross-platform compatibility.

    Args:
        mapping: AnonymizationMapping to persist.
        project_root: Project root directory.

    Returns:
        Path to saved mapping file.

    """
    cache_dir = project_root / ".bmad-assist" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    filename = f"validation-mapping-{mapping.session_id}.json"
    target_path = cache_dir / filename
    temp_path = cache_dir / f"{filename}.tmp"

    data = {
        "session_id": mapping.session_id,
        "timestamp": mapping.timestamp.isoformat(),
        "mapping": mapping.mapping,
    }

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # os.replace() is atomic and works cross-platform (unlike os.rename on Windows)
        os.replace(temp_path, target_path)
        logger.info("Saved anonymization mapping to %s", target_path)
        return target_path
    except OSError:
        # Clean up temp file if it exists
        if temp_path.exists():
            temp_path.unlink()
        raise  # Re-raise - let caller handle OS errors


def get_mapping(session_id: str, project_root: Path) -> AnonymizationMapping | None:
    """Retrieve anonymization mapping by session ID.

    Args:
        session_id: Session ID to look up.
        project_root: Project root directory.

    Returns:
        AnonymizationMapping if found and valid, None otherwise.

    """
    cache_dir = project_root / ".bmad-assist" / "cache"
    file_path = cache_dir / f"validation-mapping-{session_id}.json"

    # Return None if file doesn't exist (graceful handling)
    if not file_path.exists():
        return None

    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        # Handle empty file
        if not content.strip():
            logger.warning(f"Mapping file is empty: {file_path}")
            return None

        data = json.loads(content)

    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in mapping file {file_path}: {e}")
        return None
    except OSError as e:
        logger.warning(f"Cannot read mapping file {file_path}: {e}")
        return None

    # Validate schema - required keys: session_id, timestamp, mapping
    return _validate_and_parse_mapping(data, file_path)


def _validate_and_parse_mapping(
    data: dict[str, Any], file_path: Path
) -> AnonymizationMapping | None:
    """Validate mapping schema and parse to dataclass.

    Args:
        data: Parsed JSON data.
        file_path: Path to the file (for logging).

    Returns:
        AnonymizationMapping if valid, None otherwise.

    """
    # Check required keys exist
    required_keys = ["session_id", "timestamp", "mapping"]
    for key in required_keys:
        if key not in data:
            logger.warning(f"Missing required key '{key}' in mapping file {file_path}")
            return None

    # Validate types
    if not isinstance(data["session_id"], str):
        logger.warning(f"Invalid session_id type in mapping file {file_path}")
        return None

    if not isinstance(data["mapping"], dict):
        logger.warning(f"Invalid mapping type in mapping file {file_path}")
        return None

    # Parse timestamp (handle both +00:00 and Z suffix formats)
    try:
        ts = data["timestamp"]
        if isinstance(ts, str) and ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        timestamp = datetime.fromisoformat(ts)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid timestamp format in mapping file {file_path}: {e}")
        return None

    return AnonymizationMapping(
        session_id=data["session_id"],
        timestamp=timestamp,
        mapping=data["mapping"],
    )

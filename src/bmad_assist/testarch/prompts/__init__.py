"""Package resources for testarch prompts.

This package contains prompt templates for the Test Architect module.
These are bundled as package resources and loaded via importlib.resources.

Available prompts:
- atdd_eligibility.xml: ATDD eligibility assessment prompt template

Available functions:
- get_eligibility_prompt(): Load eligibility prompt template
- parse_eligibility_response(): Parse and validate LLM response

Available models:
- ATDDEligibilityOutput: Pydantic model for validated LLM response
"""

import re
from importlib import resources

from pydantic import BaseModel, Field

__all__ = ["get_eligibility_prompt", "ATDDEligibilityOutput", "parse_eligibility_response"]

# Regex to extract JSON from markdown code blocks or raw content
# Handles: ```json {...} ```, ``` {...} ```, or raw {...}
# Case-insensitive for language tag, captures content between outermost braces
_JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.IGNORECASE | re.DOTALL)
_RAW_JSON_PATTERN = re.compile(r"(\{.*\})", re.DOTALL)


class ATDDEligibilityOutput(BaseModel):
    """Validated LLM output for ATDD eligibility assessment.

    Attributes:
        ui_score: UI involvement score (0.0-1.0)
        api_score: API involvement score (0.0-1.0)
        testability_score: General testability score (0.0-1.0)
        skip_score: Skip indicator score (0.0-1.0)
        reasoning: Explanation of assessment

    """

    ui_score: float = Field(ge=0.0, le=1.0, description="UI involvement score")
    api_score: float = Field(ge=0.0, le=1.0, description="API involvement score")
    testability_score: float = Field(default=0.0, ge=0.0, le=1.0, description="General testability score")
    skip_score: float = Field(ge=0.0, le=1.0, description="Skip indicator score")
    reasoning: str = Field(..., min_length=1, description="Explanation of assessment")


def parse_eligibility_response(llm_output: str) -> ATDDEligibilityOutput:
    """Parse and validate LLM response.

    Extracts JSON from markdown code blocks or raw content using regex.
    Handles preamble text, uppercase language tags, and various formatting.

    Args:
        llm_output: Raw LLM output string (may contain markdown code blocks)

    Returns:
        Validated ATDDEligibilityOutput model

    Raises:
        pydantic.ValidationError: If JSON is invalid, scores are out of range,
            or required fields are missing.

    """
    cleaned = llm_output.strip()

    # Try to extract JSON from markdown code block first
    match = _JSON_BLOCK_PATTERN.search(cleaned)
    if match:
        cleaned = match.group(1).strip()
    else:
        # Fall back to extracting raw JSON object
        match = _RAW_JSON_PATTERN.search(cleaned)
        if match:
            cleaned = match.group(1).strip()

    return ATDDEligibilityOutput.model_validate_json(cleaned)


def get_eligibility_prompt() -> str:
    """Load ATDD eligibility prompt template from package resources.

    The returned template contains a {story_content} placeholder that must be
    substituted by the caller via .format(story_content=...).

    Returns:
        Raw XML prompt template string with placeholder.

    Raises:
        FileNotFoundError: If prompt file or package is missing (broken installation).

    """
    try:
        prompt_file = resources.files("bmad_assist.testarch.prompts").joinpath(
            "atdd_eligibility.xml"
        )
        return prompt_file.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as e:
        raise FileNotFoundError(
            "ATDD eligibility prompt not found. "
            "This may indicate a broken installation. "
            "Please reinstall bmad-assist."
        ) from e

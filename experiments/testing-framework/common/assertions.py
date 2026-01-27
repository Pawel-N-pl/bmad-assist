"""
Reusable assertion helpers for behavioral tests.

These assertions focus on verifying external behavior
without coupling to implementation details.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx


def assert_response_ok(response: httpx.Response, msg: str = "") -> None:
    """Assert response has 2xx status code."""
    prefix = f"{msg}: " if msg else ""
    assert 200 <= response.status_code < 300, (
        f"{prefix}Expected 2xx status, got {response.status_code}. "
        f"Body: {response.text[:200]}"
    )


def assert_status_code(
    response: httpx.Response,
    expected: int | list[int],
    msg: str = "",
) -> None:
    """Assert response has specific status code(s)."""
    if isinstance(expected, int):
        expected = [expected]

    prefix = f"{msg}: " if msg else ""
    assert response.status_code in expected, (
        f"{prefix}Expected status {expected}, got {response.status_code}. "
        f"Body: {response.text[:200]}"
    )


def assert_json_response(
    response: httpx.Response,
    required_fields: list[str] | None = None,
    msg: str = "",
) -> dict[str, Any]:
    """
    Assert response is valid JSON and optionally contains required fields.

    Returns the parsed JSON data.
    """
    prefix = f"{msg}: " if msg else ""

    # Check content type
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type, (
        f"{prefix}Expected application/json content-type, got {content_type}"
    )

    # Parse JSON
    try:
        data = response.json()
    except Exception as e:
        raise AssertionError(
            f"{prefix}Failed to parse JSON response: {e}. Body: {response.text[:200]}"
        ) from e

    # Check required fields
    if required_fields:
        missing = [f for f in required_fields if f not in data]
        assert not missing, (
            f"{prefix}Response missing required fields: {missing}. Got: {list(data.keys())}"
        )

    return data


def assert_json_array(
    response: httpx.Response,
    min_length: int = 0,
    msg: str = "",
) -> list[Any]:
    """
    Assert response is a JSON array.

    Returns the parsed array.
    """
    data = assert_json_response(response, msg=msg)
    prefix = f"{msg}: " if msg else ""

    assert isinstance(data, list), f"{prefix}Expected JSON array, got {type(data).__name__}"

    if min_length > 0:
        assert len(data) >= min_length, (
            f"{prefix}Expected array with at least {min_length} items, got {len(data)}"
        )

    return data


def assert_error_response(
    response: httpx.Response,
    expected_status: int | list[int] | None = None,
    error_field: str = "error",
    msg: str = "",
) -> dict[str, Any]:
    """
    Assert response is an error response with expected status.

    Returns the parsed error data.
    """
    prefix = f"{msg}: " if msg else ""

    # Check status code indicates error
    if expected_status:
        assert_status_code(response, expected_status, msg)
    else:
        assert response.status_code >= 400, (
            f"{prefix}Expected error status (4xx/5xx), got {response.status_code}"
        )

    # Parse error body (may not always be JSON)
    try:
        data = response.json()
        if error_field:
            assert error_field in data, (
                f"{prefix}Error response missing '{error_field}' field. Got: {list(data.keys())}"
            )
        return data
    except Exception:
        # Some errors return plain text
        return {"error": response.text}


def assert_contains_text(response: httpx.Response, text: str, msg: str = "") -> None:
    """Assert response body contains specific text."""
    prefix = f"{msg}: " if msg else ""
    assert text in response.text, (
        f"{prefix}Response does not contain '{text}'. Body: {response.text[:200]}"
    )


def assert_header_present(
    response: httpx.Response,
    header: str,
    expected_value: str | None = None,
    msg: str = "",
) -> str:
    """
    Assert response has specific header, optionally with expected value.

    Returns the header value.
    """
    prefix = f"{msg}: " if msg else ""

    # Headers are case-insensitive
    value = response.headers.get(header)
    assert value is not None, f"{prefix}Response missing header: {header}"

    if expected_value is not None:
        assert value == expected_value, (
            f"{prefix}Header {header} has value '{value}', expected '{expected_value}'"
        )

    return value


# ============================================================================
# UI Assertions (for Playwright tests)
# ============================================================================


def assert_page_title_contains(page: Any, text: str, msg: str = "") -> None:
    """Assert page title contains text."""
    prefix = f"{msg}: " if msg else ""
    title = page.title()
    assert text.lower() in title.lower(), f"{prefix}Page title '{title}' does not contain '{text}'"


def assert_element_visible(page: Any, selector: str, timeout: int = 5000, msg: str = "") -> None:
    """Assert element is visible on page."""
    prefix = f"{msg}: " if msg else ""
    try:
        page.wait_for_selector(selector, state="visible", timeout=timeout)
    except Exception as e:
        raise AssertionError(f"{prefix}Element not visible: {selector}") from e


def assert_element_text(
    page: Any,
    selector: str,
    expected_text: str,
    msg: str = "",
) -> None:
    """Assert element contains expected text."""
    prefix = f"{msg}: " if msg else ""
    element = page.locator(selector)
    actual_text = element.text_content() or ""
    assert expected_text in actual_text, (
        f"{prefix}Element {selector} text '{actual_text}' does not contain '{expected_text}'"
    )


def assert_url_matches(page: Any, pattern: str, msg: str = "") -> None:
    """Assert current URL matches pattern (substring or regex)."""
    prefix = f"{msg}: " if msg else ""
    url = page.url
    assert pattern in url, f"{prefix}URL '{url}' does not match pattern '{pattern}'"

"""Tests for QuotaExhaustedError exception hierarchy."""

from bmad_assist.core.exceptions import (
    BmadAssistError,
    ProviderError,
    QuotaExhaustedError,
)


class TestQuotaExhaustedError:
    """Test QuotaExhaustedError class and inheritance."""

    def test_inherits_from_provider_error(self) -> None:
        """QuotaExhaustedError is a ProviderError."""
        assert issubclass(QuotaExhaustedError, ProviderError)

    def test_inherits_from_bmad_assist_error(self) -> None:
        """QuotaExhaustedError is also a BmadAssistError."""
        assert issubclass(QuotaExhaustedError, BmadAssistError)

    def test_can_be_raised_and_caught_as_provider_error(self) -> None:
        """Can catch QuotaExhaustedError via ProviderError handler."""
        try:
            raise QuotaExhaustedError("quota hit")
        except ProviderError:
            pass  # Expected

    def test_attributes_stored(self) -> None:
        """All attributes are stored correctly."""
        err = QuotaExhaustedError(
            "Gemini quota exhausted for model gemini-3-pro",
            provider_name="gemini",
            model="gemini-3-pro",
            stderr="Error when talking to Gemini API",
        )
        assert str(err) == "Gemini quota exhausted for model gemini-3-pro"
        assert err.provider_name == "gemini"
        assert err.model == "gemini-3-pro"
        assert err.stderr == "Error when talking to Gemini API"

    def test_default_attributes(self) -> None:
        """Attributes default to empty strings."""
        err = QuotaExhaustedError("quota hit")
        assert err.provider_name == ""
        assert err.model == ""
        assert err.stderr == ""

    def test_in_all_exports(self) -> None:
        """QuotaExhaustedError is in __all__."""
        from bmad_assist.core import exceptions

        assert "QuotaExhaustedError" in exceptions.__all__

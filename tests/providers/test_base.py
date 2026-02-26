"""Unit tests for BaseProvider ABC and ProviderResult dataclass.

Tests cover:
- AC1: BaseProvider inherits from ABC
- AC2: invoke() abstract method signature
- AC3: parse_output() abstract method signature
- AC4: supports_model() abstract method signature
- AC5: ProviderResult dataclass fields
- AC6: provider_name abstract property
- AC7: default_model property with None default
- AC8: providers package structure and exports
- AC9: ProviderError import from core.exceptions
- AC10: BaseProvider is not instantiable
- AC11: Concrete subclass can be created
"""

import inspect
from abc import ABC
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path

import pytest


class TestPackageExports:
    """Test AC8 and AC9: Package structure and exports."""

    def test_providers_package_exports_baseprovider(self) -> None:
        """Test AC8: BaseProvider exported from providers package."""
        from bmad_assist.providers import BaseProvider

        assert BaseProvider is not None

    def test_providers_package_exports_providerresult(self) -> None:
        """Test AC8: ProviderResult exported from providers package."""
        from bmad_assist.providers import ProviderResult

        assert ProviderResult is not None

    def test_providers_all_contains_exports(self) -> None:
        """Test AC8: __all__ contains expected exports."""
        from bmad_assist import providers

        assert hasattr(providers, "__all__")
        assert "BaseProvider" in providers.__all__
        assert "ProviderResult" in providers.__all__

    def test_providererror_importable_from_exceptions(self) -> None:
        """Test AC9: ProviderError can be imported from core.exceptions."""
        from bmad_assist.core.exceptions import ProviderError

        assert ProviderError is not None

    def test_providererror_inherits_from_bmadassisterror(self) -> None:
        """Test AC9: ProviderError inherits from BmadAssistError."""
        from bmad_assist.core.exceptions import BmadAssistError, ProviderError

        assert issubclass(ProviderError, BmadAssistError)


class TestProviderResult:
    """Test AC5: ProviderResult dataclass."""

    def test_providerresult_is_dataclass(self) -> None:
        """Test AC5: ProviderResult is a dataclass."""
        from bmad_assist.providers import ProviderResult

        assert is_dataclass(ProviderResult)

    def test_providerresult_is_frozen(self) -> None:
        """Test AC5: ProviderResult has frozen=True."""
        from bmad_assist.providers import ProviderResult

        result = ProviderResult(
            stdout="output",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="test",
            command=("test",),
        )

        with pytest.raises(FrozenInstanceError):
            result.stdout = "modified"  # type: ignore[misc]

    def test_providerresult_has_stdout_field(self) -> None:
        """Test AC5: ProviderResult has stdout: str field."""
        from bmad_assist.providers import ProviderResult

        field_names = {f.name: f.type for f in fields(ProviderResult)}
        assert "stdout" in field_names
        assert field_names["stdout"] == str

    def test_providerresult_has_stderr_field(self) -> None:
        """Test AC5: ProviderResult has stderr: str field."""
        from bmad_assist.providers import ProviderResult

        field_names = {f.name: f.type for f in fields(ProviderResult)}
        assert "stderr" in field_names
        assert field_names["stderr"] == str

    def test_providerresult_has_exit_code_field(self) -> None:
        """Test AC5: ProviderResult has exit_code: int field."""
        from bmad_assist.providers import ProviderResult

        field_names = {f.name: f.type for f in fields(ProviderResult)}
        assert "exit_code" in field_names
        assert field_names["exit_code"] == int

    def test_providerresult_has_duration_ms_field(self) -> None:
        """Test AC5: ProviderResult has duration_ms: int field."""
        from bmad_assist.providers import ProviderResult

        field_names = {f.name: f.type for f in fields(ProviderResult)}
        assert "duration_ms" in field_names
        assert field_names["duration_ms"] == int

    def test_providerresult_has_model_field(self) -> None:
        """Test AC5: ProviderResult has model: str | None field."""
        from bmad_assist.providers import ProviderResult

        field_names = {f.name: f.type for f in fields(ProviderResult)}
        assert "model" in field_names
        assert field_names["model"] == (str | None)

    def test_providerresult_has_command_field(self) -> None:
        """Test AC5: ProviderResult has command: tuple[str, ...] field."""
        from bmad_assist.providers import ProviderResult

        field_names = {f.name: f.type for f in fields(ProviderResult)}
        assert "command" in field_names
        assert field_names["command"] == tuple[str, ...]

    def test_providerresult_has_docstring(self) -> None:
        """Test AC5: ProviderResult has docstring explaining fields."""
        from bmad_assist.providers import ProviderResult

        assert ProviderResult.__doc__ is not None
        assert "stdout" in ProviderResult.__doc__
        assert "stderr" in ProviderResult.__doc__
        assert "exit_code" in ProviderResult.__doc__
        assert "duration_ms" in ProviderResult.__doc__
        assert "model" in ProviderResult.__doc__
        assert "command" in ProviderResult.__doc__

    def test_providerresult_can_be_created(self) -> None:
        """Test AC5: ProviderResult can be instantiated with all fields."""
        from bmad_assist.providers import ProviderResult

        result = ProviderResult(
            stdout="Hello, World!",
            stderr="",
            exit_code=0,
            duration_ms=1500,
            model="opus_4",
            command=("claude", "-p", "Hello"),
        )

        assert result.stdout == "Hello, World!"
        assert result.stderr == ""
        assert result.exit_code == 0
        assert result.duration_ms == 1500
        assert result.model == "opus_4"
        assert result.command == ("claude", "-p", "Hello")

    def test_providerresult_model_can_be_none(self) -> None:
        """Test AC5: ProviderResult model field accepts None."""
        from bmad_assist.providers import ProviderResult

        result = ProviderResult(
            stdout="output",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model=None,
            command=("test",),
        )

        assert result.model is None


class TestBaseProviderStructure:
    """Test AC1, AC6, AC7: BaseProvider class structure."""

    def test_baseprovider_inherits_from_abc(self) -> None:
        """Test AC1: BaseProvider inherits from abc.ABC."""
        from bmad_assist.providers import BaseProvider

        assert issubclass(BaseProvider, ABC)

    def test_baseprovider_has_class_docstring(self) -> None:
        """Test AC1: BaseProvider has class docstring."""
        from bmad_assist.providers import BaseProvider

        assert BaseProvider.__doc__ is not None
        assert "abstract" in BaseProvider.__doc__.lower()
        assert "provider" in BaseProvider.__doc__.lower()

    def test_provider_name_is_abstract_property(self) -> None:
        """Test AC6: provider_name is an abstract property."""
        from bmad_assist.providers import BaseProvider

        # Check it's a property
        assert isinstance(inspect.getattr_static(BaseProvider, "provider_name"), property)

        # Check it's abstract
        assert hasattr(BaseProvider.provider_name, "fget")
        fget = BaseProvider.provider_name.fget
        assert fget is not None
        assert getattr(fget, "__isabstractmethod__", False)

    def test_provider_name_returns_str(self) -> None:
        """Test AC6: provider_name property returns str."""
        from bmad_assist.providers import BaseProvider

        # Get the property's type hints from fget
        fget = BaseProvider.provider_name.fget
        assert fget is not None
        hints = fget.__annotations__
        assert hints.get("return") == str

    def test_provider_name_has_docstring(self) -> None:
        """Test AC6: provider_name has docstring."""
        from bmad_assist.providers import BaseProvider

        fget = BaseProvider.provider_name.fget
        assert fget is not None
        assert fget.__doc__ is not None
        assert "identifier" in fget.__doc__.lower()

    def test_default_model_is_property(self) -> None:
        """Test AC7: default_model is a property."""
        from bmad_assist.providers import BaseProvider

        assert isinstance(inspect.getattr_static(BaseProvider, "default_model"), property)

    def test_default_model_is_not_abstract(self) -> None:
        """Test AC7: default_model is NOT abstract (has default)."""
        from bmad_assist.providers import BaseProvider

        fget = BaseProvider.default_model.fget
        assert fget is not None
        # Should NOT be abstract - it has a concrete implementation
        assert not getattr(fget, "__isabstractmethod__", False)

    def test_default_model_returns_none_by_default(self) -> None:
        """Test AC7: default_model returns None by default."""
        from bmad_assist.providers import BaseProvider, ProviderResult

        # Create a concrete implementation to test default_model
        class MinimalProvider(BaseProvider):
            @property
            def provider_name(self) -> str:
                return "minimal"

            def invoke(
                self,
                prompt: str,
                *,
                model: str | None = None,
                timeout: int | None = None,
                settings_file: Path | None = None,
            ) -> ProviderResult:
                return ProviderResult(
                    stdout="",
                    stderr="",
                    exit_code=0,
                    duration_ms=0,
                    model=model,
                    command=(),
                )

            def parse_output(self, result: ProviderResult) -> str:
                return result.stdout

            def supports_model(self, model: str) -> bool:
                return True

        provider = MinimalProvider()
        assert provider.default_model is None

    def test_default_model_has_docstring(self) -> None:
        """Test AC7: default_model has docstring."""
        from bmad_assist.providers import BaseProvider

        fget = BaseProvider.default_model.fget
        assert fget is not None
        assert fget.__doc__ is not None
        assert "default" in fget.__doc__.lower()


class TestBaseProviderAbstractMethods:
    """Test AC2, AC3, AC4: Abstract method definitions."""

    def test_invoke_is_abstract_method(self) -> None:
        """Test AC2: invoke() is decorated with @abstractmethod."""
        from bmad_assist.providers import BaseProvider

        assert hasattr(BaseProvider.invoke, "__isabstractmethod__")
        assert BaseProvider.invoke.__isabstractmethod__

    def test_invoke_has_correct_signature(self) -> None:
        """Test AC2: invoke() has correct signature with keyword-only args."""
        from bmad_assist.providers import BaseProvider, ProviderResult

        sig = inspect.signature(BaseProvider.invoke)
        params = list(sig.parameters.keys())

        # Check parameter order
        assert params == [
            "self",
            "prompt",
            "model",
            "timeout",
            "settings_file",
            "cwd",
            "disable_tools",
            "allowed_tools",
            "no_cache",
            "color_index",
            "display_model",
            "thinking",
            "cancel_token",
            "reasoning_effort",
        ]

        # Check prompt is positional
        assert sig.parameters["prompt"].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD

        # Check keyword-only parameters
        assert sig.parameters["model"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["timeout"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["settings_file"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["cwd"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["disable_tools"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["allowed_tools"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["no_cache"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["color_index"].kind == inspect.Parameter.KEYWORD_ONLY

        # Check defaults
        assert sig.parameters["model"].default is None
        assert sig.parameters["timeout"].default is None
        assert sig.parameters["settings_file"].default is None
        assert sig.parameters["cwd"].default is None
        assert sig.parameters["disable_tools"].default is False
        assert sig.parameters["allowed_tools"].default is None
        assert sig.parameters["no_cache"].default is False
        assert sig.parameters["color_index"].default is None

        # Check return type
        assert sig.return_annotation == ProviderResult

    def test_invoke_has_google_style_docstring(self) -> None:
        """Test AC2: invoke() has Google-style docstring with Args/Returns/Raises."""
        from bmad_assist.providers import BaseProvider

        doc = BaseProvider.invoke.__doc__
        assert doc is not None
        assert "Args:" in doc
        assert "prompt" in doc
        assert "model" in doc
        assert "timeout" in doc
        assert "settings_file" in doc
        assert "Returns:" in doc
        assert "ProviderResult" in doc
        assert "Raises:" in doc
        assert "ProviderError" in doc

    def test_parse_output_is_abstract_method(self) -> None:
        """Test AC3: parse_output() is decorated with @abstractmethod."""
        from bmad_assist.providers import BaseProvider

        assert hasattr(BaseProvider.parse_output, "__isabstractmethod__")
        assert BaseProvider.parse_output.__isabstractmethod__

    def test_parse_output_has_correct_signature(self) -> None:
        """Test AC3: parse_output() accepts ProviderResult, returns str."""
        from bmad_assist.providers import BaseProvider, ProviderResult

        sig = inspect.signature(BaseProvider.parse_output)
        params = list(sig.parameters.keys())

        assert params == ["self", "result"]
        assert sig.parameters["result"].annotation == ProviderResult
        assert sig.return_annotation == str

    def test_parse_output_has_google_style_docstring(self) -> None:
        """Test AC3: parse_output() has Google-style docstring."""
        from bmad_assist.providers import BaseProvider

        doc = BaseProvider.parse_output.__doc__
        assert doc is not None
        assert "Args:" in doc
        assert "result" in doc
        assert "Returns:" in doc
        # Should mention provider-specific parsing
        assert "provider" in doc.lower() or "Provider" in doc

    def test_supports_model_is_abstract_method(self) -> None:
        """Test AC4: supports_model() is decorated with @abstractmethod."""
        from bmad_assist.providers import BaseProvider

        assert hasattr(BaseProvider.supports_model, "__isabstractmethod__")
        assert BaseProvider.supports_model.__isabstractmethod__

    def test_supports_model_has_correct_signature(self) -> None:
        """Test AC4: supports_model() accepts model str, returns bool."""
        from bmad_assist.providers import BaseProvider

        sig = inspect.signature(BaseProvider.supports_model)
        params = list(sig.parameters.keys())

        assert params == ["self", "model"]
        assert sig.parameters["model"].annotation == str
        assert sig.return_annotation == bool

    def test_supports_model_has_google_style_docstring(self) -> None:
        """Test AC4: supports_model() has Google-style docstring."""
        from bmad_assist.providers import BaseProvider

        doc = BaseProvider.supports_model.__doc__
        assert doc is not None
        assert "Args:" in doc
        assert "model" in doc
        assert "Returns:" in doc
        assert "True" in doc or "bool" in doc.lower()


class TestBaseProviderInstantiation:
    """Test AC10 and AC11: Instantiation rules."""

    def test_baseprovider_cannot_be_instantiated(self) -> None:
        """Test AC10: BaseProvider() raises TypeError."""
        from bmad_assist.providers import BaseProvider

        with pytest.raises(TypeError) as exc_info:
            BaseProvider()  # type: ignore[abstract]

        error_msg = str(exc_info.value).lower()
        assert "abstract" in error_msg

    def test_baseprovider_error_mentions_abstract_methods(self) -> None:
        """Test AC10: TypeError mentions abstract methods not implemented."""
        from bmad_assist.providers import BaseProvider

        with pytest.raises(TypeError) as exc_info:
            BaseProvider()  # type: ignore[abstract]

        error_msg = str(exc_info.value)
        # Should mention at least one abstract method
        assert (
            "provider_name" in error_msg
            or "invoke" in error_msg
            or "parse_output" in error_msg
            or "supports_model" in error_msg
        )


# Module-level MockProvider for type hints and fixture use
from bmad_assist.providers import BaseProvider, ProviderResult


class MockProvider(BaseProvider):
    """Concrete mock provider for testing.

    Provides deterministic responses for unit testing BaseProvider contract.
    Used by mock_provider fixture and concrete provider tests.
    """

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def default_model(self) -> str | None:
        return "mock_default"

    def invoke(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout: int | None = None,
        settings_file: Path | None = None,
    ) -> ProviderResult:
        return ProviderResult(
            stdout=f"Mock response to: {prompt}",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model=model or self.default_model,
            command=("mock", "--model", model or "default"),
        )

    def parse_output(self, result: ProviderResult) -> str:
        return result.stdout

    def supports_model(self, model: str) -> bool:
        return model in ["mock_model_1", "mock_model_2", "mock_default"]


@pytest.fixture
def mock_provider() -> MockProvider:
    """Create a concrete mock provider for testing AC11.

    Returns module-level MockProvider instance for consistency.
    """
    return MockProvider()


class TestConcreteProviderWorks:
    """Test AC11: Concrete subclass can be created and used."""

    def test_concrete_provider_can_be_instantiated(self, mock_provider: MockProvider) -> None:
        """Test AC11: MockProvider can be instantiated."""
        assert mock_provider is not None
        assert isinstance(mock_provider, BaseProvider)

    def test_concrete_provider_name_returns_string(self, mock_provider: MockProvider) -> None:
        """Test AC11: provider_name returns string."""
        assert mock_provider.provider_name == "mock"
        assert isinstance(mock_provider.provider_name, str)

    def test_concrete_provider_default_model_can_be_overridden(
        self, mock_provider: MockProvider
    ) -> None:
        """Test AC11: default_model can be overridden."""
        assert mock_provider.default_model == "mock_default"

    def test_concrete_provider_invoke_is_callable(self, mock_provider: MockProvider) -> None:
        """Test AC11: invoke() is callable and returns ProviderResult."""
        result = mock_provider.invoke("test prompt")

        assert isinstance(result, ProviderResult)
        assert "test prompt" in result.stdout

    def test_concrete_provider_invoke_with_keyword_args(self, mock_provider: MockProvider) -> None:
        """Test AC11: invoke() accepts keyword-only arguments."""
        result = mock_provider.invoke(
            "test prompt",
            model="mock_model_1",
            timeout=30,
            settings_file=Path("/tmp/settings.json"),
        )

        assert isinstance(result, ProviderResult)
        assert result.model == "mock_model_1"

    def test_concrete_provider_parse_output_is_callable(self, mock_provider: MockProvider) -> None:
        """Test AC11: parse_output() is callable."""
        result = mock_provider.invoke("test")
        parsed = mock_provider.parse_output(result)

        assert isinstance(parsed, str)
        assert parsed == result.stdout

    def test_concrete_provider_supports_model_is_callable(
        self, mock_provider: MockProvider
    ) -> None:
        """Test AC11: supports_model() is callable and returns bool."""
        assert mock_provider.supports_model("mock_model_1") is True
        assert mock_provider.supports_model("mock_model_2") is True
        assert mock_provider.supports_model("unknown_model") is False


class TestDocstringsExist:
    """Verify all public methods have docstrings."""

    def test_module_has_docstring(self) -> None:
        """Test module has docstring."""
        from bmad_assist.providers import base

        assert base.__doc__ is not None
        assert "provider" in base.__doc__.lower()

    def test_providerresult_has_docstring(self) -> None:
        """Test ProviderResult has docstring."""
        from bmad_assist.providers import ProviderResult

        assert ProviderResult.__doc__ is not None

    def test_baseprovider_has_docstring(self) -> None:
        """Test BaseProvider has docstring."""
        from bmad_assist.providers import BaseProvider

        assert BaseProvider.__doc__ is not None

    def test_invoke_has_docstring(self) -> None:
        """Test invoke() has docstring."""
        from bmad_assist.providers import BaseProvider

        assert BaseProvider.invoke.__doc__ is not None

    def test_parse_output_has_docstring(self) -> None:
        """Test parse_output() has docstring."""
        from bmad_assist.providers import BaseProvider

        assert BaseProvider.parse_output.__doc__ is not None

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        from bmad_assist.providers import BaseProvider

        assert BaseProvider.supports_model.__doc__ is not None

    def test_provider_name_has_docstring(self) -> None:
        """Test provider_name property has docstring."""
        from bmad_assist.providers import BaseProvider

        fget = BaseProvider.provider_name.fget
        assert fget is not None
        assert fget.__doc__ is not None

    def test_default_model_has_docstring(self) -> None:
        """Test default_model property has docstring."""
        from bmad_assist.providers import BaseProvider

        fget = BaseProvider.default_model.fget
        assert fget is not None
        assert fget.__doc__ is not None

"""Tests for testarch configuration module.

Covers all acceptance criteria for testarch-1:
- AC1: TestarchConfig Pydantic Model
- AC2: EligibilityConfig Nested Model
- AC3: Weight Sum Validation
- AC4: PreflightConfig Nested Model
- AC5: Optional Integration with Main Config
- AC6: Full Configuration Example Works
- AC7: Minimal Configuration Works

Story 17.1 additions:
- PlaywrightConfig validation tests
"""

import pytest
from pydantic import ValidationError

from bmad_assist.core.config import (
    Config,
    MasterProviderConfig,
    ProviderConfig,
    _reset_config,
    load_config,
)
from bmad_assist.core.exceptions import ConfigError
from bmad_assist.testarch.config import (
    EligibilityConfig,
    PlaywrightConfig,
    PreflightConfig,
    TestarchConfig,
    VALID_BROWSERS,
)


class TestEligibilityConfigAC2:
    """Test AC2: EligibilityConfig Nested Model."""

    def test_default_values(self) -> None:
        """Test EligibilityConfig has correct default values."""
        config = EligibilityConfig()
        assert config.keyword_weight == 0.5
        assert config.llm_weight == 0.5
        assert config.threshold == 0.5

    def test_custom_values(self) -> None:
        """Test EligibilityConfig accepts custom values."""
        config = EligibilityConfig(
            keyword_weight=0.4,
            llm_weight=0.6,
            threshold=0.7,
        )
        assert config.keyword_weight == 0.4
        assert config.llm_weight == 0.6
        assert config.threshold == 0.7

    def test_keyword_weight_lower_bound(self) -> None:
        """Test keyword_weight validates ge=0.0."""
        with pytest.raises(ValidationError) as exc_info:
            EligibilityConfig(keyword_weight=-0.1, llm_weight=1.1)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("keyword_weight",) for e in errors)

    def test_keyword_weight_upper_bound(self) -> None:
        """Test keyword_weight validates le=1.0."""
        with pytest.raises(ValidationError) as exc_info:
            EligibilityConfig(keyword_weight=1.1, llm_weight=-0.1)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("keyword_weight",) for e in errors)

    def test_llm_weight_lower_bound(self) -> None:
        """Test llm_weight validates ge=0.0."""
        with pytest.raises(ValidationError) as exc_info:
            EligibilityConfig(keyword_weight=1.1, llm_weight=-0.1)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("llm_weight",) for e in errors)

    def test_llm_weight_upper_bound(self) -> None:
        """Test llm_weight validates le=1.0."""
        with pytest.raises(ValidationError) as exc_info:
            EligibilityConfig(keyword_weight=-0.1, llm_weight=1.1)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("llm_weight",) for e in errors)

    def test_threshold_lower_bound(self) -> None:
        """Test threshold validates ge=0.0."""
        with pytest.raises(ValidationError) as exc_info:
            EligibilityConfig(threshold=-0.1)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("threshold",) for e in errors)

    def test_threshold_upper_bound(self) -> None:
        """Test threshold validates le=1.0."""
        with pytest.raises(ValidationError) as exc_info:
            EligibilityConfig(threshold=1.1)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("threshold",) for e in errors)

    def test_boundary_values_valid(self) -> None:
        """Test boundary values (0.0 and 1.0) are valid."""
        # Both extremes should work
        config1 = EligibilityConfig(keyword_weight=0.0, llm_weight=1.0, threshold=0.0)
        assert config1.keyword_weight == 0.0
        assert config1.llm_weight == 1.0
        assert config1.threshold == 0.0

        config2 = EligibilityConfig(keyword_weight=1.0, llm_weight=0.0, threshold=1.0)
        assert config2.keyword_weight == 1.0
        assert config2.llm_weight == 0.0
        assert config2.threshold == 1.0

    def test_frozen_model(self) -> None:
        """Test EligibilityConfig is immutable."""
        config = EligibilityConfig()
        with pytest.raises(ValidationError):
            config.keyword_weight = 0.9  # type: ignore[misc]


class TestWeightSumValidationAC3:
    """Test AC3: Weight Sum Validation."""

    def test_valid_weights_sum_to_one(self) -> None:
        """Test weights summing to 1.0 are accepted."""
        config = EligibilityConfig(keyword_weight=0.3, llm_weight=0.7)
        assert config.keyword_weight == 0.3
        assert config.llm_weight == 0.7

    def test_valid_weights_with_tolerance(self) -> None:
        """Test weights within epsilon tolerance are accepted."""
        # 0.4 + 0.6 = 1.0 exactly
        config = EligibilityConfig(keyword_weight=0.4, llm_weight=0.6)
        assert config.keyword_weight + config.llm_weight == 1.0

    def test_invalid_weights_sum_below_one(self) -> None:
        """Test weights summing to less than 1.0 are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            EligibilityConfig(keyword_weight=0.3, llm_weight=0.3)
        assert "eligibility weights must sum to 1.0" in str(exc_info.value)

    def test_invalid_weights_sum_above_one(self) -> None:
        """Test weights summing to more than 1.0 are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            EligibilityConfig(keyword_weight=0.6, llm_weight=0.6)
        assert "eligibility weights must sum to 1.0" in str(exc_info.value)

    def test_epsilon_tolerance_accepted(self) -> None:
        """Test weights just within epsilon tolerance (0.001) are accepted."""
        # Sum = 0.9995, diff from 1.0 = 0.0005 < 0.001
        config = EligibilityConfig(keyword_weight=0.4995, llm_weight=0.5)
        assert config.keyword_weight == 0.4995

    def test_beyond_epsilon_tolerance_rejected(self) -> None:
        """Test weights just beyond epsilon tolerance (0.001) are rejected."""
        # Sum = 0.998, diff from 1.0 = 0.002 > 0.001
        with pytest.raises(ValidationError) as exc_info:
            EligibilityConfig(keyword_weight=0.498, llm_weight=0.5)
        assert "eligibility weights must sum to 1.0" in str(exc_info.value)


class TestPreflightConfigAC4:
    """Test AC4: PreflightConfig Nested Model."""

    def test_default_values(self) -> None:
        """Test PreflightConfig has correct default values."""
        config = PreflightConfig()
        assert config.test_design is True
        assert config.framework is True
        assert config.ci is True

    def test_custom_values(self) -> None:
        """Test PreflightConfig accepts custom values."""
        config = PreflightConfig(
            test_design=False,
            framework=True,
            ci=False,
        )
        assert config.test_design is False
        assert config.framework is True
        assert config.ci is False

    def test_all_false(self) -> None:
        """Test all preflight checks can be disabled."""
        config = PreflightConfig(test_design=False, framework=False, ci=False)
        assert config.test_design is False
        assert config.framework is False
        assert config.ci is False

    def test_frozen_model(self) -> None:
        """Test PreflightConfig is immutable."""
        config = PreflightConfig()
        with pytest.raises(ValidationError):
            config.test_design = False  # type: ignore[misc]


class TestTestarchConfigAC1:
    """Test AC1: TestarchConfig Pydantic Model."""

    def test_default_values(self) -> None:
        """Test TestarchConfig has correct default values."""
        config = TestarchConfig()
        assert config.atdd_mode == "auto"
        assert config.trace_on_epic_complete == "auto"
        assert isinstance(config.eligibility, EligibilityConfig)
        assert isinstance(config.preflight, PreflightConfig)

    def test_atdd_mode_off(self) -> None:
        """Test atdd_mode accepts 'off' value."""
        config = TestarchConfig(atdd_mode="off")
        assert config.atdd_mode == "off"

    def test_atdd_mode_on(self) -> None:
        """Test atdd_mode accepts 'on' value."""
        config = TestarchConfig(atdd_mode="on")
        assert config.atdd_mode == "on"

    def test_atdd_mode_auto(self) -> None:
        """Test atdd_mode accepts 'auto' value."""
        config = TestarchConfig(atdd_mode="auto")
        assert config.atdd_mode == "auto"

    def test_atdd_mode_invalid(self) -> None:
        """Test atdd_mode rejects invalid values."""
        with pytest.raises(ValidationError) as exc_info:
            TestarchConfig(atdd_mode="invalid")  # type: ignore[arg-type]
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("atdd_mode",) for e in errors)

    def test_trace_on_epic_complete_values(self) -> None:
        """Test trace_on_epic_complete accepts all valid values."""
        for mode in ("off", "auto", "on"):
            config = TestarchConfig(trace_on_epic_complete=mode)  # type: ignore[arg-type]
            assert config.trace_on_epic_complete == mode

    def test_trace_on_epic_complete_invalid(self) -> None:
        """Test trace_on_epic_complete rejects invalid values."""
        with pytest.raises(ValidationError) as exc_info:
            TestarchConfig(trace_on_epic_complete="wrong")  # type: ignore[arg-type]
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("trace_on_epic_complete",) for e in errors)

    def test_nested_eligibility_config(self) -> None:
        """Test custom eligibility config is accepted."""
        config = TestarchConfig(eligibility=EligibilityConfig(keyword_weight=0.3, llm_weight=0.7))
        assert config.eligibility.keyword_weight == 0.3
        assert config.eligibility.llm_weight == 0.7

    def test_nested_preflight_config(self) -> None:
        """Test custom preflight config is accepted."""
        config = TestarchConfig(preflight=PreflightConfig(ci=False))
        assert config.preflight.ci is False
        assert config.preflight.test_design is True  # defaults preserved

    def test_frozen_model(self) -> None:
        """Test TestarchConfig is immutable."""
        config = TestarchConfig()
        with pytest.raises(ValidationError):
            config.atdd_mode = "on"  # type: ignore[misc]

    def test_default_factory_creates_new_instances(self) -> None:
        """Test default_factory creates independent nested config instances."""
        config1 = TestarchConfig()
        config2 = TestarchConfig()
        # Ensure they're independent (different objects)
        # With frozen models, we can't mutate, but we can verify they're separate
        assert config1.eligibility is not config2.eligibility
        assert config1.preflight is not config2.preflight


class TestMainConfigIntegrationAC5:
    """Test AC5: Optional Integration with Main Config."""

    def setup_method(self) -> None:
        """Reset config singleton before each test."""
        _reset_config()

    def teardown_method(self) -> None:
        """Reset config singleton after each test."""
        _reset_config()

    def test_testarch_absent_returns_none(self) -> None:
        """Test testarch is None when section absent from config."""
        config = Config(
            providers=ProviderConfig(master=MasterProviderConfig(provider="claude", model="opus"))
        )
        assert config.testarch is None

    def test_testarch_present_returns_config(self) -> None:
        """Test testarch returns TestarchConfig when section present."""
        config = Config(
            providers=ProviderConfig(master=MasterProviderConfig(provider="claude", model="opus")),
            testarch=TestarchConfig(),
        )
        assert config.testarch is not None
        assert isinstance(config.testarch, TestarchConfig)

    def test_config_model_validate_with_testarch(self) -> None:
        """Test Config.model_validate works with testarch section."""
        config = Config.model_validate(
            {
                "providers": {"master": {"provider": "claude", "model": "opus"}},
                "testarch": {"atdd_mode": "on"},
            }
        )
        assert config.testarch is not None
        assert config.testarch.atdd_mode == "on"

    def test_config_model_validate_without_testarch(self) -> None:
        """Test Config.model_validate works without testarch section."""
        config = Config.model_validate(
            {"providers": {"master": {"provider": "claude", "model": "opus"}}}
        )
        assert config.testarch is None

    def test_load_config_with_testarch(self) -> None:
        """Test load_config() works with testarch section."""
        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus"}},
                "testarch": {"atdd_mode": "off"},
            }
        )
        assert config.testarch is not None
        assert config.testarch.atdd_mode == "off"


class TestFullConfigurationAC6:
    """Test AC6: Full Configuration Example Works."""

    def setup_method(self) -> None:
        """Reset config singleton before each test."""
        _reset_config()

    def teardown_method(self) -> None:
        """Reset config singleton after each test."""
        _reset_config()

    def test_full_configuration_example(self) -> None:
        """Test the full configuration example from AC6."""
        config = load_config(
            {
                "providers": {
                    "master": {"provider": "claude", "model": "opus"},
                    "helper": {"provider": "claude", "model": "haiku"},
                },
                "testarch": {
                    "atdd_mode": "auto",
                    "eligibility": {
                        "keyword_weight": 0.4,
                        "llm_weight": 0.6,
                        "threshold": 0.5,
                    },
                    "preflight": {
                        "test_design": True,
                        "framework": True,
                        "ci": False,
                    },
                    "trace_on_epic_complete": "on",
                },
            }
        )
        assert config.testarch is not None
        assert config.testarch.atdd_mode == "auto"
        assert config.testarch.eligibility.keyword_weight == 0.4
        assert config.testarch.eligibility.llm_weight == 0.6
        assert config.testarch.eligibility.threshold == 0.5
        assert config.testarch.preflight.test_design is True
        assert config.testarch.preflight.framework is True
        assert config.testarch.preflight.ci is False
        assert config.testarch.trace_on_epic_complete == "on"


class TestMinimalConfigurationAC7:
    """Test AC7: Minimal Configuration Works."""

    def setup_method(self) -> None:
        """Reset config singleton before each test."""
        _reset_config()

    def teardown_method(self) -> None:
        """Reset config singleton after each test."""
        _reset_config()

    def test_empty_testarch_section_applies_defaults(self) -> None:
        """Test empty testarch: {} section applies all defaults."""
        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus"}},
                "testarch": {},
            }
        )
        assert config.testarch is not None
        # Default values should be applied
        assert config.testarch.atdd_mode == "auto"
        assert config.testarch.eligibility.keyword_weight == 0.5
        assert config.testarch.eligibility.llm_weight == 0.5
        assert config.testarch.eligibility.threshold == 0.5
        assert config.testarch.preflight.test_design is True
        assert config.testarch.preflight.framework is True
        assert config.testarch.preflight.ci is True
        assert config.testarch.trace_on_epic_complete == "auto"


class TestWeightValidationViaLoadConfigAC3:
    """Test AC3: Weight validation is wrapped in ConfigError by load_config."""

    def setup_method(self) -> None:
        """Reset config singleton before each test."""
        _reset_config()

    def teardown_method(self) -> None:
        """Reset config singleton after each test."""
        _reset_config()

    def test_invalid_weights_raises_config_error(self) -> None:
        """Test load_config wraps weight validation error in ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            load_config(
                {
                    "providers": {"master": {"provider": "claude", "model": "opus"}},
                    "testarch": {
                        "eligibility": {
                            "keyword_weight": 0.3,
                            "llm_weight": 0.3,  # Sum = 0.6, not 1.0
                        }
                    },
                }
            )
        assert "eligibility weights must sum to 1.0" in str(exc_info.value)


# =============================================================================
# Story 17.1: PlaywrightConfig Tests
# =============================================================================


class TestPlaywrightConfigDefaults:
    """Test PlaywrightConfig default values."""

    def test_default_values(self) -> None:
        """Test PlaywrightConfig has correct default values."""
        config = PlaywrightConfig()
        assert config.browsers == ["chromium"]
        assert config.headless is True
        assert config.timeout == 30000
        assert config.workers == 1

    def test_frozen_model(self) -> None:
        """Test PlaywrightConfig is immutable."""
        config = PlaywrightConfig()
        with pytest.raises(ValidationError):
            config.headless = False  # type: ignore[misc]


class TestPlaywrightConfigBrowserValidation:
    """Test PlaywrightConfig browser validation (AC3)."""

    def test_valid_single_browser_chromium(self) -> None:
        """Test single valid browser: chromium."""
        config = PlaywrightConfig(browsers=["chromium"])
        assert config.browsers == ["chromium"]

    def test_valid_single_browser_firefox(self) -> None:
        """Test single valid browser: firefox."""
        config = PlaywrightConfig(browsers=["firefox"])
        assert config.browsers == ["firefox"]

    def test_valid_single_browser_webkit(self) -> None:
        """Test single valid browser: webkit."""
        config = PlaywrightConfig(browsers=["webkit"])
        assert config.browsers == ["webkit"]

    def test_valid_multiple_browsers(self) -> None:
        """Test multiple valid browsers."""
        config = PlaywrightConfig(browsers=["chromium", "firefox"])
        assert config.browsers == ["chromium", "firefox"]

    def test_valid_all_browsers(self) -> None:
        """Test all valid browsers."""
        config = PlaywrightConfig(browsers=["chromium", "firefox", "webkit"])
        assert config.browsers == ["chromium", "firefox", "webkit"]

    def test_empty_browsers_allowed(self) -> None:
        """Test empty browsers list is allowed (disables browser testing)."""
        config = PlaywrightConfig(browsers=[])
        assert config.browsers == []

    def test_invalid_single_browser(self) -> None:
        """Test invalid single browser raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            PlaywrightConfig(browsers=["safari"])
        assert "Invalid browser(s): safari" in str(exc_info.value)
        assert "Valid options: chromium, firefox, webkit" in str(exc_info.value)

    def test_invalid_browser_edge(self) -> None:
        """Test edge browser is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PlaywrightConfig(browsers=["edge"])
        assert "Invalid browser(s): edge" in str(exc_info.value)

    def test_mixed_valid_invalid_browsers(self) -> None:
        """Test mix of valid and invalid browsers rejects all invalid."""
        with pytest.raises(ValidationError) as exc_info:
            PlaywrightConfig(browsers=["chromium", "edge"])
        assert "Invalid browser(s): edge" in str(exc_info.value)

    def test_multiple_invalid_browsers(self) -> None:
        """Test multiple invalid browsers listed in error."""
        with pytest.raises(ValidationError) as exc_info:
            PlaywrightConfig(browsers=["safari", "edge"])
        error_str = str(exc_info.value)
        assert "Invalid browser(s):" in error_str
        # Both should be listed
        assert "safari" in error_str
        assert "edge" in error_str


class TestPlaywrightConfigBounds:
    """Test PlaywrightConfig field bounds."""

    def test_timeout_minimum(self) -> None:
        """Test timeout has minimum of 1000ms."""
        with pytest.raises(ValidationError):
            PlaywrightConfig(timeout=999)

    def test_timeout_at_minimum(self) -> None:
        """Test timeout accepts minimum value of 1000ms."""
        config = PlaywrightConfig(timeout=1000)
        assert config.timeout == 1000

    def test_timeout_maximum(self) -> None:
        """Test timeout has maximum of 300000ms."""
        with pytest.raises(ValidationError):
            PlaywrightConfig(timeout=300001)

    def test_timeout_at_maximum(self) -> None:
        """Test timeout accepts maximum value of 300000ms."""
        config = PlaywrightConfig(timeout=300000)
        assert config.timeout == 300000

    def test_workers_minimum(self) -> None:
        """Test workers has minimum of 1."""
        with pytest.raises(ValidationError):
            PlaywrightConfig(workers=0)

    def test_workers_at_minimum(self) -> None:
        """Test workers accepts minimum value of 1."""
        config = PlaywrightConfig(workers=1)
        assert config.workers == 1

    def test_workers_maximum(self) -> None:
        """Test workers has maximum of 16."""
        with pytest.raises(ValidationError):
            PlaywrightConfig(workers=17)

    def test_workers_at_maximum(self) -> None:
        """Test workers accepts maximum value of 16."""
        config = PlaywrightConfig(workers=16)
        assert config.workers == 16


class TestPlaywrightConfigInTestarch:
    """Test PlaywrightConfig integration with TestarchConfig."""

    def test_playwright_absent_by_default(self) -> None:
        """Test playwright is None by default in TestarchConfig."""
        config = TestarchConfig()
        assert config.playwright is None

    def test_playwright_can_be_set(self) -> None:
        """Test playwright can be set in TestarchConfig."""
        playwright = PlaywrightConfig(browsers=["firefox"], headless=False)
        config = TestarchConfig(playwright=playwright)
        assert config.playwright is not None
        assert config.playwright.browsers == ["firefox"]
        assert config.playwright.headless is False

    def test_playwright_via_dict(self) -> None:
        """Test playwright can be set via dictionary."""
        config = TestarchConfig.model_validate(
            {
                "playwright": {
                    "browsers": ["chromium", "webkit"],
                    "timeout": 60000,
                    "workers": 4,
                }
            }
        )
        assert config.playwright is not None
        assert config.playwright.browsers == ["chromium", "webkit"]
        assert config.playwright.timeout == 60000
        assert config.playwright.workers == 4


class TestPlaywrightConfigViaLoadConfig:
    """Test PlaywrightConfig via load_config."""

    def setup_method(self) -> None:
        """Reset config singleton before each test."""
        _reset_config()

    def teardown_method(self) -> None:
        """Reset config singleton after each test."""
        _reset_config()

    def test_load_config_with_playwright(self) -> None:
        """Test load_config with playwright section."""
        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus"}},
                "testarch": {
                    "playwright": {
                        "browsers": ["chromium", "firefox"],
                        "headless": False,
                        "timeout": 45000,
                        "workers": 2,
                    }
                },
            }
        )
        assert config.testarch is not None
        assert config.testarch.playwright is not None
        assert config.testarch.playwright.browsers == ["chromium", "firefox"]
        assert config.testarch.playwright.headless is False
        assert config.testarch.playwright.timeout == 45000
        assert config.testarch.playwright.workers == 2

    def test_load_config_invalid_browser_raises_config_error(self) -> None:
        """Test load_config with invalid browser raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            load_config(
                {
                    "providers": {"master": {"provider": "claude", "model": "opus"}},
                    "testarch": {
                        "playwright": {
                            "browsers": ["opera"],
                        }
                    },
                }
            )
        assert "Invalid browser(s): opera" in str(exc_info.value)


class TestValidBrowsersConstant:
    """Test VALID_BROWSERS constant."""

    def test_valid_browsers_is_tuple(self) -> None:
        """Test VALID_BROWSERS is a tuple."""
        assert isinstance(VALID_BROWSERS, tuple)

    def test_valid_browsers_contains_expected(self) -> None:
        """Test VALID_BROWSERS contains expected values."""
        assert "chromium" in VALID_BROWSERS
        assert "firefox" in VALID_BROWSERS
        assert "webkit" in VALID_BROWSERS

    def test_valid_browsers_count(self) -> None:
        """Test VALID_BROWSERS has exactly 3 items."""
        assert len(VALID_BROWSERS) == 3


# =============================================================================
# Story 25.5: Evidence & Knowledge Configuration Tests
# =============================================================================


class TestSourceConfigModel:
    """Test SourceConfigModel Pydantic model (AC3)."""

    def test_default_values(self) -> None:
        """Test SourceConfigModel has correct default values."""
        from bmad_assist.testarch.config import SourceConfigModel

        config = SourceConfigModel()
        assert config.enabled is True
        assert config.patterns == []
        assert config.command is None
        assert config.timeout == 30

    def test_custom_values(self) -> None:
        """Test SourceConfigModel accepts custom values."""
        from bmad_assist.testarch.config import SourceConfigModel

        config = SourceConfigModel(
            enabled=False,
            patterns=["*.json", "**/*.xml"],
            command="npm audit",
            timeout=60,
        )
        assert config.enabled is False
        assert config.patterns == ["*.json", "**/*.xml"]
        assert config.command == "npm audit"
        assert config.timeout == 60

    def test_frozen_model(self) -> None:
        """Test SourceConfigModel is immutable."""
        from bmad_assist.testarch.config import SourceConfigModel

        config = SourceConfigModel()
        with pytest.raises(ValidationError):
            config.enabled = False  # type: ignore[misc]

    def test_timeout_minimum_bound(self) -> None:
        """Test timeout has minimum of 1."""
        from bmad_assist.testarch.config import SourceConfigModel

        with pytest.raises(ValidationError) as exc_info:
            SourceConfigModel(timeout=0)
        assert "timeout" in str(exc_info.value).lower()

    def test_timeout_maximum_bound(self) -> None:
        """Test timeout has maximum of 300."""
        from bmad_assist.testarch.config import SourceConfigModel

        with pytest.raises(ValidationError) as exc_info:
            SourceConfigModel(timeout=301)
        assert "timeout" in str(exc_info.value).lower()

    def test_timeout_at_bounds(self) -> None:
        """Test timeout accepts boundary values."""
        from bmad_assist.testarch.config import SourceConfigModel

        config1 = SourceConfigModel(timeout=1)
        assert config1.timeout == 1

        config2 = SourceConfigModel(timeout=300)
        assert config2.timeout == 300

    def test_patterns_all_empty_strings_rejected_when_enabled(self) -> None:
        """Test patterns with only empty strings rejected when enabled."""
        from bmad_assist.testarch.config import SourceConfigModel

        with pytest.raises(ValidationError) as exc_info:
            SourceConfigModel(enabled=True, patterns=["", "", ""])
        assert "patterns" in str(exc_info.value).lower()

    def test_patterns_all_empty_strings_allowed_when_disabled(self) -> None:
        """Test patterns with only empty strings allowed when disabled."""
        from bmad_assist.testarch.config import SourceConfigModel

        # When disabled, we don't validate patterns
        config = SourceConfigModel(enabled=False, patterns=["", ""])
        assert config.enabled is False

    def test_patterns_mixed_with_one_valid_accepted(self) -> None:
        """Test patterns with at least one non-empty string accepted."""
        from bmad_assist.testarch.config import SourceConfigModel

        config = SourceConfigModel(enabled=True, patterns=["", "*.json", ""])
        assert "*.json" in config.patterns


class TestEvidenceConfig:
    """Test EvidenceConfig Pydantic model (AC1)."""

    def test_default_values(self) -> None:
        """Test EvidenceConfig has correct default values."""
        from bmad_assist.testarch.config import EvidenceConfig

        config = EvidenceConfig()
        assert config.enabled is True
        assert config.storage_path is None
        assert config.collect_before_step is True
        assert config.coverage is None
        assert config.test_results is None
        assert config.security is None
        assert config.performance is None

    def test_custom_values(self) -> None:
        """Test EvidenceConfig accepts custom values."""
        from bmad_assist.testarch.config import EvidenceConfig, SourceConfigModel

        config = EvidenceConfig(
            enabled=False,
            storage_path="{implementation_artifacts}/testarch/evidence/",
            collect_before_step=False,
            coverage=SourceConfigModel(enabled=True),
        )
        assert config.enabled is False
        assert config.storage_path == "{implementation_artifacts}/testarch/evidence/"
        assert config.collect_before_step is False
        assert config.coverage is not None

    def test_frozen_model(self) -> None:
        """Test EvidenceConfig is immutable."""
        from bmad_assist.testarch.config import EvidenceConfig

        config = EvidenceConfig()
        with pytest.raises(ValidationError):
            config.enabled = False  # type: ignore[misc]

    def test_storage_path_rejects_path_traversal(self) -> None:
        """Test storage_path rejects paths with .. (AC8)."""
        from bmad_assist.testarch.config import EvidenceConfig

        with pytest.raises(ValidationError) as exc_info:
            EvidenceConfig(storage_path="../outside/evidence")
        assert "path traversal" in str(exc_info.value).lower()

    def test_storage_path_rejects_absolute_path_unix(self) -> None:
        """Test storage_path rejects absolute Unix paths (AC8)."""
        from bmad_assist.testarch.config import EvidenceConfig

        with pytest.raises(ValidationError) as exc_info:
            EvidenceConfig(storage_path="/etc/evidence")
        assert "absolute" in str(exc_info.value).lower()

    def test_storage_path_allows_placeholder(self) -> None:
        """Test storage_path allows {implementation_artifacts} placeholder."""
        from bmad_assist.testarch.config import EvidenceConfig

        config = EvidenceConfig(
            storage_path="{implementation_artifacts}/testarch/evidence/"
        )
        assert "{implementation_artifacts}" in config.storage_path  # type: ignore[operator]

    def test_storage_path_allows_relative_path(self) -> None:
        """Test storage_path allows relative paths."""
        from bmad_assist.testarch.config import EvidenceConfig

        config = EvidenceConfig(storage_path="testarch/evidence/")
        assert config.storage_path == "testarch/evidence/"

    def test_per_source_config_coverage(self) -> None:
        """Test coverage source configuration."""
        from bmad_assist.testarch.config import EvidenceConfig, SourceConfigModel

        config = EvidenceConfig(
            coverage=SourceConfigModel(
                enabled=True,
                patterns=["coverage/lcov.info", "**/coverage-summary.json"],
            )
        )
        assert config.coverage is not None
        assert config.coverage.enabled is True
        assert len(config.coverage.patterns) == 2

    def test_per_source_config_security(self) -> None:
        """Test security source configuration."""
        from bmad_assist.testarch.config import EvidenceConfig, SourceConfigModel

        config = EvidenceConfig(
            security=SourceConfigModel(
                enabled=True,
                command="npm audit --json",
                timeout=60,
            )
        )
        assert config.security is not None
        assert config.security.command == "npm audit --json"
        assert config.security.timeout == 60


class TestKnowledgeConfig:
    """Test KnowledgeConfig Pydantic model (AC2)."""

    def test_default_values(self) -> None:
        """Test KnowledgeConfig has correct default values."""
        from bmad_assist.testarch.config import KnowledgeConfig

        config = KnowledgeConfig()
        assert config.index_path == "_bmad/tea/testarch/tea-index.csv"
        assert config.playwright_utils is True
        assert config.mcp_enhancements is True
        assert config.default_fragments is None

    def test_custom_values(self) -> None:
        """Test KnowledgeConfig accepts custom values."""
        from bmad_assist.testarch.config import KnowledgeConfig

        config = KnowledgeConfig(
            index_path="_custom/knowledge/index.csv",
            playwright_utils=False,
            mcp_enhancements=False,
            default_fragments={"atdd": ["custom-fragment"]},
        )
        assert config.index_path == "_custom/knowledge/index.csv"
        assert config.playwright_utils is False
        assert config.mcp_enhancements is False
        assert config.default_fragments == {"atdd": ["custom-fragment"]}

    def test_frozen_model(self) -> None:
        """Test KnowledgeConfig is immutable."""
        from bmad_assist.testarch.config import KnowledgeConfig

        config = KnowledgeConfig()
        with pytest.raises(ValidationError):
            config.playwright_utils = False  # type: ignore[misc]

    def test_index_path_must_end_with_csv(self) -> None:
        """Test index_path must end with .csv (AC8)."""
        from bmad_assist.testarch.config import KnowledgeConfig

        with pytest.raises(ValidationError) as exc_info:
            KnowledgeConfig(index_path="_bmad/tea/index.yaml")
        assert ".csv" in str(exc_info.value)

    def test_index_path_rejects_absolute_path(self) -> None:
        """Test index_path rejects absolute paths (AC8)."""
        from bmad_assist.testarch.config import KnowledgeConfig

        with pytest.raises(ValidationError) as exc_info:
            KnowledgeConfig(index_path="/etc/index.csv")
        assert "absolute" in str(exc_info.value).lower()

    def test_get_workflow_fragments_returns_override(self) -> None:
        """Test get_workflow_fragments returns user override when set."""
        from bmad_assist.testarch.config import KnowledgeConfig

        config = KnowledgeConfig(
            default_fragments={"atdd": ["my-custom-fragment", "another-one"]}
        )
        fragments = config.get_workflow_fragments("atdd")
        assert fragments == ["my-custom-fragment", "another-one"]

    def test_get_workflow_fragments_returns_default_when_no_override(self) -> None:
        """Test get_workflow_fragments returns default when no user override."""
        from bmad_assist.testarch.config import KnowledgeConfig

        config = KnowledgeConfig()  # No overrides
        fragments = config.get_workflow_fragments("atdd")
        # Should return from WORKFLOW_KNOWLEDGE_MAP
        assert "fixture-architecture" in fragments

    def test_get_workflow_fragments_returns_empty_for_unknown(self) -> None:
        """Test get_workflow_fragments returns empty list for unknown workflow."""
        from bmad_assist.testarch.config import KnowledgeConfig

        config = KnowledgeConfig()
        fragments = config.get_workflow_fragments("unknown-workflow")
        assert fragments == []


class TestTestarchConfigExtended:
    """Test TestarchConfig extensions for Story 25.5 (AC4)."""

    def test_new_fields_have_defaults(self) -> None:
        """Test new fields have sensible defaults."""
        config = TestarchConfig()
        assert config.evidence is None
        assert config.knowledge is None
        assert config.test_dir == "tests/"

    def test_evidence_field_accepts_config(self) -> None:
        """Test evidence field accepts EvidenceConfig."""
        from bmad_assist.testarch.config import EvidenceConfig

        config = TestarchConfig(evidence=EvidenceConfig(enabled=True))
        assert config.evidence is not None
        assert config.evidence.enabled is True

    def test_knowledge_field_accepts_config(self) -> None:
        """Test knowledge field accepts KnowledgeConfig."""
        from bmad_assist.testarch.config import KnowledgeConfig

        config = TestarchConfig(knowledge=KnowledgeConfig(playwright_utils=False))
        assert config.knowledge is not None
        assert config.knowledge.playwright_utils is False

    def test_test_dir_custom_value(self) -> None:
        """Test test_dir accepts custom value."""
        config = TestarchConfig(test_dir="spec/")
        assert config.test_dir == "spec/"

    def test_backward_compatibility(self) -> None:
        """Test backward compatibility - existing config still works."""
        config = TestarchConfig(
            atdd_mode="on",
            eligibility=EligibilityConfig(keyword_weight=0.3, llm_weight=0.7),
            preflight=PreflightConfig(ci=False),
        )
        assert config.atdd_mode == "on"
        assert config.eligibility.keyword_weight == 0.3
        assert config.preflight.ci is False
        # New fields default to None/default
        assert config.evidence is None
        assert config.knowledge is None
        assert config.test_dir == "tests/"


class TestTestarchConfigViaLoadConfig:
    """Test TestarchConfig extensions via load_config (AC4)."""

    def setup_method(self) -> None:
        """Reset config singleton before each test."""
        _reset_config()

    def teardown_method(self) -> None:
        """Reset config singleton after each test."""
        _reset_config()

    def test_load_config_with_evidence(self) -> None:
        """Test load_config with evidence section."""
        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus"}},
                "testarch": {
                    "evidence": {
                        "enabled": True,
                        "storage_path": "{implementation_artifacts}/testarch/evidence/",
                        "coverage": {
                            "enabled": True,
                            "patterns": ["coverage/lcov.info"],
                        },
                    }
                },
            }
        )
        assert config.testarch is not None
        assert config.testarch.evidence is not None
        assert config.testarch.evidence.enabled is True
        assert config.testarch.evidence.coverage is not None
        assert config.testarch.evidence.coverage.patterns == ["coverage/lcov.info"]

    def test_load_config_with_knowledge(self) -> None:
        """Test load_config with knowledge section."""
        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus"}},
                "testarch": {
                    "knowledge": {
                        "index_path": "_bmad/custom/index.csv",
                        "playwright_utils": False,
                        "default_fragments": {
                            "atdd": ["custom-1", "custom-2"],
                        },
                    }
                },
            }
        )
        assert config.testarch is not None
        assert config.testarch.knowledge is not None
        assert config.testarch.knowledge.index_path == "_bmad/custom/index.csv"
        assert config.testarch.knowledge.playwright_utils is False

    def test_load_config_invalid_storage_path_raises_error(self) -> None:
        """Test load_config with invalid storage_path raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            load_config(
                {
                    "providers": {"master": {"provider": "claude", "model": "opus"}},
                    "testarch": {
                        "evidence": {
                            "storage_path": "../outside/evidence",
                        }
                    },
                }
            )
        assert "path traversal" in str(exc_info.value).lower()

    def test_load_config_invalid_index_path_raises_error(self) -> None:
        """Test load_config with invalid index_path raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            load_config(
                {
                    "providers": {"master": {"provider": "claude", "model": "opus"}},
                    "testarch": {
                        "knowledge": {
                            "index_path": "_bmad/index.json",
                        }
                    },
                }
            )
        assert ".csv" in str(exc_info.value)

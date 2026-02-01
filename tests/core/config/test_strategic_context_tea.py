"""Tests for TEA workflow strategic context config extensions.

Verifies default values for TEA workflow configs per ADR-4 in tech-spec-tea-context-loader.md.
"""

from bmad_assist.core.config.models.strategic_context import StrategicContextConfig


class TestTEAWorkflowDefaults:
    """Test default values for TEA workflow configs per ADR-4."""

    def test_testarch_atdd_defaults(self):
        """testarch-atdd should only include project-context."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-atdd")
        assert wf_config[0] == ("project-context",), f"testarch-atdd: expected ('project-context',), got {wf_config[0]}"

    def test_testarch_trace_defaults(self):
        """testarch-trace should include project-context and architecture."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-trace")
        assert wf_config[0] == ("project-context", "architecture"), f"testarch-trace: got {wf_config[0]}"

    def test_testarch_automate_defaults(self):
        """testarch-automate should include project-context, prd, architecture."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-automate")
        assert wf_config[0] == ("project-context", "prd", "architecture"), f"testarch-automate: got {wf_config[0]}"

    def test_testarch_nfr_assess_defaults(self):
        """testarch-nfr-assess should include project-context, prd, architecture."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-nfr-assess")
        assert wf_config[0] == ("project-context", "prd", "architecture"), f"testarch-nfr-assess: got {wf_config[0]}"

    def test_testarch_test_design_defaults(self):
        """testarch-test-design should include project-context, prd, architecture."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-test-design")
        assert wf_config[0] == ("project-context", "prd", "architecture"), f"testarch-test-design: got {wf_config[0]}"

    def test_testarch_test_review_defaults(self):
        """testarch-test-review should only include project-context."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-test-review")
        assert wf_config[0] == ("project-context",), f"testarch-test-review: got {wf_config[0]}"

    def test_testarch_framework_defaults(self):
        """testarch-framework should include project-context and architecture."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-framework")
        assert wf_config[0] == ("project-context", "architecture"), f"testarch-framework: got {wf_config[0]}"

    def test_testarch_ci_defaults(self):
        """testarch-ci should include project-context and architecture."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-ci")
        assert wf_config[0] == ("project-context", "architecture"), f"testarch-ci: got {wf_config[0]}"


class TestTEAConfigNormalization:
    """Test workflow name normalization for TEA workflows."""

    def test_normalization_kebab_to_snake_atdd(self):
        """Workflow name normalization: testarch-atdd -> testarch_atdd."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-atdd")
        assert wf_config[0] == ("project-context",)

    def test_normalization_kebab_to_snake_nfr(self):
        """Workflow name normalization: testarch-nfr-assess -> testarch_nfr_assess."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-nfr-assess")
        assert wf_config[0] == ("project-context", "prd", "architecture")

    def test_normalization_kebab_to_snake_test_review(self):
        """Workflow name normalization: testarch-test-review -> testarch_test_review."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-test-review")
        assert wf_config[0] == ("project-context",)


class TestTEAConfigBackwardCompatibility:
    """Test backward compatibility with missing config."""

    def test_unknown_workflow_uses_base_defaults(self):
        """Unknown testarch workflow falls back to base defaults."""
        config = StrategicContextConfig()
        wf_config = config.get_workflow_config("testarch-unknown-workflow")
        # Should not crash, should return defaults.include
        assert wf_config[0] == ("project-context",)  # defaults.include

    def test_budget_has_default_value(self):
        """Budget should have default value of 8000."""
        config = StrategicContextConfig()
        assert config.budget == 8000

    def test_zero_budget_disables_context(self):
        """Budget=0 should be valid (disables context collection)."""
        config = StrategicContextConfig(budget=0)
        assert config.budget == 0


class TestTEAMainOnlyDefaults:
    """Test main_only defaults for TEA workflows."""

    def test_testarch_workflows_inherit_main_only_true(self):
        """TEA workflows should inherit main_only=True from defaults."""
        config = StrategicContextConfig()

        for workflow in [
            "testarch-atdd",
            "testarch-trace",
            "testarch-test-review",
            "testarch-framework",
            "testarch-ci",
            "testarch-test-design",
            "testarch-automate",
            "testarch-nfr-assess",
        ]:
            _, main_only = config.get_workflow_config(workflow)
            assert main_only is True, f"{workflow} should have main_only=True"


class TestSourceContextBudgetDefaults:
    """Test SourceContextBudgetsConfig TEA workflow budget defaults (F2 fix)."""

    def test_testarch_atdd_budget_is_zero(self):
        """testarch-atdd should have budget=0 (no source context)."""
        from bmad_assist.core.config.models.source_context import SourceContextBudgetsConfig

        config = SourceContextBudgetsConfig()
        assert config.get_budget("testarch-atdd") == 0

    def test_testarch_automate_budget_enabled(self):
        """testarch-automate should have budget=10000 (needs source for discovery)."""
        from bmad_assist.core.config.models.source_context import SourceContextBudgetsConfig

        config = SourceContextBudgetsConfig()
        assert config.get_budget("testarch-automate") == 10000

    def test_testarch_nfr_assess_budget_enabled(self):
        """testarch-nfr-assess should have budget=10000 (needs source for code health)."""
        from bmad_assist.core.config.models.source_context import SourceContextBudgetsConfig

        config = SourceContextBudgetsConfig()
        assert config.get_budget("testarch-nfr-assess") == 10000

    def test_other_tea_workflows_have_zero_budget(self):
        """Most TEA workflows should have budget=0."""
        from bmad_assist.core.config.models.source_context import SourceContextBudgetsConfig

        config = SourceContextBudgetsConfig()

        for workflow in [
            "testarch-trace",
            "testarch-test-review",
            "testarch-framework",
            "testarch-ci",
            "testarch-test-design",
        ]:
            budget = config.get_budget(workflow)
            assert budget == 0, f"{workflow} should have budget=0, got {budget}"

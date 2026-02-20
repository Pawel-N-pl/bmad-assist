"""Tests for State data model (Story 3.1).

Story 3.1 Tests cover:
- AC1: State model contains required fields
- AC2: Phase enum defines workflow phases
- AC3: Default factory creates valid initial state
- AC4: State accepts valid field values
- AC5: State validates invalid field types
- AC6: State serializes to dict for YAML
- AC7: State deserializes from dict
- AC8: State is mutable (frozen=False)
- AC9: State exports from module
- AC10: Google-style docstrings present
"""

from datetime import datetime

import pytest
import yaml
from pydantic import ValidationError

from bmad_assist.core.state import Phase, State


# =============================================================================
# AC2: Phase enum defines workflow phases
# =============================================================================


class TestPhaseEnum:
    """Test Phase enum values and ordering (AC2)."""

    def test_phase_enum_has_eighteen_values(self) -> None:
        """Phase enum contains exactly 19 workflow phases (including TEA handlers + QA)."""
        assert len(Phase) == 19

    def test_phase_enum_values_in_order(self) -> None:
        """Phase enum values match expected order."""
        expected_order = [
            ("CREATE_STORY", "create_story"),
            ("VALIDATE_STORY", "validate_story"),
            ("VALIDATE_STORY_SYNTHESIS", "validate_story_synthesis"),
            ("ATDD", "atdd"),
            ("DEV_STORY", "dev_story"),
            ("CODE_REVIEW", "code_review"),
            ("CODE_REVIEW_SYNTHESIS", "code_review_synthesis"),
            ("TEST_REVIEW", "test_review"),
            ("TRACE", "trace"),
            ("TEA_FRAMEWORK", "tea_framework"),
            ("TEA_CI", "tea_ci"),
            ("TEA_TEST_DESIGN", "tea_test_design"),
            ("TEA_AUTOMATE", "tea_automate"),
            ("TEA_NFR_ASSESS", "tea_nfr_assess"),
            ("RETROSPECTIVE", "retrospective"),
            ("HARDENING", "hardening"),
            ("QA_PLAN_GENERATE", "qa_plan_generate"),
            ("QA_PLAN_EXECUTE", "qa_plan_execute"),
            ("QA_REMEDIATE", "qa_remediate"),
        ]
        actual_order = [(p.name, p.value) for p in Phase]
        assert actual_order == expected_order

    def test_phase_enum_create_story(self) -> None:
        """CREATE_STORY is first phase."""
        assert Phase.CREATE_STORY.value == "create_story"
        assert list(Phase)[0] == Phase.CREATE_STORY

    def test_phase_enum_qa_remediate(self) -> None:
        """QA_REMEDIATE is last phase."""
        assert Phase.QA_REMEDIATE.value == "qa_remediate"
        assert list(Phase)[-1] == Phase.QA_REMEDIATE

    def test_phase_can_be_accessed_by_name(self) -> None:
        """Phase enum members accessible by name."""
        assert Phase["DEV_STORY"] == Phase.DEV_STORY
        assert Phase["CODE_REVIEW"] == Phase.CODE_REVIEW

    def test_phase_can_be_created_from_value(self) -> None:
        """Phase enum members creatable from string value."""
        assert Phase("dev_story") == Phase.DEV_STORY
        assert Phase("code_review") == Phase.CODE_REVIEW


# =============================================================================
# AC1, AC3: State model fields and defaults
# =============================================================================


class TestStateModel:
    """Test State model fields and default values (AC1, AC3)."""

    def test_state_default_current_epic_is_none(self, default_state: State) -> None:
        """Default state has current_epic=None."""
        assert default_state.current_epic is None

    def test_state_default_current_story_is_none(self, default_state: State) -> None:
        """Default state has current_story=None."""
        assert default_state.current_story is None

    def test_state_default_current_phase_is_none(self, default_state: State) -> None:
        """Default state has current_phase=None."""
        assert default_state.current_phase is None

    def test_state_default_completed_stories_is_empty_list(self, default_state: State) -> None:
        """Default state has completed_stories=[]."""
        assert default_state.completed_stories == []
        assert isinstance(default_state.completed_stories, list)

    def test_state_default_completed_epics_is_empty_list(self, default_state: State) -> None:
        """Default state has completed_epics=[]."""
        assert default_state.completed_epics == []
        assert isinstance(default_state.completed_epics, list)

    def test_state_default_started_at_is_none(self, default_state: State) -> None:
        """Default state has started_at=None."""
        assert default_state.started_at is None

    def test_state_default_updated_at_is_none(self, default_state: State) -> None:
        """Default state has updated_at=None."""
        assert default_state.updated_at is None

    def test_state_default_is_valid_object(self, default_state: State) -> None:
        """Default State() creates valid State object."""
        assert isinstance(default_state, State)


# =============================================================================
# AC4: State accepts valid field values
# =============================================================================


class TestStateValidValues:
    """Test State accepts valid field values (AC4)."""

    def test_state_with_all_values(self, populated_state: State) -> None:
        """State stores all provided values correctly."""
        assert populated_state.current_epic == 3
        assert populated_state.current_story == "3.1"
        assert populated_state.current_phase == Phase.DEV_STORY
        assert populated_state.completed_stories == ["1.1", "1.2", "2.1", "2.2", "2.3"]
        assert populated_state.started_at == datetime(2025, 12, 10, 8, 0, 0)
        assert populated_state.updated_at == datetime(2025, 12, 10, 14, 30, 0)

    def test_state_with_partial_values(self) -> None:
        """State accepts partial field values."""
        state = State(current_epic=1, current_phase=Phase.CREATE_STORY)
        assert state.current_epic == 1
        assert state.current_story is None
        assert state.current_phase == Phase.CREATE_STORY
        assert state.completed_stories == []

    def test_state_completed_stories_accepts_list(self) -> None:
        """completed_stories field accepts list of strings."""
        state = State(completed_stories=["1.1", "1.2", "1.3"])
        assert state.completed_stories == ["1.1", "1.2", "1.3"]

    def test_state_datetime_fields_accept_datetime(self) -> None:
        """Datetime fields accept datetime objects."""
        now = datetime.now()
        state = State(started_at=now, updated_at=now)
        assert state.started_at == now
        assert state.updated_at == now


# =============================================================================
# AC5: State validates invalid field types
# =============================================================================


class TestStateValidation:
    """Test State Pydantic validation errors (AC5)."""

    def test_state_rejects_invalid_current_epic_type(self) -> None:
        """current_epic rejects invalid types (list, dict) but accepts int or str."""
        # String epic IDs are now valid (e.g., "testarch", "0a")
        state = State(current_epic="testarch")
        assert state.current_epic == "testarch"

        # Int epic IDs remain valid
        state = State(current_epic=3)
        assert state.current_epic == 3

        # Invalid types should still be rejected
        with pytest.raises(ValidationError) as exc_info:
            State(current_epic=["invalid"])  # type: ignore[arg-type]
        assert "current_epic" in str(exc_info.value)

    def test_state_rejects_invalid_completed_stories_type(self) -> None:
        """completed_stories rejects non-list values."""
        with pytest.raises(ValidationError) as exc_info:
            State(completed_stories="not-a-list")  # type: ignore[arg-type]
        assert "completed_stories" in str(exc_info.value)

    def test_state_rejects_invalid_phase_type(self) -> None:
        """current_phase rejects invalid string values."""
        with pytest.raises(ValidationError) as exc_info:
            State(current_phase="not-a-phase")  # type: ignore[arg-type]
        assert "current_phase" in str(exc_info.value)

    def test_state_rejects_invalid_datetime_type(self) -> None:
        """Datetime fields reject invalid values."""
        with pytest.raises(ValidationError) as exc_info:
            State(started_at="invalid-datetime")  # type: ignore[arg-type]
        assert "started_at" in str(exc_info.value)

    def test_state_rejects_float_for_current_epic(self) -> None:
        """current_epic rejects float values."""
        with pytest.raises(ValidationError) as exc_info:
            State(current_epic=3.5)  # type: ignore[arg-type]
        assert "current_epic" in str(exc_info.value)


# =============================================================================
# AC6: State serializes to dict for YAML
# =============================================================================


class TestStateSerialization:
    """Test State serialization to dict (AC6)."""

    def test_state_model_dump_returns_dict(self, populated_state: State) -> None:
        """model_dump() returns dict."""
        data = populated_state.model_dump()
        assert isinstance(data, dict)

    def test_state_model_dump_contains_all_fields(self, populated_state: State) -> None:
        """model_dump() contains all fields."""
        data = populated_state.model_dump()
        assert "current_epic" in data
        assert "current_story" in data
        assert "current_phase" in data
        assert "completed_stories" in data
        assert "completed_epics" in data
        assert "started_at" in data
        assert "updated_at" in data

    def test_state_model_dump_mode_json_serializes_phase_as_string(
        self, populated_state: State
    ) -> None:
        """model_dump(mode='json') serializes Phase as string value."""
        data = populated_state.model_dump(mode="json")
        assert data["current_phase"] == "dev_story"
        assert isinstance(data["current_phase"], str)

    def test_state_model_dump_mode_json_serializes_datetime_as_iso(
        self, populated_state: State
    ) -> None:
        """model_dump(mode='json') serializes datetime as ISO string."""
        data = populated_state.model_dump(mode="json")
        assert data["started_at"] == "2025-12-10T08:00:00"
        assert data["updated_at"] == "2025-12-10T14:30:00"
        assert isinstance(data["started_at"], str)

    def test_state_model_dump_can_be_passed_to_yaml_dump(self, populated_state: State) -> None:
        """model_dump(mode='json') output can be passed to yaml.dump()."""
        data = populated_state.model_dump(mode="json")
        yaml_output = yaml.dump(data)
        assert isinstance(yaml_output, str)
        assert "current_epic: 3" in yaml_output
        assert "current_phase: dev_story" in yaml_output


# =============================================================================
# AC7: State deserializes from dict
# =============================================================================


class TestStateDeserialization:
    """Test State deserialization from dict (AC7)."""

    def test_state_model_validate_from_dict(self, state_as_dict: dict) -> None:
        """State.model_validate(data) creates State from dict."""
        state = State.model_validate(state_as_dict)
        assert isinstance(state, State)
        assert state.current_epic == 2
        assert state.current_story == "2.3"

    def test_state_model_validate_converts_string_to_phase_enum(self, state_as_dict: dict) -> None:
        """model_validate converts string to Phase enum."""
        state = State.model_validate(state_as_dict)
        assert state.current_phase == Phase.CODE_REVIEW
        assert isinstance(state.current_phase, Phase)

    def test_state_model_validate_parses_iso_datetime(self, state_as_dict: dict) -> None:
        """model_validate parses ISO datetime string to datetime."""
        state = State.model_validate(state_as_dict)
        assert state.started_at == datetime(2025, 12, 10, 8, 0, 0)
        assert isinstance(state.started_at, datetime)

    def test_state_from_kwargs(self, state_as_dict: dict) -> None:
        """State(**data) creates State from dict."""
        state = State(**state_as_dict)
        assert state.current_epic == 2
        assert state.current_phase == Phase.CODE_REVIEW

    def test_state_round_trip_serialization(self, populated_state: State) -> None:
        """State survives round-trip: State -> dict -> State."""
        data = populated_state.model_dump(mode="json")
        restored = State.model_validate(data)
        assert restored.current_epic == populated_state.current_epic
        assert restored.current_story == populated_state.current_story
        assert restored.current_phase == populated_state.current_phase
        assert restored.completed_stories == populated_state.completed_stories
        assert restored.started_at == populated_state.started_at
        assert restored.updated_at == populated_state.updated_at


# =============================================================================
# AC8: State is mutable (frozen=False)
# =============================================================================


class TestStateMutability:
    """Test State mutability configuration (AC8)."""

    def test_state_is_mutable(self, default_state: State) -> None:
        """State allows field updates (frozen=False)."""
        default_state.current_epic = 5
        assert default_state.current_epic == 5

    def test_state_can_update_phase(self, default_state: State) -> None:
        """State allows updating current_phase."""
        default_state.current_phase = Phase.DEV_STORY
        assert default_state.current_phase == Phase.DEV_STORY

    def test_state_can_append_to_completed_stories(self, default_state: State) -> None:
        """State allows modifying completed_stories list."""
        default_state.completed_stories.append("1.1")
        assert "1.1" in default_state.completed_stories


# =============================================================================
# AC9: State exports from module
# =============================================================================


class TestModuleExports:
    """Test module exports (AC9)."""

    def test_state_importable_from_module(self) -> None:
        """State is importable from bmad_assist.core.state."""
        from bmad_assist.core.state import State as ImportedState

        assert ImportedState is State

    def test_phase_importable_from_module(self) -> None:
        """Phase is importable from bmad_assist.core.state."""
        from bmad_assist.core.state import Phase as ImportedPhase

        assert ImportedPhase is Phase

    def test_module_all_contains_state_and_phase(self) -> None:
        """__all__ contains State and Phase."""
        from bmad_assist.core import state as state_module

        assert hasattr(state_module, "__all__")
        assert "State" in state_module.__all__
        assert "Phase" in state_module.__all__


# =============================================================================
# AC10: Google-style docstrings present
# =============================================================================


class TestDocstrings:
    """Test Google-style docstrings are present (AC10)."""

    def test_state_class_has_docstring(self) -> None:
        """State class has docstring."""
        assert State.__doc__ is not None
        assert len(State.__doc__) > 0

    def test_phase_class_has_docstring(self) -> None:
        """Phase class has docstring."""
        assert Phase.__doc__ is not None
        assert len(Phase.__doc__) > 0

    def test_state_docstring_mentions_purpose(self) -> None:
        """State docstring explains its purpose."""
        assert State.__doc__ is not None
        assert "development loop" in State.__doc__.lower() or "state" in State.__doc__.lower()

    def test_phase_docstring_mentions_workflow(self) -> None:
        """Phase docstring explains workflow phases."""
        assert Phase.__doc__ is not None
        assert "phase" in Phase.__doc__.lower() or "workflow" in Phase.__doc__.lower()


# =============================================================================
# YAML round-trip test
# =============================================================================


class TestYamlRoundTrip:
    """Test complete YAML round-trip serialization."""

    def test_yaml_round_trip_full_state(self, populated_state: State) -> None:
        """State survives YAML round-trip: State -> yaml.dump -> yaml.safe_load -> State."""
        # Serialize to YAML-compatible dict
        data = populated_state.model_dump(mode="json")

        # Dump to YAML string
        yaml_str = yaml.dump(data)

        # Load from YAML string
        loaded_data = yaml.safe_load(yaml_str)

        # Reconstruct State
        restored = State.model_validate(loaded_data)

        # Verify all fields
        assert restored.current_epic == populated_state.current_epic
        assert restored.current_story == populated_state.current_story
        assert restored.current_phase == populated_state.current_phase
        assert restored.completed_stories == populated_state.completed_stories
        assert restored.started_at == populated_state.started_at
        assert restored.updated_at == populated_state.updated_at

    def test_yaml_round_trip_empty_state(self, default_state: State) -> None:
        """Empty state survives YAML round-trip."""
        data = default_state.model_dump(mode="json")
        yaml_str = yaml.dump(data)
        loaded_data = yaml.safe_load(yaml_str)
        restored = State.model_validate(loaded_data)

        assert restored.current_epic is None
        assert restored.current_story is None
        assert restored.current_phase is None
        assert restored.completed_stories == []
        assert restored.started_at is None
        assert restored.updated_at is None

    def test_yaml_round_trip_preserves_completed_stories_order(self) -> None:
        """YAML round-trip preserves order of completed_stories."""
        state = State(completed_stories=["1.1", "2.1", "1.2", "3.1"])
        data = state.model_dump(mode="json")
        yaml_str = yaml.dump(data)
        loaded_data = yaml.safe_load(yaml_str)
        restored = State.model_validate(loaded_data)

        assert restored.completed_stories == ["1.1", "2.1", "1.2", "3.1"]

    def test_yaml_round_trip_with_completed_epics(self) -> None:
        """YAML round-trip preserves completed_epics list."""
        state = State(
            current_epic=5,
            current_story="5.1",
            completed_stories=["1.1", "2.1", "3.1", "4.1"],
            completed_epics=[1, 2, 3, 4],
        )
        data = state.model_dump(mode="json")
        yaml_str = yaml.dump(data)
        loaded_data = yaml.safe_load(yaml_str)
        restored = State.model_validate(loaded_data)

        assert restored.completed_epics == [1, 2, 3, 4]
        assert restored.current_epic == 5


# =============================================================================
# Preflight State Entry Tests (Story testarch-5)
# =============================================================================


class TestPreflightStateEntry:
    """Test PreflightStateEntry model and State.testarch_preflight field."""

    def test_state_default_preflight_is_none(self) -> None:
        """State.testarch_preflight defaults to None."""
        state = State()
        assert state.testarch_preflight is None

    def test_state_with_preflight_entry(self) -> None:
        """State accepts PreflightStateEntry for testarch_preflight."""
        from bmad_assist.core.state import PreflightStateEntry

        entry = PreflightStateEntry(
            completed_at=datetime(2026, 1, 4, 12, 0, 0),
            test_design="found",
            framework="not_found",
            ci="skipped",
        )
        state = State(testarch_preflight=entry)

        assert state.testarch_preflight is not None
        assert state.testarch_preflight.test_design == "found"
        assert state.testarch_preflight.framework == "not_found"
        assert state.testarch_preflight.ci == "skipped"

    def test_preflight_yaml_round_trip(self) -> None:
        """PreflightStateEntry survives YAML round-trip."""
        from bmad_assist.core.state import PreflightStateEntry

        entry = PreflightStateEntry(
            completed_at=datetime(2026, 1, 4, 12, 30, 45),
            test_design="found",
            framework="found",
            ci="not_found",
        )
        state = State(testarch_preflight=entry)

        # Serialize
        data = state.model_dump(mode="json")
        yaml_str = yaml.dump(data)

        # Deserialize
        loaded_data = yaml.safe_load(yaml_str)
        restored = State.model_validate(loaded_data)

        # Verify
        assert restored.testarch_preflight is not None
        assert restored.testarch_preflight.completed_at == datetime(2026, 1, 4, 12, 30, 45)
        assert restored.testarch_preflight.test_design == "found"
        assert restored.testarch_preflight.framework == "found"
        assert restored.testarch_preflight.ci == "not_found"

    def test_preflight_state_entry_module_export(self) -> None:
        """PreflightStateEntry is exported from state module."""
        from bmad_assist.core import state as state_module

        assert "PreflightStateEntry" in state_module.__all__


# =============================================================================
# ATDD State Tracking Fields (Story testarch-6)
# =============================================================================


class TestATDDStateFields:
    """Test ATDD state tracking fields: atdd_ran_for_story and atdd_ran_in_epic."""

    def test_state_default_atdd_ran_for_story_is_false(self) -> None:
        """State.atdd_ran_for_story defaults to False."""
        state = State()
        assert state.atdd_ran_for_story is False

    def test_state_default_atdd_ran_in_epic_is_false(self) -> None:
        """State.atdd_ran_in_epic defaults to False."""
        state = State()
        assert state.atdd_ran_in_epic is False

    def test_state_accepts_atdd_ran_for_story_true(self) -> None:
        """State accepts atdd_ran_for_story=True."""
        state = State(atdd_ran_for_story=True)
        assert state.atdd_ran_for_story is True

    def test_state_accepts_atdd_ran_in_epic_true(self) -> None:
        """State accepts atdd_ran_in_epic=True."""
        state = State(atdd_ran_in_epic=True)
        assert state.atdd_ran_in_epic is True

    def test_atdd_fields_yaml_round_trip(self) -> None:
        """ATDD state fields survive YAML round-trip."""
        state = State(
            current_epic=1,
            current_story="1.1",
            atdd_ran_for_story=True,
            atdd_ran_in_epic=True,
        )

        # Serialize
        data = state.model_dump(mode="json")
        yaml_str = yaml.dump(data)

        # Deserialize
        loaded_data = yaml.safe_load(yaml_str)
        restored = State.model_validate(loaded_data)

        # Verify
        assert restored.atdd_ran_for_story is True
        assert restored.atdd_ran_in_epic is True

    def test_backward_compatibility_old_state_without_atdd_fields(self) -> None:
        """Old state files without ATDD fields load with defaults."""
        # Simulate old state YAML without atdd_ran_* fields
        old_state_data = {
            "current_epic": 3,
            "current_story": "3.1",
            "current_phase": "dev_story",
            "completed_stories": ["1.1", "2.1"],
            "completed_epics": [1, 2],
            "started_at": "2026-01-01T10:00:00",
            "updated_at": "2026-01-01T12:00:00",
            "anomalies": [],
            "testarch_preflight": None,
            # Note: atdd_ran_for_story and atdd_ran_in_epic are NOT present
        }

        # Load should succeed with default values
        state = State.model_validate(old_state_data)
        assert state.current_epic == 3
        assert state.current_story == "3.1"
        assert state.atdd_ran_for_story is False  # Default
        assert state.atdd_ran_in_epic is False  # Default


# =============================================================================
# Framework/CI State Tracking Fields (Story 25.9)
# =============================================================================


class TestFrameworkCIStateFields:
    """Test framework_ran_in_epic and ci_ran_in_epic state tracking fields."""

    def test_state_default_framework_ran_in_epic_is_false(self) -> None:
        """State.framework_ran_in_epic defaults to False."""
        state = State()
        assert state.framework_ran_in_epic is False

    def test_state_default_ci_ran_in_epic_is_false(self) -> None:
        """State.ci_ran_in_epic defaults to False."""
        state = State()
        assert state.ci_ran_in_epic is False

    def test_state_accepts_framework_ran_in_epic_true(self) -> None:
        """State accepts framework_ran_in_epic=True."""
        state = State(framework_ran_in_epic=True)
        assert state.framework_ran_in_epic is True

    def test_state_accepts_ci_ran_in_epic_true(self) -> None:
        """State accepts ci_ran_in_epic=True."""
        state = State(ci_ran_in_epic=True)
        assert state.ci_ran_in_epic is True

    def test_framework_ci_fields_yaml_round_trip(self) -> None:
        """Framework/CI state fields survive YAML round-trip."""
        state = State(
            current_epic=1,
            current_story="1.1",
            framework_ran_in_epic=True,
            ci_ran_in_epic=True,
        )

        # Serialize
        data = state.model_dump(mode="json")
        yaml_str = yaml.dump(data)

        # Deserialize
        loaded_data = yaml.safe_load(yaml_str)
        restored = State.model_validate(loaded_data)

        # Verify
        assert restored.framework_ran_in_epic is True
        assert restored.ci_ran_in_epic is True

    def test_backward_compatibility_old_state_without_framework_ci_fields(self) -> None:
        """Old state files without framework/CI fields load with defaults."""
        old_state_data = {
            "current_epic": 3,
            "current_story": "3.1",
            "current_phase": "dev_story",
            "completed_stories": ["1.1", "2.1"],
            "completed_epics": [1, 2],
            "started_at": "2026-01-01T10:00:00",
            "updated_at": "2026-01-01T12:00:00",
            "anomalies": [],
            "testarch_preflight": None,
            "atdd_ran_for_story": False,
            "atdd_ran_in_epic": True,
            # Note: framework_ran_in_epic and ci_ran_in_epic are NOT present
        }

        # Load should succeed with default values
        state = State.model_validate(old_state_data)
        assert state.framework_ran_in_epic is False  # Default
        assert state.ci_ran_in_epic is False  # Default


class TestPhaseEnumTeaFrameworkCI:
    """Test TEA_FRAMEWORK and TEA_CI Phase enum values."""

    def test_tea_framework_phase_exists(self) -> None:
        """TEA_FRAMEWORK phase exists in Phase enum."""
        assert Phase.TEA_FRAMEWORK.value == "tea_framework"

    def test_tea_ci_phase_exists(self) -> None:
        """TEA_CI phase exists in Phase enum."""
        assert Phase.TEA_CI.value == "tea_ci"

    def test_tea_framework_can_be_created_from_value(self) -> None:
        """TEA_FRAMEWORK can be created from string value."""
        assert Phase("tea_framework") == Phase.TEA_FRAMEWORK

    def test_tea_ci_can_be_created_from_value(self) -> None:
        """TEA_CI can be created from string value."""
        assert Phase("tea_ci") == Phase.TEA_CI

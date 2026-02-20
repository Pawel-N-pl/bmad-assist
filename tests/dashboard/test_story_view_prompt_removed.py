"""Tests for Story 24.10 - Remove Story-level View Prompt.

These tests verify:
1. getStoryActions() does NOT include view-prompt for any status
2. getPhaseActions() STILL includes view-prompt as first action
3. view-prompt handler is simplified (no type branch)
4. No regressions in other story/phase actions
"""

from pathlib import Path

import pytest


# Story 24.10 synthesis: Module-level fixture to avoid DRY violation
# Previously duplicated across 5 test classes
@pytest.fixture
def context_menu_content() -> str:
    """Read context-menu.js content - shared across all test classes."""
    context_menu_path = (
        Path(__file__).parent.parent.parent
        / "src/bmad_assist/dashboard/static-src/js/components/context-menu.js"
    )
    return context_menu_path.read_text(encoding="utf-8")


class TestStoryActionsNoViewPrompt:
    """Tests verifying View Prompt is removed from all story statuses (AC 1)."""

    def test_ready_for_dev_no_view_prompt(self, context_menu_content: str) -> None:
        """AC1: ready-for-dev status should NOT have view-prompt action."""
        # Find the ready-for-dev case
        case_start = context_menu_content.find("case 'ready-for-dev':")
        assert case_start != -1, "ready-for-dev case not found"

        # Find the next case to bound our search
        next_case = context_menu_content.find("case '", case_start + 20)
        section = context_menu_content[case_start:next_case]

        # Should NOT contain view-prompt action
        assert "action: 'view-prompt'" not in section
        # Should have Story 24.10 comment
        assert "Story 24.10" in section

    def test_in_progress_no_view_prompt(self, context_menu_content: str) -> None:
        """AC1: in-progress status should NOT have view-prompt action."""
        case_start = context_menu_content.find("case 'in-progress':")
        assert case_start != -1, "in-progress case not found"

        next_case = context_menu_content.find("case '", case_start + 20)
        section = context_menu_content[case_start:next_case]

        assert "action: 'view-prompt'" not in section
        assert "Story 24.10" in section

    def test_review_no_view_prompt(self, context_menu_content: str) -> None:
        """AC1: review status should NOT have view-prompt action."""
        case_start = context_menu_content.find("case 'review':")
        assert case_start != -1, "review case not found"

        next_case = context_menu_content.find("case '", case_start + 15)
        section = context_menu_content[case_start:next_case]

        assert "action: 'view-prompt'" not in section
        assert "Story 24.10" in section

    def test_done_no_view_prompt(self, context_menu_content: str) -> None:
        """AC1: done status should NOT have view-prompt action."""
        case_start = context_menu_content.find("case 'done':")
        assert case_start != -1, "done case not found"

        # Find the return statement that ends this case
        return_stmt = context_menu_content.find("return [", case_start)
        # Find the closing bracket of that return
        closing_bracket = context_menu_content.find("];", return_stmt)
        section = context_menu_content[case_start : closing_bracket + 2]

        assert "action: 'view-prompt'" not in section
        assert "Story 24.10" in section


class TestPhaseActionsHasViewPrompt:
    """Tests verifying View Prompt is preserved for phase context menus (AC 2)."""

    def test_phase_actions_has_view_prompt(self, context_menu_content: str) -> None:
        """AC2: getPhaseActions() should still include view-prompt as first action."""
        # Find getPhaseActions function
        func_start = context_menu_content.find("getPhaseActions(phase)")
        assert func_start != -1, "getPhaseActions function not found"

        # Find the first actions.push (should be View Prompt)
        first_push = context_menu_content.find("actions.push", func_start)
        assert first_push != -1, "No actions.push found in getPhaseActions"

        # Get the section up to closing brace
        first_action = context_menu_content[first_push : first_push + 200]

        # Should be view-prompt
        assert "action: 'view-prompt'" in first_action
        assert "testId: 'action-view-prompt'" in first_action

    def test_phase_view_prompt_first_action(self, context_menu_content: str) -> None:
        """AC2: View Prompt should be the FIRST action in phase actions."""
        func_start = context_menu_content.find("getPhaseActions(phase)")
        assert func_start != -1

        # Find first push and verify it's view-prompt
        first_push = context_menu_content.find("actions.push", func_start)
        view_prompt_push = context_menu_content.find(
            "action: 'view-prompt'", func_start
        )

        # view-prompt should be in the first push
        assert (
            view_prompt_push < first_push + 200
        ), "view-prompt not in first actions.push"


class TestViewPromptHandlerSimplified:
    """Tests verifying view-prompt handler is simplified (AC 3)."""

    def test_no_type_check_in_handler(self, context_menu_content: str) -> None:
        """AC3: view-prompt handler should NOT check type === 'phase' anymore."""
        # Find the view-prompt case in executeAction
        case_start = context_menu_content.find("case 'view-prompt':")
        assert case_start != -1, "view-prompt case not found"

        # Find the next case
        next_case = context_menu_content.find("case '", case_start + 20)
        section = context_menu_content[case_start:next_case]

        # Should NOT have the type === 'phase' check
        assert "if (type === 'phase')" not in section
        assert "type === 'phase'" not in section

    def test_no_story_level_comment(self, context_menu_content: str) -> None:
        """AC3: Handler should NOT have story-level comment anymore."""
        case_start = context_menu_content.find("case 'view-prompt':")
        assert case_start != -1

        next_case = context_menu_content.find("case '", case_start + 20)
        section = context_menu_content[case_start:next_case]

        # Should NOT have the old story-level comment
        assert "Story-level" not in section

    def test_uses_item_id_directly(self, context_menu_content: str) -> None:
        """AC3: Handler should use item?.id directly without type branch."""
        case_start = context_menu_content.find("case 'view-prompt':")
        assert case_start != -1

        next_case = context_menu_content.find("case '", case_start + 20)
        section = context_menu_content[case_start:next_case]

        # Should use item?.id || 'dev_story' directly (not in a conditional)
        assert "const phaseId = item?.id || 'dev_story'" in section

    def test_story_24_10_comment_present(self, context_menu_content: str) -> None:
        """AC3: Handler should have Story 24.10 traceability comment."""
        case_start = context_menu_content.find("case 'view-prompt':")
        assert case_start != -1

        next_case = context_menu_content.find("case '", case_start + 20)
        section = context_menu_content[case_start:next_case]

        # Should have Story 24.10 comment
        assert "Story 24.10" in section

    def test_handler_still_has_defensive_warning(
        self, context_menu_content: str
    ) -> None:
        """Handler should still have defensive warning when item.id is undefined."""
        case_start = context_menu_content.find("case 'view-prompt':")
        assert case_start != -1

        next_case = context_menu_content.find("case '", case_start + 20)
        section = context_menu_content[case_start:next_case]

        # Should still have console.warn for undefined ID
        assert "console.warn" in section
        assert "Phase ID undefined" in section


class TestStoryActionsComplete:
    """Tests verifying all expected story actions are present (AC 4 - no regressions)."""

    def test_ready_for_dev_has_expected_actions(
        self, context_menu_content: str
    ) -> None:
        """ready-for-dev should have: View Story, Run dev-story, Open story file."""
        case_start = context_menu_content.find("case 'ready-for-dev':")
        next_case = context_menu_content.find("case '", case_start + 20)
        section = context_menu_content[case_start:next_case]

        assert "action: 'view-story-modal'" in section
        assert "action: 'run-dev-story'" in section
        assert "action: 'open-file'" in section
        # Should NOT have view-prompt
        assert "action: 'view-prompt'" not in section

    def test_in_progress_has_expected_actions(self, context_menu_content: str) -> None:
        """in-progress should have: View Story, Open story file."""
        case_start = context_menu_content.find("case 'in-progress':")
        next_case = context_menu_content.find("case '", case_start + 20)
        section = context_menu_content[case_start:next_case]

        assert "action: 'view-story-modal'" in section
        assert "action: 'open-file'" in section
        # Should NOT have view-prompt
        assert "action: 'view-prompt'" not in section

    def test_review_has_expected_actions(self, context_menu_content: str) -> None:
        """Review should have: View Story, Open story file, View review."""
        case_start = context_menu_content.find("case 'review':")
        next_case = context_menu_content.find("case '", case_start + 15)
        section = context_menu_content[case_start:next_case]

        assert "action: 'view-story-modal'" in section
        assert "action: 'open-file'" in section
        assert "action: 'view-review'" in section
        # Should NOT have view-prompt
        assert "action: 'view-prompt'" not in section

    def test_done_has_expected_actions(self, context_menu_content: str) -> None:
        """Done should have: View Story, View review, Re-run."""
        case_start = context_menu_content.find("case 'done':")
        # Find the return statement that ends this case
        return_stmt = context_menu_content.find("return [", case_start)
        # Find the closing bracket of that return
        closing_bracket = context_menu_content.find("];", return_stmt)
        section = context_menu_content[case_start : closing_bracket + 2]

        assert "action: 'view-story-modal'" in section
        assert "action: 'view-review'" in section
        assert "action: 're-run'" in section
        # Should NOT have view-prompt
        assert "action: 'view-prompt'" not in section

    def test_backlog_unchanged(self, context_menu_content: str) -> None:
        """Backlog should still have: View Story, View in epic (never had view-prompt)."""
        case_start = context_menu_content.find("case 'backlog':")
        next_case = context_menu_content.find("case '", case_start + 15)
        section = context_menu_content[case_start:next_case]

        assert "action: 'view-story-modal'" in section
        assert "action: 'view-story'" in section
        # backlog never had view-prompt
        assert "action: 'view-prompt'" not in section


class TestPhaseActionsComplete:
    """Tests verifying phase actions are preserved (AC 4 - no regressions)."""

    def test_phase_actions_has_common_actions(self, context_menu_content: str) -> None:
        """All phases should have: View prompt, Re-run, Skip."""
        func_start = context_menu_content.find("getPhaseActions(phase)")
        func_end = context_menu_content.find("return actions;", func_start)
        section = context_menu_content[func_start:func_end]

        assert "action: 'view-prompt'" in section
        assert "action: 're-run-phase'" in section
        assert "action: 'skip-phase'" in section

    def test_phase_view_prompt_testid_present(self, context_menu_content: str) -> None:
        """Phase view-prompt should have correct test ID."""
        func_start = context_menu_content.find("getPhaseActions(phase)")
        func_end = context_menu_content.find("return actions;", func_start)
        section = context_menu_content[func_start:func_end]

        assert "testId: 'action-view-prompt'" in section

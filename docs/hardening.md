# Hardening Feature

The hardening feature in `bmad-assist` provides automated remediation and triage of issues identified during an epic's retrospective phase. It acts as an intelligent bridge between the development lifecycle and the Quality Assurance (QA) pipeline, ensuring that known technical debt, skipped tests, or architectural improvements are addressed before an epic is formally tested.

## High-Level Workflow

The hardening phase operates as part of the `epic_teardown` sequence (configurable via the `loop.yaml` configuration). It requires that the `retrospective` phase has accurately generated an action items report for the epic.

1. **Triage**: The `HardeningHandler` reads the retrospective report and instructs the Master LLM to triage the action items.
2. **Decision Making**: The LLM outputs structured triage fields (`has_direct_fixes`, `story_needed`, `fixes_applied`, `story_content`) and the handler executes them as a pipeline:
   - If `fixes_applied` contains items, trivial fixes are recorded as directly applied.
   - If `story_needed` is true (or `story_content` is provided), a hardening story is generated for complex work only (e.g., `7-4-hardening.md`).
   - If both are present, mixed retrospectives are handled in one pass: trivial items are fixed immediately and the generated story stays focused on complex items.
   - If neither is present, hardening is marked done with no story.
3. **Execution Pause**: If a hardening story is generated, the epic's teardown execution is suspended, preventing subsequent QA phases from starting prematurely.
4. **Implementation**: The newly generated hardening story is injected into the active epic. The loop cleanly re-enters at the first story-level phase (typically `CREATE_STORY`), where the generated markdown is refined and validated before moving through the rest of the loop (`VALIDATE_STORY` -> `DEV_STORY` -> ... -> `CODE_REVIEW_SYNTHESIS`).
5. **QA Resumption**: Upon completion of the hardening story, the epic lifecycle resumes from where it left off in the teardown sequence, cleanly executing the QA pipeline phases.

## State Machine & Orchestration

The integration of the hardening story relies heavily on `EpicLifecycle` state management across `epic_phases.py`, `runner.py`, and the `HardeningHandler`.

### 1. `HardeningHandler` (`src/bmad_assist/core/loop/handlers/hardening.py`)
- Executes the LLM triage via the prompt template defined in `instructions.md`.
- Parses the structured `HARDENING_TRIAGE` JSON block.
- Generates the story file `{epic_id}-{story_num}-hardening.md` when complex follow-up work is required (`story_needed=true`, including mixed outcomes).
- Registers the story into `sprint-status.yaml` as an `EPIC_STORY` entry with the status `backlog`.
- Transitions the state: `state.epic_lifecycle = EpicLifecycle.HARDENING`.

### 2. Epic Teardown Suspend (`src/bmad_assist/core/loop/epic_phases.py`)
- Inside `_execute_epic_teardown`, after each teardown phase executes successfully, the state is checked:
  ```python
  if state.epic_lifecycle == EpicLifecycle.HARDENING:
      logger.info("Epic lifecycle transitioned to HARDENING. Suspending teardown to execute hardening story.")
      break
  ```
- This `break` immediately suspends the sequence, blocking execution of phases like `qa_plan_generate` or `qa_plan_execute`.

### 3. Story Completion & Resumption (`src/bmad_assist/core/loop/runner.py` & `story_transitions.py`)
- When the `CODE_REVIEW_SYNTHESIS` phase completes for the hardening story, `handle_story_completion` recognizes that it's the final story of the epic.
- The lifecycle transitions from `EpicLifecycle.HARDENING` to `EpicLifecycle.QA_RELEASE`.
- `runner.py` observes that the epic is complete and the lifecycle is `QA_RELEASE`. It explicitly re-invokes `_execute_epic_teardown`.

### 4. QA Pipeline Slice (`src/bmad_assist/core/loop/epic_phases.py`)
- When `_execute_epic_teardown` is re-invoked in the `QA_RELEASE` lifecycle, it must avoid re-running `retrospective` and `hardening`:
  ```python
  if state.epic_lifecycle == EpicLifecycle.QA_RELEASE:
      if "hardening" in teardown_phases:
          idx = teardown_phases.index("hardening")
          teardown_phases = teardown_phases[idx + 1:]
          logger.info("Resuming teardown from QA_RELEASE lifecycle: skipping phases up to hardening")
  ```
- This slicing mechanism seamlessly picks up execution exclusively at the QA phases (`qa_plan_generate`, `qa_plan_execute`, `qa_remediate`), verifying the epic and the hardening fixes.

## Configuration Tracking (`sprint-status.yaml`)

The hardening story adopts standard story lifecycle tracking within `sprint-status.yaml`:
- The story number is dynamically resolved (e.g., if the highest story in Epic 7 is `7.3`, the hardening story becomes `7.4`).
- It uses the standard `done` status tracking.
- Removing or re-running the hardening lifecycle safely recalculates the `sprint-status.yaml` without generating duplicate teardown tasks.

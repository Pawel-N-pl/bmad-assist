<step n="1" goal="Read Retrospective Report">
  <input>
    <retrospective_report>
      {retrospective_report_content}
    </retrospective_report>
  </input>
  <action>Analyze the retrospective report to identify actionable items and technical debt.</action>
</step>

<step n="2" goal="Triage Hardening Items">
  <instruction>
    You are a Senior Technical Lead. Your task is to triage the findings from the Retrospective Report and decide how to handle the hardening phase for the upcoming Epic {next_epic_id}.
    
    You MUST output a raw JSON object wrapped EXACTLY in these HTML markers:
    <!-- HARDENING_TRIAGE_START -->
    {{
        "decision": "...",
        "reason": "...",
        "fixes_applied": [],
        "story_content": "..."
    }}
    <!-- HARDENING_TRIAGE_END -->

    **Decision Rules:**
    1. `"decision": "no_action"`: Use this if there are no actionable items or technical debt from the retrospective.
    2. `"decision": "direct_fix"`: Use this if the items are trivial (e.g., typos, simple config changes) and you can fix them directly inline. Include descriptions of what you fixed in the `"fixes_applied"` array.
    3. `"decision": "story_needed"`: Use this if complex issues require dedicated work. Provide the full markdown for the new hardening story in the `"story_content"` field.

    **Story Content Requirements (if decision is story_needed):**
    The `"story_content"` must be a valid markdown string (escape internal quotes or newlines as needed for JSON) describing the required work, including an Acceptance Criteria checklist. Set the status of the story to `backlog` (or `ready-for-dev` if immediately actionable).

    **CRITICAL:** 
    - You must NOT output anything outside of the `<!-- HARDENING_TRIAGE_START -->` and `<!-- HARDENING_TRIAGE_END -->` markers.
    - Your output must be valid, parseable JSON. Do not use markdown blocks (```json) inside the markers.
  </instruction>
</step>

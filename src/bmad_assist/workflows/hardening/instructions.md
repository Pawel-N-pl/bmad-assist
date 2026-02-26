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
        "has_direct_fixes": true,
        "story_needed": false,
        "reason": "...",
        "fixes_applied": [],
        "story_content": "..."
    }}
    <!-- HARDENING_TRIAGE_END -->

    **Decision Rules:**
    1. Set `"has_direct_fixes": true` only when you actually fixed trivial items inline (e.g., typos, simple config changes). List each fix in `"fixes_applied"`.
    2. Set `"story_needed": true` only when complex issues still require dedicated implementation planning. In that case, provide the full markdown hardening story in `"story_content"`.
    3. If there are no actionable items, set both booleans to `false`, set `"fixes_applied": []`, and set `"story_content": ""`.
    4. If there are both trivial and complex items, fix the trivial items immediately (listing them in `fixes_applied`) AND provide a markdown story for ONLY the complex items (in `story_content`). Do NOT put trivial items in the `story_content`.

    **Story Content Requirements (if `story_needed` is true):**
    The `"story_content"` must be a valid markdown string (escape internal quotes or newlines as needed for JSON) describing the required work, including an Acceptance Criteria checklist. Set the status of the story to `backlog` (or `ready-for-dev` if immediately actionable).

    **CRITICAL:** 
    - You must NOT output anything outside of the `<!-- HARDENING_TRIAGE_START -->` and `<!-- HARDENING_TRIAGE_END -->` markers.
    - Your output must be valid, parseable JSON. Do not use markdown blocks (```json) inside the markers.
  </instruction>
</step>

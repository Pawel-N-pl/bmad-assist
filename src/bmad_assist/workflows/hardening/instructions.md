<step n="1" goal="Read Retrospective Report">
  <input>
    <retrospective_report>
      {retrospective_report_content}
    </retrospective_report>
  </input>
  <action>Analyze the retrospective report to identify actionable items and technical debt.</action>
</step>

<step n="2" goal="Create Hardening Story">
  <instruction>
    You are a Senior Technical Lead. Your task is to transform the findings from the Retrospective Report into a concrete, actionable "Hardening Story" (Story 0) for the upcoming Epic {next_epic_id}.
    
    This story MUST be prioritized at the top of the backlog (Story 0) and address the most critical issues identified.

    **Requirements:**
    1.  **Title:** `# Story {next_epic_id}.0: Retrospective Hardening`
    2.  **User Story:** As a developer, I want to implement improvements from the retrospective...
    3.  **Acceptance Criteria:** Must include specific, verifiable items derived from the report.
    4.  **Tasks:** Break down the work into checklists.
    5.  **Status:** `backlog` (or `ready-for-dev` if immediately actionable).

    **Output Format:**
    Return ONLY the markdown content for the story file. Do not include conversational text.
  </instruction>
</step>

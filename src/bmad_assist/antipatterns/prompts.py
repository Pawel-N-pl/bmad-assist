"""Extraction prompt template for antipatterns.

This module contains the prompt template used to extract verified issues
from synthesis reports using the helper LLM.
"""

EXTRACTION_PROMPT = '''Extract all VERIFIED issues from this synthesis report.
Return ONLY valid YAML (no markdown, no explanation):

```yaml
story_id: "{story_id}"
date: "{date}"
issues:
  - severity: critical|high|medium
    issue: "brief description"
    file: "path/to/file.py:line"
    fix: "what was done"
```

Rules:
- Extract ONLY from "Issues Verified" section
- Ignore "Issues Dismissed" completely
- If no verified issues found, return: issues: []
- Each issue must have: severity, issue, file (if mentioned), fix
- Use the exact severity from the report (critical, high, medium)
- Keep descriptions brief but informative

SYNTHESIS REPORT:
{synthesis_content}
'''

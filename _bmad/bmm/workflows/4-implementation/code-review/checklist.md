# Senior Developer Review - Validation Checklist

## Story & Context Loading
- [ ] Story file loaded from `{{story_path}}`
- [ ] Story Status verified as reviewable (review)
- [ ] Epic and Story IDs resolved ({{epic_num}}.{{story_num}})
- [ ] Story Context located or warning recorded
- [ ] Epic Tech Spec located or warning recorded
- [ ] Architecture/standards docs loaded (as available)
- [ ] Tech stack detected and documented

## Git Reality Check
- [ ] Git repository detected and analyzed
- [ ] `git status --porcelain` executed for uncommitted changes
- [ ] `git diff --name-only` executed for modified files
- [ ] Story File List compared against git reality
- [ ] Discrepancies documented (files in git but not in story, vice versa)

## Acceptance Criteria Validation
- [ ] All ACs extracted from story
- [ ] Each AC checked against implementation
- [ ] AC implementation status documented (IMPLEMENTED/PARTIAL/MISSING)
- [ ] Missing/partial ACs flagged as HIGH severity

## Task Completion Audit
- [ ] All tasks with [x] status extracted
- [ ] Each [x] task verified against actual code
- [ ] False completion claims flagged as CRITICAL
- [ ] Evidence recorded (file:line references)

## Code Quality Assessment

### SOLID Principles
- [ ] Single Responsibility violations checked
- [ ] Open/Closed principle violations checked
- [ ] Liskov Substitution violations checked
- [ ] Interface Segregation violations checked
- [ ] Dependency Inversion violations checked

### Hidden Bugs Detection
- [ ] Resource leaks identified
- [ ] Race conditions analyzed
- [ ] Edge cases reviewed
- [ ] Off-by-one errors checked
- [ ] Exception handling reviewed
- [ ] Boundary conditions in string matching validated (path prefixes use `+ '/'`, substring checks handle partial matches)

### Abstraction Analysis
- [ ] Over-engineering identified
- [ ] Under-engineering identified
- [ ] Pattern misuse flagged
- [ ] Boundary breaches documented

### Test Quality
- [ ] Lying tests identified (always pass, weak assertions)
- [ ] Missing test coverage noted
- [ ] Mock overuse flagged
- [ ] Edge case coverage assessed

### Performance
- [ ] N+1 queries identified
- [ ] Unnecessary allocations found
- [ ] Missing caching opportunities noted
- [ ] Blocking operations in async contexts flagged
- [ ] Algorithm efficiency reviewed

### Tech Debt
- [ ] Hard-coded values documented
- [ ] Magic strings identified
- [ ] Copy-paste code flagged
- [ ] Deprecated API usage noted
- [ ] Tight coupling identified

### Style & Type Safety
- [ ] PEP 8 compliance checked (Python) / language-specific standards
- [ ] Naming conventions verified
- [ ] Import organization reviewed
- [ ] Type hints coverage assessed
- [ ] Type correctness verified

### Security
- [ ] Credential exposure checked
- [ ] Injection vectors analyzed
- [ ] Authentication issues reviewed
- [ ] Authorization gaps identified
- [ ] Data exposure risks assessed

## Review Finalization
- [ ] Final Score calculated (1-10)
- [ ] Verdict determined (APPROVE/MAJOR REWORK/REJECT)
- [ ] Minimum 3 issues found (adversarial requirement)
- [ ] Suggested fixes provided for critical issues
- [ ] Review notes appended under "Senior Developer Review (AI)"
- [ ] Change Log updated with review entry
- [ ] Status updated according to verdict
- [ ] Sprint status synced (if sprint tracking enabled)
- [ ] Story saved successfully

_Reviewer: {{user_name}} on {{date}}_
_Final Score: {{final_score}}/10_
_Verdict: {{verdict}}_

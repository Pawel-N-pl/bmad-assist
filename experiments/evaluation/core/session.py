"""Session management for evaluation framework.

Session files track individual evaluation runs with auto-filled and manual scores.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .scoring import grade, GRADE_THRESHOLDS


# Criteria codes
AUTO_CRITERIA = ["F1", "F2", "F3", "F4", "Q1", "Q3", "Q4", "C1"]
MANUAL_CRITERIA = ["Q2", "U1", "U2", "U3", "U4", "C2", "C3", "C4"]
ALL_CRITERIA = AUTO_CRITERIA + MANUAL_CRITERIA


# Criterion labels
CRITERION_LABELS = {
    "F1": "Core Features",
    "F2": "Coverage",
    "F3": "Configuration",
    "F4": "Output/Integration",
    "Q1": "Stability",
    "Q2": "Correctness",
    "Q3": "Performance",
    "Q4": "Determinism/Consistency",
    "U1": "API Intuitive",
    "U2": "Error Messages",
    "U3": "Documentation",
    "U4": "IDE Support",
    "C1": "Test Coverage",
    "C2": "Acceptance Criteria",
    "C3": "Feature Gaps",
    "C4": "Integration Ready",
}


class SessionManager:
    """Manages evaluation session files."""

    def __init__(self, project_dir: Path):
        """Initialize session manager.

        Args:
            project_dir: Path to project's evaluation directory
                        (e.g., tests/fixtures/auth-service/evaluation/)
        """
        self.project_dir = Path(project_dir)
        self.sessions_dir = self.project_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def generate_session(
        self,
        results: dict[str, tuple[int, str]],
        project_name: str,
    ) -> Path:
        """Generate a new session file with auto-filled scores.

        Args:
            results: Dict of criterion code -> (score, note)
            project_name: Name of the project being evaluated

        Returns:
            Path to created session file
        """
        today = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%H%M")
        session_file = self.sessions_dir / f"session-{today}-{timestamp}.md"

        # Calculate auto subtotal
        auto_total = sum(results.get(c, (0, ""))[0] for c in AUTO_CRITERIA)

        # Build functionality table
        func_rows = []
        for c in ["F1", "F2", "F3", "F4"]:
            pts, note = results.get(c, (0, "not run"))
            label = CRITERION_LABELS[c]
            func_rows.append(f"| {c} | {label} | {pts}/5 | {note} |")
        func_subtotal = sum(results.get(c, (0, ""))[0] for c in ["F1", "F2", "F3", "F4"])

        # Build quality auto table
        quality_auto_rows = []
        for c in ["Q1", "Q3", "Q4"]:
            pts, note = results.get(c, (0, "not run"))
            label = CRITERION_LABELS[c]
            quality_auto_rows.append(f"| {c} | {label} | {pts}/5 | {note} |")

        # Build completeness auto table
        c1_pts, c1_note = results.get("C1", (0, "not run"))

        content = f"""# Evaluation: {today}

**Project:** {project_name}
**Evaluator:** [Name]
**Duration:** [X] min

---

## Auto Scores (from evaluation framework)

### FUNCTIONALITY

| # | Criterion | Score | Notes |
|---|-----------|-------|-------|
{chr(10).join(func_rows)}
| | **Subtotal** | **{func_subtotal}/20** | |

### QUALITY (auto)

| # | Criterion | Score | Notes |
|---|-----------|-------|-------|
{chr(10).join(quality_auto_rows)}

### COMPLETENESS (auto)

| # | Criterion | Score | Notes |
|---|-----------|-------|-------|
| C1 | {CRITERION_LABELS['C1']} | {c1_pts}/5 | {c1_note} |

**Auto subtotal: {auto_total}/40**

---

## Manual Scores (fill these in)

### QUALITY (manual)

| # | Criterion | Score | Notes |
|---|-----------|-------|-------|
| Q2 | {CRITERION_LABELS['Q2']} | /5 | |

### USABILITY

| # | Criterion | Score | Notes |
|---|-----------|-------|-------|
| U1 | {CRITERION_LABELS['U1']} | /5 | |
| U2 | {CRITERION_LABELS['U2']} | /5 | |
| U3 | {CRITERION_LABELS['U3']} | /5 | |
| U4 | {CRITERION_LABELS['U4']} | /5 | |

### COMPLETENESS (manual)

| # | Criterion | Score | Notes |
|---|-----------|-------|-------|
| C2 | {CRITERION_LABELS['C2']} | /5 | |
| C3 | {CRITERION_LABELS['C3']} | /5 | |
| C4 | {CRITERION_LABELS['C4']} | /5 | |

**Manual subtotal: ___/40**

---

## Issues Found

```
BUG P1 -
MISSING P2 -
UX P2 -
```

---

## Summary

| Source | Score |
|--------|-------|
| Auto | {auto_total}/40 |
| Manual | ___/40 |
| **TOTAL** | **___/80** |

**Grade:** [ ] A (72+) [ ] B (64-71) [ ] C (56-63) [ ] D (48-55) [ ] F (<48)

**Priority Fixes:**
1.
2.
3.
"""
        session_file.write_text(content)
        return session_file

    def find_latest_session(self) -> Path | None:
        """Find the most recent session file."""
        sessions = list(self.sessions_dir.glob("session-*.md"))
        if not sessions:
            return None
        return max(sessions, key=lambda p: p.stat().st_mtime)

    def parse_session(self, session_path: Path) -> dict[str, int]:
        """Parse scores from a session file.

        Args:
            session_path: Path to session file

        Returns:
            Dict of criterion code -> score
        """
        content = session_path.read_text()
        scores = {}

        # Parse all scores from tables: | F1 | ... | 3/5 | ... |
        pattern = r"\|\s*([A-Z]\d)\s*\|[^|]+\|\s*(\d+)/5\s*\|"
        for match in re.finditer(pattern, content):
            code = match.group(1)
            pts = int(match.group(2))
            scores[code] = pts

        return scores

    def calculate_and_update(self, session_path: Path) -> dict[str, Any]:
        """Calculate totals and update session file.

        Args:
            session_path: Path to session file

        Returns:
            Dict with auto_total, manual_total, total, grade, missing
        """
        scores = self.parse_session(session_path)

        auto_total = sum(scores.get(c, 0) for c in AUTO_CRITERIA)
        manual_filled = [c for c in MANUAL_CRITERIA if c in scores]
        manual_missing = [c for c in MANUAL_CRITERIA if c not in scores]
        manual_total = sum(scores.get(c, 0) for c in MANUAL_CRITERIA)
        total = auto_total + manual_total
        letter_grade = grade(total)

        result = {
            "auto_total": auto_total,
            "manual_total": manual_total,
            "total": total,
            "grade": letter_grade,
            "missing": manual_missing,
            "scores": scores,
        }

        # Update file if all manual scores filled
        if not manual_missing:
            content = session_path.read_text()
            content = re.sub(
                r"\| Manual \| ___/40 \|",
                f"| Manual | {manual_total}/40 |",
                content,
            )
            content = re.sub(
                r"\| \*\*TOTAL\*\* \| \*\*___/80\*\* \|",
                f"| **TOTAL** | **{total}/80** |",
                content,
            )
            content = re.sub(
                r"\*\*Manual subtotal: ___/40\*\*",
                f"**Manual subtotal: {manual_total}/40**",
                content,
            )
            # Mark the grade
            content = re.sub(
                rf"\[ \] {letter_grade} ",
                f"[x] {letter_grade} ",
                content,
            )
            session_path.write_text(content)

        return result

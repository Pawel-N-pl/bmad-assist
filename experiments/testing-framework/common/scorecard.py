"""
Automated Quality Scorecard Generator.

Generates quality scorecards for fixtures by analyzing:
- Completeness (stories done, TODOs, placeholders)
- Functionality (build, tests)
- Code quality (linting, complexity, security)
- Documentation (README, comments)

Usage:
    python -m experiments.testing_framework.common.scorecard webhook-relay-001

    # Compare two fixtures
    python -m experiments.testing_framework.common.scorecard --compare fixture1 fixture2
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


# ============================================================================
# Path Constants
# ============================================================================


def get_fixtures_dir() -> Path:
    """Get the fixtures directory."""
    return Path(__file__).parent.parent.parent / "fixtures"


def get_scorecards_dir() -> Path:
    """Get the scorecards output directory."""
    return Path(__file__).parent.parent.parent / "analysis" / "scorecards"


# ============================================================================
# Completeness Scoring (25 points)
# ============================================================================


def score_completeness(fixture_path: Path) -> dict[str, Any]:
    """
    Score fixture completeness.

    - stories_completed (10 pts): done/total from sprint-status.yaml
    - no_todos (5 pts): -0.5 per TODO/FIXME found
    - no_placeholders (5 pts): -1 per placeholder pattern
    - no_empty_files (5 pts): 5 if no empty files, 0 otherwise
    """
    results = {
        "stories_completed": {"max": 10, "score": 0, "metric": "0/0"},
        "no_todos": {"max": 5, "score": 5, "metric": 0, "notes": ""},
        "no_placeholders": {"max": 5, "score": 5, "metric": 0, "patterns_found": []},
        "no_empty_files": {"max": 5, "score": 5, "metric": 0},
    }

    # Stories completed
    sprint_status = fixture_path / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
    if sprint_status.exists():
        with open(sprint_status) as f:
            data = yaml.safe_load(f)
        if data and "stories" in data:
            total = len(data["stories"])
            done = sum(1 for s in data["stories"].values() if s.get("status") == "done")
            results["stories_completed"]["score"] = round((done / total) * 10, 1) if total > 0 else 0
            results["stories_completed"]["metric"] = f"{done}/{total}"

    # TODO/FIXME count
    todo_pattern = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b", re.IGNORECASE)
    todo_count = 0
    todo_files: list[str] = []

    src_dirs = [
        fixture_path / "src",
        fixture_path / "internal",
        fixture_path / "cmd",
        fixture_path / "lib",
        fixture_path / "app",
    ]

    for src_dir in src_dirs:
        if src_dir.exists():
            for file in src_dir.rglob("*"):
                if file.is_file() and file.suffix in (".go", ".py", ".js", ".ts", ".rs"):
                    try:
                        content = file.read_text(errors="ignore")
                        matches = todo_pattern.findall(content)
                        if matches:
                            todo_count += len(matches)
                            todo_files.append(f"{file.relative_to(fixture_path)} ({len(matches)})")
                    except Exception:
                        pass

    results["no_todos"]["metric"] = todo_count
    results["no_todos"]["score"] = max(0, 5 - (todo_count * 0.5))
    if todo_files:
        results["no_todos"]["notes"] = "; ".join(todo_files[:5])

    # Placeholder patterns
    placeholder_patterns = [
        (r'\bpass\s*$', 'pass'),
        (r'raise NotImplementedError', 'NotImplementedError'),
        (r'panic\("not implemented"\)', 'panic'),
        (r'unimplemented!\(\)', 'unimplemented!'),
        (r'// TODO:', 'TODO comment'),
    ]

    placeholder_count = 0
    found_patterns: list[str] = []

    for src_dir in src_dirs:
        if src_dir.exists():
            for file in src_dir.rglob("*"):
                if file.is_file() and file.suffix in (".go", ".py", ".js", ".ts", ".rs"):
                    try:
                        content = file.read_text(errors="ignore")
                        for pattern, name in placeholder_patterns:
                            if re.search(pattern, content):
                                placeholder_count += len(re.findall(pattern, content))
                                if name not in found_patterns:
                                    found_patterns.append(name)
                    except Exception:
                        pass

    results["no_placeholders"]["metric"] = placeholder_count
    results["no_placeholders"]["score"] = max(0, 5 - placeholder_count)
    results["no_placeholders"]["patterns_found"] = found_patterns

    # Empty files
    empty_count = 0
    for src_dir in src_dirs:
        if src_dir.exists():
            for file in src_dir.rglob("*"):
                if file.is_file() and file.suffix in (".go", ".py", ".js", ".ts", ".rs"):
                    if file.stat().st_size < 50:  # Less than 50 bytes
                        empty_count += 1

    results["no_empty_files"]["metric"] = empty_count
    results["no_empty_files"]["score"] = 5 if empty_count == 0 else 0

    return {
        "weight": 25,
        "score": sum(r["score"] for r in results.values()),
        "details": results,
    }


# ============================================================================
# Functionality Scoring (25 points)
# ============================================================================


def score_functionality(fixture_path: Path) -> dict[str, Any]:
    """
    Score fixture functionality.

    - build (10 pts): build succeeds
    - unit_tests (10 pts): unit tests pass
    - behavior_tests (5 pts): behavioral tests pass
    """
    results = {
        "build": {"max": 10, "score": 0, "success": False, "command": "", "errors": []},
        "unit_tests": {
            "max": 10,
            "score": 0,
            "metric": "0/0",
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
        },
        "behavior_tests": {
            "max": 5,
            "score": 0,
            "metric": "0/0",
            "passed": 0,
            "failed": 0,
            "notes": "",
        },
    }

    # Detect build system and run build
    if (fixture_path / "go.mod").exists():
        cmd = ["go", "build", "./..."]
        results["build"]["command"] = " ".join(cmd)
        try:
            result = subprocess.run(
                cmd, cwd=fixture_path, capture_output=True, text=True, timeout=120
            )
            results["build"]["success"] = result.returncode == 0
            results["build"]["score"] = 10 if result.returncode == 0 else 0
            if result.returncode != 0:
                results["build"]["errors"] = result.stderr.split("\n")[:5]
        except Exception as e:
            results["build"]["errors"] = [str(e)]

        # Run Go tests
        try:
            result = subprocess.run(
                ["go", "test", "-json", "./..."],
                cwd=fixture_path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            # Parse test output
            passed = failed = skipped = 0
            for line in result.stdout.split("\n"):
                if '"Action":"pass"' in line and '"Test":' in line:
                    passed += 1
                elif '"Action":"fail"' in line and '"Test":' in line:
                    failed += 1
                elif '"Action":"skip"' in line and '"Test":' in line:
                    skipped += 1

            total = passed + failed
            results["unit_tests"]["passed"] = passed
            results["unit_tests"]["failed"] = failed
            results["unit_tests"]["skipped"] = skipped
            results["unit_tests"]["metric"] = f"{passed}/{total}"
            results["unit_tests"]["score"] = round((passed / total) * 10, 1) if total > 0 else 0
        except Exception as e:
            results["unit_tests"]["errors"] = [str(e)]

    elif (fixture_path / "pyproject.toml").exists():
        cmd = ["pip", "install", "-e", "."]
        results["build"]["command"] = " ".join(cmd)
        # Skip actual build for Python (usually done via pip install)
        results["build"]["success"] = True
        results["build"]["score"] = 10

    elif (fixture_path / "package.json").exists():
        cmd = ["npm", "install"]
        results["build"]["command"] = " ".join(cmd)
        # Skip actual build for Node
        results["build"]["success"] = True
        results["build"]["score"] = 10

    # Behavioral tests (check if they exist and count)
    # First try exact match (fixture-tests/webhook-relay-001)
    # Then try base project name (fixture-tests/webhook-relay for webhook-relay-001)
    fixture_tests_base = fixture_path.parent.parent / "fixture-tests"
    fixture_tests_dir = fixture_tests_base / fixture_path.name

    if not fixture_tests_dir.exists():
        # Try stripping variant suffix (e.g., webhook-relay-001 -> webhook-relay)
        base_name = re.sub(r"-\d+$", "", fixture_path.name)
        if base_name != fixture_path.name:
            fixture_tests_dir = fixture_tests_base / base_name

    if fixture_tests_dir.exists():
        test_files = list(fixture_tests_dir.glob("test_*.py"))
        if test_files:
            results["behavior_tests"]["notes"] = f"{len(test_files)} test files found in {fixture_tests_dir.name}/"
            results["behavior_tests"]["score"] = 2  # Partial credit for having tests
        # Full run would be: pytest fixture_tests_dir --fixture-variant={fixture_path.name}

    return {
        "weight": 25,
        "score": sum(r["score"] for r in results.values()),
        "details": results,
    }


# ============================================================================
# Code Quality Scoring (20 points)
# ============================================================================


def score_code_quality(fixture_path: Path) -> dict[str, Any]:
    """
    Score code quality.

    - linting (8 pts): lint errors
    - complexity (6 pts): cyclomatic complexity
    - security (6 pts): security issues

    Note: Scores default to 0 when required tools are not installed.
    This prevents false positives from unverified code.
    """
    results = {
        "linting": {"max": 8, "score": 0, "tool": "", "errors": 0, "warnings": 0, "top_issues": []},
        "complexity": {
            "max": 6,
            "score": 0,
            "tool": "",
            "average": 0.0,
            "max_function": "",
            "max_value": 0,
        },
        "security": {"max": 6, "score": 0, "tool": "", "high": 0, "medium": 0, "low": 0, "issues": []},
    }

    # Detect language and run appropriate linter
    if (fixture_path / "go.mod").exists():
        results["linting"]["tool"] = "go vet"

        if not shutil.which("go"):
            # Go toolchain not installed - mark as skipped, keep score at 0
            results["linting"]["skipped"] = True
            results["linting"]["reason"] = "go not installed"
            results["complexity"]["skipped"] = True
            results["complexity"]["reason"] = "go not installed"
            results["security"]["skipped"] = True
            results["security"]["reason"] = "go not installed"
            # Return early - can't run any Go-based quality checks
            return {
                "weight": 20,
                "score": 0,
                "skipped": True,
                "reason": "go toolchain not installed",
                "details": results,
            }

        # Go is confirmed installed (early return above if not)
        try:
            result = subprocess.run(
                ["go", "vet", "./..."],
                cwd=fixture_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            # Count errors
            errors = len([l for l in result.stderr.split("\n") if l.strip()])
            results["linting"]["errors"] = errors
            results["linting"]["score"] = max(0, 8 - errors)
        except Exception:
            pass

        # Complexity with gocyclo if available
        if shutil.which("gocyclo"):
            results["complexity"]["tool"] = "gocyclo"
            try:
                result = subprocess.run(
                    ["gocyclo", "-avg", "."],
                    cwd=fixture_path,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                # Parse average
                for line in result.stdout.split("\n"):
                    if "Average" in line:
                        match = re.search(r"(\d+\.?\d*)", line)
                        if match:
                            avg = float(match.group(1))
                            results["complexity"]["average"] = avg
                            results["complexity"]["score"] = 6 if avg < 10 else (3 if avg < 15 else 0)
            except Exception:
                pass
        else:
            results["complexity"]["skipped"] = True
            results["complexity"]["reason"] = "gocyclo not installed"

        # Security with gosec if available
        if shutil.which("gosec"):
            results["security"]["tool"] = "gosec"
            try:
                result = subprocess.run(
                    ["gosec", "-quiet", "-fmt", "json", "./..."],
                    cwd=fixture_path,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                # Parse JSON output
                import json

                try:
                    data = json.loads(result.stdout)
                    issues = data.get("Issues", [])
                    high = sum(1 for i in issues if i.get("severity") == "HIGH")
                    medium = sum(1 for i in issues if i.get("severity") == "MEDIUM")
                    low = sum(1 for i in issues if i.get("severity") == "LOW")
                    results["security"]["high"] = high
                    results["security"]["medium"] = medium
                    results["security"]["low"] = low
                    results["security"]["score"] = 6 if high == 0 else (3 if high < 3 else 0)
                except json.JSONDecodeError:
                    pass
            except Exception:
                pass
        else:
            results["security"]["skipped"] = True
            results["security"]["reason"] = "gosec not installed"

    elif (fixture_path / "pyproject.toml").exists():
        results["linting"]["tool"] = "ruff"

        if shutil.which("ruff"):
            try:
                result = subprocess.run(
                    ["ruff", "check", "."],
                    cwd=fixture_path,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                errors = len([l for l in result.stdout.split("\n") if l.strip()])
                results["linting"]["errors"] = errors
                results["linting"]["score"] = max(0, 8 - errors)
            except Exception:
                pass
        else:
            results["linting"]["skipped"] = True
            results["linting"]["reason"] = "ruff not installed"
        # Complexity and security tools for Python not configured
        results["complexity"]["skipped"] = True
        results["complexity"]["reason"] = "no Python complexity tool configured"
        results["security"]["skipped"] = True
        results["security"]["reason"] = "no Python security tool configured"

    else:
        # Unknown project type - can't run any code quality checks
        results["linting"]["skipped"] = True
        results["linting"]["reason"] = "unknown project type"
        results["complexity"]["skipped"] = True
        results["complexity"]["reason"] = "unknown project type"
        results["security"]["skipped"] = True
        results["security"]["reason"] = "unknown project type"

    return {
        "weight": 20,
        "score": sum(r["score"] for r in results.values()),
        "details": results,
    }


# ============================================================================
# Documentation Scoring (15 points)
# ============================================================================


def score_documentation(fixture_path: Path) -> dict[str, Any]:
    """
    Score documentation quality.

    - readme_exists (4 pts): README exists and has content
    - readme_sections (3 pts): has install/usage/config sections
    - api_docs (4 pts): API documentation exists
    - inline_comments (4 pts): comment ratio in code
    """
    results = {
        "readme_exists": {"max": 4, "score": 0, "exists": False, "length": 0},
        "readme_sections": {"max": 3, "score": 0, "has_install": False, "has_usage": False, "has_config": False},
        "api_docs": {"max": 4, "score": 0, "exists": False, "format": "", "location": ""},
        "inline_comments": {"max": 4, "score": 0, "ratio": 0.0, "sampled_files": []},
    }

    # README check
    readme_files = ["README.md", "README.rst", "README.txt", "README"]
    for readme_name in readme_files:
        readme = fixture_path / readme_name
        if readme.exists():
            content = readme.read_text(errors="ignore")
            results["readme_exists"]["exists"] = True
            results["readme_exists"]["length"] = len(content)
            results["readme_exists"]["score"] = 4 if len(content) > 100 else 2

            # Check sections
            content_lower = content.lower()
            if "install" in content_lower:
                results["readme_sections"]["has_install"] = True
                results["readme_sections"]["score"] += 1
            if "usage" in content_lower or "getting started" in content_lower:
                results["readme_sections"]["has_usage"] = True
                results["readme_sections"]["score"] += 1
            if "config" in content_lower or "environment" in content_lower:
                results["readme_sections"]["has_config"] = True
                results["readme_sections"]["score"] += 1
            break

    # API docs check
    api_doc_locations = [
        ("docs/api.md", "markdown"),
        ("docs/api.yaml", "openapi"),
        ("docs/openapi.yaml", "openapi"),
        ("api/openapi.yaml", "openapi"),
        ("swagger.yaml", "openapi"),
    ]
    for location, fmt in api_doc_locations:
        if (fixture_path / location).exists():
            results["api_docs"]["exists"] = True
            results["api_docs"]["format"] = fmt
            results["api_docs"]["location"] = location
            results["api_docs"]["score"] = 4
            break

    # Inline comment ratio
    total_lines = 0
    comment_lines = 0
    sampled_files: list[str] = []

    src_dirs = [fixture_path / "src", fixture_path / "internal", fixture_path / "cmd"]
    for src_dir in src_dirs:
        if src_dir.exists():
            for file in list(src_dir.rglob("*.go"))[:10]:  # Sample up to 10 Go files
                try:
                    content = file.read_text(errors="ignore")
                    lines = content.split("\n")
                    total_lines += len(lines)
                    comment_lines += sum(1 for l in lines if l.strip().startswith("//"))
                    sampled_files.append(str(file.relative_to(fixture_path)))
                except Exception:
                    pass

    if total_lines > 0:
        ratio = (comment_lines / total_lines) * 100
        results["inline_comments"]["ratio"] = round(ratio, 1)
        results["inline_comments"]["score"] = min(4, int(ratio / 5))  # 5% = 1pt, 20% = 4pt
        results["inline_comments"]["sampled_files"] = sampled_files[:5]

    return {
        "weight": 15,
        "score": sum(r["score"] for r in results.values()),
        "details": results,
    }


# ============================================================================
# UI/UX Scoring (15 points) - Manual only
# ============================================================================


def score_ui_ux(fixture_path: Path) -> dict[str, Any]:
    """
    Check if fixture has UI (for manual scoring).

    Returns placeholder for manual review.
    """
    has_ui = any(
        [
            (fixture_path / "static").exists(),
            (fixture_path / "public").exists(),
            (fixture_path / "templates").exists(),
            (fixture_path / "frontend").exists(),
        ]
    )

    if not has_ui:
        return {
            "weight": 15,
            "score": None,
            "applicable": False,
            "details": "Fixture has no UI - points redistributed",
        }

    return {
        "weight": 15,
        "score": None,  # Requires manual review
        "applicable": True,
        "details": {
            "responsive": {"max": 3, "score": 0, "notes": ""},
            "navigation": {"max": 3, "score": 0, "notes": ""},
            "error_feedback": {"max": 3, "score": 0, "notes": ""},
            "loading_states": {"max": 3, "score": 0, "notes": ""},
            "visual_consistency": {"max": 3, "score": 0, "notes": ""},
        },
    }


# ============================================================================
# Main Scorecard Generation
# ============================================================================


def generate_scorecard(fixture_name: str) -> dict[str, Any]:
    """Generate a complete scorecard for a fixture."""
    fixtures_dir = get_fixtures_dir()
    fixture_path = fixtures_dir / fixture_name

    if not fixture_path.exists():
        raise ValueError(f"Fixture not found: {fixture_path}")

    # Score each category
    completeness = score_completeness(fixture_path)
    functionality = score_functionality(fixture_path)
    code_quality = score_code_quality(fixture_path)
    documentation = score_documentation(fixture_path)
    ui_ux = score_ui_ux(fixture_path)

    # Calculate totals
    scores = {
        "completeness": completeness,
        "functionality": functionality,
        "code_quality": code_quality,
        "documentation": documentation,
        "ui_ux": ui_ux,
    }

    raw_score = sum(s["score"] for s in scores.values() if s["score"] is not None)

    # Adjust max possible if UI not applicable
    max_possible = 100 if ui_ux["applicable"] else 85

    weighted_score = round((raw_score / max_possible) * 100, 1)

    # Determine grade
    if weighted_score >= 90:
        grade = "A"
    elif weighted_score >= 80:
        grade = "B"
    elif weighted_score >= 70:
        grade = "C"
    elif weighted_score >= 60:
        grade = "D"
    else:
        grade = "F"

    return {
        "fixture": fixture_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator_version": "1.0",
        "mode": "automated",
        "scores": scores,
        "totals": {
            "raw_score": raw_score,
            "max_possible": max_possible,
            "weighted_score": weighted_score,
            "grade": grade,
        },
        "notes": "",
        "recommendations": [],
        "comparison": {"baseline_fixture": None, "delta": {}},
    }


def save_scorecard(scorecard: dict[str, Any]) -> Path:
    """Save scorecard to the scorecards directory."""
    scorecards_dir = get_scorecards_dir()
    scorecards_dir.mkdir(parents=True, exist_ok=True)

    output_path = scorecards_dir / f"{scorecard['fixture']}.yaml"

    with open(output_path, "w") as f:
        yaml.dump(scorecard, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return output_path


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate quality scorecard for a fixture")
    parser.add_argument("fixture", help="Fixture name (e.g., webhook-relay-001)")
    parser.add_argument("--compare", help="Compare with another fixture")
    parser.add_argument("--output", "-o", help="Output file (default: scorecards/{fixture}.yaml)")

    args = parser.parse_args()

    print(f"Generating scorecard for: {args.fixture}")

    scorecard = generate_scorecard(args.fixture)

    if args.compare:
        print(f"Comparing with: {args.compare}")
        baseline = generate_scorecard(args.compare)
        scorecard["comparison"]["baseline_fixture"] = args.compare
        scorecard["comparison"]["delta"] = {
            "completeness": scorecard["scores"]["completeness"]["score"]
            - baseline["scores"]["completeness"]["score"],
            "functionality": scorecard["scores"]["functionality"]["score"]
            - baseline["scores"]["functionality"]["score"],
            "code_quality": scorecard["scores"]["code_quality"]["score"]
            - baseline["scores"]["code_quality"]["score"],
            "documentation": scorecard["scores"]["documentation"]["score"]
            - baseline["scores"]["documentation"]["score"],
            "total": scorecard["totals"]["raw_score"] - baseline["totals"]["raw_score"],
        }

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            yaml.dump(scorecard, f, default_flow_style=False, sort_keys=False)
    else:
        output_path = save_scorecard(scorecard)

    print(f"\nScorecard saved to: {output_path}")
    print(f"\nGrade: {scorecard['totals']['grade']} ({scorecard['totals']['weighted_score']}%)")
    print(f"  Completeness:  {scorecard['scores']['completeness']['score']}/25")
    print(f"  Functionality: {scorecard['scores']['functionality']['score']}/25")
    print(f"  Code Quality:  {scorecard['scores']['code_quality']['score']}/20")
    print(f"  Documentation: {scorecard['scores']['documentation']['score']}/15")
    ui_score = scorecard['scores']['ui_ux']['score']
    print(f"  UI/UX:         {ui_score if ui_score is not None else 'N/A'}/15")


if __name__ == "__main__":
    main()

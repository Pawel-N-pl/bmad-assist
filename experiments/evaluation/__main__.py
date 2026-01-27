#!/usr/bin/env python3
"""CLI entry point for evaluation framework.

Usage:
    # Run evaluation for a project
    python -m tests.fixtures._evaluation run auth-service

    # Calculate totals from a session file
    python -m tests.fixtures._evaluation calc auth-service
    python -m tests.fixtures._evaluation calc auth-service session-2025-12-27-1430.md

    # List available projects
    python -m tests.fixtures._evaluation list
"""

import importlib
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent


def discover_projects() -> dict[str, Path]:
    """Find all fixture projects with evaluators."""
    projects = {}

    for project_dir in FIXTURES_DIR.iterdir():
        if project_dir.name.startswith("_"):
            continue
        if not project_dir.is_dir():
            continue

        # Check for evaluation module
        eval_dir = project_dir / "evaluation"
        if eval_dir.exists() and (eval_dir / "evaluator.py").exists():
            projects[project_dir.name] = project_dir

    return projects


def load_evaluator(project_name: str):
    """Dynamically load evaluator for a project."""
    # Import the evaluator module
    module_name = f"tests.fixtures.{project_name}.evaluation.evaluator"

    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        print(f"Failed to import evaluator for {project_name}: {e}")
        sys.exit(1)

    # Find the evaluator class (ends with "Evaluator")
    for name in dir(module):
        if name.endswith("Evaluator") and name != "BaseEvaluator":
            return getattr(module, name)

    print(f"No evaluator class found in {module_name}")
    sys.exit(1)


def cmd_list():
    """List available projects."""
    projects = discover_projects()

    print("Available fixture projects with evaluators:")
    print()

    if not projects:
        print("  (none found)")
        print()
        print("To add an evaluator for a project:")
        print("  1. Create <project>/evaluation/evaluator.py")
        print("  2. Define a class inheriting from BaseEvaluator")
        return

    for name, path in sorted(projects.items()):
        # Check if it has source code
        has_src = (path / "src").exists()
        status = "ready" if has_src else "docs only"
        print(f"  {name:20s} [{status}]")


def cmd_run(project_name: str):
    """Run evaluation for a project."""
    projects = discover_projects()

    if project_name not in projects:
        print(f"Unknown project: {project_name}")
        print()
        print("Available projects:")
        for name in sorted(projects.keys()):
            print(f"  {name}")
        sys.exit(1)

    project_dir = projects[project_name]
    evaluator_class = load_evaluator(project_name)

    print(f"Evaluating: {project_name}")
    print("=" * 50)

    # Check if source exists
    src_dir = project_dir / "src"
    if not src_dir.exists():
        print("\n⚠️  No src/ directory found!")
        print("This fixture has BMAD docs but no generated code yet.")
        print("\nTo use this evaluator:")
        print("  1. Run an LLM to generate code from the BMAD docs")
        print("  2. Run this evaluator to score the result")
        return

    # Run evaluation
    evaluator = evaluator_class(project_dir)

    print("\nRunning auto tests...")
    try:
        results = evaluator.run_all()
    except Exception as e:
        print(f"\n❌ Evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Print results
    print()
    auto_total = 0
    for code, (pts, note) in sorted(results.items()):
        print(f"  {code}: {pts}/5 - {note}")
        auto_total += pts

    print()
    print(f"Auto total: {auto_total}/40")

    # Generate session file
    from .core.session import SessionManager

    eval_dir = project_dir / "evaluation"
    session_mgr = SessionManager(eval_dir)
    session_file = session_mgr.generate_session(results, project_name)

    print()
    print(f"Created: {session_file.relative_to(project_dir)}")
    print()
    print("Next steps:")
    print(f"  1. Open {session_file.name}")
    print("  2. Fill in manual scores (Q2, U1-U4, C2-C4)")
    print(f"  3. Run: python -m tests.fixtures._evaluation calc {project_name}")


def cmd_calc(project_name: str, session_name: str | None = None):
    """Calculate totals from a session file."""
    projects = discover_projects()

    if project_name not in projects:
        print(f"Unknown project: {project_name}")
        sys.exit(1)

    project_dir = projects[project_name]

    from .core.session import SessionManager

    eval_dir = project_dir / "evaluation"
    session_mgr = SessionManager(eval_dir)

    # Find session file
    if session_name:
        session_path = session_mgr.sessions_dir / session_name
        if not session_path.exists():
            session_path = Path(session_name)
    else:
        session_path = session_mgr.find_latest_session()

    if not session_path or not session_path.exists():
        print("No session file found.")
        print(f"Run evaluation first: python -m tests.fixtures._evaluation run {project_name}")
        sys.exit(1)

    # Calculate and display
    result = session_mgr.calculate_and_update(session_path)

    print(f"Session: {session_path.name}")
    print("=" * 40)
    print()

    from .core.session import AUTO_CRITERIA, MANUAL_CRITERIA

    print("Auto scores:")
    for c in AUTO_CRITERIA:
        pts = result["scores"].get(c, "?")
        print(f"  {c}: {pts}/5")
    print(f"  Subtotal: {result['auto_total']}/40")
    print()

    print("Manual scores:")
    for c in MANUAL_CRITERIA:
        if c in result["scores"]:
            print(f"  {c}: {result['scores'][c]}/5")
        else:
            print(f"  {c}: ___/5  <- FILL THIS IN")
    print(f"  Subtotal: {result['manual_total']}/40")

    if result["missing"]:
        print()
        print(f"⚠️  Missing: {', '.join(result['missing'])}")

    print()
    print("=" * 40)
    print(f"TOTAL: {result['total']}/80")
    print(f"GRADE: {result['grade']}")
    print("=" * 40)

    if not result["missing"]:
        print()
        print(f"✓ Updated {session_path.name} with totals")


def main():
    """Main CLI entry point."""
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        sys.exit(0)

    command = args[0]

    if command == "list":
        cmd_list()
    elif command == "run":
        if len(args) < 2:
            print("Usage: python -m tests.fixtures._evaluation run <project>")
            sys.exit(1)
        cmd_run(args[1])
    elif command in ("calc", "calculate"):
        if len(args) < 2:
            print("Usage: python -m tests.fixtures._evaluation calc <project> [session-file]")
            sys.exit(1)
        session_name = args[2] if len(args) > 2 else None
        cmd_calc(args[1], session_name)
    else:
        print(f"Unknown command: {command}")
        print("Available commands: list, run, calc")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Base evaluator abstract class.

All project evaluators inherit from BaseEvaluator and implement
the required test methods for their specific stack.
"""

import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..core.scoring import ratio_score, time_score


class BaseEvaluator(ABC):
    """Abstract base class for project evaluators.

    Subclasses must implement:
        - test_f1_core_features()
        - test_f2_coverage()
        - test_f3_config()
        - test_f4_output()

    Optional overrides:
        - test_q1_stability() - default derives from F1+F2
        - test_q3_performance() - default runs performance benchmark
        - test_q4_consistency() - default checks determinism
        - test_c1_tests() - default runs project test suite

    Configuration:
        - project_root: Path to project root
        - test_command: Command to run project tests
        - performance_benchmark: Callable for Q3 test
    """

    # Class attributes (override in subclass)
    stack_name: str = "unknown"
    test_command: list[str] = ["pytest", "-q", "--tb=no"]
    test_timeout: int = 120
    performance_iterations: int = 1

    def __init__(self, project_root: Path):
        """Initialize evaluator.

        Args:
            project_root: Path to the project being evaluated
        """
        self.project_root = Path(project_root)
        self.src_dir = self.project_root / "src"
        self._setup_done = False
        self._setup_success = False  # Track if setup actually worked
        self._teardown_done = False

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def setup(self) -> None:
        """Setup before running tests (e.g., start server).

        Override in subclass if needed.
        Sets _setup_success = True if setup completes successfully.
        """
        self._setup_done = True
        self._setup_success = True  # Base assumes success; subclasses override

    def teardown(self) -> None:
        """Cleanup after running tests (e.g., stop server).

        Override in subclass if needed.
        """
        self._teardown_done = True

    # =========================================================================
    # REQUIRED: FUNCTIONALITY TESTS (F1-F4)
    # =========================================================================

    @abstractmethod
    def test_f1_core_features(self) -> tuple[int, str]:
        """F1: Test that core features work.

        Returns:
            Tuple of (score 0-5, note string)
        """
        ...

    @abstractmethod
    def test_f2_coverage(self) -> tuple[int, str]:
        """F2: Test feature/component/endpoint coverage.

        Returns:
            Tuple of (score 0-5, note string)
        """
        ...

    @abstractmethod
    def test_f3_config(self) -> tuple[int, str]:
        """F3: Test configuration/customization options.

        Returns:
            Tuple of (score 0-5, note string)
        """
        ...

    @abstractmethod
    def test_f4_output(self) -> tuple[int, str]:
        """F4: Test output formats / integration points.

        Returns:
            Tuple of (score 0-5, note string)
        """
        ...

    # =========================================================================
    # OPTIONAL: QUALITY TESTS (Q1, Q3, Q4)
    # =========================================================================

    def test_q1_stability(self) -> tuple[int, str]:
        """Q1: Stability - derived from crash count in F1+F2.

        Default implementation counts issues from F1 and F2.
        Override if you have a better stability metric.
        """
        f1_score, _ = self.test_f1_core_features()
        f2_score, _ = self.test_f2_coverage()

        # Each point lost = potential crash/issue
        issues = (5 - f1_score) + (5 - f2_score)

        # Score: 0 issues = 5, 1-2 = 4, 3-4 = 3, 5-6 = 2, 7+ = 1
        thresholds = [(0, 5), (2, 4), (4, 3), (6, 2), (8, 1)]
        for max_issues, score in thresholds:
            if issues <= max_issues:
                return score, f"{issues} issues"
        return 0, f"{issues} issues"

    def test_q3_performance(self) -> tuple[int, str]:
        """Q3: Performance benchmark.

        Default runs _performance_benchmark() and scores based on time.
        Override _performance_benchmark() in subclass.
        """
        if not self._setup_success:
            return 0, "setup failed"

        try:
            start = time.perf_counter()
            for _ in range(self.performance_iterations):
                self._performance_benchmark()
            elapsed = time.perf_counter() - start

            # Guard against trivially fast benchmarks (likely no-ops)
            if elapsed < 0.001 and not self._has_meaningful_benchmark():
                return 0, "no benchmark (setup incomplete)"

            return time_score(elapsed)
        except Exception as e:
            return 0, f"error: {e}"

    def _performance_benchmark(self) -> None:
        """Run performance benchmark. Override in subclass."""
        pass

    def _has_meaningful_benchmark(self) -> bool:
        """Check if we have a real benchmark to run.

        Override in subclass to return True when benchmark is valid.
        Default returns False to catch trivial/no-op benchmarks.
        """
        return False

    def test_q4_consistency(self) -> tuple[int, str]:
        """Q4: Consistency/Determinism check.

        Default implementation runs _consistency_check().
        Override if you have specific determinism requirements.
        """
        if not self._setup_success:
            return 0, "setup failed"

        try:
            is_consistent, note = self._consistency_check()
            return (5 if is_consistent else 2, note)
        except Exception as e:
            return 0, f"error: {e}"

    def _consistency_check(self) -> tuple[bool, str]:
        """Check consistency. Override in subclass.

        Returns:
            Tuple of (is_consistent, note)
        """
        return True, "no check implemented"

    # =========================================================================
    # OPTIONAL: COMPLETENESS TEST (C1)
    # =========================================================================

    def test_c1_tests(self) -> tuple[int, str]:
        """C1: Run project's test suite and score pass rate.

        Uses self.test_command to run tests.
        """
        test_dir = self.project_root / "tests"
        if not test_dir.exists():
            return 0, "no tests/ dir"

        try:
            result = subprocess.run(
                self.test_command,
                capture_output=True,
                text=True,
                timeout=self.test_timeout,
                cwd=self.project_root,
            )
            output = result.stdout + result.stderr

            # Parse pytest-style output
            import re
            passed = 0
            failed = 0

            match = re.search(r"(\d+) passed", output)
            if match:
                passed = int(match.group(1))

            match = re.search(r"(\d+) failed", output)
            if match:
                failed = int(match.group(1))

            total = passed + failed
            if total == 0:
                # Try to find any test count
                match = re.search(r"(\d+) tests?", output)
                if match:
                    return 3, f"found {match.group(1)} tests (parse issue)"
                return 0, "no tests found"

            return ratio_score(passed, total)

        except subprocess.TimeoutExpired:
            return 0, f"timeout ({self.test_timeout}s)"
        except FileNotFoundError:
            return 0, f"command not found: {self.test_command[0]}"
        except Exception as e:
            return 0, f"error: {e}"

    # =========================================================================
    # RUNNER
    # =========================================================================

    def run_all(self) -> dict[str, tuple[int, str]]:
        """Run all auto tests and return results.

        Returns:
            Dict of criterion code -> (score, note)
        """
        tests = [
            ("F1", self.test_f1_core_features),
            ("F2", self.test_f2_coverage),
            ("F3", self.test_f3_config),
            ("F4", self.test_f4_output),
            ("Q1", self.test_q1_stability),
            ("Q3", self.test_q3_performance),
            ("Q4", self.test_q4_consistency),
            ("C1", self.test_c1_tests),
        ]

        results: dict[str, tuple[int, str]] = {}

        try:
            self.setup()
        except Exception as e:
            # All tests fail if setup fails
            for code, _ in tests:
                results[code] = (0, f"setup failed: {e}")
            return results

        try:
            for code, test_fn in tests:
                try:
                    results[code] = test_fn()
                except Exception as e:
                    results[code] = (0, f"CRASH: {e}")
        finally:
            try:
                self.teardown()
            except Exception:
                pass  # Don't fail on teardown errors

        return results

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def _run_command(
        self,
        command: list[str],
        timeout: int = 30,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a shell command.

        Args:
            command: Command and arguments
            timeout: Timeout in seconds
            cwd: Working directory (default: project_root)

        Returns:
            CompletedProcess result
        """
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or self.project_root,
        )

    def _file_exists(self, relative_path: str) -> bool:
        """Check if a file exists relative to project root."""
        return (self.project_root / relative_path).exists()

    def _files_exist(self, paths: list[str]) -> tuple[int, int]:
        """Check which files exist.

        Returns:
            Tuple of (existing_count, total_count)
        """
        existing = sum(1 for p in paths if self._file_exists(p))
        return existing, len(paths)

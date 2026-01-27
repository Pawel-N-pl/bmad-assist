"""Python library adapter for pure Python library projects.

For projects that are importable Python packages without a server:
- test-data-gen
- Other utility libraries

Tests by importing the library and calling its public API.
"""

import importlib
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .base import BaseEvaluator
from ..core.scoring import ratio_score, time_score


class PythonLibraryAdapter(BaseEvaluator):
    """Base adapter for Python library projects.

    Subclasses should set:
        - package_name: Name of the package to import
        - src_path: Path to src/ directory (for PYTHONPATH)

    Example:
        class MyLibEvaluator(PythonLibraryAdapter):
            package_name = "mylib"
    """

    stack_name = "python-library"

    # Package configuration (override in subclass)
    package_name: str = ""

    def __init__(self, project_root: Path):
        super().__init__(project_root)
        self._module: Any = None
        self._import_error: str | None = None

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def setup(self) -> None:
        """Add src/ to PYTHONPATH and import the package."""
        super().setup()
        self._setup_success = False  # Reset until import succeeds

        # Add src/ to path
        src_path = self.project_root / "src"
        if src_path.exists() and str(src_path) not in sys.path:
            sys.path.insert(0, str(src_path))

        # Try to import the package
        if self.package_name:
            try:
                self._module = importlib.import_module(self.package_name)
                self._import_error = None
                self._setup_success = True  # Import succeeded
            except ImportError as e:
                self._import_error = str(e)
                self._module = None

    def teardown(self) -> None:
        """Cleanup."""
        # Remove src/ from path if we added it
        src_path = str(self.project_root / "src")
        if src_path in sys.path:
            sys.path.remove(src_path)

        # Clear cached module
        if self.package_name and self.package_name in sys.modules:
            # Don't remove - might break other things
            pass

        super().teardown()

    def _has_meaningful_benchmark(self) -> bool:
        """Check if library is imported for meaningful benchmark."""
        return self._setup_success and self._module is not None

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def _import_from(self, *names: str) -> tuple[bool, Any]:
        """Import names from the package.

        Args:
            names: Names to import (e.g., "Schema", "Field", "generate")

        Returns:
            Tuple of (success, imported_items or error_message)
            If success, imported_items is a tuple of the imported objects
        """
        if self._import_error:
            return False, self._import_error

        if not self._module:
            return False, "package not imported"

        items = []
        for name in names:
            try:
                item = getattr(self._module, name)
                items.append(item)
            except AttributeError:
                return False, f"'{name}' not found in {self.package_name}"

        return True, tuple(items) if len(items) > 1 else items[0]

    def _try_import(self, *names: str) -> Any | None:
        """Try to import names, return None on failure."""
        success, result = self._import_from(*names)
        return result if success else None

    def _safe_call(
        self,
        func: Callable,
        *args,
        **kwargs,
    ) -> tuple[bool, Any]:
        """Safely call a function, catching exceptions.

        Returns:
            Tuple of (success, result or error_message)
        """
        try:
            result = func(*args, **kwargs)
            return True, result
        except Exception as e:
            return False, str(e)

    def _test_import_and_call(
        self,
        import_names: list[str],
        test_code: Callable[[tuple], tuple[bool, str]],
    ) -> tuple[int, str]:
        """Common pattern: import names, run test code, return score.

        Args:
            import_names: Names to import from package
            test_code: Function that takes imported items and returns (success, note)

        Returns:
            Tuple of (score 0-5, note)
        """
        success, result = self._import_from(*import_names)
        if not success:
            return 0, f"import failed: {result}"

        items = result if isinstance(result, tuple) else (result,)

        try:
            passed, note = test_code(items)
            return 5 if passed else 2, note
        except Exception as e:
            return 0, f"error: {e}"

    # =========================================================================
    # DEFAULT IMPLEMENTATIONS
    # =========================================================================

    def test_q1_stability(self) -> tuple[int, str]:
        """Q1: Stability - check for import errors and crashes."""
        if self._import_error:
            return 0, f"import failed: {self._import_error}"

        # Run F1 and F2 to check for crashes
        f1_score, f1_note = self.test_f1_core_features()
        f2_score, f2_note = self.test_f2_coverage()

        issues = (5 - f1_score) + (5 - f2_score)

        if issues == 0:
            return 5, "stable"
        elif issues <= 2:
            return 4, f"{issues} minor issues"
        elif issues <= 4:
            return 3, f"{issues} issues"
        elif issues <= 6:
            return 2, f"{issues} issues"
        else:
            return 1, f"{issues} issues"

    def test_q3_performance(self) -> tuple[int, str]:
        """Q3: Performance - must be overridden with specific benchmark."""
        if self._import_error:
            return 0, f"import failed: {self._import_error}"

        return super().test_q3_performance()

    def test_q4_consistency(self) -> tuple[int, str]:
        """Q4: Consistency - must be overridden with specific check."""
        if self._import_error:
            return 0, f"import failed: {self._import_error}"

        return super().test_q4_consistency()

    def test_c1_tests(self) -> tuple[int, str]:
        """C1: Run project's pytest suite."""
        # Set PYTHONPATH for subprocess
        import os
        env = os.environ.copy()
        src_path = str(self.project_root / "src")
        env["PYTHONPATH"] = f"{src_path}:{env.get('PYTHONPATH', '')}"

        test_dir = self.project_root / "tests"
        if not test_dir.exists():
            return 0, "no tests/ dir"

        try:
            import subprocess
            result = subprocess.run(
                self.test_command,
                capture_output=True,
                text=True,
                timeout=self.test_timeout,
                cwd=self.project_root,
                env=env,
            )
            output = result.stdout + result.stderr

            # Parse pytest output
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
                return 0, "no tests found"

            return ratio_score(passed, total)

        except subprocess.TimeoutExpired:
            return 0, f"timeout ({self.test_timeout}s)"
        except Exception as e:
            return 0, f"error: {e}"

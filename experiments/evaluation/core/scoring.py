"""Scoring utilities for evaluation framework.

All evaluations use a 0-5 scale:
    5 = Excellent - works flawlessly
    4 = Good - minor issues
    3 = Acceptable - needs fixes
    2 = Poor - significant problems
    1 = Failing - barely works
    0 = Missing - doesn't exist or broken

Total score: 80 points (8 auto + 8 manual criteria, 5 points each)
"""

from typing import Sequence

# Grade thresholds (total out of 80)
GRADE_THRESHOLDS = {
    "A": 72,  # 90%+ - Ship it
    "B": 64,  # 80%+ - Minor fixes
    "C": 56,  # 70%+ - Rework needed
    "D": 48,  # 60%+ - Major issues
    "F": 0,   # <60% - Not usable
}


def score(value: float, thresholds: Sequence[tuple[float, int]]) -> int:
    """Convert a numeric value to 0-5 score based on thresholds.

    Args:
        value: The measured value
        thresholds: List of (threshold, score) tuples in descending order.
                   First threshold that value >= gets returned.

    Returns:
        Score from 0-5

    Example:
        >>> score(0.95, [(1.0, 5), (0.9, 4), (0.8, 3), (0.7, 2), (0.5, 1)])
        4
    """
    for threshold, points in thresholds:
        if value >= threshold:
            return points
    return 0


def grade(total: int) -> str:
    """Convert total score (0-80) to letter grade.

    Args:
        total: Total score out of 80

    Returns:
        Letter grade A-F
    """
    for letter, threshold in GRADE_THRESHOLDS.items():
        if total >= threshold:
            return letter
    return "F"


def ratio_score(passed: int, total: int) -> tuple[int, str]:
    """Score based on pass/total ratio.

    Common pattern for counting tests, features, etc.

    Args:
        passed: Number of items that passed
        total: Total number of items

    Returns:
        Tuple of (score 0-5, note string)
    """
    if total == 0:
        return 0, "no items"

    ratio = passed / total
    pts = score(ratio, [(1.0, 5), (0.9, 4), (0.75, 3), (0.5, 2), (0.25, 1)])
    return pts, f"{passed}/{total}"


def count_score(count: int, thresholds: Sequence[tuple[int, int]],
                lower_is_better: bool = False) -> tuple[int, str]:
    """Score based on a count value.

    Args:
        count: The count to score
        thresholds: (threshold, score) tuples
        lower_is_better: If True, lower counts get higher scores

    Returns:
        Tuple of (score 0-5, note string)
    """
    if lower_is_better:
        # Invert for things like "crash count" where 0 is best
        pts = score(-count, [(-t, s) for t, s in thresholds])
    else:
        pts = score(count, thresholds)
    return pts, f"{count}"


def time_score(elapsed_seconds: float,
               thresholds: Sequence[tuple[float, int]] | None = None) -> tuple[int, str]:
    """Score based on execution time (lower is better).

    Default thresholds: <0.5s=5, <1s=4, <2s=3, <5s=2, <10s=1

    Args:
        elapsed_seconds: Time taken
        thresholds: Optional custom (max_seconds, score) tuples

    Returns:
        Tuple of (score 0-5, note string)
    """
    if thresholds is None:
        thresholds = [(0.5, 5), (1.0, 4), (2.0, 3), (5.0, 2), (10.0, 1)]

    # Convert to "speed" (1/time) for scoring
    speed = 1 / elapsed_seconds if elapsed_seconds > 0 else 999
    speed_thresholds = [(1/t, s) for t, s in thresholds]
    pts = score(speed, speed_thresholds)
    return pts, f"{elapsed_seconds:.2f}s"

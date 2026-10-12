"""Judgment consensus + calibration + Merkle helpers (pure, no I/O).

The consensus here is a simple majority over A/B (or a crowd median for
ratings) — deliberately simpler than the capture `schemas.agree()` category+IoU
matching, which stays for the dormant capture path.
"""

from __future__ import annotations

import hashlib
import statistics
from typing import Iterable, Sequence

CHOICES = ("a", "b", "tie", "cant_tell", "rating")


def majority_choice(choices: Iterable[str]) -> tuple[str | None, int]:
    """Majority over ``a``/``b``. Returns ``(winner, votes_for_winner)`` or
    ``(None, 0)`` on a tie. ``tie`` and ``cant_tell`` are excluded by callers."""
    a = sum(1 for c in choices if c == "a")
    b = sum(1 for c in choices if c == "b")
    if a == b:
        return None, a + b
    if a > b:
        return "a", a
    return "b", b


def median_rating(ratings: Iterable[int]) -> float:
    """Crowd median of 1-5 ratings (float median for even counts)."""
    vals = list(ratings)
    if not vals:
        return 0.0
    return statistics.median(vals)


def is_aligned_rating(rating: int, median: float) -> bool:
    return abs(rating - median) <= 1.0


def calibration_correct(
    task_type: str, known_choice: str, choice: str | None, rating: int | None
) -> bool:
    """Whether a calibration answer matches the known consensus. Preference
    tasks match on ``choice``; rating tasks match on the exact known rating."""
    if task_type == "rating":
        try:
            return rating is not None and rating == int(known_choice)
        except (TypeError, ValueError):
            return False
    return choice == known_choice


def _leaf(pair_id: str, preference: str, agreement: float, confidence: float) -> bytes:
    return hashlib.sha256(
        f"{pair_id}|{preference}|{agreement}|{confidence}".encode()
    ).digest()


def merkle_root(
    entries: Sequence[tuple[str, str, float, float]],
) -> str | None:
    """Standard Merkle root over (pair_id, preference, agreement, confidence)
    leaves; the last leaf is padded to a power of two. Returns hex, or None
    when there are no entries."""
    if not entries:
        return None
    level = [_leaf(*e) for e in entries]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(level[i] + level[i + 1]).digest()
            for i in range(0, len(level), 2)
        ]
    return level[0].hex()

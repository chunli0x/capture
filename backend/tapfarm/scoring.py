"""Gold-standard scoring and claim eligibility.

The network's product is label quality, so "what stops someone scripting ten
thousand submissions" has to be answered in code. Two rules do the work:

**Exact-set grading.** A tap-grid submission is correct only if it matches the
answer set exactly. No partial credit - partial credit rewards tapping
everything, since recall goes to 1.0 for free. With 9 cells there are 512
possible subsets, so blind guessing is not a strategy.

**Probation before payout.** Rolling accuracy alone lets a fresh wallet claim
after one lucky gold task, which makes sybil attacks cheap. A contributor must
answer at least MIN_GOLD_SAMPLES gold tasks before any claim is allowed.

This module is also the slashing oracle for the TAP bond: the same rolling
accuracy that gates claiming decides whether part of a bond is burned. Only TAP
is slashable - a staked contributor's SKR is never touched.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

# Gold tasks needed before a contributor may claim. Chosen so that a sybil
# wallet must do real work before it can extract anything, while an honest
# contributor clears it in a couple of minutes.
MIN_GOLD_SAMPLES = 10

# How many recent gold results count toward accuracy. Bounded so a contributor
# who degrades cannot coast on early history.
ACCURACY_WINDOW = 25


def grade_submission(answer: Iterable[int], submitted: Iterable[int]) -> bool:
    """Exact set match. Order and duplicates are irrelevant."""
    return set(answer) == set(submitted)


@dataclass
class Eligibility:
    allowed: bool
    reason: str
    accuracy: float
    samples: int


@dataclass
class ContributorRecord:
    """Rolling gold-task history for one contributor."""

    contributor: str
    gold_results: deque[bool] = field(
        default_factory=lambda: deque(maxlen=ACCURACY_WINDOW)
    )
    gold_seen: int = 0
    production_submitted: int = 0

    def record_gold(self, correct: bool) -> None:
        self.gold_results.append(correct)
        self.gold_seen += 1

    def record_production(self) -> None:
        self.production_submitted += 1

    @property
    def accuracy(self) -> float:
        """Accuracy over the window. 0.0 with no samples, never a free pass."""
        if not self.gold_results:
            return 0.0
        return sum(self.gold_results) / len(self.gold_results)

    def eligibility(self, min_accuracy: float) -> Eligibility:
        if self.gold_seen < MIN_GOLD_SAMPLES:
            return Eligibility(
                allowed=False,
                reason=(
                    f"{self.gold_seen}/{MIN_GOLD_SAMPLES} verification tasks completed"
                ),
                accuracy=self.accuracy,
                samples=self.gold_seen,
            )
        if self.accuracy < min_accuracy:
            return Eligibility(
                allowed=False,
                reason=(
                    f"accuracy {self.accuracy:.0%} is below the "
                    f"{min_accuracy:.0%} required to claim"
                ),
                accuracy=self.accuracy,
                samples=self.gold_seen,
            )
        return Eligibility(
            allowed=True,
            reason="eligible",
            accuracy=self.accuracy,
            samples=self.gold_seen,
        )


def consensus_label(
    submissions: Iterable[Iterable[int]], *, quorum: int = 2
) -> frozenset[int] | None:
    """Most-agreed answer for a production task, or None below quorum.

    Production tasks have no known answer at serving time, so their label is
    whatever independent contributors agree on. Requiring a quorum means one
    contributor cannot unilaterally define a label.
    """
    counts: dict[frozenset[int], int] = {}
    for submission in submissions:
        key = frozenset(submission)
        counts[key] = counts.get(key, 0) + 1

    if not counts:
        return None

    best, votes = max(counts.items(), key=lambda kv: kv[1])
    return best if votes >= quorum else None

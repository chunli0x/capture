"""Grading for the clip-judgment campaign, and the chance floor it must clear.

Grading itself is trivial next to the pose campaign: a choice either matches the
recorded answer or it does not, with no error metric and no threshold to tune.
The part that needs care is the opposite of trivial.

## Why a binary task needs a sized blind set

The ghost overlay could use a small blind set because dragging a sprite to
within 15px and 10 degrees by luck is vanishingly unlikely. A two-choice
question is not like that: a bot that ignores the clip entirely and flips a coin
is right half the time. If the gate asked for 5 of 6, a coin-flipper would pass
roughly **11%** of the time - and "trivial for a human, hard for a bot" would be
false on the one screen where we claim to prove it.

So the blind set is sized against the binomial tail rather than by taste, and
`chance_pass_probability` is exported so the gate can be *checked* rather than
asserted. `MAX_CHANCE_PASS` is the budget: a guesser must get through less than
one time in a hundred.

This is also why the honest claim is about the *aggregate*, not the single task.
One clip judgment does not prove a human did it. A run of them under a bond
does, which is the same argument the accuracy window in `scoring.py` makes for
the labeling campaigns.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb

# A guesser must clear the blind gate less than 1% of the time. Picked as the
# loosest number that still lets the demo claim the gate means something; the
# defaults below land well under it.
MAX_CHANCE_PASS = 0.01

# "Flag as unclear" is a first-class answer, not a third choice to guess with.
FLAG_UNCLEAR = "unclear"


@dataclass(frozen=True)
class ClipGrade:
    """One graded judgment. `correct` is None when there is no truth to grade."""

    correct: bool | None
    chosen: str
    expected: str | None

    @property
    def gradeable(self) -> bool:
        return self.correct is not None


def grade_choice(chosen: str, expected: str | None) -> ClipGrade:
    """Grade one judgment against a known answer, if there is one.

    `expected is None` means live work: real buyer tasks have no ground truth,
    so the grade is ungradeable rather than silently counted as correct. The
    pose campaign draws the same distinction and for the same reason - counting
    ungraded work as passing would inflate every accuracy number we publish.
    """
    if expected is None:
        return ClipGrade(correct=None, chosen=chosen, expected=None)
    return ClipGrade(correct=chosen == expected, chosen=chosen, expected=expected)


def chance_pass_probability(items: int, required: int, choices: int = 2) -> float:
    """Probability that a uniform guesser passes a blind set of this size.

    The binomial tail: sum over k >= required of C(n, k) p^k (1-p)^(n-k), with
    p = 1/choices. Exported rather than inlined because the number it returns is
    the evidence behind "hard for a bot", and a claim that cannot be recomputed
    is a claim nobody should repeat on stage.
    """
    if items <= 0:
        raise ValueError("a blind set needs at least one item")
    if not 0 < required <= items:
        raise ValueError(f"required must be in 1..{items}, got {required}")
    if choices < 2:
        raise ValueError("a judgment needs at least two choices")

    p = 1.0 / choices
    return sum(
        comb(items, k) * (p**k) * ((1.0 - p) ** (items - k))
        for k in range(required, items + 1)
    )


def required_correct(items: int, pass_fraction: float) -> int:
    """How many correct answers a pass fraction demands, rounded up.

    Rounded up rather than to nearest: 0.9 of 12 is 10.8, and letting 10 pass
    would quietly weaken the gate below what the configuration says.
    """
    if items <= 0:
        raise ValueError("a blind set needs at least one item")
    if not 0.0 < pass_fraction <= 1.0:
        raise ValueError("pass_fraction must be in (0, 1]")

    required = -(-int(round(items * pass_fraction * 1_000_000)) // 1_000_000)
    return max(1, min(items, required))


@dataclass(frozen=True)
class ClipQualification:
    graded: int
    correct: int
    required: int
    passed: bool
    chance_pass: float

    @property
    def accuracy(self) -> float:
        return self.correct / self.graded if self.graded else 0.0


def qualification_result(
    grades: list[ClipGrade],
    *,
    items: int,
    pass_fraction: float,
    choices: int = 2,
) -> ClipQualification:
    """Decide the blind gate, and report what luck alone would have achieved.

    `chance_pass` rides along on the result so that any surface reporting a
    qualification can also report how meaningful it was, instead of the number
    living only in a config file nobody reads.
    """
    gradeable = [g for g in grades if g.gradeable]
    correct = sum(1 for g in gradeable if g.correct)
    required = required_correct(items, pass_fraction)
    return ClipQualification(
        graded=len(gradeable),
        correct=correct,
        required=required,
        # An incomplete run has not passed yet, however well it is going.
        passed=len(gradeable) >= items and correct >= required,
        chance_pass=chance_pass_probability(items, required, choices),
    )


def gate_is_meaningful(
    items: int, pass_fraction: float, choices: int = 2, budget: float = MAX_CHANCE_PASS
) -> bool:
    """True when a guesser clears this gate less often than the budget allows."""
    return (
        chance_pass_probability(items, required_correct(items, pass_fraction), choices)
        < budget
    )

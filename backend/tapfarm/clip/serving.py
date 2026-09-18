"""Serving and grading for the clip-judgment campaign.

Mirrors `pose/serving.py` deliberately: the same three modes, the same golden
mix, the same rule that blind means blind. Where it differs, it differs because
a two-choice judgment is not a drag gesture.

## The three modes

**practice** - unpaid. The response includes the answer *after* submission so
the client can say "Correct.", drawn from a pool no qualification item appears
in.

**qualify** - the blind set. No per-item feedback at all until the run is
complete, because a per-item pass/fail on a binary question is not merely a
proximity signal, it is the answer. Flagging is refused here: "unclear" would
otherwise be a free pass out of any item a bot could not answer.

**earn** - paid work with hidden golden items mixed in at `GOLDEN_MIX_RATE`.
Live items carry `quality_signal: "agreement"` and no correctness, because
there is no ground truth to be correct against.

## Flagging

"Flag as unclear" is a real answer in practice and earn: a clip that genuinely
does not show the answer should be reportable, and punishing that would train
people to guess. It is never graded as correct or incorrect, and never paid, so
it cannot become the cheapest path through paid work.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from tapfarm.clip.dataset import GOLDEN, LIVE, PRACTICE, QUALIFY, ClipTaskRecord
from tapfarm.clip.scoring import (
    FLAG_UNCLEAR,
    ClipGrade,
    ClipQualification,
    grade_choice,
    qualification_result,
)

GOLDEN_MIX_RATE = 0.25


class ClipTaskExhausted(Exception):
    """No unseen clip remains in this pool for this contributor."""


class UnknownClipTask(Exception):
    """Submitted a task that was never served to this contributor."""


class NotQualified(Exception):
    """Paid work requires passing the blind gate first."""


class CannotFlag(Exception):
    """Flagging is not available during qualification."""


class InvalidChoice(Exception):
    """The submitted answer is not one of the choices offered."""


@dataclass(frozen=True)
class ServedClipTask:
    task_id: str
    mode: str
    clip: str
    question: str
    choices: list[str]
    can_flag: bool
    placeholder: bool


@dataclass(frozen=True)
class ClipSubmission:
    accepted: bool
    mode: str
    correct: bool | None
    expected: str | None
    reward: int
    balance: int
    quality_signal: str | None
    qualification: ClipQualification | None
    qualified: bool
    flagged: bool


@dataclass
class _Contributor:
    seen: set[str] = field(default_factory=set)
    outstanding: dict[str, tuple[ClipTaskRecord, str]] = field(default_factory=dict)
    qualify_grades: list[ClipGrade] = field(default_factory=list)
    qualified: bool = False
    balance: int = 0
    drift_grades: list[ClipGrade] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)


class ClipTaskStore:
    def __init__(
        self,
        records: list[ClipTaskRecord],
        truth: dict[str, str],
        *,
        reward_per_task: int,
        qualify_items: int,
        pass_fraction: float,
        rng: random.Random | None = None,
    ) -> None:
        self.reward_per_task = reward_per_task
        self.qualify_items = qualify_items
        self.pass_fraction = pass_fraction
        self._rng = rng or random.Random()
        self._truth = truth
        self._by_pool: dict[str, list[ClipTaskRecord]] = {}
        for record in records:
            self._by_pool.setdefault(record.pool, []).append(record)
        self._by_id = {record.task_id: record for record in records}
        self._contributors: dict[str, _Contributor] = {}

        available = len(self._by_pool.get(QUALIFY, ()))
        if available < qualify_items:
            raise ValueError(
                f"blind set needs {qualify_items} clips, dataset has {available}"
            )

    def state(self, contributor: str) -> _Contributor:
        return self._contributors.setdefault(contributor, _Contributor())

    def _pick(self, pool: str, state: _Contributor) -> ClipTaskRecord:
        candidates = [
            r for r in self._by_pool.get(pool, ()) if r.task_id not in state.seen
        ]
        if not candidates:
            raise ClipTaskExhausted(f"no unseen {pool} clip remains")
        return self._rng.choice(candidates)

    def next_task(self, contributor: str, mode: str) -> ServedClipTask:
        state = self.state(contributor)

        if mode == PRACTICE:
            record = self._pick(PRACTICE, state)
        elif mode == QUALIFY:
            if len(state.qualify_grades) >= self.qualify_items:
                raise ClipTaskExhausted("blind set already complete")
            record = self._pick(QUALIFY, state)
        elif mode == "earn":
            if not state.qualified:
                raise NotQualified("pass the blind set before paid work")
            pool = GOLDEN if self._rng.random() < GOLDEN_MIX_RATE else LIVE
            try:
                record = self._pick(pool, state)
            except ClipTaskExhausted:
                # Running out of one pool must not stop paid work; fall back to
                # the other rather than surfacing which pool was empty, since
                # that alone would tell the labeler which items are graded.
                record = self._pick(LIVE if pool == GOLDEN else GOLDEN, state)
        else:
            raise ValueError(f"unknown mode {mode!r}")

        state.seen.add(record.task_id)
        state.outstanding[record.task_id] = (record, mode)
        return ServedClipTask(
            task_id=record.task_id,
            mode=mode,
            clip=record.clip,
            question=record.question,
            choices=list(record.choices),
            # Blind means blind: an escape hatch during qualification is a way
            # past any item, which is the whole thing the gate is for.
            can_flag=mode != QUALIFY,
            placeholder=record.placeholder,
        )

    def submit(self, contributor: str, task_id: str, chosen: str) -> ClipSubmission:
        state = self.state(contributor)
        if task_id not in state.outstanding:
            raise UnknownClipTask(f"{task_id} was not served to this contributor")
        record, mode = state.outstanding.pop(task_id)

        flagged = chosen == FLAG_UNCLEAR
        if flagged and mode == QUALIFY:
            # Put it back: refusing the submission must not consume the item.
            state.outstanding[task_id] = (record, mode)
            raise CannotFlag("cannot flag during qualification")
        if not flagged and chosen not in record.choices:
            state.outstanding[task_id] = (record, mode)
            raise InvalidChoice(
                f"{chosen!r} is not one of {record.choices!r}"
            )

        if flagged:
            state.flagged.append(task_id)
            return ClipSubmission(
                accepted=True,
                mode=mode,
                correct=None,
                expected=None,
                reward=0,
                balance=state.balance,
                quality_signal=None,
                qualification=None,
                qualified=state.qualified,
                flagged=True,
            )

        expected = self._truth.get(task_id)
        grade = grade_choice(chosen, expected)

        if mode == PRACTICE:
            return ClipSubmission(
                accepted=True,
                mode=mode,
                correct=grade.correct,
                expected=expected,
                reward=0,
                balance=state.balance,
                quality_signal="golden_item",
                qualification=None,
                qualified=state.qualified,
                flagged=False,
            )

        if mode == QUALIFY:
            state.qualify_grades.append(grade)
            result = qualification_result(
                state.qualify_grades,
                items=self.qualify_items,
                pass_fraction=self.pass_fraction,
                choices=len(record.choices),
            )
            complete = len(state.qualify_grades) >= self.qualify_items
            if complete:
                state.qualified = result.passed
            return ClipSubmission(
                accepted=True,
                mode=mode,
                # Blind: no per-item correctness leaves the server mid-run.
                correct=None,
                expected=None,
                reward=0,
                balance=state.balance,
                quality_signal=None,
                qualification=result if complete else None,
                qualified=state.qualified,
                flagged=False,
            )

        # earn
        if grade.gradeable:
            state.drift_grades.append(grade)
        state.balance += self.reward_per_task
        return ClipSubmission(
            accepted=True,
            mode=mode,
            # Hidden golden items must be indistinguishable from live work, so
            # nothing about gradeability leaves the server here either.
            correct=None,
            expected=None,
            reward=self.reward_per_task,
            balance=state.balance,
            quality_signal="golden_item" if grade.gradeable else "agreement",
            qualification=None,
            qualified=True,
            flagged=False,
        )

    def drift_accuracy(self, contributor: str) -> float | None:
        """Rolling accuracy on hidden golden items, or None if none graded yet."""
        grades = self.state(contributor).drift_grades
        if not grades:
            return None
        return sum(1 for g in grades if g.correct) / len(grades)

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

## Failing the gate, and the one retry

A blind gate with no second chance punishes the fluke run: twelve items at 11
correct means a single misread clip plus one misclick ends it. So a failed run
is resettable exactly once, after a cooldown.

Both halves matter. The cap is what stops the gate being brute-forced - with
unlimited retries a coin-flipper reaches 0.32% per attempt but ~1 in 3 over a
hundred attempts, and the gate would mean nothing. The cooldown is what stops
those attempts being cheap.

The retry prefers clips the contributor has not seen. When the qualify pool is
too small for that - twelve items and a twelve-item pool, which is what the
brief's dataset split gives - it re-serves seen clips rather than refusing the
retry outright. That is acceptable *because the first run was blind*: they know
which clips they saw, but never learned which ones they got wrong, so there is
nothing to target. It is still second-best, and a larger qualify pool is worth
having for exactly this reason.

## Flagging

"Flag as unclear" is a real answer in practice and earn: a clip that genuinely
does not show the answer should be reportable, and punishing that would train
people to guess. It is never graded as correct or incorrect, and never paid, so
it cannot become the cheapest path through paid work.
"""

from __future__ import annotations

import random
import time
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


class QualificationFailed(Exception):
    """The blind gate was failed and no retry is available yet."""


class RetryUnavailable(Exception):
    """Asked to retry when there is nothing to retry, or no retry is left."""


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
    failed_at: float | None = None
    retries_used: int = 0


class ClipTaskStore:
    def __init__(
        self,
        records: list[ClipTaskRecord],
        truth: dict[str, str],
        *,
        reward_per_task: int,
        qualify_items: int,
        pass_fraction: float,
        max_retries: int = 1,
        retry_cooldown_seconds: float = 3600.0,
        rng: random.Random | None = None,
    ) -> None:
        self.reward_per_task = reward_per_task
        self.qualify_items = qualify_items
        self.pass_fraction = pass_fraction
        self.max_retries = max_retries
        self.retry_cooldown_seconds = retry_cooldown_seconds
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

    def _pick_qualify(self, state: _Contributor) -> ClipTaskRecord:
        """Prefer an unseen blind item; fall back to a seen one on a retry.

        See the module docstring: falling back is safe only because the first
        run returned no per-item correctness, so a repeated clip carries no
        information about whether it was answered right.
        """
        try:
            return self._pick(QUALIFY, state)
        except ClipTaskExhausted:
            pool = self._by_pool.get(QUALIFY, ())
            served_this_run = {
                task_id for task_id, (_, mode) in state.outstanding.items()
                if mode == QUALIFY
            }
            graded_this_run = len(state.qualify_grades)
            if state.retries_used == 0 or not pool:
                raise
            candidates = [r for r in pool if r.task_id not in served_this_run]
            if not candidates or graded_this_run >= len(pool):
                raise
            return self._rng.choice(candidates)

    def retry_available(self, contributor: str) -> bool:
        state = self.state(contributor)
        return state.failed_at is not None and state.retries_used < self.max_retries

    def retry_ready_at(self, contributor: str) -> float | None:
        """When a retry becomes available, or None if there is nothing to retry."""
        state = self.state(contributor)
        if state.failed_at is None:
            return None
        return state.failed_at + self.retry_cooldown_seconds

    def retry_qualification(self, contributor: str, now: float | None = None) -> None:
        """Reset a failed blind run, once, after the cooldown.

        Raising rather than silently no-opping: a caller that thinks it reset
        the gate and did not would show the contributor a run that can never
        complete.
        """
        state = self.state(contributor)
        now = time.time() if now is None else now

        if state.failed_at is None:
            raise RetryUnavailable("no failed qualification to retry")
        if state.retries_used >= self.max_retries:
            raise RetryUnavailable(
                f"the blind set may be retried {self.max_retries} time(s), and "
                "that has been used"
            )
        ready_at = state.failed_at + self.retry_cooldown_seconds
        if now < ready_at:
            raise RetryUnavailable(
                f"retry available in {ready_at - now:.0f}s"
            )

        state.retries_used += 1
        state.failed_at = None
        state.qualify_grades = []
        # Any blind item still outstanding belongs to the abandoned run.
        for task_id, (_, task_mode) in list(state.outstanding.items()):
            if task_mode == QUALIFY:
                del state.outstanding[task_id]

    def next_task(self, contributor: str, mode: str) -> ServedClipTask:
        state = self.state(contributor)

        if mode == PRACTICE:
            record = self._pick(PRACTICE, state)
        elif mode == QUALIFY:
            if state.failed_at is not None:
                raise QualificationFailed(
                    "the blind set was failed; request a retry"
                    if self.retry_available(contributor)
                    else "the blind set was failed and no retry is available"
                )
            if len(state.qualify_grades) >= self.qualify_items:
                raise ClipTaskExhausted("blind set already complete")
            record = self._pick_qualify(state)
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
                state.failed_at = None if result.passed else time.time()
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

    def last_grade_correct(self, contributor: str) -> bool:
        """Was the most recent hidden golden item answered correctly?

        Needed by the leaderboard, which has to score accuracy without the
        client ever learning it. Returns False when nothing gradeable has been
        submitted, so an ungraded live item is never counted as a win.
        """
        grades = self.state(contributor).drift_grades
        return bool(grades) and grades[-1].correct is True

    def drift_accuracy(self, contributor: str) -> float | None:
        """Rolling accuracy on hidden golden items, or None if none graded yet."""
        grades = self.state(contributor).drift_grades
        if not grades:
            return None
        return sum(1 for g in grades if g.correct) / len(grades)

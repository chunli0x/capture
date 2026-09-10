"""Serving and grading for the ghost-overlay campaign.

## The three modes

**practice** - unpaid training. The response *includes* the true pose, because
the client needs it to render the snap glow and show "you were 4 degrees off".
That release is safe only because practice draws from its own pool: no practice
image is ever in the blind set, so releasing practice truth leaks nothing about
qualification.

**qualify** - the blind set. Truth never leaves the server, and no per-item
feedback comes back at all: `PoseSubmission.feedback` is None for every item
until the run is complete. A per-item pass/fail would be a proximity signal by
another route, and blind has to mean zero signal.

**earn** - paid work. Hidden golden items are mixed in at
`GOLDEN_MIX_RATE` for drift detection; the labeler cannot distinguish them from
live work. Live items have no ground truth, so they carry `quality_signal:
"agreement"` and no error fields - saying "accuracy on every label" would be
false for the majority of real work.

Snap assist and snap glow are a client concern, but the server decides whether
they are allowed: `allow_snap` is true only in practice. If the glow ever fires
during qualification the gate is not blind and the quality proof is gone.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field

from tapfarm.pose.dataset import GOLDEN, LIVE, PRACTICE, QUALIFY, PoseTaskRecord
from tapfarm.pose.scoring import (
    Pose,
    PoseGrade,
    PoseThreshold,
    QualificationResult,
    grade_pose,
    qualification_result,
)

# Share of paid tasks that are secretly known-answer items. High enough to
# detect drift quickly, low enough that most paid work is real work.
GOLDEN_MIX_RATE = 0.25


class PoseTaskExhausted(Exception):
    """No unseen task remains in this pool for this contributor."""


class UnknownPoseTask(Exception):
    """Submitted a task that was never served to this contributor."""


class NotQualified(Exception):
    """Paid work requires passing the blind gate first."""


@dataclass(frozen=True)
class ServedPoseTask:
    """What the client receives.

    `truth` is populated in practice only. `allow_snap` gates the snap glow and
    tracks it exactly.
    """

    task_id: str
    object_id: str
    image_url: str
    canvas: int
    mode: str
    allow_snap: bool
    reward: int
    truth: dict[str, float] | None = None
    index: int | None = None
    of: int | None = None


@dataclass(frozen=True)
class PoseFeedback:
    error_px: float
    error_deg: float
    within_tolerance: bool


@dataclass(frozen=True)
class PoseSubmission:
    accepted: bool
    mode: str
    feedback: PoseFeedback | None
    label: dict | None
    reward: int
    balance: int
    qualification: QualificationResult | None
    qualified: bool


@dataclass
class _ContributorPose:
    seen: set[str] = field(default_factory=set)
    outstanding: dict[str, tuple[PoseTaskRecord, str]] = field(default_factory=dict)
    practice_done: int = 0
    qualify_grades: list[PoseGrade] = field(default_factory=list)
    qualified: bool = False
    balance: int = 0
    labels: list[dict] = field(default_factory=list)
    drift_grades: list[PoseGrade] = field(default_factory=list)


class PoseTaskStore:
    def __init__(
        self,
        records: list[PoseTaskRecord],
        truth: dict[str, dict[str, float]],
        *,
        reward_per_task: int,
        threshold: PoseThreshold | None = None,
        qualify_items: int = 6,
        rng: random.Random | None = None,
    ) -> None:
        self.threshold = threshold or PoseThreshold()
        self.reward_per_task = reward_per_task
        self.qualify_items = qualify_items
        self._rng = rng or random.Random()
        self._truth = truth
        self._by_pool: dict[str, list[PoseTaskRecord]] = {}
        for record in records:
            self._by_pool.setdefault(record.pool, []).append(record)
        self._by_id = {record.task_id: record for record in records}
        self._contributors: dict[str, _ContributorPose] = {}

        available = len(self._by_pool.get(QUALIFY, ()))
        if available < qualify_items:
            raise ValueError(
                f"blind set needs {qualify_items} items, dataset has {available}"
            )

    def state(self, contributor: str) -> _ContributorPose:
        if contributor not in self._contributors:
            self._contributors[contributor] = _ContributorPose()
        return self._contributors[contributor]

    def _pick(self, pool: str, state: _ContributorPose) -> PoseTaskRecord:
        candidates = [r for r in self._by_pool.get(pool, ()) if r.task_id not in state.seen]
        if not candidates:
            raise PoseTaskExhausted(f"no unseen {pool} task remains")
        return self._rng.choice(candidates)

    def next_task(self, contributor: str, mode: str) -> ServedPoseTask:
        state = self.state(contributor)

        if mode == PRACTICE:
            record = self._pick(PRACTICE, state)
            pool = PRACTICE
        elif mode == QUALIFY:
            if len(state.qualify_grades) >= self.qualify_items:
                raise PoseTaskExhausted("blind set already complete")
            record = self._pick(QUALIFY, state)
            pool = QUALIFY
        elif mode == "earn":
            if not state.qualified:
                raise NotQualified("pass the blind qualification set first")
            pool = GOLDEN if self._rng.random() < GOLDEN_MIX_RATE else LIVE
            try:
                record = self._pick(pool, state)
            except PoseTaskExhausted:
                # Falling back keeps paid work flowing when one pool empties;
                # the labeler must never be able to infer the pool from this.
                pool = LIVE if pool == GOLDEN else GOLDEN
                record = self._pick(pool, state)
        else:
            raise ValueError(f"unknown mode: {mode}")

        state.seen.add(record.task_id)
        state.outstanding[record.task_id] = (record, mode)

        return ServedPoseTask(
            task_id=record.task_id,
            object_id=record.object_id,
            image_url=f"/pose/images/{record.image}",
            canvas=record.canvas,
            mode=mode,
            # Practice only. Anywhere else this must stay false.
            allow_snap=mode == PRACTICE,
            reward=self.reward_per_task if mode == "earn" else 0,
            truth=self._truth.get(record.task_id) if mode == PRACTICE else None,
            index=len(state.qualify_grades) + 1 if mode == QUALIFY else None,
            of=self.qualify_items if mode == QUALIFY else None,
        )

    def submit(
        self, contributor: str, task_id: str, pose: Pose, *, now: dt.datetime | None = None
    ) -> PoseSubmission:
        state = self.state(contributor)
        served = state.outstanding.pop(task_id, None)
        if served is None:
            raise UnknownPoseTask(task_id)
        record, mode = served

        truth_pose = self._truth.get(task_id)
        grade = (
            grade_pose(pose, Pose(**truth_pose), self.threshold) if truth_pose else None
        )

        if mode == PRACTICE:
            state.practice_done += 1
            return PoseSubmission(
                accepted=True,
                mode=mode,
                feedback=self._feedback(grade),
                label=None,  # practice is training, not shippable data
                reward=0,
                balance=state.balance,
                qualification=None,
                qualified=state.qualified,
            )

        if mode == QUALIFY:
            assert grade is not None  # qualify items always have truth
            state.qualify_grades.append(grade)
            result = qualification_result(
                state.qualify_grades,
                required_items=self.qualify_items,
                threshold=self.threshold,
            )
            if result.qualified:
                state.qualified = True
            complete = len(state.qualify_grades) >= self.qualify_items
            label = self._label(contributor, record, pose, grade, now)
            state.labels.append(label)
            return PoseSubmission(
                accepted=True,
                mode=mode,
                # Blind: no feedback at all until the whole set is done.
                feedback=None,
                label=label,
                reward=0,
                balance=state.balance,
                qualification=result if complete else None,
                qualified=state.qualified,
            )

        # earn
        state.balance += self.reward_per_task
        if grade is not None:
            state.drift_grades.append(grade)
        label = self._label(contributor, record, pose, grade, now)
        state.labels.append(label)
        return PoseSubmission(
            accepted=True,
            mode=mode,
            feedback=None,
            label=label,
            reward=self.reward_per_task,
            balance=state.balance,
            qualification=None,
            qualified=state.qualified,
        )

    def _feedback(self, grade: PoseGrade | None) -> PoseFeedback | None:
        if grade is None:
            return None
        return PoseFeedback(
            error_px=round(grade.error_px, 1),
            error_deg=round(grade.error_deg, 1),
            within_tolerance=grade.passed,
        )

    def _label(
        self,
        contributor: str,
        record: PoseTaskRecord,
        pose: Pose,
        grade: PoseGrade | None,
        now: dt.datetime | None,
    ) -> dict:
        """The shipped label, per the output spec.

        Error fields appear only where ground truth exists. On live work they
        are absent and the signal is agreement - the distinction between
        "measured accuracy" and "agreement" is exactly what makes the audited
        -data claim survive contact with a buyer.
        """
        timestamp = (now or dt.datetime.now(dt.timezone.utc)).replace(microsecond=0)
        label = {
            "task_id": record.task_id,
            "object_id": record.object_id,
            "worker_id": contributor,
            "pose": pose.as_payload(),
            "scale": round(pose.scale, 2),
        }
        if grade is not None:
            label["error_px"] = round(grade.error_px, 1)
            label["error_deg"] = round(grade.error_deg, 1)
            label["quality_signal"] = "golden_item"
        else:
            label["quality_signal"] = "agreement"
        label["timestamp"] = timestamp.isoformat().replace("+00:00", "Z")
        return label

    def qualification(self, contributor: str) -> QualificationResult:
        state = self.state(contributor)
        return qualification_result(
            state.qualify_grades,
            required_items=self.qualify_items,
            threshold=self.threshold,
        )

    def drift(self, contributor: str) -> QualificationResult:
        """Rolling standing on hidden golden items inside paid work."""
        state = self.state(contributor)
        return qualification_result(
            state.drift_grades, required_items=1, threshold=self.threshold
        )

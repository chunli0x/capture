"""Task serving, grading and contributor state.

The one subtlety here is what "gold" means at serving time rather than at
generation time.

The generator knows the answer to every scene it builds. What makes a task
*gold* is a serving decision: whether this contributor's submission will be
graded against that answer and counted toward their accuracy. Everything else
is served as **production** work - ungraded, paid, and labeled by consensus,
standing in for the real jobs a buyer pays for and whose answers we would not
know in advance.

So two rules follow, and both matter:

- The contributor cannot tell which is which. If gold were identifiable, it
  would be graded honestly and everything else scripted.
- Production submissions are paid whether or not they match the withheld truth.
  We are not entitled to grade work we are pretending not to know the answer
  to, and quality is enforced by gold sampling plus the bond instead.

Gold rate is *designed* to fall once a contributor has a bond at stake, on the
reasoning that the bond does the work verification sampling would otherwise pay
for. **That path is not live:** every caller passes tier 0, so the staked rate
below is currently unreachable. Reading the real tier from the stake program is
listed in PLATFORM.md as decided and not yet built.
"""

from __future__ import annotations

import json
import pathlib
import random
from dataclasses import dataclass, field

from tapfarm.scoring import ContributorRecord, grade_submission

# Fraction of served tasks that are graded, by tier. Unstaked contributors are
# verified heavily because nothing else is protecting the data; a staked
# contributor would be verified less because the bond covers the difference.
#
# Only tier 0 is reachable today - `next_task` is always called with tier=0, so
# the 5% entry is aspirational rather than in use. It is kept because the shape
# of the mechanism is settled and only the lookup of a contributor's real tier
# is missing; see PLATFORM.md.
GOLD_RATE_BY_TIER: dict[int, float] = {0: 0.20, 1: 0.05}


@dataclass(frozen=True)
class TaskView:
    """What the client is allowed to see. Never carries the answer."""

    task_id: str
    campaign_id: str
    prompt: str
    grid: int
    image_url: str
    reward: int


@dataclass(frozen=True)
class SubmissionResult:
    accepted: bool
    graded: bool
    correct: bool | None  # None when the task was not graded
    reward: int
    balance: int
    accuracy: float
    gold_samples: int
    claimable: bool
    reason: str


class TaskExhausted(Exception):
    """No unseen task remains for this contributor."""


class UnknownTask(Exception):
    """Submitted a task id that was never served to this contributor."""


@dataclass
class _Served:
    task_id: str
    is_gold: bool


@dataclass
class ContributorState:
    record: ContributorRecord
    seen: set[str] = field(default_factory=set)
    outstanding: dict[str, _Served] = field(default_factory=dict)
    balance: int = 0


class TaskStore:
    """In-memory task store backed by a generated dataset directory.

    SQLite replaces this once the demo shape is settled; the interface is the
    part worth keeping stable.
    """

    def __init__(
        self,
        dataset_dir: pathlib.Path,
        *,
        campaign_id: str = "img-grid-v1",
        reward_per_task: int = 1000,
        rng: random.Random | None = None,
    ) -> None:
        self.dataset_dir = dataset_dir
        self.campaign_id = campaign_id
        self.reward_per_task = reward_per_task
        self._rng = rng or random.Random()

        manifest_path = dataset_dir / "manifest.jsonl"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"no dataset at {dataset_dir}; run python -m tapfarm.generator.dataset"
            )

        self._tasks: list[dict] = [
            json.loads(line) for line in manifest_path.open() if line.strip()
        ]
        # truth.jsonl is server-side only - it is what makes grading possible
        # and also what would let someone auto-solve every task.
        self._truth: dict[str, list[int]] = {}
        with (dataset_dir / "truth.jsonl").open() as handle:
            for line in handle:
                row = json.loads(line)
                self._truth[row["task_id"]] = row["answer"]

        self._by_id = {task["task_id"]: task for task in self._tasks}
        self._contributors: dict[str, ContributorState] = {}

    # -- contributor state ---------------------------------------------------

    def state(self, contributor: str) -> ContributorState:
        if contributor not in self._contributors:
            self._contributors[contributor] = ContributorState(
                record=ContributorRecord(contributor=contributor)
            )
        return self._contributors[contributor]

    def gold_rate_for(self, tier: int) -> float:
        return GOLD_RATE_BY_TIER.get(tier, GOLD_RATE_BY_TIER[0])

    # -- serving -------------------------------------------------------------

    def next_task(self, contributor: str, *, tier: int = 0) -> TaskView:
        state = self.state(contributor)

        candidates = [t for t in self._tasks if t["task_id"] not in state.seen]
        if not candidates:
            raise TaskExhausted(f"{contributor} has seen every task")

        task = self._rng.choice(candidates)
        task_id = task["task_id"]

        is_gold = self._rng.random() < self.gold_rate_for(tier)
        state.seen.add(task_id)
        state.outstanding[task_id] = _Served(task_id=task_id, is_gold=is_gold)

        return TaskView(
            task_id=task_id,
            campaign_id=self.campaign_id,
            prompt=task["prompt"],
            grid=task["grid"],
            image_url=f"/images/{task['image']}",
            reward=self.reward_per_task,
        )

    # -- grading -------------------------------------------------------------

    def submit(
        self, contributor: str, task_id: str, cells: list[int], *, min_accuracy: float
    ) -> SubmissionResult:
        state = self.state(contributor)

        served = state.outstanding.pop(task_id, None)
        if served is None:
            # Either never served to this contributor, or already submitted.
            # Both are rejected: replaying a known-good answer is the cheapest
            # possible farm.
            raise UnknownTask(task_id)

        grid_cells = self._by_id[task_id]["grid"] ** 2
        if any(cell < 0 or cell >= grid_cells for cell in cells):
            raise ValueError(f"cell index outside 0..{grid_cells - 1}")

        correct: bool | None = None
        if served.is_gold:
            correct = grade_submission(self._truth[task_id], cells)
            state.record.record_gold(correct)
        else:
            state.record.record_production()

        # Gold tasks pay only when right; production tasks always pay, because
        # we are not entitled to grade what we claim not to know.
        paid = self.reward_per_task if (correct is None or correct) else 0
        state.balance += paid

        eligibility = state.record.eligibility(min_accuracy)
        return SubmissionResult(
            accepted=True,
            graded=served.is_gold,
            correct=correct,
            reward=paid,
            balance=state.balance,
            accuracy=eligibility.accuracy,
            gold_samples=eligibility.samples,
            claimable=eligibility.allowed and state.balance > 0,
            reason=eligibility.reason,
        )

    def withheld_truth(self, task_id: str) -> list[int]:
        """Server-side only. Used to measure label quality after the fact."""
        return self._truth[task_id]

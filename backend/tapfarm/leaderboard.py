"""Network stats and the quality leaderboard.

## Why accuracy dominates

A leaderboard is an incentive, not a decoration: whatever it ranks on is what
people will optimise. Rank on volume and a farm wins by doing more work, which
is precisely the behaviour the bond exists to punish - the board would be
paying for the thing the rest of the system is trying to stop.

So the score is accuracy first, and volume only separates contributors who are
already equally accurate. Concretely:

    score = accuracy + (volume_bonus * confidence)

where `volume_bonus` is capped at `MAX_VOLUME_BONUS`, small enough that no
amount of work overtakes a meaningfully more accurate contributor. With the
default cap of 0.05, someone at 90% accuracy cannot be passed by anyone below
85% however much they grind.

`confidence` exists because ten graded items and a thousand are not the same
claim. A contributor with three golden items at 100% is not yet better than
one with two hundred at 97%, and without a confidence term the board's top
would be a churn of newcomers with tiny samples.

## What "online now" is, and is not

A heartbeat: contributors this process has heard from inside
`ONLINE_WINDOW_SECONDS`. It is not a verified population, it cannot be
verified by anyone, and it resets when the process does. Every surface that
reports it names it an estimate, because it is the number on the network
screen most likely to be read as harder than it is.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# Someone counts as online if we have heard from them this recently.
ONLINE_WINDOW_SECONDS = 300.0

DAY_SECONDS = 86_400.0

# The most volume can ever add to a score. Deliberately far below the spread
# between a good and a bad contributor's accuracy.
MAX_VOLUME_BONUS = 0.05

# Graded items at which the volume bonus is considered fully earned.
CONFIDENCE_ITEMS = 50


def quality_score(
    accuracy: float,
    graded_items: int,
    *,
    max_volume_bonus: float = MAX_VOLUME_BONUS,
    confidence_items: int = CONFIDENCE_ITEMS,
) -> float:
    """Accuracy, nudged by how much work backs it up.

    Pure, and exported, so the ranking can be recomputed by anyone who doubts
    the board rather than taken on trust.
    """
    if not 0.0 <= accuracy <= 1.0:
        raise ValueError(f"accuracy must be in 0..1, got {accuracy}")
    if graded_items < 0:
        raise ValueError("graded_items cannot be negative")
    if confidence_items <= 0:
        raise ValueError("confidence_items must be positive")

    confidence = min(1.0, graded_items / confidence_items)
    return accuracy + max_volume_bonus * confidence


@dataclass
class _Contributor:
    last_seen: float = 0.0
    graded_items: int = 0
    correct_items: int = 0
    work_count: int = 0
    bond: int = 0
    first_acted_today: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.correct_items / self.graded_items if self.graded_items else 0.0


@dataclass(frozen=True)
class LeaderRow:
    human: str
    short: str
    score: float
    accuracy: float
    work_count: int
    bond: int


@dataclass(frozen=True)
class NetworkSnapshot:
    online_now: int
    acted_today: int
    work_proven: int
    source: str


def shorten(pubkey: str, lead: int = 4, tail: int = 4) -> str:
    """`3Kw...xQ9`. Shown instead of a full key so a row stays readable."""
    if len(pubkey) <= lead + tail + 3:
        return pubkey
    return f"{pubkey[:lead]}...{pubkey[-tail:]}"


class NetworkTracker:
    """In-memory activity, matching the rest of this backend's demo scope.

    Thread-safe because the routes that record activity are plain `def` and
    run in FastAPI's threadpool, so two submissions really can land at once.

    A restart clears it. That is the honest failure for a heartbeat, and the
    reason `source` is reported alongside the counts rather than letting a
    reader assume they are durable or on-chain.
    """

    def __init__(self, *, online_window: float = ONLINE_WINDOW_SECONDS) -> None:
        self.online_window = online_window
        self._lock = threading.Lock()
        self._people: dict[str, _Contributor] = {}

    def _get(self, human: str) -> _Contributor:
        return self._people.setdefault(human, _Contributor())

    def seen(self, human: str, *, now: float | None = None) -> None:
        """Record a heartbeat. Called wherever a contributor touches the API."""
        now = time.time() if now is None else now
        with self._lock:
            self._get(human).last_seen = now

    def record_work(
        self,
        human: str,
        *,
        graded: bool = False,
        correct: bool = False,
        now: float | None = None,
    ) -> None:
        """One completed task.

        `graded` is false for live work, which has no ground truth. Counting
        ungraded work as correct would inflate every accuracy on the board,
        which is the same distinction the campaigns already draw.
        """
        now = time.time() if now is None else now
        with self._lock:
            person = self._get(human)
            person.last_seen = now
            person.work_count += 1
            person.first_acted_today = now
            if graded:
                person.graded_items += 1
                if correct:
                    person.correct_items += 1

    def set_bond(self, human: str, bond: int) -> None:
        with self._lock:
            self._get(human).bond = bond

    def snapshot(self, *, now: float | None = None) -> NetworkSnapshot:
        now = time.time() if now is None else now
        with self._lock:
            online = sum(
                1
                for p in self._people.values()
                if now - p.last_seen <= self.online_window
            )
            acted_today = sum(
                1
                for p in self._people.values()
                if p.first_acted_today and now - p.first_acted_today <= DAY_SECONDS
            )
            work = sum(p.work_count for p in self._people.values())
        return NetworkSnapshot(
            online_now=online,
            acted_today=acted_today,
            work_proven=work,
            # Named rather than implied: these are this process's own records,
            # not chain reads. They become on-chain counts when attestations
            # are actually being minted.
            source="backend records (not yet on-chain)",
        )

    def leaderboard(self, *, limit: int = 25) -> list[LeaderRow]:
        with self._lock:
            people = list(self._people.items())

        rows = [
            LeaderRow(
                human=key,
                short=shorten(key),
                score=quality_score(person.accuracy, person.graded_items),
                accuracy=person.accuracy,
                work_count=person.work_count,
                bond=person.bond,
            )
            for key, person in people
            # Somebody who has done nothing is not last, they are absent.
            if person.work_count > 0
        ]
        # Ties break on the key so the order is stable between calls rather
        # than wandering with dict iteration.
        rows.sort(key=lambda r: (-r.score, -r.work_count, r.human))
        return rows[:limit]

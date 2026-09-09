"""Task serving rules.

Most of these correspond to a way of extracting rewards without doing the work.
"""

from __future__ import annotations

import random

import pytest

from tapfarm.generator.dataset import build_dataset
from tapfarm.scoring import MIN_GOLD_SAMPLES
from tapfarm.tasks import (
    GOLD_RATE_BY_TIER,
    TaskExhausted,
    TaskStore,
    UnknownTask,
)

REWARD = 1000
MIN_ACCURACY = 0.8
ALICE = "alice"


@pytest.fixture
def dataset(tmp_path):
    build_dataset(tmp_path, count=200, gold_fraction=0.1, seed=3, write_images=False)
    return tmp_path


@pytest.fixture
def store(dataset):
    return TaskStore(
        dataset, reward_per_task=REWARD, rng=random.Random(1234)
    )


def _force_gold(store: TaskStore, is_gold: bool) -> None:
    store.gold_rate_for = lambda _tier: 1.0 if is_gold else 0.0  # type: ignore[assignment]


def _answer(store: TaskStore, task_id: str) -> list[int]:
    return store.withheld_truth(task_id)


# -- serving ------------------------------------------------------------------

def test_served_task_never_carries_the_answer(store):
    task = store.next_task(ALICE)
    assert not hasattr(task, "answer")
    assert "answer" not in vars(task)


def test_never_serves_the_same_task_twice(store):
    seen = {store.next_task(ALICE).task_id for _ in range(50)}
    assert len(seen) == 50


def test_two_contributors_can_receive_the_same_task(store):
    """Production labels come from consensus, so overlap is required."""
    a = {store.next_task("alice").task_id for _ in range(80)}
    b = {store.next_task("bob").task_id for _ in range(80)}
    assert a & b


def test_running_out_of_tasks_is_explicit(dataset):
    small = TaskStore(dataset, reward_per_task=REWARD, rng=random.Random(1))
    for _ in range(200):
        small.next_task(ALICE)
    with pytest.raises(TaskExhausted):
        small.next_task(ALICE)


def test_staked_tier_is_verified_less_often(store):
    assert store.gold_rate_for(1) < store.gold_rate_for(0)
    assert GOLD_RATE_BY_TIER[0] > 0


def test_unknown_tier_falls_back_to_the_strictest_rate(store):
    assert store.gold_rate_for(99) == GOLD_RATE_BY_TIER[0]


def test_gold_rate_is_roughly_honoured(dataset):
    """Sampling should land near the configured rate, not wildly off."""
    store = TaskStore(dataset, reward_per_task=REWARD, rng=random.Random(7))
    gold = 0
    for _ in range(200):
        task = store.next_task(ALICE)
        served = store.state(ALICE).outstanding[task.task_id]
        gold += served.is_gold
    assert 0.10 < gold / 200 < 0.32  # nominal 0.20


# -- grading ------------------------------------------------------------------

def test_correct_gold_answer_pays(store):
    _force_gold(store, True)
    task = store.next_task(ALICE)
    result = store.submit(ALICE, task.task_id, _answer(store, task.task_id),
                          min_accuracy=MIN_ACCURACY)
    assert result.graded and result.correct is True
    assert result.reward == REWARD and result.balance == REWARD


def test_wrong_gold_answer_pays_nothing(store):
    _force_gold(store, True)
    task = store.next_task(ALICE)
    result = store.submit(ALICE, task.task_id, [], min_accuracy=MIN_ACCURACY)
    assert result.graded and result.correct is False
    assert result.reward == 0 and result.balance == 0


def test_production_task_is_ungraded_and_always_pays(store):
    """We are not entitled to grade work we claim not to know the answer to."""
    _force_gold(store, False)
    task = store.next_task(ALICE)
    result = store.submit(ALICE, task.task_id, [0], min_accuracy=MIN_ACCURACY)
    assert not result.graded
    assert result.correct is None
    assert result.reward == REWARD


def test_production_submissions_do_not_move_accuracy(store):
    _force_gold(store, False)
    for _ in range(30):
        task = store.next_task(ALICE)
        store.submit(ALICE, task.task_id, [0], min_accuracy=MIN_ACCURACY)
    assert store.state(ALICE).record.gold_seen == 0


def test_tapping_everything_fails_gold_tasks(store):
    """The obvious farm: maximise recall by selecting every cell."""
    _force_gold(store, True)
    paid = 0
    for _ in range(20):
        task = store.next_task(ALICE)
        result = store.submit(ALICE, task.task_id, list(range(task.grid**2)),
                              min_accuracy=MIN_ACCURACY)
        paid += result.reward
    assert paid == 0


# -- replay and validation -----------------------------------------------------

def test_resubmitting_the_same_task_is_rejected(store):
    """Replaying a known-good answer would be the cheapest possible farm."""
    _force_gold(store, True)
    task = store.next_task(ALICE)
    answer = _answer(store, task.task_id)
    store.submit(ALICE, task.task_id, answer, min_accuracy=MIN_ACCURACY)
    with pytest.raises(UnknownTask):
        store.submit(ALICE, task.task_id, answer, min_accuracy=MIN_ACCURACY)


def test_submitting_a_task_served_to_someone_else_is_rejected(store):
    task = store.next_task("bob")
    with pytest.raises(UnknownTask):
        store.submit(ALICE, task.task_id, [0], min_accuracy=MIN_ACCURACY)


def test_out_of_range_cells_are_rejected(store):
    task = store.next_task(ALICE)
    with pytest.raises(ValueError, match="outside"):
        store.submit(ALICE, task.task_id, [99], min_accuracy=MIN_ACCURACY)


def test_negative_cells_are_rejected(store):
    task = store.next_task(ALICE)
    with pytest.raises(ValueError, match="outside"):
        store.submit(ALICE, task.task_id, [-1], min_accuracy=MIN_ACCURACY)


# -- eligibility ---------------------------------------------------------------

def test_not_claimable_before_probation_even_when_perfect(store):
    _force_gold(store, True)
    result = None
    for _ in range(MIN_GOLD_SAMPLES - 1):
        task = store.next_task(ALICE)
        result = store.submit(ALICE, task.task_id, _answer(store, task.task_id),
                              min_accuracy=MIN_ACCURACY)
    assert result is not None
    assert result.balance > 0
    assert not result.claimable
    assert "verification tasks" in result.reason


def test_claimable_after_probation_with_good_accuracy(store):
    _force_gold(store, True)
    result = None
    for _ in range(MIN_GOLD_SAMPLES):
        task = store.next_task(ALICE)
        result = store.submit(ALICE, task.task_id, _answer(store, task.task_id),
                              min_accuracy=MIN_ACCURACY)
    assert result is not None and result.claimable


def test_a_scripted_contributor_clears_probation_but_cannot_claim(store):
    """Volume alone must not unlock payout.

    A fixed guess coincides with the real answer occasionally - some scenes
    genuinely do answer [0] - so the balance is not zero. That is expected and
    harmless: accrual is not payout, and the accuracy gate is what stands
    between a scripter and the money.
    """
    _force_gold(store, True)
    rounds = MIN_GOLD_SAMPLES * 2
    result = None
    for _ in range(rounds):
        task = store.next_task(ALICE)
        result = store.submit(ALICE, task.task_id, [0], min_accuracy=MIN_ACCURACY)

    assert result is not None
    assert result.gold_samples >= MIN_GOLD_SAMPLES
    assert result.accuracy < MIN_ACCURACY
    assert not result.claimable
    # Lucky hits only, nowhere near what the same effort earns honestly.
    assert result.balance < rounds * REWARD * MIN_ACCURACY


def test_an_honest_contributor_out_earns_a_scripted_one(store):
    """The comparison the previous test implies, made explicit."""
    _force_gold(store, True)
    rounds = MIN_GOLD_SAMPLES * 2

    honest = None
    for _ in range(rounds):
        task = store.next_task("honest")
        honest = store.submit("honest", task.task_id,
                              _answer(store, task.task_id),
                              min_accuracy=MIN_ACCURACY)

    scripted = None
    for _ in range(rounds):
        task = store.next_task("scripted")
        scripted = store.submit("scripted", task.task_id, [0],
                                min_accuracy=MIN_ACCURACY)

    assert honest is not None and scripted is not None
    assert honest.balance == rounds * REWARD
    assert honest.claimable
    assert scripted.balance < honest.balance
    assert not scripted.claimable


def test_missing_dataset_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="no dataset"):
        TaskStore(tmp_path / "nope")

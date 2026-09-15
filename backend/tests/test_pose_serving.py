"""Ghost-overlay serving rules.

Several of these encode the hard rules from the robotics-advisor review. They
are written so a regression fails the suite rather than quietly weakening the
quality claim, which is the part a buyer would be relying on.
"""

from __future__ import annotations

import datetime as dt
import random

import pytest

from tapfarm.pose.dataset import (
    GOLDEN,
    LIVE,
    PRACTICE,
    QUALIFY,
    build_pose_dataset,
    load_truth,
)
from tapfarm.pose.scoring import Pose, PoseThreshold
from tapfarm.pose.serving import (
    CannotFlag,
    NotQualified,
    PoseTaskExhausted,
    PoseTaskStore,
    UnknownPoseTask,
)

REWARD = 10_000
QUALIFY_ITEMS = 6
ALICE = "alice"


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("pose")
    records = build_pose_dataset(
        out, live_per_object=12, seed=5, write_images=False
    )
    return records, load_truth(out)


@pytest.fixture
def store(dataset):
    records, truth = dataset
    return PoseTaskStore(
        records, truth, reward_per_task=REWARD,
        qualify_items=QUALIFY_ITEMS, rng=random.Random(99),
    )


def _exact(store, task_id):
    """Submit the true pose for a task the server knows the answer to."""
    return Pose(**store._truth[task_id])


def _way_off(store, task_id):
    truth = store._truth[task_id]
    return Pose(x=truth["x"] + 220, y=truth["y"] + 180, roll=truth["roll"] + 90)


def _qualify(store, contributor, *, correct: int):
    """Run the whole blind set, getting `correct` of them right."""
    last = None
    for i in range(QUALIFY_ITEMS):
        task = store.next_task(contributor, QUALIFY)
        pose = _exact(store, task.task_id) if i < correct else _way_off(store, task.task_id)
        last = store.submit(contributor, task.task_id, pose)
    return last


# -- hard rule: qualification is blind ----------------------------------------

def test_qualify_never_returns_truth(store):
    for _ in range(QUALIFY_ITEMS):
        task = store.next_task(ALICE, QUALIFY)
        assert task.truth is None, "the blind set must never carry its answer"
        store.submit(ALICE, task.task_id, Pose(1, 2, 3))


def test_qualify_returns_no_per_item_feedback(store):
    """Per-item pass/fail would be a proximity signal by another route."""
    for i in range(QUALIFY_ITEMS):
        task = store.next_task(ALICE, QUALIFY)
        result = store.submit(ALICE, task.task_id, _exact(store, task.task_id))
        assert result.feedback is None
        if i < QUALIFY_ITEMS - 1:
            assert result.qualification is None, "no running score mid-run"


def test_snap_is_allowed_in_practice_only(store):
    """Hard rule: no proximity-dependent UI during qualification."""
    assert store.next_task(ALICE, PRACTICE).allow_snap is True
    assert store.next_task(ALICE, QUALIFY).allow_snap is False


def test_earn_tasks_never_allow_snap(store):
    _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    for _ in range(6):
        assert store.next_task(ALICE, "earn").allow_snap is False


def test_practice_and_qualify_pools_do_not_overlap(dataset):
    """Practice truth is released, so any overlap would leak the blind set."""
    records, _ = dataset
    practice = {r.task_id for r in records if r.pool == PRACTICE}
    qualify = {r.task_id for r in records if r.pool == QUALIFY}
    assert practice and qualify
    assert practice.isdisjoint(qualify)


# -- practice ------------------------------------------------------------------

def test_practice_releases_truth_for_the_snap_glow(store):
    task = store.next_task(ALICE, PRACTICE)
    assert task.truth is not None
    assert set(task.truth) == {"x", "y", "roll", "scale"}


def test_practice_gives_an_error_delta(store):
    task = store.next_task(ALICE, PRACTICE)
    truth = store._truth[task.task_id]
    result = store.submit(
        ALICE, task.task_id, Pose(truth["x"] + 3, truth["y"] + 4, truth["roll"] + 2)
    )
    assert result.feedback is not None
    assert result.feedback.error_px == pytest.approx(5.0, abs=0.1)
    assert result.feedback.error_deg == pytest.approx(2.0, abs=0.1)


def test_practice_pays_nothing_and_ships_no_label(store):
    """Practice is training, not shippable data."""
    task = store.next_task(ALICE, PRACTICE)
    result = store.submit(ALICE, task.task_id, _exact(store, task.task_id))
    assert result.reward == 0 and result.label is None


# -- the gate ------------------------------------------------------------------

def test_a_perfect_run_qualifies(store):
    result = _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    assert result.qualified
    assert result.qualification is not None and result.qualification.qualified


def test_a_poor_run_does_not_qualify(store):
    result = _qualify(store, ALICE, correct=2)
    assert not result.qualified
    assert not result.qualification.qualified


def test_qualification_is_reported_only_when_the_run_completes(store):
    for i in range(QUALIFY_ITEMS):
        task = store.next_task(ALICE, QUALIFY)
        result = store.submit(ALICE, task.task_id, _exact(store, task.task_id))
    assert result.qualification is not None


def test_blind_set_cannot_be_extended(store):
    _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    with pytest.raises(PoseTaskExhausted):
        store.next_task(ALICE, QUALIFY)


def test_paid_work_requires_qualifying_first(store):
    with pytest.raises(NotQualified):
        store.next_task(ALICE, "earn")


# -- earning and labels ---------------------------------------------------------

def test_earn_pays_per_task(store):
    _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    task = store.next_task(ALICE, "earn")
    result = store.submit(ALICE, task.task_id, Pose(100, 100, 10))
    assert result.reward == REWARD and result.balance == REWARD


def test_label_matches_the_output_spec(store):
    _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    task = store.next_task(ALICE, "earn")
    when = dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.timezone.utc)
    label = store.submit(ALICE, task.task_id, Pose(122, 338, 12.9, 1.0), now=when).label

    assert label is not None
    required = {"task_id", "object_id", "worker_id", "pose", "scale",
                "quality_signal", "timestamp"}
    assert required <= set(label)
    assert set(label["pose"]) == {"x", "y", "roll"}
    assert label["worker_id"] == ALICE
    assert label["timestamp"] == "2026-09-30T12:00:00Z"
    assert label["task_id"].startswith("pose_")


def test_golden_labels_carry_measured_error(store):
    """Accuracy is knowable only where we hold ground truth."""
    _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    for _ in range(40):
        task = store.next_task(ALICE, "earn")
        label = store.submit(ALICE, task.task_id, Pose(120, 300, 15)).label
        if label["quality_signal"] == "golden_item":
            assert "error_px" in label and "error_deg" in label
            return
    pytest.fail("no golden item was mixed into paid work")


def test_live_labels_carry_agreement_and_no_error_fields(store):
    """Hard rule: accuracy on golden items, agreement on live items."""
    _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    seen_live = False
    for _ in range(40):
        task = store.next_task(ALICE, "earn")
        label = store.submit(ALICE, task.task_id, Pose(120, 300, 15)).label
        if label["quality_signal"] == "agreement":
            seen_live = True
            assert "error_px" not in label
            assert "error_deg" not in label
    assert seen_live, "no live item was served"


def test_golden_items_are_mixed_into_paid_work(store):
    """Drift detection needs hidden known-answer items in the live stream."""
    _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    signals = []
    for _ in range(30):
        task = store.next_task(ALICE, "earn")
        signals.append(store.submit(ALICE, task.task_id, Pose(1, 2, 3)).label["quality_signal"])
    assert "golden_item" in signals and "agreement" in signals


def test_earn_tasks_are_indistinguishable_to_the_client(store):
    """A labeler must not be able to tell a golden item from live work."""
    _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    shapes = set()
    for _ in range(20):
        task = store.next_task(ALICE, "earn")
        shapes.add((task.truth is None, task.allow_snap, task.reward))
        store.submit(ALICE, task.task_id, Pose(1, 2, 3))
    assert shapes == {(True, False, REWARD)}, "served earn tasks differ by pool"


def test_drift_tracks_hidden_golden_items(store):
    _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    for _ in range(30):
        task = store.next_task(ALICE, "earn")
        store.submit(ALICE, task.task_id, _exact(store, task.task_id)
                     if task.task_id in store._truth else Pose(1, 2, 3))
    assert store.drift(ALICE).attempted > 0


# -- replay and validation ------------------------------------------------------

def test_resubmitting_a_task_is_rejected(store):
    task = store.next_task(ALICE, PRACTICE)
    store.submit(ALICE, task.task_id, Pose(1, 2, 3))
    with pytest.raises(UnknownPoseTask):
        store.submit(ALICE, task.task_id, Pose(1, 2, 3))


def test_submitting_someone_elses_task_is_rejected(store):
    task = store.next_task("bob", PRACTICE)
    with pytest.raises(UnknownPoseTask):
        store.submit(ALICE, task.task_id, Pose(1, 2, 3))


def test_no_task_is_served_twice_to_one_contributor(store):
    seen = {store.next_task(ALICE, PRACTICE).task_id for _ in range(2)}
    assert len(seen) == 2


def test_unknown_mode_is_rejected(store):
    with pytest.raises(ValueError, match="unknown mode"):
        store.next_task(ALICE, "freestyle")


def test_store_rejects_a_dataset_too_small_for_the_blind_set(dataset):
    records, truth = dataset
    with pytest.raises(ValueError, match="blind set needs"):
        PoseTaskStore(records, truth, reward_per_task=REWARD, qualify_items=999)


def test_a_looser_threshold_qualifies_a_shakier_run(dataset):
    """Threshold is configurable because it is expected to be loosened."""
    records, truth = dataset
    loose = PoseTaskStore(
        records, truth, reward_per_task=REWARD, qualify_items=QUALIFY_ITEMS,
        threshold=PoseThreshold(max_error_px=25, max_error_deg=15, pass_fraction=0.80),
        rng=random.Random(4),
    )
    for _ in range(QUALIFY_ITEMS):
        task = loose.next_task(ALICE, QUALIFY)
        truth_pose = loose._truth[task.task_id]
        result = loose.submit(
            ALICE, task.task_id,
            Pose(truth_pose["x"] + 20, truth_pose["y"], truth_pose["roll"] + 12),
        )
    assert result.qualified


# -- the safety valve ----------------------------------------------------------

def test_flagging_discards_a_practice_task(store):
    task = store.next_task(ALICE, PRACTICE)
    flagged = store.flag(ALICE, task.task_id, "no_object")
    assert flagged.reason == "no_object" and flagged.mode == PRACTICE
    assert store.flagged(ALICE)[0].task_id == task.task_id


def test_a_flagged_task_cannot_then_be_submitted(store):
    task = store.next_task(ALICE, PRACTICE)
    store.flag(ALICE, task.task_id, "unclear")
    with pytest.raises(UnknownPoseTask):
        store.submit(ALICE, task.task_id, Pose(1, 2, 3))


def test_flagging_pays_nothing(store):
    """A skip must not be a way to earn without labeling."""
    _qualify(store, ALICE, correct=QUALIFY_ITEMS)
    before = store.state(ALICE).balance
    task = store.next_task(ALICE, "earn")
    store.flag(ALICE, task.task_id, "unclear")
    assert store.state(ALICE).balance == before


def test_the_blind_set_cannot_be_skipped(store):
    """Otherwise a labeler rerolls until the set is easy.

    The gate would then measure persistence rather than skill, and the
    qualification number would stop meaning anything.
    """
    task = store.next_task(ALICE, QUALIFY)
    with pytest.raises(CannotFlag):
        store.flag(ALICE, task.task_id, "unclear")


def test_a_refused_flag_leaves_the_task_answerable(store):
    """Refusing the skip must not also strand the item."""
    task = store.next_task(ALICE, QUALIFY)
    with pytest.raises(CannotFlag):
        store.flag(ALICE, task.task_id, "unclear")
    result = store.submit(ALICE, task.task_id, _exact(store, task.task_id))
    assert result.accepted


def test_unknown_flag_reasons_are_rejected(store):
    task = store.next_task(ALICE, PRACTICE)
    with pytest.raises(ValueError, match="unknown flag reason"):
        store.flag(ALICE, task.task_id, "boring")


def test_flagging_an_unserved_task_is_rejected(store):
    with pytest.raises(UnknownPoseTask):
        store.flag(ALICE, "pose_mug_01_001", "unclear")

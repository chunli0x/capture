"""The clip-judgment campaign: the gate, the pools, and what leaves the server.

The properties worth pinning here are the ones a plausible edit would break
silently: that luck cannot clear the blind gate, that blind stays blind, that
flagging cannot become a way through qualification or a way to get paid, and
that live work is never counted as correct.
"""

from __future__ import annotations

import random

import pytest

from tapfarm.clip.dataset import (
    GOLDEN,
    LIVE,
    PRACTICE,
    QUALIFY,
    SourceClip,
    build_clip_dataset,
    load_records,
    load_truth,
    placeholder_clips,
)
from tapfarm.clip.scoring import (
    FLAG_UNCLEAR,
    MAX_CHANCE_PASS,
    chance_pass_probability,
    gate_is_meaningful,
    grade_choice,
    qualification_result,
    required_correct,
)
from tapfarm.clip.serving import (
    CannotFlag,
    ClipTaskStore,
    InvalidChoice,
    NotQualified,
    UnknownClipTask,
)
from tapfarm.config import Settings

QUESTION = "Is the person holding a phone, or a wallet?"
CHOICES = ["phone", "wallet"]


def _clips(count: int) -> list[SourceClip]:
    return [
        SourceClip(
            clip=f"clips/{i:03d}.mp4",
            question=QUESTION,
            choices=list(CHOICES),
            answer=CHOICES[i % 2],
        )
        for i in range(count)
    ]


@pytest.fixture
def dataset(tmp_path):
    records = build_clip_dataset(
        tmp_path, _clips(60), practice=8, qualify=12, golden=10, seed=7
    )
    return records, load_truth(tmp_path), tmp_path


def _store(dataset, **kwargs):
    records, truth, _ = dataset
    params = dict(
        reward_per_task=1000,
        qualify_items=12,
        pass_fraction=0.85,
        rng=random.Random(3),
    )
    params.update(kwargs)
    return ClipTaskStore(records, truth, **params)


class TestChanceFloor:
    """A two-choice task is only hard for a bot if the gate is sized for it."""

    def test_the_shipped_default_gate_beats_chance(self):
        cfg = Settings()
        required = required_correct(cfg.clip_qualify_items, cfg.clip_pass_fraction)
        chance = chance_pass_probability(cfg.clip_qualify_items, required)
        assert chance < MAX_CHANCE_PASS
        assert required == 11 and chance == pytest.approx(0.003174, abs=1e-5)

    def test_the_pose_campaigns_gate_would_not_have_been_good_enough(self):
        """Pinned because copying 6/0.90 across would look reasonable.

        It is the exact mistake this campaign was one edit away from making.
        """
        assert not gate_is_meaningful(items=6, pass_fraction=0.90)
        assert chance_pass_probability(6, required_correct(6, 0.90)) > MAX_CHANCE_PASS

    def test_a_lenient_fraction_is_rejected_by_config(self):
        with pytest.raises(ValueError, match="guesser passes"):
            Settings(clip_qualify_items=6, clip_pass_fraction=0.80)

    def test_more_choices_make_a_smaller_gate_acceptable(self):
        """Four choices quarter the guess rate, so the sizing follows."""
        assert not gate_is_meaningful(items=6, pass_fraction=0.80, choices=2)
        assert gate_is_meaningful(items=6, pass_fraction=0.80, choices=4)

    def test_required_correct_rounds_up_rather_than_to_nearest(self):
        # 0.9 * 12 = 10.8; allowing 10 would weaken the gate below the config.
        assert required_correct(12, 0.9) == 11
        assert required_correct(10, 0.85) == 9

    def test_chance_probability_rejects_impossible_gates(self):
        with pytest.raises(ValueError):
            chance_pass_probability(5, 6)
        with pytest.raises(ValueError):
            chance_pass_probability(0, 0)


class TestDatasetPools:
    def test_pools_are_disjoint(self, dataset):
        """Overlap between practice and qualify would void the gate."""
        records, _, _ = dataset
        by_pool: dict[str, set[str]] = {}
        for r in records:
            by_pool.setdefault(r.pool, set()).add(r.clip)
        assert not by_pool[PRACTICE] & by_pool[QUALIFY]
        assert not by_pool[QUALIFY] & by_pool[GOLDEN]
        assert not by_pool[PRACTICE] & by_pool[GOLDEN]

    def test_live_answers_are_not_in_the_grading_truth(self, dataset):
        """`load_truth` must not be able to reach live answers at all."""
        records, truth, _ = dataset
        live_ids = {r.task_id for r in records if r.pool == LIVE}
        assert live_ids
        assert not live_ids & set(truth)

    def test_truth_covers_every_graded_pool_item(self, dataset):
        records, truth, _ = dataset
        graded = {r.task_id for r in records if r.pool in (PRACTICE, QUALIFY, GOLDEN)}
        assert graded == set(truth)

    def test_manifest_round_trips_without_answers(self, dataset):
        _, _, out_dir = dataset
        reloaded = load_records(out_dir)
        assert reloaded
        for record in reloaded:
            assert not hasattr(record, "answer")

    def test_too_few_clips_is_refused_with_the_arithmetic(self, tmp_path):
        with pytest.raises(ValueError, match="pools need 30 clips"):
            build_clip_dataset(tmp_path, _clips(10), practice=8, qualify=12, golden=10)

    def test_an_answer_outside_the_choices_is_refused(self):
        with pytest.raises(ValueError, match="not one of the choices"):
            SourceClip(clip="c.mp4", question=QUESTION, choices=CHOICES, answer="cat")

    def test_placeholders_are_flagged_so_a_demo_can_refuse_them(self):
        clips = placeholder_clips(4, question=QUESTION, choices=CHOICES)
        assert all(c.placeholder for c in clips)


class TestBlindMeansBlind:
    def test_no_per_item_correctness_leaves_the_server_during_qualify(self, dataset):
        store = _store(dataset)
        for _ in range(5):
            task = store.next_task("alice", QUALIFY)
            result = store.submit("alice", task.task_id, "phone")
            assert result.correct is None
            assert result.expected is None
            assert result.qualification is None

    def test_the_result_arrives_only_when_the_run_completes(self, dataset):
        store = _store(dataset)
        _, truth, _ = dataset
        for i in range(12):
            task = store.next_task("alice", QUALIFY)
            answer = truth[task.task_id]
            result = store.submit("alice", task.task_id, answer)
            if i < 11:
                assert result.qualification is None
        assert result.qualification is not None
        assert result.qualification.passed is True
        assert result.qualified is True

    def test_the_qualification_reports_what_luck_would_have_scored(self, dataset):
        """So any screen showing a pass can also show what it was worth."""
        store = _store(dataset)
        _, truth, _ = dataset
        for _ in range(12):
            task = store.next_task("alice", QUALIFY)
            result = store.submit("alice", task.task_id, truth[task.task_id])
        assert result.qualification.chance_pass < MAX_CHANCE_PASS

    def test_two_wrong_answers_fail_the_gate(self, dataset):
        store = _store(dataset)
        _, truth, _ = dataset
        for i in range(12):
            task = store.next_task("alice", QUALIFY)
            answer = truth[task.task_id]
            if i < 2:
                answer = next(c for c in CHOICES if c != answer)
            result = store.submit("alice", task.task_id, answer)
        assert result.qualification.correct == 10
        assert result.qualification.passed is False
        assert result.qualified is False

    def test_flagging_is_refused_during_qualification(self, dataset):
        store = _store(dataset)
        task = store.next_task("alice", QUALIFY)
        with pytest.raises(CannotFlag):
            store.submit("alice", task.task_id, FLAG_UNCLEAR)

    def test_a_refused_flag_does_not_consume_the_item(self, dataset):
        """Otherwise flagging would still be a way past an item it cannot answer."""
        store = _store(dataset)
        _, truth, _ = dataset
        task = store.next_task("alice", QUALIFY)
        with pytest.raises(CannotFlag):
            store.submit("alice", task.task_id, FLAG_UNCLEAR)
        result = store.submit("alice", task.task_id, truth[task.task_id])
        assert result.accepted is True

    def test_qualify_tasks_do_not_offer_flagging(self, dataset):
        store = _store(dataset)
        assert store.next_task("alice", QUALIFY).can_flag is False
        assert store.next_task("bob", PRACTICE).can_flag is True


class TestPaidWork:
    def test_paid_work_requires_the_gate(self, dataset):
        store = _store(dataset)
        with pytest.raises(NotQualified):
            store.next_task("alice", "earn")

    def _qualify(self, store, dataset, who="alice"):
        _, truth, _ = dataset
        for _ in range(12):
            task = store.next_task(who, QUALIFY)
            store.submit(who, task.task_id, truth[task.task_id])

    def test_earning_pays_and_accumulates(self, dataset):
        store = _store(dataset)
        self._qualify(store, dataset)
        task = store.next_task("alice", "earn")
        result = store.submit("alice", task.task_id, "phone")
        assert result.reward == 1000
        assert result.balance == 1000

    def test_golden_and_live_are_indistinguishable_to_the_labeler(self, dataset):
        """The only difference visible to the client is the quality signal.

        Correctness must never come back, or the labeler learns which items
        are graded and can treat the rest as free money.
        """
        store = _store(dataset)
        self._qualify(store, dataset)
        signals = set()
        for _ in range(20):
            task = store.next_task("alice", "earn")
            result = store.submit("alice", task.task_id, "phone")
            assert result.correct is None and result.expected is None
            signals.add(result.quality_signal)
        assert signals == {"golden_item", "agreement"}

    def test_live_work_is_never_graded_as_correct(self, dataset):
        """There is no ground truth on live work; counting it would inflate."""
        records, truth, _ = dataset
        live = next(r for r in records if r.pool == LIVE)
        assert grade_choice("phone", truth.get(live.task_id)).correct is None

    def test_flagging_pays_nothing_but_is_accepted(self, dataset):
        """Reportable, but never the cheapest path through paid work."""
        store = _store(dataset)
        self._qualify(store, dataset)
        task = store.next_task("alice", "earn")
        result = store.submit("alice", task.task_id, FLAG_UNCLEAR)
        assert result.accepted is True
        assert result.flagged is True
        assert result.reward == 0
        assert result.balance == 0

    def test_an_answer_outside_the_choices_is_refused(self, dataset):
        store = _store(dataset)
        task = store.next_task("alice", PRACTICE)
        with pytest.raises(InvalidChoice):
            store.submit("alice", task.task_id, "banana")

    def test_submitting_a_task_never_served_is_refused(self, dataset):
        store = _store(dataset)
        with pytest.raises(UnknownClipTask):
            store.submit("alice", "qualify-0000", "phone")

    def test_drift_accuracy_only_counts_golden_items(self, dataset):
        store = _store(dataset)
        self._qualify(store, dataset)
        assert store.drift_accuracy("alice") is None
        _, truth, _ = dataset
        for _ in range(20):
            task = store.next_task("alice", "earn")
            store.submit("alice", task.task_id, truth.get(task.task_id, "phone"))
        accuracy = store.drift_accuracy("alice")
        assert accuracy is not None and 0.0 <= accuracy <= 1.0


class TestPractice:
    def test_practice_returns_the_answer_so_feedback_can_be_shown(self, dataset):
        store = _store(dataset)
        _, truth, _ = dataset
        task = store.next_task("alice", PRACTICE)
        result = store.submit("alice", task.task_id, truth[task.task_id])
        assert result.correct is True
        assert result.expected == truth[task.task_id]
        assert result.reward == 0

    def test_practice_never_serves_a_qualification_clip(self, dataset):
        """Releasing practice truth is safe only because the pools are disjoint."""
        records, _, _ = dataset
        store = _store(dataset)
        qualify_clips = {r.clip for r in records if r.pool == QUALIFY}
        for _ in range(8):
            assert store.next_task("alice", PRACTICE).clip not in qualify_clips


def test_a_dataset_too_small_for_the_gate_is_refused(tmp_path):
    records = build_clip_dataset(
        tmp_path, _clips(30), practice=4, qualify=6, golden=4, seed=1
    )
    with pytest.raises(ValueError, match="blind set needs 12 clips"):
        ClipTaskStore(
            records,
            load_truth(tmp_path),
            reward_per_task=1,
            qualify_items=12,
            pass_fraction=0.85,
        )

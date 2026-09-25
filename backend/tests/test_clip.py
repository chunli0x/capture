"""The clip-judgment campaign: the gate, the pools, and what leaves the server.

The properties worth pinning here are the ones a plausible edit would break
silently: that luck cannot clear the blind gate, that blind stays blind, that
flagging cannot become a way through qualification or a way to get paid, and
that live work is never counted as correct.
"""

from __future__ import annotations

import random
import time

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
    ClipTaskExhausted,
    ClipTaskStore,
    InvalidChoice,
    NotQualified,
    QualificationFailed,
    RetryUnavailable,
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


class TestExactChanceFloorPins:
    """The three numbers quoted in the docs and the commit message.

    Pinned exactly, because they are the evidence for "hard for a bot" and a
    drifting constant would quietly turn a documented claim into a wrong one.
    """

    def test_pose_gate_on_a_binary_task(self):
        assert chance_pass_probability(6, required_correct(6, 0.90)) == pytest.approx(
            0.015625, abs=1e-9
        )

    def test_a_lenient_six_item_gate(self):
        assert chance_pass_probability(6, required_correct(6, 0.80)) == pytest.approx(
            0.109375, abs=1e-9
        )

    def test_the_shipped_gate(self):
        assert chance_pass_probability(12, required_correct(12, 0.85)) == pytest.approx(
            0.0031738281, abs=1e-9
        )


class TestQualificationRetry:
    def _fail_the_gate(self, store, dataset, who="alice"):
        _, truth, _ = dataset
        for i in range(12):
            task = store.next_task(who, QUALIFY)
            answer = truth[task.task_id]
            if i < 3:
                answer = next(c for c in CHOICES if c != answer)
            result = store.submit(who, task.task_id, answer)
        return result

    def test_failing_locks_the_gate_rather_than_letting_it_run_on(self, dataset):
        store = _store(dataset)
        assert self._fail_the_gate(store, dataset).qualified is False
        with pytest.raises(QualificationFailed):
            store.next_task("alice", QUALIFY)

    def test_the_cooldown_must_elapse(self, dataset):
        store = _store(dataset, retry_cooldown_seconds=3600)
        self._fail_the_gate(store, dataset)
        assert store.retry_available("alice") is True
        with pytest.raises(RetryUnavailable, match="retry available in"):
            store.retry_qualification("alice", now=time.time())

    def test_after_the_cooldown_the_run_resets(self, dataset):
        store = _store(dataset, retry_cooldown_seconds=60)
        self._fail_the_gate(store, dataset)
        store.retry_qualification("alice", now=time.time() + 61)
        state = store.state("alice")
        assert state.qualify_grades == []
        assert state.failed_at is None
        assert store.next_task("alice", QUALIFY).mode == QUALIFY

    def test_the_retry_can_be_passed(self, dataset):
        """A fluke run must be recoverable, or the gate punishes humans."""
        store = _store(dataset, retry_cooldown_seconds=0)
        self._fail_the_gate(store, dataset)
        store.retry_qualification("alice", now=time.time())
        _, truth, _ = dataset
        for _ in range(12):
            task = store.next_task("alice", QUALIFY)
            result = store.submit("alice", task.task_id, truth[task.task_id])
        assert result.qualification.passed is True
        assert store.state("alice").qualified is True

    def test_only_one_retry_is_allowed(self, dataset):
        """The cap is what stops the gate being brute-forced."""
        store = _store(dataset, retry_cooldown_seconds=0)
        self._fail_the_gate(store, dataset)
        store.retry_qualification("alice", now=time.time())
        self._fail_the_gate(store, dataset)
        assert store.retry_available("alice") is False
        with pytest.raises(RetryUnavailable, match="has been used"):
            store.retry_qualification("alice", now=time.time())

    def test_retrying_without_a_failed_run_is_refused(self, dataset):
        store = _store(dataset)
        with pytest.raises(RetryUnavailable, match="no failed qualification"):
            store.retry_qualification("alice")

    def test_a_retry_after_passing_is_refused(self, dataset):
        store = _store(dataset)
        _, truth, _ = dataset
        for _ in range(12):
            task = store.next_task("alice", QUALIFY)
            store.submit("alice", task.task_id, truth[task.task_id])
        with pytest.raises(RetryUnavailable, match="no failed qualification"):
            store.retry_qualification("alice")

    def test_retry_ready_at_is_none_until_a_run_fails(self, dataset):
        store = _store(dataset, retry_cooldown_seconds=120)
        assert store.retry_ready_at("alice") is None
        self._fail_the_gate(store, dataset)
        ready = store.retry_ready_at("alice")
        assert ready is not None and ready > time.time()

    def test_an_abandoned_outstanding_item_does_not_survive_the_retry(self, dataset):
        """Or the reset run would start with a stale item still open."""
        store = _store(dataset, retry_cooldown_seconds=0)
        self._fail_the_gate(store, dataset)
        store.retry_qualification("alice", now=time.time())
        task = store.next_task("alice", QUALIFY)
        assert list(store.state("alice").outstanding) == [task.task_id]


class TestPoolFallbackAndExhaustion:
    def _qualify(self, store, dataset, who="alice"):
        _, truth, _ = dataset
        for _ in range(12):
            task = store.next_task(who, QUALIFY)
            store.submit(who, task.task_id, truth[task.task_id])

    def test_earning_falls_back_when_one_pool_is_empty(self, tmp_path):
        """Running out of golden items must not stop paid work.

        Nor may it reveal which pool ran dry, since that tells the labeler
        which remaining items are graded.
        """
        records = build_clip_dataset(
            tmp_path, _clips(40), practice=4, qualify=12, golden=1, seed=5
        )
        truth = load_truth(tmp_path)
        store = ClipTaskStore(
            records,
            truth,
            reward_per_task=10,
            qualify_items=12,
            pass_fraction=0.85,
            rng=random.Random(1),
        )
        for _ in range(12):
            task = store.next_task("alice", QUALIFY)
            store.submit("alice", task.task_id, truth[task.task_id])
        for _ in range(15):
            task = store.next_task("alice", "earn")
            assert store.submit("alice", task.task_id, "phone").accepted

    def test_both_paid_pools_exhausted_raises_rather_than_looping(self, tmp_path):
        records = build_clip_dataset(
            tmp_path, _clips(15), practice=1, qualify=12, golden=1, seed=5
        )
        truth = load_truth(tmp_path)
        store = ClipTaskStore(
            records,
            truth,
            reward_per_task=10,
            qualify_items=12,
            pass_fraction=0.85,
            rng=random.Random(1),
        )
        for _ in range(12):
            task = store.next_task("alice", QUALIFY)
            store.submit("alice", task.task_id, truth[task.task_id])
        # Two paid clips exist: one golden, one live.
        for _ in range(2):
            task = store.next_task("alice", "earn")
            store.submit("alice", task.task_id, "phone")
        with pytest.raises(ClipTaskExhausted):
            store.next_task("alice", "earn")

    def test_practice_exhaustion_is_reported(self, dataset):
        store = _store(dataset)
        for _ in range(8):
            store.next_task("alice", PRACTICE)
        with pytest.raises(ClipTaskExhausted, match="practice"):
            store.next_task("alice", PRACTICE)

    def test_completing_the_blind_set_refuses_further_items(self, dataset):
        store = _store(dataset)
        _, truth, _ = dataset
        for _ in range(12):
            task = store.next_task("alice", QUALIFY)
            store.submit("alice", task.task_id, truth[task.task_id])
        with pytest.raises(ClipTaskExhausted, match="already complete"):
            store.next_task("alice", QUALIFY)


class TestSubmissionGuards:
    def _qualify(self, store, dataset, who="alice"):
        _, truth, _ = dataset
        for _ in range(12):
            task = store.next_task(who, QUALIFY)
            store.submit(who, task.task_id, truth[task.task_id])

    @pytest.mark.parametrize("mode", [PRACTICE, QUALIFY, "earn"])
    def test_invalid_choice_is_refused_in_every_mode(self, dataset, mode):
        store = _store(dataset)
        if mode == "earn":
            self._qualify(store, dataset)
        task = store.next_task("alice", mode)
        with pytest.raises(InvalidChoice):
            store.submit("alice", task.task_id, "banana")

    @pytest.mark.parametrize("mode", [PRACTICE, QUALIFY, "earn"])
    def test_a_refused_choice_does_not_consume_the_item(self, dataset, mode):
        store = _store(dataset)
        if mode == "earn":
            self._qualify(store, dataset)
        task = store.next_task("alice", mode)
        with pytest.raises(InvalidChoice):
            store.submit("alice", task.task_id, "banana")
        assert store.submit("alice", task.task_id, task.choices[0]).accepted

    def test_double_submit_is_refused(self, dataset):
        """Or a paid task could be submitted repeatedly for repeated reward."""
        store = _store(dataset)
        self._qualify(store, dataset)
        task = store.next_task("alice", "earn")
        first = store.submit("alice", task.task_id, "phone")
        assert first.reward == 1000
        with pytest.raises(UnknownClipTask):
            store.submit("alice", task.task_id, "phone")
        assert store.state("alice").balance == 1000

    def test_an_unknown_mode_is_rejected(self, dataset):
        store = _store(dataset)
        with pytest.raises(ValueError, match="unknown mode"):
            store.next_task("alice", "freestyle")

    def test_another_contributors_task_cannot_be_submitted(self, dataset):
        store = _store(dataset)
        task = store.next_task("alice", PRACTICE)
        with pytest.raises(UnknownClipTask):
            store.submit("bob", task.task_id, "phone")

    def test_drift_accuracy_is_none_when_everything_was_flagged(self, dataset):
        """Flags are not grades; a wall of flags must not read as 0% accuracy."""
        store = _store(dataset)
        self._qualify(store, dataset)
        for _ in range(10):
            task = store.next_task("alice", "earn")
            store.submit("alice", task.task_id, FLAG_UNCLEAR)
        assert store.drift_accuracy("alice") is None
        assert store.state("alice").balance == 0

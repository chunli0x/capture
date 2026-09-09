"""Anti-gaming rules. These tests are the specification.

Each one corresponds to a way someone would try to farm rewards without doing
the work.
"""

from __future__ import annotations

import pytest

from tapfarm.scoring import (
    ACCURACY_WINDOW,
    MIN_GOLD_SAMPLES,
    ContributorRecord,
    consensus_label,
    grade_submission,
)


def _record(results: list[bool], contributor: str = "alice") -> ContributorRecord:
    record = ContributorRecord(contributor=contributor)
    for correct in results:
        record.record_gold(correct)
    return record


# --- grading -----------------------------------------------------------------

def test_exact_match_is_correct():
    assert grade_submission([1, 4, 7], [7, 1, 4])


def test_order_and_duplicates_do_not_matter():
    assert grade_submission([1, 4], [4, 1, 1, 4])


def test_missing_a_cell_is_wrong():
    assert not grade_submission([1, 4, 7], [1, 4])


def test_extra_cell_is_wrong():
    assert not grade_submission([1, 4], [1, 4, 5])


def test_tapping_everything_is_wrong():
    """The single most obvious farming strategy, closed by exact-set grading."""
    assert not grade_submission([2, 5], list(range(9)))


def test_tapping_nothing_is_wrong():
    assert not grade_submission([2, 5], [])


# --- eligibility -------------------------------------------------------------

def test_perfect_but_unproven_contributor_cannot_claim():
    """A fresh wallet with one lucky answer is the cheap sybil attack."""
    record = _record([True])
    eligibility = record.eligibility(min_accuracy=0.8)
    assert not eligibility.allowed
    assert "1/10 verification tasks" in eligibility.reason


def test_probation_clears_at_the_threshold():
    record = _record([True] * MIN_GOLD_SAMPLES)
    assert record.eligibility(min_accuracy=0.8).allowed


def test_no_history_means_zero_accuracy_not_a_free_pass():
    record = ContributorRecord(contributor="bob")
    assert record.accuracy == 0.0
    assert not record.eligibility(min_accuracy=0.8).allowed


def test_low_accuracy_blocks_claiming_and_says_why():
    record = _record([True] * 5 + [False] * 5)
    eligibility = record.eligibility(min_accuracy=0.8)
    assert not eligibility.allowed
    assert eligibility.accuracy == pytest.approx(0.5)
    assert "50%" in eligibility.reason and "80%" in eligibility.reason


def test_accuracy_is_windowed_so_a_good_history_cannot_be_coasted_on():
    """Someone who was accurate then started scripting must lose eligibility."""
    record = _record([True] * ACCURACY_WINDOW + [False] * ACCURACY_WINDOW)
    assert record.gold_seen == ACCURACY_WINDOW * 2
    assert record.accuracy == 0.0
    assert not record.eligibility(min_accuracy=0.8).allowed


def test_window_holds_only_the_most_recent_results():
    record = _record([False] * ACCURACY_WINDOW + [True] * ACCURACY_WINDOW)
    assert record.accuracy == 1.0
    assert record.eligibility(min_accuracy=0.8).allowed


def test_recovery_is_possible_after_a_bad_streak():
    record = _record([False] * 5 + [True] * ACCURACY_WINDOW)
    assert record.eligibility(min_accuracy=0.8).allowed


def test_production_submissions_do_not_count_toward_eligibility():
    """Otherwise a scripter farms unverified tasks to clear probation."""
    record = ContributorRecord(contributor="carol")
    for _ in range(500):
        record.record_production()
    assert record.gold_seen == 0
    assert not record.eligibility(min_accuracy=0.8).allowed


def test_boundary_accuracy_exactly_at_threshold_is_allowed():
    record = _record([True] * 8 + [False] * 2)
    assert record.accuracy == pytest.approx(0.8)
    assert record.eligibility(min_accuracy=0.8).allowed


# --- consensus ---------------------------------------------------------------

def test_consensus_needs_a_quorum():
    assert consensus_label([[1, 2]], quorum=2) is None


def test_consensus_returns_the_agreed_answer():
    assert consensus_label([[1, 2], [2, 1], [3]], quorum=2) == frozenset({1, 2})


def test_consensus_ignores_a_lone_dissenter():
    assert consensus_label([[4], [4], [4], [0, 1, 2]], quorum=3) == frozenset({4})


def test_consensus_of_nothing_is_none():
    assert consensus_label([], quorum=2) is None


def test_no_agreement_yields_no_label():
    assert consensus_label([[1], [2], [3]], quorum=2) is None

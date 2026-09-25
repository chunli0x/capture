"""The board's incentive, pinned.

A leaderboard is an incentive, not a decoration. The tests that matter are the
ones asserting that grinding volume cannot beat being accurate, because that
is the failure mode where nothing breaks and the network quietly rewards the
behaviour the bond exists to punish.
"""

from __future__ import annotations

import pytest

from tapfarm.leaderboard import (
    MAX_VOLUME_BONUS,
    NetworkTracker,
    quality_score,
    shorten,
)


class TestQualityScore:
    def test_accuracy_dominates_volume(self):
        careful = quality_score(0.98, graded_items=10)
        grinder = quality_score(0.80, graded_items=100_000)
        assert careful > grinder

    def test_volume_cannot_close_a_ten_point_accuracy_gap(self):
        assert quality_score(0.90, 5) > quality_score(0.80, 10_000_000)

    def test_volume_breaks_a_tie_between_equals(self):
        assert quality_score(0.95, 200) > quality_score(0.95, 1)

    def test_the_bonus_is_capped(self):
        unlimited = quality_score(0.5, 10_000_000)
        assert unlimited <= 0.5 + MAX_VOLUME_BONUS + 1e-9

    def test_a_perfect_newcomer_does_not_outrank_a_proven_contributor(self):
        """Without a confidence term the top would churn with tiny samples."""
        newcomer = quality_score(1.0, graded_items=1)
        proven = quality_score(0.99, graded_items=500)
        assert proven > newcomer

    def test_zero_graded_items_scores_its_accuracy_with_no_bonus(self):
        assert quality_score(0.0, 0) == 0.0

    def test_an_impossible_accuracy_is_refused(self):
        with pytest.raises(ValueError):
            quality_score(1.5, 10)
        with pytest.raises(ValueError):
            quality_score(-0.1, 10)


class TestShorten:
    def test_a_long_key_is_abbreviated(self):
        assert shorten("3KwabcdefghijklmnopqrstuvwxQ9") == "3Kwa...wxQ9"

    def test_a_short_string_is_left_alone(self):
        assert shorten("abc") == "abc"


class TestTracker:
    def test_online_counts_only_recent_heartbeats(self):
        tracker = NetworkTracker(online_window=60.0)
        now = 1_000.0
        tracker.seen("alice", now=now)
        tracker.seen("bob", now=now - 600)
        assert tracker.snapshot(now=now).online_now == 1

    def test_the_snapshot_says_where_its_numbers_came_from(self):
        """So nobody reads the heartbeat as an on-chain count."""
        snapshot = NetworkTracker().snapshot()
        assert "not yet on-chain" in snapshot.source

    def test_work_is_counted_and_ungraded_work_does_not_inflate_accuracy(self):
        tracker = NetworkTracker()
        tracker.record_work("alice", graded=True, correct=True)
        tracker.record_work("alice", graded=False)  # live work, no ground truth
        rows = tracker.leaderboard()
        assert rows[0].work_count == 2
        assert rows[0].accuracy == 1.0  # one graded item, one correct

    def test_a_wrong_golden_item_lowers_accuracy(self):
        tracker = NetworkTracker()
        tracker.record_work("alice", graded=True, correct=True)
        tracker.record_work("alice", graded=True, correct=False)
        assert tracker.leaderboard()[0].accuracy == 0.5

    def test_someone_who_has_done_nothing_is_absent_rather_than_last(self):
        tracker = NetworkTracker()
        tracker.seen("lurker")
        assert tracker.leaderboard() == []

    def test_the_board_is_ordered_by_score(self):
        tracker = NetworkTracker()
        for _ in range(50):
            tracker.record_work("accurate", graded=True, correct=True)
        for i in range(200):
            tracker.record_work("grinder", graded=True, correct=i % 2 == 0)
        rows = tracker.leaderboard()
        assert [r.human for r in rows] == ["accurate", "grinder"]

    def test_ordering_is_stable_between_calls(self):
        tracker = NetworkTracker()
        for who in ("a", "b", "c"):
            tracker.record_work(who, graded=True, correct=True)
        assert tracker.leaderboard() == tracker.leaderboard()

    def test_the_limit_is_respected(self):
        tracker = NetworkTracker()
        for i in range(10):
            tracker.record_work(f"who-{i}", graded=True, correct=True)
        assert len(tracker.leaderboard(limit=3)) == 3

    def test_acted_today_ignores_activity_older_than_a_day(self):
        tracker = NetworkTracker()
        now = 1_000_000.0
        tracker.record_work("recent", now=now)
        tracker.record_work("stale", now=now - 90_000)
        assert tracker.snapshot(now=now).acted_today == 1

    def test_rows_carry_a_shortened_key_for_display(self):
        tracker = NetworkTracker()
        tracker.record_work("3KwabcdefghijklmnopqrstuvwxQ9", graded=True, correct=True)
        assert "..." in tracker.leaderboard()[0].short

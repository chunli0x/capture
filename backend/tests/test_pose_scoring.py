"""Image-plane pose metrics.

The wraparound case and the "scale is not scored" case are the two that would
silently ship wrong answers, so both are pinned here.
"""

from __future__ import annotations

import pytest

from tapfarm.pose.scoring import (
    Pose,
    PoseThreshold,
    grade_pose,
    qualification_result,
    rotation_error_deg,
    translation_error_px,
)

T = PoseThreshold()


def test_translation_error_is_euclidean():
    assert translation_error_px(Pose(103, 104, 0), Pose(100, 100, 0)) == pytest.approx(5.0)


def test_identical_pose_scores_zero():
    p = Pose(100, 100, 33, 1.0)
    assert translation_error_px(p, p) == 0
    assert rotation_error_deg(p, p) == 0


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (10, 20, 10),
        (350, 10, 20),      # across the wrap point
        (10, 350, 20),      # and back the other way
        (-170, 170, 20),    # negative representation
        (0, 180, 180),      # maximum possible
        (0, 360, 0),        # full turn is no rotation
        (720 + 15, 15, 0),  # multiple turns
    ],
)
def test_rotation_error_wraps(a, b, expected):
    """350 and 10 degrees are 20 apart, not 340.

    A naive absolute difference fails correct labels near the wrap point; this
    is the classic bug in an angular metric.
    """
    assert rotation_error_deg(Pose(0, 0, a), Pose(0, 0, b)) == pytest.approx(expected)


def test_rotation_error_is_never_above_180():
    for a in range(-360, 361, 17):
        for b in range(-360, 361, 23):
            assert 0 <= rotation_error_deg(Pose(0, 0, a), Pose(0, 0, b)) <= 180


def test_grade_passes_inside_both_tolerances():
    grade = grade_pose(Pose(105, 100, 14), Pose(100, 100, 10), T)
    assert grade.passed and grade.within_translation and grade.within_rotation


def test_grade_is_an_and_not_an_or():
    """Good translation with bad rotation must fail, and vice versa."""
    translation_ok = grade_pose(Pose(100, 100, 40), Pose(100, 100, 10), T)
    rotation_ok = grade_pose(Pose(200, 100, 10), Pose(100, 100, 10), T)
    assert translation_ok.within_translation and not translation_ok.passed
    assert rotation_ok.within_rotation and not rotation_ok.passed


def test_boundary_values_are_inclusive():
    assert grade_pose(Pose(115, 100, 20), Pose(100, 100, 10), T).passed


def test_just_outside_the_boundary_fails():
    assert not grade_pose(Pose(115.1, 100, 10), Pose(100, 100, 10), T).passed
    assert not grade_pose(Pose(100, 100, 20.1), Pose(100, 100, 10), T).passed


def test_scale_is_recorded_but_never_scored():
    """The advisor's MED finding: an unscored, unitless scale must not gate.

    A pinch value with no reference to focal length or physical size maps to
    nothing physical, so letting it into the gate would pass or fail people on
    noise.
    """
    truth = Pose(100, 100, 10, scale=1.0)
    wildly_wrong_scale = Pose(100, 100, 10, scale=9.9)
    assert grade_pose(wildly_wrong_scale, truth, T).passed


def test_scale_still_reaches_the_payload():
    assert Pose(1, 2, 3, scale=0.87).scale == 0.87


def test_pose_payload_has_exactly_the_spec_keys():
    assert set(Pose(1.24, 2.26, 3.31, 1.0).as_payload()) == {"x", "y", "roll"}


# -- qualification -------------------------------------------------------------

def _grades(passing: int, failing: int):
    good, bad = Pose(100, 100, 10), Pose(400, 400, 170)
    truth = Pose(100, 100, 10)
    return [grade_pose(good, truth, T)] * passing + [grade_pose(bad, truth, T)] * failing


def test_qualifies_at_the_pass_fraction():
    result = qualification_result(_grades(9, 1), required_items=10, threshold=T)
    assert result.qualified and result.pass_rate == pytest.approx(0.9)


def test_just_below_the_pass_fraction_fails():
    result = qualification_result(_grades(8, 2), required_items=10, threshold=T)
    assert not result.qualified
    assert "not qualified" in result.summary


def test_incomplete_run_is_never_qualified():
    """A partial run must not qualify, however good it looks so far."""
    result = qualification_result(_grades(5, 0), required_items=10, threshold=T)
    assert not result.qualified
    assert "5/10" in result.summary


def test_empty_run_is_not_qualified():
    result = qualification_result([], required_items=6, threshold=T)
    assert not result.qualified and result.pass_rate == 0.0


def test_summary_reports_the_threshold_actually_used():
    loose = PoseThreshold(max_error_px=25, max_error_deg=15, pass_fraction=0.80)
    result = qualification_result(_grades(5, 5), required_items=10, threshold=loose)
    assert "80% needed" in result.summary


def test_a_loosened_threshold_admits_a_run_the_strict_one_rejects():
    """The threshold is a product decision, not a physics constant."""
    submitted, truth = Pose(120, 100, 22), Pose(100, 100, 10)
    loose = PoseThreshold(max_error_px=25, max_error_deg=15, pass_fraction=0.80)
    assert not grade_pose(submitted, truth, T).passed
    assert grade_pose(submitted, truth, loose).passed

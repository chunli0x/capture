"""Error metrics and the qualification gate for image-plane pose.

Image-plane pose is four numbers: translation (x, y in pixels), in-plane
rotation (roll, degrees), and a unitless scale. It is a 2D similarity
transform, **not** 6D pose - there is no pitch, yaw or physical depth here, and
a flat sprite could not express them. Naming it accurately is a hard rule:
a robotics buyer spots the gap immediately.

## What is scored, and what is not

Translation and rotation are scored. **Scale is recorded but not scored and
does not gate qualification.** The advisor review is blunt about why that has
to be explicit: a unitless pinch value has no reference to focal length or
physical object size, so it maps to nothing physical. Shipping it inside the
gate would let someone pass while being grossly wrong on the one depth-like
axis, with the label still marked accurate. Either it earns a real physical
definition (z = f * physical_size / apparent_px) or it stays out of the gate.
It stays out.

## Two caveats carried from the review

- Pixels are not a physical quantity, and 15px means different things at
  different resolutions and distances. Fine as a relative demo gate; production
  needs normalisation by object size and a pixel-to-mm path.
- Roll is ill-defined for rotationally symmetric objects. Every object in the
  golden set has a visible roll feature, so plain angular difference is
  meaningful here; a symmetric object would need a symmetry-aware metric.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Pose:
    """An image-plane pose. `scale` is auxiliary metadata, never scored."""

    x: float
    y: float
    roll: float
    scale: float = 1.0

    def as_payload(self) -> dict[str, float]:
        """The `pose` object in the output JSON - scale is reported alongside."""
        return {"x": round(self.x, 1), "y": round(self.y, 1), "roll": round(self.roll, 1)}


@dataclass(frozen=True)
class PoseThreshold:
    """Qualification gate.

    A starting point, not a physics constant. The review expects finger input
    on a phone to be looser than this first guess and predicts landing nearer
    20-25px / 15deg / 80-85% after testing with fresh users.
    """

    max_error_px: float = 15.0
    max_error_deg: float = 10.0
    pass_fraction: float = 0.90


@dataclass(frozen=True)
class PoseGrade:
    error_px: float
    error_deg: float
    within_translation: bool
    within_rotation: bool

    @property
    def passed(self) -> bool:
        """Both axes must be within tolerance - the gate is an AND."""
        return self.within_translation and self.within_rotation


def translation_error_px(submitted: Pose, truth: Pose) -> float:
    return math.dist((submitted.x, submitted.y), (truth.x, truth.y))


def rotation_error_deg(submitted: Pose, truth: Pose) -> float:
    """Smallest angular difference, in [0, 180].

    Wrapped deliberately: 350 degrees and 10 degrees are 20 degrees apart, not
    340. A naive absolute difference would fail correct labels near the wrap
    point and is the classic bug in this metric.
    """
    delta = abs(submitted.roll - truth.roll) % 360.0
    return min(delta, 360.0 - delta)


def grade_pose(submitted: Pose, truth: Pose, threshold: PoseThreshold) -> PoseGrade:
    error_px = translation_error_px(submitted, truth)
    error_deg = rotation_error_deg(submitted, truth)
    return PoseGrade(
        error_px=error_px,
        error_deg=error_deg,
        within_translation=error_px <= threshold.max_error_px,
        within_rotation=error_deg <= threshold.max_error_deg,
    )


@dataclass(frozen=True)
class QualificationResult:
    attempted: int
    required: int
    passed_items: int
    pass_rate: float
    required_pass_rate: float
    qualified: bool
    mean_error_px: float
    mean_error_deg: float

    @property
    def summary(self) -> str:
        if self.attempted < self.required:
            return f"{self.attempted}/{self.required} of the blind set completed"
        if self.qualified:
            return (
                f"qualified - {self.passed_items}/{self.attempted} within tolerance "
                f"({self.mean_error_px:.1f}px, {self.mean_error_deg:.1f} deg average)"
            )
        return (
            f"not qualified - {self.passed_items}/{self.attempted} within tolerance "
            f"({self.pass_rate:.0%}), {self.required_pass_rate:.0%} needed"
        )


def qualification_result(
    grades: list[PoseGrade], *, required_items: int, threshold: PoseThreshold
) -> QualificationResult:
    """Whether a blind run clears the gate.

    Qualification is only decided once the whole blind set is done. Grading a
    partial run would leak progress, and the run has to stay silent until the
    end.
    """
    attempted = len(grades)
    passed_items = sum(1 for grade in grades if grade.passed)
    pass_rate = passed_items / attempted if attempted else 0.0
    return QualificationResult(
        attempted=attempted,
        required=required_items,
        passed_items=passed_items,
        pass_rate=pass_rate,
        required_pass_rate=threshold.pass_fraction,
        qualified=attempted >= required_items and pass_rate >= threshold.pass_fraction,
        mean_error_px=(
            sum(g.error_px for g in grades) / attempted if attempted else 0.0
        ),
        mean_error_deg=(
            sum(g.error_deg for g in grades) / attempted if attempted else 0.0
        ),
    )

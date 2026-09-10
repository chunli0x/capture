"""Object silhouettes for the ghost-overlay task.

Every object here is defined once, in a canonical local frame, and used for two
things: rendering the scene image at a known pose, and rendering the ghost
sprite the labeler drags. Both come from the same geometry, so a perfect drag
produces a perfect overlay - if the two were defined separately, the task would
be unwinnable by construction.

## Why these shapes

The advisor review flags roll as ill-defined for rotationally symmetric objects:
a ball or a top-down cylinder has no unambiguous roll, so a "within 10 degrees"
gate is meaningless on it and two correct labels can disagree by any angle.
Every object below therefore carries a clear, visible roll feature - a handle,
an open jaw, a right-angle corner - and none has rotational symmetry.

Coordinates are in a unit frame centred on (0, 0), with the object's longest
extent roughly within [-1, 1]. `base_size_px` scales that frame to pixels at
scale 1.0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Point = tuple[float, float]
Polygon = list[Point]


def _arc(cx: float, cy: float, r: float, start_deg: float, end_deg: float,
         steps: int = 28) -> Polygon:
    """Points along an arc, used to build rounded silhouettes."""
    return [
        (
            cx + r * math.cos(math.radians(start_deg + (end_deg - start_deg) * i / steps)),
            cy + r * math.sin(math.radians(start_deg + (end_deg - start_deg) * i / steps)),
        )
        for i in range(steps + 1)
    ]


@dataclass(frozen=True)
class ShapeDef:
    """One object: a silhouette plus the parts that make its roll readable.

    `parts` is a list of separate filled polygons, not one concatenated ring of
    points. Joining them into a single polygon makes the filler treat the whole
    sequence as one self-intersecting outline - the wrench rendered as a wedge
    that way before this was split out.
    """

    object_id: str
    label: str
    roll_feature: str
    base_size_px: int
    parts: list[Polygon]
    # Drawn in a contrasting tone so roll is visible even when the silhouette
    # alone is nearly symmetric.
    details: list[Polygon] = field(default_factory=list)


def _mug() -> ShapeDef:
    """Top-down mug: a ring body with a handle sticking off one side."""
    body = _arc(0.0, 0.0, 0.62, 0, 360)
    handle = [
        (0.58, -0.20), (0.98, -0.26), (1.04, 0.0),
        (0.98, 0.26), (0.58, 0.20), (0.62, 0.0),
    ]
    inner = _arc(0.0, 0.0, 0.40, 0, 360)
    return ShapeDef(
        object_id="mug_01",
        label="Mug (top-down)",
        roll_feature="handle",
        base_size_px=190,
        parts=[body, handle],
        details=[inner],
    )


def _wrench() -> ShapeDef:
    """Combination wrench: open jaw one end, closed ring the other."""
    shaft = [(-0.62, -0.11), (0.55, -0.13), (0.55, 0.13), (-0.62, 0.11)]
    jaw = [
        (0.55, -0.34), (1.02, -0.34), (1.02, -0.10), (0.80, -0.10),
        (0.80, 0.10), (1.02, 0.10), (1.02, 0.34), (0.55, 0.34),
    ]
    ring = _arc(-0.78, 0.0, 0.30, 0, 360)
    ring_hole = _arc(-0.78, 0.0, 0.15, 0, 360)
    return ShapeDef(
        object_id="wrench_01",
        label="Wrench",
        roll_feature="open jaw versus closed ring",
        base_size_px=250,
        parts=[ring, shaft, jaw],
        details=[ring_hole],
    )


def _bracket() -> ShapeDef:
    """L-bracket: a right angle, so roll is unambiguous at every angle."""
    outline = [
        (-0.55, -0.55), (0.30, -0.55), (0.30, -0.20),
        (-0.20, -0.20), (-0.20, 0.55), (-0.55, 0.55),
    ]
    hole_a = _arc(-0.375, 0.34, 0.09, 0, 360)
    hole_b = _arc(0.10, -0.375, 0.09, 0, 360)
    return ShapeDef(
        object_id="bracket_01",
        label="L-bracket",
        roll_feature="right-angle corner",
        base_size_px=210,
        parts=[outline],
        details=[hole_a, hole_b],
    )


SHAPES: dict[str, ShapeDef] = {
    shape.object_id: shape for shape in (_mug(), _wrench(), _bracket())
}


def transform(
    polygon: Polygon, *, x: float, y: float, roll_deg: float, scale: float,
    base_size_px: int,
) -> list[tuple[float, float]]:
    """Apply the same similarity transform the ghost overlay applies.

    Order is scale, then rotate, then translate - matching the Android canvas,
    where the ghost is scaled and rotated about its own centre before being
    moved. Any other order would make the app and the scorer disagree.

    Roll is clockwise-positive in image coordinates (y grows downward), which is
    what a labeler sees when they twist two fingers clockwise.
    """
    radians = math.radians(roll_deg)
    cos_r, sin_r = math.cos(radians), math.sin(radians)
    size = base_size_px * scale
    out = []
    for px, py in polygon:
        sx, sy = px * size / 2.0, py * size / 2.0
        out.append((x + sx * cos_r - sy * sin_r, y + sx * sin_r + sy * cos_r))
    return out

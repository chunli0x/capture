"""Synthetic scene generation for the tap-grid campaign.

Every scene is built from known ground truth, so labels are exact and free.
That is what makes gold-standard scoring possible at all, and it is also what
the model accuracy curve trains on.

Design constraint worth stating plainly: **at most one object per grid cell, and
every object fits entirely inside its cell.** Objects straddling cell borders
would create genuinely ambiguous tasks, and ambiguous tasks poison
gold-standard scoring - an honest contributor who reads a boundary case
differently than the generator did would be marked wrong and eventually
slashed. Crisp tasks are a correctness requirement, not an aesthetic one.

Scenes are deterministic in their seed, so a dataset can be regenerated exactly
and tests can assert on specific scenes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from PIL import Image, ImageDraw

GRID = 3
CELL = 128
CANVAS = GRID * CELL
OBJECT_MARGIN = 22  # keeps objects clear of cell borders


class Shape(str, Enum):
    CIRCLE = "circle"
    SQUARE = "square"
    TRIANGLE = "triangle"
    DIAMOND = "diamond"
    HEXAGON = "hexagon"


# Chosen for mutual distinguishability, including for the most common forms of
# colour vision deficiency - a contributor should never be slashed for a palette
# they cannot separate.
COLORS: dict[str, tuple[int, int, int]] = {
    "red": (214, 69, 65),
    "blue": (54, 116, 209),
    "green": (46, 158, 94),
    "yellow": (226, 176, 32),
    "purple": (147, 91, 199),
    "orange": (231, 130, 45),
}

BACKGROUND = (247, 248, 250)
GRID_LINE = (223, 227, 232)


@dataclass(frozen=True)
class SceneObject:
    cell: int
    shape: Shape
    color: str

    @property
    def row(self) -> int:
        return self.cell // GRID

    @property
    def col(self) -> int:
        return self.cell % GRID

    def bbox(self) -> tuple[int, int, int, int]:
        x0 = self.col * CELL + OBJECT_MARGIN
        y0 = self.row * CELL + OBJECT_MARGIN
        return (x0, y0, x0 + CELL - 2 * OBJECT_MARGIN, y0 + CELL - 2 * OBJECT_MARGIN)

    def yolo_box(self) -> tuple[float, float, float, float]:
        """Normalized (cx, cy, w, h) - YOLO's native label format."""
        x0, y0, x1, y1 = self.bbox()
        return (
            ((x0 + x1) / 2) / CANVAS,
            ((y0 + y1) / 2) / CANVAS,
            (x1 - x0) / CANVAS,
            (y1 - y0) / CANVAS,
        )


@dataclass(frozen=True)
class Scene:
    seed: int
    target_shape: Shape
    target_color: str
    objects: tuple[SceneObject, ...]

    @property
    def prompt(self) -> str:
        return f"Tap every cell with a {self.target_color} {self.target_shape.value}"

    @property
    def answer(self) -> frozenset[int]:
        """Cells containing a target object. The ground truth."""
        return frozenset(
            o.cell
            for o in self.objects
            if o.shape is self.target_shape and o.color == self.target_color
        )


def _draw_object(draw: ImageDraw.ImageDraw, obj: SceneObject) -> None:
    x0, y0, x1, y1 = obj.bbox()
    fill = COLORS[obj.color]

    if obj.shape is Shape.CIRCLE:
        draw.ellipse((x0, y0, x1, y1), fill=fill)
    elif obj.shape is Shape.SQUARE:
        draw.rectangle((x0, y0, x1, y1), fill=fill)
    elif obj.shape is Shape.TRIANGLE:
        draw.polygon([(x0, y1), (x1, y1), ((x0 + x1) / 2, y0)], fill=fill)
    elif obj.shape is Shape.DIAMOND:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        draw.polygon([(cx, y0), (x1, cy), (cx, y1), (x0, cy)], fill=fill)
    elif obj.shape is Shape.HEXAGON:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
        draw.polygon(
            [
                (cx - rx / 2, y0),
                (cx + rx / 2, y0),
                (x1, cy),
                (cx + rx / 2, y1),
                (cx - rx / 2, y1),
                (x0, cy),
            ],
            fill=fill,
        )


def build_scene(seed: int) -> Scene:
    """Compose one scene.

    Distractors deliberately share either the target's colour or its shape, so
    the task cannot be solved by matching a single attribute.
    """
    rng = random.Random(seed)

    target_shape = rng.choice(list(Shape))
    target_color = rng.choice(list(COLORS))

    cells = list(range(GRID * GRID))
    rng.shuffle(cells)

    n_positive = rng.randint(1, 3)
    n_objects = rng.randint(n_positive + 3, min(7, len(cells)))

    objects: list[SceneObject] = [
        SceneObject(cell=cells[i], shape=target_shape, color=target_color)
        for i in range(n_positive)
    ]

    other_shapes = [s for s in Shape if s is not target_shape]
    other_colors = [c for c in COLORS if c != target_color]

    # The first two distractors are forced near-misses - same shape in the wrong
    # colour, then the right colour in the wrong shape - so a contributor who
    # checks only one attribute gets it wrong.
    near_misses: list[tuple[Shape, str]] = [
        (target_shape, rng.choice(other_colors)),
        (rng.choice(other_shapes), target_color),
    ]
    for i in range(n_positive, n_objects):
        distractor_index = i - n_positive
        if distractor_index < len(near_misses):
            shape, color = near_misses[distractor_index]
        else:
            shape, color = rng.choice(other_shapes), rng.choice(other_colors)
        objects.append(SceneObject(cell=cells[i], shape=shape, color=color))

    return Scene(
        seed=seed,
        target_shape=target_shape,
        target_color=target_color,
        objects=tuple(sorted(objects, key=lambda o: o.cell)),
    )


def render(scene: Scene) -> Image.Image:
    image = Image.new("RGB", (CANVAS, CANVAS), BACKGROUND)
    draw = ImageDraw.Draw(image)

    for i in range(1, GRID):
        draw.line([(i * CELL, 0), (i * CELL, CANVAS)], fill=GRID_LINE, width=2)
        draw.line([(0, i * CELL), (CANVAS, i * CELL)], fill=GRID_LINE, width=2)

    for obj in scene.objects:
        _draw_object(draw, obj)

    return image

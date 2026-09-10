"""Rendering for the ghost-overlay task.

Two outputs, both derived from the same `ShapeDef`:

- **Scene image** - the object drawn at a known true pose on a work surface.
  This is what the labeler sees, standing in for a robot camera frame.
- **Ghost sprite** - the same silhouette as a bright outline on transparency,
  drawn at the canonical pose (centred, roll 0, scale 1). The app applies
  translate / rotate / scale to it.

The golden set is generated this way rather than hand-annotated, which is the
advisor review's second HIGH finding: annotating the golden set by dragging the
same overlay would make "error" mean agreement with one keyholder rather than
correctness, and the accuracy claim is the whole moat. Here the truth is the
transform we rendered at, so the error is honest to render fidelity.

Views are fronto-parallel / top-down of objects lying flat, which is the only
regime where a flat sprite can actually line up - out-of-plane rotation would
need foreshortening the sprite cannot express.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter

from tapfarm.pose.shapes import ShapeDef, transform

CANVAS = 512

SURFACE = (74, 79, 84)
SURFACE_ALT = (67, 72, 77)
OBJECT_FILL = (206, 200, 188)
OBJECT_EDGE = (46, 49, 53)
OBJECT_DETAIL = (150, 144, 133)
CLUTTER = (88, 93, 99)

GHOST_LINE = (74, 222, 128, 255)
GHOST_FILL = (74, 222, 128, 46)


def _work_surface(rng: random.Random) -> Image.Image:
    """A plausible bench background: banded tone, speckle, faint grid."""
    image = Image.new("RGB", (CANVAS, CANVAS), SURFACE)
    draw = ImageDraw.Draw(image)

    for y in range(0, CANVAS, 8):
        if rng.random() < 0.45:
            draw.rectangle([0, y, CANVAS, y + rng.randint(2, 6)], fill=SURFACE_ALT)

    step = 64
    for i in range(step, CANVAS, step):
        draw.line([(i, 0), (i, CANVAS)], fill=(80, 85, 91), width=1)
        draw.line([(0, i), (CANVAS, i)], fill=(80, 85, 91), width=1)

    for _ in range(1400):
        x, y = rng.randrange(CANVAS), rng.randrange(CANVAS)
        tone = rng.randint(-14, 14)
        base = image.getpixel((x, y))
        image.putpixel((x, y), tuple(max(0, min(255, c + tone)) for c in base))

    return image.filter(ImageFilter.GaussianBlur(0.4))


def _clutter(draw: ImageDraw.ImageDraw, rng: random.Random, avoid: tuple[float, float]) -> None:
    """A few background objects, kept clear of the target.

    Without these the task degenerates into "find the only thing in the frame",
    which would not exercise the alignment the label is actually measuring.
    """
    for _ in range(rng.randint(2, 4)):
        for _attempt in range(30):
            cx, cy = rng.randint(60, CANVAS - 60), rng.randint(60, CANVAS - 60)
            if math.dist((cx, cy), avoid) > 210:
                break
        else:
            continue
        w, h = rng.randint(26, 64), rng.randint(26, 64)
        angle = rng.uniform(0, math.pi)
        corners = []
        for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
            corners.append((
                cx + dx * math.cos(angle) - dy * math.sin(angle),
                cy + dx * math.sin(angle) + dy * math.cos(angle),
            ))
        draw.polygon(corners, fill=CLUTTER, outline=(60, 64, 69))


def render_scene(
    shape: ShapeDef,
    *,
    x: float,
    y: float,
    roll: float,
    scale: float,
    seed: int,
) -> Image.Image:
    """Draw the object at the given true pose on a work surface."""
    rng = random.Random(seed)
    image = _work_surface(rng)
    draw = ImageDraw.Draw(image)
    _clutter(draw, rng, avoid=(x, y))

    kwargs = dict(x=x, y=y, roll_deg=roll, scale=scale, base_size_px=shape.base_size_px)

    for part in shape.parts:
        draw.polygon(
            transform(part, **{**kwargs, "x": x + 5, "y": y + 6}), fill=(58, 62, 67)
        )
    for part in shape.parts:
        draw.polygon(transform(part, **kwargs), fill=OBJECT_FILL, outline=OBJECT_EDGE)
    for detail in shape.details:
        draw.polygon(transform(detail, **kwargs), fill=OBJECT_DETAIL, outline=OBJECT_EDGE)

    return image


def render_sprite(shape: ShapeDef, *, line_width: int = 5) -> Image.Image:
    """The ghost, at canonical pose on a transparent square canvas.

    Sized so the sprite's own centre is the canvas centre: the app rotates and
    scales about that centre, so any other framing would make the recorded
    translation disagree with the rendered truth.
    """
    size = int(shape.base_size_px * 1.8)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    centre = size / 2.0
    kwargs = dict(
        x=centre, y=centre, roll_deg=0.0, scale=1.0, base_size_px=shape.base_size_px
    )

    # Fill goes on its own opaque layer that is faded once at the end. Drawing
    # translucent parts directly would darken wherever two parts overlap, and
    # the seams would read as part of the object.
    fill_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fill_draw = ImageDraw.Draw(fill_layer)
    for part in shape.parts:
        fill_draw.polygon(transform(part, **kwargs), fill=GHOST_LINE)
    alpha = fill_layer.getchannel("A").point(lambda v: int(v * GHOST_FILL[3] / 255))
    fill_layer.putalpha(alpha)
    image.alpha_composite(fill_layer)

    draw = ImageDraw.Draw(image)
    for part in shape.parts:
        draw.line(transform(part, **kwargs) + [transform(part, **kwargs)[0]],
                  fill=GHOST_LINE, width=line_width, joint="curve")
    for detail in shape.details:
        pts = transform(detail, **kwargs)
        draw.line(pts + [pts[0]], fill=GHOST_LINE, width=max(2, line_width - 2), joint="curve")

    return image


def sprite_scale_factor(shape: ShapeDef) -> float:
    """Sprite pixels per unit of `scale`.

    The app needs this to size the ghost so that scale 1.0 matches the rendered
    object exactly; it is the one number that has to agree between renderer and
    client.
    """
    return float(int(shape.base_size_px * 1.8))

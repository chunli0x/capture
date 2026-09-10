"""Builds the ghost-overlay golden set.

Every image is a synthetic render at a known transform, so the truth is what we
rendered at rather than what somebody dragged. That is deliberate and it is the
point: hand-annotating the golden set with the same overlay would make the
error metric measure agreement with one keyholder instead of correctness, and
the accuracy claim is the whole moat.

## Four pools, and why they are separate

- **practice** - truth *is* released to the client, because instant feedback and
  the snap glow need it. Practice items are therefore a wholly separate pool
  that never appears in qualification; if they overlapped, releasing practice
  truth would leak the answers to the blind set.
- **qualify** - the blind set. Truth never leaves the server, in any mode.
- **golden** - hidden known-answer items mixed into paid work, for drift
  detection. Truth stays server-side; the labeler cannot tell these from live
  work.
- **live** - stands in for real buyer work. Its truth is written to a separate
  file that scoring never opens, kept only so label quality can be measured
  after the fact. Live labels carry `quality_signal: "agreement"` and no error
  fields, because on real work there is no ground truth to compare against.

Views are fronto-parallel / top-down of objects lying flat - the only regime
where a flat sprite can genuinely align.
"""

from __future__ import annotations

import json
import pathlib
import random
from dataclasses import asdict, dataclass

from tapfarm.pose.render import CANVAS, render_scene, render_sprite, sprite_scale_factor
from tapfarm.pose.shapes import SHAPES

PRACTICE, QUALIFY, GOLDEN, LIVE = "practice", "qualify", "golden", "live"

# Keeps the object clear of the frame edge so the whole silhouette is visible
# and draggable.
MARGIN_PX = 130
SCALE_RANGE = (0.85, 1.15)


@dataclass(frozen=True)
class PoseTaskRecord:
    """What may be written to the client-facing manifest. Never truth."""

    task_id: str
    object_id: str
    pool: str
    image: str
    canvas: int


def _random_pose(rng: random.Random) -> dict[str, float]:
    return {
        "x": float(rng.randint(MARGIN_PX, CANVAS - MARGIN_PX)),
        "y": float(rng.randint(MARGIN_PX, CANVAS - MARGIN_PX)),
        "roll": round(rng.uniform(-180.0, 180.0), 1),
        "scale": round(rng.uniform(*SCALE_RANGE), 2),
    }


def build_pose_dataset(
    out_dir: pathlib.Path,
    *,
    practice_per_object: int = 2,
    qualify_per_object: int = 3,
    golden_per_object: int = 3,
    live_per_object: int = 10,
    seed: int = 1,
    write_images: bool = True,
) -> list[PoseTaskRecord]:
    """Render the dataset and write it to `out_dir`.

    Writes:
      images/<task_id>.png   the scenes
      sprites/<object>.png   the ghost outlines
      objects.json           object metadata the client needs
      manifest.jsonl         task records, no truth
      truth.jsonl            practice + qualify + golden truth (server-side)
      live_truth.jsonl       withheld live truth, for post-hoc analysis only
    """
    plan = [
        (PRACTICE, practice_per_object),
        (QUALIFY, qualify_per_object),
        (GOLDEN, golden_per_object),
        (LIVE, live_per_object),
    ]
    for pool, count in plan:
        if count < 0:
            raise ValueError(f"{pool} count must not be negative, got {count}")

    images_dir, sprites_dir = out_dir / "images", out_dir / "sprites"
    (images_dir if write_images else out_dir).mkdir(parents=True, exist_ok=True)
    if write_images:
        sprites_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    records: list[PoseTaskRecord] = []
    truth_rows: list[dict] = []
    live_rows: list[dict] = []
    objects: list[dict] = []

    for object_id, shape in SHAPES.items():
        if write_images:
            render_sprite(shape).save(sprites_dir / f"{object_id}.png")
        objects.append({
            "object_id": object_id,
            "label": shape.label,
            "roll_feature": shape.roll_feature,
            "sprite": f"/pose/sprites/{object_id}.png",
            # The client sizes the ghost from this so scale 1.0 matches the
            # rendered object exactly. Renderer and client must agree on it.
            "sprite_px_at_scale_1": sprite_scale_factor(shape),
            "canvas": CANVAS,
        })

        index = 0
        for pool, count in plan:
            for _ in range(count):
                index += 1
                task_id = f"pose_{object_id}_{index:03d}"
                pose = _random_pose(rng)
                records.append(PoseTaskRecord(
                    task_id=task_id,
                    object_id=object_id,
                    pool=pool,
                    image=f"{task_id}.png",
                    canvas=CANVAS,
                ))
                if write_images:
                    render_scene(
                        shape, x=pose["x"], y=pose["y"], roll=pose["roll"],
                        scale=pose["scale"], seed=rng.randrange(1 << 30),
                    ).save(images_dir / f"{task_id}.png", optimize=True)

                row = {"task_id": task_id, "object_id": object_id, "pose": pose}
                (live_rows if pool == LIVE else truth_rows).append(row)

    (out_dir / "objects.json").write_text(json.dumps(objects, indent=2))
    with (out_dir / "manifest.jsonl").open("w") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record)) + "\n")
    with (out_dir / "truth.jsonl").open("w") as handle:
        for row in truth_rows:
            handle.write(json.dumps(row) + "\n")
    with (out_dir / "live_truth.jsonl").open("w") as handle:
        for row in live_rows:
            handle.write(json.dumps(row) + "\n")

    return records


def load_truth(out_dir: pathlib.Path) -> dict[str, dict[str, float]]:
    """Golden truth, server-side only. Never serialise this to a client."""
    truth: dict[str, dict[str, float]] = {}
    with (out_dir / "truth.jsonl").open() as handle:
        for line in handle:
            row = json.loads(line)
            truth[row["task_id"]] = row["pose"]
    return truth


def load_objects(out_dir: pathlib.Path) -> list[dict]:
    return json.loads((out_dir / "objects.json").read_text())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build the ghost-overlay dataset")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/pose"))
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    built = build_pose_dataset(args.out, seed=args.seed)
    counts: dict[str, int] = {}
    for record in built:
        counts[record.pool] = counts.get(record.pool, 0) + 1
    print(f"{len(built)} pose tasks -> {args.out}")
    for pool in (PRACTICE, QUALIFY, GOLDEN, LIVE):
        print(f"  {pool:9} {counts.get(pool, 0)}")
    print(f"  objects   {len(SHAPES)}")

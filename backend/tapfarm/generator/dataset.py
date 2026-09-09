"""Dataset builder for the tap-grid campaign.

The synthetic set is used two different ways, and the distinction matters for
what we are entitled to claim:

**Gold tasks** keep their ground truth and are used to score contributors.
Injected into every stream at an undisclosed rate; rolling accuracy against
them gates claiming and, once staking lands, drives slashing.

**Production tasks** have their ground truth withheld from scoring. They stand
in for the real work a buyer is paying for - labels we do not know in advance -
and their labels come from contributor consensus. Because we generated them, we
can afterwards measure consensus against the withheld truth and report a real
number for label quality rather than asserting one.

Keeping the split explicit stops the demo from quietly grading contributors on
tasks it claims not to know the answers to.
"""

from __future__ import annotations

import json
import pathlib
import random
from dataclasses import asdict, dataclass

from tapfarm.generator.scenes import CANVAS, GRID, Scene, build_scene, render


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    seed: int
    image: str
    prompt: str
    grid: int
    kind: str  # "gold" | "production"
    target_shape: str
    target_color: str
    answer: list[int] | None  # withheld (None) for production tasks
    yolo_labels: list[list[float]]

    @property
    def is_gold(self) -> bool:
        return self.kind == "gold"


# Shape order defines the YOLO class index and must stay stable once a model has
# been trained against it.
YOLO_CLASSES = ["circle", "square", "triangle", "diamond", "hexagon"]


def _yolo_labels(scene: Scene) -> list[list[float]]:
    return [
        [float(YOLO_CLASSES.index(o.shape.value)), *o.yolo_box()]
        for o in scene.objects
    ]


def build_task(seed: int, *, kind: str) -> tuple[TaskRecord, Scene]:
    scene = build_scene(seed)
    record = TaskRecord(
        task_id=f"tapgrid-{seed:06d}",
        seed=seed,
        image=f"tapgrid-{seed:06d}.png",
        prompt=scene.prompt,
        grid=GRID,
        kind=kind,
        target_shape=scene.target_shape.value,
        target_color=scene.target_color,
        answer=sorted(scene.answer) if kind == "gold" else None,
        yolo_labels=_yolo_labels(scene),
    )
    return record, scene


def build_dataset(
    out_dir: pathlib.Path,
    *,
    count: int = 10_000,
    gold_fraction: float = 0.08,
    seed: int = 1,
    write_images: bool = True,
) -> list[TaskRecord]:
    """Generate `count` tasks into `out_dir`.

    Returns the task records and writes:
      images/<task_id>.png
      manifest.jsonl        - one TaskRecord per line
      truth.jsonl           - full ground truth for every task, gold or not

    `truth.jsonl` is written separately and is the file that must never be
    served to a client: it is what makes the post-hoc label-quality measurement
    possible, and also what would let someone auto-solve every task.
    """
    if not 0 < gold_fraction < 1:
        raise ValueError(f"gold_fraction must be in (0, 1), got {gold_fraction}")

    images_dir = out_dir / "images"
    if write_images:
        images_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    records: list[TaskRecord] = []

    with (out_dir / "manifest.jsonl").open("w") as manifest, (
        out_dir / "truth.jsonl"
    ).open("w") as truth:
        for i in range(count):
            kind = "gold" if rng.random() < gold_fraction else "production"
            record, scene = build_task(seed * 1_000_000 + i, kind=kind)
            records.append(record)

            if write_images:
                render(scene).save(images_dir / record.image, format="PNG", optimize=True)

            manifest.write(json.dumps(asdict(record)) + "\n")
            truth.write(
                json.dumps({"task_id": record.task_id, "answer": sorted(scene.answer)})
                + "\n"
            )

    (out_dir / "dataset.yaml").write_text(
        "# Ultralytics dataset config for the bounding-box campaign and the\n"
        "# accuracy-curve model. Labels are exact by construction.\n"
        f"path: {out_dir.resolve()}\n"
        "train: images\n"
        "val: images\n"
        f"nc: {len(YOLO_CLASSES)}\n"
        f"names: {YOLO_CLASSES}\n"
    )
    return records


def load_truth(out_dir: pathlib.Path) -> dict[str, list[int]]:
    """Read truth.jsonl. Server-side only."""
    truth: dict[str, list[int]] = {}
    with (out_dir / "truth.jsonl").open() as handle:
        for line in handle:
            row = json.loads(line)
            truth[row["task_id"]] = row["answer"]
    return truth


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build the tap-grid dataset")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/tapgrid"))
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--gold-fraction", type=float, default=0.08)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    built = build_dataset(
        args.out, count=args.count, gold_fraction=args.gold_fraction, seed=args.seed
    )
    gold = sum(1 for r in built if r.is_gold)
    print(f"{len(built)} tasks -> {args.out}  ({gold} gold, {len(built) - gold} production)")
    print(f"canvas {CANVAS}x{CANVAS}, {GRID}x{GRID} grid")

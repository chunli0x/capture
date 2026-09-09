"""The generator's ground truth is what everything else trusts.

If a scene's stated answer does not match what is drawn, gold-standard scoring
silently starts punishing honest contributors, so these tests check the
invariants rather than just that it runs.
"""

from __future__ import annotations

import json

import pytest

from tapfarm.generator.dataset import YOLO_CLASSES, build_dataset, load_truth
from tapfarm.generator.scenes import CANVAS, CELL, GRID, build_scene, render

SEEDS = list(range(200))


@pytest.mark.parametrize("seed", SEEDS[:40])
def test_answer_matches_drawn_objects(seed):
    scene = build_scene(seed)
    expected = {
        o.cell
        for o in scene.objects
        if o.shape is scene.target_shape and o.color == scene.target_color
    }
    assert scene.answer == expected


def test_every_scene_has_at_least_one_answer():
    """A scene with an empty answer is unsolvable and would grade everyone wrong."""
    for seed in SEEDS:
        assert len(build_scene(seed).answer) >= 1, f"seed {seed} has no answer"


def test_answer_is_never_the_whole_grid():
    """If 'tap everything' were ever right, it would be worth trying."""
    for seed in SEEDS:
        assert len(build_scene(seed).answer) < GRID * GRID


def test_at_most_one_object_per_cell():
    """The core disambiguation guarantee."""
    for seed in SEEDS:
        cells = [o.cell for o in build_scene(seed).objects]
        assert len(cells) == len(set(cells)), f"seed {seed} stacked two objects"


def test_objects_stay_inside_their_own_cell():
    for seed in SEEDS:
        for obj in build_scene(seed).objects:
            x0, y0, x1, y1 = obj.bbox()
            assert obj.col * CELL <= x0 and x1 <= (obj.col + 1) * CELL
            assert obj.row * CELL <= y0 and y1 <= (obj.row + 1) * CELL


def test_scenes_include_forced_near_misses():
    """Solving by colour alone or shape alone must not work."""
    same_shape_wrong_color = 0
    same_color_wrong_shape = 0
    for seed in SEEDS:
        scene = build_scene(seed)
        for o in scene.objects:
            if o.shape is scene.target_shape and o.color != scene.target_color:
                same_shape_wrong_color += 1
            if o.color == scene.target_color and o.shape is not scene.target_shape:
                same_color_wrong_shape += 1
    assert same_shape_wrong_color >= len(SEEDS)
    assert same_color_wrong_shape >= len(SEEDS)


def test_generation_is_deterministic():
    assert build_scene(42) == build_scene(42)
    assert build_scene(42) != build_scene(43)


def test_render_produces_expected_canvas():
    image = render(build_scene(3))
    assert image.size == (CANVAS, CANVAS)


def test_rendered_target_color_is_actually_present():
    """Catches a palette or draw-order regression that makes the task a lie."""
    from tapfarm.generator.scenes import COLORS

    scene = build_scene(11)
    image = render(scene)
    # getcolors over getdata: getdata is deprecated in Pillow 12.
    present = {color for _count, color in image.getcolors(maxcolors=1 << 16)}
    assert COLORS[scene.target_color] in present


def test_yolo_boxes_are_normalized_and_within_bounds():
    for seed in SEEDS[:50]:
        scene = build_scene(seed)
        for obj in scene.objects:
            cx, cy, w, h = obj.yolo_box()
            assert 0 < w < 1 and 0 < h < 1
            assert 0 < cx - w / 2 and cx + w / 2 < 1
            assert 0 < cy - h / 2 and cy + h / 2 < 1


def test_dataset_withholds_truth_from_production_tasks(tmp_path):
    records = build_dataset(
        tmp_path, count=300, gold_fraction=0.1, seed=5, write_images=False
    )

    gold = [r for r in records if r.is_gold]
    production = [r for r in records if not r.is_gold]
    assert gold and production

    assert all(r.answer is not None for r in gold)
    assert all(r.answer is None for r in production), (
        "production tasks must not carry their answer - the manifest is served "
        "to clients"
    )


def test_manifest_never_leaks_a_production_answer(tmp_path):
    build_dataset(tmp_path, count=300, gold_fraction=0.1, seed=6, write_images=False)
    with (tmp_path / "manifest.jsonl").open() as handle:
        for line in handle:
            row = json.loads(line)
            if row["kind"] == "production":
                assert row["answer"] is None


def test_truth_file_covers_every_task(tmp_path):
    records = build_dataset(
        tmp_path, count=150, gold_fraction=0.1, seed=7, write_images=False
    )
    truth = load_truth(tmp_path)
    assert set(truth) == {r.task_id for r in records}
    assert all(len(v) >= 1 for v in truth.values())


def test_dataset_yaml_class_order_is_stable(tmp_path):
    build_dataset(tmp_path, count=10, gold_fraction=0.2, seed=8, write_images=False)
    text = (tmp_path / "dataset.yaml").read_text()
    assert f"nc: {len(YOLO_CLASSES)}" in text
    assert "['circle', 'square', 'triangle', 'diamond', 'hexagon']" in text


def test_images_are_written_when_requested(tmp_path):
    records = build_dataset(
        tmp_path, count=5, gold_fraction=0.2, seed=9, write_images=True
    )
    for record in records:
        assert (tmp_path / "images" / record.image).exists()


@pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5])
def test_rejects_invalid_gold_fraction(tmp_path, bad):
    with pytest.raises(ValueError, match="gold_fraction"):
        build_dataset(tmp_path, count=10, gold_fraction=bad, write_images=False)

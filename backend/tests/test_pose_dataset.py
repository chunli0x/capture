"""Golden-set construction.

The separation between what the client may see and what stays server-side is
the whole basis of the accuracy claim, so it is asserted here rather than
assumed.
"""

from __future__ import annotations

import json

import pytest

from tapfarm.pose.dataset import (
    GOLDEN,
    LIVE,
    PRACTICE,
    QUALIFY,
    build_pose_dataset,
    load_objects,
    load_truth,
)
from tapfarm.pose.render import CANVAS
from tapfarm.pose.shapes import SHAPES


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("posedata")
    records = build_pose_dataset(out, seed=3, write_images=False)
    return out, records


def test_every_object_is_represented(built):
    _out, records = built
    assert {r.object_id for r in records} == set(SHAPES)


def test_each_object_has_five_to_eight_known_truth_images(built):
    """The brief asks for 2-3 objects at 5-8 images each."""
    _out, records = built
    known = [r for r in records if r.pool in (PRACTICE, QUALIFY, GOLDEN)]
    per_object: dict[str, int] = {}
    for record in known:
        per_object[record.object_id] = per_object.get(record.object_id, 0) + 1
    assert 2 <= len(per_object) <= 3 or len(per_object) == len(SHAPES)
    for object_id, count in per_object.items():
        assert 5 <= count <= 8, f"{object_id} has {count} known-truth images"


def test_manifest_never_carries_a_pose(built):
    """The manifest is client-facing; a pose in it would be the answer key."""
    out, _records = built
    with (out / "manifest.jsonl").open() as handle:
        for line in handle:
            row = json.loads(line)
            assert "pose" not in row
            assert "truth" not in row
            assert set(row) == {"task_id", "object_id", "pool", "image", "canvas"}


def test_live_truth_is_kept_out_of_the_scoring_truth_file(built):
    """Live work has no ground truth by definition.

    Its rendered pose is retained in a separate file for post-hoc measurement
    only; if it leaked into truth.jsonl the server would start reporting
    accuracy on labels it has no business scoring.
    """
    out, records = built
    truth = load_truth(out)
    live_ids = {r.task_id for r in records if r.pool == LIVE}
    known_ids = {r.task_id for r in records if r.pool != LIVE}

    assert live_ids, "expected some live tasks"
    assert live_ids.isdisjoint(truth)
    assert known_ids <= set(truth)


def test_live_truth_file_exists_for_post_hoc_analysis(built):
    out, records = built
    rows = [json.loads(l) for l in (out / "live_truth.jsonl").open() if l.strip()]
    assert {r["task_id"] for r in rows} == {
        r.task_id for r in records if r.pool == LIVE
    }


def test_objects_expose_the_sprite_contract(built):
    """`sprite_px_at_scale_1` is the one number renderer and client must share."""
    out, _records = built
    for entry in load_objects(out):
        assert set(entry) >= {
            "object_id", "label", "roll_feature", "sprite",
            "sprite_px_at_scale_1", "canvas",
        }
        assert entry["sprite_px_at_scale_1"] > 0
        assert entry["canvas"] == CANVAS
        assert entry["roll_feature"], "every object needs a visible roll feature"


def test_poses_stay_inside_the_frame(built):
    out, _records = built
    for pose in load_truth(out).values():
        assert 0 < pose["x"] < CANVAS
        assert 0 < pose["y"] < CANVAS
        assert -180.0 <= pose["roll"] <= 180.0
        assert 0.5 < pose["scale"] < 2.0


def test_task_ids_follow_the_spec_shape(built):
    _out, records = built
    for record in records:
        assert record.task_id == f"pose_{record.object_id}_{record.task_id.split('_')[-1]}"
        assert record.task_id.startswith("pose_")


def test_generation_is_deterministic(tmp_path):
    a = build_pose_dataset(tmp_path / "a", seed=11, write_images=False)
    b = build_pose_dataset(tmp_path / "b", seed=11, write_images=False)
    assert [x.task_id for x in a] == [x.task_id for x in b]
    assert load_truth(tmp_path / "a") == load_truth(tmp_path / "b")


def test_different_seeds_give_different_poses(tmp_path):
    build_pose_dataset(tmp_path / "a", seed=1, write_images=False)
    build_pose_dataset(tmp_path / "b", seed=2, write_images=False)
    assert load_truth(tmp_path / "a") != load_truth(tmp_path / "b")


def test_images_are_written_when_requested(tmp_path):
    records = build_pose_dataset(
        tmp_path, practice_per_object=1, qualify_per_object=1,
        golden_per_object=1, live_per_object=1, write_images=True,
    )
    for record in records:
        assert (tmp_path / "images" / record.image).exists()
    for object_id in SHAPES:
        assert (tmp_path / "sprites" / f"{object_id}.png").exists()


@pytest.mark.parametrize("bad", [-1, -5])
def test_negative_pool_sizes_are_rejected(tmp_path, bad):
    with pytest.raises(ValueError, match="must not be negative"):
        build_pose_dataset(tmp_path, live_per_object=bad, write_images=False)

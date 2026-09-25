"""Ghost-overlay HTTP surface.

The serving rules are unit tested in test_pose_serving.py; these assert they
survive the trip through the API, since that is the boundary a client - or a
motivated labeler - actually sees.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from solders.hash import Hash
from solders.keypair import Keypair

from tapfarm import main as main_mod
from tapfarm.config import Settings
from tapfarm.generator.dataset import build_dataset
from tapfarm.pose.dataset import build_pose_dataset, load_truth

REWARD = 10_000
QUALIFY_ITEMS = 6


@pytest.fixture
def client(monkeypatch, tmp_path):
    treasury = Keypair()
    treasury_path = tmp_path / "treasury.json"
    treasury_path.write_text(json.dumps(list(bytes(treasury))))

    grid = tmp_path / "grid"
    build_dataset(grid, count=60, gold_fraction=0.1, seed=2, write_images=False)
    pose_dir = tmp_path / "pose"
    build_pose_dataset(pose_dir, live_per_object=10, seed=4, write_images=False)

    test_settings = Settings(
        tap_mint=str(Keypair().pubkey()),
        tap_decimals=6,
        treasury_keypair_path=str(treasury_path),
        reward_per_task=REWARD,
        dataset_dir=str(grid),
        pose_dataset_dir=str(pose_dir),
        pose_qualify_items=QUALIFY_ITEMS,
    )
    monkeypatch.setattr("tapfarm.main.settings", lambda: test_settings)
    for factory in (main_mod.task_store, main_mod.pose_store, main_mod.referrals):
        factory.cache_clear()

    # Only the blockhash fetch is stubbed; transaction construction runs for real.
    class _StubRpc:
        async def get_latest_blockhash(self):
            class _Resp:
                class value:
                    blockhash = Hash.from_string("11111111111111111111111111111111")
            return _Resp()

    @asynccontextmanager
    async def _stub(_url, **_kwargs):
        yield _StubRpc()

    monkeypatch.setattr("tapfarm.main.AsyncClient", lambda url, **kw: _stub(url, **kw))

    yield TestClient(main_mod.app), load_truth(pose_dir)

    for factory in (main_mod.task_store, main_mod.pose_store, main_mod.referrals):
        factory.cache_clear()


def _who() -> str:
    return str(Keypair().pubkey())


def _run_blind(c, truth, who, *, correct: int):
    last = None
    for i in range(QUALIFY_ITEMS):
        task = c.get("/pose/task/next", params={"contributor": who, "mode": "qualify"}).json()
        answer = truth[task["task_id"]]
        pose = (
            dict(answer) if i < correct
            else {"x": answer["x"] + 300, "y": answer["y"] + 200,
                  "roll": answer["roll"] + 90, "scale": 1.0}
        )
        last = c.post(
            "/pose/submit",
            json={"contributor": who, "task_id": task["task_id"], "pose": pose},
        ).json()
    return last


def test_objects_expose_sprites_and_roll_features(client):
    c, _ = client
    objects = c.get("/pose/objects").json()
    assert objects
    for entry in objects:
        assert entry["sprite"].startswith("/pose/sprites/")
        assert entry["sprite_px_at_scale_1"] > 0
        assert entry["roll_feature"]


def test_practice_task_carries_truth_and_allows_snap(client):
    c, _ = client
    task = c.get("/pose/task/next", params={"contributor": _who(), "mode": "practice"}).json()
    assert task["allow_snap"] is True
    assert task["truth"] is not None


def test_qualify_task_is_blind_over_the_wire(client):
    """The response body must not contain the answer in any form."""
    c, _ = client
    who = _who()
    response = c.get("/pose/task/next", params={"contributor": who, "mode": "qualify"})
    body = response.json()
    assert body["truth"] is None
    assert body["allow_snap"] is False
    assert "roll" not in response.text.replace('"roll"', "")  # no stray pose values


def test_qualify_submission_returns_no_feedback(client):
    c, truth = client
    who = _who()
    task = c.get("/pose/task/next", params={"contributor": who, "mode": "qualify"}).json()
    body = c.post("/pose/submit", json={
        "contributor": who, "task_id": task["task_id"], "pose": truth[task["task_id"]],
    }).json()
    assert body["feedback"] is None
    assert body["qualification"] is None  # silent until the run completes


def test_practice_submission_returns_the_delta(client):
    c, truth = client
    who = _who()
    task = c.get("/pose/task/next", params={"contributor": who, "mode": "practice"}).json()
    answer = truth[task["task_id"]]
    body = c.post("/pose/submit", json={
        "contributor": who, "task_id": task["task_id"],
        "pose": {"x": answer["x"] + 3, "y": answer["y"] + 4,
                 "roll": answer["roll"] + 2, "scale": 1.0},
    }).json()
    assert body["feedback"]["error_px"] == pytest.approx(5.0, abs=0.1)
    assert body["feedback"]["error_deg"] == pytest.approx(2.0, abs=0.1)


def test_a_good_blind_run_qualifies(client):
    c, truth = client
    who = _who()
    body = _run_blind(c, truth, who, correct=QUALIFY_ITEMS)
    assert body["qualified"] is True
    assert body["qualification"]["qualified"] is True
    assert c.get(f"/pose/qualification/{who}").json()["qualified"] is True


def test_a_poor_blind_run_does_not_qualify(client):
    c, truth = client
    who = _who()
    body = _run_blind(c, truth, who, correct=1)
    assert body["qualified"] is False
    assert "not qualified" in body["qualification"]["summary"]


def test_paid_work_is_refused_before_qualifying(client):
    c, _ = client
    response = c.get("/pose/task/next", params={"contributor": _who(), "mode": "earn"})
    assert response.status_code == 403


def test_paid_work_pays_after_qualifying(client):
    c, truth = client
    who = _who()
    _run_blind(c, truth, who, correct=QUALIFY_ITEMS)
    task = c.get("/pose/task/next", params={"contributor": who, "mode": "earn"}).json()
    body = c.post("/pose/submit", json={
        "contributor": who, "task_id": task["task_id"],
        "pose": {"x": 100, "y": 100, "roll": 10, "scale": 1.0},
    }).json()
    assert body["reward"] == REWARD
    assert body["label"]["quality_signal"] in {"golden_item", "agreement"}


def test_pose_earnings_reach_the_existing_claim_path(client):
    """The brief says reuse the two-signer claim; pose money must land in it."""
    c, truth = client
    who = _who()
    _run_blind(c, truth, who, correct=QUALIFY_ITEMS)
    for _ in range(3):
        task = c.get("/pose/task/next", params={"contributor": who, "mode": "earn"}).json()
        c.post("/pose/submit", json={
            "contributor": who, "task_id": task["task_id"],
            "pose": {"x": 100, "y": 100, "roll": 10, "scale": 1.0},
        })

    summary = c.get(f"/contributor/{who}").json()
    assert summary["pose_balance"] == 3 * REWARD
    assert summary["total_claimable"] >= 3 * REWARD
    # Qualification stands in for tap-grid probation, so the claim is allowed.
    assert summary["claimable"] is True


def test_qualifying_on_pose_unlocks_claiming_without_tap_grid_history(client):
    c, truth = client
    who = _who()
    before = c.post("/claim/prepare", json={"contributor": who})
    assert before.status_code == 403

    _run_blind(c, truth, who, correct=QUALIFY_ITEMS)
    task = c.get("/pose/task/next", params={"contributor": who, "mode": "earn"}).json()
    c.post("/pose/submit", json={
        "contributor": who, "task_id": task["task_id"],
        "pose": {"x": 100, "y": 100, "roll": 10, "scale": 1.0},
    })
    after = c.post("/claim/prepare", json={"contributor": who})
    assert after.status_code == 200, after.text
    assert after.json()["pose_amount"] == REWARD


def test_replaying_a_pose_task_is_rejected(client):
    c, truth = client
    who = _who()
    task = c.get("/pose/task/next", params={"contributor": who, "mode": "practice"}).json()
    payload = {"contributor": who, "task_id": task["task_id"],
               "pose": {"x": 1, "y": 2, "roll": 3, "scale": 1.0}}
    assert c.post("/pose/submit", json=payload).status_code == 200
    assert c.post("/pose/submit", json=payload).status_code == 409


def test_malformed_pubkey_is_rejected(client):
    c, _ = client
    assert c.get("/pose/task/next", params={"contributor": "nope"}).status_code == 400


def test_unknown_mode_is_rejected(client):
    c, _ = client
    response = c.get("/pose/task/next", params={"contributor": _who(), "mode": "cheat"})
    assert response.status_code == 400


@pytest.mark.parametrize(
    "path",
    [
        "/pose/truth.jsonl",
        "/pose/live_truth.jsonl",
        "/pose/manifest.jsonl",
        "/pose/images/../truth.jsonl",
        "/pose/sprites/../truth.jsonl",
    ],
)
def test_pose_truth_is_never_served(client, path):
    """Only images and sprites are mounted.

    truth.jsonl beside them is the answer key for the blind set; serving it
    would make qualification worthless.
    """
    c, _ = client
    assert c.get(path).status_code == 404


def test_flag_endpoint_skips_a_practice_task(client):
    c, _ = client
    who = _who()
    task = c.get("/pose/task/next", params={"contributor": who, "mode": "practice"}).json()
    body = c.post("/pose/flag", json={
        "contributor": who, "task_id": task["task_id"], "reason": "no_object",
    })
    assert body.status_code == 200
    assert body.json()["reason"] == "no_object"


def test_flag_endpoint_refuses_the_blind_set(client):
    c, _ = client
    who = _who()
    task = c.get("/pose/task/next", params={"contributor": who, "mode": "qualify"}).json()
    response = c.post("/pose/flag", json={
        "contributor": who, "task_id": task["task_id"], "reason": "unclear",
    })
    assert response.status_code == 409
    assert "cannot be skipped" in response.json()["detail"]


def test_flag_endpoint_rejects_an_unknown_reason(client):
    c, _ = client
    who = _who()
    task = c.get("/pose/task/next", params={"contributor": who, "mode": "practice"}).json()
    response = c.post("/pose/flag", json={
        "contributor": who, "task_id": task["task_id"], "reason": "nah",
    })
    assert response.status_code == 400


@pytest.mark.parametrize(
    "raw_pose",
    [
        '{"x": NaN, "y": 1, "roll": 0, "scale": 1.0}',
        '{"x": 1, "y": Infinity, "roll": 0, "scale": 1.0}',
        '{"x": 1, "y": 1, "roll": -Infinity, "scale": 1.0}',
        '{"x": 1, "y": 1, "roll": 0, "scale": NaN}',
        '{"x": 1e9, "y": 1, "roll": 0, "scale": 1.0}',
        '{"x": 1, "y": 1, "roll": 0, "scale": 0.0}',
        '{"x": 1, "y": 1, "roll": 0, "scale": -1.0}',
    ],
    ids=["nan-x", "inf-y", "-inf-roll", "nan-scale", "huge-x", "zero-scale", "neg-scale"],
)
def test_nonfinite_or_out_of_range_poses_are_rejected(client, raw_pose):
    """NaN is the dangerous one: it compares false against every threshold.

    Left unchecked it does not raise - it silently scores as "outside
    tolerance" while looking like an ordinary answer, so a malformed client
    would quietly fail qualification with no explanation.

    Sent as a raw body rather than through `json=`, because httpx refuses to
    serialise NaN at all - so this is what a hand-rolled client can actually put
    on the wire.

    These used to return 500. Python's JSON parser accepts NaN on the way in,
    pydantic rejects it and echoes the offending value into the error detail,
    and the encoder then refuses to serialise that detail - turning a clean 422
    into a server crash. A validation handler now scrubs non-finite values out
    of the error body.
    """
    c, _ = client
    who = _who()
    task = c.get("/pose/task/next", params={"contributor": who, "mode": "practice"}).json()
    body = (
        '{"contributor": "%s", "task_id": "%s", "pose": %s}'
        % (who, task["task_id"], raw_pose)
    )
    response = c.post(
        "/pose/submit", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422, response.text


def test_a_valid_pose_at_the_bounds_is_accepted(client):
    c, _ = client
    who = _who()
    task = c.get("/pose/task/next", params={"contributor": who, "mode": "practice"}).json()
    response = c.post("/pose/submit", json={
        "contributor": who, "task_id": task["task_id"],
        "pose": {"x": 0.0, "y": 0.0, "roll": -180.0, "scale": 0.5},
    })
    assert response.status_code == 200

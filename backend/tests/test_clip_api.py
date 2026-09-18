"""Clip-judgment HTTP surface.

The serving rules are unit tested in test_clip.py; these assert they survive
the trip through the API. That boundary is the point of these tests rather
than a formality: the campaign was written, tested and merged while being
unreachable over HTTP, so "the rules are right" and "the campaign is live" are
demonstrably different claims.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from solders.keypair import Keypair

from tapfarm import main as main_mod
from tapfarm.clip.dataset import SourceClip, build_clip_dataset, load_truth
from tapfarm.config import Settings
from tapfarm.generator.dataset import build_dataset

REWARD = 10_000
QUALIFY_ITEMS = 12
QUESTION = "Is the person holding a phone, or a wallet?"
CHOICES = ["phone", "wallet"]


def _clips(count: int) -> list[SourceClip]:
    return [
        SourceClip(
            clip=f"{i:03d}.mp4",
            question=QUESTION,
            choices=list(CHOICES),
            answer=CHOICES[i % 2],
        )
        for i in range(count)
    ]


@pytest.fixture
def env(monkeypatch, tmp_path):
    treasury_path = tmp_path / "treasury.json"
    treasury_path.write_text(json.dumps(list(bytes(Keypair()))))

    grid = tmp_path / "grid"
    build_dataset(grid, count=60, gold_fraction=0.1, seed=2, write_images=False)
    clip_dir = tmp_path / "clip"
    build_clip_dataset(
        clip_dir, _clips(60), practice=8, qualify=12, golden=10, seed=11
    )

    test_settings = Settings(
        tap_mint=str(Keypair().pubkey()),
        tap_decimals=6,
        treasury_keypair_path=str(treasury_path),
        reward_per_task=REWARD,
        dataset_dir=str(grid),
        clip_dataset_dir=str(clip_dir),
        clip_qualify_items=QUALIFY_ITEMS,
        clip_pass_fraction=0.85,
        clip_retry_cooldown_seconds=0.0,
    )
    monkeypatch.setattr("tapfarm.main.settings", lambda: test_settings)
    for factory in (
        main_mod.task_store,
        main_mod.pose_store,
        main_mod.clip_store,
        main_mod.referrals,
    ):
        factory.cache_clear()

    with TestClient(main_mod.app) as client:
        yield client, load_truth(clip_dir)


@pytest.fixture
def client(env):
    return env[0]


@pytest.fixture
def truth(env):
    return env[1]


def _who() -> str:
    return str(Keypair().pubkey())


def _run_blind(client, truth, contributor, wrong=0):
    result = None
    for i in range(QUALIFY_ITEMS):
        task = client.get(
            "/clip/task/next", params={"contributor": contributor, "mode": "qualify"}
        ).json()
        answer = truth[task["task_id"]]
        if i < wrong:
            answer = next(c for c in CHOICES if c != answer)
        result = client.post(
            "/clip/submit",
            json={
                "contributor": contributor,
                "task_id": task["task_id"],
                "choice": answer,
            },
        ).json()
    return result


class TestRoutesExist:
    def test_a_practice_clip_is_served(self, client):
        who = _who()
        response = client.get(
            "/clip/task/next", params={"contributor": who, "mode": "practice"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["question"] == QUESTION
        assert body["choices"] == CHOICES
        assert body["clip_url"].startswith("/clips/")
        assert body["can_flag"] is True
        assert body["reward"] == 0

    def test_practice_returns_the_answer_after_submitting(self, client, truth):
        who = _who()
        task = client.get(
            "/clip/task/next", params={"contributor": who, "mode": "practice"}
        ).json()
        body = client.post(
            "/clip/submit",
            json={
                "contributor": who,
                "task_id": task["task_id"],
                "choice": truth[task["task_id"]],
            },
        ).json()
        assert body["correct"] is True
        assert body["expected"] == truth[task["task_id"]]

    def test_an_invalid_pubkey_is_rejected(self, client):
        response = client.get(
            "/clip/task/next", params={"contributor": "not-a-key", "mode": "practice"}
        )
        assert response.status_code == 400

    def test_an_unknown_mode_is_a_400(self, client):
        response = client.get(
            "/clip/task/next", params={"contributor": _who(), "mode": "freestyle"}
        )
        assert response.status_code == 400

    def test_paid_work_before_qualifying_is_a_403(self, client):
        response = client.get(
            "/clip/task/next", params={"contributor": _who(), "mode": "earn"}
        )
        assert response.status_code == 403


class TestBlindOverHttp:
    def test_the_gate_stays_blind_through_the_api(self, client, truth):
        """The API is where a motivated labeler would look for the leak."""
        who = _who()
        for _ in range(5):
            task = client.get(
                "/clip/task/next", params={"contributor": who, "mode": "qualify"}
            ).json()
            assert task["can_flag"] is False
            body = client.post(
                "/clip/submit",
                json={"contributor": who, "task_id": task["task_id"], "choice": "phone"},
            ).json()
            assert body["correct"] is None
            assert body["expected"] is None
            assert body["qualification"] is None

    def test_passing_reports_the_chance_floor(self, client, truth):
        who = _who()
        result = _run_blind(client, truth, who)
        qualification = result["qualification"]
        assert qualification["passed"] is True
        assert qualification["correct"] == 12
        assert qualification["chance_pass"] == pytest.approx(0.0031738, abs=1e-6)

    def test_flagging_during_qualification_is_a_409(self, client):
        who = _who()
        task = client.get(
            "/clip/task/next", params={"contributor": who, "mode": "qualify"}
        ).json()
        response = client.post(
            "/clip/flag", json={"contributor": who, "task_id": task["task_id"], "choice": ""}
        )
        assert response.status_code == 409

    def test_an_invalid_choice_is_a_400(self, client):
        who = _who()
        task = client.get(
            "/clip/task/next", params={"contributor": who, "mode": "practice"}
        ).json()
        response = client.post(
            "/clip/submit",
            json={"contributor": who, "task_id": task["task_id"], "choice": "banana"},
        )
        assert response.status_code == 400

    def test_double_submit_is_a_409(self, client, truth):
        who = _who()
        task = client.get(
            "/clip/task/next", params={"contributor": who, "mode": "practice"}
        ).json()
        payload = {
            "contributor": who,
            "task_id": task["task_id"],
            "choice": truth[task["task_id"]],
        }
        assert client.post("/clip/submit", json=payload).status_code == 200
        assert client.post("/clip/submit", json=payload).status_code == 409


class TestRetryOverHttp:
    def test_failing_then_retrying_and_passing(self, client, truth):
        who = _who()
        failed = _run_blind(client, truth, who, wrong=3)
        assert failed["qualification"]["passed"] is False
        assert failed["qualification"]["retry_available"] is True

        # The gate is locked until the retry is requested.
        assert (
            client.get(
                "/clip/task/next", params={"contributor": who, "mode": "qualify"}
            ).status_code
            == 403
        )

        retry = client.post("/clip/qualification/retry", json={"contributor": who})
        assert retry.status_code == 200
        assert retry.json()["graded"] == 0

        passed = _run_blind(client, truth, who)
        assert passed["qualification"]["passed"] is True

    def test_a_second_retry_is_a_409(self, client, truth):
        who = _who()
        _run_blind(client, truth, who, wrong=3)
        assert (
            client.post(
                "/clip/qualification/retry", json={"contributor": who}
            ).status_code
            == 200
        )
        _run_blind(client, truth, who, wrong=3)
        response = client.post("/clip/qualification/retry", json={"contributor": who})
        assert response.status_code == 409
        assert "has been used" in response.json()["detail"]

    def test_retrying_without_a_failure_is_a_409(self, client):
        response = client.post("/clip/qualification/retry", json={"contributor": _who()})
        assert response.status_code == 409

    def test_the_qualification_endpoint_reports_progress(self, client, truth):
        who = _who()
        body = client.get(f"/clip/qualification/{who}").json()
        assert body["graded"] == 0 and body["passed"] is False
        _run_blind(client, truth, who)
        body = client.get(f"/clip/qualification/{who}").json()
        assert body["passed"] is True and body["correct"] == 12


class TestEarningAndClaim:
    def _qualify(self, client, truth, who):
        _run_blind(client, truth, who)

    def test_paid_work_credits_the_contributor_summary(self, client, truth):
        who = _who()
        self._qualify(client, truth, who)
        task = client.get(
            "/clip/task/next", params={"contributor": who, "mode": "earn"}
        ).json()
        assert task["reward"] == REWARD
        body = client.post(
            "/clip/submit",
            json={"contributor": who, "task_id": task["task_id"], "choice": "phone"},
        ).json()
        assert body["reward"] == REWARD

        summary = client.get(f"/contributor/{who}").json()
        assert summary["clip_balance"] == REWARD
        assert summary["clip_qualified"] is True
        assert summary["total_claimable"] >= REWARD

    def test_paid_work_never_reveals_which_items_are_graded(self, client, truth):
        who = _who()
        self._qualify(client, truth, who)
        signals = set()
        for _ in range(20):
            task = client.get(
                "/clip/task/next", params={"contributor": who, "mode": "earn"}
            ).json()
            body = client.post(
                "/clip/submit",
                json={"contributor": who, "task_id": task["task_id"], "choice": "phone"},
            ).json()
            assert body["correct"] is None and body["expected"] is None
            signals.add(body["quality_signal"])
        assert signals == {"golden_item", "agreement"}

    def test_flagging_paid_work_pays_nothing(self, client, truth):
        who = _who()
        self._qualify(client, truth, who)
        task = client.get(
            "/clip/task/next", params={"contributor": who, "mode": "earn"}
        ).json()
        body = client.post(
            "/clip/flag",
            json={"contributor": who, "task_id": task["task_id"], "choice": ""},
        ).json()
        assert body["flagged"] is True and body["reward"] == 0

    def test_clip_qualification_alone_makes_a_contributor_claimable(
        self, client, truth
    ):
        """A campaign that can pay has to appear in the claim gate.

        Otherwise clip earnings would be credited and then be unspendable, or
        /contributor and /claim/prepare would disagree about whether they are.
        """
        who = _who()
        before = client.get(f"/contributor/{who}").json()
        assert before["claimable"] is False
        assert "clip-judgment" in before["reason"]

        self._qualify(client, truth, who)
        task = client.get(
            "/clip/task/next", params={"contributor": who, "mode": "earn"}
        ).json()
        client.post(
            "/clip/submit",
            json={"contributor": who, "task_id": task["task_id"], "choice": "phone"},
        )

        after = client.get(f"/contributor/{who}").json()
        assert after["claimable"] is True
        assert after["reason"] == "qualified on the clip-judgment blind set"

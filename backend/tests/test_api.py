"""API wiring, with devnet stubbed out.

This container can reach a validator, but these tests should stay offline and
fast, so only the blockhash fetch is patched. Everything else - task serving,
grading, eligibility, transaction construction, encoding - runs for real.
"""

from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from solders.hash import Hash
from solders.keypair import Keypair
from solders.transaction import Transaction

from tapfarm import main as main_mod
from tapfarm.config import Settings
from tapfarm.generator.dataset import build_dataset
from tapfarm.scoring import MIN_GOLD_SAMPLES

STUB_BLOCKHASH = Hash.from_string("11111111111111111111111111111111")
REWARD = 1000


@pytest.fixture
def client(monkeypatch, tmp_path):
    treasury_kp = Keypair()
    treasury_path = tmp_path / "treasury.json"
    treasury_path.write_text(json.dumps(list(bytes(treasury_kp))))
    mint = Keypair().pubkey()

    dataset = tmp_path / "data"
    build_dataset(dataset, count=300, gold_fraction=0.1, seed=11, write_images=False)

    test_settings = Settings(
        tap_mint=str(mint),
        tap_decimals=6,
        treasury_keypair_path=str(treasury_path),
        reward_per_task=REWARD,
        dataset_dir=str(dataset),
    )
    monkeypatch.setattr("tapfarm.main.settings", lambda: test_settings)
    main_mod.task_store.cache_clear()
    main_mod.referrals.cache_clear()
    main_mod.stake_reader.cache_clear()

    # Referral eligibility is an on-chain read; drive it from the test instead.
    eligible: set[str] = set()

    class _FakeReader:
        async def is_referral_eligible(self, contributor, **_kwargs):
            return contributor in eligible

    monkeypatch.setattr("tapfarm.main.stake_reader", lambda: _FakeReader())

    class _StubValue:
        blockhash = STUB_BLOCKHASH

    class _StubResp:
        value = _StubValue()

    class _StubRpc:
        async def get_latest_blockhash(self):
            return _StubResp()

    @asynccontextmanager
    async def _stub_client(_url):
        yield _StubRpc()

    # Accept **kwargs so the stub keeps working as the real call site gains
    # options (it passes commitment=Confirmed).
    monkeypatch.setattr(
        "tapfarm.main.AsyncClient", lambda url, **_kwargs: _stub_client(url)
    )

    yield TestClient(main_mod.app), treasury_kp, mint, eligible
    # stake_reader is monkeypatched to a plain function by now, so only the
    # real lru_cache-wrapped factories can be cleared here.
    main_mod.task_store.cache_clear()
    main_mod.referrals.cache_clear()


def _force_gold(is_gold: bool) -> None:
    main_mod.task_store().gold_rate_for = lambda _tier: 1.0 if is_gold else 0.0


def _answer(task_id: str) -> list[int]:
    return main_mod.task_store().withheld_truth(task_id)


def _solve_correctly(c: TestClient, who: str, rounds: int) -> dict:
    body: dict = {}
    for _ in range(rounds):
        task = c.get("/task/next", params={"contributor": who}).json()
        body = c.post(
            "/task/submit",
            json={"contributor": who, "task_id": task["task_id"],
                  "cells": _answer(task["task_id"])},
        ).json()
    return body


def test_health_reports_configuration(client):
    c, _, _, _ = client
    body = c.get("/health").json()
    assert body["ok"] is True
    assert body["mint_configured"] is True
    assert body["treasury_present"] is True
    assert body["dataset_present"] is True


def test_campaigns_expose_live_and_queued(client):
    c, _, _, _ = client
    statuses = {x["id"]: x["status"] for x in c.get("/campaigns").json()}
    assert statuses == {"img-grid-v1": "live", "robotics-bbox-v1": "queued"}


def test_served_task_does_not_leak_the_answer(client):
    c, _, _, _ = client
    who = str(Keypair().pubkey())
    body = c.get("/task/next", params={"contributor": who}).json()
    assert set(body) == {
        "task_id", "campaign_id", "prompt", "grid", "image_url", "reward",
    }


def test_submitting_an_unserved_task_is_rejected(client):
    c, _, _, _ = client
    who = str(Keypair().pubkey())
    resp = c.post(
        "/task/submit",
        json={"contributor": who, "task_id": "tapgrid-000001", "cells": [0]},
    )
    assert resp.status_code == 409


def test_out_of_range_cell_is_rejected(client):
    c, _, _, _ = client
    who = str(Keypair().pubkey())
    task = c.get("/task/next", params={"contributor": who}).json()
    resp = c.post(
        "/task/submit",
        json={"contributor": who, "task_id": task["task_id"], "cells": [42]},
    )
    assert resp.status_code == 400


def test_rejects_malformed_pubkey(client):
    c, _, _, _ = client
    assert c.get("/task/next", params={"contributor": "nope"}).status_code == 400


def test_correct_gold_answers_accrue_balance(client):
    c, _, _, _ = client
    _force_gold(True)
    who = str(Keypair().pubkey())
    body = _solve_correctly(c, who, 3)
    assert body["graded"] is True and body["correct"] is True
    assert body["balance"] == 3 * REWARD


def test_claim_is_refused_before_probation(client):
    """The accuracy gate is worthless if the endpoint behind it pays anyone."""
    c, _, _, _ = client
    _force_gold(True)
    who = str(Keypair().pubkey())
    body = _solve_correctly(c, who, MIN_GOLD_SAMPLES - 1)
    assert body["balance"] > 0 and body["claimable"] is False

    resp = c.post("/claim/prepare", json={"contributor": who})
    assert resp.status_code == 403
    assert "verification tasks" in resp.json()["detail"]


def test_claim_is_refused_for_poor_accuracy(client):
    c, _, _, _ = client
    _force_gold(True)
    who = str(Keypair().pubkey())
    for _ in range(MIN_GOLD_SAMPLES * 2):
        task = c.get("/task/next", params={"contributor": who}).json()
        c.post(
            "/task/submit",
            json={"contributor": who, "task_id": task["task_id"], "cells": []},
        )
    resp = c.post("/claim/prepare", json={"contributor": who})
    assert resp.status_code == 403
    assert "below" in resp.json()["detail"]


def test_eligible_claim_returns_a_contributor_paid_transaction(client):
    c, treasury_kp, mint, _ = client
    _force_gold(True)
    contributor_kp = Keypair()
    who = str(contributor_kp.pubkey())

    body = _solve_correctly(c, who, MIN_GOLD_SAMPLES)
    assert body["claimable"] is True

    resp = c.post("/claim/prepare", json={"contributor": who})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["amount"] == MIN_GOLD_SAMPLES * REWARD
    assert payload["fee_payer"] == who
    assert payload["mint"] == str(mint)

    tx = Transaction.from_bytes(base64.b64decode(payload["transaction"]))
    assert tx.message.account_keys[0] == contributor_kp.pubkey()
    assert tx.message.header.num_required_signatures == 2
    assert set(tx.message.signer_keys()) == {
        contributor_kp.pubkey(),
        treasury_kp.pubkey(),
    }
    with pytest.raises(Exception):
        tx.verify()
    tx.partial_sign([contributor_kp], tx.message.recent_blockhash)
    tx.verify()


def test_claim_zeroes_the_balance(client):
    c, _, _, _ = client
    _force_gold(True)
    who = str(Keypair().pubkey())
    _solve_correctly(c, who, MIN_GOLD_SAMPLES)
    c.post("/claim/prepare", json={"contributor": who})

    assert c.get(f"/contributor/{who}").json()["balance"] == 0
    assert c.post("/claim/prepare", json={"contributor": who}).status_code == 409


@pytest.mark.parametrize(
    "path",
    [
        "/truth.jsonl",
        "/manifest.jsonl",
        "/dataset.yaml",
        "/images/../truth.jsonl",
        "/images/../../treasury.json",
    ],
)
def test_dataset_internals_are_not_served(client, tmp_path, path):
    """Only /images is mounted.

    truth.jsonl is the file that makes grading possible and would also let
    anyone auto-solve every task, so serving it would quietly void the whole
    verification scheme. These files exist on disk - a 404 here means not
    served, not absent.
    """
    c, _, _, _ = client
    assert (tmp_path / "data" / "manifest.jsonl").exists()
    assert c.get(path).status_code == 404


def test_contributor_summary_tracks_progress(client):
    c, _, _, _ = client
    _force_gold(True)
    who = str(Keypair().pubkey())
    _solve_correctly(c, who, 4)
    body = c.get(f"/contributor/{who}").json()
    assert body["solved"] == 4
    assert body["gold_samples"] == 4
    assert body["accuracy"] == 1.0
    assert body["claimable"] is False  # still on probation


# -- referrals -----------------------------------------------------------------

def _register(c: TestClient, referrer: str, referee: str):
    return c.post(
        "/referral/register", json={"referrer": referrer, "referee": referee}
    )


def test_referral_registration_and_summary(client):
    c, _, _, _ = client
    alice, bob = str(Keypair().pubkey()), str(Keypair().pubkey())

    body = _register(c, alice, bob).json()
    assert body["referees"] == 1
    assert body["eligible"] is False  # nothing staked

    assert c.get(f"/referral/{bob}").json()["referrer"] == alice


def test_self_referral_is_refused(client):
    c, _, _, _ = client
    alice = str(Keypair().pubkey())
    assert _register(c, alice, alice).status_code == 409


def test_mutual_referral_is_refused(client):
    c, _, _, _ = client
    alice, bob = str(Keypair().pubkey()), str(Keypair().pubkey())
    assert _register(c, alice, bob).status_code == 200
    assert _register(c, bob, alice).status_code == 409


def test_referrer_earns_only_when_eligible(client):
    c, _, _, eligible = client
    _force_gold(True)
    alice, bob = str(Keypair().pubkey()), str(Keypair().pubkey())
    _register(c, alice, bob)

    _solve_correctly(c, bob, 3)
    assert c.get(f"/referral/{alice}").json()["unclaimed"] == 0

    eligible.add(alice)
    _solve_correctly(c, bob, 3)
    assert c.get(f"/referral/{alice}").json()["unclaimed"] > 0


def test_referral_does_not_reduce_the_referees_earnings(client):
    """The invariant the whole design rests on."""
    c, _, _, eligible = client
    _force_gold(True)
    alice, bob, solo = (str(Keypair().pubkey()) for _ in range(3))
    eligible.add(alice)
    _register(c, alice, bob)

    referred = _solve_correctly(c, bob, 5)
    unreferred = _solve_correctly(c, solo, 5)
    assert referred["balance"] == unreferred["balance"]


def test_a_failed_task_pays_no_referral(client):
    c, _, _, eligible = client
    _force_gold(True)
    alice, bob = str(Keypair().pubkey()), str(Keypair().pubkey())
    eligible.add(alice)
    _register(c, alice, bob)

    for _ in range(4):
        task = c.get("/task/next", params={"contributor": bob}).json()
        c.post("/task/submit", json={"contributor": bob, "task_id": task["task_id"], "cells": []})

    assert c.get(f"/referral/{alice}").json()["unclaimed"] == 0


def test_a_pure_recruiter_cannot_cash_out(client):
    """No pure-recruiter accounts: collecting requires being a contributor.

    This is most of what stops the programme looking like a pyramid from the
    inside - recruiting alone never pays out.
    """
    c, _, _, eligible = client
    _force_gold(True)
    alice, bob = str(Keypair().pubkey()), str(Keypair().pubkey())
    eligible.add(alice)
    _register(c, alice, bob)

    _solve_correctly(c, bob, MIN_GOLD_SAMPLES)
    assert c.get(f"/contributor/{alice}").json()["referral_unclaimed"] > 0

    resp = c.post("/claim/prepare", json={"contributor": alice})
    assert resp.status_code == 403
    assert "verification tasks" in resp.json()["detail"]


def test_claim_pays_task_and_referral_balances_together(client):
    c, _, _, eligible = client
    _force_gold(True)
    alice, bob = str(Keypair().pubkey()), str(Keypair().pubkey())
    eligible.add(alice)
    _register(c, alice, bob)

    _solve_correctly(c, bob, 5)              # alice accrues referral
    _solve_correctly(c, alice, MIN_GOLD_SAMPLES)  # alice clears probation

    summary = c.get(f"/contributor/{alice}").json()
    assert summary["referral_unclaimed"] > 0
    assert summary["total_claimable"] == summary["balance"] + summary["referral_unclaimed"]

    payload = c.post("/claim/prepare", json={"contributor": alice}).json()
    assert payload["referral_amount"] == summary["referral_unclaimed"]
    assert payload["task_amount"] == summary["balance"]
    assert payload["amount"] == summary["total_claimable"]

    after = c.get(f"/contributor/{alice}").json()
    assert after["total_claimable"] == 0
    assert after["referral_unclaimed"] == 0


def test_referral_chain_pays_only_the_direct_referrer(client):
    c, _, _, eligible = client
    _force_gold(True)
    alice, bob, carol = (str(Keypair().pubkey()) for _ in range(3))
    eligible.update({alice, bob})
    _register(c, alice, bob)
    _register(c, bob, carol)

    _solve_correctly(c, carol, 4)

    assert c.get(f"/referral/{bob}").json()["unclaimed"] > 0
    assert c.get(f"/referral/{alice}").json()["unclaimed"] == 0

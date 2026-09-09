"""End-to-end claim against a real ledger.

Every other test here is offline. This one submits the claim transaction to a
validator and checks that TAP actually moves, which is the only way to know the
runtime accepts it rather than that it is merely well-formed.

Skipped unless a validator is reachable, so the default suite stays fast and
offline. To run it:

    solana-test-validator --reset --quiet &
    CLUSTER=localhost ./scripts/bootstrap_devnet.sh
    cd backend && TAPFARM_E2E=1 TAPFARM_RPC_URL=http://localhost:8899 \
      TAPFARM_SKR_MINT=<mint from bootstrap> pytest tests/test_e2e_claim.py -v

A local validator is preferable to devnet: no faucet rate limit, and devnet
airdrops fail routinely from shared or cloud IPs.

The contributor's signature is applied here with a local keypair, standing in
for what the wallet does on the phone over MWA. That is the only simulated
step.
"""

from __future__ import annotations

import base64
import os
import pathlib

import pytest
from fastapi.testclient import TestClient
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from spl.token.instructions import get_associated_token_address

from tapfarm import main as main_mod
from tapfarm.config import Settings
from tapfarm.generator.dataset import build_dataset

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("TAPFARM_E2E") != "1",
        reason="set TAPFARM_E2E=1 with a reachable validator to run",
    ),
    pytest.mark.asyncio,
]

REWARD_PER_TASK = 1000
# Must clear MIN_GOLD_SAMPLES probation for the claim to be allowed.
TASKS = 12
# Enough for the fee plus rent on the contributor's new TAP token account.
CONTRIBUTOR_LAMPORTS = 1_000_000_000


@pytest.fixture
def live_settings(monkeypatch, tmp_path) -> Settings:
    mint = os.environ.get("TAPFARM_TAP_MINT")
    if not mint:
        pytest.skip("TAPFARM_TAP_MINT not set; run scripts/bootstrap_devnet.sh")

    treasury = pathlib.Path(__file__).parent.parent / "treasury.json"
    if not treasury.exists():
        pytest.skip(f"no treasury at {treasury}; run scripts/bootstrap_devnet.sh")

    dataset = tmp_path / "data"
    build_dataset(dataset, count=200, gold_fraction=0.1, seed=21, write_images=False)

    settings = Settings(
        rpc_url=os.environ.get("TAPFARM_RPC_URL", "http://localhost:8899"),
        tap_mint=mint,
        tap_decimals=6,
        treasury_keypair_path=str(treasury),
        reward_per_task=REWARD_PER_TASK,
        dataset_dir=str(dataset),
    )
    monkeypatch.setattr("tapfarm.main.settings", lambda: settings)
    main_mod.task_store.cache_clear()
    return settings


async def test_claim_moves_tap_on_chain(live_settings):
    contributor = Keypair()
    mint = Pubkey.from_string(live_settings.tap_mint)
    client = TestClient(main_mod.app)

    # commitment=Confirmed matters: send_raw_transaction runs preflight against
    # the client's commitment, and the default (finalized) lags far enough on a
    # fresh validator that a just-airdropped account looks nonexistent -
    # surfacing as a misleading "no record of a prior credit" error.
    async with AsyncClient(live_settings.rpc_url, commitment=Confirmed) as rpc:
        airdrop = await rpc.request_airdrop(contributor.pubkey(), CONTRIBUTOR_LAMPORTS)
        await rpc.confirm_transaction(airdrop.value, commitment=Confirmed)

        who = str(contributor.pubkey())
        # Earn the balance the way the app does: solve gold tasks correctly
        # until past probation.
        main_mod.task_store().gold_rate_for = lambda _tier: 1.0
        for _ in range(TASKS):
            task = client.get("/task/next", params={"contributor": who}).json()
            client.post(
                "/task/submit",
                json={
                    "contributor": who,
                    "task_id": task["task_id"],
                    "cells": main_mod.task_store().withheld_truth(task["task_id"]),
                },
            )

        prepared = client.post("/claim/prepare", json={"contributor": who})
        assert prepared.status_code == 200, prepared.text
        body = prepared.json()
        assert body["amount"] == TASKS * REWARD_PER_TASK
        assert body["fee_payer"] == who

        tx = Transaction.from_bytes(base64.b64decode(body["transaction"]))

        # The backend must have left our signature slot open.
        assert tx.message.account_keys[0] == contributor.pubkey()
        with pytest.raises(Exception):
            tx.verify()

        # What the wallet does over MWA.
        tx.partial_sign([contributor], tx.message.recent_blockhash)
        tx.verify()

        sent = await rpc.send_raw_transaction(bytes(tx))
        await rpc.confirm_transaction(sent.value, commitment=Confirmed)

        ata = get_associated_token_address(contributor.pubkey(), mint)
        balance = await rpc.get_token_account_balance(ata, commitment=Confirmed)
        assert int(balance.value.amount) == TASKS * REWARD_PER_TASK
        assert balance.value.decimals == live_settings.tap_decimals

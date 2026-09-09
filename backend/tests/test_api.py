"""End-to-end wiring test for the claim path, with devnet stubbed out.

This container has no route to api.devnet.solana.com, so the blockhash fetch is
patched. Everything else - config, treasury loading, tx construction, base64
encoding, the ledger debit - runs for real.
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
from tapfarm.config import Settings, settings

STUB_BLOCKHASH = Hash.from_string("11111111111111111111111111111111")


@pytest.fixture
def treasury_file(tmp_path):
    kp = Keypair()
    path = tmp_path / "treasury.json"
    path.write_text(json.dumps(list(bytes(kp))))
    return kp, path


@pytest.fixture
def client(monkeypatch, treasury_file):
    kp, path = treasury_file
    mint = Keypair().pubkey()

    settings.cache_clear()
    test_settings = Settings(
        skr_mint=str(mint),
        skr_decimals=6,
        treasury_keypair_path=str(path),
        reward_per_task=1000,
    )
    monkeypatch.setattr("tapfarm.main.settings", lambda: test_settings)

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

    main_mod._EARNED.clear()
    yield TestClient(main_mod.app), kp, mint
    settings.cache_clear()


def test_health_reports_configuration(client):
    c, _, _ = client
    body = c.get("/health").json()
    assert body["ok"] is True
    assert body["mint_configured"] is True
    assert body["treasury_present"] is True


def test_campaigns_expose_live_and_queued(client):
    c, _, _ = client
    body = c.get("/campaigns").json()
    ids = {x["id"] for x in body}
    assert ids == {"img-grid-v1", "robotics-bbox-v1"}
    statuses = {x["id"]: x["status"] for x in body}
    assert statuses["img-grid-v1"] == "live"
    assert statuses["robotics-bbox-v1"] == "queued"


def test_claim_with_nothing_earned_is_rejected(client):
    c, _, _ = client
    who = str(Keypair().pubkey())
    assert c.post("/claim/prepare", json={"contributor": who}).status_code == 409


def test_rejects_malformed_pubkey(client):
    c, _, _ = client
    assert c.post("/spike/grant", json={"contributor": "not-a-key"}).status_code == 400


def test_claim_returns_contributor_paid_transaction(client):
    c, treasury_kp, mint = client
    contributor_kp = Keypair()
    who = str(contributor_kp.pubkey())

    c.post("/spike/grant", json={"contributor": who, "tasks": 6})
    assert c.get(f"/contributor/{who}").json()["earned"] == 6000

    resp = c.post("/claim/prepare", json={"contributor": who})
    assert resp.status_code == 200
    body = resp.json()

    assert body["amount"] == 6000
    assert body["ui_amount"] == pytest.approx(0.006)
    assert body["fee_payer"] == who
    assert body["mint"] == str(mint)

    tx = Transaction.from_bytes(base64.b64decode(body["transaction"]))
    # The contract the app depends on: user is fee payer, two signers, and the
    # treasury has already signed.
    assert tx.message.account_keys[0] == contributor_kp.pubkey()
    assert tx.message.header.num_required_signatures == 2
    assert set(tx.message.signer_keys()) == {
        contributor_kp.pubkey(),
        treasury_kp.pubkey(),
    }

    # Incomplete until the wallet signs...
    with pytest.raises(Exception):
        tx.verify()
    # ...and valid once it does.
    tx.partial_sign([contributor_kp], tx.message.recent_blockhash)
    tx.verify()


def test_claim_zeroes_the_balance(client):
    c, _, _ = client
    who = str(Keypair().pubkey())
    c.post("/spike/grant", json={"contributor": who, "tasks": 3})
    c.post("/claim/prepare", json={"contributor": who})
    assert c.get(f"/contributor/{who}").json()["earned"] == 0
    assert c.post("/claim/prepare", json={"contributor": who}).status_code == 409

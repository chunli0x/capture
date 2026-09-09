"""Tap Farm API - spike scope.

Endpoints exist to prove the claim path end to end from the phone. Task serving
and gold-standard verification land in week 2; the campaign shape is already
here because it drives the schema.
"""

from __future__ import annotations

import json
import pathlib

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from tapfarm.claim_tx import (
    build_claim_transaction,
    serialize_for_wallet,
    treasury_sign,
)
from tapfarm.config import settings

app = FastAPI(title="Tap Farm", version="0.1.0-spike")

# In-memory contributor ledger for the spike. SQLite lands with task serving.
_EARNED: dict[str, int] = {}


def _treasury() -> Keypair:
    path = pathlib.Path(settings().treasury_keypair_path)
    if not path.exists():
        raise HTTPException(
            503, f"treasury keypair missing at {path}; run scripts/bootstrap_devnet.sh"
        )
    return Keypair.from_bytes(bytes(json.loads(path.read_text())))


def _mint() -> Pubkey:
    raw = settings().skr_mint
    if not raw:
        raise HTTPException(503, "TAPFARM_SKR_MINT unset; run scripts/bootstrap_devnet.sh")
    return Pubkey.from_string(raw)


def _parse_pubkey(value: str) -> Pubkey:
    try:
        return Pubkey.from_string(value)
    except Exception as exc:
        raise HTTPException(400, f"not a valid pubkey: {value}") from exc


class CampaignOut(BaseModel):
    id: str
    title: str
    task_type: str
    reward_per_task: int
    status: str
    description: str


CAMPAIGNS = [
    CampaignOut(
        id="img-grid-v1",
        title="Image grid labeling",
        task_type="tap_grid",
        reward_per_task=1000,
        status="live",
        description="Tap every cell containing the target object.",
    ),
    CampaignOut(
        id="robotics-bbox-v1",
        title="Robotics grasp annotation",
        task_type="bounding_box",
        reward_per_task=4000,
        status="queued",
        description="Draw boxes around graspable objects in bin-picking frames.",
    ),
]


class GrantIn(BaseModel):
    """Spike-only: credit a contributor without solving anything.

    Task submission replaces this in week 2. It exists so the claim path can be
    exercised on the Seeker today.
    """

    contributor: str
    tasks: int = Field(default=1, ge=1, le=100)


class ClaimPrepareIn(BaseModel):
    contributor: str


class ClaimPrepareOut(BaseModel):
    transaction: str = Field(description="base64 wire-format tx, treasury-partial-signed")
    amount: int
    ui_amount: float
    mint: str
    fee_payer: str
    cluster: str


@app.get("/health")
def health() -> dict[str, object]:
    cfg = settings()
    return {
        "ok": True,
        "cluster": cfg.cluster,
        "mint_configured": bool(cfg.skr_mint),
        "treasury_present": pathlib.Path(cfg.treasury_keypair_path).exists(),
    }


@app.get("/campaigns", response_model=list[CampaignOut])
def campaigns() -> list[CampaignOut]:
    return CAMPAIGNS


@app.get("/contributor/{contributor}")
def contributor(contributor: str) -> dict[str, object]:
    _parse_pubkey(contributor)
    cfg = settings()
    earned = _EARNED.get(contributor, 0)
    return {
        "contributor": contributor,
        "earned": earned,
        "ui_earned": earned / (10**cfg.skr_decimals),
        "claimable": earned > 0,
    }


@app.post("/spike/grant")
def grant(body: GrantIn) -> dict[str, object]:
    _parse_pubkey(body.contributor)
    cfg = settings()
    _EARNED[body.contributor] = (
        _EARNED.get(body.contributor, 0) + body.tasks * cfg.reward_per_task
    )
    return {"contributor": body.contributor, "earned": _EARNED[body.contributor]}


@app.post("/claim/prepare", response_model=ClaimPrepareOut)
async def claim_prepare(body: ClaimPrepareIn) -> ClaimPrepareOut:
    """Build and treasury-sign the claim tx. The wallet signs as fee payer."""
    cfg = settings()
    contributor = _parse_pubkey(body.contributor)

    amount = _EARNED.get(body.contributor, 0)
    if amount <= 0:
        raise HTTPException(409, "nothing to claim")

    treasury = _treasury()
    mint = _mint()

    # Fetch the blockhash last: it expires in ~60s, so anything slow should
    # happen before this, not after. Confirmed rather than the default
    # finalized, so the hash is as fresh as possible and the wallet has the
    # full validity window to get a signature back.
    async with AsyncClient(cfg.rpc_url, commitment=Confirmed) as rpc:
        blockhash = (await rpc.get_latest_blockhash()).value.blockhash

    tx = build_claim_transaction(
        contributor=contributor,
        treasury=treasury.pubkey(),
        mint=mint,
        amount=amount,
        decimals=cfg.skr_decimals,
        blockhash=blockhash,
    )
    treasury_sign(tx, treasury)

    # Debit optimistically. The spike accepts that a wallet rejection loses the
    # credit; week 2 moves this behind a claim record keyed on the signature so
    # an unsubmitted claim can be reopened.
    _EARNED[body.contributor] = 0

    return ClaimPrepareOut(
        transaction=serialize_for_wallet(tx),
        amount=amount,
        ui_amount=amount / (10**cfg.skr_decimals),
        mint=str(mint),
        fee_payer=body.contributor,
        cluster=cfg.cluster,
    )

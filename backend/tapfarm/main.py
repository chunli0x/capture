"""Tap Farm API.

Task serving and grading are in tapfarm.tasks; the claim transaction is in
tapfarm.claim_tx. This module wires them to HTTP and enforces one rule that
neither can enforce alone: a contributor cannot claim until their gold-standard
accuracy says they should.
"""

from __future__ import annotations

import functools
import json
import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
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
from tapfarm.tasks import TaskExhausted, TaskStore, UnknownTask

app = FastAPI(title="Tap Farm", version="0.2.0")


@functools.lru_cache(maxsize=1)
def task_store() -> TaskStore:
    cfg = settings()
    return TaskStore(
        pathlib.Path(cfg.dataset_dir), reward_per_task=cfg.reward_per_task
    )


def _mount_images() -> None:
    """Serve task images. Only the images directory - never truth.jsonl."""
    images = pathlib.Path(settings().dataset_dir) / "images"
    if images.is_dir():
        app.mount("/images", StaticFiles(directory=images), name="images")


try:
    _mount_images()
except Exception:  # noqa: BLE001 - a missing dataset must not stop the API booting
    pass


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
        raise HTTPException(503, "reward mint unset; run scripts/bootstrap_devnet.sh")
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


class TaskOut(BaseModel):
    task_id: str
    campaign_id: str
    prompt: str
    grid: int
    image_url: str
    reward: int


class SubmitIn(BaseModel):
    contributor: str
    task_id: str
    cells: list[int] = Field(default_factory=list)


class SubmitOut(BaseModel):
    graded: bool
    correct: bool | None
    reward: int
    balance: int
    ui_balance: float
    accuracy: float
    gold_samples: int
    claimable: bool
    reason: str


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
    dataset = pathlib.Path(cfg.dataset_dir)
    return {
        "ok": True,
        "cluster": cfg.cluster,
        "mint_configured": bool(cfg.skr_mint),
        "treasury_present": pathlib.Path(cfg.treasury_keypair_path).exists(),
        "dataset_present": (dataset / "manifest.jsonl").exists(),
    }


@app.get("/campaigns", response_model=list[CampaignOut])
def campaigns() -> list[CampaignOut]:
    return CAMPAIGNS


@app.get("/task/next", response_model=TaskOut)
def next_task(contributor: str) -> TaskOut:
    _parse_pubkey(contributor)
    try:
        # tier is 0 until the stake program is wired in; a staked contributor
        # is verified less often because the bond covers the difference.
        task = task_store().next_task(contributor, tier=0)
    except TaskExhausted as exc:
        raise HTTPException(409, str(exc)) from exc
    return TaskOut(**vars(task))


@app.post("/task/submit", response_model=SubmitOut)
def submit_task(body: SubmitIn) -> SubmitOut:
    _parse_pubkey(body.contributor)
    cfg = settings()
    try:
        result = task_store().submit(
            body.contributor,
            body.task_id,
            body.cells,
            min_accuracy=cfg.min_accuracy_to_claim,
        )
    except UnknownTask as exc:
        raise HTTPException(409, f"task not outstanding for this contributor: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return SubmitOut(
        graded=result.graded,
        correct=result.correct,
        reward=result.reward,
        balance=result.balance,
        ui_balance=result.balance / (10**cfg.skr_decimals),
        accuracy=result.accuracy,
        gold_samples=result.gold_samples,
        claimable=result.claimable,
        reason=result.reason,
    )


@app.get("/contributor/{contributor}")
def contributor(contributor: str) -> dict[str, object]:
    _parse_pubkey(contributor)
    cfg = settings()
    state = task_store().state(contributor)
    eligibility = state.record.eligibility(cfg.min_accuracy_to_claim)
    return {
        "contributor": contributor,
        "balance": state.balance,
        "ui_balance": state.balance / (10**cfg.skr_decimals),
        "solved": len(state.seen) - len(state.outstanding),
        "accuracy": eligibility.accuracy,
        "gold_samples": eligibility.samples,
        "claimable": eligibility.allowed and state.balance > 0,
        "reason": eligibility.reason,
    }


@app.post("/claim/prepare", response_model=ClaimPrepareOut)
async def claim_prepare(body: ClaimPrepareIn) -> ClaimPrepareOut:
    """Build and treasury-sign the claim tx. The wallet signs as fee payer.

    Eligibility is enforced here rather than only in the UI: the accuracy gate
    is worthless if the endpoint behind it will pay anyone who asks.
    """
    cfg = settings()
    contributor_key = _parse_pubkey(body.contributor)
    store = task_store()
    state = store.state(body.contributor)

    eligibility = state.record.eligibility(cfg.min_accuracy_to_claim)
    if not eligibility.allowed:
        raise HTTPException(403, eligibility.reason)

    amount = state.balance
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
        contributor=contributor_key,
        treasury=treasury.pubkey(),
        mint=mint,
        amount=amount,
        decimals=cfg.skr_decimals,
        blockhash=blockhash,
    )
    treasury_sign(tx, treasury)

    # Debit optimistically. A declined wallet approval loses the credit; week 2
    # moves this behind a claim record keyed on the transaction signature so an
    # unsubmitted claim can be reopened.
    state.balance = 0

    return ClaimPrepareOut(
        transaction=serialize_for_wallet(tx),
        amount=amount,
        ui_amount=amount / (10**cfg.skr_decimals),
        mint=str(mint),
        fee_payer=body.contributor,
        cluster=cfg.cluster,
    )

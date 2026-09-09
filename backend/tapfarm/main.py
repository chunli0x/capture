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
from tapfarm.referrals import ReferralError, ReferralLedger
from tapfarm.stake_reader import StakeReader
from tapfarm.tasks import TaskExhausted, TaskStore, UnknownTask

app = FastAPI(title="Tap Farm", version="0.2.0")


@functools.lru_cache(maxsize=1)
def task_store() -> TaskStore:
    cfg = settings()
    return TaskStore(
        pathlib.Path(cfg.dataset_dir), reward_per_task=cfg.reward_per_task
    )


@functools.lru_cache(maxsize=1)
def referrals() -> ReferralLedger:
    return ReferralLedger(settings=settings())


@functools.lru_cache(maxsize=1)
def stake_reader() -> StakeReader:
    cfg = settings()
    program_id = (
        Pubkey.from_string(cfg.stake_program_id) if cfg.stake_program_id else None
    )
    return StakeReader(
        cfg.rpc_url, program_id, ttl_seconds=cfg.stake_cache_ttl_seconds
    )


async def _credit_referrer(referee: str, task_value: int) -> None:
    """Pay the referee's direct referrer out of the platform fee.

    Eligibility is resolved before crediting because it needs an on-chain read;
    the ledger itself stays synchronous and chain-free.
    """
    ledger = referrals()
    referrer = ledger.referrer_of(referee)
    if referrer is None:
        return

    cfg = settings()
    eligible = await stake_reader().is_referral_eligible(
        referrer,
        min_tap_stake=cfg.min_tap_stake,
        min_skr_stake=cfg.min_skr_stake,
    )
    ledger.credit_for_task(referee, task_value, is_eligible=lambda _who: eligible)


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
    raw = settings().tap_mint
    if not raw:
        raise HTTPException(503, "TAP mint unset; run scripts/bootstrap_devnet.sh")
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


class ReferralRegisterIn(BaseModel):
    referrer: str
    referee: str


class ReferralOut(BaseModel):
    contributor: str
    referrer: str | None
    referees: int
    earned: int
    ui_earned: float
    unclaimed: int
    ui_unclaimed: float
    eligible: bool
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
    task_amount: int
    referral_amount: int


@app.get("/health")
def health() -> dict[str, object]:
    cfg = settings()
    dataset = pathlib.Path(cfg.dataset_dir)
    return {
        "ok": True,
        "cluster": cfg.cluster,
        "mint_configured": bool(cfg.tap_mint),
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
async def submit_task(body: SubmitIn) -> SubmitOut:
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

    # Referral pay is a share of our margin on work that actually earned, so it
    # follows the reward: a failed gold task pays the contributor nothing and
    # therefore pays their referrer nothing.
    if result.reward > 0:
        await _credit_referrer(body.contributor, result.reward)

    return SubmitOut(
        graded=result.graded,
        correct=result.correct,
        reward=result.reward,
        balance=result.balance,
        ui_balance=result.balance / (10**cfg.tap_decimals),
        accuracy=result.accuracy,
        gold_samples=result.gold_samples,
        claimable=result.claimable,
        reason=result.reason,
    )


@app.post("/referral/register", response_model=ReferralOut)
async def register_referral(body: ReferralRegisterIn) -> ReferralOut:
    """Record that `referee` was brought in by `referrer`.

    Registration is separate from earning: it is allowed before the referrer has
    staked anything. Eligibility is evaluated per task at credit time, so a
    referrer who unstakes simply stops earning rather than losing the link.
    """
    _parse_pubkey(body.referrer)
    _parse_pubkey(body.referee)
    try:
        referrals().register(body.referrer, body.referee)
    except ReferralError as exc:
        raise HTTPException(409, str(exc)) from exc
    return await _referral_out(body.referrer)


@app.get("/referral/{contributor}", response_model=ReferralOut)
async def referral_summary(contributor: str) -> ReferralOut:
    _parse_pubkey(contributor)
    return await _referral_out(contributor)


async def _referral_out(contributor: str) -> ReferralOut:
    cfg = settings()
    ledger = referrals()
    stats = ledger.stats(contributor)

    eligible = await stake_reader().is_referral_eligible(
        contributor,
        min_tap_stake=cfg.min_tap_stake,
        min_skr_stake=cfg.min_skr_stake,
    )
    if eligible:
        reason = "earning referral rewards"
    elif not cfg.stake_program_id:
        reason = "staking is not configured on this deployment"
    else:
        reason = (
            f"stake at least {cfg.min_tap_stake / 10**cfg.tap_decimals:g} TAP and "
            f"{cfg.min_skr_stake / 10**cfg.skr_decimals:g} SKR to earn referral rewards"
        )

    return ReferralOut(
        contributor=contributor,
        referrer=ledger.referrer_of(contributor),
        referees=stats.referees,
        earned=stats.earned,
        ui_earned=stats.earned / (10**cfg.tap_decimals),
        unclaimed=stats.unclaimed,
        ui_unclaimed=stats.unclaimed / (10**cfg.tap_decimals),
        eligible=eligible,
        reason=reason,
    )


@app.get("/contributor/{contributor}")
def contributor(contributor: str) -> dict[str, object]:
    _parse_pubkey(contributor)
    cfg = settings()
    state = task_store().state(contributor)
    eligibility = state.record.eligibility(cfg.min_accuracy_to_claim)
    referral_unclaimed = referrals().unclaimed(contributor)
    total = state.balance + referral_unclaimed
    return {
        "contributor": contributor,
        "balance": state.balance,
        "ui_balance": state.balance / (10**cfg.tap_decimals),
        "referral_unclaimed": referral_unclaimed,
        "ui_referral_unclaimed": referral_unclaimed / (10**cfg.tap_decimals),
        "total_claimable": total,
        "ui_total_claimable": total / (10**cfg.tap_decimals),
        "solved": len(state.seen) - len(state.outstanding),
        "accuracy": eligibility.accuracy,
        "gold_samples": eligibility.samples,
        "claimable": eligibility.allowed and total > 0,
        "reason": eligibility.reason,
    }


@app.post("/claim/prepare", response_model=ClaimPrepareOut)
async def claim_prepare(body: ClaimPrepareIn) -> ClaimPrepareOut:
    """Build and treasury-sign the claim tx. The wallet signs as fee payer.

    Eligibility is enforced here rather than only in the UI: the accuracy gate
    is worthless if the endpoint behind it will pay anyone who asks.

    It gates referral earnings too, which is intentional and load-bearing. A
    contributor who has never passed probation cannot withdraw referral rewards,
    so there is no such thing as a pure recruiter account - you have to be a
    working contributor in good standing to collect for bringing others in. That
    is most of what stops this looking like a pyramid from the inside.
    """
    cfg = settings()
    contributor_key = _parse_pubkey(body.contributor)
    store = task_store()
    state = store.state(body.contributor)

    eligibility = state.record.eligibility(cfg.min_accuracy_to_claim)
    if not eligibility.allowed:
        raise HTTPException(403, eligibility.reason)

    ledger = referrals()
    referral_amount = ledger.unclaimed(body.contributor)
    amount = state.balance + referral_amount
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
        decimals=cfg.tap_decimals,
        blockhash=blockhash,
    )
    treasury_sign(tx, treasury)

    # Debit optimistically. A declined wallet approval loses the credit; the fix
    # is a claim record keyed on the transaction signature so an unsubmitted
    # claim can be reopened. Both balances are debited together so a partial
    # failure cannot leave the referral side double-claimable.
    state.balance = 0
    ledger.claim(body.contributor)

    return ClaimPrepareOut(
        transaction=serialize_for_wallet(tx),
        amount=amount,
        ui_amount=amount / (10**cfg.tap_decimals),
        mint=str(mint),
        fee_payer=body.contributor,
        cluster=cfg.cluster,
        task_amount=amount - referral_amount,
        referral_amount=referral_amount,
    )

"""Tap API.

Task serving and grading are in tapfarm.tasks; the claim transaction is in
tapfarm.claim_tx. This module wires them to HTTP and enforces one rule that
neither can enforce alone: a contributor cannot claim until their gold-standard
accuracy says they should.
"""

from __future__ import annotations

import functools
import json
import math
import pathlib
import secrets
import threading
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
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
from tapfarm.clip.dataset import ClipTaskRecord
from tapfarm.clip.dataset import load_records as load_clip_records
from tapfarm.clip.dataset import load_truth as load_clip_truth
import time

from solders.message import Message
from solders.transaction import Transaction
from spl.token.instructions import get_associated_token_address

from tapfarm import sas
from tapfarm.bond_client import BondStatus, decode_bond, derive_bond, post_bond_ix
from tapfarm.clip.scoring import FLAG_UNCLEAR
from tapfarm.verifier import VerifierKeyError, load_verifier
from tapfarm import x402
from tapfarm.jev import (
    TASK_TYPES,
    FixedRouter,
    JevClassifier,
    JevError,
    RoutingLog,
    decide,
)
from tapfarm.leaderboard import NetworkTracker
from tapfarm.liveness import (
    Challenge,
    LivenessError,
    LivenessSessionStore,
    SessionAlreadyUsed,
    SessionExpired,
    UnknownSession,
)
from tapfarm.clip.scoring import qualification_result as clip_qualification_result
from tapfarm.clip.serving import (
    CannotFlag as ClipCannotFlag,
)
from tapfarm.clip.serving import (
    ClipTaskExhausted,
    ClipTaskStore,
    InvalidChoice,
    QualificationFailed,
    RetryUnavailable,
    UnknownClipTask,
)
from tapfarm.clip.serving import (
    NotQualified as ClipNotQualified,
)
from tapfarm.pose.dataset import PoseTaskRecord, load_objects, load_truth
from tapfarm.pose.scoring import Pose, PoseThreshold
from tapfarm.pose.serving import (
    FLAG_REASONS,
    CannotFlag,
    NotQualified,
    PoseTaskExhausted,
    PoseTaskStore,
    UnknownPoseTask,
)
from tapfarm.referrals import ReferralError, ReferralLedger
from tapfarm.stake_reader import StakeReader
from tapfarm.tasks import TaskExhausted, TaskStore, UnknownTask

app = FastAPI(title="Tap", version="0.3.0")


@functools.lru_cache(maxsize=1)
def task_store() -> TaskStore:
    cfg = settings()
    return TaskStore(
        pathlib.Path(cfg.dataset_dir), reward_per_task=cfg.reward_per_task
    )


@functools.lru_cache(maxsize=1)
def pose_store() -> PoseTaskStore:
    cfg = settings()
    directory = pathlib.Path(cfg.pose_dataset_dir)
    manifest = directory / "manifest.jsonl"
    if not manifest.exists():
        raise HTTPException(
            503,
            f"no pose dataset at {directory}; run python -m tapfarm.pose.dataset",
        )
    records = [
        PoseTaskRecord(**json.loads(line))
        for line in manifest.open()
        if line.strip()
    ]
    return PoseTaskStore(
        records,
        load_truth(directory),
        reward_per_task=cfg.reward_per_task,
        qualify_items=cfg.pose_qualify_items,
        threshold=PoseThreshold(
            max_error_px=cfg.pose_max_error_px,
            max_error_deg=cfg.pose_max_error_deg,
            pass_fraction=cfg.pose_pass_fraction,
        ),
    )


@functools.lru_cache(maxsize=1)
def clip_store() -> ClipTaskStore:
    cfg = settings()
    directory = pathlib.Path(cfg.clip_dataset_dir)
    records = load_clip_records(directory)
    if not records:
        raise HTTPException(
            503,
            f"no clip dataset at {directory}; build one with "
            "tapfarm.clip.dataset.build_clip_dataset",
        )
    return ClipTaskStore(
        records,
        load_clip_truth(directory),
        reward_per_task=cfg.reward_per_task,
        qualify_items=cfg.clip_qualify_items,
        pass_fraction=cfg.clip_pass_fraction,
        max_retries=cfg.clip_max_retries,
        retry_cooldown_seconds=cfg.clip_retry_cooldown_seconds,
    )


def _clip_balance(contributor: str) -> int:
    """Clip earnings, or 0 where the campaign is not deployed.

    Same reasoning as `_pose_balance`: a deployment running only some
    campaigns must still be able to answer /contributor and pay a claim.
    """
    try:
        return clip_store().state(contributor).balance
    except HTTPException:
        return 0


def _clip_qualified(contributor: str) -> bool:
    try:
        return clip_store().state(contributor).qualified
    except HTTPException:
        return False


@functools.lru_cache(maxsize=1)
def liveness_sessions() -> LivenessSessionStore:
    return LivenessSessionStore(ttl_seconds=settings().liveness_ttl_seconds)


@functools.lru_cache(maxsize=1)
def network_tracker() -> NetworkTracker:
    return NetworkTracker()


@functools.lru_cache(maxsize=1)
def router():
    """The escalation classifier, or a fixed one when none is configured.

    Falling back rather than failing: an unconfigured Jev key should not stop
    the demand side working offline. The fallback names itself in every logged
    decision, so a run without a real classifier is never mistaken for one
    with.
    """
    cfg = settings()
    if not cfg.jev_api_key:
        return FixedRouter()
    return JevClassifier(cfg.jev_api_key, model=cfg.jev_model)


@functools.lru_cache(maxsize=1)
def routing_log() -> RoutingLog:
    return RoutingLog()


@functools.lru_cache(maxsize=1)
def payment_ledger() -> x402.PaymentLedger:
    return x402.PaymentLedger()


# Agent-submitted judge requests, awaiting human verdicts.
_judge_requests: dict[str, x402.JudgeRequest] = {}
_judge_lock = threading.Lock()


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


def _pose_balance(contributor: str) -> int:
    """Pose earnings, or 0 when the campaign is not deployed here.

    Swallowing the missing-dataset case keeps the contributor summary and the
    claim path working on a deployment that only runs the tap-grid campaign.
    """
    try:
        return pose_store().state(contributor).balance
    except HTTPException:
        return 0


def _pose_qualified(contributor: str) -> bool:
    try:
        return pose_store().state(contributor).qualified
    except HTTPException:
        return False


# One lock per contributor, guarding the read-and-zero of their balances.
# A threading lock rather than an asyncio one because the routes that credit
# those balances are plain `def` and therefore run in the threadpool - an
# asyncio lock would not exclude them.
_claim_locks: dict[str, threading.Lock] = {}
_claim_locks_guard = threading.Lock()


def _claim_lock(contributor: str) -> threading.Lock:
    with _claim_locks_guard:
        return _claim_locks.setdefault(contributor, threading.Lock())


@dataclass(frozen=True)
class ClaimSnapshot:
    """Balances captured at the instant they were zeroed."""

    task: int
    referral: int
    pose: int
    clip: int

    @property
    def total(self) -> int:
        return self.task + self.referral + self.pose + self.clip


def _snapshot_and_debit(contributor: str) -> ClaimSnapshot:
    """Read every balance and zero it in one indivisible step.

    This must stay synchronous. Reading the totals, awaiting a blockhash, and
    only then zeroing leaves a window in which a concurrent submit has its fresh
    reward wiped, or a second claim reads the same balance and both
    transactions get signed for the full amount.
    """
    with _claim_lock(contributor):
        gate = _claim_gate(contributor)
        if not gate.allowed:
            raise HTTPException(403, gate.reason)

        task_state = task_store().state(contributor)
        snapshot = ClaimSnapshot(
            task=task_state.balance,
            referral=referrals().unclaimed(contributor),
            pose=_pose_balance(contributor),
            clip=_clip_balance(contributor),
        )
        if snapshot.total <= 0:
            raise HTTPException(409, "nothing to claim")

        task_state.balance = 0
        if snapshot.pose:
            pose_store().state(contributor).balance = 0
        if snapshot.clip:
            clip_store().state(contributor).balance = 0
        if snapshot.referral:
            referrals().claim(contributor)
        return snapshot


def _restore(contributor: str, snapshot: ClaimSnapshot) -> None:
    """Give the money back when the claim could not be built.

    Added back rather than assigned, so a reward that arrived between the debit
    and the failure is not clobbered.
    """
    with _claim_lock(contributor):
        task_store().state(contributor).balance += snapshot.task
        if snapshot.pose:
            pose_store().state(contributor).balance += snapshot.pose
        if snapshot.clip:
            clip_store().state(contributor).balance += snapshot.clip
        if snapshot.referral:
            referrals().credit_back(contributor, snapshot.referral)


@dataclass(frozen=True)
class ClaimGate:
    """Whether a contributor may withdraw, and why.

    One helper rather than two, because /contributor and /claim/prepare have to
    agree: a summary that says "not claimable" while the endpoint behind it
    pays out - or the reverse - is worse than either answer on its own.
    """

    allowed: bool
    reason: str


def _claim_gate(contributor: str) -> ClaimGate:
    """Each campaign carries its own proof of quality.

    Tap-grid uses rolling gold-standard accuracy; ghost-overlay and
    clip-judgment each use their own blind qualification run. Clearing any one
    makes a contributor verified - requiring all three would strand someone
    behind a gate for a campaign they never touched.

    Every campaign that can pay has to appear here. A campaign that credits a
    balance but is missing from this gate would either be unspendable or, worse,
    let /contributor and /claim/prepare disagree about whether it is.
    """
    cfg = settings()
    eligibility = task_store().state(contributor).record.eligibility(
        cfg.min_accuracy_to_claim
    )
    if eligibility.allowed:
        return ClaimGate(True, eligibility.reason)
    if _pose_qualified(contributor):
        return ClaimGate(True, "qualified on the ghost-overlay blind set")
    if _clip_qualified(contributor):
        return ClaimGate(True, "qualified on the clip-judgment blind set")
    return ClaimGate(
        False,
        f"{eligibility.reason}, and neither the ghost-overlay nor the "
        "clip-judgment qualification has been passed",
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
        min_human_stake=cfg.min_human_stake,
        min_skr_stake=cfg.min_skr_stake,
    )
    ledger.credit_for_task(referee, task_value, is_eligible=lambda _who: eligible)


def _json_safe(value: object) -> object:
    """Replace values that cannot survive JSON encoding.

    Only non-finite floats qualify: everything else pydantic puts in an error
    is already encodable.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return a 422 that can actually be encoded.

    pydantic echoes the offending input back inside the error detail. When that
    input is NaN or Infinity - which Python's JSON parser accepts on the way in
    but the encoder refuses on the way out - the error response is itself
    invalid JSON, and a clean 422 becomes a 500. A client sending a malformed
    pose then sees a server crash instead of being told which field is wrong.
    """
    return JSONResponse(status_code=422, content={"detail": _json_safe(exc.errors())})


def _mount_images() -> None:
    """Serve task media only.

    Each mount points at an images or sprites directory specifically, never at
    a dataset root - truth.jsonl and live_truth.jsonl sit beside them and must
    never be reachable over HTTP.
    """
    images = pathlib.Path(settings().dataset_dir) / "images"
    if images.is_dir():
        app.mount("/images", StaticFiles(directory=images), name="images")

    pose_dir = pathlib.Path(settings().pose_dataset_dir)
    if (pose_dir / "images").is_dir():
        app.mount(
            "/pose/images", StaticFiles(directory=pose_dir / "images"), name="pose-images"
        )
    if (pose_dir / "sprites").is_dir():
        app.mount(
            "/pose/sprites",
            StaticFiles(directory=pose_dir / "sprites"),
            name="pose-sprites",
        )

    # `media` specifically, not the clip dataset root: truth.jsonl and
    # live_truth.jsonl live in that root, and serving it would hand the blind
    # set's answers to anyone who guessed the filename.
    clip_media = pathlib.Path(settings().clip_dataset_dir) / "media"
    if clip_media.is_dir():
        app.mount("/clips", StaticFiles(directory=clip_media), name="clips")


try:
    _mount_images()
except Exception:  # noqa: BLE001 - a missing dataset must not stop the API booting
    pass


@functools.lru_cache(maxsize=4)
def _load_treasury(path_str: str) -> Keypair:
    """Parse the treasury keypair once.

    Cached on the path so tests that point at a different file still get their
    own key, rather than being served whichever one was loaded first.
    """
    path = pathlib.Path(path_str)
    if not path.exists():
        raise HTTPException(
            503, f"treasury keypair missing at {path}; run scripts/bootstrap_devnet.sh"
        )
    return Keypair.from_bytes(bytes(json.loads(path.read_text())))


def _treasury() -> Keypair:
    return _load_treasury(settings().treasury_keypair_path)


def _verifier() -> Keypair:
    """The key that co-signs every attestation.

    Loaded through `verifier.py`, which refuses a key whose pubkey is not the
    configured verifier - a valid but wrong key would sign happily and have
    every mint rejected on-chain.
    """
    cfg = settings()
    return load_verifier(cfg.verifier_keypair_path, cfg.verifier_pubkey)


def _payout_mint() -> tuple[Pubkey, int, str]:
    """What a claim actually pays out, and at what precision.

    USDC, always. Paying workers a stablecoin is what keeps the token a
    staking and access instrument rather than the thing people are working for
    - the distinction the pitch rests on when asked whether the token is a
    security. There is no fallback: a deployment without a USDC mint has
    nothing correct to pay in, so it refuses rather than paying in something
    the UI did not promise.
    """
    cfg = settings()
    if cfg.usdc_mint:
        return Pubkey.from_string(cfg.usdc_mint), cfg.usdc_decimals, "USDC"
    raise HTTPException(
        503, "no USDC mint configured; run scripts/bootstrap_devnet.sh"
    )


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
        id="ghost-pose-v1",
        title="Ghost overlay: image-plane pose",
        task_type="ghost_pose",
        reward_per_task=10_000,
        status="live",
        description=(
            "Drag a translucent outline onto the object until it lines up. "
            "Records image-plane pose: x, y and roll, plus an auxiliary scale."
        ),
    ),
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


class PoseIn(BaseModel):
    """A submitted pose.

    Bounds are explicit because pydantic v2 accepts NaN and Infinity into a
    plain `float`. Either would sail through scoring: NaN compares false against
    every threshold, so it fails silently rather than being rejected, and an
    infinite coordinate makes the error metric meaningless. `allow_inf_nan`
    turns both into a 422 at the edge instead.

    The coordinate range is generous rather than tight to the canvas - a ghost
    clamped to the frame cannot leave it, and a hard canvas bound here would
    couple the wire format to one image size.
    """

    model_config = ConfigDict(allow_inf_nan=False)

    x: float = Field(ge=-10_000, le=10_000)
    y: float = Field(ge=-10_000, le=10_000)
    roll: float = Field(ge=-3_600, le=3_600)
    scale: float = Field(default=1.0, gt=0.0, le=100.0)


class PoseSubmitIn(BaseModel):
    contributor: str
    task_id: str
    pose: PoseIn


class PoseTaskOut(BaseModel):
    task_id: str
    object_id: str
    image_url: str
    canvas: int
    mode: str
    # Practice only. The snap glow is a proximity signal, so it must never be
    # enabled during the blind qualification run.
    allow_snap: bool
    reward: int
    truth: dict[str, float] | None = None
    index: int | None = None
    of: int | None = None


class PoseFeedbackOut(BaseModel):
    error_px: float
    error_deg: float
    within_tolerance: bool


class QualificationOut(BaseModel):
    attempted: int
    required: int
    passed_items: int
    pass_rate: float
    required_pass_rate: float
    qualified: bool
    mean_error_px: float
    mean_error_deg: float
    summary: str


class PoseFlagIn(BaseModel):
    contributor: str
    task_id: str
    reason: str


class PoseFlagOut(BaseModel):
    task_id: str
    reason: str
    mode: str


class PoseSubmitOut(BaseModel):
    mode: str
    reward: int
    balance: int
    ui_balance: float
    qualified: bool
    # None during qualification: the run stays silent until it is complete.
    feedback: PoseFeedbackOut | None = None
    label: dict | None = None
    qualification: QualificationOut | None = None


class ClipTaskOut(BaseModel):
    task_id: str
    mode: str
    clip_url: str
    question: str
    choices: list[str]
    # False during qualification: an escape hatch there is a way past any item.
    can_flag: bool
    reward: int
    # True for stand-in clips. Surfaced so a demo can refuse to show one rather
    # than present a placeholder as if it were real footage.
    placeholder: bool


class ClipSubmitIn(BaseModel):
    contributor: str
    task_id: str
    choice: str


class ClipQualificationOut(BaseModel):
    graded: int
    correct: int
    required: int
    accuracy: float
    passed: bool
    # What a uniform guesser would have scored on this gate. Carried so any
    # surface reporting a pass can also report what the pass was worth.
    chance_pass: float
    retry_available: bool
    retry_ready_at: float | None = None


class ClipSubmitOut(BaseModel):
    mode: str
    reward: int
    balance: int
    ui_balance: float
    qualified: bool
    flagged: bool
    # Practice only. Blind runs and paid work both return None: during
    # qualification it would be the answer, and in paid work it would reveal
    # which items are the hidden golden ones.
    correct: bool | None = None
    expected: str | None = None
    quality_signal: str | None = None
    qualification: ClipQualificationOut | None = None


class LivenessSessionIn(BaseModel):
    contributor: str
    task_id: str


class LivenessSessionOut(BaseModel):
    session_id: str
    # The motion to perform. Server-chosen: if the device picked, one recorded
    # run would satisfy every future session.
    challenge: str
    # Hex, because this is the anti-replay value the device must commit to and
    # JSON has no bytes.
    nonce: str
    expires_at: float
    ttl_seconds: float


class LivenessCompleteIn(BaseModel):
    contributor: str
    session_id: str
    # Whatever the on-device check summarises itself as, hex-encoded. Opaque
    # to the server on purpose: no biometric material should ever arrive here.
    result_digest: str


class LivenessCompleteOut(BaseModel):
    liveness_proof_hash: str
    task_id: str
    challenge: str
    # Said in the payload, not only in the docs, so a client rendering this
    # cannot accidentally present it as more than it is.
    attests: str = (
        "a live person performed a motion challenge on-device; "
        "not bank-grade anti-spoofing"
    )


class AttestationPrepareIn(BaseModel):
    contributor: str
    task_id: str
    liveness_proof_hash: str


class AttestationPrepareOut(BaseModel):
    """A transaction the wallet signs to mint its own attestation."""

    transaction: str = Field(
        description="base64 wire-format tx, verifier-partial-signed"
    )
    bond_account: str
    attestation_account: str
    bond_amount: int
    ui_bond_amount: float
    cluster: str
    # What the resulting record does and does not establish. Carried in the
    # response so a client cannot present it as more than it is.
    attests: str = (
        "a verifier-vouched, bond-secured attestation that this human "
        "completed this task; not cryptographic proof of humanness"
    )


class VerifyOut(BaseModel):
    """The portable credential, as a buyer checks it."""

    found: bool
    human: str | None = None
    task_id: str | None = None
    status: str | None = None
    bond_amount: int | None = None
    ui_bond_amount: float | None = None
    attested_at: int | None = None
    verifier: str | None = None
    liveness_proof_hash: str | None = None
    bond_account: str | None = None
    attestation_account: str | None = None
    cluster: str
    # The three checks the demo's verify screen renders as badges.
    verified_human: bool = False
    task_complete: bool = False
    staked: bool = False
    # One sentence a buyer can quote without overstating it.
    summary: str


class NetworkStatsOut(BaseModel):
    # Soft: a heartbeat count, not a verified population. Named so on the wire
    # so a UI cannot render it as anything firmer.
    online_now_estimate: int
    acted_today: int
    work_proven: int
    # Says plainly which numbers are which, because a leaderboard that mixes
    # a heartbeat with on-chain counts invites reading all three as proven.
    online_now_is_estimate: bool = True
    source: str


class LeaderboardRow(BaseModel):
    rank: int
    human: str
    human_short: str
    quality_score: float
    accuracy: float
    work_count: int
    bond: int
    ui_bond: float


class LeaderboardOut(BaseModel):
    rows: list[LeaderboardRow]
    scored_on: str


class JudgeIn(BaseModel):
    """What an agent sends to buy a human judgment."""

    task_type: str
    question: str
    choices: list[str]
    media_url: str | None = None
    # Free-text state for the router. The agent's own summary of what it saw.
    state: str = ""


class RoutingOut(BaseModel):
    escalate: bool
    reasons: list[str]
    probabilities: dict[str, float]
    model: str
    # True when no classifier is configured and a fixed router answered, so a
    # reader never mistakes a stub for a calibrated decision.
    simulated: bool


class JudgeAcceptedOut(BaseModel):
    request_id: str
    status: str
    routing: RoutingOut
    judges_required: int
    judges_so_far: int
    # Stated rather than implied: the inbound leg is not settled on chain in
    # this build.
    payment_verification: str = "receipt shape only; not settled on chain"


class JudgeVerdictOut(BaseModel):
    request_id: str
    status: str
    verdict: str | None
    agreement: str | None
    judges: int
    routing: RoutingOut


class ClipRetryIn(BaseModel):
    contributor: str


class ClaimPrepareIn(BaseModel):
    contributor: str


class ClaimPrepareOut(BaseModel):
    # Which token actually moved. Always USDC: the payout mint has no fallback.
    payout_symbol: str = "USDC"
    transaction: str = Field(description="base64 wire-format tx, treasury-partial-signed")
    amount: int
    ui_amount: float
    mint: str
    fee_payer: str
    cluster: str
    task_amount: int
    referral_amount: int
    pose_amount: int


@app.get("/health")
def health() -> dict[str, object]:
    cfg = settings()
    dataset = pathlib.Path(cfg.dataset_dir)
    return {
        "ok": True,
        "cluster": cfg.cluster,
        "mint_configured": bool(cfg.usdc_mint),
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
        # Hardcoded, and that is the whole of the tiering story today: the
        # stake program can report a contributor's tier, but nothing reads it
        # here, so the reduced verification rate for bonded contributors never
        # fires. Wiring this to stake_reader is in PLATFORM.md.
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
        ui_balance=result.balance / (10**cfg.usdc_decimals),
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
        min_human_stake=cfg.min_human_stake,
        min_skr_stake=cfg.min_skr_stake,
    )
    if eligible:
        reason = "earning referral rewards"
    elif not cfg.stake_program_id:
        reason = "staking is not configured on this deployment"
    else:
        reason = (
            f"stake at least {cfg.min_human_stake / 10**cfg.human_decimals:g} HUMAN and "
            f"{cfg.min_skr_stake / 10**cfg.skr_decimals:g} SKR to earn referral rewards"
        )

    return ReferralOut(
        contributor=contributor,
        referrer=ledger.referrer_of(contributor),
        referees=stats.referees,
        earned=stats.earned,
        ui_earned=stats.earned / (10**cfg.usdc_decimals),
        unclaimed=stats.unclaimed,
        ui_unclaimed=stats.unclaimed / (10**cfg.usdc_decimals),
        eligible=eligible,
        reason=reason,
    )


@app.get("/pose/objects")
def pose_objects() -> list[dict]:
    """Object metadata and ghost sprites the client needs to render."""
    return load_objects(pathlib.Path(settings().pose_dataset_dir))


@app.get("/pose/task/next", response_model=PoseTaskOut)
def pose_next_task(contributor: str, mode: str = "practice") -> PoseTaskOut:
    _parse_pubkey(contributor)
    try:
        task = pose_store().next_task(contributor, mode)
    except NotQualified as exc:
        raise HTTPException(403, str(exc)) from exc
    except PoseTaskExhausted as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return PoseTaskOut(**vars(task))


@app.post("/pose/submit", response_model=PoseSubmitOut)
def pose_submit(body: PoseSubmitIn) -> PoseSubmitOut:
    _parse_pubkey(body.contributor)
    cfg = settings()
    try:
        result = pose_store().submit(
            body.contributor,
            body.task_id,
            Pose(**body.pose.model_dump()),
        )
    except UnknownPoseTask as exc:
        raise HTTPException(
            409, f"task not outstanding for this contributor: {exc}"
        ) from exc

    return PoseSubmitOut(
        mode=result.mode,
        reward=result.reward,
        balance=result.balance,
        ui_balance=result.balance / (10**cfg.usdc_decimals),
        qualified=result.qualified,
        feedback=(
            PoseFeedbackOut(**vars(result.feedback)) if result.feedback else None
        ),
        label=result.label,
        qualification=(
            _qualification_out(result.qualification) if result.qualification else None
        ),
    )


@app.post("/pose/flag", response_model=PoseFlagOut)
def pose_flag(body: PoseFlagIn) -> PoseFlagOut:
    """Discard a task the labeler cannot honestly answer.

    A forced guess on an unclear or empty frame is a confident wrong label,
    which is worse for the dataset than no label at all.
    """
    _parse_pubkey(body.contributor)
    try:
        flagged = pose_store().flag(body.contributor, body.task_id, body.reason)
    except UnknownPoseTask as exc:
        raise HTTPException(
            409, f"task not outstanding for this contributor: {exc}"
        ) from exc
    except CannotFlag as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            400, f"{exc}; expected one of {', '.join(FLAG_REASONS)}"
        ) from exc
    return PoseFlagOut(task_id=flagged.task_id, reason=flagged.reason, mode=flagged.mode)


@app.get("/pose/qualification/{contributor}", response_model=QualificationOut)
def pose_qualification(contributor: str) -> QualificationOut:
    _parse_pubkey(contributor)
    return _qualification_out(pose_store().qualification(contributor))


def _qualification_out(result) -> QualificationOut:
    return QualificationOut(
        attempted=result.attempted,
        required=result.required,
        passed_items=result.passed_items,
        pass_rate=result.pass_rate,
        required_pass_rate=result.required_pass_rate,
        qualified=result.qualified,
        mean_error_px=round(result.mean_error_px, 1),
        mean_error_deg=round(result.mean_error_deg, 1),
        summary=result.summary,
    )


@app.get("/clip/task/next", response_model=ClipTaskOut)
def clip_next_task(contributor: str, mode: str = "practice") -> ClipTaskOut:
    _parse_pubkey(contributor)
    try:
        task = clip_store().next_task(contributor, mode)
    except ClipNotQualified as exc:
        raise HTTPException(403, str(exc)) from exc
    except QualificationFailed as exc:
        raise HTTPException(403, str(exc)) from exc
    except ClipTaskExhausted as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return ClipTaskOut(
        task_id=task.task_id,
        mode=task.mode,
        clip_url=f"/clips/{task.clip}",
        question=task.question,
        choices=task.choices,
        can_flag=task.can_flag,
        reward=clip_store().reward_per_task if task.mode == "earn" else 0,
        placeholder=task.placeholder,
    )


@app.post("/clip/submit", response_model=ClipSubmitOut)
def clip_submit(body: ClipSubmitIn) -> ClipSubmitOut:
    _parse_pubkey(body.contributor)
    try:
        result = clip_store().submit(body.contributor, body.task_id, body.choice)
    except UnknownClipTask as exc:
        raise HTTPException(
            409, f"task not outstanding for this contributor: {exc}"
        ) from exc
    except ClipCannotFlag as exc:
        raise HTTPException(409, str(exc)) from exc
    except InvalidChoice as exc:
        raise HTTPException(400, str(exc)) from exc

    # Only paid work counts towards the board: practice is unpaid training and
    # a qualification run is a gate, not a contribution.
    if result.mode == "earn" and not result.flagged:
        network_tracker().record_work(
            body.contributor,
            graded=result.quality_signal == "golden_item",
            correct=clip_store().last_grade_correct(body.contributor),
        )
    else:
        network_tracker().seen(body.contributor)
    return _clip_submit_out(body.contributor, result)


@app.post("/clip/flag", response_model=ClipSubmitOut)
def clip_flag(body: ClipSubmitIn) -> ClipSubmitOut:
    """Report a clip that does not show the answer.

    A forced guess on an unclear clip is a confident wrong label, which is
    worse for the dataset than no label. Flagging pays nothing, so it cannot
    become the cheapest route through paid work, and it is refused outright
    during qualification.

    A separate route from /clip/submit so a client never has to smuggle the
    sentinel through the choice field, and so the refusal during qualification
    is a property of the endpoint rather than of a magic string.
    """
    _parse_pubkey(body.contributor)
    try:
        result = clip_store().submit(body.contributor, body.task_id, FLAG_UNCLEAR)
    except UnknownClipTask as exc:
        raise HTTPException(
            409, f"task not outstanding for this contributor: {exc}"
        ) from exc
    except ClipCannotFlag as exc:
        raise HTTPException(409, str(exc)) from exc
    return _clip_submit_out(body.contributor, result)


@app.get("/clip/qualification/{contributor}", response_model=ClipQualificationOut)
def clip_qualification(contributor: str) -> ClipQualificationOut:
    _parse_pubkey(contributor)
    store = clip_store()
    state = store.state(contributor)
    result = clip_qualification_result(
        state.qualify_grades,
        items=store.qualify_items,
        pass_fraction=store.pass_fraction,
        choices=settings().clip_choices,
    )
    return _clip_qualification_out(contributor, result)


@app.post("/clip/qualification/retry", response_model=ClipQualificationOut)
def clip_qualification_retry(body: ClipRetryIn) -> ClipQualificationOut:
    """Reset a failed blind run, once, after the cooldown."""
    _parse_pubkey(body.contributor)
    store = clip_store()
    try:
        store.retry_qualification(body.contributor)
    except RetryUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    state = store.state(body.contributor)
    return _clip_qualification_out(
        body.contributor,
        clip_qualification_result(
            state.qualify_grades,
            items=store.qualify_items,
            pass_fraction=store.pass_fraction,
            choices=settings().clip_choices,
        ),
    )


def _clip_submit_out(contributor: str, result) -> ClipSubmitOut:
    cfg = settings()
    return ClipSubmitOut(
        mode=result.mode,
        reward=result.reward,
        balance=result.balance,
        ui_balance=result.balance / (10**cfg.usdc_decimals),
        qualified=result.qualified,
        flagged=result.flagged,
        correct=result.correct,
        expected=result.expected,
        quality_signal=result.quality_signal,
        qualification=(
            _clip_qualification_out(contributor, result.qualification)
            if result.qualification
            else None
        ),
    )


def _clip_qualification_out(contributor: str, result) -> ClipQualificationOut:
    store = clip_store()
    return ClipQualificationOut(
        graded=result.graded,
        correct=result.correct,
        required=result.required,
        accuracy=round(result.accuracy, 4),
        passed=result.passed,
        chance_pass=result.chance_pass,
        retry_available=store.retry_available(contributor),
        retry_ready_at=store.retry_ready_at(contributor),
    )


@app.post("/liveness/session", response_model=LivenessSessionOut)
def liveness_session(body: LivenessSessionIn) -> LivenessSessionOut:
    """Issue a fresh, single-use motion challenge for one task."""
    _parse_pubkey(body.contributor)
    store = liveness_sessions()
    session = store.issue(body.contributor, body.task_id)
    return LivenessSessionOut(
        session_id=session.session_id,
        challenge=session.challenge.value,
        nonce=session.nonce.hex(),
        expires_at=session.expires_at,
        ttl_seconds=store.ttl_seconds,
    )


@app.post("/liveness/complete", response_model=LivenessCompleteOut)
def liveness_complete(body: LivenessCompleteIn) -> LivenessCompleteOut:
    """Accept one result and return the hash the human signs over.

    The hash is returned rather than stored against the task because the
    binding that matters is the signature: it is committed into the
    MWA-signed payload that mints the attestation, which is what makes the
    human a party to the claim rather than its subject.
    """
    _parse_pubkey(body.contributor)
    try:
        result_digest = bytes.fromhex(body.result_digest)
    except ValueError as exc:
        raise HTTPException(400, f"result_digest must be hex: {exc}") from exc

    store = liveness_sessions()
    session = None
    try:
        session = store.get(body.contributor, body.session_id)
        digest = store.complete(body.contributor, body.session_id, result_digest)
    except UnknownSession as exc:
        raise HTTPException(404, str(exc)) from exc
    except SessionExpired as exc:
        raise HTTPException(410, str(exc)) from exc
    except SessionAlreadyUsed as exc:
        raise HTTPException(409, str(exc)) from exc
    except LivenessError as exc:
        raise HTTPException(400, str(exc)) from exc

    return LivenessCompleteOut(
        liveness_proof_hash=digest.hex(),
        task_id=session.task_id,
        challenge=session.challenge.value,
    )


@app.post("/attestation/prepare", response_model=AttestationPrepareOut)
async def attestation_prepare(body: AttestationPrepareIn) -> AttestationPrepareOut:
    """Build the attestation-mint transaction for the wallet to sign.

    Two instructions, one transaction: `post_bond` escrows HUMAN and creates
    the bond PDA, and SAS `create_attestation` issues the credential with its
    nonce set to that bond. Splitting them would allow a crash to leave a
    credential with no stake behind it, which is precisely the claim this
    product says it does not make.

    The human is the fee payer and a required signer, so the transaction
    cannot land without their wallet. The verifier partial-signs here.
    """
    human = _parse_pubkey(body.contributor)
    cfg = settings()

    if not cfg.bond_program_id:
        raise HTTPException(503, "bond program not configured; attestations are off")
    if not cfg.human_mint:
        raise HTTPException(503, "HUMAN mint unset; run scripts/bootstrap_devnet.sh")

    try:
        liveness_hash = bytes.fromhex(body.liveness_proof_hash)
    except ValueError as exc:
        raise HTTPException(400, f"liveness_proof_hash must be hex: {exc}") from exc
    if len(liveness_hash) != 32:
        raise HTTPException(400, "liveness_proof_hash must be 32 bytes")

    # The proof must be one this server issued and has not already spent.
    # Checking here turns a replay into a 409 instead of a failed instruction.
    if not liveness_sessions().has_seen(liveness_hash):
        raise HTTPException(
            403,
            "unknown liveness proof; complete a liveness check for this task first",
        )

    gate = _claim_gate(body.contributor)
    if not gate.allowed:
        raise HTTPException(403, gate.reason)

    try:
        verifier = _verifier()
    except VerifierKeyError as exc:
        raise HTTPException(503, str(exc)) from exc

    program_id = _parse_pubkey(cfg.bond_program_id)
    human_mint = _parse_pubkey(cfg.human_mint)
    human_tokens = get_associated_token_address(human, human_mint)

    try:
        bond_ix = post_bond_ix(
            program_id=program_id,
            payer=human,
            human=human,
            verifier=verifier.pubkey(),
            human_mint=human_mint,
            human_tokens=human_tokens,
            task_id=body.task_id,
            liveness_proof_hash=liveness_hash,
            amount=cfg.attestation_bond,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    bond_account, _ = derive_bond(program_id, human, body.task_id)

    # The join: SAS's nonce is our bond PDA, so each record names the other.
    authority = (
        _parse_pubkey(cfg.sas_credential_authority)
        if cfg.sas_credential_authority
        else _treasury().pubkey()
    )
    credential, _ = sas.derive_credential(authority, sas.CREDENTIAL_NAME)
    schema, _ = sas.derive_schema(credential, sas.CLIP_JUDGMENT_SCHEMA_NAME)
    attestation, _ = sas.derive_attestation(credential, schema, bond_account)

    claim = sas.ClipJudgmentClaim(
        task_id=body.task_id,
        liveness_proof_hash=liveness_hash,
        bond_amount=cfg.attestation_bond,
        attested_at=int(time.time()),
    )
    attestation_ix = sas.create_attestation_ix(
        payer=human,
        authorized_signer=verifier.pubkey(),
        credential=credential,
        schema=schema,
        nonce=bond_account,
        schema_data=claim.encode(),
    )

    async with AsyncClient(cfg.rpc_url, commitment=Confirmed) as rpc:
        blockhash = (await rpc.get_latest_blockhash()).value.blockhash

    message = Message.new_with_blockhash(
        [bond_ix, attestation_ix], human, blockhash
    )
    tx = Transaction.new_unsigned(message)
    tx.partial_sign([verifier], blockhash)

    return AttestationPrepareOut(
        transaction=base64.b64encode(bytes(tx)).decode(),
        bond_account=str(bond_account),
        attestation_account=str(attestation),
        bond_amount=cfg.attestation_bond,
        ui_bond_amount=cfg.attestation_bond / (10**cfg.human_decimals),
        cluster=cfg.cluster,
    )


@app.post("/v1/judge")
async def judge(body: JudgeIn, request: Request) -> Response:
    """Buy one human judgment. Answers 402 until a payment arrives.

    The flow, in the order an agent meets it:

    1. No payment header -> route the request through the escalation
       classifier. If it says a human is not needed, say so and charge
       nothing; selling a judgment the agent did not need would be the easiest
       way to make this product dishonest.
    2. Otherwise answer `402 Payment Required` with a price, using x402 V2's
       header transport on Solana.
    3. With a valid, unspent receipt -> enqueue to the human feed and hold.
    """
    cfg = settings()
    if body.task_type not in TASK_TYPES:
        raise HTTPException(
            400, f"task_type must be one of {', '.join(TASK_TYPES)}"
        )
    if len(body.choices) < 2:
        raise HTTPException(400, "a judgment needs at least two choices")

    state = body.state or body.question
    try:
        answers = router().classify(state)
    except JevError as exc:
        # Fail towards the human. A router that cannot answer is not evidence
        # that nobody needs to look, and the expensive mistake here is
        # skipping a judgment that was needed.
        log_note = f"router unavailable ({exc}); escalating by default"
        answers = FixedRouter().answers
        decision = decide(answers)
        decision = type(decision)(
            escalate=True, reasons=[log_note], answers=answers
        )
    else:
        decision = decide(answers)

    routing_log().record(body.task_type, decision)
    routing = RoutingOut(
        escalate=decision.escalate,
        reasons=decision.reasons,
        probabilities=decision.answers.as_dict(),
        model=decision.answers.model,
        simulated=decision.answers.model == "fixed-router",
    )

    if not decision.escalate:
        return JSONResponse(
            {
                "status": "no_human_needed",
                "routing": routing.model_dump(),
                "detail": "the agent may proceed; nothing was charged",
            }
        )

    signature = request.headers.get(x402.PAYMENT_SIGNATURE_HEADER)
    if not signature:
        requirement = x402.PaymentRequirement(
            scheme=x402.SCHEME_EXACT,
            network=x402.network_for(cfg.cluster),
            price=cfg.judge_price_usd,
            asset=cfg.usdc_mint or "USDC",
            pay_to=str(_treasury().pubkey()),
            resource="/v1/judge",
            description=f"One human judgment: {body.question}",
        )
        reference = payment_ledger().issue(cfg.judge_price_usd)
        header = x402.payment_required_header([requirement])
        return JSONResponse(
            status_code=402,
            content={
                "status": "payment_required",
                "reference": reference,
                "price": cfg.judge_price_usd,
                "network": requirement.network,
                "routing": routing.model_dump(),
            },
            headers={
                x402.PAYMENT_REQUIRED_HEADER: header,
                # The reference travels in the body too: it is what the client
                # echoes back, and a header-only value is easy to drop.
                "X-Payment-Reference": reference,
            },
        )

    try:
        receipt = x402.parse_payment_signature(signature)
        payment_ledger().spend(receipt)
    except x402.ReceiptError as exc:
        raise HTTPException(402, str(exc)) from exc

    request_id = secrets.token_hex(8)
    with _judge_lock:
        _judge_requests[request_id] = x402.JudgeRequest(
            request_id=request_id,
            task_type=body.task_type,
            question=body.question,
            choices=list(body.choices),
            media_url=body.media_url,
            price=cfg.judge_price_usd,
            payer=receipt.payer,
            created_at=time.time(),
        )

    return JSONResponse(
        JudgeAcceptedOut(
            request_id=request_id,
            status="queued",
            routing=routing,
            judges_required=cfg.judge_quorum,
            judges_so_far=0,
        ).model_dump()
    )


@app.get("/v1/judge/{request_id}", response_model=JudgeVerdictOut)
def judge_result(request_id: str) -> JudgeVerdictOut:
    """Poll for the verdict. Held until the quorum of humans has judged."""
    cfg = settings()
    with _judge_lock:
        entry = _judge_requests.get(request_id)
    if entry is None:
        raise HTTPException(404, "unknown judge request")

    verdict, agreed, total = entry.agreement
    resolved = total >= cfg.judge_quorum
    return JudgeVerdictOut(
        request_id=request_id,
        status="complete" if resolved else "awaiting_humans",
        # Withheld until the quorum is in. Returning a running majority would
        # let an agent read one judge's answer and stop paying attention.
        verdict=verdict if resolved else None,
        agreement=f"{agreed}/{total}" if resolved else None,
        judges=total,
        routing=RoutingOut(
            escalate=True,
            reasons=["already escalated"],
            probabilities={},
            model="n/a",
            simulated=False,
        ),
    )


@app.get("/agent/queue")
def agent_queue(limit: int = 20) -> list[dict]:
    """Agent-submitted work, for the human feed.

    Shown beside clip tasks in the same feed. The judge path deliberately
    reuses the flag and golden-item machinery rather than growing a parallel
    one - a second scoring path is how two quality standards appear.
    """
    with _judge_lock:
        pending = [
            entry
            for entry in _judge_requests.values()
            if len(entry.verdicts) < settings().judge_quorum
        ]
    pending.sort(key=lambda e: e.created_at)
    return [
        {
            "request_id": entry.request_id,
            "task_type": entry.task_type,
            "question": entry.question,
            "choices": entry.choices,
            "media_url": entry.media_url,
            "price": entry.price,
            "judges_so_far": len(entry.verdicts),
            "judges_required": settings().judge_quorum,
        }
        for entry in pending[:limit]
    ]


@app.post("/agent/judge/{request_id}")
def submit_agent_judgment(request_id: str, contributor: str, choice: str) -> dict:
    """A human's verdict on an agent's request."""
    _parse_pubkey(contributor)
    cfg = settings()
    with _judge_lock:
        entry = _judge_requests.get(request_id)
        if entry is None:
            raise HTTPException(404, "unknown judge request")
        if choice not in entry.choices:
            raise HTTPException(400, f"{choice!r} is not one of {entry.choices}")
        if len(entry.verdicts) >= cfg.judge_quorum:
            raise HTTPException(409, "this request already has its verdicts")
        entry.verdicts.append(choice)
        so_far = len(entry.verdicts)

    # Agent work counts towards the board, and has no ground truth, so it is
    # recorded ungraded - the same rule live clip work follows.
    network_tracker().record_work(contributor, graded=False)
    return {
        "request_id": request_id,
        "judges_so_far": so_far,
        "judges_required": cfg.judge_quorum,
        "complete": so_far >= cfg.judge_quorum,
    }


@app.get("/agent/routing/recent")
def routing_recent(limit: int = 25) -> dict:
    """Recent routing decisions and the escalation rate.

    Exposed because the four thresholds are a stated hypothesis. Tuning them
    needs the decisions in front of whoever is tuning.
    """
    log_ = routing_log()
    return {
        "escalation_rate": log_.escalation_rate,
        "decisions": [
            {
                "at": r.at,
                "task_type": r.task_type,
                "escalate": r.escalate,
                "reasons": r.reasons,
                "probabilities": r.answers,
                "model": r.model,
            }
            for r in log_.recent(limit)
        ],
    }


@app.get("/verify/{human}/{task_id}", response_model=VerifyOut)
async def verify(human: str, task_id: str) -> VerifyOut:
    """Answer "is this attested human real, and did they do the task?".

    Reads the bond account from the chain rather than our own database. That
    is the point of the whole design: a buyer does not have to trust this
    endpoint, because everything it reports is on-chain and they can re-read
    it themselves from the two addresses in the response.

    What the chain establishes is identity, bond, timestamp and a verifier
    signature. The liveness decision and the grading happened off-chain,
    inside the verifier - the summary says so rather than leaving a reader to
    assume the chain checked something it cannot check.
    """
    owner = _parse_pubkey(human)
    cfg = settings()
    if not cfg.bond_program_id:
        raise HTTPException(503, "bond program not configured")

    program_id = _parse_pubkey(cfg.bond_program_id)
    try:
        bond_account, _ = derive_bond(program_id, owner, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    async with AsyncClient(cfg.rpc_url, commitment=Confirmed) as rpc:
        info = (await rpc.get_account_info(bond_account)).value

    if info is None:
        return VerifyOut(
            found=False,
            bond_account=str(bond_account),
            cluster=cfg.cluster,
            summary="No attestation exists for this human and task.",
        )

    try:
        record = decode_bond(bytes(info.data))
    except ValueError as exc:
        raise HTTPException(502, f"bond account could not be decoded: {exc}") from exc

    authority = (
        _parse_pubkey(cfg.sas_credential_authority)
        if cfg.sas_credential_authority
        else _treasury().pubkey()
    )
    credential, _ = sas.derive_credential(authority, sas.CREDENTIAL_NAME)
    schema, _ = sas.derive_schema(credential, sas.CLIP_JUDGMENT_SCHEMA_NAME)
    attestation, _ = sas.derive_attestation(credential, schema, bond_account)

    staked = record.amount > 0 and record.status is not BondStatus.SLASHED
    summary = (
        f"Verifier {record.verifier} vouched that this human completed "
        f"{record.task_id}, with {record.amount} HUMAN bonded. Liveness and "
        "grading were performed off-chain by that verifier."
    )
    if record.status is BondStatus.CHALLENGED:
        summary += " This attestation is currently challenged."
    elif record.status is BondStatus.SLASHED:
        summary += " This attestation was slashed."
    elif record.status is BondStatus.RELEASED:
        summary += " The bond behind it has since been released."

    return VerifyOut(
        found=True,
        human=str(record.human),
        task_id=record.task_id,
        status=record.status.label,
        bond_amount=record.amount,
        ui_bond_amount=record.amount / (10**cfg.human_decimals),
        attested_at=record.attested_at,
        verifier=str(record.verifier),
        liveness_proof_hash=record.liveness_proof_hash.hex(),
        bond_account=str(bond_account),
        attestation_account=str(attestation),
        cluster=cfg.cluster,
        verified_human=record.status is BondStatus.ATTESTED,
        task_complete=True,
        staked=staked,
        summary=summary,
    )


@app.get("/network/stats", response_model=NetworkStatsOut)
def network_stats() -> NetworkStatsOut:
    """Headline counts for the network screen.

    `online_now_estimate` is an off-chain heartbeat: contributors this process
    has heard from recently. It is a live estimate and is named as one on the
    wire, because it is the single number here that nobody can verify and the
    easiest to accidentally present as proven.

    The other two are counted from local records in this build. They become
    on-chain counts once attestations are being minted; until then reporting
    them as on-chain would be the overclaim this project keeps avoiding, so
    `source` says where they came from.
    """
    stats = network_tracker().snapshot()
    return NetworkStatsOut(
        online_now_estimate=stats.online_now,
        acted_today=stats.acted_today,
        work_proven=stats.work_proven,
        source=stats.source,
    )


@app.get("/network/leaderboard", response_model=LeaderboardOut)
def leaderboard(limit: int = 25) -> LeaderboardOut:
    """Ranked by quality, with volume as a tiebreak only.

    Accuracy dominates on purpose. A board a farm could climb by doing more
    work would reward exactly the behaviour the bond exists to punish, so
    volume can only separate contributors who are already equally accurate.
    See `leaderboard.py`.
    """
    cfg = settings()
    rows = network_tracker().leaderboard(limit=max(1, min(limit, 100)))
    return LeaderboardOut(
        rows=[
            LeaderboardRow(
                rank=i + 1,
                human=row.human,
                human_short=row.short,
                quality_score=round(row.score, 4),
                accuracy=round(row.accuracy, 4),
                work_count=row.work_count,
                bond=row.bond,
                ui_bond=row.bond / (10**cfg.human_decimals),
            )
            for i, row in enumerate(rows)
        ],
        scored_on="rolling gold-standard accuracy, with volume as a tiebreak",
    )


@app.get("/contributor/{contributor}")
def contributor(contributor: str) -> dict[str, object]:
    _parse_pubkey(contributor)
    cfg = settings()
    state = task_store().state(contributor)
    eligibility = state.record.eligibility(cfg.min_accuracy_to_claim)
    gate = _claim_gate(contributor)
    referral_unclaimed = referrals().unclaimed(contributor)
    pose_balance = _pose_balance(contributor)
    clip_balance = _clip_balance(contributor)
    total = state.balance + referral_unclaimed + pose_balance + clip_balance
    return {
        "contributor": contributor,
        "balance": state.balance,
        "ui_balance": state.balance / (10**cfg.usdc_decimals),
        "pose_balance": pose_balance,
        "ui_pose_balance": pose_balance / (10**cfg.usdc_decimals),
        "clip_balance": clip_balance,
        "ui_clip_balance": clip_balance / (10**cfg.usdc_decimals),
        "clip_qualified": _clip_qualified(contributor),
        "referral_unclaimed": referral_unclaimed,
        "ui_referral_unclaimed": referral_unclaimed / (10**cfg.usdc_decimals),
        "total_claimable": total,
        "ui_total_claimable": total / (10**cfg.usdc_decimals),
        "solved": len(state.seen) - len(state.outstanding),
        "accuracy": eligibility.accuracy,
        "gold_samples": eligibility.samples,
        "claimable": gate.allowed and total > 0,
        "reason": gate.reason,
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
    treasury = _treasury()
    mint, payout_decimals, payout_symbol = _payout_mint()

    # The blockhash is fetched *before* the balances are read, which is the only
    # await in this handler. Doing it the other way round - read, await, zero -
    # opens a window where a concurrent submit loses its reward, or a second
    # claim reads the same balance and both transactions are signed for the full
    # amount. Confirmed rather than the default finalized, so the hash is as
    # fresh as it can be; the remaining work below is pure CPU and costs
    # microseconds of its ~60s validity.
    async with AsyncClient(cfg.rpc_url, commitment=Confirmed) as rpc:
        blockhash = (await rpc.get_latest_blockhash()).value.blockhash

    snapshot = _snapshot_and_debit(body.contributor)

    # Debited before the transaction exists, so anything that fails from here
    # has to hand the money back. A declined wallet approval still loses the
    # credit - the fix for that is a claim record keyed on the signature, which
    # is listed in PLATFORM.md as not yet built.
    try:
        tx = build_claim_transaction(
            contributor=contributor_key,
            treasury=treasury.pubkey(),
            mint=mint,
            amount=snapshot.total,
            decimals=payout_decimals,
            blockhash=blockhash,
        )
        treasury_sign(tx, treasury)
    except Exception:
        _restore(body.contributor, snapshot)
        raise

    amount = snapshot.total
    referral_amount = snapshot.referral
    pose_amount = snapshot.pose

    return ClaimPrepareOut(
        transaction=serialize_for_wallet(tx),
        amount=amount,
        ui_amount=amount / (10**payout_decimals),
        mint=str(mint),
        payout_symbol=payout_symbol,
        fee_payer=body.contributor,
        cluster=cfg.cluster,
        task_amount=amount - referral_amount - pose_amount,
        referral_amount=referral_amount,
        pose_amount=pose_amount,
    )

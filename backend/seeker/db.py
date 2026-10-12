"""Durable pilot schema. Apply with `python -m seeker.migrate`; no startup DDL."""

import time
import uuid
from contextlib import contextmanager

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
)


def uid():
    return uuid.uuid4().hex


def now():
    return int(time.time())


class Base(DeclarativeBase):
    pass


class Actor(Base):
    __tablename__ = "seeker_actors"
    wallet: Mapped[str] = mapped_column(String(44), primary_key=True)
    worker: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer: Mapped[bool] = mapped_column(Boolean, default=False)
    # Self-attested over-18 declaration recorded at enrollment. A claim, not a
    # cryptographic proof — never treated as one.
    over_18: Mapped[bool] = mapped_column(Boolean, default=False)
    # Enrollment is an operator decision, never a claimed proof of humanity.
    # Capture v2: cumulative accepted open-uploads, denormalized for fast /me.
    # The rolling acceptance rate is computed from Submission rows (see api.py).
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    # Capture v2: server-side liveness gate. Set once a wallet completes a
    # server-issued liveness session (see /liveness/complete). Open uploads are
    # refused until this is true, so liveness is enforced server-side rather
    # than being a client-only claim.
    liveness_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Capture bond gate (migration 0006, CAPTURE-BOND-SPEC). All server-recorded:
    # bonded == the devnet bond was deposited; quality_checks == completed free
    # peer-reviews; skr_funded == the devnet test-SKR faucet ran. The gate is
    # ``bonded OR quality_checks >= QUALITY_CHECKS_REQUIRED`` (see api.py).
    bonded: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_checks: Mapped[int] = mapped_column(Integer, default=0)
    skr_funded: Mapped[bool] = mapped_column(Boolean, default=False)
    # Capture v2: accrued-but-unsettled payout in USDC base units. Accepted
    # uploads credit this off-chain; a batched /bond/settle transfers the whole
    # balance on-chain in one transaction (fee minimization: one treasury tx per
    # settle, not one per accepted upload).
    pending_usdc: Mapped[int] = mapped_column(BigInteger, default=0)
    # A settle in flight: moved here (and committed) before the treasury
    # transfer is broadcast, so a dropped/lost transaction cannot lose or
    # double-pay earnings (finding 1). Cleared on confirmed settle, restored on
    # failure.
    settling_usdc: Mapped[int] = mapped_column(BigInteger, default=0)
    # ---- Judgment product (RLHF preference judging) ----
    # calibrated == passed the N-pair calibration gate (unpaid) and may stake +
    # judge. agreement_rate == rolling fraction of resolved judgments this judge
    # was aligned on (last judge_window). judged_count == resolved judgments
    # participated in. staked_skr == the SKR bond escrowed on deposit (mirror).
    # warnings == mirror of the on-chain bond.warnings ladder (0 clean, 1 warned,
    # >= 2 slashed).
    calibrated: Mapped[bool] = mapped_column(Boolean, default=False)
    agreement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    judged_count: Mapped[int] = mapped_column(Integer, default=0)
    staked_skr: Mapped[int] = mapped_column(BigInteger, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)


class Challenge(Base):
    __tablename__ = "seeker_challenges"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wallet: Mapped[str] = mapped_column(String(44))
    message: Mapped[str] = mapped_column(String(1024))
    expires: Mapped[int] = mapped_column(BigInteger)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Login(Base):
    __tablename__ = "seeker_sessions"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    wallet: Mapped[str] = mapped_column(ForeignKey(Actor.wallet))
    expires: Mapped[int] = mapped_column(BigInteger)


class Rate(Base):
    __tablename__ = "seeker_rates"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    bucket: Mapped[int] = mapped_column(BigInteger)
    count: Mapped[int] = mapped_column(Integer)


class Bounty(Base):
    __tablename__ = "seeker_bounties"
    __table_args__ = (UniqueConstraint("requester", "request_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requester: Mapped[str] = mapped_column(ForeignKey(Actor.wallet))
    request_key: Mapped[str] = mapped_column(String(64))
    body_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16), default="object")
    taxonomy: Mapped[dict] = mapped_column(JSON)
    reward: Mapped[int] = mapped_column(BigInteger)
    slots: Mapped[int] = mapped_column(Integer)
    deadline: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="draft")


class Submission(Base):
    __tablename__ = "seeker_submissions"
    __table_args__ = (
        UniqueConstraint("bounty_id", "worker"),
        UniqueConstraint("bounty_id", "media_hash"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    # Nullable: an open (no-bounty) upload has no bounty (Capture v2 pivot).
    bounty_id: Mapped[str | None] = mapped_column(ForeignKey(Bounty.id), index=True)
    worker: Mapped[str] = mapped_column(ForeignKey(Actor.wallet))
    expires: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="claimed")
    # The upload's primary kind for open submissions (object|place|action);
    # for bounty submissions this mirrors Bounty.kind and is informational.
    kind: Mapped[str] = mapped_column(String(16), default="object")
    media_hash: Mapped[str | None] = mapped_column(String(64))
    perceptual: Mapped[str | None] = mapped_column(String(16))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    # Deferred: the encrypted blob is the largest column on the table and is
    # only needed by the media GET endpoint and the offline keypoint job.
    # Duplicate checks, rolling-acceptance and history queries therefore never
    # pull megabytes of ciphertext they do not read.
    encrypted_media: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    moderation: Mapped[dict | None] = mapped_column(JSON)
    labels: Mapped[list | None] = mapped_column(JSON)
    # Optional secondary labels (expressions / postures / environment) resolved
    # server-side against the registry; collected metadata, never a payout gate.
    secondary: Mapped[dict | None] = mapped_column(JSON)
    # Capture v2 optional capture metadata (surface_type/lighting/weather/
    # ego_motion), resolved server-side against the string-keyed registries.
    # Named capture_metadata because `metadata` collides with DeclarativeBase.
    capture_metadata: Mapped[dict | None] = mapped_column(JSON)
    label_hash: Mapped[str | None] = mapped_column(String(64))
    # Server-write-only COCO-17 pose; written by the offline keypoint job, never
    # by a seeker (no request schema accepts it).
    keypoints: Mapped[list | None] = mapped_column(JSON)
    # Capture v2 judge outcome: accepted (bool), the reason string, and when it
    # was judged. None/absent until the judge has run.
    accepted: Mapped[bool | None] = mapped_column(Boolean)
    judged_at: Mapped[int | None] = mapped_column(BigInteger)
    verdict_reason: Mapped[str | None] = mapped_column(String(512))
    payout_usdc: Mapped[int | None] = mapped_column(BigInteger)
    # Base58 signature of the treasury -> worker USDC transfer recorded on
    # accept (real on-chain settlement). NULL until settlement is recorded.
    payout_signature: Mapped[str | None] = mapped_column(String(88))
    level_after: Mapped[int | None] = mapped_column(Integer)


class Review(Base):
    __tablename__ = "seeker_reviews"
    __table_args__ = (UniqueConstraint("submission_id", "reviewer"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey(Submission.id), index=True)
    reviewer: Mapped[str] = mapped_column(ForeignKey(Actor.wallet))
    labels: Mapped[list] = mapped_column(JSON)
    secondary: Mapped[dict | None] = mapped_column(JSON)
    # Open-upload peer reviews carry a boolean verdict (accept/reject) instead of
    # full labels; NULL for the operator bounty-review path.
    accepted: Mapped[bool | None] = mapped_column(Boolean)


class Violation(Base):
    """One punished media-policy violation, deduped by (worker, media_hash).

    Finding 4: without this journal, retrying the same rejected upload could
    count as another strike, and concurrent failures could read the same warning
    count. Recording the punished hash makes enforcement idempotent per upload.
    """
    __tablename__ = "seeker_violations"
    __table_args__ = (UniqueConstraint("worker", "media_hash"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    worker: Mapped[str] = mapped_column(ForeignKey(Actor.wallet), index=True)
    media_hash: Mapped[str] = mapped_column(String(64))
    created: Mapped[int] = mapped_column(BigInteger)


class Prepared(Base):
    __tablename__ = "seeker_prepared"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    wallet: Mapped[str] = mapped_column(ForeignKey(Actor.wallet), index=True)
    action: Mapped[str] = mapped_column(String(24))
    target: Mapped[str] = mapped_column(String(44), index=True)
    message_hash: Mapped[str] = mapped_column(String(64))
    transaction: Mapped[str] = mapped_column(String(4096))
    last_valid_height: Mapped[int] = mapped_column(BigInteger)
    signature: Mapped[str | None] = mapped_column(String(88), unique=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class JudgmentBatch(Base):
    """A batch of pairs whose resolved preferences commit one Merkle root
    on-chain (provenance anchor for the RLHF preference dataset)."""

    __tablename__ = "judgment_batches"
    batch_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    merkle_root: Mapped[str | None] = mapped_column(String(64))
    # anchored == the merkle_root was confirmed on-chain via post_batch. Set
    # only after a successful confirm so a failed final anchor is durably
    # retried (finding #10) instead of swallowed.
    anchored: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(BigInteger, default=now)


class JudgmentPair(Base):
    """One A/B preference or 1-5 rating task, sent to K judges."""

    __tablename__ = "judgment_pairs"
    pair_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey(JudgmentBatch.batch_id), index=True)
    media_type: Mapped[str] = mapped_column(String(16), default="image")
    task_type: Mapped[str] = mapped_column(String(16), default="preference")
    output_a_url: Mapped[str | None] = mapped_column(String(512))
    output_b_url: Mapped[str | None] = mapped_column(String(512))
    rubric: Mapped[str | None] = mapped_column(String(1024))
    k: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(16), default="open")
    preference: Mapped[str | None] = mapped_column(String(8))
    agreement: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[int] = mapped_column(BigInteger, default=now)


class Judgment(Base):
    """One judge's answer to one pair. One judge cannot answer a pair twice."""

    __tablename__ = "judgments"
    __table_args__ = (UniqueConstraint("pair_id", "wallet"),)
    judgment_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    pair_id: Mapped[str] = mapped_column(ForeignKey(JudgmentPair.pair_id), index=True)
    wallet: Mapped[str] = mapped_column(ForeignKey(Actor.wallet), index=True)
    choice: Mapped[str] = mapped_column(String(16))
    rating: Mapped[int | None] = mapped_column(Integer)
    aligned: Mapped[bool | None] = mapped_column(Boolean)
    # consumed == this judgment was already factored into a reroute (a neutral
    # "cant_tell"/"tie" vote). Consumed judgments do not re-trigger a reroute
    # and are excluded from the final consensus denominator.
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    earned_skr: Mapped[int] = mapped_column(BigInteger, default=0)
    payout_signature: Mapped[str | None] = mapped_column(String(88))
    # settling == the earned_skr obligation was committed to the ledger but its
    # mint transaction has not yet been confirmed on-chain. Payout obligations
    # are persisted BEFORE broadcast so a partial payout can never be lost or
    # double-paid (finding 10 #1); cleared once the mint confirms.
    settling: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[int] = mapped_column(BigInteger, default=now)


class CalibrationPair(Base):
    """A known-consensus pair used to gate new judges before they can stake.

    ``known_choice`` is "a" | "b" for preference tasks, or the known rating as a
    decimal string (e.g. "4") for rating tasks."""

    __tablename__ = "calibration_pairs"
    pair_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    known_choice: Mapped[str] = mapped_column(String(16))
    known_consensus: Mapped[float] = mapped_column(Float, default=1.0)
    media_type: Mapped[str] = mapped_column(String(16), default="image")
    task_type: Mapped[str] = mapped_column(String(16), default="preference")
    output_a_url: Mapped[str | None] = mapped_column(String(512))
    output_b_url: Mapped[str | None] = mapped_column(String(512))
    rubric: Mapped[str | None] = mapped_column(String(1024))


class CalibrationAnswer(Base):
    """A judge's answer to a calibration pair; drives calibration progress."""

    __tablename__ = "calibration_answers"
    __table_args__ = (UniqueConstraint("pair_id", "wallet"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    pair_id: Mapped[str] = mapped_column(ForeignKey(CalibrationPair.pair_id), index=True)
    wallet: Mapped[str] = mapped_column(ForeignKey(Actor.wallet), index=True)
    choice: Mapped[str] = mapped_column(String(16))
    rating: Mapped[int | None] = mapped_column(Integer)
    correct: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[int] = mapped_column(BigInteger, default=now)


def connect(url):
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 30}
        if url.startswith("sqlite")
        else {},
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_connection(dbapi_connection, _):
            dbapi_connection.isolation_level = None
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine, "begin")
        def sqlite_begin(conn):
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


class Database:
    def __init__(self, url):
        self.engine = connect(url)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self):
        with self.factory.begin() as session:
            yield session

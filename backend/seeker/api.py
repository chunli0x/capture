"""Run: uvicorn seeker.api:production_app --factory. Wallet ownership is mandatory."""

import hashlib
import json
import secrets
from itertools import combinations
from typing import Annotated, NoReturn, Union

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from solders.pubkey import Pubkey
from solders.signature import Signature
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from .chain import Chain, ChainUnavailable
from .config import Settings
from .db import (
    Actor,
    Bounty,
    Challenge,
    Database,
    Login,
    Prepared,
    Rate,
    Review,
    Submission,
    now,
)
from .media import (
    MediaCipher,
    MediaRejected,
    Moderation,
    canonicalize,
    canonicalize_video,
    extract_video_frame,
)
from .schemas import (
    ActionLabels,
    Confirm,
    CreateBounty,
    Enrollment,
    Labels,
    LivenessComplete,
    LivenessSession,
    OpenReview,
    OpenSubmission,
    PlaceLabels,
    Verify,
    Wallet,
    labels_agree,
)
from .leveling import ROLLING_WINDOW, level_info
from .judge import JudgeUnavailable, StubJudge, build_judge
from .payout import payout_units
from . import taxonomy

# Liveness sessions are self-contained (stdlib only). Reuse the same module so
# the wire shape and replay rules match.
from .liveness import (
    LivenessError,
    LivenessSessionStore,
    SessionAlreadyUsed,
    SessionExpired,
    UnknownSession,
)

import functools


# Capture bond gate (CAPTURE-BOND-SPEC): a new user must either deposit the SKR
# bond OR complete this many free peer-reviews before their first upload.
QUALITY_CHECKS_REQUIRED = 3


@functools.lru_cache(maxsize=1)
def liveness_sessions() -> LivenessSessionStore:
    return LivenessSessionStore()


def fail(status, detail) -> NoReturn:
    raise HTTPException(status, detail)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def lock(db, cls, key):
    # ``populate_existing`` forces the ORM to re-read the row from the freshly
    # acquired SELECT ... FOR UPDATE instead of returning an identity-map cache
    # hit. Without it, a handler that loaded a row before taking the lock (e.g.
    # ``labels()`` reading the submission to pick the open/bounty branch, then
    # ``own_open``/``authorized_submission`` locking it) would observe stale
    # state and let two concurrent requests both pass an immutable-state guard.
    row = db.scalar(
        select(cls)
        .where(getattr(cls, next(iter(cls.__table__.primary_key.columns)).name) == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        fail(404, "Resource not found")
    return row


def insert_once(db, cls, values):
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    db.execute(insert(cls).values(**values).on_conflict_do_nothing())


def rate(db, key, limit, period=60):
    key = digest(key.encode())
    bucket = now() // period
    insert_once(db, Rate, {"key": key, "bucket": bucket, "count": 0})
    row = lock(db, Rate, key)
    if row.bucket != bucket:
        row.bucket, row.count = bucket, 0
    if row.count >= limit:
        fail(429, "Rate limit reached; retry later")
    row.count += 1


def rolling_acceptance(db, wallet):
    """Rolling acceptance rate (fraction) over the last ROLLING_WINDOW judged
    submissions. 0.0 when there are none."""
    rows = db.scalars(
        select(Submission.accepted)
        .where(Submission.worker == wallet, Submission.accepted.is_not(None))
        .order_by(Submission.judged_at.desc())
        .limit(ROLLING_WINDOW)
    ).all()
    if not rows:
        return 0.0
    return sum(1 for a in rows if a) / len(rows)


def contributor_level(db, wallet):
    """The v2 level block for ``/me``/``/actor`` (contract §6 field names)."""
    actor = db.get(Actor, wallet)
    accepted_count = actor.accepted_count if actor else 0
    return level_info(accepted_count, rolling_acceptance(db, wallet))


def bounty_view(b):
    return {
        "id": b.id,
        "requester": b.requester,
        "title": b.title,
        "kind": b.kind,
        "categories": b.taxonomy,
        "reward_usdc_units": b.reward,
        "slots": b.slots,
        "deadline": b.deadline,
        "status": b.status,
        "network": "test-only",
        "fee_usdc_units": 0,
    }


def submission_view(s, b, actor):
    result = {
        "id": s.id,
        "bounty_id": b.id if b else None,
        "worker": s.worker,
        "status": s.status,
        "expires": s.expires,
        "media_hash": s.media_hash,
        "keypoints": s.keypoints,
    }
    if b is None:
        # Capture v2 open upload: no bounty to join. Expose the stored judge
        # verdict so a retrying client can recover its outcome instead of a 409.
        result["kind"] = s.kind
        result["accepted"] = s.accepted
        result["verdict_reason"] = s.verdict_reason
        result["payout_usdc"] = s.payout_usdc
        result["level_after"] = s.level_after
        result["judged_at"] = s.judged_at
        if actor.wallet == s.worker:
            result["boxes"] = s.labels
            result["secondary"] = s.secondary or {}
        return result
    result["bounty"] = bounty_view(b)
    if actor.wallet in {s.worker, b.requester}:
        result["boxes"] = s.labels
        result["secondary"] = s.secondary or {}
    return result


def create_app(settings: Settings, *, chain=None, moderator=None, judge=None):
    app = FastAPI(title="Seeker object pilot", version="0.1.0")
    database = Database(settings.database_url)
    # Apply schema on boot so a restart against a pre-v2 DB can never serve a
    # stale schema (the 500 we hit when a restart loaded new code over an old
    # database). Idempotent: create_all + numbered ALTER TABLEs are no-ops on a
    # current DB.
    from .db import Base
    from .migrate import apply_migrations

    Base.metadata.create_all(database.engine)
    apply_migrations(database.engine)
    chain = chain or Chain(settings)
    moderator = moderator or Moderation(settings)
    judge = judge or build_judge(settings)
    cipher = MediaCipher(settings.media_key)
    app.state.database, app.state.chain = database, chain
    app.state.judge = judge

    @app.exception_handler(ChainUnavailable)
    async def unavailable(_, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # `keypoints` is server-write-only: any seeker attempt to submit it is a
        # hard 400, distinct from other schema rejections (which keep the
        # standard 422 body).
        if any("keypoints" in str(err.get("loc", ())) for err in exc.errors()):
            return JSONResponse(
                status_code=400,
                content={"detail": "keypoints is server-generated and cannot be submitted"},
            )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(IntegrityError)
    async def conflict(_, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=409,
            content={"detail": "Concurrent or duplicate operation; reload and retry"},
        )

    def current(authorization: Annotated[str | None, Header()] = None):
        if not authorization or not authorization.startswith("Bearer "):
            fail(401, "Wallet sign-in required")
        with database.transaction() as db:
            login = db.get(Login, digest(authorization[7:].encode()))
            if not login or login.expires <= now():
                fail(401, "Session expired or invalid")
            return db.get(Actor, login.wallet)

    Auth = Annotated[Actor, Depends(current)]

    def authorized_submission(db, sid, actor):
        # Bounty before submission is the global lock order used by every writer.
        s = db.get(Submission, sid)
        if not s:
            fail(404, "Submission not found")
        b = lock(db, Bounty, s.bounty_id)
        s = lock(db, Submission, sid)
        if actor.wallet not in {s.worker, b.requester} and not actor.reviewer:
            fail(403, "Media is private")
        return s, b

    def own_active(db, sid, actor):
        actor = lock(db, Actor, actor.wallet)
        if not actor.worker:
            fail(403, "Worker enrollment required")
        s, b = authorized_submission(db, sid, actor)
        if s.worker != actor.wallet:
            fail(403, "Only this claim's worker may upload or label")
        if b.deadline <= now() or s.expires <= now():
            fail(409, "Claim expired")
        return s, b

    def own_open(db, sid, actor):
        """Lock + authorize an open (no-bounty) submission for its worker."""
        actor = lock(db, Actor, actor.wallet)
        if not actor.worker:
            fail(403, "Worker enrollment required")
        s = lock(db, Submission, sid)
        if s.bounty_id is not None:
            fail(404, "Submission not found")
        if s.worker != actor.wallet:
            fail(403, "Only this upload's worker may edit it")
        return s

    def own_media(db, sid, actor):
        """Lock + authorize a submission for media upload (open or bounty).

        Returns ``(s, is_video)``. ``is_video`` is drawn from the open
        submission's ``kind``, or the bounty's kind for bounty submissions.
        """
        actor = lock(db, Actor, actor.wallet)
        if not actor.worker:
            fail(403, "Worker enrollment required")
        # bounty_id is immutable; read it (unlocked) only to pick the branch so
        # the bounty path can keep the global Bounty-before-Submission lock
        # order. The locked loads below re-read fresh state.
        branch = db.execute(
            select(Submission.id, Submission.bounty_id).where(Submission.id == sid)
        ).first()
        if branch is None:
            fail(404, "Submission not found")
        _, bounty_id = branch
        if bounty_id is None:
            s = lock(db, Submission, sid)
            if s.worker != actor.wallet:
                fail(403, "Only this upload's worker may edit it")
            if s.expires <= now():
                fail(409, "Upload expired")
            return s, s.kind == "action"
        b = lock(db, Bounty, bounty_id)
        s = lock(db, Submission, sid)
        if s.worker != actor.wallet:
            fail(403, "Only this claim's worker may upload or label")
        if b.deadline <= now() or s.expires <= now():
            fail(409, "Claim expired")
        return s, b.kind == "action"

    def _check_category(kind, cid):
        try:
            taxonomy.resolve(kind, [cid])
        except ValueError as exc:
            fail(422, str(exc))

    def resolve_open_metadata(body):
        """Resolve v2 optional capture metadata against the string-keyed
        registries. Returns ``{namespace: {id,name,kind}, ego_motion: bool}``."""
        metadata = {"ego_motion": bool(body.ego_motion)}
        for namespace, value in (
            ("surface_type", body.surface_type),
            ("lighting", body.lighting),
            ("weather", body.weather),
        ):
            if not value:
                continue
            try:
                metadata[namespace] = taxonomy.resolve_metadata(namespace, value)
            except ValueError as exc:
                fail(422, str(exc))
        return metadata

    def validate_open_labels(body, s):
        """Validate labels for an open upload. Enforces posture (required in
        v2), resolves secondary + metadata, and returns
        ``(labels, secondary, metadata)``."""
        if body.media_hash != s.media_hash or not s.encrypted_media:
            fail(409, "Labels must reference the approved immutable media")
        if not body.postures:
            fail(422, "posture is required")
        secondary = {}
        for dim, ids in (
            ("expressions", body.expressions),
            ("postures", body.postures),
            ("environment", body.environment),
        ):
            if not ids:
                continue
            try:
                secondary[dim] = taxonomy.resolve_secondary(dim, ids)
            except ValueError as exc:
                fail(422, str(exc))
        metadata = resolve_open_metadata(body)
        kind = s.kind
        if isinstance(body, PlaceLabels):
            if kind != "place":
                fail(422, "This upload expects object boxes, not a scene label")
            _check_category(kind, body.scene.category_id)
            return {"scene": {"category_id": body.scene.category_id}}, secondary, metadata
        if isinstance(body, ActionLabels):
            if kind != "action":
                fail(422, "This upload expects object boxes, not an action label")
            span = body.action
            _check_category(kind, span.category_id)
            if s.duration_ms is None:
                fail(409, "Media duration is unavailable")
            if span.end_ms > s.duration_ms:
                fail(422, "Action trim exceeds the clip duration")
            return {
                "action": {
                    "category_id": span.category_id,
                    "start_ms": span.start_ms,
                    "end_ms": span.end_ms,
                }
            }, secondary, metadata
        if kind != "object":
            fail(422, "This upload expects a single scene or action label, not boxes")
        boxes = [box.model_dump() for box in body.boxes]
        for box in boxes:
            _check_category(kind, box["category_id"])
        if len({canonical(box) for box in boxes}) != len(boxes):
            fail(422, "Duplicate boxes are not allowed")
        return boxes, secondary, metadata

    def open_labels(db, sid, body, actor):
        """Open-upload submit: judge -> accept/reject -> record auto-pay.

        On accept the payout is recorded (base rate x level multiplier x label
        premium, in USDC base units) and the worker's accepted_count advances;
        on reject the bond is recorded as slashed (payout 0). The devnet
        TEST-USDC treasury transfer and on-chain bond slash are settlement
        seams behind this ledger record, matching the judge's env-gated design.
        """
        s = own_open(db, sid, actor)
        if s.status in {"accepted", "rejected"}:
            # Idempotent retry: the label was already committed and judged.
            # Return the stored verdict instead of a 409 so a client whose
            # response was lost can recover its outcome without a double pay.
            return {
                "id": s.id,
                "status": s.status,
                "verdict": {"accepted": s.accepted, "reason": s.verdict_reason},
                "payout_usdc": s.payout_usdc,
                "level_after": s.level_after,
            }
        if s.status == "review":
            # Idempotent retry for a free-tier upload already dropped into the
            # peer-review queue: return its state rather than a 409.
            return {"id": s.id, "status": "review"}
        if s.expires <= now():
            fail(409, "Upload expired")
        if s.status != "claimed" or s.labels is not None:
            fail(409, "Submission is immutable")
        boxes, secondary, metadata = validate_open_labels(body, s)

        worker = lock(db, Actor, actor.wallet)
        if not worker.bonded:
            # No free tier yet. A non-bonded worker cannot create a submission
            # through the gate above; fail closed here rather than route to the
            # (not-yet-launched) peer-review queue.
            fail(403, "Bond required — deposit the SKR bond to capture")

        # Decode the stored media so the judge sees actual pixels, not just the
        # media-hash presence flag. For an action video, extract one frame.
        judge_image: bytes | None = None
        if s.encrypted_media and s.media_hash:
            decoded = cipher.decrypt(s.encrypted_media, s.media_hash)
            if s.kind == "action":
                try:
                    judge_image = extract_video_frame(decoded, s.duration_ms)
                except MediaRejected:
                    judge_image = None
            else:
                judge_image = decoded

        # Judge budget guard: the VLM is the dominant token cost, so bound
        # judged uploads per wallet per day (configurable; 0 disables).
        if settings.judge_daily_cap > 0:
            rate(db, "judge:" + actor.wallet, settings.judge_daily_cap, 86400)

        try:
            verdict = judge.judge(
                s.kind,
                boxes,
                secondary,
                metadata,
                s.duration_ms,
                s.media_hash is not None,
                judge_image,
            )
        except JudgeUnavailable as exc:
            # Fail-closed: a real judge that cannot be reached must never accept
            # silently, and must not slash the worker. Leave the submission
            # claimable so the client can retry when the judge recovers.
            fail(503, f"Quality judge unavailable: {exc}")

        level_before = contributor_level(db, actor.wallet)["level"]
        payout = 0
        if verdict.accepted:
            complete = bool(secondary.get("postures")) and bool(secondary.get("environment"))
            payout = payout_units(level_before, s.kind, s.duration_ms, complete)
            worker = lock(db, Actor, actor.wallet)
            worker.accepted_count += 1
            s.status, s.accepted = "accepted", True
        else:
            s.status, s.accepted = "rejected", False

        s.labels = boxes
        s.secondary = secondary
        s.capture_metadata = metadata
        s.label_hash = digest(canonical(boxes))
        s.judged_at = now()
        s.verdict_reason = verdict.reason
        s.payout_usdc = payout
        s.level_after = contributor_level(db, actor.wallet)["level"]

        return {
            "id": s.id,
            "status": s.status,
            "verdict": {"accepted": verdict.accepted, "reason": verdict.reason},
            "payout_usdc": payout,
            "level_after": s.level_after,
        }

    def validate_labels(body, s, b):
        if body.media_hash != s.media_hash or not s.encrypted_media:
            fail(409, "Labels must reference the approved immutable media")
        secondary = {}
        for dim, ids in (
            ("expressions", body.expressions),
            ("postures", body.postures),
            ("environment", body.environment),
        ):
            if not ids:
                continue
            try:
                secondary[dim] = taxonomy.resolve_secondary(dim, ids)
            except ValueError as exc:
                fail(422, str(exc))
        if isinstance(body, PlaceLabels):
            if b.kind != "place":
                fail(422, "This bounty expects object boxes, not a scene label")
            cat = body.scene.category_id
            if cat not in {c["id"] for c in b.taxonomy}:
                fail(422, "Unknown category for this taxonomy")
            return {"scene": {"category_id": cat}}, secondary
        if isinstance(body, ActionLabels):
            if b.kind != "action":
                fail(422, "This bounty expects object boxes, not an action label")
            span = body.action
            if span.category_id not in {c["id"] for c in b.taxonomy}:
                fail(422, "Unknown category for this taxonomy")
            if s.duration_ms is None:
                fail(409, "Media duration is unavailable")
            if span.end_ms > s.duration_ms:
                fail(422, "Action trim exceeds the clip duration")
            return {
                "action": {
                    "category_id": span.category_id,
                    "start_ms": span.start_ms,
                    "end_ms": span.end_ms,
                }
            }, secondary
        if b.kind != "object":
            fail(422, "This bounty expects a single scene or action label, not boxes")
        boxes = [box.model_dump() for box in body.boxes]
        if any(
            box["category_id"] not in {c["id"] for c in b.taxonomy} for box in boxes
        ):
            fail(422, "Unknown category for this taxonomy")
        if len({canonical(box) for box in boxes}) != len(boxes):
            fail(422, "Duplicate boxes are not allowed")
        return boxes, secondary

    @app.get("/health")
    def health():
        """Real readiness probe: database connect, schema applied, judge
        configured-or-stubbed, chain reachable. 200 when all pass, 503
        otherwise, with a per-check breakdown."""
        status = 200
        checks = {}

        # 1. Database connection.
        try:
            with database.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "down"
            status = 503

        # 2. Schema applied (core tables present).
        try:
            from sqlalchemy import inspect

            tables = set(inspect(database.engine).get_table_names())
            required = {
                "seeker_actors",
                "seeker_submissions",
                "seeker_bounties",
                "seeker_prepared",
            }
            missing = required - tables
            checks["schema"] = "applied" if not missing else "missing " + ",".join(sorted(missing))
            if missing:
                status = 503
        except Exception:
            checks["schema"] = "unavailable"
            status = 503

        # 3. Judge configured (real) or stubbed.
        if judge is None:
            checks["judge"] = "missing"
            status = 503
        else:
            checks["judge"] = "stubbed" if isinstance(judge, StubJudge) else "configured"

        # 4. Chain reachable (program initialized and config matches).
        try:
            chain.check_environment()
            checks["chain"] = "reachable"
        except Exception:
            checks["chain"] = "unreachable"
            status = 503

        return JSONResponse(
            status_code=status,
            content={
                "service": "seeker",
                "network": settings.cluster,
                "production_ready": status == 200,
                "checks": checks,
            },
        )

    @app.get("/taxonomy")
    def get_taxonomy():
        # Closed vocabulary is server-owned and public: clients read valid ids
        # here and can never mint a category.
        return {"categories": taxonomy.all_categories()}

    @app.post("/auth/challenge")
    def challenge(body: Wallet, request: Request):
        nonce, expires = secrets.token_hex(32), now() + 120
        message = f"{settings.domain} requests Seeker test-pilot sign-in.\nWallet: {body.wallet}\nNetwork: {settings.cluster}\nNonce: {nonce}\nExpires: {expires}\nThis does not authorize any token transfer."
        with database.transaction() as db:
            rate(db, "ip:" + (request.client.host if request.client else "unknown"), 30)
            rate(db, "login:" + body.wallet, 10)
            db.add(
                Challenge(
                    id=nonce, wallet=body.wallet, message=message, expires=expires
                )
            )
        return {"challenge_id": nonce, "message": message, "expires": expires}

    @app.post("/auth/verify")
    def verify(body: Verify):
        with database.transaction() as db:
            c = lock(db, Challenge, body.challenge_id)
            if c.used or c.expires <= now():
                fail(401, "Challenge expired or already consumed")
            try:
                valid = Signature.from_string(body.signature).verify(
                    Pubkey.from_string(c.wallet), c.message.encode()
                )
            except ValueError:
                valid = False
            if not valid:
                fail(401, "Signature does not match this wallet and challenge")
            c.used = True
            insert_once(
                db, Actor,
                {"wallet": c.wallet, "worker": False, "reviewer": False, "over_18": body.over_18},
            )
            token = secrets.token_urlsafe(32)
            expires = now() + settings.session_seconds
            db.add(
                Login(digest=digest(token.encode()), wallet=c.wallet, expires=expires)
            )
        return {"token": token, "wallet": c.wallet, "expires": expires}

    @app.post("/auth/logout")
    def logout(actor: Auth, authorization: Annotated[str, Header()]):
        with database.transaction() as db:
            login = db.get(Login, digest(authorization[7:].encode()))
            if login:
                db.delete(login)
        return {"signed_out": True}

    @app.get("/me")
    def me(actor: Auth):
        with database.transaction() as db:
            level = contributor_level(db, actor.wallet)
        return {
            "wallet": actor.wallet,
            "worker": actor.worker,
            "reviewer": actor.reviewer,
            "over_18": actor.over_18,
            "identity_status": "operator-enrolled"
            if actor.worker or actor.reviewer
            else "wallet-only",
            "bond_test_skr_units": settings.min_bond,
            # Capture bond gate: bonded once the bond is deposited. No free tier
            # yet, so unlocked == bonded (peer reviews launch later and will
            # re-add the quality-checks path).
            "bonded": actor.bonded,
            "quality_checks": actor.quality_checks,
            "quality_checks_required": QUALITY_CHECKS_REQUIRED,
            "unlocked": actor.bonded,
            **level,
        }

    @app.post("/liveness/session")
    def liveness_session(body: LivenessSession, actor: Auth):
        # Capture v2: a fresh, single-use motion challenge before the first
        # upload. `contributor` is the wallet; the challenge is server-chosen so
        # one recorded run cannot be replayed. The contributor must match the
        # authenticated caller so a proof can never be issued for someone
        # else's wallet.
        Pubkey.from_string(body.contributor)
        if body.contributor != actor.wallet:
            fail(403, "Liveness contributor must match the authenticated wallet")
        with database.transaction() as db:
            rate(db, "liveness-session:" + actor.wallet, 10, 3600)
        store = liveness_sessions()
        session = store.issue(actor.wallet, body.task_id)
        return {
            "session_id": session.session_id,
            "challenge": session.challenge.value,
            "nonce": session.nonce.hex(),
            "expires_at": session.expires_at,
            "ttl_seconds": store.ttl_seconds,
        }

    @app.post("/liveness/complete")
    def liveness_complete(body: LivenessComplete, actor: Auth):
        if body.contributor != actor.wallet:
            fail(403, "Liveness contributor must match the authenticated wallet")
        try:
            result_digest = bytes.fromhex(body.result_digest)
        except ValueError:
            fail(400, "result_digest must be hex")
        store = liveness_sessions()
        try:
            digest_ = store.complete(actor.wallet, body.session_id, result_digest)
        except UnknownSession as exc:
            fail(404, str(exc))
        except SessionExpired as exc:
            fail(410, str(exc))
        except SessionAlreadyUsed as exc:
            fail(409, str(exc))
        except LivenessError as exc:
            fail(400, str(exc))
        # Server-side record that this wallet completed a valid, server-issued
        # liveness proof. The open-upload submit path enforces this flag, so
        # liveness is no longer a client-only claim.
        with database.transaction() as db:
            rate(db, "liveness-complete:" + actor.wallet, 10, 3600)
            worker = lock(db, Actor, actor.wallet)
            worker.liveness_completed = True
        return {
            "liveness_proof_hash": digest_.hex(),
            "task_id": "capture-session",
            "attests": (
                "a live person performed a motion challenge on-device; "
                "not bank-grade anti-spoofing"
            ),
        }

    @app.post("/operator/enroll")
    def enroll(body: Enrollment, x_operator_key: Annotated[str, Header()]):
        if not secrets.compare_digest(
            x_operator_key.encode(), settings.operator_key.encode()
        ):
            fail(403, "Operator authorization required")
        with database.transaction() as db:
            insert_once(
                db, Actor,
                {"wallet": body.wallet, "worker": False, "reviewer": False, "over_18": False},
            )
            actor = lock(db, Actor, body.wallet)
            actor.worker, actor.reviewer = body.worker, body.reviewer
            actor.over_18 = body.over_18
        return {"wallet": body.wallet, "identity_status": "operator-enrolled"}

    @app.post("/bounties")
    def create_bounty(
        body: CreateBounty,
        actor: Auth,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=64)],
    ):
        body_hash = digest(canonical(body.model_dump()))
        with database.transaction() as db:
            lock(db, Actor, actor.wallet)
            old = db.scalar(
                select(Bounty).where(
                    Bounty.requester == actor.wallet,
                    Bounty.request_key == idempotency_key,
                )
            )
            if old:
                if old.body_hash != body_hash:
                    fail(409, "Idempotency key already used for different content")
                return bounty_view(old)
            if not now() + 300 <= body.deadline <= now() + 30 * 86400:
                fail(422, "Deadline must be between five minutes and thirty days away")
            rate(db, "bounties:" + actor.wallet, 10, 3600)
            try:
                resolved = taxonomy.resolve(body.kind, body.category_ids)
            except ValueError as exc:
                fail(422, str(exc))
            b = Bounty(
                requester=actor.wallet,
                request_key=idempotency_key,
                body_hash=body_hash,
                title=body.title,
                kind=body.kind,
                taxonomy=resolved,
                reward=body.reward_usdc_units,
                slots=body.slots,
                deadline=body.deadline,
            )
            db.add(b)
            db.flush()
            return bounty_view(b)

    @app.get("/bounties")
    def bounties(actor: Auth):
        with database.transaction() as db:
            rows = db.scalars(
                select(Bounty)
                .where(or_(Bounty.status == "open", Bounty.requester == actor.wallet))
                .order_by(Bounty.deadline.desc())
                .limit(100)
            ).all()
            return [bounty_view(b) for b in rows]

    @app.post("/bounties/{bid}/claim")
    def claim(bid: str, actor: Auth):
        with database.transaction() as db:
            actor = lock(db, Actor, actor.wallet)
            b = lock(db, Bounty, bid)
            if not actor.worker or actor.wallet == b.requester:
                fail(403, "An independent enrolled worker is required")
            if b.status != "open" or b.deadline <= now():
                fail(409, "Bounty is not open")
            old = db.scalar(
                select(Submission).where(
                    Submission.bounty_id == bid, Submission.worker == actor.wallet
                )
            )
            if old and (old.status != "claimed" or old.expires > now()):
                return submission_view(old, b, actor)
            active = db.scalar(
                select(func.count())
                .select_from(Submission)
                .where(
                    Submission.bounty_id == bid,
                    or_(Submission.status != "claimed", Submission.expires > now()),
                )
            )
            if active >= b.slots:
                fail(409, "All slots are reserved")
            if old:
                old.expires = min(b.deadline, now() + 1200)
                s = old
            else:
                s = Submission(
                    bounty_id=bid,
                    worker=actor.wallet,
                    expires=min(b.deadline, now() + 1200),
                )
                db.add(s)
            db.flush()
            return submission_view(s, b, actor)

    @app.post("/submissions")
    def open_submit(body: OpenSubmission, actor: Auth):
        """Capture v2 open upload: create a no-bounty submission to fill in.

        The bounty path stays intact but dormant; this is the new entry point.
        Returns ``{id, kind, worker, status}``; media and labels follow on the
        per-submission endpoints.
        """
        with database.transaction() as db:
            actor = lock(db, Actor, actor.wallet)
            if not actor.worker:
                fail(403, "Worker enrollment required")
            if not actor.liveness_completed:
                fail(
                    403,
                    "Liveness proof required; complete /liveness/session then "
                    "/liveness/complete first",
                )
            if not actor.bonded:
                # No free tier yet: peer reviews launch later. During this
                # initial stage every capturer must hold the SKR bond.
                fail(403, "Bond required — deposit the SKR bond to capture")
            rate(db, "open-upload:" + actor.wallet, 60, 3600)
            s = Submission(
                bounty_id=None,
                worker=actor.wallet,
                expires=now() + settings.session_seconds,
                kind=body.kind,
            )
            db.add(s)
            db.flush()
            return {
                "id": s.id,
                "kind": s.kind,
                "worker": s.worker,
                "status": s.status,
            }

    @app.get("/submissions")
    def submissions(actor: Auth):
        with database.transaction() as db:
            # Outer join (not inner) so open uploads — whose bounty_id is NULL —
            # still appear in the worker's history; submission_view handles the
            # b=None case by exposing the stored judge verdict.
            rows = db.execute(
                select(Submission, Bounty)
                .outerjoin(Bounty)
                .where(
                    or_(
                        Submission.worker == actor.wallet,
                        Bounty.requester == actor.wallet,
                    )
                )
                .limit(100)
            ).all()
            return [submission_view(s, b, actor) for s, b in rows]

    @app.get("/review-queue")
    def queue(actor: Auth):
        with database.transaction() as db:
            done = select(Review.submission_id).where(Review.reviewer == actor.wallet)
            # Open (no-bounty) uploads awaiting peer review: any authenticated
            # user may review them (no operator reviewer enrollment needed), so
            # they are listed regardless of the reviewer flag.
            open_rows = db.execute(
                select(Submission, Bounty)
                .outerjoin(Bounty)
                .where(
                    Submission.bounty_id.is_(None),
                    Submission.status == "review",
                    Submission.worker != actor.wallet,
                    Submission.id.not_in(done),
                )
                .limit(50)
            ).all()
            if not actor.reviewer:
                return [submission_view(s, b, actor) for s, b in open_rows]
            # Existing bounty review queue for operator-enrolled reviewers.
            bounty_rows = db.execute(
                select(Submission, Bounty)
                .join(Bounty)
                .where(
                    Submission.status == "review",
                    Submission.worker != actor.wallet,
                    Bounty.requester != actor.wallet,
                    Bounty.deadline > now(),
                    Submission.id.not_in(done),
                )
                .limit(50)
            ).all()
            result = [submission_view(s, b, actor) for s, b in open_rows]
            result.extend(submission_view(s, b, actor) for s, b in bounty_rows)
            return result

    @app.post("/submissions/{sid}/media")
    async def upload(sid: str, request: Request, actor: Auth):
        def authorize():
            # Synchronous lock + rate-limit; runs in a worker thread so the
            # event loop is never blocked by a DB transaction or row lock.
            with database.transaction() as db:
                s, is_video = own_media(db, sid, actor)
                if s.status != "claimed":
                    fail(409, "Submission is immutable")
                rate(db, "upload:" + actor.wallet, 12, 3600)
                return (
                    settings.max_video_bytes if is_video else settings.max_upload_bytes,
                    is_video,
                )

        limit, is_video = await run_in_threadpool(authorize)

        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > limit:
                fail(413, "Video exceeds 100 MiB" if is_video else "Image exceeds 15 MiB")

        try:
            if is_video:
                data, media_hash, perceptual, duration_ms = await run_in_threadpool(
                    canonicalize_video, bytes(raw)
                )
                if len(data) > limit:
                    fail(413, "Canonical video exceeds 100 MiB")
            else:
                data, media_hash, perceptual = await run_in_threadpool(
                    canonicalize, bytes(raw)
                )
                duration_ms = None
                if len(data) > settings.max_upload_bytes:
                    fail(413, "Canonical image exceeds 15 MiB")

            def recheck_idempotent():
                with database.transaction() as db:
                    s, _ = own_media(db, sid, actor)
                    if s.media_hash:
                        if s.media_hash != media_hash:
                            fail(409, "Approved media cannot be replaced")
                        return s.media_hash
                    return None

            existing = await run_in_threadpool(recheck_idempotent)
            if existing:
                return {"media_hash": existing}

            # Moderation is network I/O: no DB transaction is held across it.
            verdict = (
                await moderator.scan_video(data)
                if is_video
                else await moderator.scan(data)
            )
        except MediaRejected as exc:
            fail(422, str(exc))

        def finalize():
            with database.transaction() as db:
                s, is_video = own_media(db, sid, actor)
                if s.status != "claimed" or (s.media_hash and s.media_hash != media_hash):
                    fail(409, "Submission changed during scan")
                # Duplicate gate projects only the hash columns (the encrypted
                # media blob is also deferred at the model level).
                dup = select(Submission.media_hash, Submission.perceptual).where(
                    Submission.id != s.id,
                    Submission.media_hash.is_not(None),
                    Submission.perceptual.is_not(None),
                )
                # Bounty submissions gate duplicates within the bounty; open
                # uploads gate duplicates across ALL open uploads, so a worker
                # cannot dodge dedupe by switching wallets.
                dup = dup.where(
                    Submission.bounty_id == s.bounty_id
                    if s.bounty_id is not None
                    else Submission.bounty_id.is_(None)
                )
                others = db.execute(dup).all()
                if any(
                    o_media == media_hash
                    or (int(o_perc, 16) ^ int(perceptual, 16)).bit_count() <= 3
                    for o_media, o_perc in others
                ):
                    fail(409, "Duplicate or near-duplicate media")
                s.media_hash, s.perceptual = media_hash, perceptual
                if is_video:
                    s.duration_ms = duration_ms
                s.encrypted_media, s.moderation = cipher.encrypt(data, media_hash), verdict

        await run_in_threadpool(finalize)
        return {"media_hash": media_hash}

    @app.get("/submissions/{sid}/media")
    def image(sid: str, actor: Auth):
        with database.transaction() as db:
            s = db.get(Submission, sid)
            if not s:
                fail(404, "Submission not found")
            if s.bounty_id is None:
                if s.worker != actor.wallet:
                    fail(403, "Media is private")
                media_type = "video/mp4" if s.kind == "action" else "image/png"
            else:
                s, b = authorized_submission(db, sid, actor)
                if actor.wallet not in {s.worker, b.requester} and (
                    s.status != "review" or b.deadline <= now()
                ):
                    fail(403, "Review access closed")
                media_type = "video/mp4" if b.kind == "action" else "image/png"
            if not s.encrypted_media:
                fail(404, "Approved media not found")
            data = cipher.decrypt(s.encrypted_media, s.media_hash)
        return Response(
            data,
            media_type=media_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/submissions/{sid}/labels")
    def labels(sid: str, body: Union[Labels, PlaceLabels, ActionLabels], actor: Auth):
        with database.transaction() as db:
            s = db.get(Submission, sid)
            if s is not None and s.bounty_id is None:
                # Capture v2 open upload: judge + auto-pay, no bounty claim.
                return open_labels(db, sid, body, actor)
            s, b = own_active(db, sid, actor)
            boxes, secondary = validate_labels(body, s, b)
            if s.labels is not None:
                if canonical(s.labels) != canonical(boxes) or canonical(s.secondary) != canonical(secondary):
                    fail(409, "Submitted labels are immutable")
                return submission_view(s, b, actor)
            s.labels, s.secondary, s.label_hash, s.status = (
                boxes,
                secondary,
                digest(canonical(boxes)),
                "review",
            )
            s.expires = b.deadline
            return submission_view(s, b, actor)

    def review_open(db, sid, body, actor):
        """Peer review an open (no-bounty) upload. Any authenticated user who is
        not the worker may review (no operator reviewer enrollment); each new
        review increments the reviewer's ``quality_checks``. A review is a simple
        accept/reject verdict (``OpenReview``). Two reviews settle: both accept ->
        accepted + payout (the judge accept path); otherwise rejected.
        """
        s = lock(db, Submission, sid)
        if s.worker == actor.wallet:
            fail(403, "Workers may not review their own upload")
        if s.status != "review":
            fail(409, "Review round is closed")
        verdict = body.accepted
        existing = db.scalar(
            select(Review).where(
                Review.submission_id == sid, Review.reviewer == actor.wallet
            )
        )
        if existing:
            if existing.accepted != verdict:
                fail(409, "A review cannot be replaced")
            return {"status": s.status}
        db.add(
            Review(
                submission_id=sid,
                reviewer=actor.wallet,
                labels=[],
                secondary=None,
                accepted=verdict,
            )
        )
        actor.quality_checks += 1
        # Reaching the free-check threshold is also self-serve enrollment: the
        # reviewer becomes a worker so they can capture without an operator key.
        if actor.quality_checks >= QUALITY_CHECKS_REQUIRED:
            actor.worker = True
        db.flush()
        reviews = db.scalars(
            select(Review).where(Review.submission_id == sid)
        ).all()
        if len(reviews) == 2:
            if all(r.accepted for r in reviews):
                # Both accept: settle like the judge accept path — record payout
                # and advance the worker's accepted_count.
                level_before = contributor_level(db, s.worker)["level"]
                complete = bool((s.secondary or {}).get("postures")) and bool(
                    (s.secondary or {}).get("environment")
                )
                payout = payout_units(level_before, s.kind, s.duration_ms, complete)
                worker = lock(db, Actor, s.worker)
                worker.accepted_count += 1
                s.status, s.accepted = "accepted", True
                s.judged_at = now()
                s.verdict_reason = "peer-review consensus"
                s.payout_usdc = payout
                s.level_after = contributor_level(db, s.worker)["level"]
            else:
                s.status, s.accepted = "rejected", False
                s.judged_at = now()
                s.verdict_reason = "peer-review disagreement"
                s.payout_usdc = 0
                s.level_after = contributor_level(db, s.worker)["level"]
        return {"status": s.status}

    @app.post("/submissions/{sid}/reviews")
    def review(sid: str, body: Union[Labels, PlaceLabels, ActionLabels, OpenReview], actor: Auth):
        with database.transaction() as db:
            actor = lock(db, Actor, actor.wallet)
            # Open (no-bounty) uploads are peer-reviewed without a bounty lock:
            # branch BEFORE authorized_submission, which requires a bounty.
            branch = db.execute(
                select(Submission.id, Submission.bounty_id).where(Submission.id == sid)
            ).first()
            if branch is None:
                fail(404, "Submission not found")
            if branch.bounty_id is None:
                return review_open(db, sid, body, actor)
            s, b = authorized_submission(db, sid, actor)
            if not actor.reviewer or actor.wallet in {s.worker, b.requester}:
                fail(403, "Independent enrolled reviewer required")
            boxes, secondary = validate_labels(body, s, b)
            existing = db.scalar(
                select(Review).where(
                    Review.submission_id == sid, Review.reviewer == actor.wallet
                )
            )
            if existing:
                if canonical(existing.labels) != canonical(boxes) or canonical(existing.secondary) != canonical(secondary):
                    fail(409, "A review cannot be replaced")
                return {"status": s.status}
            if s.status != "review" or b.deadline <= now():
                fail(409, "Review round is closed")
            db.add(
                Review(
                    submission_id=sid,
                    reviewer=actor.wallet,
                    labels=boxes,
                    secondary=secondary,
                )
            )
            db.flush()
            reviews = db.scalars(
                select(Review).where(Review.submission_id == sid)
            ).all()
            if len(reviews) == 2:
                sets = [s.labels] + [r.labels for r in reviews]
                s.status = (
                    "eligible"
                    if all(labels_agree(b.kind, a, c) for a, c in combinations(sets, 2))
                    else "disputed"
                )
            return {"status": s.status}

    def prepare(db, action, target, actor, b=None, s=None):
        old = db.scalars(
            select(Prepared)
            .where(
                Prepared.wallet == actor.wallet,
                Prepared.action == action,
                Prepared.target == target,
                Prepared.confirmed.is_(False),
            )
            .order_by(Prepared.last_valid_height.desc())
        ).first()
        if old and old.last_valid_height >= chain.height():
            return tx_view(old)
        result = chain.prepare(action, actor.wallet, b, s)
        p = Prepared(wallet=actor.wallet, action=action, target=target, **result)
        db.add(p)
        db.flush()
        return tx_view(p)

    def tx_view(p):
        return {
            "id": p.id,
            "action": p.action,
            "target": p.target,
            "transaction_base64": p.transaction,
            "last_valid_block_height": p.last_valid_height,
            "confirmed": p.confirmed,
            "signature": p.signature,
        }

    @app.post("/bounties/{bid}/{action}/prepare")
    def prepare_bounty(bid: str, action: str, actor: Auth):
        with database.transaction() as db:
            lock(db, Actor, actor.wallet)
            b = lock(db, Bounty, bid)
            if b.requester != actor.wallet:
                fail(403, "Requester signature required")
            if action == "fund" and b.status == "draft" and b.deadline > now():
                return prepare(db, action, bid, actor, b)
            if (
                action == "refund"
                and b.status in {"open", "refunded"}
                and b.deadline <= now()
            ):
                return prepare(db, action, bid, actor, b)
            fail(409, "Action not available in current bounty state")

    @app.post("/submissions/{sid}/{action}/prepare")
    def prepare_submission(sid: str, action: str, actor: Auth):
        with database.transaction() as db:
            actor = lock(db, Actor, actor.wallet)
            s, b = authorized_submission(db, sid, actor)
            if action == "fulfill":
                if (
                    actor.wallet != s.worker
                    or not actor.worker
                    or s.status != "eligible"
                    or b.deadline <= now()
                ):
                    fail(
                        403, "Only an eligible enrolled worker may register fulfillment"
                    )
            elif action in {"accept", "reject"}:
                if actor.wallet != b.requester:
                    fail(403, "Requester signature required")
                if s.status != "registered" or (
                    action == "accept" and b.deadline <= now()
                ):
                    fail(409, "Submission cannot be settled in this state")
            elif action == "expire":
                if s.status != "registered" or b.deadline > now():
                    fail(409, "Submission is not expired")
            else:
                fail(404, "Unknown action")
            return prepare(db, action, sid, actor, b, s)

    @app.post("/bond/faucet")
    def bond_faucet(actor: Auth):
        """Devnet test-SKR faucet ("Get test SKR"). Records funding server-side;
        idempotent. On-chain settlement stays on the prepare seam."""
        with database.transaction() as db:
            actor = lock(db, Actor, actor.wallet)
            actor.skr_funded = True
        return {"funded": True}

    @app.post("/bond/deposit")
    def bond_deposit(actor: Auth):
        """Devnet server-recorded bond deposit. Requires the test-SKR faucet to
        have run first; idempotent. Does NOT touch /bond/{action}/prepare."""
        with database.transaction() as db:
            actor = lock(db, Actor, actor.wallet)
            if not actor.skr_funded:
                fail(409, "Get test SKR first")
            actor.bonded = True
            # Bonding is the self-serve worker enrollment: an unlocked account
            # must be able to capture without the operator-key /operator/enroll.
            actor.worker = True
        return {"bonded": True}

    @app.post("/bond/{action}/prepare")
    def prepare_bond(action: str, actor: Auth):
        if action not in {"deposit", "withdraw"}:
            fail(404, "Unknown action")
        with database.transaction() as db:
            actor = lock(db, Actor, actor.wallet)
            if not actor.worker:
                fail(403, "Worker enrollment required")
            return prepare(db, action, actor.wallet, actor)

    @app.get("/transactions")
    def transactions(actor: Auth):
        with database.transaction() as db:
            rows = db.scalars(
                select(Prepared)
                .where(Prepared.wallet == actor.wallet)
                .order_by(Prepared.last_valid_height.desc())
                .limit(100)
            ).all()
            return [tx_view(p) for p in rows]

    def record_confirmation(pid, actor, signature=None):
        # Phase 1: read + authorize under a short transaction, capture the
        # inputs the RPC calls need, then release every row lock. Network work
        # (signature walk + verification) must never hold a DB lock.
        with database.transaction() as db:
            lock(db, Actor, actor.wallet)
            p = db.get(Prepared, pid)
            if not p or p.wallet != actor.wallet:
                fail(404, "Prepared transaction not found")
            b, s = None, None
            if p.action in {"fund", "refund"}:
                b = lock(db, Bounty, p.target)
            elif p.action in {"fulfill", "accept", "reject", "expire"}:
                s, b = authorized_submission(db, p.target, actor)
            p = lock(db, Prepared, pid)
            if p.confirmed:
                if signature and signature != p.signature:
                    fail(409, "Already confirmed with another signature")
                return tx_view(p)
            prepared, bounty, submission = p, b, s

        # Phase 2: network I/O with no DB locks held.
        resolved = signature or chain.find_signature(prepared, bounty, submission)
        chain.confirm(prepared, resolved)

        # Phase 3: re-acquire the lock and write atomically, tolerating a
        # concurrent confirmation that landed between phases.
        with database.transaction() as db:
            p = lock(db, Prepared, pid)
            if p.confirmed:
                if signature and signature != p.signature:
                    fail(409, "Already confirmed with another signature")
                return tx_view(p)
            p.signature, p.confirmed = resolved, True
            if p.action == "fund":
                b = lock(db, Bounty, p.target)
                if b.status == "draft":
                    b.status = "open"
            elif p.action == "refund":
                b = lock(db, Bounty, p.target)
                b.status = "refunded"
            elif p.action == "fulfill":
                s, _ = authorized_submission(db, p.target, actor)
                # Late callback must never regress a settled submission.
                if s.status == "eligible":
                    s.status = "registered"
            elif p.action in {"accept", "reject", "expire"}:
                s, _ = authorized_submission(db, p.target, actor)
                s.status = {
                    "accept": "paid",
                    "reject": "rejected",
                    "expire": "expired",
                }[p.action]
            return tx_view(p)

    @app.post("/transactions/{pid}/confirm")
    def confirm(pid: str, body: Confirm, actor: Auth):
        return record_confirmation(pid, actor, body.signature)

    @app.post("/transactions/{pid}/reconcile")
    def reconcile(pid: str, actor: Auth):
        return record_confirmation(pid, actor)

    return app


def production_app():
    return create_app(Settings())

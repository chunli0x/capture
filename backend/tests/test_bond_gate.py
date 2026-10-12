"""Capture bond gate + judge routing (CAPTURE-BOND-SPEC, bonded-only stage).

Covers the hard gate (bonded only — the free peer-review tier is deferred), the
faucet -> deposit -> unlock flow, bonded-judge routing, and the fail-closed
behavior of an unbonded worker.
"""

import base64
import io
import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from seeker.api import create_app
from seeker.config import Settings
from seeker.db import Actor, Base, Submission
from solders.keypair import Keypair


class FakeChain:
    confirmed = 0

    def height(self):
        return 10

    def prepare(self, *args):
        return {
            "transaction": "TEST-ONLY",
            "message_hash": "a" * 64,
            "last_valid_height": 100,
        }

    def confirm(self, p, sig):
        self.confirmed += 1
        return True

    def find_signature(self, p, *args):
        return str(Keypair().sign_message(p.id.encode()))


class FakeModerator:
    async def scan(self, data):
        return {"policy": "TEST-ONLY", "result": "pass"}

    async def scan_video(self, data):
        return {"policy": "TEST-ONLY", "result": "pass"}


@pytest.fixture
def pilot(tmp_path):
    chain, mod = FakeChain(), FakeModerator()
    settings = Settings(
        database_url="sqlite:///" + str(tmp_path / "bond.db"),
        local_sqlite=True,
        domain="pilot.test",
        operator_key="o" * 32,
        media_key=base64.b64encode(b"k" * 32).decode(),
        program_id=str(Keypair().pubkey()),
        usdc_mint=str(Keypair().pubkey()),
        skr_mint=str(Keypair().pubkey()),
        verifier_key_file=tmp_path / "unused",
    )
    app = create_app(settings, chain=chain, moderator=mod)
    Base.metadata.drop_all(app.state.database.engine)
    Base.metadata.create_all(app.state.database.engine)
    c = TestClient(app)
    keys = [Keypair() for _ in range(6)]
    h = []
    for i, k in enumerate(keys):
        r = c.post("/auth/challenge", json={"wallet": str(k.pubkey())}).json()
        v = c.post(
            "/auth/verify",
            json={
                "challenge_id": r["challenge_id"],
                "signature": str(k.sign_message(r["message"].encode())),
            },
        )
        assert v.status_code == 200, v.text
        h.append({"Authorization": "Bearer " + v.json()["token"]})
        # keys[5] is worker-only (reviewer=False) to prove open-upload peer
        # review needs no operator reviewer enrollment.
        reviewer = i != 5
        assert (
            c.post(
                "/operator/enroll",
                json={
                    "wallet": str(k.pubkey()),
                    "worker": True,
                    "reviewer": reviewer,
                },
                headers={"x-operator-key": "o" * 32},
            ).status_code
            == 200
        )
    for k, hd in zip(keys, h):
        do_liveness(c, hd, str(k.pubkey()))
    yield c, app, h, keys, settings
    app.state.database.engine.dispose()


def png():
    # Random noise: open-upload dedupe rejects identical/near-identical media
    # (smooth/solid images share a perceptual hash), so each upload needs a
    # genuinely distinct, high-entropy image.
    img = Image.frombytes("RGB", (64, 64), os.urandom(64 * 64 * 3))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def do_liveness(c, h, wallet, task_id="capture-session"):
    r = c.post(
        "/liveness/session",
        headers=h,
        json={"contributor": wallet, "task_id": task_id},
    )
    assert r.status_code == 200, r.text
    r = c.post(
        "/liveness/complete",
        headers=h,
        json={"contributor": wallet, "session_id": r.json()["session_id"], "result_digest": "0" * 64},
    )
    assert r.status_code == 200, r.text


def open_submission(c, h, kind="object"):
    r = c.post("/submissions", headers=h, json={"kind": kind})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def upload_media(c, h, sid, content=None):
    r = c.post(f"/submissions/{sid}/media", headers=h, content=content or png())
    assert r.status_code == 200, r.text
    return r.json()["media_hash"]


def object_labels(media_hash, postures=(1,), environment=(), boxes=None, **extra):
    if boxes is None:
        boxes = [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}]
    body = {
        "media_hash": media_hash,
        "boxes": boxes,
        "postures": list(postures),
    }
    if environment:
        body["environment"] = list(environment)
    body.update(extra)
    return body


def make_free(app, wallet):
    """Mark a worker with 3 quality checks (the deferred free-tier path)."""

    with app.state.database.transaction() as db:
        db.get(Actor, wallet).quality_checks = 3


# ---- bond flow ----


def test_faucet_then_deposit_unlocks(pilot):
    c, _app, h, *_ = pilot
    me = c.get("/me", headers=h[0]).json()
    assert me["bonded"] is False
    assert me["unlocked"] is False
    assert me["quality_checks_required"] == 3
    assert me["quality_checks"] == 0

    # Deposit before faucet -> 409.
    r = c.post("/bond/deposit", headers=h[0])
    assert r.status_code == 409
    assert "test skr" in r.json()["detail"].lower()

    # Faucet is idempotent.
    assert c.post("/bond/faucet", headers=h[0]).json() == {"funded": True}
    assert c.post("/bond/faucet", headers=h[0]).json() == {"funded": True}

    # Deposit now works and is idempotent.
    assert c.post("/bond/deposit", headers=h[0]).json() == {"bonded": True}
    assert c.post("/bond/deposit", headers=h[0]).json() == {"bonded": True}

    me = c.get("/me", headers=h[0]).json()
    assert me["bonded"] is True
    assert me["unlocked"] is True


def test_open_upload_gated_until_unlocked(pilot):
    c, _app, h, *_ = pilot
    # worker + liveness, but not bonded and zero quality checks -> 403.
    r = c.post("/submissions", headers=h[1], json={"kind": "object"})
    assert r.status_code == 403
    assert "bond" in r.json()["detail"].lower()

    # Faucet + deposit unlocks; upload now allowed.
    assert c.post("/bond/faucet", headers=h[1]).json() == {"funded": True}
    assert c.post("/bond/deposit", headers=h[1]).json() == {"bonded": True}
    assert c.post("/submissions", headers=h[1], json={"kind": "object"}).status_code == 200


# ---- bonded-only gate (free tier deferred) ----


def test_quality_checks_do_not_unlock_without_bond(pilot):
    c, app, h, keys, *_ = pilot
    # Even a worker with 3 quality checks (the old free path) is NOT unlocked:
    # the free tier is deferred, so the bond is the only way in.
    make_free(app, str(keys[3].pubkey()))
    me = c.get("/me", headers=h[3]).json()
    assert me["quality_checks"] == 3
    assert me["bonded"] is False
    assert me["unlocked"] is False

    r = c.post("/submissions", headers=h[3], json={"kind": "object"})
    assert r.status_code == 403
    assert "bond" in r.json()["detail"].lower()

    # Deposit the bond and the same worker is now unlocked.
    assert c.post("/bond/faucet", headers=h[3]).json() == {"funded": True}
    assert c.post("/bond/deposit", headers=h[3]).json() == {"bonded": True}
    assert c.post("/submissions", headers=h[3], json={"kind": "object"}).status_code == 200


def test_unbonded_labels_fail_closed_not_queued(pilot):
    c, app, h, keys, *_ = pilot
    # A submission can no longer be created by an unbonded worker, so there is
    # nothing to route to review; but defend the label path directly: seed a
    # claimed submission, then confirm an unbonded worker cannot label it.
    with app.state.database.transaction() as db:
        import time as _time
        from seeker.db import Submission as _Submission
        s = _Submission(
            bounty_id=None,
            worker=str(keys[3].pubkey()),
            expires=_time.time() + 3600,
            kind="object",
        )
        db.add(s)
        db.flush()
        sid = s.id
    # Give the worker liveness but not the bond.
    do_liveness(c, h[3], str(keys[3].pubkey()))
    mh = upload_media(c, h[3], sid)
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[3],
        json=object_labels(mh, postures=[1], environment=[1]),
    )
    assert r.status_code == 403
    assert "bond" in r.json()["detail"].lower()


def test_review_queue_empty_when_no_free_tier(pilot):
    c, _app, h, *_ = pilot
    # No free tier -> no open uploads enter status='review' -> the queue is empty.
    q = c.get("/review-queue", headers=h[5]).json()
    assert q == []


# ---- bonded-only judge routing ----


def test_bonded_worker_gets_judge_verdict(pilot):
    c, _app, h, *_ = pilot
    assert c.post("/bond/faucet", headers=h[1]).json() == {"funded": True}
    assert c.post("/bond/deposit", headers=h[1]).json() == {"bonded": True}
    sid = open_submission(c, h[1])
    mh = upload_media(c, h[1], sid)
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json=object_labels(mh, postures=[1], environment=[1]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted"
    assert body["verdict"]["accepted"] is True
    assert body["payout_usdc"] == 100_000

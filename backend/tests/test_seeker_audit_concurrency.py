"""Deterministic guard test plus a Postgres-only concurrency test for the
open-labels acceptance race (audit fix #1).

The double-increment only manifests when two transactions can both observe a
submission as "claimed" before either commits. That requires row-level
``SELECT ... FOR UPDATE`` (Postgres); SQLite's ``BEGIN IMMEDIATE`` serializes
whole transactions, so the race cannot occur there. The deterministic test
pins the underlying mechanism (``lock()`` refreshes a stale identity-map row),
and the concurrency test exercises the end-to-end invariant against Postgres.
"""

import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from seeker.api import create_app, lock
from seeker.config import Settings
from seeker.db import Actor, Base, Submission
from solders.keypair import Keypair
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def test_lock_refreshes_stale_identity_map():
    """``lock()`` must re-read the committed DB row (populate_existing) rather
    than return a stale identity-map value. This is what prevents two concurrent
    label requests from both passing the immutable-state guard: each re-reads
    the row under ``SELECT ... FOR UPDATE`` instead of trusting an earlier read.

    Simulated deterministically: an in-memory attribute that diverges from the
    DB (as happens when another transaction commits between a handler's early
    read and its lock) must be discarded by ``lock()``.
    """
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    S = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    with S.begin() as seed:
        seed.add(Actor(wallet="w" * 44, worker=True))
        seed.add(
            Submission(
                id="1" * 32,
                bounty_id=None,
                worker="w" * 44,
                expires=9999999999,
                kind="object",
            )
        )

    sa = S()
    s = sa.get(Submission, "1" * 32)
    assert s.status == "claimed"
    # Stale in-memory divergence (autoflush=False keeps it uncommitted).
    s.status = "accepted"

    assert lock(sa, Submission, "1" * 32).status == "claimed"  # DB value, not "accepted"
    sa.close()
    engine.dispose()


# ---- Postgres-only end-to-end concurrency test ----


POSTGRES_URL = os.environ.get("SEEKER_TEST_DATABASE", "")


def _is_postgres(url: str) -> bool:
    return bool(url) and make_url(url).get_backend_name() == "postgresql"


class FakeChain:
    def height(self):
        return 10

    def prepare(self, *args):
        return {
            "transaction": "TEST-ONLY",
            "message_hash": "a" * 64,
            "last_valid_height": 100,
        }

    def confirm(self, p, sig):
        return True

    def find_signature(self, p, *args):
        return str(Keypair().sign_message(p.id.encode()))


class FakeModerator:
    async def scan(self, data):
        return {"policy": "TEST-ONLY", "result": "pass"}

    async def scan_video(self, data):
        return {"policy": "TEST-ONLY", "result": "pass"}


def png(color="red"):
    out = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(out, "PNG")
    return out.getvalue()


def _liveness(c, h, wallet):
    r = c.post(
        "/liveness/session",
        headers=h,
        json={"contributor": wallet, "task_id": "capture-session"},
    )
    assert r.status_code == 200, r.text
    r = c.post(
        "/liveness/complete",
        headers=h,
        json={
            "contributor": wallet,
            "session_id": r.json()["session_id"],
            "result_digest": "0" * 64,
        },
    )
    assert r.status_code == 200, r.text


@pytest.fixture
def pg_pilot(tmp_path: Path):
    dbname = make_url(POSTGRES_URL).database or ""
    assert dbname.endswith("_test"), "Refusing to reset a database not ending in _test"
    settings = Settings(
        database_url=POSTGRES_URL,
        domain="pilot.test",
        operator_key="o" * 32,
        media_key=base64.b64encode(b"k" * 32).decode(),
        program_id=str(Keypair().pubkey()),
        usdc_mint=str(Keypair().pubkey()),
        skr_mint=str(Keypair().pubkey()),
        verifier_key_file=tmp_path / "unused",
    )
    app = create_app(settings, chain=FakeChain(), moderator=FakeModerator())
    Base.metadata.drop_all(app.state.database.engine)
    Base.metadata.create_all(app.state.database.engine)
    c = TestClient(app)

    key = Keypair()
    ch = c.post("/auth/challenge", json={"wallet": str(key.pubkey())}).json()
    token = c.post(
        "/auth/verify",
        json={
            "challenge_id": ch["challenge_id"],
            "signature": str(key.sign_message(ch["message"].encode())),
        },
    ).json()["token"]
    h = {"Authorization": "Bearer " + token}
    assert (
        c.post(
            "/operator/enroll",
            json={"wallet": str(key.pubkey()), "worker": True, "reviewer": False},
            headers={"x-operator-key": "o" * 32},
        ).status_code
        == 200
    )
    _liveness(c, h, str(key.pubkey()))
    # Bond the worker so the open-upload label path runs the (judge) accept
    # path, not the bond gate / free peer-review path.
    assert c.post("/bond/faucet", headers=h).status_code == 200
    assert c.post("/bond/deposit", headers=h).status_code == 200
    yield c, app, h, key
    app.state.database.engine.dispose()


@pytest.mark.skipif(
    not _is_postgres(POSTGRES_URL),
    reason="SEEKER_TEST_DATABASE must point at a PostgreSQL test database",
)
def test_concurrent_open_labels_single_accept(pg_pilot):
    """Two concurrent label requests must yield exactly one accepted_count."""
    c, app, h, key = pg_pilot
    sid = c.post("/submissions", headers=h, json={"kind": "object"}).json()["id"]
    media_hash = c.post(
        f"/submissions/{sid}/media", headers=h, content=png()
    ).json()["media_hash"]
    body = {
        "media_hash": media_hash,
        "boxes": [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
        "postures": [1],
        "environment": [1],
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        rs = list(
            pool.map(
                lambda _: c.post(f"/submissions/{sid}/labels", headers=h, json=body),
                [0, 1],
            )
        )
    # One request does the work; the loser either idempotently returns the
    # stored verdict (200) — never a double accept.
    assert all(r.status_code == 200 for r in rs), [r.text for r in rs]
    with app.state.database.transaction() as db:
        assert db.get(Actor, str(key.pubkey())).accepted_count == 1

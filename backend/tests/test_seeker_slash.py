"""Two-strike media-policy ladder + real bond deposit/withdraw prepare path
(CAPTURE-STAKE-SLASH-SPEC).

Covers:
- first moderation violation -> on-chain ``warn`` -> 422 (warning body)
- second violation -> on-chain ``slash`` -> 403 (bond slashed)
- chain unavailability during the ladder -> fail closed 503
- /bond/deposit + /bond/withdraw return a real prepare() payload; ``bonded``
  is set/cleared only on confirm
- accepted open upload settles the treasury->worker USDC transfer and records
  the signature
"""

import base64
import io
import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from seeker.api import create_app
from seeker.chain import ChainUnavailable
from seeker.config import Settings
from seeker.db import Actor, Base, Submission
from seeker.media import MediaRejected
from solders.keypair import Keypair


class FakeChain:
    """Records the on-chain seams the API calls, without a real chain."""

    def __init__(self):
        self.prepared = []       # (action, wallet) from prepare()
        self.confirm_calls = []  # (action, signature) from confirm()
        self.issued = []         # (action, wallet, amount) from issue()
        self.settled = []        # (wallet, amount) from settle_usdc()
        self.warnings = 0        # bond.warnings the ladder reads
        self.fail_warnings = False
        self.fail_issue = False

    def height(self):
        return 10

    def prepare(self, action, wallet, bounty=None, submission=None):
        self.prepared.append((action, wallet))
        return {
            "transaction": "TEST-ONLY",
            "message_hash": "a" * 64,
            "last_valid_height": 100,
        }

    def confirm(self, p, sig):
        self.confirm_calls.append((p.action, sig))
        return True

    def find_signature(self, p, *args):
        return str(Keypair().sign_message(p.id.encode()))

    def bond_warnings(self, wallet):
        if self.fail_warnings:
            raise ChainUnavailable("RPC unavailable")
        return self.warnings

    def issue(self, action, wallet, amount=None):
        if self.fail_issue:
            raise ChainUnavailable("RPC unavailable")
        self.issued.append((action, wallet, amount))
        return str(Keypair().sign_message(f"issue-{len(self.issued)}".encode()))

    def settle_usdc(self, wallet, amount):
        self.settled.append((wallet, amount))
        return str(Keypair().sign_message(f"settle-{len(self.settled)}".encode()))


class FakeModerator:
    def __init__(self):
        self.reject = False

    async def scan(self, data):
        if self.reject:
            raise MediaRejected("nudity-2.0 signal")
        return {"policy": "TEST-ONLY", "result": "pass"}

    async def scan_video(self, data):
        if self.reject:
            raise MediaRejected("nudity-2.0 signal")
        return {"policy": "TEST-ONLY", "result": "pass"}


@pytest.fixture
def pilot(tmp_path):
    chain, mod = FakeChain(), FakeModerator()
    settings = Settings(
        database_url="sqlite:///" + str(tmp_path / "slash.db"),
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
    keys = [Keypair() for _ in range(3)]
    h = []
    for k in keys:
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
        assert (
            c.post(
                "/operator/enroll",
                json={"wallet": str(k.pubkey()), "worker": True, "reviewer": True},
                headers={"x-operator-key": "o" * 32},
            ).status_code
            == 200
        )
    yield c, app, h, keys, chain, mod, settings
    app.state.database.engine.dispose()


def png():
    # High-entropy noise so the open-upload dedupe gate never trips.
    img = Image.frombytes("RGB", (64, 64), os.urandom(64 * 64 * 3))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def do_liveness(c, h, wallet):
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


def bond(c, h):
    """faucet -> deposit/prepare -> confirm, so ``bonded`` is set via the seam."""
    assert c.post("/bond/faucet", headers=h).status_code == 200
    tx = c.post("/bond/deposit", headers=h).json()
    sig = str(Keypair().sign_message(tx["id"].encode()))
    r = c.post(
        f"/transactions/{tx['id']}/confirm", headers=h, json={"signature": sig}
    )
    assert r.status_code == 200, r.text


def ready_worker(c, h, wallet):
    do_liveness(c, h, wallet)
    bond(c, h)


# ---- media-policy ladder ----


def test_first_violation_issues_warn_and_returns_422(pilot):
    c, _app, h, keys, chain, mod, *_ = pilot
    wallet = str(keys[0].pubkey())
    ready_worker(c, h[0], wallet)
    sid = c.post("/submissions", headers=h[0], json={"kind": "object"}).json()["id"]

    chain.warnings = 0
    mod.reject = True
    r = c.post(f"/submissions/{sid}/media", headers=h[0], content=png())
    assert r.status_code == 422
    assert "warning" in r.json()["detail"].lower()
    assert chain.issued == [("warn", wallet, None)]
    assert chain.settled == []


def test_second_violation_issues_slash_and_returns_403(pilot):
    c, _app, h, keys, chain, mod, *_ = pilot
    wallet = str(keys[0].pubkey())
    ready_worker(c, h[0], wallet)
    sid = c.post("/submissions", headers=h[0], json={"kind": "object"}).json()["id"]

    chain.warnings = 1
    mod.reject = True
    r = c.post(f"/submissions/{sid}/media", headers=h[0], content=png())
    assert r.status_code == 403
    assert "slash" in r.json()["detail"].lower()
    # Second strike: warn once more to reach the on-chain slash threshold
    # (warnings >= 2), then slash the bond.
    assert chain.issued == [("warn", wallet, None), ("slash", wallet, None)]


def test_ladder_fails_closed_503_when_chain_unavailable(pilot):
    c, _app, h, keys, chain, mod, *_ = pilot
    wallet = str(keys[0].pubkey())
    ready_worker(c, h[0], wallet)
    sid = c.post("/submissions", headers=h[0], json={"kind": "object"}).json()["id"]

    chain.fail_warnings = True
    mod.reject = True
    r = c.post(f"/submissions/{sid}/media", headers=h[0], content=png())
    assert r.status_code == 503
    assert chain.issued == []


def test_format_rejection_is_not_a_policy_strike(pilot):
    """A malformed file (not a moderation verdict) must not touch the bond."""
    c, _app, h, keys, chain, *_ = pilot
    wallet = str(keys[0].pubkey())
    ready_worker(c, h[0], wallet)
    sid = c.post("/submissions", headers=h[0], json={"kind": "object"}).json()["id"]
    r = c.post(f"/submissions/{sid}/media", headers=h[0], content=b"not an image")
    assert r.status_code == 422
    assert chain.issued == []


# ---- deposit / withdraw prepare path ----


def test_deposit_builds_prepare_and_confirm_sets_bonded(pilot):
    c, _app, h, keys, chain, *_ = pilot
    wallet = str(keys[0].pubkey())
    do_liveness(c, h[0], wallet)

    # deposit before faucet -> 409
    assert c.post("/bond/deposit", headers=h[0]).status_code == 409

    # faucet (idempotent DB-flag fallback: no treasury key configured)
    assert c.post("/bond/faucet", headers=h[0]).json() == {"funded": True}
    assert c.post("/bond/faucet", headers=h[0]).json() == {"funded": True}

    # deposit returns the real prepare payload
    r = c.post("/bond/deposit", headers=h[0])
    assert r.status_code == 200, r.text
    tx = r.json()
    assert tx["action"] == "deposit"
    assert tx["transaction_base64"] == "TEST-ONLY"
    assert tx["confirmed"] is False
    assert tx["signature"] is None
    assert chain.prepared == [("deposit", wallet)]

    # not bonded until the exact message is confirmed
    assert c.get("/me", headers=h[0]).json()["bonded"] is False

    sig = str(Keypair().sign_message(tx["id"].encode()))
    cr = c.post(
        f"/transactions/{tx['id']}/confirm", headers=h[0], json={"signature": sig}
    )
    assert cr.status_code == 200, cr.text
    assert chain.confirm_calls[-1][0] == "deposit"

    me = c.get("/me", headers=h[0]).json()
    assert me["bonded"] is True
    assert me["unlocked"] is True
    assert me["worker"] is True


def test_withdraw_builds_prepare_and_confirm_clears_bonded(pilot):
    c, _app, h, keys, chain, *_ = pilot
    wallet = str(keys[0].pubkey())
    ready_worker(c, h[0], wallet)
    assert c.get("/me", headers=h[0]).json()["bonded"] is True

    tx = c.post("/bond/withdraw", headers=h[0]).json()
    assert tx["action"] == "withdraw"
    assert chain.prepared[-1] == ("withdraw", wallet)

    sig = str(Keypair().sign_message(tx["id"].encode()))
    r = c.post(
        f"/transactions/{tx['id']}/confirm", headers=h[0], json={"signature": sig}
    )
    assert r.status_code == 200, r.text
    assert chain.confirm_calls[-1][0] == "withdraw"
    assert c.get("/me", headers=h[0]).json()["bonded"] is False


# ---- accepted settlement records the treasury signature ----


def test_accept_records_treasury_settlement_signature(pilot):
    c, app, h, keys, chain, *_ = pilot
    wallet = str(keys[0].pubkey())
    ready_worker(c, h[0], wallet)

    sid = c.post("/submissions", headers=h[0], json={"kind": "object"}).json()["id"]
    mh = c.post(f"/submissions/{sid}/media", headers=h[0], content=png()).json()[
        "media_hash"
    ]
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[0],
        json={
            "media_hash": mh,
            "boxes": [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
            "postures": [1],
            "environment": [1],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "accepted"
    assert body["payout_usdc"] == 100_000
    assert body["payout_signature"] is not None
    assert chain.settled == [(wallet, 100_000)]

    with app.state.database.transaction() as db:
        assert db.get(Submission, sid).payout_signature == body["payout_signature"]

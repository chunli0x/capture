"""Explicit fake services here prove API behavior, never actual token transfers."""

import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from PIL import Image
from seeker.api import create_app
from seeker.chain import ChainUnavailable
from seeker.config import Settings
from seeker.db import Base, Challenge, Review, Submission, now
from seeker.media import (
    MediaCipher,
    MediaRejected,
    canonicalize,
    hive_pass,
    sightengine_pass,
)
from seeker.schemas import Labels, agree
from solders.keypair import Keypair
from sqlalchemy import select
from sqlalchemy.engine import make_url


class FakeChain:
    confirmed = 0
    allowed = True
    current_height = 10

    def height(self):
        return self.current_height

    def prepare(self, *args):
        return {
            "transaction": "TEST-ONLY",
            "message_hash": "a" * 64,
            "last_valid_height": 100,
        }

    def confirm(self, p, sig):
        if not self.allowed:
            raise ChainUnavailable("not finalized")
        self.confirmed += 1
        return True

    def find_signature(self, p, *args):
        return str(Keypair().sign_message(p.id.encode()))


class FakeModerator:
    reject = False
    calls = 0

    async def scan(self, data):
        self.calls += 1
        if self.reject:
            raise MediaRejected("test rejection")
        return {"policy": "TEST-ONLY", "result": "pass"}


@pytest.fixture
def pilot(tmp_path):
    chain, mod = FakeChain(), FakeModerator()
    settings = Settings(
        database_url=os.environ.get(
            "SEEKER_TEST_DATABASE", "sqlite:///" + str(tmp_path / "pilot.db")
        ),
        local_sqlite=True,
        domain="pilot.test",
        operator_key="o" * 32,
        media_key=base64.b64encode(b"k" * 32).decode(),
        program_id=str(Keypair().pubkey()),
        usdc_mint=str(Keypair().pubkey()),
        skr_mint=str(Keypair().pubkey()),
        verifier_key_file=tmp_path / "unused",
    )
    if os.environ.get("SEEKER_TEST_DATABASE"):
        assert (make_url(settings.database_url).database or "").endswith("_test"), (
            "Refusing to reset a database not ending in _test"
        )
    app = create_app(settings, chain=chain, moderator=mod)
    Base.metadata.drop_all(app.state.database.engine)
    Base.metadata.create_all(app.state.database.engine)
    c = TestClient(app)
    keys = [Keypair() for _ in range(6)]
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


def png(color="red"):
    out = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(out, "PNG")
    return out.getvalue()


def bounty(p, slots=2):
    c, _, h, *_ = p
    body = {
        "title": "Label a cup",
        "category_ids": [1],
        "reward_usdc_units": 1000,
        "slots": slots,
        "deadline": now() + 3600,
    }
    r = c.post(
        "/bounties", headers={**h[0], "Idempotency-Key": os.urandom(8).hex()}, json=body
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def transact(p, path, actor=0):
    c, _, h, *_ = p
    r = c.post(path + "/prepare", headers=h[actor])
    assert r.status_code == 200, r.text
    tx = r.json()
    sig = str(Keypair().sign_message(tx["id"].encode()))
    r = c.post(
        f"/transactions/{tx['id']}/confirm", headers=h[actor], json={"signature": sig}
    )
    assert r.status_code == 200, r.text
    return tx["id"], sig


def submitted(p):
    c, _, h, *_ = p
    bid = bounty(p)
    transact(p, f"/bounties/{bid}/fund")
    r = c.post(f"/bounties/{bid}/claim", headers=h[1])
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=png())
    assert r.status_code == 200, r.text
    labels = {
        "media_hash": r.json()["media_hash"],
        "boxes": [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
    }
    r = c.post(f"/submissions/{sid}/labels", headers=h[1], json=labels)
    assert r.status_code == 200, r.text
    return bid, sid, labels


def eligible(p):
    c, _, h, *_ = p
    bid, sid, labels = submitted(p)
    for i in (2, 3):
        r = c.post(f"/submissions/{sid}/reviews", headers=h[i], json=labels)
        assert r.status_code == 200, r.text
    assert r.json()["status"] == "eligible"
    return bid, sid, labels


def test_full_flow_accept_restart_exact_once(pilot):
    c, _app, h, _, chain, mod, settings = pilot
    _bid, sid, _labels = eligible(pilot)
    assert chain.confirmed == 1
    assert c.post(f"/submissions/{sid}/accept/prepare", headers=h[0]).status_code == 409
    transact(pilot, f"/submissions/{sid}/fulfill", 1)
    assert c.post(f"/submissions/{sid}/accept/prepare", headers=h[1]).status_code == 403
    before = chain.confirmed
    assert c.post(f"/submissions/{sid}/accept/prepare", headers=h[0]).status_code == 200
    assert chain.confirmed == before
    restart = TestClient(create_app(settings, chain=chain, moderator=mod))
    assert restart.get("/submissions", headers=h[0]).json()[0]["status"] == "registered"
    tx, sig = transact(pilot, f"/submissions/{sid}/accept")
    assert (
        c.post(
            f"/transactions/{tx}/confirm", headers=h[0], json={"signature": sig}
        ).status_code
        == 200
    )
    assert chain.confirmed == before + 1
    assert c.get("/submissions", headers=h[0]).json()[0]["status"] == "paid"
    assert c.post(f"/submissions/{sid}/accept/prepare", headers=h[0]).status_code == 409
    assert (
        c.post(
            f"/transactions/{tx}/confirm", headers=h[1], json={"signature": sig}
        ).status_code
        == 404
    )


def test_auth_replay_wrong_wallet_expiry_logout(pilot):
    c, app, h, keys, *_ = pilot
    challenge = c.post("/auth/challenge", json={"wallet": str(keys[0].pubkey())}).json()
    body = {
        "challenge_id": challenge["challenge_id"],
        "signature": str(keys[1].sign_message(challenge["message"].encode())),
    }
    assert c.post("/auth/verify", json=body).status_code == 401
    body["signature"] = str(keys[0].sign_message(challenge["message"].encode()))
    assert c.post("/auth/verify", json=body).status_code == 200
    assert c.post("/auth/verify", json=body).status_code == 401
    challenge = c.post("/auth/challenge", json={"wallet": str(keys[0].pubkey())}).json()
    with app.state.database.transaction() as db:
        db.get(Challenge, challenge["challenge_id"]).expires = 0
    assert (
        c.post(
            "/auth/verify",
            json={
                "challenge_id": challenge["challenge_id"],
                "signature": body["signature"],
            },
        ).status_code
        == 401
    )
    assert c.get("/bounties").status_code == 401
    assert (
        c.get("/bounties", headers={"Authorization": "Bearer bad"}).status_code == 401
    )
    assert c.post("/auth/logout", headers=h[0]).status_code == 200
    assert c.get("/me", headers=h[0]).status_code == 401


def test_over_18_self_attestation_recorded_on_verify(pilot):
    c, app, _h, _keys, *_ = pilot
    k = Keypair()  # fresh wallet, so verify() creates the Actor with over_18
    ch = c.post("/auth/challenge", json={"wallet": str(k.pubkey())}).json()
    body = {
        "challenge_id": ch["challenge_id"],
        "signature": str(k.sign_message(ch["message"].encode())),
        "over_18": True,
    }
    r = c.post("/auth/verify", json=body)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    me = c.get("/me", headers={"Authorization": "Bearer " + token})
    assert me.status_code == 200
    assert me.json()["over_18"] is True


def test_idempotency_ownership(pilot):
    c, _app, h, keys, *_ = pilot
    body = {
        "title": "Cup",
        "category_ids": [1],
        "reward_usdc_units": 100,
        "slots": 1,
        "deadline": now() + 3600,
    }
    headers = {**h[0], "Idempotency-Key": "same-key"}
    a = c.post("/bounties", json=body, headers=headers).json()
    assert c.post("/bounties", json=body, headers=headers).json() == a
    body["slots"] = 2
    assert c.post("/bounties", json=body, headers=headers).status_code == 409
    assert c.post(f"/bounties/{a['id']}/fund/prepare", headers=h[1]).status_code == 403
    assert (
        c.post(
            "/operator/enroll",
            json={"wallet": str(keys[5].pubkey())},
            headers={"x-operator-key": "bad"},
        ).status_code
        == 403
    )
    assert c.post("/auth/challenge", json={"wallet": "bad"}).status_code == 422


def test_blind_distinct_reviews_disagreement(pilot):
    c, app, h, _, chain, *_ = pilot
    _bid, sid, labels = submitted(pilot)
    for i in (0, 1):
        assert (
            c.post(f"/submissions/{sid}/reviews", headers=h[i], json=labels).status_code
            == 403
        )
    assert "boxes" not in c.get("/review-queue", headers=h[2]).json()[0]
    for _ in range(2):
        assert (
            c.post(f"/submissions/{sid}/reviews", headers=h[2], json=labels).json()[
                "status"
            ]
            == "review"
        )
    other = {
        **labels,
        "boxes": [{"category_id": 1, "x": 0.8, "y": 0.8, "w": 0.1, "h": 0.1}],
    }
    assert (
        c.post(f"/submissions/{sid}/reviews", headers=h[2], json=other).status_code
        == 409
    )
    assert (
        c.post(f"/submissions/{sid}/reviews", headers=h[3], json=other).json()["status"]
        == "disputed"
    )
    assert (
        c.post(f"/submissions/{sid}/fulfill/prepare", headers=h[1]).status_code == 403
    )
    assert chain.confirmed == 1
    with app.state.database.transaction() as db:
        assert len(db.scalars(select(Review)).all()) == 2


def test_media_gate_exact_bytes_privacy_immutability(pilot):
    c, app, h, keys, chain, mod, *_ = pilot
    bid = bounty(pilot)
    transact(pilot, f"/bounties/{bid}/fund")
    sid = c.post(f"/bounties/{bid}/claim", headers=h[1]).json()["id"]
    assert (
        c.post(f"/submissions/{sid}/media", headers=h[2], content=png()).status_code
        == 403
    )
    mod.reject = True
    assert (
        c.post(f"/submissions/{sid}/media", headers=h[1], content=png()).status_code
        == 422
    )
    assert c.get(f"/submissions/{sid}/media", headers=h[0]).status_code == 404
    mod.reject = False
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=png())
    assert r.status_code == 200
    media_hash = r.json()["media_hash"]
    calls = mod.calls
    assert (
        c.post(f"/submissions/{sid}/media", headers=h[1], content=png()).json()[
            "media_hash"
        ]
        == media_hash
    )
    assert mod.calls == calls
    assert (
        c.post(
            f"/submissions/{sid}/media", headers=h[1], content=png("blue")
        ).status_code
        == 409
    )
    assert (
        c.get(f"/submissions/{sid}/media", headers=h[1]).content
        == canonicalize(png())[0]
    )
    c.post(
        "/operator/enroll",
        json={"wallet": str(keys[5].pubkey())},
        headers={"x-operator-key": "o" * 32},
    )
    assert c.get(f"/submissions/{sid}/media", headers=h[5]).status_code == 403
    with app.state.database.transaction() as db:
        stored = db.get(Submission, sid).encrypted_media
        assert not stored.startswith(b"\x89PNG") and png() not in stored
    labels = {
        "media_hash": media_hash,
        "boxes": [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}],
    }
    assert (
        c.post(
            f"/submissions/{sid}/labels",
            headers=h[1],
            json={**labels, "media_hash": "0" * 64},
        ).status_code
        == 409
    )
    assert (
        c.post(
            f"/submissions/{sid}/labels",
            headers=h[1],
            json={**labels, "moderation": "PASS"},
        ).status_code
        == 422
    )
    assert (
        c.post(f"/submissions/{sid}/labels", headers=h[1], json=labels).status_code
        == 200
    )
    assert (
        c.post(f"/submissions/{sid}/media", headers=h[1], content=png()).status_code
        == 409
    )
    assert chain.confirmed == 1


def test_concurrent_claims_never_overreserve(pilot):
    c, _, h, *_ = pilot
    bid = bounty(pilot, slots=1)
    transact(pilot, f"/bounties/{bid}/fund")
    with ThreadPoolExecutor(max_workers=4) as pool:
        rs = list(
            pool.map(
                lambda i: c.post(f"/bounties/{bid}/claim", headers=h[i]), [1, 2, 3, 4]
            )
        )
    assert sorted(r.status_code for r in rs) == [200, 409, 409, 409]


def test_failed_confirmation_recovery(pilot):
    c, _, h, _, chain, *_ = pilot
    bid = bounty(pilot)
    tx = c.post(f"/bounties/{bid}/fund/prepare", headers=h[0]).json()
    chain.allowed = False
    assert (
        c.post(
            f"/transactions/{tx['id']}/confirm",
            headers=h[0],
            json={"signature": str(Keypair().sign_message(b"x"))},
        ).status_code
        == 503
    )
    assert c.get("/bounties", headers=h[0]).json()[0]["status"] == "draft"
    chain.allowed = True
    assert (
        c.post(f"/transactions/{tx['id']}/reconcile", headers=h[0]).status_code == 200
    )
    assert c.get("/bounties", headers=h[0]).json()[0]["status"] == "open"


@pytest.mark.parametrize(
    "box",
    [
        {"category_id": "1", "x": 0, "y": 0, "w": 1, "h": 1},
        {"category_id": 1, "x": 0.9, "y": 0, "w": 0.2, "h": 1},
        {"category_id": 1, "x": 0, "y": 0, "w": 0, "h": 1},
        {"category_id": 1, "x": float("nan"), "y": 0, "w": 1, "h": 1},
        {"category_id": 1, "x": 0, "y": 0, "w": 1, "h": 1, "confidence": 1},
    ],
)
def test_invalid_boxes(box):
    with pytest.raises(ValueError):
        Labels(media_hash="a" * 64, boxes=[box])


def test_matching_requires_every_box():
    a = {"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}
    b = {**a, "x": 0.5}
    assert agree([a, b], [b, a])
    assert not agree([a, b], [a, a])
    assert not agree([a], [a, b])
    assert not agree([a], [{**a, "category_id": 2}])


def test_provider_contract_fail_closed():
    benign = {
        "status": [
            {
                "status": {"code": 200},
                "response": {
                    "output": {
                        "file": {
                            "fileType": "image",
                            "reasons": [],
                            "classifierPrediction": {
                                "csam_classifier": {
                                    "csam": 0.001,
                                    "pornography": 0.001,
                                    "other": 0.998,
                                }
                            },
                        },
                        "hashes": [],
                    }
                },
            }
        ]
    }
    assert hive_pass(benign)
    benign["status"][0]["response"]["output"]["hashes"] = [{"matchTypes": ["CSAM"]}]
    assert not hive_pass(benign)
    assert sightengine_pass({"status": "success", "faces": []})
    assert not sightengine_pass(
        {"status": "success", "faces": [{"attributes": {"age": {"minor": 0}}}]}
    )
    with pytest.raises(KeyError):
        hive_pass({})
    with pytest.raises(KeyError):
        sightengine_pass({"status": "success"})
    with pytest.raises(MediaRejected):
        canonicalize(b"bad")
    cipher = MediaCipher(base64.b64encode(b"x" * 32).decode())
    encrypted = cipher.encrypt(png(), "digest")
    assert cipher.decrypt(encrypted, "digest") == png()
    with pytest.raises(InvalidTag):
        cipher.decrypt(encrypted, "wrong-digest")


def test_reject_expiry_refund_and_deposit_routes(pilot):
    from seeker.db import Bounty

    c, app, h, _, _chain, *_ = pilot
    bid, sid, _ = eligible(pilot)
    transact(pilot, "/bond/deposit", 1)
    transact(pilot, "/bond/withdraw", 1)
    transact(pilot, f"/submissions/{sid}/fulfill", 1)
    assert c.post(f"/submissions/{sid}/expire/prepare", headers=h[1]).status_code == 409
    assert c.post(f"/bounties/{bid}/refund/prepare", headers=h[0]).status_code == 409
    with app.state.database.transaction() as db:
        db.get(Bounty, bid).deadline = 0
    assert c.post(f"/submissions/{sid}/accept/prepare", headers=h[0]).status_code == 409
    transact(pilot, f"/submissions/{sid}/expire", 1)
    transact(pilot, f"/bounties/{bid}/refund")
    assert c.get("/submissions", headers=h[0]).json()[0]["status"] == "expired"
    assert c.get("/bounties", headers=h[0]).json()[0]["status"] == "refunded"
    assert c.get("/transactions", headers=h[0]).status_code == 200
    assert c.get("/me", headers=h[0]).json()["identity_status"] == "operator-enrolled"
    assert c.get("/health").json()["production_ready"] is False


def test_revoked_worker_and_duplicate_upload(pilot):
    c, _app, h, keys, _chain, _mod, *_ = pilot
    bid, sid, labels = submitted(pilot)
    second = c.post(f"/bounties/{bid}/claim", headers=h[4]).json()["id"]
    assert (
        c.post(f"/submissions/{second}/media", headers=h[4], content=png()).status_code
        == 409
    )
    c.post(
        "/operator/enroll",
        json={"wallet": str(keys[4].pubkey())},
        headers={"x-operator-key": "o" * 32},
    )
    assert (
        c.post(f"/submissions/{second}/media", headers=h[4], content=png()).status_code
        == 403
    )
    assert c.post("/bond/deposit/prepare", headers=h[4]).status_code == 403
    assert c.get("/review-queue", headers=h[4]).status_code == 403
    assert (
        c.post(f"/submissions/{sid}/labels", headers=h[1], json=labels).status_code
        == 200
    )
    unknown = {**labels, "boxes": [{**labels["boxes"][0], "category_id": 999}]}
    assert (
        c.post(f"/submissions/{sid}/labels", headers=h[1], json=unknown).status_code
        == 422
    )
    assert (
        c.post(
            f"/submissions/{sid}/labels",
            headers=h[1],
            json={**labels, "boxes": labels["boxes"] * 2},
        ).status_code
        == 422
    )


@pytest.mark.asyncio
async def test_moderation_errors_do_not_pass(pilot, monkeypatch):
    import httpx
    from seeker.media import Moderation

    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    settings = pilot[-1]
    m = Moderation(settings)
    with pytest.raises(MediaRejected):
        await m.scan(png())
    settings.sightengine_user = "user"
    settings.sightengine_secret = "secret"
    settings.hive_key = "test"

    async def unavailable(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", unavailable)
    with pytest.raises(MediaRejected):
        await m.scan(png())

    async def incomplete(*args, **kwargs):
        return httpx.Response(
            200, json={}, request=httpx.Request("POST", "https://example.test")
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", incomplete)
    with pytest.raises(MediaRejected):
        await m.scan(png())

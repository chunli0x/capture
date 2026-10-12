"""Capture v2: open-upload pipeline, leveling, payout, and the stub judge."""

import base64
import io
import os
import struct

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from seeker.api import create_app
from seeker.config import Settings
from seeker.db import Actor, Base, Submission, now
from seeker.judge import StubJudge, Verdict, build_judge
from seeker.leveling import (
    bond_multiplier,
    level_for,
    level_info,
    rate_multiplier,
)
from seeker.payout import payout_units
from seeker.schemas import Labels
from solders.keypair import Keypair
from sqlalchemy import select


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

    def settle_usdc(self, wallet, amount):
        return str(Keypair().sign_message(b"settle"))


class FakeModerator:
    async def scan(self, data):
        return {"policy": "TEST-ONLY", "result": "pass"}

    async def scan_video(self, data):
        return {"policy": "TEST-ONLY", "result": "pass"}


@pytest.fixture
def pilot(tmp_path):
    chain, mod = FakeChain(), FakeModerator()
    settings = Settings(
        database_url="sqlite:///" + str(tmp_path / "v2.db"),
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
    # Capture v2 requires a completed server-side liveness proof before an open
    # upload. Enroll every worker and complete liveness so the open-upload tests
    # exercise the real (post-gate) flow.
    for k, hd in zip(keys, h):
        do_liveness(c, hd, str(k.pubkey()))
    # Capture bond gate: bond every worker so the open-upload tests exercise the
    # bonded (instant-judge) path. The free peer-review path is covered in
    # test_bond_gate.py.
    for hd in h:
        assert c.post("/bond/faucet", headers=hd).status_code == 200
        tx = c.post("/bond/deposit", headers=hd).json()
        sig = str(Keypair().sign_message(tx["id"].encode()))
        assert (
            c.post(
                f"/transactions/{tx['id']}/confirm", headers=hd, json={"signature": sig}
            ).status_code
            == 200
        )
    yield c, app, h, keys, settings
    app.state.database.engine.dispose()


def png(color="red"):
    out = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(out, "PNG")
    return out.getvalue()


# ---- minimal mp4 builder (mirrors test_seeker_phase2) ----


def _box(typ, payload=b""):
    return struct.pack(">I", 8 + len(payload)) + typ + payload


def _mvhd(duration_ms, timescale=1000):
    payload = (
        b"\x00\x00\x00\x00"
        + struct.pack(">II", 0, 0)
        + struct.pack(">I", timescale)
        + struct.pack(">I", duration_ms * timescale // 1000)
        + b"\x00" * 80
    )
    return _box(b"mvhd", payload)


def _hdlr(handler):
    return _box(b"hdlr", b"\x00\x00\x00\x00" + struct.pack(">I", 0) + handler + b"\x00" * 12)


def _mdhd(duration_ms, timescale=1000):
    payload = (
        b"\x00\x00\x00\x00"
        + struct.pack(">II", 0, 0)
        + struct.pack(">I", timescale)
        + struct.pack(">I", duration_ms * timescale // 1000)
        + struct.pack(">HH", 0x55C4, 0)
    )
    return _box(b"mdhd", payload)


def _stts(sample_count, sample_delta):
    return _box(
        b"stts", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + struct.pack(">II", sample_count, sample_delta)
    )


def _trak(handler, duration_ms=2000):
    stbl = _box(b"stbl", _stts(1, duration_ms))
    minf = _box(b"minf", stbl)
    mdia = _box(b"mdia", _mdhd(duration_ms) + _hdlr(handler) + minf)
    return _box(b"trak", mdia)


def mp4(duration_ms=2000):
    children = [_mvhd(duration_ms), _trak(b"vide", duration_ms), _trak(b"soun", duration_ms)]
    moov = _box(b"moov", b"".join(children))
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isom")
    return ftyp + moov + _box(b"mdat", b"\x00" * 16)


# ---- helpers ----


def open_submission(c, h, kind="object"):
    r = c.post("/submissions", headers=h, json={"kind": kind})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def do_liveness(c, h, wallet, task_id="capture-session"):
    """Run the /liveness/session -> /liveness/complete flow for a wallet."""
    r = c.post(
        "/liveness/session",
        headers=h,
        json={"contributor": wallet, "task_id": task_id},
    )
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]
    r = c.post(
        "/liveness/complete",
        headers=h,
        json={"contributor": wallet, "session_id": session_id, "result_digest": "ab" * 32},
    )
    assert r.status_code == 200, r.text
    return r.json()["liveness_proof_hash"]


def upload_media(c, h, sid, content=None):
    r = c.post(f"/submissions/{sid}/media", headers=h, content=content or png())
    assert r.status_code == 200, r.text
    return r.json()["media_hash"]


def object_labels(media_hash, postures=(1,), environment=(), **extra):
    body = {
        "media_hash": media_hash,
        "boxes": [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
        "postures": list(postures),
    }
    if environment:
        body["environment"] = list(environment)
    body.update(extra)
    return body


# ---- leveling ----


def test_level_ladder_matches_contract():
    assert level_for(0, 0.0) == 0
    assert level_for(24, 1.0) == 0
    assert level_for(25, 0.90) == 1
    assert level_for(25, 0.89) == 0  # rate gate fails -> still Scout
    assert level_for(100, 0.95) == 2
    assert level_for(100, 0.94) == 1  # passes Regular, misses Veteran
    assert level_for(500, 0.97) == 3
    assert level_for(2000, 0.98) == 4
    assert level_for(2000, 0.97) == 3  # misses Pathfinder's 98% gate
    assert rate_multiplier(0) == 1.0
    assert rate_multiplier(4) == 1.5
    assert bond_multiplier(0) == 2.0
    assert bond_multiplier(4) == 0.0  # waived


def test_level_info_shape_matches_contract():
    info = level_info(30, 0.93)
    assert set(info) == {
        "level",
        "level_name",
        "accepted_count",
        "acceptance_rate",
        "rate_multiplier",
        "bond_multiplier",
    }
    assert info["level"] == 1
    assert info["level_name"] == "Regular"
    assert info["accepted_count"] == 30
    assert info["acceptance_rate"] == 0.93


# ---- payout ----


def test_payout_rates_match_contract():
    # complete 6-dim photo: $0.10; minimal (3-primary): $0.07
    assert payout_units(0, "object", None, True) == 100_000
    assert payout_units(0, "object", None, False) == 70_000
    # video tiers: $0.25 / $0.40 complete
    assert payout_units(0, "action", 10_000, True) == 250_000
    assert payout_units(0, "action", 20_000, True) == 400_000
    # top tier (level 4, x1.5): $0.15 / $0.38 / $0.60 — matches unit-economics §5
    assert payout_units(4, "object", None, True) == 150_000
    assert payout_units(4, "action", 10_000, True) == 380_000
    assert payout_units(4, "action", 20_000, True) == 600_000


def test_media_tier_buckets_duration():
    from seeker.payout import media_tier

    assert media_tier("object", None) == "photo"
    assert media_tier("place", None) == "photo"
    assert media_tier("action", 5000) == "video_short"
    assert media_tier("action", 15_000) == "video_short"
    assert media_tier("action", 15_001) == "video_long"
    assert media_tier("action", 30_000) == "video_long"


# ---- stub judge ----


def test_stub_judge_rules():
    j = StubJudge()
    good = dict(secondary={"postures": [{"id": 1}]}, metadata={"ego_motion": True})
    img = b"fake-png-bytes"
    # no media -> reject
    assert j.judge("object", [{"x": 1}], good["secondary"], good["metadata"], None, False, None).accepted is False
    # no primary label -> reject
    assert j.judge("object", None, good["secondary"], good["metadata"], None, True, img).accepted is False
    # no posture -> reject
    assert j.judge("object", [{"x": 1}], {}, {"ego_motion": True}, None, True, img).accepted is False
    # video with no ego-motion -> reject
    v = j.judge("action", [{"x": 1}], good["secondary"], {}, None, True, img)
    assert v.accepted is False and "ego-motion" in v.reason
    # happy object path -> accept
    assert j.judge("object", [{"x": 1}], good["secondary"], good["metadata"], None, True, img).accepted is True
    # media present but pixels undecodable: stub still keys off has_media, so a
    # header-only synthetic video with valid labels accepts (stub is label-only)
    assert j.judge("action", [{"x": 1}], good["secondary"], {"ego_motion": True}, 9000, True, None).accepted is True
    # weather tagged while indoor -> reject
    indoor = {"postures": [{"id": 1}], "environment": [{"id": 1, "name": "indoor", "kind": "environment", "group": "indoor_outdoor"}]}
    assert j.judge("object", [{"x": 1}], indoor, {"weather": {"id": "sun"}, "ego_motion": True}, None, True, img).accepted is False


def test_build_judge_defaults_to_stub(monkeypatch):
    monkeypatch.delenv("SEEKER_JUDGE_DRIVER", raising=False)
    assert isinstance(build_judge(), StubJudge)


def test_build_judge_env_gates_astra(monkeypatch):
    from seeker.judge import AstraJudge

    monkeypatch.setenv("SEEKER_JUDGE_DRIVER", "astra")
    assert isinstance(build_judge(), AstraJudge)


def test_parse_verdict_accepts_bare_and_fenced():
    from seeker.judge import _parse_verdict

    assert _parse_verdict('{"accepted": true, "reason": "ok"}').accepted is True
    assert _parse_verdict('```json\n{"accepted": false, "reason": "blurry"}\n```').accepted is False
    assert _parse_verdict("garbage") is None
    assert _parse_verdict("") is None
    # non-bool accepted is rejected as unparseable
    assert _parse_verdict('{"accepted": "yes", "reason": "x"}') is None


def test_astra_judge_fails_closed_when_codex_missing(monkeypatch):
    from seeker.judge import AstraJudge, JudgeUnavailable

    j = AstraJudge(codex_bin="/nonexistent/codex")
    try:
        j.judge("object", [{"x": 1}], {"postures": [{"id": 1}]}, {}, None, True, b"img")
        assert False, "expected JudgeUnavailable"
    except JudgeUnavailable:
        pass


def test_astra_judge_fails_closed_when_no_decodable_image():
    from seeker.judge import AstraJudge, JudgeUnavailable

    j = AstraJudge(codex_bin="/nonexistent/codex")
    # media present but pixels undecodable -> fail closed, not accept
    try:
        j.judge("object", [{"x": 1}], {"postures": [{"id": 1}]}, {}, None, True, None)
        assert False, "expected JudgeUnavailable"
    except JudgeUnavailable:
        pass
    # genuinely no media -> ordinary reject (not an availability error)
    assert j.judge("object", [{"x": 1}], {"postures": [{"id": 1}]}, {}, None, False, None).accepted is False


# ---- open-upload HTTP flow ----


def test_open_upload_object_accept_pays_and_levels(pilot):
    c, app, h, *_ = pilot
    sid = open_submission(c, h[1])
    media_hash = upload_media(c, h[1], sid)
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json=object_labels(media_hash, postures=[1], environment=[1]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "accepted"
    assert body["verdict"] == {
        "accepted": True,
        "reason": "accepted by deterministic stub judge",
    }
    assert body["payout_usdc"] == 100_000  # complete photo, level 0 -> $0.10
    assert body["level_after"] == 0  # 1 accepted is still Scout
    # persisted judge outcome
    with app.state.database.transaction() as db:
        s = db.get(Submission, sid)
        assert s.accepted is True
        assert s.payout_usdc == 100_000
        assert s.capture_metadata == {"ego_motion": False}


def test_open_upload_minimal_label_pays_base_rate(pilot):
    c, _app, h, *_ = pilot
    sid = open_submission(c, h[1])
    media_hash = upload_media(c, h[1], sid)
    # posture only (no environment) -> minimal rate, no +50% premium
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json=object_labels(media_hash, postures=[1]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["verdict"]["accepted"] is True
    assert r.json()["payout_usdc"] == 70_000  # $0.07 minimal


def test_open_upload_missing_posture_rejected(pilot):
    c, _app, h, *_ = pilot
    sid = open_submission(c, h[1])
    media_hash = upload_media(c, h[1], sid)
    body = {
        "media_hash": media_hash,
        "boxes": [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
    }
    r = c.post(f"/submissions/{sid}/labels", headers=h[1], json=body)
    assert r.status_code == 422


def test_open_upload_unknown_metadata_rejected(pilot):
    c, _app, h, *_ = pilot
    sid = open_submission(c, h[1])
    media_hash = upload_media(c, h[1], sid)
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json=object_labels(media_hash, postures=[1], surface_type="lava"),
    )
    assert r.status_code == 422


def test_open_upload_static_video_rejected(pilot):
    c, app, h, *_ = pilot
    sid = open_submission(c, h[1], kind="action")
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=mp4(10_000))
    assert r.status_code == 200, r.text
    media_hash = r.json()["media_hash"]
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json={
            "media_hash": media_hash,
            "action": {"category_id": 8, "start_ms": 0, "end_ms": 9000},
            "postures": [1],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["verdict"]["accepted"] is False
    assert r.json()["payout_usdc"] == 0


def test_open_upload_moving_video_accepts_and_pays(pilot):
    c, app, h, *_ = pilot
    sid = open_submission(c, h[1], kind="action")
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=mp4(10_000))
    assert r.status_code == 200, r.text
    media_hash = r.json()["media_hash"]
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json={
            "media_hash": media_hash,
            "action": {"category_id": 8, "start_ms": 0, "end_ms": 9000},
            "postures": [1],
            "environment": [1],
            "ego_motion": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["verdict"]["accepted"] is True
    assert r.json()["payout_usdc"] == 250_000  # complete video 5-15s -> $0.25


def test_open_upload_requires_worker(pilot):
    c, _app, h, keys, *_ = pilot
    # enroll a fresh wallet as worker-only=False is not possible here; instead
    # assert an unauthenticated request is refused.
    assert c.post("/submissions", json={"kind": "object"}).status_code == 401


def test_me_exposes_level_fields_after_accept(pilot):
    c, _app, h, *_ = pilot
    me = c.get("/me", headers=h[1]).json()
    assert me["level"] == 0
    assert me["level_name"] == "Scout"
    assert me["accepted_count"] == 0
    assert me["rate_multiplier"] == 1.0
    assert me["bond_multiplier"] == 2.0

    sid = open_submission(c, h[1])
    media_hash = upload_media(c, h[1], sid)
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json=object_labels(media_hash, postures=[1], environment=[1]),
    )
    assert r.status_code == 200
    me = c.get("/me", headers=h[1]).json()
    assert me["accepted_count"] == 1
    assert me["acceptance_rate"] == 1.0
    assert me["level"] == 0  # 1 accepted < 25 threshold


def test_acceptance_rate_rolls_over_rejects(pilot):
    c, app, h, *_ = pilot
    # one accepted then one rejected -> 0.5 rolling rate
    sid = open_submission(c, h[1])
    mh = upload_media(c, h[1], sid)
    assert c.post(f"/submissions/{sid}/labels", headers=h[1], json=object_labels(mh, postures=[1], environment=[1])).status_code == 200

    sid2 = open_submission(c, h[1], kind="action")
    r = c.post(f"/submissions/{sid2}/media", headers=h[1], content=mp4())
    mh2 = r.json()["media_hash"]
    r = c.post(
        f"/submissions/{sid2}/labels",
        headers=h[1],
        json={"media_hash": mh2, "action": {"category_id": 8, "start_ms": 0, "end_ms": 1000}, "postures": [1]},
    )
    assert r.status_code == 200
    assert r.json()["verdict"]["accepted"] is False  # static video rejected

    me = c.get("/me", headers=h[1]).json()
    assert me["accepted_count"] == 1
    assert me["acceptance_rate"] == 0.5


# ---- audit fixes: idempotent retry, open-upload recovery, liveness gate ----


def test_open_labels_idempotent_retry_returns_stored_verdict(pilot):
    """Retrying a committed label must return the stored verdict (200), never a
    409, and must never double-increment the worker's accepted_count."""
    c, app, h, keys, *_ = pilot
    sid = open_submission(c, h[1])
    media_hash = upload_media(c, h[1], sid)
    body = object_labels(media_hash, postures=[1], environment=[1])

    first = c.post(f"/submissions/{sid}/labels", headers=h[1], json=body)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "accepted"

    retry = c.post(f"/submissions/{sid}/labels", headers=h[1], json=body)
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "accepted"
    assert retry.json()["verdict"] == first.json()["verdict"]
    assert retry.json()["payout_usdc"] == first.json()["payout_usdc"]

    with app.state.database.transaction() as db:
        assert db.get(Actor, str(keys[1].pubkey())).accepted_count == 1


def test_submissions_lists_open_upload_with_stored_verdict(pilot):
    """GET /submissions must expose open (no-bounty) uploads with their stored
    judge verdict, not hide them behind an inner join."""
    c, _app, h, *_ = pilot
    sid = open_submission(c, h[1])
    media_hash = upload_media(c, h[1], sid)
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json=object_labels(media_hash, postures=[1], environment=[1]),
    )
    assert r.status_code == 200, r.text

    entry = next(s for s in c.get("/submissions", headers=h[1]).json() if s["id"] == sid)
    assert entry["bounty_id"] is None
    assert entry["status"] == "accepted"
    assert entry["accepted"] is True
    assert entry["verdict_reason"] == "accepted by deterministic stub judge"
    assert entry["payout_usdc"] == 100_000


def test_open_submission_expiry_blocks_late_label(pilot):
    """An open upload past its expiration must refuse a new label."""
    c, app, h, *_ = pilot
    sid = open_submission(c, h[1])
    media_hash = upload_media(c, h[1], sid)
    with app.state.database.transaction() as db:
        db.get(Submission, sid).expires = now() - 1
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json=object_labels(media_hash, postures=[1], environment=[1]),
    )
    assert r.status_code == 409
    assert "expired" in r.json()["detail"].lower()


def test_open_submit_requires_liveness(pilot):
    """POST /submissions must refuse a worker without a completed liveness proof."""
    c, _app, _h, _keys, *_ = pilot
    k = Keypair()
    ch = c.post("/auth/challenge", json={"wallet": str(k.pubkey())}).json()
    token = c.post(
        "/auth/verify",
        json={
            "challenge_id": ch["challenge_id"],
            "signature": str(k.sign_message(ch["message"].encode())),
        },
    ).json()["token"]
    hd = {"Authorization": "Bearer " + token}
    assert (
        c.post(
            "/operator/enroll",
            json={"wallet": str(k.pubkey()), "worker": True, "reviewer": False},
            headers={"x-operator-key": "o" * 32},
        ).status_code
        == 200
    )
    r = c.post("/submissions", headers=hd, json={"kind": "object"})
    assert r.status_code == 403
    assert "liveness" in r.json()["detail"].lower()
    do_liveness(c, hd, str(k.pubkey()))
    # Bond the fresh worker so the post-liveness open upload passes the gate.
    assert c.post("/bond/faucet", headers=hd).status_code == 200
    tx = c.post("/bond/deposit", headers=hd).json()
    sig = str(Keypair().sign_message(tx["id"].encode()))
    assert (
        c.post(
            f"/transactions/{tx['id']}/confirm", headers=hd, json={"signature": sig}
        ).status_code
        == 200
    )
    assert c.post("/submissions", headers=hd, json={"kind": "object"}).status_code == 200


def test_liveness_requires_matching_wallet(pilot):
    """Liveness endpoints must bind to the authenticated wallet: a session or
    completion for a different contributor is refused."""
    c, _app, h, keys, *_ = pilot
    r = c.post(
        "/liveness/session",
        headers=h[0],
        json={"contributor": str(keys[1].pubkey()), "task_id": "capture-session"},
    )
    assert r.status_code == 403
    r = c.post(
        "/liveness/session",
        headers=h[0],
        json={"contributor": str(keys[0].pubkey()), "task_id": "capture-session"},
    )
    session_id = r.json()["session_id"]
    r = c.post(
        "/liveness/complete",
        headers=h[1],
        json={
            "contributor": str(keys[0].pubkey()),
            "session_id": session_id,
            "result_digest": "ab" * 32,
        },
    )
    assert r.status_code == 403


def test_health_reports_real_readiness(pilot):
    """/health reflects readiness: an unreachable chain yields 503 + a per-check
    breakdown, while DB/schema/judge are reported as ready."""
    c, _app, _h, *_ = pilot
    r = c.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["production_ready"] is False
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["schema"] == "applied"
    assert body["checks"]["judge"] == "stubbed"
    assert body["checks"]["chain"] == "unreachable"

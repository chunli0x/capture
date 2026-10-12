"""Phase 2: places, video/action bounties, cloud keypoints, fail-closed video moderation."""

import base64
import io
import os
import struct

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from seeker.api import create_app
from seeker.config import Settings
from seeker.db import Base, Database, Submission
from seeker.media import (
    MAX_VIDEO_BYTES,
    MediaCipher,
    MediaRejected,
    Moderation,
    canonicalize_video,
    sightengine_genai_pass,
    sightengine_nudity_pass,
    sightengine_video_pass,
)
from seeker.schemas import ActionLabels, ActionSpan, PlaceLabels, Scene
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


class FakeModerator:
    reject = False
    reject_video = False
    image_calls = 0
    video_calls = 0

    async def scan(self, data):
        self.image_calls += 1
        if self.reject:
            raise MediaRejected("test rejection")
        return {"policy": "TEST-ONLY", "result": "pass"}

    async def scan_video(self, data):
        self.video_calls += 1
        if self.reject_video:
            raise MediaRejected("test video rejection")
        return {"policy": "TEST-ONLY", "result": "pass"}


@pytest.fixture
def pilot(tmp_path):
    chain, mod = FakeChain(), FakeModerator()
    settings = Settings(
        database_url="sqlite:///" + str(tmp_path / "phase2.db"),
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
    payload = b"\x00\x00\x00\x00" + struct.pack(">I", 0) + handler + b"\x00" * 12
    return _box(b"hdlr", payload)


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
    payload = (
        b"\x00\x00\x00\x00"
        + struct.pack(">I", 1)
        + struct.pack(">II", sample_count, sample_delta)
    )
    return _box(b"stts", payload)


def _trak(handler, duration_ms=2000):
    stbl = _box(b"stbl", _stts(1, duration_ms))
    minf = _box(b"minf", stbl)
    mdia = _box(b"mdia", _mdhd(duration_ms) + _hdlr(handler) + minf)
    return _box(b"trak", mdia)


def _udta(marker):
    return _box(b"udta", _box(b"\xa9xyz", marker))


def mp4(
    duration_ms=2000,
    video=True,
    extra_video=False,
    audio=True,
    track_duration_ms=None,
    marker=None,
):
    if track_duration_ms is None:
        track_duration_ms = duration_ms
    children = [_mvhd(duration_ms)]
    if video:
        children.append(_trak(b"vide", track_duration_ms))
    if extra_video:
        children.append(_trak(b"vide", track_duration_ms))
    if audio:
        children.append(_trak(b"soun", duration_ms))
    if marker is not None:
        children.append(_udta(marker))
    moov = _box(b"moov", b"".join(children))
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isom")
    return ftyp + moov + _box(b"mdat", b"\x00" * 16)


def bounty(p, kind="object", category_ids=None, slots=2):
    c, _, h, *_ = p
    if category_ids is None:
        category_ids = [1]
    body = {
        "kind": kind,
        "title": "Phase 2 bounty",
        "category_ids": category_ids,
        "reward_usdc_units": 1000,
        "slots": slots,
        "deadline": int(__import__("time").time()) + 3600,
    }
    r = c.post(
        "/bounties", headers={**h[0], "Idempotency-Key": os.urandom(8).hex()}, json=body
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def fund_and_claim(p, bid, actor=1):
    c, _, h, *_ = p
    tx = c.post(f"/bounties/{bid}/fund/prepare", headers=h[0]).json()
    sig = str(Keypair().sign_message(tx["id"].encode()))
    assert (
        c.post(
            f"/transactions/{tx['id']}/confirm",
            headers=h[0],
            json={"signature": sig},
        ).status_code
        == 200
    )
    r = c.post(f"/bounties/{bid}/claim", headers=h[actor])
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---- schema-level label shapes ----


def test_place_single_class_enforcement():
    assert PlaceLabels(media_hash="a" * 64, scene={"category_id": 3}).scene.category_id == 3
    # No multi-label: a list of scenes is rejected, extra fields are rejected.
    with pytest.raises(ValueError):
        PlaceLabels(media_hash="a" * 64, scene=[{"category_id": 1}])
    with pytest.raises(ValueError):
        PlaceLabels(media_hash="a" * 64, scene={"category_id": 1, "category_id2": 2})
    with pytest.raises(ValueError):
        PlaceLabels(media_hash="a" * 64, scene={"category_id": "1"})


def test_action_trim_bounds_schema():
    ok = ActionLabels(media_hash="a" * 64, action={"category_id": 1, "start_ms": 0, "end_ms": 3000})
    assert ok.action.start_ms == 0 and ok.action.end_ms == 3000
    for bad in [
        {"category_id": 1, "start_ms": 3000, "end_ms": 3000},
        {"category_id": 1, "start_ms": 4000, "end_ms": 3000},
        {"category_id": 1, "start_ms": -1, "end_ms": 3000},
        {"category_id": 1, "start_ms": 0, "end_ms": 0},
    ]:
        with pytest.raises(ValueError):
            ActionLabels(media_hash="a" * 64, action=bad)
    with pytest.raises(ValueError):
        ActionSpan(category_id=1, start_ms=1.5, end_ms=3)


def test_create_bounty_kind_namespace():
    from seeker.schemas import CreateBounty

    # Duplicate category ids are rejected at the schema boundary.
    with pytest.raises(ValueError):
        CreateBounty(
            kind="action",
            title="xxx",
            category_ids=[1, 1],
            reward_usdc_units=1,
            slots=1,
            deadline=1234,
        )
    # A free-text category name (the phase-1 gap) is no longer accepted at all:
    # `categories` is an unknown field, so the request can never mint a label.
    with pytest.raises(ValueError):
        CreateBounty(
            kind="place",
            title="xxx",
            category_ids=[1],
            categories=[{"id": 1, "name": "beach", "kind": "place"}],
            reward_usdc_units=1,
            slots=1,
            deadline=1234,
        )
    body = CreateBounty(
        kind="place",
        title="xxx",
        category_ids=[1, 2],
        reward_usdc_units=1,
        slots=1,
        deadline=1234,
    )
    assert body.kind == "place"
    assert body.category_ids == [1, 2]


# ---- taxonomy registry + server-side resolution ----


def test_taxonomy_endpoint_returns_registry(pilot):
    c, *_ = pilot
    r = c.get("/taxonomy")
    assert r.status_code == 200, r.text
    categories = r.json()["categories"]
    by = {(c["id"], c["kind"]): c for c in categories}
    # Every entry carries id/name/kind; environment also carries group.
    assert all({"id", "name", "kind"} <= set(c) for c in categories)
    # Spot-check the names the label pipeline relies on across namespaces.
    assert by[(1, "object")]["name"] == "bowls"
    assert by[(1, "place")]["name"] == "bed"
    assert by[(1, "action")]["name"] == "look around"
    # v2 object/action additions are present.
    assert by[(14, "object")]["name"] == "stairs"
    assert by[(15, "object")]["name"] == "person"
    assert by[(16, "object")]["name"] == "obstacles-clutter"
    assert by[(17, "object")]["name"] == "curb-step"
    assert by[(21, "action")]["name"] == "person walking"
    # Secondary dimensions are present and environment carries a group.
    assert by[(1, "expression")]["name"] == "neutral"
    assert by[(1, "posture")]["name"] == "standing"
    assert by[(1, "environment")]["group"] == "indoor_outdoor"
    # posture is required, expression is optional, per the v2 contract.
    assert by[(1, "posture")]["required"] is True
    assert by[(1, "expression")]["required"] is False
    # String-keyed metadata registries are present with a string id.
    assert by[("hardwood", "surface_type")]["name"] == "Hardwood"
    assert by[("day", "lighting")]["name"] == "Day"
    assert by[("sun", "weather")]["name"] == "Sun"
    assert by[("forward", "ego_motion")]["name"] == "Forward"


def test_create_bounty_rejects_unknown_category_id(pilot):
    c, _, h, *_ = pilot
    r = c.post(
        "/bounties",
        headers={**h[0], "Idempotency-Key": os.urandom(8).hex()},
        json={
            "kind": "object",
            "title": "Unknown category bounty",
            "category_ids": [9999],
            "reward_usdc_units": 100,
            "slots": 1,
            "deadline": int(__import__("time").time()) + 3600,
        },
    )
    assert r.status_code == 422


def test_create_bounty_builds_taxonomy_from_registry(pilot):
    c, _, h, *_ = pilot
    r = c.post(
        "/bounties",
        headers={**h[0], "Idempotency-Key": os.urandom(8).hex()},
        json={
            "kind": "object",
            "title": "Registry taxonomy bounty",
            "category_ids": [1, 2],
            "reward_usdc_units": 100,
            "slots": 1,
            "deadline": int(__import__("time").time()) + 3600,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["categories"] == [
        {"id": 1, "name": "bowls", "kind": "object"},
        {"id": 2, "name": "toys", "kind": "object"},
    ]


def test_secondary_labels_accepted_and_stored(pilot):
    c, _, h, *_ = pilot
    bid = bounty(pilot, kind="object")
    sid = fund_and_claim(pilot, bid)
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=png())
    assert r.status_code == 200, r.text
    media_hash = r.json()["media_hash"]
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json={
            "media_hash": media_hash,
            "boxes": [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
            "expressions": [1, 2],
            "postures": [1, 7],
            "environment": [1, 3, 7, 12, 21],
        },
    )
    assert r.status_code == 200, r.text
    secondary = r.json()["secondary"]
    assert [e["id"] for e in secondary["expressions"]] == [1, 2]
    assert [p["id"] for p in secondary["postures"]] == [1, 7]
    assert [e["id"] for e in secondary["environment"]] == [1, 3, 7, 12, 21]
    # Primary label is unchanged by the secondary tags.
    assert r.json()["boxes"] == [
        {"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}
    ]


def test_secondary_unknown_id_rejected(pilot):
    c, _, h, *_ = pilot
    bid = bounty(pilot, kind="object")
    sid = fund_and_claim(pilot, bid)
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=png())
    media_hash = r.json()["media_hash"]
    base = {
        "media_hash": media_hash,
        "boxes": [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
    }
    assert (
        c.post(
            f"/submissions/{sid}/labels",
            headers=h[1],
            json={**base, "expressions": [999]},
        ).status_code
        == 422
    )
    assert (
        c.post(
            f"/submissions/{sid}/labels",
            headers=h[1],
            json={**base, "postures": [999]},
        ).status_code
        == 422
    )


def test_environment_one_per_group(pilot):
    c, _, h, *_ = pilot
    bid = bounty(pilot, kind="object")
    sid = fund_and_claim(pilot, bid)
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=png())
    media_hash = r.json()["media_hash"]
    # Two ids in the same group (indoor + outdoor) are rejected.
    assert (
        c.post(
            f"/submissions/{sid}/labels",
            headers=h[1],
            json={
                "media_hash": media_hash,
                "boxes": [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
                "environment": [1, 2],
            },
        ).status_code
        == 422
    )


def test_over_18_stored_and_returned_by_me(pilot):
    c, _, h, keys, *_ = pilot
    # Declared over-18 is recorded and surfaced in /me.
    assert (
        c.post(
            "/operator/enroll",
            json={
                "wallet": str(keys[0].pubkey()),
                "worker": True,
                "reviewer": True,
                "over_18": True,
            },
            headers={"x-operator-key": "o" * 32},
        ).status_code
        == 200
    )
    assert c.get("/me", headers=h[0]).json()["over_18"] is True
    # Omitted over_18 defaults to False.
    assert (
        c.post(
            "/operator/enroll",
            json={"wallet": str(keys[1].pubkey()), "worker": True, "reviewer": True},
            headers={"x-operator-key": "o" * 32},
        ).status_code
        == 200
    )
    assert c.get("/me", headers=h[1]).json()["over_18"] is False


# ---- API: place single-class, action trim bounds ----


def test_place_bounty_accepts_only_single_scene(pilot):
    c, _, h, *_ = pilot
    bid = bounty(pilot, kind="place")
    sid = fund_and_claim(pilot, bid)
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=png())
    assert r.status_code == 200, r.text
    media_hash = r.json()["media_hash"]
    # Object boxes are the wrong shape for a place bounty.
    assert (
        c.post(
            f"/submissions/{sid}/labels",
            headers=h[1],
            json={
                "media_hash": media_hash,
                "boxes": [{"category_id": 1, "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
            },
        ).status_code
        == 422
    )
    # A single scene class is accepted.
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json={"media_hash": media_hash, "scene": {"category_id": 1}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["boxes"] == {"scene": {"category_id": 1}}


def test_action_trim_bounds_enforced_against_clip(pilot):
    c, _, h, *_ = pilot
    bid = bounty(pilot, kind="action")
    sid = fund_and_claim(pilot, bid)
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=mp4(5000))
    assert r.status_code == 200, r.text
    media_hash = r.json()["media_hash"]
    base = {"media_hash": media_hash, "action": {"category_id": 1}}
    # Trim exceeding the 5000 ms clip.
    assert (
        c.post(
            f"/submissions/{sid}/labels",
            headers=h[1],
            json={**base, "action": {"category_id": 1, "start_ms": 0, "end_ms": 10000}},
        ).status_code
        == 422
    )
    # start >= end is a schema violation.
    assert (
        c.post(
            f"/submissions/{sid}/labels",
            headers=h[1],
            json={**base, "action": {"category_id": 1, "start_ms": 3000, "end_ms": 3000}},
        ).status_code
        == 422
    )
    # In-range trim is accepted.
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json={"media_hash": media_hash, "action": {"category_id": 1, "start_ms": 1000, "end_ms": 4000}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["boxes"] == {
        "action": {"category_id": 1, "start_ms": 1000, "end_ms": 4000}
    }


def test_keypoint_write_rejected_for_seekers(pilot):
    c, _, h, *_ = pilot
    bid = bounty(pilot, kind="action")
    sid = fund_and_claim(pilot, bid)
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=mp4())
    media_hash = r.json()["media_hash"]
    # A seeker attempt to write keypoints is a hard 400.
    assert (
        c.post(
            f"/submissions/{sid}/labels",
            headers=h[1],
            json={
                "media_hash": media_hash,
                "action": {"category_id": 1, "start_ms": 0, "end_ms": 1000},
                "keypoints": [[[0.1, 0.1, 2] for _ in range(17)]],
            },
        ).status_code
        == 400
    )
    # Same for bounty creation.
    assert (
        c.post(
            "/bounties",
            headers={**h[0], "Idempotency-Key": os.urandom(8).hex()},
            json={
                "kind": "action",
                "title": "x",
                "category_ids": [1],
                "reward_usdc_units": 1,
                "slots": 1,
                "deadline": int(__import__("time").time()) + 3600,
                "keypoints": [],
            },
        ).status_code
        == 400
    )


# ---- video ingestion bounds ----


def test_mp4_ingestion_bounds():
    ok, h, dhash, dur = canonicalize_video(mp4(2000))
    assert dur == 2000 and h == __import__("hashlib").sha256(ok).hexdigest()
    with pytest.raises(MediaRejected):
        canonicalize_video(mp4(31_000))  # > 30s
    with pytest.raises(MediaRejected):
        canonicalize_video(mp4(2000), max_bytes=100)  # size bound
    with pytest.raises(MediaRejected):
        canonicalize_video(mp4(2000, video=False))  # audio-only
    with pytest.raises(MediaRejected):
        canonicalize_video(mp4(2000, extra_video=True))  # multi-track
    with pytest.raises(MediaRejected):
        canonicalize_video(png())  # not an MP4


def test_mp4_without_mdat_rejected():
    # A header-only synthetic that declares a video track but carries no mdat
    # (media data) must be rejected rather than trusted on its headers alone.
    children = [_mvhd(2000), _trak(b"vide", 2000), _trak(b"soun", 2000)]
    moov = _box(b"moov", b"".join(children))
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isom")
    no_mdat = ftyp + moov + b"\x00" * 16
    with pytest.raises(MediaRejected):
        canonicalize_video(no_mdat)


def test_video_duration_authoritative_from_track():
    # mvhd lies (2000ms) while the video track's mdhd/stts runs 60000ms: the
    # authoritative duration must exceed 30s and be rejected, not silently
    # accepted at the spoofed 2000ms.
    with pytest.raises(MediaRejected):
        canonicalize_video(mp4(2000, track_duration_ms=60_000))
    # Track duration within bounds is authoritative (maximum of mvhd and track).
    ok, h, dhash, dur = canonicalize_video(mp4(2000, track_duration_ms=25_000))
    assert dur == 25_000 and h == __import__("hashlib").sha256(ok).hexdigest()


def test_canonicalize_video_strips_udta_metadata():
    marker = b"+27.5916+085.5640"  # GPS location in an Apple ©xyz atom
    raw = mp4(marker=marker)
    assert marker in raw and b"\xa9xyz" in raw  # ©xyz GPS/device atom
    canonical, h, dhash, dur = canonicalize_video(raw)
    assert marker not in canonical
    assert b"\xa9xyz" not in canonical
    assert h == __import__("hashlib").sha256(canonical).hexdigest()


def test_video_moderation_fail_closed(pilot, monkeypatch):
    import httpx

    settings = pilot[-1]
    m = Moderation(settings)
    # Unconfigured -> blocked.
    with pytest.raises(MediaRejected):
        __import__("asyncio").run(m.scan_video(mp4()))

    settings.sightengine_user = "user"
    settings.sightengine_secret = "secret"

    async def image_only(*args, **kwargs):
        # A provider that returns an image verdict (cannot scan video) -> block.
        return httpx.Response(
            200,
            json={"status": "success", "faces": []},
            request=httpx.Request("POST", "https://example.test"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", image_only)
    with pytest.raises(MediaRejected):
        __import__("asyncio").run(m.scan_video(mp4()))

    async def error(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", error)
    with pytest.raises(MediaRejected):
        __import__("asyncio").run(m.scan_video(mp4()))


def test_video_pass_helpers_fail_closed():
    # sightengine: no frames analyzed -> never pass.
    assert not sightengine_video_pass({"status": "success", "faces": []})
    # A documented sync video response nests frames under data.frames, each
    # frame carrying its own faces list AND nudity object. A clean response
    # (frames analyzed, no faces, no sexual-content signal) passes.
    assert sightengine_video_pass(
        {
            "status": "success",
            "type": {"ai_generated": 0.001},
            "data": {
                "frames": [
                    {"faces": [], "nudity": {"sexual_activity": 0.001, "sexual_display": 0.001, "erotica": 0.001, "sextoy": 0.001, "suggestive": 0.001}},
                    {"faces": [], "nudity": {"sexual_activity": 0.001, "sexual_display": 0.001, "erotica": 0.001, "sextoy": 0.001, "suggestive": 0.001}},
                ]
            },
        }
    )
    # A frame missing its nudity object fails closed (provider did not analyze it).
    assert not sightengine_video_pass(
        {"status": "success", "data": {"frames": [{"faces": []}]}}
    )
    # A face detected in any single frame must block, even if others are clean.
    assert not sightengine_video_pass(
        {"status": "success", "data": {"frames": [{"faces": []}, {"faces": [{"x1": 0.1}]}]}}
    )
    # A frame that lacks a faces list is not a clean verdict -> fail closed.
    assert not sightengine_video_pass(
        {"status": "success", "data": {"frames": [{}]}}
    )
    # A frame with a sexual-content signal fails closed (nudity-2.0 model).
    assert not sightengine_video_pass(
        {
            "status": "success",
            "data": {
                "frames": [
                    {"faces": [], "nudity": {"sexual_activity": 0.9, "sexual_display": 0.1, "erotica": 0.1, "sextoy": 0.1, "suggestive": 0.1}}
                ]
            },
        }
    )
    # A clean frame (no faces, no nudity, not AI-generated) passes.
    assert sightengine_video_pass(
        {
            "status": "success",
            "type": {"ai_generated": 0.001},
            "data": {
                "frames": [
                    {"faces": [], "nudity": {"sexual_activity": 0.001, "sexual_display": 0.001, "erotica": 0.001, "sextoy": 0.001, "suggestive": 0.001}}
                ]
            },
        }
    )
    # An AI-generated clip (genai at/above threshold) fails even with clean frames.
    assert not sightengine_video_pass(
        {
            "status": "success",
            "type": {"ai_generated": 0.95},
            "data": {
                "frames": [
                    {"faces": [], "nudity": {"sexual_activity": 0.001, "sexual_display": 0.001, "erotica": 0.001, "sextoy": 0.001, "suggestive": 0.001}}
                ]
            },
        }
    )


def test_sightengine_nudity_pass():
    clean = {
        "sexual_activity": 0.001, "sexual_display": 0.001,
        "erotica": 0.001, "sextoy": 0.001, "suggestive": 0.001,
    }
    assert sightengine_nudity_pass({"nudity": clean})
    assert not sightengine_nudity_pass(
        {"nudity": {**clean, "sexual_display": 0.9}}
    )
    assert not sightengine_nudity_pass(
        {"nudity": {**clean, "suggestive": 0.8}}
    )
    # missing/malformed nudity object -> fail closed
    assert not sightengine_nudity_pass({})
    assert not sightengine_nudity_pass({"nudity": None})


def test_sightengine_genai_pass():
    assert sightengine_genai_pass({"type": {"ai_generated": 0.001}})
    assert sightengine_genai_pass({"type": {"ai_generated": 0.49}})
    # at/above threshold -> synthetic -> reject
    assert not sightengine_genai_pass({"type": {"ai_generated": 0.5}})
    assert not sightengine_genai_pass({"type": {"ai_generated": 0.999}})
    # missing/malformed/non-finite/out-of-range type object -> fail closed
    assert not sightengine_genai_pass({})
    assert not sightengine_genai_pass({"type": None})
    assert not sightengine_genai_pass({"type": {"ai_generated": None}})
    assert not sightengine_genai_pass({"type": {"ai_generated": "nope"}})
    assert not sightengine_genai_pass({"type": {"ai_generated": 1.7}})
    assert not sightengine_genai_pass({"type": {"ai_generated": float("nan")}})


# ---- offline keypoint job ----


def _action_submission(tmp_path):
    from seeker.db import Bounty

    db = Database("sqlite:///" + str(tmp_path / "kp.db"))
    Base.metadata.create_all(db.engine)
    cipher = MediaCipher(base64.b64encode(b"k" * 32).decode())
    data = b"video-bytes" * 8
    media_hash = __import__("hashlib").sha256(data).hexdigest()
    with db.transaction() as s:
        from seeker.db import Actor

        s.add(Actor(wallet="w" * 44, worker=True, reviewer=False))
        s.add(Actor(wallet="r" * 44, worker=False, reviewer=False))
        b = Bounty(
            id="01" * 16, requester="r" * 44, request_key="k", body_hash="b" * 64,
            title="action", kind="action", taxonomy=[], reward=1, slots=1, deadline=0,
        )
        s.add(b)
        s.add(
            Submission(
                id="02" * 16, bounty_id="01" * 16, worker="w" * 44, expires=0,
                media_hash=media_hash, encrypted_media=cipher.encrypt(data, media_hash),
            )
        )
    return db, cipher, "02" * 16


class FakeExtractor:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def extract(self, video_bytes):
        self.calls += 1
        if self.fail:
            raise __import__("seeker.keypoints", fromlist=["KeypointError"]).KeypointError("boom")
        return [[[0.5, 0.5, 2] for _ in range(17)] for _ in range(4)]


def test_keypoint_job_idempotent_resumable(tmp_path):
    from seeker.keypoints import generate_submission_keypoints, run_pending

    db, cipher, sid = _action_submission(tmp_path)
    ex = FakeExtractor()
    assert generate_submission_keypoints(db, cipher, sid, ex) is True
    with db.transaction() as s:
        assert len(s.get(Submission, sid).keypoints) == 4
    # Idempotent: already present -> skipped, extractor not re-run.
    assert generate_submission_keypoints(db, cipher, sid, ex) is False
    assert ex.calls == 1
    # Failure leaves keypoints absent, not corrupt.
    ex.fail = True
    with pytest.raises(__import__("seeker.keypoints", fromlist=["KeypointError"]).KeypointError):
        generate_submission_keypoints(db, cipher, sid, ex, force=True)
    with db.transaction() as s:
        assert s.get(Submission, sid).keypoints is not None  # previous value intact


def test_keypoint_job_run_pending_isolates_failures(tmp_path):
    from seeker.keypoints import run_pending

    db, cipher, sid = _action_submission(tmp_path)
    assert run_pending(db, cipher, FakeExtractor()) == 1
    with db.transaction() as s:
        assert s.get(Submission, sid).keypoints is not None
    # Second run finds nothing pending.
    assert run_pending(db, cipher, FakeExtractor()) == 0


def test_keypoint_job_skips_non_action(tmp_path):
    from seeker.db import Bounty
    from seeker.keypoints import generate_submission_keypoints

    db, cipher, _sid = _action_submission(tmp_path)
    with db.transaction() as s:
        b = s.get(Bounty, "01" * 16)
        b.kind = "object"
    assert generate_submission_keypoints(db, cipher, "02" * 16, FakeExtractor()) is False


def test_action_flow_keypoints_are_server_side_only(pilot):
    from seeker.keypoints import generate_submission_keypoints

    c, app, h, *_ = pilot
    bid = bounty(pilot, kind="action")
    sid = fund_and_claim(pilot, bid)
    r = c.post(f"/submissions/{sid}/media", headers=h[1], content=mp4())
    media_hash = r.json()["media_hash"]
    r = c.post(
        f"/submissions/{sid}/labels",
        headers=h[1],
        json={"media_hash": media_hash, "action": {"category_id": 1, "start_ms": 0, "end_ms": 1000}},
    )
    assert r.status_code == 200
    assert r.json()["keypoints"] is None
    cipher = MediaCipher(base64.b64encode(b"k" * 32).decode())
    assert generate_submission_keypoints(app.state.database, cipher, sid, FakeExtractor()) is True
    got = c.get("/submissions", headers=h[0]).json()
    sub = next(s for s in got if s["id"] == sid)
    assert len(sub["keypoints"]) == 4


# ---- migration 0002: phase-2 columns ----


def test_migration_0002_adds_phase2_columns(tmp_path):
    from sqlalchemy import inspect

    from seeker.db import connect
    from seeker.migrate import apply_migrations

    engine = connect("sqlite:///" + str(tmp_path / "old-phase1.db"))
    # Phase-1 schema: no kind, duration_ms, or keypoints columns.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE seeker_bounties (id VARCHAR(32) PRIMARY KEY, "
            "requester VARCHAR(44), request_key VARCHAR(64), body_hash VARCHAR(64), "
            "title VARCHAR(160), taxonomy JSON, reward BIGINT, slots INTEGER, "
            "deadline BIGINT, status VARCHAR(24))"
        )
        conn.exec_driver_sql(
            "CREATE TABLE seeker_submissions (id VARCHAR(32) PRIMARY KEY, "
            "bounty_id VARCHAR(32), worker VARCHAR(44), expires BIGINT, "
            "status VARCHAR(24), media_hash VARCHAR(64), perceptual VARCHAR(16), "
            "encrypted_media BLOB, moderation JSON, labels JSON, label_hash VARCHAR(64))"
        )
        conn.exec_driver_sql(
            "CREATE TABLE seeker_reviews (id VARCHAR(32) PRIMARY KEY, "
            "submission_id VARCHAR(32), reviewer VARCHAR(44), labels JSON)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE seeker_actors (wallet VARCHAR(44) PRIMARY KEY, "
            "worker BOOLEAN, reviewer BOOLEAN, over_18 BOOLEAN)"
        )
    bounty_cols = {c["name"] for c in inspect(engine).get_columns("seeker_bounties")}
    sub_cols = {c["name"] for c in inspect(engine).get_columns("seeker_submissions")}
    rev_cols = {c["name"] for c in inspect(engine).get_columns("seeker_reviews")}
    actor_cols = {c["name"] for c in inspect(engine).get_columns("seeker_actors")}
    assert "kind" not in bounty_cols
    assert "duration_ms" not in sub_cols and "keypoints" not in sub_cols
    assert "secondary" not in sub_cols and "secondary" not in rev_cols
    assert "accepted_count" not in actor_cols
    assert "liveness_completed" not in actor_cols
    assert "bonded" not in actor_cols and "quality_checks" not in actor_cols
    assert "skr_funded" not in actor_cols
    assert "capture_metadata" not in sub_cols and "accepted" not in sub_cols

    # 0002 adds 3 columns; 0003 adds 2; 0004 adds 8 (actors.accepted_count +
    # 7 submission columns); 0005 adds 1 (actors.liveness_completed); 0006 adds
    # 3 (actors.bonded, quality_checks, skr_funded); 0007 adds 1
    # (reviews.accepted); 0008 adds 1 (submissions.payout_signature).
    assert apply_migrations(engine) == 19
    assert apply_migrations(engine) == 0  # re-run is a no-op

    bounty_cols = {c["name"] for c in inspect(engine).get_columns("seeker_bounties")}
    sub_cols = {c["name"] for c in inspect(engine).get_columns("seeker_submissions")}
    rev_cols = {c["name"] for c in inspect(engine).get_columns("seeker_reviews")}
    actor_cols = {c["name"] for c in inspect(engine).get_columns("seeker_actors")}
    assert "kind" in bounty_cols
    assert "duration_ms" in sub_cols and "keypoints" in sub_cols
    assert "secondary" in sub_cols and "secondary" in rev_cols
    assert "accepted_count" in actor_cols
    assert "liveness_completed" in actor_cols
    assert "bonded" in actor_cols and "quality_checks" in actor_cols
    assert "skr_funded" in actor_cols
    assert "capture_metadata" in sub_cols and "accepted" in sub_cols
    assert "judged_at" in sub_cols and "payout_usdc" in sub_cols
    assert "verdict_reason" in sub_cols and "level_after" in sub_cols
    assert "payout_signature" in sub_cols
    assert "kind" in sub_cols  # v2 open-upload kind column
    engine.dispose()

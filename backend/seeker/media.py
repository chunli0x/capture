"""No remote URL uploads. Canonical bytes are scanned, encrypted, and later served unchanged."""

import asyncio
import base64
import hashlib
import io
import math
import os
import warnings

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_VIDEO_SECONDS = 30
MAX_VIDEO_BYTES = 100 * 1024 * 1024


class MediaRejected(ValueError):
    pass


def canonicalize(raw: bytes):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in {"JPEG", "PNG"} or getattr(im, "n_frames", 1) != 1:
                    raise MediaRejected("Only single-frame JPEG/PNG is supported")
                if im.width * im.height > 12_000_000 or min(im.size) < 32:
                    raise MediaRejected("Image dimensions outside pilot limits")
                im.load()
                im = ImageOps.exif_transpose(im).convert("RGB")
                out = io.BytesIO()
                im.save(out, format="PNG")  # re-encode without GPS, EXIF, comments
                canonical = out.getvalue()
                pixels = list(im.convert("L").resize((9, 8)).get_flattened_data())
                bits = [
                    pixels[y * 9 + x] > pixels[y * 9 + x + 1]
                    for y in range(8)
                    for x in range(8)
                ]
                dhash = f"{sum(int(b) << i for i, b in enumerate(bits)):016x}"
                return canonical, hashlib.sha256(canonical).hexdigest(), dhash
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise MediaRejected("Invalid or oversized image") from exc


def _boxes(buf, start, end):
    """Yield (type, payload_start, payload_end) for every top-level ISO BMFF box."""
    i = start
    while i + 8 <= end:
        size = int.from_bytes(buf[i : i + 4], "big")
        btype = buf[i + 4 : i + 8].decode("latin1")
        header = 8
        if size == 1:  # 64-bit extended size
            if i + 16 > end:
                raise MediaRejected("Truncated MP4 box")
            size = int.from_bytes(buf[i + 8 : i + 16], "big")
            header = 16
        elif size == 0:  # box runs to end of container
            size = end - i
        if size < header or i + size > end:
            raise MediaRejected("Malformed MP4 box structure")
        yield btype, i + header, i + size
        i += size


def _mvhd_duration_ms(buf, start, end):
    payload = buf[start:end]
    if len(payload) < 20:
        raise MediaRejected("Malformed movie header")
    version = payload[0]
    if version == 1:
        if len(payload) < 32:
            raise MediaRejected("Malformed 64-bit movie header")
        timescale = int.from_bytes(payload[20:24], "big")
        duration = int.from_bytes(payload[24:32], "big")
    else:
        timescale = int.from_bytes(payload[12:16], "big")
        duration = int.from_bytes(payload[16:20], "big")
    if timescale <= 0:
        raise MediaRejected("Invalid movie timescale")
    return (duration * 1000) // timescale


def _trak_handler(buf, start, end):
    for btype, s2, e2 in _boxes(buf, start, end):
        if btype == "mdia":
            for btype3, s3, e3 in _boxes(buf, s2, e2):
                if btype3 == "hdlr":
                    payload = buf[s3:e3]
                    if len(payload) >= 12:
                        return payload[8:12].decode("latin1")
    return None


def video_dhash(raw):
    """Byte-level perceptual hash: near-duplicate gate for video without a decoder."""
    n = 64
    if len(raw) <= n:
        return hashlib.sha256(raw).hexdigest()[:16]
    step = len(raw) // (n + 1)
    samples = [raw[i * step] for i in range(n + 1)]
    bits = [samples[i] > samples[i + 1] for i in range(n)]
    return f"{sum(int(b) << i for i, b in enumerate(bits)):016x}"


def canonicalize_video(raw, max_bytes=MAX_VIDEO_BYTES, max_seconds=MAX_VIDEO_SECONDS):
    """Validate and bound an MP4 action clip: exactly one video track, bounded
    duration/size. Returns (canonical, sha256, perceptual, duration_ms).

    Unlike the image path there is no metadata-stripping re-encode here (that
    needs a transcoder); the clip is stored as validated input bytes and still
    passes the same encrypt + moderation gate. Audio-only and multi-track files
    are rejected.
    """
    if len(raw) > max_bytes:
        raise MediaRejected("Video exceeds size limit")
    if len(raw) < 8:
        raise MediaRejected("Invalid or empty video")
    buf = raw
    end = len(buf)
    has_ftyp = False
    moov = None
    for btype, start, stop in _boxes(buf, 0, end):
        if btype == "ftyp":
            has_ftyp = True
        elif btype == "moov" and moov is None:
            moov = (start, stop)
    if not has_ftyp or moov is None:
        raise MediaRejected("Not an MP4 file")
    duration_ms = None
    video_tracks = 0
    audio_tracks = 0
    ms, me = moov
    for btype, start, stop in _boxes(buf, ms, me):
        if btype == "mvhd":
            duration_ms = _mvhd_duration_ms(buf, start, stop)
        elif btype == "trak":
            handler = _trak_handler(buf, start, stop)
            if handler == "vide":
                video_tracks += 1
            elif handler == "soun":
                audio_tracks += 1
    if video_tracks == 0:
        raise MediaRejected("Audio-only media is not an acceptable video")
    if video_tracks > 1:
        raise MediaRejected("Multi-track video is not supported")
    if duration_ms is None or duration_ms <= 0:
        raise MediaRejected("Video duration could not be determined")
    if duration_ms > max_seconds * 1000:
        raise MediaRejected("Video exceeds duration limit")
    canonical = bytes(raw)
    return (
        canonical,
        hashlib.sha256(canonical).hexdigest(),
        video_dhash(canonical),
        duration_ms,
    )


def score(v):
    if type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1:
        raise MediaRejected("Incomplete moderation result")
    return v


def sightengine_pass(data):
    if data["status"] != "success" or not isinstance(data["faces"], list):
        return False
    # Conservative object-only pilot: do not admit any detected real faces.
    # Age detection alone cannot prove absence of minors with obscured faces.
    return len(data["faces"]) == 0


def hive_pass(data):
    entries = data["status"]
    if (
        not isinstance(entries, list)
        or len(entries) != 1
        or entries[0]["status"]["code"] != 200
    ):
        return False
    out = entries[0]["response"]["output"]
    file = out["file"]
    if file["fileType"] != "image" or file["reasons"] != [] or out["hashes"] != []:
        return False
    values = file["classifierPrediction"]["csam_classifier"]
    csam, porn, other = (score(values[k]) for k in ("csam", "pornography", "other"))
    return (
        abs(csam + porn + other - 1) < 0.02
        and csam < 0.01
        and porn < 0.05
        and other > 0.94
    )


def sightengine_video_pass(data):
    """Fail-closed: a provider that did not analyze video frames never passes."""
    if data.get("status") != "success":
        return False
    frames = data.get("frames")
    if not isinstance(frames, list) or len(frames) == 0:
        return False
    return len(data.get("faces", [])) == 0


def hive_video_pass(data):
    """Fail-closed: only a clean video verdict (frames analyzed) may pass."""
    entries = data.get("status")
    if (
        not isinstance(entries, list)
        or len(entries) != 1
        or entries[0]["status"]["code"] != 200
    ):
        return False
    out = entries[0]["response"]["output"]
    file = out["file"]
    if file.get("fileType") != "video" or file.get("reasons") != []:
        return False
    frames = file.get("frames")
    if not isinstance(frames, list) or len(frames) == 0:
        return False
    values = file["classifierPrediction"]["csam_classifier"]
    csam, porn, other = (score(values[k]) for k in ("csam", "pornography", "other"))
    return (
        abs(csam + porn + other - 1) < 0.02
        and csam < 0.01
        and porn < 0.05
        and other > 0.94
    )


class Moderation:
    def __init__(self, settings):
        self.settings = settings

    async def scan(self, data: bytes):
        s = self.settings
        if not (s.sightengine_user and s.sightengine_secret and s.hive_key):
            raise MediaRejected("Moderation service is not configured")
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                sight, hive = await asyncio.gather(
                    client.post(
                        "https://api.sightengine.com/1.0/check.json",
                        files={"media": ("image.png", data, "image/png")},
                        data={
                            "models": "face-age",
                            "api_user": s.sightengine_user,
                            "api_secret": s.sightengine_secret,
                        },
                    ),
                    client.post(
                        "https://api.thehive.ai/api/v2/task/sync",
                        files={"media": ("image.png", data, "image/png")},
                        headers={"Authorization": "Token " + s.hive_key},
                    ),
                )
                sight.raise_for_status()
                hive.raise_for_status()
                if not sightengine_pass(sight.json()) or not hive_pass(hive.json()):
                    raise MediaRejected("Image did not pass moderation")
                # No raw provider payloads or media URLs in logs or public APIs.
                return {
                    "policy": "object-pilot-v1",
                    "sightengine": "pass",
                    "hive": "pass",
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise MediaRejected("Moderation unavailable or image not approved") from exc

    async def scan_video(self, data: bytes):
        """Video moderation. Fails closed: if a provider cannot scan the video
        (unconfigured, error, or a non-video verdict), the submission is blocked —
        never default-PASS."""
        s = self.settings
        if not (s.sightengine_user and s.sightengine_secret and s.hive_key):
            raise MediaRejected("Video moderation service is not configured")
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                sight, hive = await asyncio.gather(
                    client.post(
                        "https://api.sightengine.com/1.0/check.json",
                        files={"media": ("video.mp4", data, "video/mp4")},
                        data={
                            "models": "face-age",
                            "api_user": s.sightengine_user,
                            "api_secret": s.sightengine_secret,
                        },
                    ),
                    client.post(
                        "https://api.thehive.ai/api/v2/task/sync",
                        files={"media": ("video.mp4", data, "video/mp4")},
                        headers={"Authorization": "Token " + s.hive_key},
                    ),
                )
                sight.raise_for_status()
                hive.raise_for_status()
                if not sightengine_video_pass(sight.json()) or not hive_video_pass(
                    hive.json()
                ):
                    raise MediaRejected("Video did not pass moderation")
                return {
                    "policy": "object-pilot-v1",
                    "sightengine": "pass",
                    "hive": "pass",
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise MediaRejected(
                "Video moderation unavailable or not approved"
            ) from exc


class MediaCipher:
    def __init__(self, key):
        self.cipher = AESGCM(base64.b64decode(key, validate=True))

    def encrypt(self, data, digest):
        nonce = os.urandom(12)
        return nonce + self.cipher.encrypt(nonce, data, digest.encode())

    def decrypt(self, data, digest):
        return self.cipher.decrypt(data[:12], data[12:], digest.encode())

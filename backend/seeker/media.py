"""No remote URL uploads. Canonical bytes are scanned, encrypted, and later served unchanged."""

import asyncio
import base64
import hashlib
import io
import math
import os
import subprocess
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


def _mdhd_info(buf, start, end):
    """Return (timescale, duration_units) from a media header (mdhd) box."""
    payload = buf[start:end]
    if len(payload) < 20:
        raise MediaRejected("Malformed media header")
    version = payload[0]
    if version == 1:
        if len(payload) < 32:
            raise MediaRejected("Malformed 64-bit media header")
        timescale = int.from_bytes(payload[20:24], "big")
        duration = int.from_bytes(payload[24:32], "big")
    else:
        timescale = int.from_bytes(payload[12:16], "big")
        duration = int.from_bytes(payload[16:20], "big")
    if timescale <= 0:
        raise MediaRejected("Invalid media timescale")
    return timescale, duration


def _stts_total(buf, start, end):
    """Return (sample_count, total_duration_units) from a time-to-sample box."""
    payload = buf[start:end]
    if len(payload) < 8:
        raise MediaRejected("Malformed time-to-sample box")
    entry_count = int.from_bytes(payload[4:8], "big")
    samples = 0
    total = 0
    off = 8
    for _ in range(entry_count):
        if off + 8 > len(payload):
            raise MediaRejected("Truncated time-to-sample entry")
        count = int.from_bytes(payload[off : off + 4], "big")
        delta = int.from_bytes(payload[off + 4 : off + 8], "big")
        samples += count
        total += count * delta
        off += 8
    return samples, total


def _trak_video_info(buf, start, end):
    """Inspect one trak box. Returns (handler, track_duration_ms, sample_count).

    track_duration_ms is the maximum of the mdhd-declared duration and the sum
    of stts sample deltas, converted to milliseconds with the mdhd timescale.
    """
    handler = None
    timescale = None
    mdhd_duration = 0
    sample_count = 0
    stts_total = 0
    for btype, s, e in _boxes(buf, start, end):
        if btype == "mdia":
            for btype2, s2, e2 in _boxes(buf, s, e):
                if btype2 == "hdlr":
                    payload = buf[s2:e2]
                    if len(payload) >= 12:
                        handler = payload[8:12].decode("latin1")
                elif btype2 == "mdhd":
                    timescale, mdhd_duration = _mdhd_info(buf, s2, e2)
                elif btype2 == "minf":
                    for btype3, s3, e3 in _boxes(buf, s2, e2):
                        if btype3 == "stbl":
                            for btype4, s4, e4 in _boxes(buf, s3, e3):
                                if btype4 == "stts":
                                    sc, tot = _stts_total(buf, s4, e4)
                                    sample_count += sc
                                    stts_total += tot
    if timescale is None:
        track_duration_ms = 0
    else:
        track_duration_ms = (max(mdhd_duration, stts_total) * 1000) // timescale
    return handler, track_duration_ms, sample_count


def _strip_metadata_atoms(buf, start, end):
    """Zero the payload of every udta/meta box under container [start, end).

    Recurses into known container boxes so a metadata atom is destroyed no
    matter where it sits (top-level, under moov, under trak, or nested inside
    another container). The media-data box (mdat) is never descended into.

    Zeroing (rather than removing) keeps every byte offset identical, so
    chunk-offset tables (stco) stay valid and the clip remains playable while
    GPS / device / copyright metadata (udta → ©xyz, ©nam, ©day, ©mak, …) is
    destroyed.
    """
    for btype, s, e in _boxes(buf, start, end):
        if btype in ("udta", "meta"):
            buf[s:e] = b"\x00" * (e - s)
        elif btype in _CONTAINER_BOXES:
            _strip_metadata_atoms(buf, s, e)


_CONTAINER_BOXES = {
    "moov",
    "trak",
    "mdia",
    "minf",
    "stbl",
    "edts",
    "dinf",
    "iprp",
    "ipco",
    "schm",
    "sinf",
    "meco",
    "mfra",
    "moof",
    "traf",
}


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
    """Validate and bound an MP4 action clip: exactly one decodable video track,
    bounded duration/size, metadata stripped. Returns
    (canonical, sha256, perceptual, duration_ms).

    The authoritative duration is the maximum of the movie-level mvhd duration
    and the video track's own mdhd/stts duration, so a track cannot spoof a
    short clip by lying in mvhd while its samples run longer. At least one
    decodable video sample must be declared in stts, so a moov-only or
    audio-only file cannot pass on handler type alone. Metadata (udta/meta
    atoms: GPS ©xyz, device, copyright) is stripped by zeroing those atoms in
    place before the bytes are stored; no transcoder re-encode is performed.
    """
    if len(raw) > max_bytes:
        raise MediaRejected("Video exceeds size limit")
    if len(raw) < 8:
        raise MediaRejected("Invalid or empty video")
    buf = bytearray(raw)
    end = len(buf)
    has_ftyp = False
    has_mdat = False
    moov = None
    for btype, start, stop in _boxes(buf, 0, end):
        if btype == "ftyp":
            has_ftyp = True
        elif btype == "moov" and moov is None:
            moov = (start, stop)
        elif btype == "mdat":
            # A real clip carries its sample payload in an mdat box. Requiring
            # one (with non-empty payload) rejects header-only synthetics that
            # declare a video track in moov but contain no media data — the
            # class of file that used to pass on headers alone.
            if stop - start > 0:
                has_mdat = True
    if not has_ftyp or moov is None or not has_mdat:
        raise MediaRejected("Not an MP4 file")
    mvhd_duration_ms = None
    video_tracks = 0
    audio_tracks = 0
    track_duration_ms = 0
    video_sample_count = 0
    ms, me = moov
    for btype, start, stop in _boxes(buf, ms, me):
        if btype == "mvhd":
            mvhd_duration_ms = _mvhd_duration_ms(buf, start, stop)
        elif btype == "trak":
            handler, t_ms, samples = _trak_video_info(buf, start, stop)
            if handler == "vide":
                video_tracks += 1
                track_duration_ms = t_ms
                video_sample_count = samples
            elif handler == "soun":
                audio_tracks += 1
    if video_tracks == 0:
        raise MediaRejected("Audio-only media is not an acceptable video")
    if video_tracks > 1:
        raise MediaRejected("Multi-track video is not supported")
    if video_sample_count < 1:
        raise MediaRejected("Video declares no decodable samples")
    if mvhd_duration_ms is None:
        raise MediaRejected("Video duration could not be determined")
    duration_ms = max(mvhd_duration_ms, track_duration_ms)
    if duration_ms <= 0:
        raise MediaRejected("Video duration could not be determined")
    if duration_ms > max_seconds * 1000:
        raise MediaRejected("Video exceeds duration limit")
    # Strip GPS/device/copyright metadata before the approved bytes are stored.
    # Recursion covers moov/trak/mdia/... and top-level atoms; mdat is skipped.
    _strip_metadata_atoms(buf, 0, end)
    canonical = bytes(buf)
    return (
        canonical,
        hashlib.sha256(canonical).hexdigest(),
        video_dhash(canonical),
        duration_ms,
    )


def sightengine_pass(data):
    if data["status"] != "success" or not isinstance(data["faces"], list):
        return False
    # Conservative object-only pilot: do not admit any detected real faces.
    # Age detection alone cannot prove absence of minors with obscured faces.
    return len(data["faces"]) == 0


def sightengine_nudity_pass(data):
    """Reject any sexual-content signal from Sightengine's nudity-2.0 model.

    Replaces the retired Hive CSAM classifier. Sightengine does not perform
    known-CSAM hash matching (PhotoDNA/MD5) the way Hive did — this is a
    classifier over nudity/sexual-content probabilities, not a known-abuse
    database lookup. For the devnet pilot (ground-level egocentric capture)
    that is an accepted, documented tradeoff. Fails closed on a missing or
    malformed nudity object.
    """
    nudity = data.get("nudity")
    if not isinstance(nudity, dict):
        return False
    # Explicit sexual-content categories. A clean frame scores ~0.001 on each.
    explicit = max(
        float(nudity.get("sexual_activity", 1)),
        float(nudity.get("sexual_display", 1)),
        float(nudity.get("erotica", 1)),
        float(nudity.get("sextoy", 1)),
    )
    suggestive = float(nudity.get("suggestive", 0))
    if explicit >= 0.5 or suggestive >= 0.7:
        return False
    return True


def sightengine_video_pass(data):
    """Fail-closed for the Sightengine video contract (face-age + nudity-2.0).

    The sync video endpoint nests per-frame results under ``data.frames``;
    each frame carries its own ``faces`` list (real faces, each with an
    ``attributes.age.minor`` probability) and a ``nudity`` object. A provider
    that did not analyze frames (missing/empty ``data.frames``), any frame
    lacking a well-formed ``faces`` list, any real face detected in any frame,
    or any frame with a sexual-content signal, all fail closed — mirroring the
    image path.
    """
    if data.get("status") != "success":
        return False
    frames = (data.get("data") or {}).get("frames")
    if not isinstance(frames, list) or len(frames) == 0:
        return False
    for frame in frames:
        if not isinstance(frame, dict):
            return False
        faces = frame.get("faces")
        if not isinstance(faces, list) or len(faces) != 0:
            return False
        # Enforce the nudity model per frame too, mirroring the image path.
        nudity = frame.get("nudity")
        if nudity is not None and not sightengine_nudity_pass({"nudity": nudity}):
            return False
    return True


class Moderation:
    def __init__(self, settings):
        self.settings = settings

    async def scan(self, data: bytes):
        s = self.settings
        if not (s.sightengine_user and s.sightengine_secret):
            raise MediaRejected("Moderation service is not configured")
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                sight = await client.post(
                    "https://api.sightengine.com/1.0/check.json",
                    files={"media": ("image.png", data, "image/png")},
                    data={
                        "models": "nudity-2.0,face-age",
                        "api_user": s.sightengine_user,
                        "api_secret": s.sightengine_secret,
                    },
                )
                sight.raise_for_status()
                payload = sight.json()
                if not sightengine_pass(payload) or not sightengine_nudity_pass(payload):
                    raise MediaRejected("Image did not pass moderation")
                # No raw provider payloads or media URLs in logs or public APIs.
                return {
                    "policy": "object-pilot-v1",
                    "sightengine": "pass",
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise MediaRejected("Moderation unavailable or image not approved") from exc

    async def scan_video(self, data: bytes):
        """Video moderation. Fails closed: if a provider cannot scan the video
        (unconfigured, error, or a non-video verdict), the submission is blocked —
        never default-PASS."""
        s = self.settings
        if not (s.sightengine_user and s.sightengine_secret):
            raise MediaRejected("Video moderation service is not configured")
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                sight = await client.post(
                    "https://api.sightengine.com/1.0/video/check-sync.json",
                    files={"media": ("video.mp4", data, "video/mp4")},
                    data={
                        "models": "nudity-2.0,face-age",
                        "api_user": s.sightengine_user,
                        "api_secret": s.sightengine_secret,
                    },
                )
                sight.raise_for_status()
                payload = sight.json()
                if not sightengine_video_pass(payload):
                    raise MediaRejected("Video did not pass moderation")
                return {
                    "policy": "object-pilot-v1",
                    "sightengine": "pass",
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


def extract_video_frame(mp4: bytes, seek_ratio: float = 0.4) -> bytes:
    """Extract one representative JPEG frame from an MP4 for the VLM judge.

    Uses ffmpeg to decode a single frame near ``seek_ratio`` of the clip and
    re-encode it as a small JPEG (bounded dimensions) so the judge can see the
    actual ego-centric view. Raises :class:`MediaRejected` if ffmpeg is missing
    or cannot produce a frame — the caller treats that as "no judge image"
    rather than a pass.
    """
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise MediaRejected("ffmpeg unavailable for video frame extraction")
    # Seek to ~40% of the clip and grab one frame at bounded scale.
    try:
        proc = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error",
                "-ss", str(seek_ratio), "-i", "pipe:0",
                "-frames:v", "1", "-vf", "scale='min(720,iw)':-2",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-",
            ],
            input=mp4,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise MediaRejected("video frame extraction timed out")
    if proc.returncode != 0 or not proc.stdout:
        raise MediaRejected("could not extract a video frame")
    return proc.stdout

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


class MediaCipher:
    def __init__(self, key):
        self.cipher = AESGCM(base64.b64decode(key, validate=True))

    def encrypt(self, data, digest):
        nonce = os.urandom(12)
        return nonce + self.cipher.encrypt(nonce, data, digest.encode())

    def decrypt(self, data, digest):
        return self.cipher.decrypt(data[:12], data[12:], digest.encode())

"""Offline COCO-17 keypoint generation for accepted `action` submissions.

This is the single permitted vision-model use in the pilot, and it is strictly
downstream/offline: it runs on a schedule/queue, never in the request path, and
writes only the server-side `keypoints` field on a Submission. No seeker request
schema accepts `keypoints`, so seekers can neither submit nor draw them.

Idempotent and resumable: reprocessing a submission recomputes the same value
(or is skipped when already present), and a failure raises before any write, so
`keypoints` is left absent rather than corrupt.
"""

import math

from sqlalchemy import select

from .db import Bounty, Database, Submission

# Canonical COCO-17 pose keypoint names, in order.
COCO_17_KEYPOINTS = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

# MediaPipe 33-landmark indices that map onto the COCO-17 order above.
_MEDIAPIPE_TO_COCO = [
    0,  # nose
    2,  # left_eye
    5,  # right_eye
    7,  # left_ear
    8,  # right_ear
    11,  # left_shoulder
    12,  # right_shoulder
    13,  # left_elbow
    14,  # right_elbow
    15,  # left_wrist
    16,  # right_wrist
    23,  # left_hip
    24,  # right_hip
    25,  # left_knee
    26,  # right_knee
    27,  # left_ankle
    28,  # right_ankle
]


class KeypointError(RuntimeError):
    pass


def validate_keypoints(keypoints):
    """Assert the COCO-17 shape: a list of frames, each 17 [x, y, v] triples."""
    if not isinstance(keypoints, list):
        raise KeypointError("keypoints must be a list of frames")
    for frame in keypoints:
        if not isinstance(frame, (list, tuple)) or len(frame) != 17:
            raise KeypointError("each frame must hold exactly 17 COCO keypoints")
        for kp in frame:
            if not isinstance(kp, (list, tuple)) or len(kp) != 3:
                raise KeypointError("each keypoint must be [x, y, v]")
            x, y, v = kp
            if (
                not isinstance(x, (int, float))
                or not isinstance(y, (int, float))
                or not math.isfinite(x)
                or not math.isfinite(y)
            ):
                raise KeypointError("keypoint coordinates must be finite numbers")
            if v not in (0, 1, 2):
                raise KeypointError("keypoint visibility must be 0, 1, or 2")
    return keypoints


class KeypointExtractor:
    """COCO-17 pose extractor. Pluggable so the offline job is testable without
    MediaPipe; production supplies a MediaPipe-backed implementation."""

    def extract(self, video_bytes: bytes) -> list:
        raise NotImplementedError


class MediaPipeExtractor(KeypointExtractor):
    """MediaPipe-backed COCO-17 keypoints per sampled frame.

    Lazy-imports mediapipe + OpenCV; where those are absent the job raises
    KeypointError and leaves `keypoints` absent (the documented fail-closed
    behaviour), never a corrupt or guessed pose.
    """

    def __init__(self, samples: int = 8):
        self.samples = max(1, samples)

    def extract(self, video_bytes: bytes) -> list:
        try:
            import cv2
            import mediapipe as mp
            import numpy as np
        except ImportError as exc:
            raise KeypointError(
                "mediapipe/opencv are not installed; keypoints unavailable"
            ) from exc

        import tempfile
        import os

        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
                fh.write(video_bytes)
                path = fh.name
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                raise KeypointError("video could not be decoded")
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
            poses = []
            with mp.solutions.pose.Pose(
                static_image_mode=False, model_complexity=1
            ) as pose:
                frame_no = 0
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    frame_no += 1
                    if total and frame_no not in self._sampled(total):
                        continue
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    result = pose.process(rgb)
                    poses.append(self._coco17(result.pose_landmarks))
                    if len(poses) >= self.samples:
                        break
            cap.release()
            if not poses:
                raise KeypointError("no frames could be analyzed")
            return poses
        except KeypointError:
            raise
        except Exception as exc:
            raise KeypointError(f"keypoint extraction failed: {exc}") from exc
        finally:
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def _sampled(self, total):
        """Evenly spaced frame numbers capped at `samples`."""
        n = min(self.samples, max(1, total))
        return {int(round((total - 1) * i / max(1, n - 1))) + 1 for i in range(n)}

    def _coco17(self, landmarks):
        if landmarks is None:
            return [[-1.0, -1.0, 0] for _ in range(17)]
        pts = []
        for idx in _MEDIAPIPE_TO_COCO:
            lm = landmarks.landmark[idx]
            pts.append([float(lm.x), float(lm.y), 2 if lm.visibility >= 0.5 else 1])
        return pts


def generate_submission_keypoints(database, cipher, sid, extractor=None, force=False):
    """Compute and store keypoints for one accepted action submission.

    Returns True when keypoints were written, False when skipped (not an action
    submission, no approved media, or already computed). A failure raises before
    any write, leaving `keypoints` absent.
    """
    extractor = extractor or MediaPipeExtractor()
    with database.transaction() as db:
        s = db.get(Submission, sid)
        if s is None or s.encrypted_media is None or s.media_hash is None:
            return False
        b = db.get(Bounty, s.bounty_id) if s.bounty_id else None
        if b is None or b.kind != "action":
            return False
        if s.keypoints is not None and not force:
            return False
        raw = cipher.decrypt(s.encrypted_media, s.media_hash)
    keypoints = validate_keypoints(extractor.extract(raw))
    with database.transaction() as db:
        row = db.get(Submission, sid)
        row.keypoints = keypoints
    return True


def run_pending(database, cipher, extractor=None, limit=None):
    """Process accepted action submissions that still lack keypoints.

    Returns the number of submissions for which keypoints were written. Per-item
    failures are isolated so one bad clip cannot stall the rest of the queue.
    """
    extractor = extractor or MediaPipeExtractor()
    with database.transaction() as db:
        ids = db.scalars(
            select(Submission.id)
            .join(Bounty, Bounty.id == Submission.bounty_id)
            .where(
                Bounty.kind == "action",
                Submission.encrypted_media.is_not(None),
                Submission.keypoints.is_(None),
            )
            .limit(limit or 100)
        ).all()
    done = 0
    for sid in ids:
        try:
            if generate_submission_keypoints(database, cipher, sid, extractor):
                done += 1
        except KeypointError:
            continue
    return done

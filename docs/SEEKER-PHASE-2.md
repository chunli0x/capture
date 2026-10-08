# Seeker phase 2 — video, places, and cloud keypoints

Status: approved by Lisa on 2026-10-06 ("build those"). Extends the object-photo
pilot (phase 1) to the full bounty set. This is the contract the implementers
build against; it supersedes the phase-1 schema where they differ.

Baseline: captcha main `4f27958`.

## What phase 2 adds

Three bounty kinds, one shared label + media pipeline. Phase 1's `object` kind
is unchanged. The new kinds are:

| Kind | Media | Seeker labels | Ground truth |
|---|---|---|---|
| `object` | JPEG/PNG | normalized bbox list + category_id | unchanged from phase 1 |
| `place` | JPEG/PNG | single scene category_id | scene class |
| `action` | MP4 (bounded) | one action category_id + `[start_ms, end_ms]` trim | action class, time-bounded |

Three secondary label dimensions accompany any submission regardless of its
primary kind: `expressions` (facial expressions), `postures` (body language),
and `environment` (indoor/outdoor, time, weather, surface, light). They are
optional multi-select metadata resolved server-side against the registry. They
are **collected metadata, not payout or agreement gates** — reviewer consensus
still keys off the primary label only.

Keypoints are **server-generated, never seeker-drawn** (see below).

## Non-negotiable invariants (carried over + new)

1. No vision model runs in the app or is trained by the app. Cloud keypoint
   generation is the ONE permitted model use, and it is downstream/offline.
2. No children, no child imagery. Every photo/video is moderation-scanned
   fail-closed before storage (extended to video).
3. USDC payout, SKR slashable bond, never mixed. (unchanged)
4. Closed vocabulary only. No free text anywhere. Taxonomy immutable per bounty.
5. Time units in video are integer milliseconds. `start_ms < end_ms`, both
   within the clip duration. No keypoint field is writable by a seeker.

## Label schema (extend `backend/seeker/schemas.py`)

The label payload is keyed by bounty kind. A seeker submission carries exactly
one kind, matching its bounty.

- `object`: `{"boxes": [{"category_id": int, "x","y","w","h": float ∈ [0,1], x+w≤1, y+h≤1}]}` — unchanged.
- `place`: `{"scene": {"category_id": int}}` — exactly one class, no multi-label.
- `action`: `{"action": {"category_id": int, "start_ms": int, "end_ms": int}}` — one tag, bounded trim.

`keypoints` is a server-write-only field on `action` submissions: COCO-17 pose
as an optional list, written only by the keypoint job, rejected on any seeker
input (extra field → 400). Seekers never see or draw it.

Taxonomy: extend the per-bounty immutable taxonomy to three primary namespaces
(`objects`, `scenes`, `actions`) plus three secondary namespaces
(`expressions`, `postures`, `environment`). The global category registry gains a
`kind` field; environment entries also carry a mutually-exclusive `group`
(`indoor_outdoor`, `time`, `weather`, `surface`, `light`) with at most one
selection per group. `category_id` is resolved server-side; a seeker can never
mint a label.

## Media pipeline (extend `backend/seeker/media.py`)

- `object`/`place`: JPEG/PNG, same bounds as phase 1 (32 px min side, ≤12MP,
  ≤15 MiB, strip metadata, canonicalize, encrypt-approved).
- `action`: MP4, bounded duration (e.g. ≤ 30 s) and size (≤ 100 MiB), single
  video track. Reject audio-only or multi-track files. Same canonicalize +
  encrypt + moderation gate.
- Moderation: the same third-party providers, extended to video where the
  provider supports it (Sightengine video / Hive video). If a provider cannot
  scan a video, the submission fails closed — never default-PASS.
- The moderation scan still runs **before** any approved store write.

## Keypoint generation (new offline job — `backend/seeker/keypoints.py`)

- Runs on a schedule / queue after an `action` submission is accepted and its
  video is approved, never in the request path.
- MediaPipe (or equivalent) COCO-17 keypoints per sampled frame; write the
  result to the submission's `keypoints` field (server-only).
- Idempotent and resumable; a failure leaves `keypoints` absent, not corrupt.
- This is the single permitted vision-model use and is documented as such.

## API surface (extend `backend/seeker/api.py`)

- `create_bounty` gains a `kind` field (`object|place|action`) with per-kind
  reward/limit fields unchanged.
- Submission endpoints accept the per-kind label shape above.
- New/updated tests must cover: place single-class enforcement, action trim
  bounds (`start_ms<end_ms`, in-range), keypoint-write rejection for seekers,
  video moderation fail-closed, and MP4 ingestion bounds.

## Android (extend `android/.../seeker/`)

- Capture: add video capture with a hard duration cap; add place-mode (single
  class picker) and action-mode (trim scrubber + action tag picker).
- Box editor for `object` unchanged. The trim editor and tag/place pickers are
  closed-vocab, zero free text, same as phase 1.
- No on-device model. Trim is a manual scrubber; the app never generates labels.

## Definition of done

- Full backend suite green (SQLite adapter) including new phase-2 tests.
- Android `testDebugUnitTest` green with new recovery/editor tests.
- The existing phase-1 invariants still hold (re-run the whole suite; no
  regression in `object` bounties, USDC/SKR never-mix, moderation fail-closed).
- Report exact test counts; do not claim anything works without running it.

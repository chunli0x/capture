"""Migration 0004 — Capture v2 open-upload + leveling + metadata columns.

Adds, idempotently (ADD COLUMN when absent):

- ``seeker_actors.accepted_count`` — cumulative accepted open-uploads, for the
  v2 level ladder surfaced on ``/me``.
- ``seeker_submissions.kind`` — the primary kind of an open (no-bounty) upload.
- ``seeker_submissions.capture_metadata`` — resolved surface_type / lighting /
  weather / ego_motion.
- ``seeker_submissions.accepted``, ``judged_at``, ``verdict_reason``,
  ``payout_usdc``, ``level_after`` — the judge outcome and settlement, used to
  compute the rolling acceptance rate and to audit the auto-pay path.

``seeker_submissions.bounty_id`` becomes nullable for the open-upload pivot.
Fresh databases get the nullable column straight from ``create_all`` (the model
declares ``Mapped[str | None]``). An already-deployed database keeps its
NOT NULL constraint until an operator runs, once, the per-dialect drop:

    -- PostgreSQL
    ALTER TABLE seeker_submissions ALTER COLUMN bounty_id DROP NOT NULL;
    -- SQLite (table rebuild, out of scope for the idempotent ADD COLUMN pass)

The numbered-migration framework only ADD COLUMNs; it deliberately does not
attempt a cross-dialect nullable-alter here.
"""

COLUMNS = [
    # table, column, DDL fragment (idempotently ADD COLUMN'd when missing)
    ("seeker_actors", "accepted_count", "INTEGER NOT NULL DEFAULT 0"),
    ("seeker_submissions", "kind", "VARCHAR(16) NOT NULL DEFAULT 'object'"),
    ("seeker_submissions", "capture_metadata", "JSON"),
    ("seeker_submissions", "accepted", "BOOLEAN"),
    ("seeker_submissions", "judged_at", "BIGINT"),
    ("seeker_submissions", "verdict_reason", "VARCHAR(512)"),
    ("seeker_submissions", "payout_usdc", "BIGINT"),
    ("seeker_submissions", "level_after", "INTEGER"),
]

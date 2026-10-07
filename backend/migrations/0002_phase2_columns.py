"""Migration 0002 — phase-2 columns.

Adds ``Bounty.kind``, ``Submission.duration_ms`` and ``Submission.keypoints``
to an existing phase-1 Seeker database. Idempotent: each column is added only
when it is absent, so it is safe to run against a fresh DB (where ``create_all``
already emitted the column) or an upgraded one. SQLite has no
``ALTER TABLE … ADD COLUMN IF NOT EXISTS``, so the idempotency check lives in
``seeker/migrate.py`` and works on both SQLite and PostgreSQL.
"""

COLUMNS = [
    # table, column, DDL fragment (idempotently ADD COLUMN'd when missing)
    ("seeker_bounties", "kind", "VARCHAR(16) NOT NULL DEFAULT 'object'"),
    ("seeker_submissions", "duration_ms", "BIGINT"),
    ("seeker_submissions", "keypoints", "JSON"),
]

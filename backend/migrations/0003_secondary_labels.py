"""Migration 0003 — secondary label dimensions.

Adds ``seeker_submissions.secondary`` and ``seeker_reviews.secondary`` for the
optional, non-gating label dimensions (facial expressions, body language,
environment). Idempotent: each column is added only when absent, so it is safe
against a fresh DB (where ``create_all`` already emitted it) or an upgraded one.
"""

COLUMNS = [
    # table, column, DDL fragment (idempotently ADD COLUMN'd when missing)
    ("seeker_submissions", "secondary", "JSON"),
    ("seeker_reviews", "secondary", "JSON"),
]

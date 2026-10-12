"""Migration 0007 — boolean verdict column for open-upload peer reviews.

Adds ``seeker_reviews.accepted`` (BOOLEAN NULL). Open-upload free reviews carry a
simple accept/reject verdict (a quick quality check, not a full re-label), so this
nullable column records it; NULL for the operator bounty-review path, which still
uses the full labels + secondary fields. Fresh DBs get it from ``create_all``.
"""

COLUMNS = [
    # table, column, DDL fragment (idempotently ADD COLUMN'd when missing)
    ("seeker_reviews", "accepted", "BOOLEAN"),
]

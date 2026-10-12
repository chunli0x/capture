"""Migration 0008 — on-chain settlement signature.

Adds ``seeker_submissions.payout_signature`` (VARCHAR(88), the base58 signature
of the treasury -> worker USDC transfer recorded when an open upload is
accepted). Fresh DBs get the column from ``create_all`` (the model declares the
same ``Mapped[str | None]``); an upgraded DB gets it idempotently via the
numbered ADD COLUMN pass.
"""

COLUMNS = [
    # table, column, DDL fragment (idempotently ADD COLUMN'd when missing)
    ("seeker_submissions", "payout_signature", "VARCHAR(88)"),
]

"""Migration 0009 — accrued (batched) payout balance.

Adds ``seeker_actors.pending_usdc`` (BIGINT, default 0): accepted uploads credit
this off-chain instead of settling on-chain per upload. A batched settle
endpoint then transfers the whole balance in one treasury transaction, cutting
on-chain fee spend from one tx per accepted upload to one tx per settle.
"""

COLUMNS = [
    # table, column, DDL fragment (idempotently ADD COLUMN'd when missing)
    ("seeker_actors", "pending_usdc", "BIGINT DEFAULT 0"),
]

"""Migration 0012 — durable $SKR payout journal (finding 10 #1).

Adds ``judgments.settling``: an earned-SKR obligation that is committed to the
ledger before its mint transaction broadcasts. Without it, a partial payout (one
judge paid, the next settle raises ChainUnavailable) is lost — the pair returns
to ``collecting`` and a later re-resolution pays the already-paid judge again.
With it, the obligation survives a crash/failure and is reconciled by the
resolve/retry path instead of being re-created.
"""

COLUMNS = [
    ("judgments", "settling", "BOOLEAN DEFAULT FALSE"),
]

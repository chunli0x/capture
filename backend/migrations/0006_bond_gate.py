"""Migration 0006 — bond gate + free quality-check columns.

Adds to ``seeker_actors`` (idempotently, ADD COLUMN when absent):

- ``bonded`` — true once the devnet bond is deposited (``/bond/deposit``).
- ``quality_checks`` — completed free peer-reviews count, the free-tier unlock
  counter toward ``QUALITY_CHECKS_REQUIRED``.
- ``skr_funded`` — true once the devnet test-SKR faucet ran (``/bond/faucet``).

Fresh databases get the columns straight from ``create_all`` (the model
declares the same ``Mapped`` columns with the same defaults). All three are
server-recorded settlement state — consistent with "TEST-USDC recorded, not
transferred" — and never touch the on-chain prepare seam.
"""

COLUMNS = [
    # table, column, DDL fragment (idempotently ADD COLUMN'd when missing)
    ("seeker_actors", "bonded", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("seeker_actors", "quality_checks", "INTEGER NOT NULL DEFAULT 0"),
    ("seeker_actors", "skr_funded", "BOOLEAN NOT NULL DEFAULT FALSE"),
]

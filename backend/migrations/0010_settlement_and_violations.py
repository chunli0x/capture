"""Migration 0010 — settlement intent + violation journal.

Finding 1 (durable settlement): ``pending_usdc`` was zeroed immediately after
``sendTransaction`` broadcast, so a dropped transaction lost earnings and a lost
response could double-pay on retry. Adds ``seeker_actors.settling_usdc``: the
settle endpoint moves the balance pending -> settling (committed) BEFORE
broadcasting, then clears settling only on a confirmed transfer, restoring it
on failure.

Finding 4 (strike idempotency): the two-strike ladder had no record of which
violations were already punished, so retrying the same rejected upload could
count as another strike. Adds ``seeker_violations`` to dedupe enforcement per
(worker, media_hash).
"""

COLUMNS = [
    ("seeker_actors", "settling_usdc", "BIGINT DEFAULT 0"),
]

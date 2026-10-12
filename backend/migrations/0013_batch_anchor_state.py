"""Migration 0013 — durable on-chain batch anchor (finding 10 #10).

Adds ``judgment_batches.anchored``: the Merkle root is only marked anchored
after ``post_batch`` confirms on-chain. A failed final anchor (e.g. the last
pair resolves and the RPC is down) previously had no durable retry — the
exception was swallowed and no reconciliation worker existed. With this flag,
the reconcile pass re-attempts any batch that has a root but is not anchored.
"""

COLUMNS = [
    ("judgment_batches", "anchored", "BOOLEAN DEFAULT FALSE"),
]

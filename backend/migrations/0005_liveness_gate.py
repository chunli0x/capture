"""Migration 0005 — server-side liveness gate flag.

Adds ``seeker_actors.liveness_completed`` (BOOLEAN NOT NULL DEFAULT FALSE),
idempotently via the numbered ADD COLUMN pass. Set to true by
``/liveness/complete`` once a wallet finishes a server-issued liveness session;
``POST /submissions`` (open upload) refuses a worker until it is true.

Fresh databases get the column straight from ``create_all`` (the model declares
``Mapped[bool]`` with ``default=False``).
"""

COLUMNS = [
    # table, column, DDL fragment (idempotently ADD COLUMN'd when missing)
    ("seeker_actors", "liveness_completed", "BOOLEAN NOT NULL DEFAULT FALSE"),
]

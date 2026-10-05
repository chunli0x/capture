# Seeker schema version 1

Run `python -m seeker.migrate` before starting `seeker.api:app`.
The initial schema lives in `seeker/db.py`; creation is additive and idempotent,
never automatic on application startup. Use a separate PostgreSQL database
and a migration role with DDL rights. The runtime role needs only DML rights.
No existing demo data is imported or silently converted into a funded balance.

This first migration does not alter an existing Seeker installation. Future
schema changes require numbered migrations; do not use create_all to upgrade.
Rollback: stop this isolated service and retain its database for reconciliation.
Do not delete settlement history for bounties that still hold escrow.

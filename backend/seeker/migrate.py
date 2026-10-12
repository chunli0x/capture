"""Apply Seeker schema: create_all for fresh DBs plus numbered, idempotent
column migrations for upgrades. Run `python -m seeker.migrate`."""

import importlib.util
from pathlib import Path

from sqlalchemy import inspect

from .config import Settings
from .db import Base, connect

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _numbered_migrations():
    """Yield (migration_id, columns) for every NNNN_*.py module in migrations/,
    in filename order. Each module exposes a COLUMNS list of
    (table, column, ddl) triples."""
    for path in sorted(MIGRATIONS_DIR.glob("[0-9]*.py")):
        spec = importlib.util.spec_from_file_location(
            "seeker_migrations_" + path.stem, path
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield path.stem, module.COLUMNS


def apply_migrations(engine):
    """Idempotently apply every numbered migration. A column is added with
    ``ALTER TABLE … ADD COLUMN`` only when it is absent, so an existing phase-1
    DB upgrades cleanly (duration_ms stops being silently NULL) and re-running
    is a no-op. Works on both SQLite and PostgreSQL."""
    applied = 0
    for migration_id, columns in _numbered_migrations():
        for table, column, ddl in columns:
            inspector = inspect(engine)
            if not inspector.has_table(table):
                # Fresh DBs get the column via create_all; a table absent here
                # means there is nothing to upgrade for this column.
                continue
            if column in {c["name"] for c in inspector.get_columns(table)}:
                continue
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"
                )
            applied += 1
    applied += apply_nullability_migrations(engine)
    return applied


def apply_nullability_migrations(engine):
    """Drop NOT NULL constraints the v2 open-upload pivot made obsolete.

    The numbered ADD COLUMN framework cannot express a nullability change
    cross-dialect, so these live here. ``bounty_id`` must become nullable so an
    open (no-bounty) upload can insert NULL. PostgreSQL: a plain
    ``ALTER COLUMN … DROP NOT NULL``, idempotent. SQLite: a fresh DB already
    gets the nullable column from ``create_all`` (the model declares
    ``Mapped[str | None]``), and the deployed DB is PostgreSQL, so SQLite is a
    no-op here.
    """
    if engine.dialect.name != "postgresql":
        return 0
    inspector = inspect(engine)
    if not inspector.has_table("seeker_submissions"):
        return 0
    col = next(
        (c for c in inspector.get_columns("seeker_submissions") if c["name"] == "bounty_id"),
        None,
    )
    if col is None or col.get("nullable"):
        return 0
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE seeker_submissions ALTER COLUMN bounty_id DROP NOT NULL"
        )
    return 1


def main():
    settings = Settings()
    engine = connect(settings.database_url)
    # create_all is additive and idempotent; numbered migrations handle the rest.
    Base.metadata.create_all(engine)
    apply_migrations(engine)
    print("Seeker schema applied (create_all + numbered migrations)")


if __name__ == "__main__":
    main()

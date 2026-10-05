"""Initial, additive schema. Requires explicit invocation against an empty Seeker DB."""

from .config import Settings
from .db import Base, connect


def main():
    settings = Settings()
    engine = connect(settings.database_url)
    # Version 1 is additive only, idempotent, and never touches tapfarm tables.
    Base.metadata.create_all(engine)
    print("Seeker schema version 1 applied")


if __name__ == "__main__":
    main()

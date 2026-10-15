
from __future__ import annotations

from app.db import models  # noqa: F401  (registers the tables on Base.metadata)
from app.core.config import Settings
from app.db.database import Base, Database
from app.db.seed import seed_defaults


def initialize_database(database: Database, settings: Settings) -> None:
    Base.metadata.create_all(bind=database.engine)
    with database.session() as db:
        seed_defaults(db, settings.layout)
        db.commit()

from __future__ import annotations

from app.db import models  
from app.core.config import Settings
from app.db.database import Base, Database
from app.db.migrations import migrate
from app.db.seed import seed_defaults


def initialize_database(database: Database, settings: Settings) -> dict:
    Base.metadata.create_all(bind=database.engine)   
    report = migrate(database.engine)                
    with database.session() as db:
        seed_defaults(db, settings.layout)
        db.commit()
    return report

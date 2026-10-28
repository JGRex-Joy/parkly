from __future__ import annotations

import logging

from app.db.database import Database
from app.repositories.audit import AuditRepository

logger = logging.getLogger(__name__)


class SeparateTransactionAudit:
    def __init__(self, database: Database) -> None:
        self._database = database

    def record(self, kind: str, **detail) -> None:
        session_id = detail.pop("session_id", None)
        slot_id = detail.pop("slot_id", None)
        plate = detail.pop("plate", None) or detail.pop("plate_number", None)
        try:
            with self._database.session() as db:
                AuditRepository(db).add(
                    kind, session_id=session_id, slot_id=slot_id, plate_number=plate, **detail
                )
                db.commit()
        except Exception:  
            logger.exception("could not record audit event %s", kind)

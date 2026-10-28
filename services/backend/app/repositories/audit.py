from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context import get_correlation_id
from app.db.models import AuditEvent


class AuditRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add(
        self,
        kind: str,
        *,
        session_id: Optional[int] = None,
        slot_id: Optional[int] = None,
        plate_number: Optional[str] = None,
        event_key: Optional[str] = None,
        **detail: Any,
    ) -> AuditEvent:
        row = AuditEvent(
            kind=kind,
            correlation_id=get_correlation_id(),
            session_id=session_id,
            slot_id=slot_id,
            plate_number=plate_number,
            event_key=event_key,
            detail=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
        )
        self._db.add(row)
        self._db.flush()
        return row

    def has_key(self, event_key: str) -> bool:
        return self._db.scalars(select(AuditEvent.id).where(AuditEvent.event_key == event_key)).first() is not None

    def list(
        self,
        *,
        session_id: Optional[int] = None,
        correlation_id: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 200,
    ) -> list[AuditEvent]:
        stmt = select(AuditEvent)
        if session_id is not None:
            stmt = stmt.where(AuditEvent.session_id == session_id)
        if correlation_id:
            stmt = stmt.where(AuditEvent.correlation_id == correlation_id)
        if kind:
            stmt = stmt.where(AuditEvent.kind == kind)
        return list(self._db.scalars(stmt.order_by(AuditEvent.id.desc()).limit(limit)))

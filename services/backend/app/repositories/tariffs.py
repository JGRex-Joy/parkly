from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Tariff


class TariffRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_active(self) -> Optional[Tariff]:
        return self._db.scalars(
            select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.id)
        ).first()

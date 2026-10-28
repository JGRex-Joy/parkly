from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import ParkingLayout
from app.api.exceptions import SlotOccupiedError
from app.db.models import ParkingSession, Slot, SlotStatus, SlotType


class SlotRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_active(self) -> list[Slot]:
        return list(
            self._db.scalars(select(Slot).where(Slot.is_active.is_(True)).order_by(Slot.id))
        )

    def get(self, slot_id: int) -> Optional[Slot]:
        return self._db.get(Slot, slot_id)

    def get_active(self, slot_id: int) -> Optional[Slot]:
        return self._db.scalars(
            select(Slot).where(Slot.id == slot_id, Slot.is_active.is_(True))
        ).first()

    def count_total(self) -> int:
        return self._count()

    def count_free(self) -> int:
        return self._count(Slot.status == SlotStatus.FREE)

    def count_occupied_outside_layout(self) -> int:
        return (
            self._db.scalar(
                select(func.count())
                .select_from(Slot)
                .where(Slot.is_active.is_(False), Slot.status == SlotStatus.PARKED)
            )
            or 0
        )

    def _count(self, *criteria) -> int:
        stmt = select(func.count()).select_from(Slot).where(Slot.is_active.is_(True), *criteria)
        return self._db.scalar(stmt) or 0

    def lock_all(self) -> None:
        self._db.execute(
            select(Slot.id).where(Slot.is_active.is_(True)).order_by(Slot.id).with_for_update()
        ).all()

    def mark_parked(self, slot: Slot) -> None:
        result = self._db.execute(
            update(Slot)
            .where(Slot.id == slot.id, Slot.status == SlotStatus.FREE)
            .values(status=SlotStatus.PARKED)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise SlotOccupiedError()
        self._db.refresh(slot)

    def mark_free(self, slot: Slot) -> None:
        slot.status = SlotStatus.FREE
        self._db.flush()

    def synchronize_layout(self, layout: ParkingLayout) -> None:
        existing = {s.slot_number: s for s in self._db.scalars(select(Slot))}
        for number in layout.slots:
            slot = existing.get(number)
            if slot is None:
                self._db.add(Slot(slot_number=number, slot_type=SlotType.PAID))
            else:
                slot.slot_type = SlotType.PAID
                slot.is_active = True
        for number, slot in existing.items():
            if number not in layout.slots:
                slot.is_active = False
        self._db.flush()

    def free_spaces_without_holder(self) -> int:
        held = select(ParkingSession.slot_id).where(
            ParkingSession.slot_id.is_not(None), ParkingSession.slot_released_at.is_(None)
        )
        result = self._db.execute(
            update(Slot)
            .where(Slot.status == SlotStatus.PARKED, Slot.id.not_in(held))
            .values(status=SlotStatus.FREE)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount

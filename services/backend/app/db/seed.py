
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import ParkingLayout
from app.db.models import Employee, Tariff
from app.repositories.slots import SlotRepository

DEFAULT_TARIFF = {
    "name": "Стандартный (тест: считаем по минутам)",
    "price_per_minute": 5.0,
    "free_minutes": 1,
    "is_active": True,
}
DEFAULT_EMPLOYEES = (
    ("A001AA", "Иванов И.И."),
    ("B777BB", "Петров П.П."),
)


def seed_defaults(db: Session, layout: ParkingLayout) -> None:
    slots = SlotRepository(db)
    slots.synchronize_layout(layout)
    slots.free_spaces_without_holder()

    if not db.scalar(select(func.count()).select_from(Tariff)):
        db.add(Tariff(**DEFAULT_TARIFF))
    if not db.scalar(select(func.count()).select_from(Employee)):
        db.add_all(Employee(plate_number=p, full_name=n) for p, n in DEFAULT_EMPLOYEES)

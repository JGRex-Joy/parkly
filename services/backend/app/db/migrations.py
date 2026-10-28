from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, select, text, true, update
from sqlalchemy.orm import Session

from app.db import models
from app.utils import normalize_plate, utcnow

logger = logging.getLogger(__name__)

_NEW_STATUS_LABELS = ("COMPLETED", "EXCEPTION")


def _add_missing_columns(engine: Engine) -> list[str]:
    added: list[str] = []
    with engine.begin() as conn:
        insp = inspect(conn)  
        for table in (models.Slot.__table__, models.ParkingSession.__table__):
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl_type = column.type.compile(dialect=engine.dialect)
                default = ""
                if not column.nullable:
                    literal = str(true().compile(dialect=engine.dialect))
                    default = f" NOT NULL DEFAULT {literal}"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {ddl_type}{default}'))
                added.append(f"{table.name}.{column.name}")
    return added


def _backfill_and_repair(engine: Engine) -> dict:
    stats = {"released_finished": 0, "duplicate_holders": 0, "plates_normalised": 0}
    S = models.ParkingSession
    now = utcnow()
    with Session(engine) as db:
        # a) finished visits must not keep holding a space
        finished = db.scalars(
            select(S).where(
                S.slot_id.is_not(None),
                S.slot_released_at.is_(None),
                (S.status.in_((models.SessionStatus.PAID, models.SessionStatus.COMPLETED)))
                | (S.exit_time.is_not(None) & (S.status == models.SessionStatus.EMPLOYEE_PASS)),
            )
        ).all()
        for s in finished:
            s.slot_released_at = s.paid_time or s.exit_time or now
            stats["released_finished"] += 1
        db.flush()

        # b) of several holders of one space only the newest keeps it
        holders: dict[int, list] = {}
        for s in db.scalars(
            select(S).where(S.slot_id.is_not(None), S.slot_released_at.is_(None)).order_by(S.id)
        ):
            holders.setdefault(s.slot_id, []).append(s)
        for group in holders.values():
            for older in group[:-1]:
                older.slot_released_at = now
                stats["duplicate_holders"] += 1
        db.flush()

        # c) canonical plate form (spaces/dashes removed, upper case)
        for s in db.scalars(select(S)):
            canon = normalize_plate(s.plate_number)
            if canon != s.plate_number:
                s.plate_number = canon
                stats["plates_normalised"] += 1
        taken = {e.plate_number for e in db.scalars(select(models.Employee))}
        for e in db.scalars(select(models.Employee)):
            canon = normalize_plate(e.plate_number)
            if canon != e.plate_number and canon not in taken:
                taken.discard(e.plate_number)
                taken.add(canon)
                e.plate_number = canon
                stats["plates_normalised"] += 1
        db.commit()
    return stats


def _create_missing_indexes(engine: Engine) -> list[str]:
    created: list[str] = []
    insp = inspect(engine)
    for table in (models.ParkingSession.__table__, models.Payment.__table__, models.AuditEvent.__table__):
        if not insp.has_table(table.name):
            continue
        have = {i["name"] for i in insp.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in have:
                index.create(bind=engine)
                created.append(index.name)
    return created


def _extend_postgres_enum(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for label in _NEW_STATUS_LABELS:
            conn.execute(text(f"ALTER TYPE sessionstatus ADD VALUE IF NOT EXISTS '{label}'"))


def migrate(engine: Engine) -> dict:
    added = _add_missing_columns(engine)
    stats = _backfill_and_repair(engine)
    indexes = _create_missing_indexes(engine)
    _extend_postgres_enum(engine)
    report = {"columns_added": added, "indexes_created": indexes, **stats}
    if added or indexes or any(stats.values()):
        logger.info("database migrated: %s", report)
    return report

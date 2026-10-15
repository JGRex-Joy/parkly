
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from app.repositories.slots import SlotRepository
from app.services.publishing import DisplayPublisher

logger = logging.getLogger(__name__)


class Outbox:
    def __init__(self) -> None:
        self._messages: list[tuple[str, dict]] = []

    def add(self, channel: str, payload: dict) -> None:
        self._messages.append((channel, payload))

    def __iter__(self):
        return iter(self._messages)


class UnitOfWork:
    def __init__(
        self, db: Session, slots: SlotRepository, publisher: DisplayPublisher
    ) -> None:
        self._db = db
        self._slots = slots
        self._publisher = publisher

    @contextmanager
    def transaction(self) -> Iterator[Outbox]:
 
        outbox = Outbox()
        try:
            self._slots.lock_all()
            yield outbox
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        for channel, payload in outbox:
            try:
                self._publisher.publish(channel, payload)
            except Exception:
                logger.exception("Failed to publish to %r display channel", channel)

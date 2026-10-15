from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.db.bootstrap import initialize_database
from app.core.config import Settings
from app.db.database import Database
from app.main import create_app
from app.repositories import Repositories
from app.services.display import DisplayPayloadBuilder
from app.services.parking import ParkingService
from app.services.payment import PaymentService
from app.services.unit_of_work import UnitOfWork


@pytest.fixture()
def settings(tmp_path) -> Settings:
    """Isolated file-based SQLite DB (a real file so threads get real connections)."""
    return replace(Settings(), database_url=f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


# ---- service-level fixtures (no HTTP) -------------------------------------
class RecordingPublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    def publish(self, channel: str, payload: dict) -> None:
        self.messages.append((channel, payload))


class Scope:
    """One request-like unit: its own DB session and services."""

    def __init__(self, database: Database, settings: Settings, publisher, clock=None):
        self.db = database.session()
        self.repos = Repositories.for_session(self.db)
        uow = UnitOfWork(self.db, self.repos.slots, publisher)
        displays = DisplayPayloadBuilder(self.repos, settings.base_url)
        extra = {"clock": clock} if clock else {}
        self.parking = ParkingService(
            self.repos, uow, displays,
            pending_entry_ttl_seconds=settings.pending_entry_ttl_seconds, **extra,
        )
        self.payment = PaymentService(self.repos, uow, displays, **extra)

    def close(self) -> None:
        self.db.close()


@pytest.fixture()
def database(settings):
    db = Database(settings.database_url)
    initialize_database(db, settings)
    yield db
    db.dispose()


@pytest.fixture()
def publisher():
    return RecordingPublisher()


@pytest.fixture()
def make_scope(database, settings, publisher):
    scopes = []

    def factory(clock=None) -> Scope:
        scope = Scope(database, settings, publisher, clock)
        scopes.append(scope)
        return scope

    yield factory
    for scope in scopes:
        scope.close()

from __future__ import annotations

from typing import Iterator

from fastapi import Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from backend.app.core.config import Settings
from app.db.database import Database
from app.repositories import Repositories
from app.services.audit import SeparateTransactionAudit
from app.services.display import DisplayPayloadBuilder
from app.services.hardware import HardwareService
from app.services.parking import ParkingService, ServicePolicy
from app.services.payment import PaymentService
from app.services.payment_providers import PaymentProvider
from app.services.publishing import DisplayPublisher
from app.services.unit_of_work import UnitOfWork
from app.websocket_manager import ConnectionManager


def get_settings(conn: HTTPConnection) -> Settings:
    return conn.app.state.settings


def get_database(conn: HTTPConnection) -> Database:
    return conn.app.state.database


def get_connection_manager(conn: HTTPConnection) -> ConnectionManager:
    return conn.app.state.connection_manager


def get_publisher(conn: HTTPConnection) -> DisplayPublisher:
    return conn.app.state.publisher


def get_templates(conn: HTTPConnection) -> Jinja2Templates:
    return conn.app.state.templates


def get_provider(conn: HTTPConnection) -> PaymentProvider:
    return conn.app.state.payment_provider


def get_policy(settings: Settings = Depends(get_settings)) -> ServicePolicy:
    return ServicePolicy.from_settings(settings)


def get_rejection_audit(database: Database = Depends(get_database)) -> SeparateTransactionAudit:
    return SeparateTransactionAudit(database)


def get_db(database: Database = Depends(get_database)) -> Iterator[Session]:
    db = database.session()
    try:
        yield db
    finally:
        db.close()


def get_repositories(db: Session = Depends(get_db)) -> Repositories:
    return Repositories.for_session(db)


def get_display_builder(
    repos: Repositories = Depends(get_repositories),
    settings: Settings = Depends(get_settings),
    provider: PaymentProvider = Depends(get_provider),
) -> DisplayPayloadBuilder:
    return DisplayPayloadBuilder(
        repos,
        settings.base_url,
        currency=settings.currency,
        payment_simulated=provider.is_simulated,
        auth_ttl_seconds=settings.auth_ttl_seconds,
    )


def get_unit_of_work(
    db: Session = Depends(get_db),
    repos: Repositories = Depends(get_repositories),
    publisher: DisplayPublisher = Depends(get_publisher),
) -> UnitOfWork:
    return UnitOfWork(db, repos.slots, publisher)


def get_parking_service(
    repos: Repositories = Depends(get_repositories),
    uow: UnitOfWork = Depends(get_unit_of_work),
    displays: DisplayPayloadBuilder = Depends(get_display_builder),
    settings: Settings = Depends(get_settings),
    policy: ServicePolicy = Depends(get_policy),
    provider: PaymentProvider = Depends(get_provider),
    rejections: SeparateTransactionAudit = Depends(get_rejection_audit),
) -> ParkingService:
    return ParkingService(
        repos, uow, displays,
        pending_entry_ttl_seconds=settings.pending_entry_ttl_seconds,
        policy=policy, provider=provider, rejections=rejections,
    )


def get_payment_service(
    repos: Repositories = Depends(get_repositories),
    uow: UnitOfWork = Depends(get_unit_of_work),
    displays: DisplayPayloadBuilder = Depends(get_display_builder),
    settings: Settings = Depends(get_settings),
    provider: PaymentProvider = Depends(get_provider),
    rejections: SeparateTransactionAudit = Depends(get_rejection_audit),
) -> PaymentService:
    return PaymentService(
        repos, uow, displays, provider=provider, currency=settings.currency, rejections=rejections
    )


def get_hardware_service(
    repos: Repositories = Depends(get_repositories),
    uow: UnitOfWork = Depends(get_unit_of_work),
    displays: DisplayPayloadBuilder = Depends(get_display_builder),
    policy: ServicePolicy = Depends(get_policy),
) -> HardwareService:
    return HardwareService(repos, uow, displays, policy=policy)

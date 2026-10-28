from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _is_memory_sqlite(url: str) -> bool:
    return url in ("sqlite://", "sqlite:///:memory:")


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        kwargs: dict = {"echo": echo}
        if _is_sqlite(url):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if _is_memory_sqlite(url):
                kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, **kwargs)
        if _is_sqlite(url):
            self._configure_sqlite(self.engine)
        self._factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )

    @staticmethod
    def _configure_sqlite(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_connection, _record) -> None:
            dbapi_connection.isolation_level = None  
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        @event.listens_for(engine, "begin")
        def _on_begin(conn) -> None:
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    def session(self) -> Session:
        return self._factory()

    def dispose(self) -> None:
        self.engine.dispose()

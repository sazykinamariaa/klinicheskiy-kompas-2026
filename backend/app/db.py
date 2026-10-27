"""Подключение к БД. По умолчанию SQLite (файл), для боевого режима — PostgreSQL через KK_DATABASE_URL."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def _url() -> str:
    url = os.environ.get("KK_DATABASE_URL")
    if url:
        return url
    data = Path(os.environ.get("KK_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    data.mkdir(parents=True, exist_ok=True)
    return "sqlite:///%s" % (data / "kk.sqlite3")


_engine = None
_Session = None


def init(url: str = None):
    """Создать подключение (повторный вызов пересоздаёт; нужно тестам)."""
    global _engine, _Session
    url = url or _url()
    kw = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
    if url == "sqlite://":
        from sqlalchemy.pool import StaticPool
        kw["poolclass"] = StaticPool
    _engine = create_engine(url, future=True, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _pragma(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=FULL")  # не терять критические данные при сбое питания
            cur.close()
    _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    from . import models  # noqa: F401
    Base.metadata.create_all(_engine)
    return _engine


def engine():
    if _engine is None:
        init()
    return _engine


def Session():
    if _Session is None:
        init()
    return _Session()


@contextmanager
def session_scope():
    s = Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()

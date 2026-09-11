from __future__ import annotations

from contextlib import contextmanager

from flask import current_app, g
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .database_config import connect_args


class Base(DeclarativeBase):
    pass


def init_engine(app):
    engine = create_engine(
        app.config["DATABASE_URL"],
        connect_args=connect_args(app.config["DATABASE_SCHEMA"]),
        pool_pre_ping=True,
        pool_size=app.config["DATABASE_POOL_SIZE"],
        max_overflow=app.config["DATABASE_MAX_OVERFLOW"],
        pool_timeout=app.config["DATABASE_POOL_TIMEOUT"],
        pool_recycle=300,
        future=True,
    )
    app.extensions["sqlalchemy_engine"] = engine
    app.extensions["session_factory"] = sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False
    )

    @app.teardown_appcontext
    def close_session(_error=None):
        session = g.pop("db_session", None)
        if session is not None:
            session.close()


def get_session() -> Session:
    if "db_session" not in g:
        g.db_session = current_app.extensions["session_factory"]()
    return g.db_session


@contextmanager
def session_scope(app=None):
    factory = (app or current_app).extensions["session_factory"]
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

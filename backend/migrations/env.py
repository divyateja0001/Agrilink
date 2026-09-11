from __future__ import annotations

from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine, pool

from app.db import Base
from app import models  # noqa: F401
from app.database_config import connect_args, database_schema, database_url


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
resolved_url = database_url(migration=True, strict=True)
resolved_schema = database_schema()
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=resolved_url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction(): context.run_migrations()


def run_migrations_online():
    connectable = create_engine(
        resolved_url,
        connect_args=connect_args(resolved_schema),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction(): context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()

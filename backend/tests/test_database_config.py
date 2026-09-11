from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from app.database_config import database_schema, database_target, database_url


def test_supabase_session_pooler_forces_tls(monkeypatch):
    monkeypatch.setenv("AGRILINK_DATABASE_TARGET", "supabase")
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://agrilink_app.project:secret@aws-0-region.pooler.supabase.com:5432/postgres",
    )
    monkeypatch.delenv("DB_SCHEMA", raising=False)
    monkeypatch.delenv("SUPABASE_DB_SCHEMA", raising=False)

    resolved = make_url(database_url(strict=True))

    assert database_target() == "supabase"
    assert database_schema() == "agrilink"
    assert resolved.drivername == "postgresql+psycopg"
    assert resolved.query["sslmode"] == "require"


def test_supabase_transaction_pooler_is_rejected(monkeypatch):
    monkeypatch.setenv("AGRILINK_DATABASE_TARGET", "supabase")
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://agrilink_app.project:secret@aws-0-region.pooler.supabase.com:6543/postgres",
    )

    with pytest.raises(RuntimeError, match="transaction pooling"):
        database_url(strict=True)


def test_local_target_prefers_local_url(monkeypatch):
    monkeypatch.setenv("AGRILINK_DATABASE_TARGET", "local")
    monkeypatch.setenv(
        "LOCAL_DATABASE_URL",
        "postgresql://agrilink_app:secret@127.0.0.1:5432/agrilink",
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://legacy:secret@127.0.0.1:5432/legacy",
    )

    resolved = make_url(database_url(strict=True))

    assert resolved.username == "agrilink_app"
    assert resolved.database == "agrilink"


def test_invalid_database_target_is_rejected(monkeypatch):
    monkeypatch.setenv("AGRILINK_DATABASE_TARGET", "automatic")
    with pytest.raises(RuntimeError, match="supabase.*local"):
        database_target()

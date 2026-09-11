from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from app import create_app
from app.db import Base


@pytest.fixture(scope="session")
def app():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database.")
    schema = os.getenv("TEST_DATABASE_SCHEMA", "public")
    if schema != "public":
        bootstrap = create_engine(url)
        with bootstrap.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        bootstrap.dispose()
    app = create_app({"TESTING": True, "DATABASE_URL": url, "DATABASE_SCHEMA": schema, "SESSION_COOKIE_SECURE": False})
    with app.app_context():
        Base.metadata.drop_all(app.extensions["sqlalchemy_engine"])
        Base.metadata.create_all(app.extensions["sqlalchemy_engine"])
    yield app
    with app.app_context(): Base.metadata.drop_all(app.extensions["sqlalchemy_engine"])


@pytest.fixture()
def client(app):
    return app.test_client()

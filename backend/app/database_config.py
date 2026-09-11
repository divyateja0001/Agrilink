from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

DEFAULT_LOCAL_DATABASE_URL = (
    "postgresql+psycopg://agrilink_app:CHANGE_ME@127.0.0.1:5432/agrilink"
)
VALID_TARGETS = {"local", "supabase"}
SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")


def database_target() -> str:
    target = os.getenv("AGRILINK_DATABASE_TARGET", "").strip().lower()
    if not target:
        # Existing installations used DATABASE_URL directly and remain local until
        # the operator explicitly selects Supabase.
        target = "local"
    if target not in VALID_TARGETS:
        raise RuntimeError(
            "AGRILINK_DATABASE_TARGET must be either 'supabase' or 'local'."
        )
    return target


def database_schema(target: str | None = None) -> str:
    selected = target or database_target()
    target_schema_key = (
        "SUPABASE_DB_SCHEMA" if selected == "supabase" else "LOCAL_DB_SCHEMA"
    )
    schema = (
        os.getenv("DB_SCHEMA", "").strip()
        or os.getenv(target_schema_key, "").strip()
        or ("agrilink" if selected == "supabase" else "public")
    )
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise RuntimeError(
            "DB_SCHEMA must start with a lowercase letter or underscore and contain "
            "only lowercase letters, numbers, and underscores."
        )
    return schema


def _use_psycopg(url: str) -> URL:
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    parsed = make_url(url)
    if parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+psycopg")
    if parsed.drivername != "postgresql+psycopg":
        raise RuntimeError("AgriLink requires a PostgreSQL psycopg connection URL.")
    return parsed


def database_url(*, migration: bool = False, strict: bool = False) -> str:
    target = database_target()
    if target == "supabase":
        key = "SUPABASE_MIGRATION_URL" if migration else "SUPABASE_DATABASE_URL"
        raw = os.getenv(key, "").strip()
        if migration and not raw:
            raw = os.getenv("SUPABASE_DATABASE_URL", "").strip()
        if not raw:
            if strict:
                raise RuntimeError(
                    f"{key} is not configured. Copy backend/.env.example to "
                    "backend/.env and paste the URL from Supabase Connect."
                )
            return DEFAULT_LOCAL_DATABASE_URL
        if any(marker in raw for marker in ("CHANGE_ME", "YOUR-", "PROJECT-REF")):
            raise RuntimeError(f"{key} still contains a placeholder value.")
        parsed = _use_psycopg(raw)
        if not parsed.host or not parsed.host.endswith(".supabase.com"):
            raise RuntimeError(f"{key} must use a hosted Supabase database host.")
        if (parsed.username or "").split(".", 1)[0] != "agrilink_app":
            raise RuntimeError(
                f"{key} must authenticate as the dedicated agrilink_app role."
            )
        if parsed.port == 6543:
            raise RuntimeError(
                f"{key} uses transaction pooling on port 6543. Use the session "
                "pooler on port 5432 for AgriLink's persistent Flask processes."
            )
        parsed = parsed.update_query_dict({"sslmode": "require"})
        return parsed.render_as_string(hide_password=False)

    raw = (
        os.getenv("LOCAL_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
        or DEFAULT_LOCAL_DATABASE_URL
    )
    if strict and "CHANGE_ME" in raw:
        raise RuntimeError(
            "LOCAL_DATABASE_URL is not configured with the agrilink_app password."
        )
    return _use_psycopg(raw).render_as_string(hide_password=False)


def connect_args(schema: str | None = None) -> dict[str, str]:
    selected_schema = schema or database_schema()
    return {"options": f"-csearch_path={selected_schema}"}

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.database_config import database_schema, database_url  # noqa: E402


ROLE_NAME = "agrilink_app"


def connection_info(raw_url: str) -> str:
    parsed = make_url(raw_url)
    if not parsed.host or not parsed.username or not parsed.database:
        raise RuntimeError("Supabase URL must include a host, user, and database.")
    if not parsed.host.endswith(".supabase.com"):
        raise RuntimeError("Expected a dashboard-generated Supabase database URL.")
    return make_conninfo(
        host=parsed.host,
        port=parsed.port or 5432,
        dbname=parsed.database,
        user=parsed.username,
        password=parsed.password or "",
        sslmode="require",
        connect_timeout=10,
    )


def main() -> int:
    if os.getenv("AGRILINK_DATABASE_TARGET", "").lower() != "supabase":
        raise RuntimeError(
            "Set AGRILINK_DATABASE_TARGET=supabase before running this bootstrap."
        )
    admin_url = os.getenv("SUPABASE_ADMIN_URL", "").strip()
    app_password = os.getenv("SUPABASE_APP_PASSWORD", "")
    if not admin_url:
        raise RuntimeError("SUPABASE_ADMIN_URL is required for the one-time bootstrap.")
    if any(marker in admin_url for marker in ("CHANGE_ME", "YOUR-", "PROJECT-REF")):
        raise RuntimeError("SUPABASE_ADMIN_URL still contains a placeholder value.")
    if len(app_password) < 20 or any(ch in app_password for ch in "\r\n"):
        raise RuntimeError(
            "SUPABASE_APP_PASSWORD must be at least 20 characters with no newlines."
        )

    runtime_url = make_url(database_url(strict=True))
    migration_url = make_url(database_url(migration=True, strict=True))
    runtime_role = (runtime_url.username or "").split(".", 1)[0]
    if runtime_role != ROLE_NAME:
        raise RuntimeError(
            "SUPABASE_DATABASE_URL must authenticate as agrilink_app. For the "
            "shared pooler, the username is agrilink_app.PROJECT_REF."
        )
    if (migration_url.username or "").split(".", 1)[0] != ROLE_NAME:
        raise RuntimeError("SUPABASE_MIGRATION_URL must also authenticate as agrilink_app.")
    if runtime_url.password != app_password:
        raise RuntimeError(
            "SUPABASE_DATABASE_URL must contain the same percent-encoded password "
            "as SUPABASE_APP_PASSWORD."
        )

    schema = database_schema("supabase")
    with psycopg.connect(connection_info(admin_url), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            database_name = cursor.fetchone()[0]
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE_NAME,))
            if cursor.fetchone():
                cursor.execute(
                    sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER "
                            "NOCREATEDB NOCREATEROLE NOREPLICATION").format(
                        sql.Identifier(ROLE_NAME), sql.Literal(app_password)
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER "
                            "NOCREATEDB NOCREATEROLE NOREPLICATION").format(
                        sql.Identifier(ROLE_NAME), sql.Literal(app_password)
                    )
                )
            cursor.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}").format(
                    sql.Identifier(schema), sql.Identifier(ROLE_NAME)
                )
            )
            cursor.execute(
                sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(
                    sql.Identifier(schema), sql.Identifier(ROLE_NAME)
                )
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(
                    sql.Identifier(schema)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(ROLE_NAME)
                )
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name), sql.Identifier(ROLE_NAME)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path TO {}").format(
                    sql.Identifier(ROLE_NAME), sql.Identifier(schema)
                )
            )

    runtime_url_text = runtime_url.render_as_string(hide_password=False)
    verification_error: Exception | None = None
    for attempt in range(3):
        try:
            with psycopg.connect(connection_info(runtime_url_text), autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT current_user, current_schema(), ssl "
                        "FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
                    )
                    user, active_schema, ssl_enabled = cursor.fetchone()
                    if user != ROLE_NAME or active_schema != schema or not ssl_enabled:
                        raise RuntimeError(
                            "Supabase runtime role, schema, or TLS verification did not pass."
                        )
            verification_error = None
            break
        except Exception as exc:
            verification_error = exc
            if attempt < 2:
                time.sleep(2)
    if verification_error:
        raise verification_error

    print(f"Supabase role and private schema '{schema}' are ready.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Supabase bootstrap failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

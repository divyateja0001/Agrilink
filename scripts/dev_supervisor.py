from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import ssl
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
RUN_DIR = ROOT / ".run"
LOG_DIR = ROOT / "logs"
MANIFEST = RUN_DIR / "dev-processes.json"
STOP_REQUEST = RUN_DIR / "dev-stop.request"

sys.path.insert(0, str(BACKEND))
database_config_spec = importlib.util.spec_from_file_location(
    "agrilink_database_config", BACKEND / "app" / "database_config.py"
)
if database_config_spec is None or database_config_spec.loader is None:
    raise RuntimeError("Could not load AgriLink database configuration.")
database_config = importlib.util.module_from_spec(database_config_spec)
database_config_spec.loader.exec_module(database_config)
connect_args = database_config.connect_args
database_schema = database_config.database_schema
database_url = database_config.database_url


class PreflightError(RuntimeError):
    pass


def normalized_environment(target: str) -> dict[str, str]:
    # Windows environment names are case-insensitive, but some parent processes
    # can still supply both PATH and Path. Building one key per folded name avoids
    # the Start-Process dictionary collision that previously stopped AgriLink.
    folded: dict[str, tuple[str, str]] = {}
    for key, value in os.environ.items():
        canonical = "Path" if key.casefold() == "path" else key
        folded[key.casefold()] = (canonical, value)
    environment = {key: value for key, value in folded.values()}
    environment["AGRILINK_DATABASE_TARGET"] = target
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def pid_is_running(pid: int) -> bool:
    result = subprocess.run(
        ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.returncode == 0 and f'"{pid}"' in result.stdout


def check_manifest() -> None:
    if not MANIFEST.exists():
        return
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
        running = [p for p in data.get("processes", []) if pid_is_running(int(p["pid"]))]
    except (OSError, ValueError, KeyError, TypeError):
        raise PreflightError(
            ".run/dev-processes.json is invalid. Inspect it before removing it."
        )
    if running:
        details = ", ".join(f"{p['name']} PID {p['pid']}" for p in running)
        raise PreflightError(f"AgriLink is already running: {details}")
    MANIFEST.unlink()


def port_owner(port: int) -> str | None:
    result = subprocess.run(
        ["netstat.exe", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) >= 5 and columns[1].endswith(f":{port}") and columns[3] == "LISTENING":
            return columns[4]
    return None


def find_postgres_tool(name: str) -> str | None:
    located = shutil.which(name)
    if located:
        return located
    program_files = Path(os.getenv("ProgramFiles", r"C:\Program Files"))
    candidates = sorted(
        (program_files / "PostgreSQL").glob(f"*/bin/{name}.exe"), reverse=True
    )
    return str(candidates[0]) if candidates else None


def database_ready() -> tuple[bool, str]:
    try:
        engine = create_engine(
            database_url(strict=True),
            connect_args={**connect_args(database_schema()), "connect_timeout": 5},
            poolclass=NullPool,
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True, ""
    except Exception as exc:
        return False, str(exc).splitlines()[0]


def ensure_database(target: str) -> bool:
    ready, reason = database_ready()
    if ready:
        return False
    if target != "local":
        raise PreflightError(
            "Supabase is unreachable. Check internet access, the session-pooler URL, "
            f"password, TLS, and project status. Detail: {reason}"
        )

    data_dir = ROOT / ".pgdata"
    pg_ctl = find_postgres_tool("pg_ctl")
    if not data_dir.joinpath("PG_VERSION").exists() or not pg_ctl:
        raise PreflightError(
            "Local PostgreSQL is unreachable and no workspace .pgdata instance can be started. "
            f"Detail: {reason}"
        )
    server_log = data_dir / "server.log"
    result = subprocess.run(
        [pg_ctl, "-D", str(data_dir), "-l", str(server_log), "-o", "-h 127.0.0.1 -p 5432", "start"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PreflightError(
            "Workspace PostgreSQL failed to start. Inspect .pgdata/server.log. "
            + (result.stderr.strip() or result.stdout.strip())
        )
    for _ in range(15):
        ready, _ = database_ready()
        if ready:
            return True
        time.sleep(0.5)
    subprocess.run(
        [pg_ctl, "-D", str(data_dir), "stop", "-m", "fast"],
        check=False,
    )
    raise PreflightError("Workspace PostgreSQL started but did not become ready.")


def wait_for_url(url: str, seconds: int = 15, *, allow_self_signed: bool = False) -> None:
    deadline = time.monotonic() + seconds
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            context = ssl._create_unverified_context() if allow_self_signed else None
            with urllib.request.urlopen(url, timeout=2, context=context) as response:
                if 200 <= response.status < 300:
                    return
                last_error = f"HTTP {response.status}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise PreflightError(f"{url} did not become ready: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AgriLink local development services")
    parser.add_argument("--database", choices=("supabase", "local"), required=True)
    parser.add_argument("--skip-migration", action="store_true")
    parser.add_argument("--phone-https", action="store_true")
    parser.add_argument("--lan-address")
    parser.add_argument("--certificate")
    parser.add_argument("--certificate-key")
    args = parser.parse_args()
    os.environ["AGRILINK_DATABASE_TARGET"] = args.database
    environment = normalized_environment(args.database)
    if args.phone_https:
        if not args.lan_address:
            raise PreflightError("Phone HTTPS requires this laptop's private LAN IPv4 address.")
        for path in (args.certificate, args.certificate_key):
            if not path or not Path(path).is_file():
                raise PreflightError("Phone HTTPS certificate or key file is missing.")
        environment["AGRILINK_DEV_HOST"] = "0.0.0.0"
        environment["AGRILINK_HTTPS_CERT"] = str(Path(args.certificate).resolve())
        environment["AGRILINK_HTTPS_KEY"] = str(Path(args.certificate_key).resolve())

    python = ROOT / ".venv" / "Scripts" / "python.exe"
    node = shutil.which("node.exe")
    vite = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
    if not python.exists():
        raise PreflightError("Python venv missing. Create .venv and install backend requirements.")
    if not node:
        raise PreflightError("Node.js is missing. Install Node 22 LTS or newer.")
    if not vite.exists():
        raise PreflightError("Frontend dependencies are missing. Run npm.cmd ci in frontend.")

    RUN_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    STOP_REQUEST.unlink(missing_ok=True)
    check_manifest()
    for port in (5000, 5173):
        owner = port_owner(port)
        if owner:
            raise PreflightError(
                f"Port {port} is already owned by PID {owner}; no process was stopped."
            )

    database_started = ensure_database(args.database)
    processes: list[tuple[str, subprocess.Popen, object, object, Path]] = []
    pg_ctl = find_postgres_tool("pg_ctl")
    try:
        if not args.skip_migration:
            migration = subprocess.run(
                [str(python), "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND,
                env=environment,
                check=False,
            )
            if migration.returncode != 0:
                raise PreflightError("Database migration failed.")

        commands = [
            ("api", [str(python), "-m", "waitress", "--listen=127.0.0.1:5000", "wsgi:app"], BACKEND),
            ("worker", [str(python), "worker.py"], BACKEND),
            ("frontend", [node, str(vite), "--host", "0.0.0.0" if args.phone_https else "127.0.0.1"], FRONTEND),
        ]
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
        for name, command, cwd in commands:
            out_path = LOG_DIR / f"{name}.out.log"
            err_path = LOG_DIR / f"{name}.err.log"
            out_stream = out_path.open("w", encoding="utf-8")
            err_stream = err_path.open("w", encoding="utf-8")
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=environment,
                stdout=out_stream,
                stderr=err_stream,
                creationflags=creation_flags,
            )
            processes.append((name, process, out_stream, err_stream, err_path))

        manifest = {
            "workspace": str(ROOT),
            "database": args.database,
            "database_started": database_started,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "processes": [
                {
                    "pid": process.pid,
                    "name": name,
                    "process_name": Path(process.args[0]).stem,
                    "started_at_utc": datetime.now(timezone.utc).isoformat(),
                }
                for name, process, *_ in processes
            ],
        }
        MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        wait_for_url("http://127.0.0.1:5000/api/health")
        frontend_url = f"https://{args.lan_address}:5173" if args.phone_https else "http://127.0.0.1:5173"
        wait_for_url(frontend_url, allow_self_signed=args.phone_https)
        print(f"AgriLink is using {args.database} PostgreSQL.")
        print(f"UI  {frontend_url}" if args.phone_https else "UI  http://localhost:5173")
        print("API http://localhost:5000/api/health")
        print("Press Ctrl+C to stop only these AgriLink processes.")

        while True:
            if STOP_REQUEST.exists():
                print("Stop requested; shutting down AgriLink.")
                break
            for name, process, *_ in processes:
                if process.poll() is not None:
                    raise PreflightError(
                        f"{name} exited with code {process.returncode}. Inspect logs/{name}.err.log."
                    )
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping AgriLink...")
    finally:
        for _name, process, *_ in processes:
            if process.poll() is None:
                process.terminate()
        for _name, process, *_ in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        for _name, _process, out_stream, err_stream, _err_path in processes:
            out_stream.close()
            err_stream.close()
        MANIFEST.unlink(missing_ok=True)
        STOP_REQUEST.unlink(missing_ok=True)
        if database_started and pg_ctl:
            subprocess.run(
                [pg_ctl, "-D", str(ROOT / ".pgdata"), "stop", "-m", "fast"],
                check=False,
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightError as exc:
        print(f"AgriLink preflight: {exc}", file=sys.stderr)
        raise SystemExit(1)

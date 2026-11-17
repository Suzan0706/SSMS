"""Connect SSMS to an existing PostgreSQL database (for example smart_school_db made in pgAdmin) without losing data.

Run from ssms/api with the virtual environment active (Windows: ssms\\windows\\setup.bat does all of this):

    python scripts/setup_database.py --db smart_school_db
    python scripts/setup_database.py --db smart_school_db --demo                 # sample school, empty database only
    python scripts/setup_database.py --db smart_school_db --admin-email you@example.com

What it does, and what it never does:
  1. Asks for the postgres password (never written to disk) and checks it can connect.
  2. Refuses to touch a database that already holds tables from another program (no alembic_version table):
     it stops and explains, so nothing of yours is changed.
  3. Before upgrading a database that already has SSMS data, saves a pg_dump backup in ssms/backups/.
  4. Writes ssms/api/.env once with new secrets. If .env already exists only the database lines are updated:
     the encryption keys are kept, because encrypted phone numbers and NIDA numbers cannot be read without them.
  5. Runs the migrations (alembic upgrade head): they only add tables and columns, they never drop your data.
  6. Gives the runtime logins ssms_app and ssms_console their passwords, then signs in as ssms_app to check.
"""

import argparse
import base64
import getpass
import os
import secrets
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

import psycopg

API_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = API_DIR / ".env"
BACKUP_DIR = API_DIR.parent / "backups"
SEED_FILE = API_DIR.parents[1] / "design" / "sql" / "seed.sql"


def _key() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


def read_env() -> dict[str, str]:
    values = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip()
    return values


def write_env(updates: dict[str, str]) -> None:
    """Set the given lines in .env, keeping every other line (and its secrets) as it is."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.is_file() else []
    done = set()
    for i, line in enumerate(lines):
        name = line.split("=", 1)[0].strip()
        if name in updates and not line.lstrip().startswith("#"):
            lines[i] = f"{name}={updates[name]}"
            done.add(name)
    lines += [f"{name}={value}" for name, value in updates.items() if name not in done]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def new_env_secrets() -> dict[str, str]:
    """Secrets made once for this installation (development mode: plain http on this computer)."""
    return {
        "SSMS_ENVIRONMENT": "development",
        "SSMS_TASKS_INLINE": "true",
        "SSMS_COOKIE_SECURE": "false",
        "SSMS_JWT_SECRET": secrets.token_urlsafe(48),
        "SSMS_ENC_KEYS": f"1:{_key()}",
        "SSMS_ENC_ACTIVE_KEY_ID": "1",
        "SSMS_BLIND_INDEX_KEY": _key(),
        "SSMS_APP_DB_PASSWORD": secrets.token_hex(24),
        "SSMS_CONSOLE_DB_PASSWORD": secrets.token_hex(24),
        "SSMS_SMS_PROVIDER": "console",
        "SSMS_GEPG_MODE": "simulator",
        "SSMS_PUSH_PROVIDER": "console",
        "SSMS_EMAIL_PROVIDER": "console",
        "SSMS_STORAGE_DIR": "./storage",
    }


def find_pg_dump() -> str | None:
    found = shutil.which("pg_dump")
    if found:
        return found
    for version in ("18", "17", "16"):
        candidate = Path(rf"C:\Program Files\PostgreSQL\{version}\bin\pg_dump.exe")
        if candidate.is_file():
            return str(candidate)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default="smart_school_db", help="database name (default smart_school_db)")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default="5432")
    parser.add_argument("--admin-user", default="postgres", help="superuser, used only for setup and upgrades")
    parser.add_argument("--demo", action="store_true", help="load the sample school (only into an empty database)")
    parser.add_argument("--admin-email", help="also create a platform (super-admin console) account")
    parser.add_argument("--no-backup", action="store_true", help="skip the backup before an upgrade (not advised)")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or getpass.getpass(f"Password of PostgreSQL user '{args.admin_user}': ")
    admin_url = f"postgresql://{quote(args.admin_user, safe='')}:{quote(password, safe='')}@{args.host}:{args.port}"

    # 1. connect
    try:
        conn = psycopg.connect(f"{admin_url}/{args.db}", autocommit=True, connect_timeout=10)
    except psycopg.OperationalError as exc:
        sys.exit(
            f"Cannot connect to database '{args.db}' on {args.host}:{args.port}: {exc}\n"
            "Check that PostgreSQL is running, the database exists in pgAdmin and the password is right."
        )
    with conn:
        version = conn.execute("SHOW server_version").fetchone()[0]
        tables = conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchone()[0]
        has_alembic = conn.execute("SELECT to_regclass('public.alembic_version') IS NOT NULL").fetchone()[0]
        current = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] if has_alembic else None
    print(f"Connected: {args.db} on PostgreSQL {version} ({tables} tables, SSMS revision {current or 'none'})")
    if int(version.split(".")[0]) < 16:
        sys.exit("SSMS needs PostgreSQL 16 or newer.")

    # 2. never mix with another program's tables
    if tables and not has_alembic:
        sys.exit(
            f"'{args.db}' already has {tables} tables that were not made by SSMS (for example from db/schema.sql,"
            " the old single-school version). Nothing was changed.\nCreate a new empty database in pgAdmin for"
            " SSMS, or back this one up and empty it first."
        )
    if args.demo and tables:
        sys.exit("--demo loads sample data only into an empty database; this one already has SSMS tables.")

    # 3. backup before upgrading existing data
    if has_alembic and not args.no_backup:
        pg_dump = find_pg_dump()
        if pg_dump is None:
            sys.exit(
                "pg_dump was not found to back up the existing data first. Add PostgreSQL's bin folder to PATH"
                " (e.g. C:\\Program Files\\PostgreSQL\\18\\bin) or run again with --no-backup."
            )
        BACKUP_DIR.mkdir(exist_ok=True)
        target = BACKUP_DIR / f"{args.db}-before-upgrade-{current}-{date.today().isoformat()}.dump"
        subprocess.run(
            [pg_dump, "-Fc", "-h", args.host, "-p", args.port, "-U", args.admin_user, "-f", str(target), args.db],
            env={**os.environ, "PGPASSWORD": password},
            check=True,
        )
        print(f"Backup saved: {target}")

    # 4. .env (secrets made once, database lines always point at this database)
    env = read_env()
    updates = {} if env.get("SSMS_ENC_KEYS") else new_env_secrets()
    if env.get("SSMS_ENC_KEYS"):
        print(f"Keeping the secrets already in {ENV_FILE} (encrypted data depends on them).")
    for name in ("SSMS_APP_DB_PASSWORD", "SSMS_CONSOLE_DB_PASSWORD"):
        if not env.get(name) and name not in updates:
            updates[name] = secrets.token_hex(24)
    merged = {**env, **updates}
    where = f"{args.host}:{args.port}/{args.db}"
    updates["SSMS_DATABASE_URL"] = f"postgresql+psycopg://ssms_app:{merged['SSMS_APP_DB_PASSWORD']}@{where}"
    updates["SSMS_PLATFORM_DATABASE_URL"] = (
        f"postgresql+psycopg://ssms_console:{merged['SSMS_CONSOLE_DB_PASSWORD']}@{where}"
    )
    write_env(updates)
    merged.update(updates)
    print(f"Settings written: {ENV_FILE}")

    # 5. migrations, 6. logins: run with the superuser URL in the environment only (never saved)
    child_env = {
        **os.environ,
        **merged,
        "SSMS_MIGRATION_DATABASE_URL": f"{admin_url.replace('postgresql://', 'postgresql+psycopg://')}/{args.db}",
    }
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=child_env, check=True)
    subprocess.run([sys.executable, "-m", "app.cli", "db-logins"], cwd=API_DIR, env=child_env, check=True)

    if args.demo:
        with psycopg.connect(f"{admin_url}/{args.db}", autocommit=True) as conn:
            conn.execute(SEED_FILE.read_text(encoding="utf-8"))
        print("Sample school loaded: school code mfano-sec, user admin, password Mfano@2026")

    if args.admin_email:
        subprocess.run(
            [sys.executable, "-m", "app.cli", "create-platform-admin", "--email", args.admin_email, "--name", "Admin"],
            cwd=API_DIR,
            env=child_env,
            check=True,
        )

    # check the runtime login the API will use
    runtime = merged["SSMS_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(runtime, connect_timeout=10) as conn:
        user, can_read = conn.execute("SELECT current_user, has_table_privilege('students', 'SELECT')").fetchone()
    with psycopg.connect(f"{admin_url}/{args.db}") as conn:
        revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        schools = conn.execute("SELECT count(*) FROM schools").fetchone()[0]
    if not can_read:
        sys.exit(f"Signed in as {user} but it cannot read the SSMS tables: run this script again.")
    print(
        f"\nDone. {args.db} is at SSMS revision {revision} with {schools} school(s); the API signs in as {user}."
        "\nStart it with: python scripts/run_api.py"
    )


if __name__ == "__main__":
    main()

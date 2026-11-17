"""Operator commands.

python -m app.cli db-logins
    After migrations: give ssms_app its password (SSMS_APP_DB_PASSWORD) and create the console login
    ssms_console (SSMS_CONSOLE_DB_PASSWORD, member of ssms_platform, NOINHERIT). Uses the migration URL.
python -m app.cli create-platform-admin --email ops@example.co.tz --name "Operations"
    The password is read from SSMS_NEW_ADMIN_PASSWORD or prompted. The TOTP provisioning URI is printed once
    for the operator to add to an authenticator app; it is not stored in clear anywhere.
python -m app.cli deploy-check
    After installing or upgrading: file storage round trip (creates the S3 bucket if missing) and, when a scanner
    is configured, that it catches the EICAR test string. Exits non-zero on any failure.
"""

import argparse
import asyncio
import contextlib
import getpass
import os
import sys
import uuid

import psycopg
from psycopg import sql

from app.core import scanner
from app.core.config import get_settings
from app.core.security import is_strong_password
from app.db.session import provider
from app.services import platform


async def _create_admin(email: str, name: str) -> None:
    password = os.environ.get("SSMS_NEW_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if not is_strong_password(password):
        sys.exit("Password must have 10+ characters with letters and digits.")
    async with provider.platform() as session:
        admin, uri = await platform.create_admin(session, name, email, password)
    print(f"Created platform admin {admin.id}. Add this to an authenticator app now (shown once):\n{uri}")


def _db_logins() -> None:
    app_password = os.environ.get("SSMS_APP_DB_PASSWORD")
    console_password = os.environ.get("SSMS_CONSOLE_DB_PASSWORD")
    if not app_password or not console_password:
        sys.exit("Set SSMS_APP_DB_PASSWORD and SSMS_CONSOLE_DB_PASSWORD.")
    url = get_settings().migration_database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("ALTER ROLE ssms_app WITH LOGIN PASSWORD {}").format(sql.Literal(app_password)))
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'ssms_console'").fetchone()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(
            sql.SQL(verb + " ROLE ssms_console WITH LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS PASSWORD {}").format(
                sql.Literal(console_password)
            )
        )
        conn.execute("GRANT ssms_platform TO ssms_console")
    print("Database logins ready: ssms_app, ssms_console.")


EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


async def _deploy_check() -> None:
    from app.core.storage import S3Storage, get_storage

    s, failures = get_settings(), []
    storage = get_storage()
    if isinstance(storage, S3Storage):
        errors = storage.client.exceptions
        with contextlib.suppress(errors.BucketAlreadyOwnedByYou, errors.BucketAlreadyExists):
            storage.client.create_bucket(Bucket=s.s3_bucket)
    key = f"deploy-check/{uuid.uuid4().hex}.txt"
    try:
        storage.put(key, b"ok")
        assert storage.get(key) == b"ok"
        storage.delete(key)
        print(f"storage ({s.storage_backend}): ok")
    except Exception as exc:  # report every check, then fail
        failures.append(f"storage ({s.storage_backend}): {type(exc).__name__}")
    if scanner.configured():
        try:
            clean, infected = await scanner.scan(b"plain text"), await scanner.scan(EICAR)
            if clean[0] != "CLEAN" or infected[0] != "INFECTED":
                failures.append(f"scanner: clean={clean[0]} eicar={infected[0]}")
            else:
                print(f"scanner: ok (EICAR caught as {infected[1]})")
        except scanner.ScannerUnavailable as exc:
            failures.append(f"scanner: unavailable ({exc})")
    else:
        print("scanner: not configured" + (" (allowed)" if s.allow_unscanned_uploads else ""))
    if failures:
        sys.exit("deploy-check failed: " + "; ".join(failures))
    print("deploy-check passed")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-platform-admin")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    commands.add_parser("db-logins")
    commands.add_parser("deploy-check")
    args = parser.parse_args()
    if args.command == "db-logins":
        _db_logins()
        return
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if args.command == "create-platform-admin":
        asyncio.run(_create_admin(args.email, args.name))
    if args.command == "deploy-check":
        asyncio.run(_deploy_check())


if __name__ == "__main__":
    main()

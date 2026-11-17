"""Alembic environment. Migrations are raw SQL files executed by the migration role; the SQL itself
switches to ssms_owner (SET ROLE) so every object is owned by ssms_owner, not by the migration login."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings


def run_migrations_online() -> None:
    engine = create_engine(get_settings().migration_database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline mode is not supported: the migrations are SQL files, read them directly.")
run_migrations_online()

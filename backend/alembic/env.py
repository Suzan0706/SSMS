from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import create_engine

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.config import get_settings
from app.db import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # Views are mapped as Tables for querying but are created by migrations, not autogenerate.
    if type_ == "table" and obj.info.get("is_view"):
        return False
    # The database is defined by db/schema.sql; objects the ORM does not map (results, attendance,
    # expression indexes, triggers ...) are not drift.
    if reflected and compare_to is None:
        return False
    return True


def compare_type(ctx, inspected_column, metadata_column, inspected_type, metadata_type):
    # Python enums are stored as VARCHAR + CHECK (see schema.sql), not as native ENUM types.
    if isinstance(metadata_type, sa.Enum) and isinstance(inspected_type, sa.String):
        return False
    return None                                   # default comparison for everything else


def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          include_object=include_object, compare_type=compare_type)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()

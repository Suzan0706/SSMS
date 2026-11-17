"""Regions and districts as reference tables; room equipment as searchable rows (both backfilled from the old text).

Revision ID: 0010_locations_equipment
Revises: 0009_normalisation
"""

from migrations.sqlfile import run_sql_file

revision = "0010_locations_equipment"
down_revision = "0009_normalisation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0010_locations_equipment.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

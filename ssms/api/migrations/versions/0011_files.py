"""Uploaded files: one stored_files row per file, the only way to reach its bytes (design/20 §20.3, NFR-16).

Revision ID: 0011_files
Revises: 0010_locations_equipment
"""

from migrations.sqlfile import run_sql_file

revision = "0011_files"
down_revision = "0010_locations_equipment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0011_files.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

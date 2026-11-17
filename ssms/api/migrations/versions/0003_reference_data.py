"""Reference data: system roles, permissions, default role -> permission map.

Revision ID: 0003_reference_data
Revises: 0002_phase1
"""

from migrations.sqlfile import run_sql_file

revision = "0003_reference_data"
down_revision = "0002_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0003_reference_data.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

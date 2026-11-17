"""Phase 1: admission number prefix per school, CHECKs on student status history, quieter row audit.

Revision ID: 0002_phase1
Revises: 0001_baseline
"""

from migrations.sqlfile import run_sql_file

revision = "0002_phase1"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0002_phase1.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

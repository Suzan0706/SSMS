"""Phase 2: soft delete for combination subjects; results_scope ignores removed ones.

Revision ID: 0004_phase2
Revises: 0003_reference_data
"""

from migrations.sqlfile import run_sql_file

revision = "0004_phase2"
down_revision = "0003_reference_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0004_phase2.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

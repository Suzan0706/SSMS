"""Phase 5: audit on facilities, memberships and library tables; index for overdue loans.

Revision ID: 0007_phase5
Revises: 0006_phase4
"""

from migrations.sqlfile import run_sql_file

revision = "0007_phase5"
down_revision = "0006_phase4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0007_phase5.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

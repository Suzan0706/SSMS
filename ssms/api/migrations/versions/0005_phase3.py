"""Phase 3: payment reversal requests (maker-checker before payment_reversals); journals.source_type width.

Revision ID: 0005_phase3
Revises: 0004_phase2
"""

from migrations.sqlfile import run_sql_file

revision = "0005_phase3"
down_revision = "0004_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0005_phase3.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

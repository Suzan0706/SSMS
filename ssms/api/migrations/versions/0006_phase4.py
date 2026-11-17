"""Phase 4: SMS delivery-report resolver, audit on devices, cards, announcements and templates; append-only credit.

Revision ID: 0006_phase4
Revises: 0005_phase3
"""

from migrations.sqlfile import run_sql_file

revision = "0006_phase4"
down_revision = "0005_phase3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0006_phase4.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

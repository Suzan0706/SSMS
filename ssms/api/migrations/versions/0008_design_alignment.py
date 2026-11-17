"""Design alignment: Registrar role; subjects each teacher is qualified to teach (backfilled from current teaching).

Revision ID: 0008_design_alignment
Revises: 0007_phase5
"""

from migrations.sqlfile import run_sql_file

revision = "0008_design_alignment"
down_revision = "0007_phase5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0008_design_alignment.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

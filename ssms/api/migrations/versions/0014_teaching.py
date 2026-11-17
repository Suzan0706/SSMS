"""Study materials and homework with submissions (FR-90 .. FR-93).

Revision ID: 0014_teaching
Revises: 0013_front_office_staff
"""

from migrations.sqlfile import run_sql_file

revision = "0014_teaching"
down_revision = "0013_front_office_staff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0014_teaching.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

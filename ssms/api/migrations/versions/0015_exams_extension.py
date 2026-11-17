"""Exam candidate numbers for admit cards (FR-85).

Revision ID: 0015_exams_extension
Revises: 0014_teaching
"""

from migrations.sqlfile import run_sql_file

revision = "0015_exams_extension"
down_revision = "0014_teaching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0015_exams_extension.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

"""Phase 0 baseline: roles, 99 tables, RLS, triggers, functions, resolvers, grants (design/sql/schema.sql).

Revision ID: 0001_baseline
Revises:
"""

from migrations.sqlfile import run_sql_file

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0001_baseline.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

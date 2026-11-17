"""Normalisation: drop derivable columns; composite foreign keys tie the remaining copies to their source.

Revision ID: 0009_normalisation
Revises: 0008_design_alignment
"""

from migrations.sqlfile import run_sql_file

revision = "0009_normalisation"
down_revision = "0008_design_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0009_normalisation.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

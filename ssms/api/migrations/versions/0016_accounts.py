"""Other income and expenses on the double-entry ledger, and fines (FR-87, FR-88, FR-89).

Revision ID: 0016_accounts
Revises: 0015_exams_extension
"""

from migrations.sqlfile import run_sql_file

revision = "0016_accounts"
down_revision = "0015_exams_extension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0016_accounts.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

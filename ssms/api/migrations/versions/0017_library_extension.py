"""Library categories, publishers and cards; card numbering (FR-96, FR-97).

Revision ID: 0017_library_extension
Revises: 0016_accounts
"""

from migrations.sqlfile import run_sql_file

revision = "0017_library_extension"
down_revision = "0016_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0017_library_extension.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

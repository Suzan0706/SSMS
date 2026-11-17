"""Library copies connected to books and loans: copy belongs to the loan's book, copies follow the book count.

Revision ID: 0020_library_copy_link
Revises: 0019_library_circulation
"""

from migrations.sqlfile import run_sql_file

revision = "0020_library_copy_link"
down_revision = "0019_library_circulation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0020_library_copy_link.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

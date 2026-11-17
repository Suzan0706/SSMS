"""Library circulation: physical copies with accession numbers, loans of copies, borrowing rules per school.

Revision ID: 0019_library_circulation
Revises: 0018_documents_email
"""

from migrations.sqlfile import run_sql_file

revision = "0019_library_circulation"
down_revision = "0018_documents_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0019_library_circulation.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

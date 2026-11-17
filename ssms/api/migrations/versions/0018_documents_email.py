"""Certificates, ID cards, the email channel and staff photographs (FR-78, FR-94, FR-95, FR-98).

Revision ID: 0018_documents_email
Revises: 0017_library_extension
"""

from migrations.sqlfile import run_sql_file

revision = "0018_documents_email"
down_revision = "0017_library_extension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0018_documents_email.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

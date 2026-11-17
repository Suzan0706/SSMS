"""Receptionist role and the permissions of the extension (design/20 §20.2, FR-76).

Revision ID: 0012_roles_extension
Revises: 0011_files
"""

from migrations.sqlfile import run_sql_file

revision = "0012_roles_extension"
down_revision = "0011_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0012_roles_extension.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

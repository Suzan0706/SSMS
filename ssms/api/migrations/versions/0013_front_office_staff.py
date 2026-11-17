"""Front office (admission inquiries, school calendar) and staff attendance and leave (FR-77, FR-80, FR-81, FR-99).

Revision ID: 0013_front_office_staff
Revises: 0012_roles_extension
"""

from migrations.sqlfile import run_sql_file

revision = "0013_front_office_staff"
down_revision = "0012_roles_extension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0013_front_office_staff.sql")


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")

"""Baseline schema from db/schema.sql

The baseline is the hand-written DDL because it contains things autogenerate cannot express:
EXCLUDE constraints, a custom range type, triggers and views. Later migrations are normal
Alembic revisions (autogenerate + review).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-22
"""
from pathlib import Path

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = Path(__file__).resolve().parents[3] / "db" / "schema.sql"


def upgrade() -> None:
    # Run the whole script through the driver (it contains $$-quoted function bodies).
    raw = op.get_bind().connection.dbapi_connection
    with raw.cursor() as cur:
        cur.execute(SCHEMA.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")

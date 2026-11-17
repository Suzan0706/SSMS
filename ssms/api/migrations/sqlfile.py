"""Run a SQL file through the raw psycopg connection (no SQLAlchemy parameter parsing, multi-statement)."""

from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).parent / "sql"
# The Phase 0 baseline is kept in one place: design/sql/schema.sql. The Docker build copies it to
# migrations/sql/0001_baseline.sql; in a source checkout it is read from the design folder.
_HERE = Path(__file__).resolve()
BASELINE_CANDIDATES = (SQL_DIR / "0001_baseline.sql",) + (
    # only in a source checkout (ssms/api/migrations); the image is /app/migrations, which has no such parent
    (_HERE.parents[3] / "design" / "sql" / "schema.sql",) if len(_HERE.parents) > 3 else ()
)


def resolve(name: str) -> Path:
    if name == "0001_baseline.sql":
        for candidate in BASELINE_CANDIDATES:
            if candidate.is_file():
                return candidate
        raise FileNotFoundError("design/sql/schema.sql not found (copy it to migrations/sql/0001_baseline.sql)")
    return SQL_DIR / name


def run_sql_file(name: str) -> None:
    sql = resolve(name).read_text(encoding="utf-8")
    op.get_bind().connection.driver_connection.execute(sql)

"""The database is the source of truth: models must match it, and the Phase 0 SQL tests must still pass."""

import re

import psycopg
import pytest
from sqlalchemy import Enum

import app.models  # noqa: F401  (registers every model)
from app.db.base import Base
from tests.conftest import REPO, TESTER_URL

SQL_TESTS = sorted((REPO / "design" / "sql" / "tests").glob("*.sql"))


def _connect():
    return psycopg.connect(TESTER_URL.replace("postgresql+psycopg://", "postgresql://"), autocommit=True)


@pytest.fixture(scope="module")
def catalog(database):
    with _connect() as conn:
        conn.execute("SET ROLE ssms_platform")  # the console role can see every table, incl. platform_admins
        columns = conn.execute("""SELECT table_name, column_name, is_nullable = 'YES', character_maximum_length,
                                         column_default IS NOT NULL
                                  FROM information_schema.columns WHERE table_schema = 'public'""").fetchall()
        checks = conn.execute("""SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint
                                 WHERE contype = 'c' AND connamespace = 'public'::regnamespace""").fetchall()
    tables: dict[str, dict] = {}
    for table, column, nullable, length, has_default in columns:
        tables.setdefault(table, {})[column] = (nullable, length, has_default)
    return tables, checks


def test_runtime_role_cannot_see_platform_admins(database):
    with _connect() as conn:
        conn.execute("SET ROLE ssms_app")
        visible = conn.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'platform_admins'"
        ).fetchone()[0]
        assert visible == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT id FROM platform_admins")


def test_models_match_database_columns(catalog):
    tables, _ = catalog
    problems = []
    for table in Base.metadata.sorted_tables:
        db = tables.get(table.name)
        if db is None:
            problems.append(f"{table.name}: table missing")
            continue
        for column in table.columns:
            if column.name not in db:
                problems.append(f"{table.name}.{column.name}: not in database")
                continue
            nullable, length, _ = db[column.name]
            if column.nullable != nullable:
                problems.append(f"{table.name}.{column.name}: nullable model={column.nullable} db={nullable}")
            model_length = None if isinstance(column.type, Enum) else getattr(column.type, "length", None)
            if length and model_length and length != model_length:
                problems.append(f"{table.name}.{column.name}: length model={model_length} db={length}")
        for name, (nullable, _, has_default) in db.items():
            if name not in table.columns and not nullable and not has_default:
                problems.append(f"{table.name}.{name}: NOT NULL without default but not mapped")
    assert problems == []


def test_enum_values_match_check_constraints(catalog):
    _, checks = catalog
    problems = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if not isinstance(column.type, Enum):
                continue
            found = next(
                (
                    set(re.findall(r"'([^']*)'::", d))
                    for t, d in checks
                    if t == table.name and re.search(rf"\(?\b{column.name}\b\)?(::text)? = ANY", d)
                ),
                None,
            )
            if found != set(column.type.enums):
                problems.append(f"{table.name}.{column.name}: model={sorted(column.type.enums)} db={found}")
    assert problems == []


@pytest.mark.parametrize("path", SQL_TESTS, ids=lambda p: p.name)
def test_phase0_sql_suite_runs_as_ssms_app(database, path):
    """design/sql/tests/*.sql: each file does SET ROLE ssms_app itself and rolls everything back."""
    notices: list[str] = []
    with _connect() as conn:
        conn.add_notice_handler(lambda diag: notices.append(diag.message_primary or ""))
        conn.execute(path.read_text(encoding="utf-8"))
    passed = [n for n in notices if n.startswith("PASS")]
    expected = path.read_text(encoding="utf-8").count("-- TEST ")
    assert len(passed) == expected, [n for n in notices if not n.startswith("PASS")]

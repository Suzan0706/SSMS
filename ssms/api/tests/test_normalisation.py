"""Keeps the schema in 3NF: a new redundant column fails here until it is removed or justified (06-data-model §6.5)."""

import re

import psycopg
import pytest

from tests.conftest import TESTER_URL
from tests.helpers import SCHOOL_A, TERM1, bearer, login, u

API = "/api/v1"

# (table, via, column): table.via leads to a parent that also holds what table.column points at.
ALLOWED_PATHS = {
    ("homework_submissions", "homework_id", "file_id"): "the student's answer, not the teacher's attachment",
    ("homework_submissions", "homework_id", "marked_by"): "who marked it; may differ from who set the homework",
    (
        "admission_inquiries",
        "application_id",
        "class_id",
    ): "class first asked about; the application may be for another",
    ("announcements", "stream_id", "class_id"): "ck_ann_audience: a row targets a class or a stream, never both",
    ("attendance_sessions", "timetable_slot_id", "stream_id"): "ck_as_scope: a lesson has a slot, a register a stream",
    ("classes", "next_class_id", "education_level_id"): "the next class may be in another level (Form IV to Form V)",
    ("enrolment_requirements", "class_id", "education_level_id"): "ck_er_scope: a level or a class, never both",
    ("mark_entries", "component_id", "subject_id"): "a component can apply to every subject (its subject_id is NULL)",
    ("published_results", "amendment_id", "supersedes_id"): "frozen legal record, versioned through amendments",
    ("published_results", "supersedes_id", "amendment_id"): "frozen legal record, versioned through amendments",
    ("published_results", "supersedes_id", "enrolment_id"): "frozen legal record, versioned through amendments",
    ("published_results", "supersedes_id", "publication_id"): "frozen legal record, versioned through amendments",
    ("published_results", "supersedes_id", "subject_id"): "frozen legal record, versioned through amendments",
    ("student_term_summaries", "supersedes_id", "enrolment_id"): "frozen legal record, versioned through amendments",
    ("student_term_summaries", "supersedes_id", "publication_id"): "frozen legal record, versioned through amendments",
    ("timetable_slots", "stream_id", "room_id"): "a lesson can be in a lab or hall, not only the stream's home room",
}

# Columns whose names suggest a stored calculation.
ALLOWED_DERIVED = {
    ("background_jobs", "error_count"): "progress of a running job",
    ("background_jobs", "total_items"): "progress of a running job",
    ("invoices", "total_tzs"): "recomputed by trg_invoices_derive on every write; direct overwrites are ignored",
    ("invoices", "paid_tzs"): "recomputed by trg_invoices_derive on every write; direct overwrites are ignored",
    ("invoices", "balance_tzs"): "generated column: total_tzs - paid_tzs",
    ("reconciliation_runs", "statement_total_tzs"): "the total of the statement as received",
    ("reconciliation_runs", "system_total_tzs"): "what the system held when the run was made; payments change later",
    ("student_term_summaries", "total_score"): "frozen legal record as published",
    ("student_term_summaries", "average_score"): "frozen legal record as published",
    ("student_term_summaries", "total_points"): "frozen legal record as published",
    ("users", "failed_login_count"): "lockout counter, not derived from other rows",
    ("venues", "total_seats"): "a fact about the venue, not a calculation",
}

DERIVED_NAME = re.compile(r"(^|_)(total|count|balance|average|avg|sum|paid)(_|$)", re.IGNORECASE)


def _connect():
    return psycopg.connect(TESTER_URL.replace("postgresql+psycopg://", "postgresql://"))


def _foreign_keys(conn) -> list[tuple[str, str, list[str]]]:
    rows = conn.execute("""
        SELECT c.conrelid::regclass::text, c.confrelid::regclass::text,
               array_agg(a.attname::text ORDER BY k.ord)
        FROM pg_constraint c
        CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace AND a.attname <> 'school_id'
        GROUP BY c.oid""").fetchall()
    return [(table, parent, columns) for table, parent, columns in rows]


def transitive_paths(keys: list[tuple[str, str, list[str]]]) -> set[tuple[str, str, str]]:
    """Single-column links only: a composite key already makes the database check that both sides agree."""
    single = [(t, p, c[0]) for t, p, c in keys if len(c) == 1 and p != "users"]
    found = set()
    for table, parent, via in single:
        for owner, target, _ in single:
            if owner != parent:
                continue
            for other_table, other_target, column in single:
                if other_table == table and other_target == target and column != via:
                    found.add((table, via, column))
    return found


@pytest.fixture(scope="module")
def conn(database):
    with _connect() as connection:
        connection.execute("SET ROLE ssms_platform")
        yield connection
        connection.rollback()


def test_no_new_transitive_dependency(conn):
    found = transitive_paths(_foreign_keys(conn))
    assert found - ALLOWED_PATHS.keys() == set(), "redundant column: derive it, use a composite key, or justify it"
    assert ALLOWED_PATHS.keys() - found == set(), "stale entry: remove it from ALLOWED_PATHS"


def test_no_new_stored_calculation(conn):
    rows = conn.execute("""
        SELECT c.table_name, c.column_name FROM information_schema.columns c
        JOIN information_schema.tables t USING (table_schema, table_name)
        WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'""").fetchall()
    found = {(t, c) for t, c in rows if DERIVED_NAME.search(c)}
    assert found - ALLOWED_DERIVED.keys() == set(), "stored calculation: use a view, or justify it"
    assert ALLOWED_DERIVED.keys() - found == set(), "stale entry: remove it from ALLOWED_DERIVED"


def test_redundant_columns_are_gone(conn):
    gone = conn.execute("""
        SELECT table_name, column_name FROM information_schema.columns
        WHERE (table_name, column_name) IN (('transport_assignments', 'route_id'),
                                            ('reconciliation_runs', 'matched_count'),
                                            ('reconciliation_runs', 'exception_count'))""").fetchall()
    assert gone == []


@pytest.mark.parametrize(
    "statement",
    [
        # A lesson's stream comes from its slot.
        """INSERT INTO attendance_sessions (school_id, session_date, kind, stream_id, timetable_slot_id)
           SELECT school_id, DATE '2026-03-03', 'LESSON', stream_id, id FROM timetable_slots LIMIT 1""",
        # A requirement names the level or the class.
        """INSERT INTO enrolment_requirements (school_id, education_level_id, class_id, name_en, name_sw)
           SELECT school_id, education_level_id, id, 'Both', 'Zote' FROM classes LIMIT 1""",
    ],
)
def test_redundant_values_are_refused(database, statement):
    with _connect() as connection:
        connection.execute("SET ROLE ssms_app")
        connection.execute(f"SET LOCAL app.school_id = '{SCHOOL_A}'")
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(statement)
        connection.rollback()


def test_copies_must_agree_with_their_source(database):
    """An enrolment cannot point at another student's application: the composite key refuses it."""
    with _connect() as connection:
        connection.execute("SET ROLE ssms_app")
        connection.execute(f"SET LOCAL app.school_id = '{SCHOOL_A}'")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute("""
                UPDATE enrolments e SET application_id = a.id
                FROM enrolment_applications a
                WHERE a.student_id <> e.student_id AND a.academic_year_id = e.academic_year_id""")
        connection.rollback()


async def test_requirement_cannot_name_level_and_class(client):
    admin = bearer(await login(client))
    response = await client.post(
        f"{API}/enrolment-requirements",
        headers=admin,
        json={"education_level_id": str(u(11, 1)), "class_id": str(u(16, 1)), "name_en": "Both", "name_sw": "Zote"},
    )
    assert response.status_code == 422


async def test_route_comes_from_the_stop(client):
    admin = bearer(await login(client))
    rows = (await client.get(f"{API}/transport-assignments?term_id={TERM1}", headers=admin)).json()
    assert rows and rows[0]["route_id"] == str(u(45, 1))
    filtered = f"{API}/transport-assignments?term_id={TERM1}&route_id="
    assert (await client.get(filtered + str(u(45, 1)), headers=admin)).json()
    assert (await client.get(filtered + str(u(45, 999)), headers=admin)).json() == []


async def test_reconciliation_counts_come_from_the_items(client):
    bursar = bearer(await login(client, username="bursar"))
    [run] = [
        r
        for r in (await client.get(f"{API}/reconciliation-runs", headers=bursar)).json()
        if r["run_date"] == "2026-01-31"
    ]
    assert run["matched_count"] == 2 and run["exception_count"] == 0

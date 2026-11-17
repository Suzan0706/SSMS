"""EXPLAIN ANALYZE the hot queries as the runtime role (ssms_app) under RLS, for one school of a synthetic database.

    python scripts/explain.py postgresql://ssms_tester@localhost:55433/ssms_perf [school_code]

The login must be a member of ssms_app without privileges of its own (as in the tests). Each query reports execution
time and every sequential scan on a table with more than 5,000 rows, which is what NFR-05 forbids on hot paths.
"""

import json
import sys

import psycopg

URL = sys.argv[1]
SCHOOL = sys.argv[2] if len(sys.argv) > 2 else "synth-1"

QUERIES = {
    "student search (prefix)": (
        "SELECT st.id, st.admission_no, u.first_name, u.last_name FROM students st JOIN users u ON u.id = st.user_id "
        "WHERE st.deleted_at IS NULL AND (st.admission_no ILIKE :q OR u.last_name ILIKE :q OR u.first_name ILIKE :q) "
        "ORDER BY lower(u.last_name), lower(u.first_name), st.id LIMIT 50"
    ),
    "register: class list": (
        "SELECT st.id, st.admission_no, u.first_name, u.last_name FROM students st JOIN enrolments e ON e.student_id "
        "= st.id "
        "JOIN users u ON u.id = st.user_id WHERE e.stream_id = :stream AND e.academic_year_id = :year "
        "AND e.status = 'ACTIVE' ORDER BY u.last_name, u.first_name"
    ),
    "register: marks of the day": (
        "SELECT r.student_id, r.status FROM attendance_records r JOIN attendance_sessions s ON s.id = r.session_id "
        "WHERE s.session_date = :day AND s.kind = 'REGISTER' AND s.stream_id = :stream"
    ),
    "parent: children": (
        "SELECT st.id, c.code, s.name FROM students st JOIN student_guardians sg ON sg.student_id = st.id "
        "AND sg.deleted_at IS NULL JOIN guardians g ON g.id = sg.guardian_id "
        "LEFT JOIN enrolments e ON e.student_id = st.id AND e.status = 'ACTIVE' "
        "LEFT JOIN streams s ON s.id = e.stream_id LEFT JOIN classes c ON c.id = s.class_id WHERE g.user_id = "
        ":guardian_user"
    ),
    "fee position of one student": (
        "SELECT outstanding_tzs, credit_tzs FROM v_student_fee_position WHERE student_id = :student"
    ),
    "statement: invoices + payments": (
        "SELECT i.invoice_no, i.balance_tzs FROM invoices i WHERE i.student_id = :student AND i.cancelled_at IS NULL "
        "UNION ALL SELECT p.external_ref, p.amount_tzs FROM payments p WHERE p.student_id = :student"
    ),
    "invoice list (term)": (
        "SELECT i.id, i.invoice_no, i.balance_tzs FROM invoices i WHERE i.term_id = :term AND i.cancelled_at IS NULL "
        "ORDER BY i.invoice_no LIMIT 50"
    ),
    "absence alert candidates": (
        "SELECT r.student_id FROM attendance_records r JOIN attendance_sessions s ON s.id = r.session_id "
        "WHERE s.session_date = :day AND s.kind = 'REGISTER' AND r.status = 'ABSENT' AND NOT EXISTS "
        "(SELECT 1 FROM absence_alerts a WHERE a.student_id = r.student_id AND a.absence_date = :day)"
    ),
    "stream attendance report (month)": (
        "SELECT r.student_id, r.status, count(*) FROM attendance_records r WHERE r.session_id IN "
        "(SELECT id FROM attendance_sessions WHERE stream_id = :stream AND kind = 'REGISTER' "
        "AND session_date BETWEEN :day AND :day + 30) GROUP BY r.student_id, r.status"
    ),
    "student attendance (portal month)": (
        "SELECT s.session_date, r.status FROM attendance_records r JOIN attendance_sessions s ON s.id = r.session_id "
        "WHERE r.student_id = :student AND s.session_date BETWEEN :day AND :day + 30"
    ),
    "chronic absence (week)": (
        "SELECT ar.student_id, count(DISTINCT a.session_date) FROM attendance_records ar JOIN attendance_sessions a "
        "ON a.id = ar.session_id WHERE ar.status = 'ABSENT' AND a.kind = 'REGISTER' "
        "AND a.session_date BETWEEN :day AND :day + 6 GROUP BY ar.student_id HAVING count(DISTINCT a.session_date) >= 3"
    ),
    "dashboard: attendance today": (
        "SELECT count(DISTINCT s.stream_id), count(r.id) FROM attendance_sessions s "
        "LEFT JOIN attendance_records r ON r.session_id = s.id WHERE s.session_date = :day AND s.kind = 'REGISTER'"
    ),
    "dashboard: outstanding total": (
        "SELECT coalesce(sum(outstanding_tzs), 0), count(*) FILTER (WHERE outstanding_tzs > 0) FROM "
        "v_student_fee_position"
    ),
    "dashboard: collections 30 days": (
        "SELECT (received_at AT TIME ZONE 'Africa/Dar_es_Salaam')::date, sum(amount_tzs) FROM payments "
        "WHERE status = 'CONFIRMED' AND received_at >= CAST(:day AS date) - 30 GROUP BY 1"
    ),
}


def walk(plan: dict, found: list) -> None:
    if plan.get("Node Type") == "Seq Scan" and plan.get("Plan Rows", 0) + plan.get("Actual Rows", 0) >= 0:
        found.append((plan.get("Relation Name"), plan.get("Actual Rows"), plan.get("Rows Removed by Filter", 0)))
    for child in plan.get("Plans", []):
        walk(child, found)


def main() -> None:
    with psycopg.connect(URL, autocommit=False) as conn:
        cur = conn.cursor()
        cur.execute("SET ROLE ssms_app")
        cur.execute("SELECT * FROM resolve_school_by_code(%s)", (SCHOOL,))
        school = cur.fetchone()[0]
        cur.execute("SELECT set_config('app.school_id', %s, false)", (str(school),))
        cur.execute("SELECT id FROM academic_years WHERE is_current")
        year = cur.fetchone()[0]
        cur.execute("SELECT id FROM terms WHERE term_no = 1")
        term = cur.fetchone()[0]
        cur.execute("SELECT stream_id, session_date FROM attendance_sessions ORDER BY session_date, stream_id LIMIT 1")
        stream, day = cur.fetchone()
        cur.execute(
            "SELECT st.id, g.user_id FROM students st JOIN student_guardians sg ON sg.student_id = st.id "
            "JOIN guardians g ON g.id = sg.guardian_id ORDER BY st.admission_no OFFSET 700 LIMIT 1"
        )
        student, guardian_user = cur.fetchone()
        cur.execute("SELECT count(*) FROM students")
        print(f"school {SCHOOL}: {cur.fetchone()[0]} students visible under RLS")
        params = {
            "q": "Familia4%",
            "stream": stream,
            "year": year,
            "day": day,
            "guardian_user": guardian_user,
            "student": student,
            "term": term,
        }
        slow = 0
        for name, sql in QUERIES.items():
            psql = sql
            for key in sorted(params, key=len, reverse=True):
                psql = psql.replace(f":{key}", f"%({key})s")
            cur.execute(psql, params)  # warm the cache: report steady-state times
            cur.fetchall()
            cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + psql, params)
            plan = cur.fetchone()[0][0]
            found: list = []
            walk(plan["Plan"], found)
            big = [f for f in found if (f[1] or 0) + (f[2] or 0) > 5000]
            ms = plan["Execution Time"]
            slow += ms > 50
            flag = "  SEQ " + ", ".join(f"{t}({(r or 0) + (x or 0)})" for t, r, x in big) if big else ""
            print(f"{ms:9.2f} ms  {name}{flag}")
        print(json.dumps({"queries": len(QUERIES), "over_50ms": slow}))


if __name__ == "__main__":
    main()

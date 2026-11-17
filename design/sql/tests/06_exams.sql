-- =====================================================================
--  Exam candidate numbers (migration 0015) — run as the RUNTIME role, never as a superuser:
--      psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/06_exams.sql
--  Requires migrations to head + seed.sql. Everything is rolled back.
--  A block raises SQLSTATE TF001 when a forbidden change is accepted.
-- =====================================================================
BEGIN;
SET ROLE ssms_app;

CREATE FUNCTION pg_temp.u(t INTEGER, n INTEGER) RETURNS UUID LANGUAGE sql IMMUTABLE AS
$$ SELECT (lpad(to_hex(t), 8, '0') || '-0000-4000-8000-' || lpad(to_hex(n), 12, '0'))::uuid $$;
CREATE FUNCTION pg_temp.ctx(p_school UUID, p_user UUID DEFAULT NULL) RETURNS VOID LANGUAGE sql AS $$
    SELECT set_config('app.school_id', COALESCE(p_school::text, ''), true),
           set_config('app.user_id',   COALESCE(p_user::text, ''), true);
$$;

-- TEST X06 candidate numbers are unique within an exam session, and one per student
SAVEPOINT test_block;
DO $$
DECLARE v_session UUID; v_e1 UUID; v_e2 UUID; v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    SELECT id INTO v_session FROM exam_sessions LIMIT 1;
    SELECT id INTO v_e1 FROM enrolments ORDER BY id LIMIT 1;
    SELECT id INTO v_e2 FROM enrolments ORDER BY id OFFSET 1 LIMIT 1;
    INSERT INTO exam_candidates (school_id, exam_session_id, enrolment_id, candidate_no) VALUES (pg_temp.u(1,1), v_session, v_e1, 'S4521-0001');
    BEGIN
        INSERT INTO exam_candidates (school_id, exam_session_id, enrolment_id, candidate_no) VALUES (pg_temp.u(1,1), v_session, v_e2, 'S4521-0001');
    EXCEPTION WHEN unique_violation THEN v_ok := v_ok + 1; END;
    BEGIN
        INSERT INTO exam_candidates (school_id, exam_session_id, enrolment_id, candidate_no) VALUES (pg_temp.u(1,1), v_session, v_e1, 'S4521-0002');
    EXCEPTION WHEN unique_violation THEN v_ok := v_ok + 1; END;
    IF v_ok <> 2 THEN RAISE EXCEPTION 'X06 duplicate candidate accepted' USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS X06 duplicate candidate number and second number for a student rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

ROLLBACK;

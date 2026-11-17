-- =====================================================================
--  Study materials and homework (migration 0014) — run as the RUNTIME role, never as a superuser:
--      psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/05_teaching.sql
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

-- TEST X09 homework: one submission per student; content required; a material is a file or a link, not both
SAVEPOINT test_block;
DO $$
DECLARE v_year UUID; v_subject UUID; v_staff UUID; v_hw UUID; v_enr UUID; v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    SELECT id INTO v_year FROM academic_years ORDER BY start_date DESC LIMIT 1;
    SELECT id INTO v_subject FROM subjects LIMIT 1;
    SELECT id INTO v_staff FROM staff LIMIT 1;
    SELECT id INTO v_enr FROM enrolments LIMIT 1;
    INSERT INTO homework (school_id, academic_year_id, subject_id, title, instructions, due_at, set_by)
    VALUES (pg_temp.u(1,1), v_year, v_subject, 'Exercise 4', 'Questions 1-10', '2026-10-28 08:00+03', v_staff) RETURNING id INTO v_hw;
    INSERT INTO homework_submissions (school_id, homework_id, enrolment_id, body) VALUES (pg_temp.u(1,1), v_hw, v_enr, 'answers');
    BEGIN INSERT INTO homework_submissions (school_id, homework_id, enrolment_id, body) VALUES (pg_temp.u(1,1), v_hw, v_enr, 'again');
    EXCEPTION WHEN unique_violation THEN v_ok := v_ok + 1; END;
    BEGIN UPDATE homework_submissions SET body = NULL WHERE homework_id = v_hw;
    EXCEPTION WHEN check_violation THEN v_ok := v_ok + 1; END;
    BEGIN INSERT INTO study_materials (school_id, academic_year_id, subject_id, title, published_by)
          VALUES (pg_temp.u(1,1), v_year, v_subject, 'Notes with nothing attached', v_staff);
    EXCEPTION WHEN check_violation THEN v_ok := v_ok + 1; END;
    BEGIN INSERT INTO study_materials (school_id, academic_year_id, subject_id, title, link_url, published_by)
          VALUES (pg_temp.u(1,1), v_year, v_subject, 'Insecure link', 'http://example.com', v_staff);
    EXCEPTION WHEN check_violation THEN v_ok := v_ok + 1; END;
    IF v_ok <> 4 THEN RAISE EXCEPTION 'X09 % of 4 rules held', v_ok USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS X09 duplicate submission, empty submission, empty material and http link rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

ROLLBACK;

-- =====================================================================
--  Front office, staff attendance and leave (migration 0013) — run as the RUNTIME role, never as a superuser:
--      psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/04_front_office.sql
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

-- TEST X02 a row written in school A is invisible from school B and with no school set
SAVEPOINT test_block;
DO $$
DECLARE n INTEGER;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO school_events (school_id, title_en, title_sw, starts_on, ends_on) VALUES (pg_temp.u(1,1), 'Sports day', 'Siku ya michezo', '2026-11-06', '2026-11-06');
    INSERT INTO admission_inquiries (school_id, full_name, phone) VALUES (pg_temp.u(1,1), 'Neema Said', '255712000111');
    PERFORM pg_temp.ctx(pg_temp.u(1,2));
    SELECT (SELECT count(*) FROM school_events) + (SELECT count(*) FROM admission_inquiries) INTO n;
    IF n <> 0 THEN RAISE EXCEPTION 'X02 school B sees % rows of school A', n USING ERRCODE = 'TF001'; END IF;
    PERFORM pg_temp.ctx(NULL);
    SELECT (SELECT count(*) FROM school_events) + (SELECT count(*) FROM admission_inquiries) INTO n;
    IF n <> 0 THEN RAISE EXCEPTION 'X02 no school context sees % rows', n USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS X02 school A rows hidden from school B and from a request with no school';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST X03 school B cannot write a row for school A, nor point at school A's staff
SAVEPOINT test_block;
DO $$
DECLARE v_staff UUID; v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1));
    SELECT id INTO v_staff FROM staff LIMIT 1;
    PERFORM pg_temp.ctx(pg_temp.u(1,2));
    BEGIN
        INSERT INTO staff_attendance (school_id, staff_id, on_date, status) VALUES (pg_temp.u(1,1), v_staff, '2026-10-21', 'PRESENT');
    EXCEPTION WHEN insufficient_privilege THEN v_ok := v_ok + 1; END;            -- RLS WITH CHECK
    BEGIN
        INSERT INTO staff_attendance (school_id, staff_id, on_date, status) VALUES (pg_temp.u(1,2), v_staff, '2026-10-21', 'PRESENT');
    EXCEPTION WHEN foreign_key_violation THEN v_ok := v_ok + 1; END;            -- composite FK (school B, staff of A)
    IF v_ok <> 2 THEN RAISE EXCEPTION 'X03 cross-school write accepted' USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS X03 cross-school insert and cross-school reference both rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST X04 one staff attendance record per person per day
SAVEPOINT test_block;
DO $$
DECLARE v_staff UUID;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    SELECT id INTO v_staff FROM staff LIMIT 1;
    INSERT INTO staff_attendance (school_id, staff_id, on_date, status) VALUES (pg_temp.u(1,1), v_staff, '2026-10-21', 'PRESENT');
    INSERT INTO staff_attendance (school_id, staff_id, on_date, status) VALUES (pg_temp.u(1,1), v_staff, '2026-10-21', 'LATE');
    RAISE EXCEPTION 'X04 second record accepted' USING ERRCODE = 'TF001';
EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'PASS X04 second attendance record for the same day rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST X05 overlapping approved leave is rejected; a decision by the requester is rejected
SAVEPOINT test_block;
DO $$
DECLARE v_staff UUID; v_type UUID; v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    SELECT id INTO v_staff FROM staff LIMIT 1;
    INSERT INTO leave_types (school_id, name_en, name_sw, applies_to, days_per_year)
    VALUES (pg_temp.u(1,1), 'Annual', 'Likizo ya mwaka', 'STAFF', 28) RETURNING id INTO v_type;
    INSERT INTO leave_requests (school_id, leave_type_id, staff_id, start_date, end_date, reason, status, decided_by, decided_at, created_by)
    VALUES (pg_temp.u(1,1), v_type, v_staff, '2026-12-01', '2026-12-10', 'Family', 'APPROVED', pg_temp.u(2,1), now(), pg_temp.u(2,2));
    BEGIN
        INSERT INTO leave_requests (school_id, leave_type_id, staff_id, start_date, end_date, reason, status, decided_by, decided_at, created_by)
        VALUES (pg_temp.u(1,1), v_type, v_staff, '2026-12-10', '2026-12-12', 'Travel', 'APPROVED', pg_temp.u(2,1), now(), pg_temp.u(2,2));
    EXCEPTION WHEN exclusion_violation THEN v_ok := v_ok + 1; END;
    BEGIN
        INSERT INTO leave_requests (school_id, leave_type_id, staff_id, start_date, end_date, reason, status, decided_by, decided_at, created_by)
        VALUES (pg_temp.u(1,1), v_type, v_staff, '2027-01-05', '2027-01-06', 'Self', 'APPROVED', pg_temp.u(2,2), now(), pg_temp.u(2,2));
    EXCEPTION WHEN check_violation THEN v_ok := v_ok + 1; END;
    -- a pending request may overlap: only approved leave blocks
    INSERT INTO leave_requests (school_id, leave_type_id, staff_id, start_date, end_date, reason, created_by)
    VALUES (pg_temp.u(1,1), v_type, v_staff, '2026-12-05', '2026-12-06', 'Pending', pg_temp.u(2,2));
    IF v_ok <> 2 THEN RAISE EXCEPTION 'X05 % of 2 rules held', v_ok USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS X05 overlapping approved leave and self-approval rejected; pending overlap allowed';
END $$;
ROLLBACK TO SAVEPOINT test_block;

ROLLBACK;

-- =====================================================================
--  Tenant isolation tests — run as the RUNTIME role, never as a superuser:
--      psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/01_isolation.sql
--  Requires schema.sql + seed.sql. Everything is rolled back.
--  A block raises SQLSTATE TF001 when a forbidden change is accepted.
--  Blocks are separated by "-- TEST" lines so a runner can isolate each in a savepoint.
-- =====================================================================
BEGIN;
SET ROLE ssms_app;

CREATE FUNCTION pg_temp.u(t INTEGER, n INTEGER) RETURNS UUID LANGUAGE sql IMMUTABLE AS
$$ SELECT (lpad(to_hex(t), 8, '0') || '-0000-4000-8000-' || lpad(to_hex(n), 12, '0'))::uuid $$;
CREATE FUNCTION pg_temp.ctx(p_school UUID, p_user UUID DEFAULT NULL) RETURNS VOID LANGUAGE sql AS $$
    SELECT set_config('app.school_id', COALESCE(p_school::text, ''), true),
           set_config('app.user_id',   COALESCE(p_user::text, ''), true);
$$;

-- TEST I01 the runtime role is not a superuser and cannot bypass RLS
SAVEPOINT test_block;
DO $$
DECLARE v_super BOOLEAN; v_bypass BOOLEAN;
BEGIN
    SELECT rolsuper, rolbypassrls INTO v_super, v_bypass FROM pg_roles WHERE rolname = current_user;
    IF current_user <> 'ssms_app' OR v_super OR v_bypass THEN
        RAISE EXCEPTION 'I01 running as % (super=%, bypassrls=%)', current_user, v_super, v_bypass USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I01 running as ssms_app, NOSUPERUSER, NOBYPASSRLS';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I02 no school context -> zero rows from every tenant table and from schools
SAVEPOINT test_block;
DO $$
DECLARE t RECORD; n BIGINT; total BIGINT := 0; tables INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(NULL);
    FOR t IN SELECT c.relname FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
             WHERE c.relkind = 'r' AND c.relrowsecurity AND has_table_privilege(c.oid, 'SELECT')
    LOOP
        EXECUTE format('SELECT count(*) FROM %I', t.relname) INTO n;
        total := total + n; tables := tables + 1;
        IF n <> 0 THEN
            RAISE EXCEPTION 'I02 % returned % rows without a school context', t.relname, n USING ERRCODE = 'TF001';
        END IF;
    END LOOP;
    RAISE NOTICE 'PASS I02 % RLS tables, 0 rows without context', tables;
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I03 school A context sees only school A rows in every table
SAVEPOINT test_block;
DO $$
DECLARE t RECORD; n BIGINT; v_students BIGINT;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1));
    FOR t IN SELECT c.relname FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
             JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'school_id'
             WHERE c.relkind = 'r' AND has_table_privilege(c.oid, 'SELECT')
    LOOP
        EXECUTE format('SELECT count(*) FROM %I WHERE school_id <> $1', t.relname) INTO n USING pg_temp.u(1,1);
        IF n <> 0 THEN
            RAISE EXCEPTION 'I03 % leaked % foreign rows', t.relname, n USING ERRCODE = 'TF001';
        END IF;
    END LOOP;
    SELECT count(*) INTO v_students FROM students;
    IF v_students <> 8 OR (SELECT count(*) FROM schools) <> 1 THEN
        RAISE EXCEPTION 'I03 expected 8 students and 1 school, got % and %', v_students, (SELECT count(*) FROM schools) USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I03 school A sees only its own rows (8 students, 1 school)';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I04 school A cannot SELECT a known school B row by id
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1));
    IF EXISTS (SELECT 1 FROM students WHERE id = pg_temp.u(6,111)) OR EXISTS (SELECT 1 FROM users WHERE id = pg_temp.u(2,121)) THEN
        RAISE EXCEPTION 'I04 school B rows visible from school A' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I04 school B rows invisible by id';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I05 school A UPDATE of a school B row affects 0 rows
SAVEPOINT test_block;
DO $$
DECLARE v_rows INTEGER;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    UPDATE students SET status = 'SUSPENDED' WHERE id = pg_temp.u(6,111);
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    IF v_rows <> 0 THEN
        RAISE EXCEPTION 'I05 updated % school B rows', v_rows USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I05 cross-school UPDATE touched 0 rows';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I06 school A cannot INSERT a row labelled with school B (RLS WITH CHECK)
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO notifications (school_id, user_id, kind, title, body)
    VALUES (pg_temp.u(1,2), pg_temp.u(2,121), 'TEST', 'x', 'x');
    RAISE EXCEPTION 'I06 inserted a school B row from school A' USING ERRCODE = 'TF001';
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS I06 cross-school INSERT rejected by RLS';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I07 composite FK: a school A row cannot point at a school B row
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO enrolments (school_id, student_id, stream_id, academic_year_id, status, started_on)
    VALUES (pg_temp.u(1,1), pg_temp.u(6,18), pg_temp.u(19,101), pg_temp.u(12,1), 'ACTIVE', '2026-01-12');   -- B's stream
    RAISE EXCEPTION 'I07 enrolment pointed at another school''s stream' USING ERRCODE = 'TF001';
EXCEPTION WHEN foreign_key_violation THEN
    RAISE NOTICE 'PASS I07 composite FK blocks cross-school references';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I08 the runtime role cannot hard-delete business rows or read platform admins
SAVEPOINT test_block;
DO $$
DECLARE v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    BEGIN
        DELETE FROM students WHERE id = pg_temp.u(6,18);
    EXCEPTION WHEN insufficient_privilege THEN v_ok := v_ok + 1;
    END;
    BEGIN
        PERFORM 1 FROM platform_admins;
    EXCEPTION WHEN insufficient_privilege THEN v_ok := v_ok + 1;
    END;
    IF v_ok <> 2 THEN
        RAISE EXCEPTION 'I08 DELETE or platform_admins read was allowed' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I08 no DELETE on students, no access to platform_admins';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I09 same username "admin" in both schools; each context sees its own
SAVEPOINT test_block;
DO $$
DECLARE a UUID; b UUID;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1));
    SELECT id INTO a FROM users WHERE lower(username) = 'admin';
    PERFORM pg_temp.ctx(pg_temp.u(1,2));
    SELECT id INTO b FROM users WHERE lower(username) = 'admin';
    IF a IS DISTINCT FROM pg_temp.u(2,1) OR b IS DISTINCT FROM pg_temp.u(2,101) THEN
        RAISE EXCEPTION 'I09 username lookup crossed schools: % / %', a, b USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I09 per-school usernames';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I10 F3: same cash receipt number in both schools; a duplicate within one school is rejected
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,2));
    IF (SELECT count(*) FROM payments WHERE channel = 'CASH' AND external_ref = 'RCT-BOOK-0001') <> 1 THEN
        RAISE EXCEPTION 'I10 school A should see exactly one RCT-BOOK-0001' USING ERRCODE = 'TF001';
    END IF;
    INSERT INTO payments (school_id, student_id, channel, external_ref, amount_tzs, status, received_at, confirmed_at, recorded_by)
    VALUES (pg_temp.u(1,1), pg_temp.u(6,11), 'CASH', 'RCT-BOOK-0001', 1000, 'CONFIRMED', now(), now(), pg_temp.u(2,2));
    RAISE EXCEPTION 'I10 duplicate receipt accepted in the same school' USING ERRCODE = 'TF001';
EXCEPTION WHEN unique_violation THEN
    RAISE NOTICE 'PASS I10 external_ref unique per school (same ref allowed in school B)';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I11 resolve_school_by_code returns only the id
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(NULL);
    IF resolve_school_by_code('MFANO-SEC') IS DISTINCT FROM pg_temp.u(1,1)
       OR resolve_school_by_code('upendo-pri') IS DISTINCT FROM pg_temp.u(1,2)
       OR resolve_school_by_code('no-such-school') IS NOT NULL THEN
        RAISE EXCEPTION 'I11 resolve_school_by_code wrong' USING ERRCODE = 'TF001';
    END IF;
    IF (SELECT count(*) FROM schools) <> 0 THEN
        RAISE EXCEPTION 'I11 resolver opened table access' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I11 resolve_school_by_code';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I12 resolve_device maps an API key hash to (school, device) and nothing for a wrong key
SAVEPOINT test_block;
DO $$
DECLARE r RECORD; n INTEGER;
BEGIN
    PERFORM pg_temp.ctx(NULL);
    SELECT * INTO r FROM resolve_device(encode(sha256('demo-device-key-upendo-gate'::bytea), 'hex'));
    SELECT count(*) INTO n FROM resolve_device(encode(sha256('wrong-key'::bytea), 'hex'));
    IF r.school_id IS DISTINCT FROM pg_temp.u(1,2) OR r.device_id IS DISTINCT FROM pg_temp.u(30,101) OR n <> 0 THEN
        RAISE EXCEPTION 'I12 resolve_device wrong: % %, unknown=%', r.school_id, r.device_id, n USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I12 resolve_device';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I13 resolve_gepg_bill by control number and by bill reference
SAVEPOINT test_block;
DO $$
DECLARE a RECORD; b RECORD;
BEGIN
    PERFORM pg_temp.ctx(NULL);
    SELECT * INTO a FROM resolve_gepg_bill(p_control_number => '994120000001');
    SELECT * INTO b FROM resolve_gepg_bill(p_bill_ref => 'mfano-sec-2026-000002');
    IF a.school_id IS DISTINCT FROM pg_temp.u(1,1) OR a.bill_id IS DISTINCT FROM pg_temp.u(37,1)
       OR b.bill_id IS DISTINCT FROM pg_temp.u(37,2) OR EXISTS (SELECT 1 FROM resolve_gepg_bill('999999999999')) THEN
        RAISE EXCEPTION 'I13 resolve_gepg_bill wrong' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I13 resolve_gepg_bill';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I14 resolve_refresh_token returns (school, user, family) for a stored hash
SAVEPOINT test_block;
DO $$
DECLARE r RECORD;
BEGIN
    PERFORM pg_temp.ctx(NULL);
    SELECT * INTO r FROM resolve_refresh_token(encode(sha256('demo-refresh-token-mfano-admin'::bytea), 'hex'));
    IF r.school_id IS DISTINCT FROM pg_temp.u(1,1) OR r.user_id IS DISTINCT FROM pg_temp.u(2,1)
       OR r.family_id IS DISTINCT FROM pg_temp.u(60,1) THEN
        RAISE EXCEPTION 'I14 resolve_refresh_token wrong' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I14 resolve_refresh_token';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I15 resolve_users_by_phone: a parent in two schools -> two rows; a staff phone -> none
SAVEPOINT test_block;
DO $$
DECLARE n_parent INTEGER; n_staff INTEGER; n_b INTEGER;
BEGIN
    PERFORM pg_temp.ctx(NULL);
    SELECT count(*), count(*) FILTER (WHERE school_id = pg_temp.u(1,2) AND user_id = pg_temp.u(2,121))
      INTO n_parent, n_b
      FROM resolve_users_by_phone(sha256(convert_to('demo-only:255754000021', 'UTF8')));
    SELECT count(*) INTO n_staff FROM resolve_users_by_phone(sha256(convert_to('demo-only:255754000001', 'UTF8')));
    IF n_parent <> 2 OR n_b <> 1 OR n_staff <> 0 THEN
        RAISE EXCEPTION 'I15 resolve_users_by_phone parent=% (B=%), staff=%', n_parent, n_b, n_staff USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS I15 resolve_users_by_phone (2 schools for the parent, 0 for staff)';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST I16 resolvers cannot be called by roles other than ssms_app (EXECUTE revoked from PUBLIC)
SAVEPOINT test_block;
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN SELECT p.proname, array_to_string(p.proacl, ',') AS acl
             FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace AND n.nspname = 'public'
             WHERE p.prosecdef
    LOOP
        IF r.acl IS NULL OR r.acl ~ '(^|,)=' THEN                 -- NULL acl = default PUBLIC execute
            RAISE EXCEPTION 'I16 % is executable by PUBLIC: %', r.proname, r.acl USING ERRCODE = 'TF001';
        END IF;
        IF r.acl !~ '(^|,)ssms_app=X' THEN
            RAISE EXCEPTION 'I16 % not granted to ssms_app: %', r.proname, r.acl USING ERRCODE = 'TF001';
        END IF;
    END LOOP;
    RAISE NOTICE 'PASS I16 SECURITY DEFINER functions executable only by owner and ssms_app';
END $$;
ROLLBACK TO SAVEPOINT test_block;

ROLLBACK;

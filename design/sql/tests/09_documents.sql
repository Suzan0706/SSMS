-- =====================================================================
--  Certificates and ID cards (migration 0018) — run as the RUNTIME role, never as a superuser:
--      psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/09_documents.sql
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

-- TEST X08 issued certificates are frozen; revocation is recorded once
SAVEPOINT test_block;
DO $$
DECLARE v_tpl UUID; v_cert UUID; v_student UUID; v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    SELECT id INTO v_student FROM students LIMIT 1;
    INSERT INTO certificate_templates (school_id, kind, name, language, body)
    VALUES (pg_temp.u(1,1), 'LEAVING', 'Cheti cha kuhitimu', 'sw', 'Hii ni kuthibitisha kwamba {{name}} ...') RETURNING id INTO v_tpl;
    INSERT INTO certificates (school_id, template_id, student_id, serial_no, issued_on, rendered_text)
    VALUES (pg_temp.u(1,1), v_tpl, v_student, 'CT-0001', '2026-10-21', 'Hii ni kuthibitisha kwamba Amani ...') RETURNING id INTO v_cert;
    BEGIN UPDATE certificates SET rendered_text = 'changed' WHERE id = v_cert;
    EXCEPTION WHEN check_violation THEN v_ok := v_ok + 1; END;
    UPDATE certificates SET revoked_at = now(), revoked_reason = 'issued to the wrong student' WHERE id = v_cert;
    BEGIN UPDATE certificates SET revoked_reason = 'second edit' WHERE id = v_cert;
    EXCEPTION WHEN check_violation THEN v_ok := v_ok + 1; END;
    BEGIN INSERT INTO certificates (school_id, template_id, student_id, serial_no, issued_on, rendered_text)
          VALUES (pg_temp.u(1,1), v_tpl, v_student, 'CT-0001', '2026-10-22', 'duplicate serial');
    EXCEPTION WHEN unique_violation THEN v_ok := v_ok + 1; END;
    IF v_ok <> 3 THEN RAISE EXCEPTION 'X08 % of 3 rules held', v_ok USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS X08 certificate text frozen, revoked once, serial unique';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST X10 one live ID card per person; card numbers unique; a new card after revoking the old one
SAVEPOINT test_block;
DO $$
DECLARE v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO identity_cards (school_id, user_id, card_no, valid_until) VALUES (pg_temp.u(1,1), pg_temp.u(2,1), 'ID-0001', '2027-12-31');
    BEGIN INSERT INTO identity_cards (school_id, user_id, card_no, valid_until) VALUES (pg_temp.u(1,1), pg_temp.u(2,1), 'ID-0002', '2027-12-31');
    EXCEPTION WHEN unique_violation THEN v_ok := v_ok + 1; END;
    UPDATE identity_cards SET revoked_at = now() WHERE card_no = 'ID-0001';
    INSERT INTO identity_cards (school_id, user_id, card_no, valid_until) VALUES (pg_temp.u(1,1), pg_temp.u(2,1), 'ID-0002', '2027-12-31');
    IF v_ok <> 1 THEN RAISE EXCEPTION 'X10 second live ID card accepted' USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS X10 one live ID card per person; a new card after revoking the old one';
END $$;
ROLLBACK TO SAVEPOINT test_block;

ROLLBACK;

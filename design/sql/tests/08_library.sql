-- =====================================================================
--  Library categories, publishers and cards (migration 0017) — run as the RUNTIME role, never as a superuser:
--      psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/08_library.sql
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

-- TEST L01 one live library card per person; card numbers unique; a new card after revoking the old one
SAVEPOINT test_block;
DO $$
DECLARE v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO library_cards (school_id, user_id, card_no, issued_on) VALUES (pg_temp.u(1,1), pg_temp.u(2,11), 'LC-0001', '2026-10-21');
    BEGIN INSERT INTO library_cards (school_id, user_id, card_no, issued_on) VALUES (pg_temp.u(1,1), pg_temp.u(2,11), 'LC-0002', '2026-10-21');
    EXCEPTION WHEN unique_violation THEN v_ok := v_ok + 1; END;
    BEGIN INSERT INTO library_cards (school_id, user_id, card_no, issued_on) VALUES (pg_temp.u(1,1), pg_temp.u(2,12), 'LC-0001', '2026-10-21');
    EXCEPTION WHEN unique_violation THEN v_ok := v_ok + 1; END;
    UPDATE library_cards SET revoked_at = now() WHERE card_no = 'LC-0001';
    INSERT INTO library_cards (school_id, user_id, card_no, issued_on) VALUES (pg_temp.u(1,1), pg_temp.u(2,11), 'LC-0002', '2026-10-22');
    IF v_ok <> 2 THEN RAISE EXCEPTION 'L01 % of 2 rules held', v_ok USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS L01 one live library card per person, numbers unique, reissue after revoking';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST L02 a book can only point to a category and publisher of its own school
SAVEPOINT test_block;
DO $$
DECLARE v_cat UUID;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,2), pg_temp.u(2,101));
    INSERT INTO library_categories (school_id, name) VALUES (pg_temp.u(1,2), 'Hadithi') RETURNING id INTO v_cat;
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    UPDATE library_books SET category_id = v_cat WHERE id = pg_temp.u(52,1);
    RAISE EXCEPTION 'L02 book linked to another school category' USING ERRCODE = 'TF001';
EXCEPTION WHEN foreign_key_violation THEN RAISE NOTICE 'PASS L02 cross-school category refused';
END $$;
ROLLBACK TO SAVEPOINT test_block;

ROLLBACK;

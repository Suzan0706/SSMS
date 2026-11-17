-- =====================================================================
--  Other income and expenses (migration 0016) — run as the RUNTIME role, never as a superuser:
--      psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/07_accounts.sql
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

-- TEST X07 cash entries: never deleted, never edited, reversal needs a second person; journals accept CASH_ENTRY
SAVEPOINT test_block;
DO $$
DECLARE v_acc UUID; v_cat UUID; v_journal UUID; v_entry UUID; v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    SELECT id INTO v_acc FROM ledger_accounts WHERE kind = 'EXPENSE' LIMIT 1;
    IF v_acc IS NULL THEN
        INSERT INTO ledger_accounts (school_id, code, name_en, name_sw, kind, is_system)
        VALUES (pg_temp.u(1,1), '5900', 'Other expenses', 'Matumizi mengine', 'EXPENSE', FALSE) RETURNING id INTO v_acc;
    END IF;
    INSERT INTO finance_categories (school_id, kind, name_en, name_sw, ledger_account_id)
    VALUES (pg_temp.u(1,1), 'EXPENSE', 'Electricity', 'Umeme', v_acc) RETURNING id INTO v_cat;
    INSERT INTO journals (school_id, journal_no, source_type, source_id, memo)
    VALUES (pg_temp.u(1,1), 'JX-TEST-1', 'CASH_ENTRY', gen_random_uuid(), 'test header') RETURNING id INTO v_journal;
    INSERT INTO cash_entries (school_id, entry_no, category_id, entry_date, amount_tzs, method, description, journal_id)
    VALUES (pg_temp.u(1,1), 'EX-0001', v_cat, '2026-10-21', 150000, 'CASH', 'TANESCO tokens', v_journal) RETURNING id INTO v_entry;
    BEGIN UPDATE cash_entries SET amount_tzs = 1 WHERE id = v_entry;
    EXCEPTION WHEN check_violation THEN v_ok := v_ok + 1; END;
    BEGIN DELETE FROM cash_entries WHERE id = v_entry;
    EXCEPTION WHEN insufficient_privilege OR check_violation THEN v_ok := v_ok + 1; END;
    BEGIN UPDATE cash_entries SET status = 'REVERSED', reversal_requested_by = pg_temp.u(2,1), reversal_approved_by = pg_temp.u(2,1),
                 reversal_reason = 'wrong amount', reversal_journal_id = v_journal WHERE id = v_entry;
    EXCEPTION WHEN check_violation THEN v_ok := v_ok + 1; END;
    BEGIN INSERT INTO journals (school_id, journal_no, source_type, source_id, memo)
          VALUES (pg_temp.u(1,1), 'JX-TEST-2', 'BOGUS', gen_random_uuid(), 'bad source');
    EXCEPTION WHEN check_violation THEN v_ok := v_ok + 1; END;
    IF v_ok <> 4 THEN RAISE EXCEPTION 'X07 % of 4 rules held', v_ok USING ERRCODE = 'TF001'; END IF;
    RAISE NOTICE 'PASS X07 cash entry edit, delete and self-approved reversal rejected; unknown journal source rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

ROLLBACK;

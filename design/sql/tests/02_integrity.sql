-- =====================================================================
--  Integrity tests (F3–F9, timetable, enrolment, SMS, audit) — run as ssms_app:
--      psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/02_integrity.sql
--  Requires schema.sql + seed.sql. Everything is rolled back.
--  Deferred rules (journal balance) are forced with SET CONSTRAINTS ... IMMEDIATE.
-- =====================================================================
BEGIN;
SET ROLE ssms_app;

CREATE FUNCTION pg_temp.u(t INTEGER, n INTEGER) RETURNS UUID LANGUAGE sql IMMUTABLE AS
$$ SELECT (lpad(to_hex(t), 8, '0') || '-0000-4000-8000-' || lpad(to_hex(n), 12, '0'))::uuid $$;
CREATE FUNCTION pg_temp.ctx(p_school UUID, p_user UUID DEFAULT NULL) RETURNS VOID LANGUAGE sql AS $$
    SELECT set_config('app.school_id', COALESCE(p_school::text, ''), true),
           set_config('app.user_id',   COALESCE(p_user::text, ''), true);
$$;

-- ---------------- Timetable, enrolment, attendance SMS ----------------

-- TEST T01 teacher double-booking (Mwita teaches F2A Mon 08:00-08:40)
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO timetable_slots (school_id, term_id, stream_id, subject_id, staff_id, room_id, day_of_week, time_start, time_end)
    VALUES (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(19,1), pg_temp.u(15,9), pg_temp.u(8,3), pg_temp.u(18,7), 1, '08:20', '09:00');
    RAISE EXCEPTION 'T01 teacher clash accepted' USING ERRCODE = 'TF001';
EXCEPTION WHEN exclusion_violation THEN RAISE NOTICE 'PASS T01 teacher clash rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST T02 room double-booking (F2A room Mon 08:00-08:40)
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO timetable_slots (school_id, term_id, stream_id, subject_id, staff_id, room_id, day_of_week, time_start, time_end)
    VALUES (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(19,1), pg_temp.u(15,1), pg_temp.u(8,8), pg_temp.u(18,1), 1, '08:10', '08:30');
    RAISE EXCEPTION 'T02 room clash accepted' USING ERRCODE = 'TF001';
EXCEPTION WHEN exclusion_violation THEN RAISE NOTICE 'PASS T02 room clash rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST T03 stream double-booking (F2A has Basic Maths Mon 08:00-08:40)
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO timetable_slots (school_id, term_id, stream_id, subject_id, staff_id, room_id, day_of_week, time_start, time_end)
    VALUES (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(19,2), pg_temp.u(15,2), pg_temp.u(8,8), pg_temp.u(18,7), 1, '08:20', '08:50');
    RAISE EXCEPTION 'T03 stream clash accepted' USING ERRCODE = 'TF001';
EXCEPTION WHEN exclusion_violation THEN RAISE NOTICE 'PASS T03 stream clash rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST T04 back-to-back periods are allowed (half-open [start, end) ranges)
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO timetable_slots (school_id, term_id, stream_id, subject_id, staff_id, room_id, day_of_week, time_start, time_end)
    VALUES (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(19,1), pg_temp.u(15,9), pg_temp.u(8,3), pg_temp.u(18,7), 2, '08:00', '08:40'),
           (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(19,2), pg_temp.u(15,9), pg_temp.u(8,3), pg_temp.u(18,1), 2, '08:40', '09:20');
    RAISE NOTICE 'PASS T04 back-to-back periods accepted';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST T05 one enrolment per student per academic year
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO enrolments (school_id, student_id, stream_id, academic_year_id, status, started_on)
    VALUES (pg_temp.u(1,1), pg_temp.u(6,11), pg_temp.u(19,3), pg_temp.u(12,1), 'ACTIVE', '2026-02-01');
    RAISE EXCEPTION 'T05 second enrolment accepted' USING ERRCODE = 'TF001';
EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'PASS T05 second enrolment in the same year rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST T06 one absence SMS per student per day (alert row and SMS idempotency key)
SAVEPOINT test_block;
DO $$
DECLARE v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    BEGIN
        INSERT INTO absence_alerts (school_id, student_id, absence_date) VALUES (pg_temp.u(1,1), pg_temp.u(6,13), '2026-03-02');
    EXCEPTION WHEN unique_violation THEN v_ok := v_ok + 1;
    END;
    BEGIN
        INSERT INTO sms_messages (school_id, to_phone_enc, to_phone_last4, language, body, segments, provider, idempotency_key)
        VALUES (pg_temp.u(1,1), '\xfa4e'::bytea, '0023', 'sw', 'duplicate', 1, 'BEEM', 'absence:' || pg_temp.u(6,13) || ':2026-03-02');
    EXCEPTION WHEN unique_violation THEN v_ok := v_ok + 1;
    END;
    IF v_ok <> 2 THEN
        RAISE EXCEPTION 'T06 duplicate absence alert or SMS accepted' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS T06 duplicate absence alert and duplicate SMS rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST T07 capacity: hostel room K1 holds 4 (1 already allocated)
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO hostel_allocations (school_id, student_id, hostel_room_id, term_id)
    SELECT pg_temp.u(1,1), pg_temp.u(6,s), pg_temp.u(42,1), pg_temp.u(13,1) FROM (VALUES (11),(13),(14)) v(s);
    BEGIN
        INSERT INTO hostel_allocations (school_id, student_id, hostel_room_id, term_id)
        VALUES (pg_temp.u(1,1), pg_temp.u(6,15), pg_temp.u(42,1), pg_temp.u(13,1));
        RAISE EXCEPTION 'T07 fifth bed allocated in a 4-bed room' USING ERRCODE = 'TF001';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    RAISE NOTICE 'PASS T07 room filled to capacity, fifth allocation rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST T08 venue bookings cannot overlap
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO venue_events (school_id, venue_id, name, event_date, time_start, time_end, seats_occupied)
    VALUES (pg_temp.u(1,1), pg_temp.u(47,1), 'Clash', '2026-10-30', '12:00', '14:00', 50);
    RAISE EXCEPTION 'T08 overlapping booking accepted' USING ERRCODE = 'TF001';
EXCEPTION WHEN exclusion_violation THEN RAISE NOTICE 'PASS T08 overlapping venue booking rejected';
END $$;

-- ---------------- F4 marks and the validation firewall ----------------
ROLLBACK TO SAVEPOINT test_block;

-- TEST F4a a score above the component maximum is rejected (A-Level CA max 40)
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,5));
    UPDATE mark_entries SET score = 41
     WHERE enrolment_id = pg_temp.u(24,17) AND subject_id = pg_temp.u(15,11);
    RAISE EXCEPTION 'F4a score above maximum accepted' USING ERRCODE = 'TF001';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'PASS F4a score above component maximum rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F4b marks are locked after publication; draft edits increment the version
SAVEPOINT test_block;
DO $$
DECLARE v_before INTEGER; v_after INTEGER;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,5));
    SELECT version INTO v_before FROM mark_entries WHERE enrolment_id = pg_temp.u(24,17) AND subject_id = pg_temp.u(15,11);
    UPDATE mark_entries SET score = 33 WHERE enrolment_id = pg_temp.u(24,17) AND subject_id = pg_temp.u(15,11);
    SELECT version INTO v_after FROM mark_entries WHERE enrolment_id = pg_temp.u(24,17) AND subject_id = pg_temp.u(15,11);
    IF v_after <> v_before + 1 THEN
        RAISE EXCEPTION 'F4b version not incremented (% -> %)', v_before, v_after USING ERRCODE = 'TF001';
    END IF;
    BEGIN
        UPDATE mark_entries SET score = 99 WHERE enrolment_id = pg_temp.u(24,11) AND subject_id = pg_temp.u(15,9);
        RAISE EXCEPTION 'F4b locked mark changed' USING ERRCODE = 'TF001';
    EXCEPTION WHEN raise_exception THEN NULL;
    END;
    RAISE NOTICE 'PASS F4b version increments on draft edit; published marks are locked';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F4c firewall lists missing marks and weight totals that are not 100
SAVEPOINT test_block;
DO $$
DECLARE v_missing INTEGER; v_weights INTEGER;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO assessment_components (school_id, term_id, education_level_id, code, name_en, name_sw, max_score, weight)
    VALUES (pg_temp.u(1,1), pg_temp.u(13,1), pg_temp.u(11,2), 'PROJECT', 'Project', 'Mradi', 100, 10);
    SELECT count(*) FILTER (WHERE problem_code = 'MISSING_MARK'), count(*) FILTER (WHERE problem_code = 'WEIGHTS_NOT_100')
      INTO v_missing, v_weights
      FROM results_firewall(pg_temp.u(13,1), pg_temp.u(16,5));
    IF v_missing < 5 OR v_weights <> 4 THEN
        RAISE EXCEPTION 'F4c firewall missing=% weights=%', v_missing, v_weights USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F4c firewall: % missing marks, % subjects with weights <> 100', v_missing, v_weights;
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F4d publishing an incomplete class is blocked with SQLSTATE SS422
SAVEPOINT test_block;
DO $$
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    PERFORM publish_results(pg_temp.u(13,1), pg_temp.u(16,5));
    RAISE EXCEPTION 'F4d incomplete class published' USING ERRCODE = 'TF001';
EXCEPTION WHEN SQLSTATE 'SS422' THEN RAISE NOTICE 'PASS F4d INCOMPLETE_GRADES_BLOCK raised';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F4e a complete class publishes; a second publication of the same class/term is refused
SAVEPOINT test_block;
DO $$
DECLARE v_pub UUID;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    INSERT INTO mark_entries (school_id, enrolment_id, subject_id, component_id, score, entered_by)
    SELECT pg_temp.u(1,1), pg_temp.u(24,17), s.sid, ac.id, CASE ac.code WHEN 'CA' THEN 30 ELSE 70 END, pg_temp.u(2,5)
    FROM (VALUES (pg_temp.u(15,10)),(pg_temp.u(15,11)),(pg_temp.u(15,12)),(pg_temp.u(15,13))) s(sid)
    JOIN assessment_components ac ON ac.term_id = pg_temp.u(13,1) AND ac.education_level_id = pg_temp.u(11,2)
    ON CONFLICT DO NOTHING;
    v_pub := publish_results(pg_temp.u(13,1), pg_temp.u(16,5));
    IF (SELECT count(*) FROM published_results WHERE publication_id = v_pub) <> 4
       OR (SELECT division FROM student_term_summaries WHERE publication_id = v_pub) IS NULL THEN
        RAISE EXCEPTION 'F4e publication incomplete' USING ERRCODE = 'TF001';
    END IF;
    BEGIN
        PERFORM publish_results(pg_temp.u(13,1), pg_temp.u(16,5));
        RAISE EXCEPTION 'F4e published twice' USING ERRCODE = 'TF001';
    EXCEPTION WHEN SQLSTATE 'SS422' THEN NULL;
    END;
    RAISE NOTICE 'PASS F4e Form V published (4 subjects, division %), second publish refused',
        (SELECT division FROM student_term_summaries WHERE publication_id = v_pub);
END $$;

-- ---------------- F5 double-entry ledger ----------------
ROLLBACK TO SAVEPOINT test_block;

-- TEST F5a an unbalanced journal fails at commit (forced with SET CONSTRAINTS IMMEDIATE)
SAVEPOINT test_block;
DO $$
DECLARE v_j UUID := gen_random_uuid();
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,2));
    INSERT INTO journals (id, school_id, journal_no, source_type, source_id, memo)
    VALUES (v_j, pg_temp.u(1,1), 'JNL-TEST-0001', 'ADJUSTMENT', gen_random_uuid(), 'Unbalanced test');
    INSERT INTO ledger_entries (school_id, journal_id, account_id, debit_tzs, credit_tzs) VALUES
     (pg_temp.u(1,1), v_j, pg_temp.u(33,1), 1000, 0),
     (pg_temp.u(1,1), v_j, pg_temp.u(33,5), 0, 900);
    EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
    RAISE EXCEPTION 'F5a unbalanced journal accepted' USING ERRCODE = 'TF001';
EXCEPTION WHEN raise_exception THEN RAISE NOTICE 'PASS F5a unbalanced journal rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F5b a balanced journal passes; ledger rows can never be updated or deleted
SAVEPOINT test_block;
DO $$
DECLARE v_j UUID := gen_random_uuid(); v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,2));
    INSERT INTO journals (id, school_id, journal_no, source_type, source_id, memo)
    VALUES (v_j, pg_temp.u(1,1), 'JNL-TEST-0002', 'ADJUSTMENT', gen_random_uuid(), 'Balanced test');
    INSERT INTO ledger_entries (school_id, journal_id, account_id, debit_tzs, credit_tzs) VALUES
     (pg_temp.u(1,1), v_j, pg_temp.u(33,1), 1000, 0),
     (pg_temp.u(1,1), v_j, pg_temp.u(33,5), 0, 1000);
    EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
    BEGIN UPDATE ledger_entries SET debit_tzs = 1 WHERE journal_id = v_j AND debit_tzs > 0;
    EXCEPTION WHEN insufficient_privilege OR raise_exception THEN v_ok := v_ok + 1; END;
    BEGIN DELETE FROM journals WHERE id = v_j;
    EXCEPTION WHEN insufficient_privilege OR raise_exception THEN v_ok := v_ok + 1; END;
    IF v_ok <> 2 THEN
        RAISE EXCEPTION 'F5b ledger row changed' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F5b balanced journal accepted; ledger append-only';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F5c every seeded journal balances
SAVEPOINT test_block;
DO $$
DECLARE v_bad INTEGER;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1));
    SELECT count(*) INTO v_bad FROM (
        SELECT journal_id FROM ledger_entries GROUP BY journal_id HAVING SUM(debit_tzs) <> SUM(credit_tzs)) x;
    IF v_bad <> 0 THEN
        RAISE EXCEPTION 'F5c % unbalanced journals in seed data', v_bad USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F5c all % seeded journals balance', (SELECT count(*) FROM journals);
END $$;

-- ---------------- F6 invoices, allocations, reversals ----------------
ROLLBACK TO SAVEPOINT test_block;

-- TEST F6a totals, paid and status are derived and cannot be overwritten
SAVEPOINT test_block;
DO $$
DECLARE v_inv UUID := gen_random_uuid(); v_pay UUID := gen_random_uuid(); r RECORD;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,2));
    INSERT INTO invoices (id, school_id, invoice_no, student_id, term_id, due_date)
    VALUES (v_inv, pg_temp.u(1,1), 'INV-TEST-0001', pg_temp.u(6,15), pg_temp.u(13,2), '2026-08-15');
    INSERT INTO invoice_lines (school_id, invoice_id, fee_item_id, description, amount_tzs) VALUES
     (pg_temp.u(1,1), v_inv, pg_temp.u(34,1), 'Tuition - Term Two', 450000),
     (pg_temp.u(1,1), v_inv, pg_temp.u(34,2), 'Meals - Term Two',   150000);
    INSERT INTO payments (id, school_id, student_id, channel, external_ref, amount_tzs, status, received_at, confirmed_at)
    VALUES (v_pay, pg_temp.u(1,1), pg_temp.u(6,15), 'MPESA', 'TEST-MP-0001', 250000, 'CONFIRMED', now(), now());
    INSERT INTO payment_allocations (school_id, payment_id, invoice_id, amount_tzs) VALUES (pg_temp.u(1,1), v_pay, v_inv, 250000);
    UPDATE invoices SET total_tzs = 1, paid_tzs = 999999 WHERE id = v_inv;          -- must be ignored
    SELECT total_tzs, paid_tzs, balance_tzs, status INTO r FROM invoices WHERE id = v_inv;
    IF r.total_tzs <> 600000 OR r.paid_tzs <> 250000 OR r.balance_tzs <> 350000 OR r.status <> 'PARTIALLY_PAID' THEN
        RAISE EXCEPTION 'F6a derived values wrong: %', row_to_json(r) USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F6a total 600000, paid 250000, balance 350000, PARTIALLY_PAID (overwrite ignored)';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F6b allocation rules: no over-allocation, no pending payment, no other student's invoice
SAVEPOINT test_block;
DO $$
DECLARE v_inv UUID := gen_random_uuid(); v_pay UUID := gen_random_uuid(); v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,2));
    INSERT INTO invoices (id, school_id, invoice_no, student_id, term_id, due_date)
    VALUES (v_inv, pg_temp.u(1,1), 'INV-TEST-0002', pg_temp.u(6,15), pg_temp.u(13,2), '2026-08-15');
    INSERT INTO invoice_lines (school_id, invoice_id, fee_item_id, description, amount_tzs)
    VALUES (pg_temp.u(1,1), v_inv, pg_temp.u(34,1), 'Tuition - Term Two', 100000);
    INSERT INTO payments (id, school_id, student_id, channel, external_ref, amount_tzs, status, received_at, confirmed_at)
    VALUES (v_pay, pg_temp.u(1,1), pg_temp.u(6,15), 'AIRTEL', 'TEST-AT-0001', 500000, 'CONFIRMED', now(), now());
    BEGIN INSERT INTO payment_allocations (school_id, payment_id, invoice_id, amount_tzs) VALUES (pg_temp.u(1,1), v_pay, v_inv, 100001);
    EXCEPTION WHEN raise_exception THEN v_ok := v_ok + 1; END;
    BEGIN INSERT INTO payment_allocations (school_id, payment_id, invoice_id, amount_tzs) VALUES (pg_temp.u(1,1), pg_temp.u(38,8), v_inv, 1000);
    EXCEPTION WHEN raise_exception THEN v_ok := v_ok + 1; END;                       -- HaloPesa payment still PENDING
    BEGIN INSERT INTO payment_allocations (school_id, payment_id, invoice_id, amount_tzs) VALUES (pg_temp.u(1,1), v_pay, pg_temp.u(36,11), 1000);
    EXCEPTION WHEN raise_exception THEN v_ok := v_ok + 1; END;                       -- Amani's invoice
    IF v_ok <> 3 THEN
        RAISE EXCEPTION 'F6b % of 3 bad allocations rejected', v_ok USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F6b over-allocation, pending payment and wrong student rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F6c reversal restores the balance; payments are immutable and never deleted
SAVEPOINT test_block;
DO $$
DECLARE v_ok INTEGER := 0; r RECORD;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,2));
    INSERT INTO payment_reversals (school_id, payment_id, reason, reversed_by, approved_by)
    VALUES (pg_temp.u(1,1), pg_temp.u(38,2), 'Test reversal', pg_temp.u(2,2), pg_temp.u(2,1));     -- Amani's M-Pesa 280000
    SELECT paid_tzs, status INTO r FROM invoices WHERE id = pg_temp.u(36,11);
    IF r.paid_tzs <> 400000 OR r.status <> 'PARTIALLY_PAID'
       OR (SELECT status FROM payments WHERE id = pg_temp.u(38,2)) <> 'REVERSED' THEN
        RAISE EXCEPTION 'F6c reversal not reflected: %', row_to_json(r) USING ERRCODE = 'TF001';
    END IF;
    BEGIN UPDATE payments SET amount_tzs = 1 WHERE id = pg_temp.u(38,1);
    EXCEPTION WHEN raise_exception THEN v_ok := v_ok + 1; END;
    BEGIN UPDATE payments SET status = 'PENDING' WHERE id = pg_temp.u(38,1);
    EXCEPTION WHEN raise_exception THEN v_ok := v_ok + 1; END;
    BEGIN DELETE FROM payments WHERE id = pg_temp.u(38,1);
    EXCEPTION WHEN insufficient_privilege OR raise_exception THEN v_ok := v_ok + 1; END;
    BEGIN INSERT INTO payment_reversals (school_id, payment_id, reason, reversed_by, approved_by)
          VALUES (pg_temp.u(1,1), pg_temp.u(38,1), 'Self-approved', pg_temp.u(2,2), pg_temp.u(2,2));
    EXCEPTION WHEN check_violation THEN v_ok := v_ok + 1; END;
    IF v_ok <> 4 THEN
        RAISE EXCEPTION 'F6c % of 4 forbidden payment changes rejected', v_ok USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F6c reversal -> paid 400000 PARTIALLY_PAID; amount/status/delete/self-approval rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F6d an invoice with payments cannot be cancelled; an unpaid one can
SAVEPOINT test_block;
DO $$
DECLARE v_ok BOOLEAN := FALSE;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    BEGIN
        UPDATE invoices SET cancelled_at = now(), cancel_reason = 'Test' WHERE id = pg_temp.u(36,12);
    EXCEPTION WHEN raise_exception THEN v_ok := TRUE;
    END;
    UPDATE invoices SET cancelled_at = now(), cancel_reason = 'Student left before term' WHERE id = pg_temp.u(36,15);
    IF NOT v_ok OR (SELECT status FROM invoices WHERE id = pg_temp.u(36,15)) <> 'CANCELLED' THEN
        RAISE EXCEPTION 'F6d cancellation rules wrong' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F6d paid invoice not cancellable; unpaid invoice CANCELLED';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F6e overpayment is student credit (ledger 2100), never a negative invoice balance
SAVEPOINT test_block;
DO $$
DECLARE v_credit NUMERIC; v_ledger NUMERIC;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1));
    SELECT credit_tzs INTO v_credit FROM v_student_fee_position WHERE student_id = pg_temp.u(6,16);
    SELECT SUM(credit_tzs - debit_tzs) INTO v_ledger FROM ledger_entries
     WHERE account_id = pg_temp.u(33,6) AND student_id = pg_temp.u(6,16);
    IF v_credit <> 20000 OR v_ledger <> 20000 OR EXISTS (SELECT 1 FROM invoices WHERE balance_tzs < 0 AND status <> 'OVERPAID') THEN
        RAISE EXCEPTION 'F6e credit view=% ledger=%', v_credit, v_ledger USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F6e overpayment 20000 held as student credit in view and ledger';
END $$;

-- ---------------- F7 frozen results and amendments ----------------
ROLLBACK TO SAVEPOINT test_block;

-- TEST F7a published results and summaries cannot be updated or deleted
SAVEPOINT test_block;
DO $$
DECLARE v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    BEGIN UPDATE published_results SET final_score = 100 WHERE enrolment_id = pg_temp.u(24,11);
    EXCEPTION WHEN insufficient_privilege OR raise_exception THEN v_ok := v_ok + 1; END;
    BEGIN DELETE FROM student_term_summaries WHERE enrolment_id = pg_temp.u(24,11);
    EXCEPTION WHEN insufficient_privilege OR raise_exception THEN v_ok := v_ok + 1; END;
    IF v_ok <> 2 THEN
        RAISE EXCEPTION 'F7a frozen result changed' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F7a published results and summaries frozen';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F7b a new version needs an approved amendment
SAVEPOINT test_block;
DO $$
DECLARE v_old published_results%ROWTYPE; v_am UUID := gen_random_uuid();
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    SELECT * INTO v_old FROM published_results WHERE enrolment_id = pg_temp.u(24,11) AND subject_id = pg_temp.u(15,9);
    INSERT INTO result_amendments (id, school_id, published_result_id, new_score, reason, requested_by)
    VALUES (v_am, pg_temp.u(1,1), v_old.id, 90, 'Marking error on paper 2', pg_temp.u(2,3));
    INSERT INTO published_results (school_id, publication_id, enrolment_id, subject_id, final_score, letter_grade, points,
                                   subject_position, supersedes_id, amendment_id)
    VALUES (pg_temp.u(1,1), v_old.publication_id, v_old.enrolment_id, v_old.subject_id, 90, 'A', 1, 1, v_old.id, v_am);
    RAISE EXCEPTION 'F7b unapproved amendment applied' USING ERRCODE = 'TF001';
EXCEPTION WHEN raise_exception THEN RAISE NOTICE 'PASS F7b unapproved new version rejected';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F7c maker-checker: the requester cannot approve; another user can; the old version stays
SAVEPOINT test_block;
DO $$
DECLARE v_old published_results%ROWTYPE; v_am UUID := gen_random_uuid(); v_new UUID; v_maker_blocked BOOLEAN := FALSE;
        v_cur RECORD; v_sum_versions INTEGER;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,3));                                   -- Mwita requests
    SELECT * INTO v_old FROM published_results WHERE enrolment_id = pg_temp.u(24,11) AND subject_id = pg_temp.u(15,9);
    INSERT INTO result_amendments (id, school_id, published_result_id, new_score, reason, requested_by)
    VALUES (v_am, pg_temp.u(1,1), v_old.id, 90, 'Marking error on paper 2', pg_temp.u(2,3));
    BEGIN
        PERFORM amend_result(v_am);
    EXCEPTION WHEN raise_exception THEN v_maker_blocked := TRUE;
    END;
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));                                   -- head teacher approves
    v_new := amend_result(v_am, 'Checked against the script');
    SELECT final_score, letter_grade, supersedes_id INTO v_cur FROM v_current_results
     WHERE enrolment_id = pg_temp.u(24,11) AND subject_id = pg_temp.u(15,9);
    SELECT count(*) INTO v_sum_versions FROM student_term_summaries WHERE enrolment_id = pg_temp.u(24,11);
    IF NOT v_maker_blocked OR v_cur.final_score <> 90 OR v_cur.letter_grade <> 'A' OR v_cur.supersedes_id <> v_old.id
       OR (SELECT final_score FROM published_results WHERE id = v_old.id) <> v_old.final_score OR v_sum_versions <> 2 THEN
        RAISE EXCEPTION 'F7c amendment flow wrong: maker_blocked=% current=% summaries=%', v_maker_blocked, row_to_json(v_cur), v_sum_versions
            USING ERRCODE = 'TF001';
    END IF;
    BEGIN
        PERFORM amend_result(v_am);
        RAISE EXCEPTION 'F7c amendment applied twice' USING ERRCODE = 'TF001';
    EXCEPTION WHEN raise_exception THEN NULL;
    END;
    RAISE NOTICE 'PASS F7c requester blocked; approver created version 2 (90, A); version 1 kept; summary re-versioned';
END $$;

-- ---------------- F9 audit trail ----------------
ROLLBACK TO SAVEPOINT test_block;

-- TEST F9a an UPDATE is audited with school, actor, request id and before/after values
SAVEPOINT test_block;
DO $$
DECLARE v_req UUID := gen_random_uuid(); r RECORD;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,4));
    PERFORM set_config('app.request_id', v_req::text, true);
    UPDATE students SET status = 'SUSPENDED' WHERE id = pg_temp.u(6,15);
    SELECT * INTO r FROM audit_logs WHERE request_id = v_req AND entity_type = 'students';
    IF r.school_id <> pg_temp.u(1,1) OR r.actor_user_id <> pg_temp.u(2,4) OR r.entity_id <> pg_temp.u(6,15)
       OR r.before_data ->> 'status' <> 'ACTIVE' OR r.after_data ->> 'status' <> 'SUSPENDED' THEN
        RAISE EXCEPTION 'F9a audit row wrong: %', row_to_json(r) USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F9a audit row: school, actor, request_id, entity, before/after';
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F9b no audit row contains *_enc, *_hash or password_hash keys
SAVEPOINT test_block;
DO $$
DECLARE v_req UUID := gen_random_uuid(); v_leaks INTEGER;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    PERFORM set_config('app.request_id', v_req::text, true);
    UPDATE users SET middle_name = 'Test' WHERE id = pg_temp.u(2,21);                    -- a row with phone_enc/phone_hash
    SELECT count(*) INTO v_leaks
    FROM audit_logs a,
         LATERAL (SELECT jsonb_object_keys(COALESCE(a.before_data, '{}'::jsonb)) AS k
                  UNION ALL SELECT jsonb_object_keys(COALESCE(a.after_data, '{}'::jsonb))) keys
    WHERE keys.k LIKE '%\_enc' OR keys.k LIKE '%\_hash' OR keys.k = 'password_hash';
    IF v_leaks <> 0 OR NOT EXISTS (SELECT 1 FROM audit_logs WHERE request_id = v_req AND entity_type = 'users') THEN
        RAISE EXCEPTION 'F9b % secret keys found in audit_logs', v_leaks USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F9b audit rows redact *_enc, *_hash and password_hash (% rows scanned)', (SELECT count(*) FROM audit_logs);
END $$;
ROLLBACK TO SAVEPOINT test_block;

-- TEST F9c audit_logs is append-only
SAVEPOINT test_block;
DO $$
DECLARE v_ok INTEGER := 0;
BEGIN
    PERFORM pg_temp.ctx(pg_temp.u(1,1), pg_temp.u(2,1));
    BEGIN UPDATE audit_logs SET action = 'LOGIN';
    EXCEPTION WHEN insufficient_privilege OR raise_exception THEN v_ok := v_ok + 1; END;
    BEGIN DELETE FROM audit_logs;
    EXCEPTION WHEN insufficient_privilege OR raise_exception THEN v_ok := v_ok + 1; END;
    IF v_ok <> 2 THEN
        RAISE EXCEPTION 'F9c audit log changed' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'PASS F9c audit_logs append-only';
END $$;
ROLLBACK TO SAVEPOINT test_block;

ROLLBACK;

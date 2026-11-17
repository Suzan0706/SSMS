-- =====================================================================
--  Database integrity tests. Run on a database loaded with schema.sql + seed.sql:
--      psql -v ON_ERROR_STOP=1 -d sms_test -f db/tests/test_constraints.sql
--  Each block must raise the expected error; if the bad change is accepted the
--  block raises SQLSTATE TF001 and the script stops. Everything is rolled back.
-- =====================================================================
BEGIN;

DO $$ BEGIN   -- T1 instructor double-booking
    INSERT INTO schedules (offering_id, stream, term_id, subject_id, instructor_id, room_id, day_of_week, time_start, time_end)
    VALUES (1, 'A', 1, 9, 1, 1, 1, '08:20', '09:00');
    RAISE EXCEPTION 'T1 accepted an instructor clash' USING ERRCODE = 'TF001';
EXCEPTION WHEN exclusion_violation THEN RAISE NOTICE 'T1 ok: instructor clash rejected';
END $$;

DO $$ BEGIN   -- T2 room double-booking
    INSERT INTO schedules (offering_id, stream, term_id, subject_id, instructor_id, room_id, day_of_week, time_start, time_end)
    VALUES (1, 'A', 1, 5, 2, 2, 1, '08:10', '08:30');
    RAISE EXCEPTION 'T2 accepted a room clash' USING ERRCODE = 'TF001';
EXCEPTION WHEN exclusion_violation THEN RAISE NOTICE 'T2 ok: room clash rejected';
END $$;

DO $$ BEGIN   -- T3 two lessons for one class stream at once
    INSERT INTO schedules (offering_id, stream, term_id, subject_id, instructor_id, room_id, day_of_week, time_start, time_end)
    VALUES (2, 'A', 1, 7, 3, 5, 1, '08:20', '08:50');
    RAISE EXCEPTION 'T3 accepted a class clash' USING ERRCODE = 'TF001';
EXCEPTION WHEN exclusion_violation THEN RAISE NOTICE 'T3 ok: class clash rejected';
END $$;

DO $$ BEGIN   -- T4 back-to-back periods are allowed ([start, end) ranges)
    INSERT INTO schedules (offering_id, stream, term_id, subject_id, instructor_id, room_id, day_of_week, time_start, time_end)
    VALUES (1, 'A', 1, 9, 1, 1, 3, '08:40', '09:20');
    RAISE NOTICE 'T4 ok: back-to-back period accepted';
END $$;

DO $$ DECLARE v_id BIGINT; BEGIN   -- T5 student in two overlapping sessions
    INSERT INTO schedules (offering_id, stream, term_id, subject_id, instructor_id, room_id, day_of_week, time_start, time_end)
    VALUES (1, 'B', 1, 7, 3, 5, 1, '08:10', '08:30') RETURNING schedule_id INTO v_id;
    INSERT INTO enrolment_schedules (enrolment_id, schedule_id) VALUES (1, v_id);
    RAISE EXCEPTION 'T5 accepted a student clash' USING ERRCODE = 'TF001';
EXCEPTION WHEN exclusion_violation THEN RAISE NOTICE 'T5 ok: student clash rejected';
END $$;

DO $$ BEGIN   -- T6 one active enrolment per student per year
    INSERT INTO enrolments (enrolment_no, student_id, offering_id) VALUES ('ENR-TEST-1', 1, 1);
    RAISE EXCEPTION 'T6 accepted a second enrolment' USING ERRCODE = 'TF001';
EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'T6 ok: second enrolment rejected';
END $$;

DO $$ BEGIN   -- T7 phone format
    UPDATE users SET phone = '0754000001' WHERE user_id = 1;
    RAISE EXCEPTION 'T7 accepted a bad phone' USING ERRCODE = 'TF001';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'T7 ok: bad phone rejected';
END $$;

DO $$ BEGIN   -- T8 completed transaction cannot be edited
    UPDATE transactions SET amount_tzs = 1 WHERE trans_id = 1;
    RAISE EXCEPTION 'T8 edited a completed transaction' USING ERRCODE = 'TF001';
EXCEPTION WHEN raise_exception THEN RAISE NOTICE 'T8 ok: ledger edit rejected';
END $$;

DO $$ BEGIN   -- T9 transaction cannot be deleted
    DELETE FROM transactions WHERE trans_id = 1;
    RAISE EXCEPTION 'T9 deleted a transaction' USING ERRCODE = 'TF001';
EXCEPTION WHEN raise_exception THEN RAISE NOTICE 'T9 ok: ledger delete rejected';
END $$;

DO $$ BEGIN   -- T10 same mobile-money receipt posted twice
    INSERT INTO transactions (trans_no, trans_type, trans_name, student_id, invoice_id, amount_tzs,
                              payment_method, reference_no, status, source, recorded_by)
    VALUES ('TXN-TEST-1', 'PAYMENT', 'dup', 1, 1, 1000, 'MPESA', 'QKJ7H2LM9P', 'COMPLETED', 'MANUAL', 3);
    RAISE EXCEPTION 'T10 accepted a double posting' USING ERRCODE = 'TF001';
EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'T10 ok: double posting rejected';
END $$;

DO $$ BEGIN   -- T11 payment against another student's invoice
    INSERT INTO transactions (trans_no, trans_type, trans_name, student_id, invoice_id, amount_tzs,
                              payment_method, reference_no, status, source, recorded_by)
    VALUES ('TXN-TEST-2', 'PAYMENT', 'wrong', 2, 1, 1000, 'MPESA', 'ZZZ-TEST', 'COMPLETED', 'MANUAL', 3);
    RAISE EXCEPTION 'T11 accepted a payment to another student''s invoice' USING ERRCODE = 'TF001';
EXCEPTION WHEN foreign_key_violation THEN RAISE NOTICE 'T11 ok: wrong-student invoice rejected';
END $$;

DO $$ BEGIN   -- T12 audit log is append-only
    UPDATE audit_logs SET action = 'LOGIN';
    RAISE EXCEPTION 'T12 edited the audit log' USING ERRCODE = 'TF001';
EXCEPTION WHEN raise_exception THEN RAISE NOTICE 'T12 ok: audit edit rejected';
END $$;

DO $$ BEGIN   -- T13 attendance only for students linked to the session
    INSERT INTO attendance (enrolment_id, schedule_id, attendance_date, status, recorded_by)
    VALUES (3, 1, '2026-03-02', 'PRESENT', 4);
    RAISE EXCEPTION 'T13 accepted attendance for a student not in the class' USING ERRCODE = 'TF001';
EXCEPTION WHEN foreign_key_violation THEN RAISE NOTICE 'T13 ok: attendance outside class rejected';
END $$;

DO $$ BEGIN   -- T14 INVALID document needs remarks
    UPDATE enrolment_documents SET status = 'INVALID', validated_by = 6, validated_at = now() WHERE document_id = 4;
    RAISE EXCEPTION 'T14 accepted INVALID without remarks' USING ERRCODE = 'TF001';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'T14 ok: INVALID without remarks rejected';
END $$;

DO $$ DECLARE v_count INT; BEGIN   -- T15 audit trigger records actor and never the password hash
    PERFORM set_config('app.user_id', '2', true), set_config('app.user_role', 'REGISTRAR', true);
    UPDATE students SET current_status = 'SUSPENDED' WHERE student_id = 2;
    SELECT count(*) INTO v_count FROM audit_logs
     WHERE entity_type = 'students' AND entity_id = '2' AND action = 'UPDATE' AND actor_user_id = 2
       AND new_values->>'current_status' = 'SUSPENDED';
    IF v_count <> 1 THEN RAISE EXCEPTION 'T15 audit row missing' USING ERRCODE = 'TF001'; END IF;
    UPDATE users SET middle_name = 'X' WHERE user_id = 1;           -- users rows hold password_hash
    IF EXISTS (SELECT 1 FROM audit_logs WHERE old_values ? 'password_hash' OR new_values ? 'password_hash') THEN
        RAISE EXCEPTION 'T15 password hash leaked into audit_logs' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'T15 ok: audit row written with actor, no password hash';
END $$;

DO $$ BEGIN   -- T16 derived balances
    IF (SELECT payment_status FROM v_invoice_balances WHERE invoice_id = 1) <> 'PAID'
       OR (SELECT balance_tzs FROM v_invoice_balances WHERE invoice_id = 2) <> 480000 THEN
        RAISE EXCEPTION 'T16 wrong invoice balances' USING ERRCODE = 'TF001';
    END IF;
    RAISE NOTICE 'T16 ok: invoice balances derived correctly';
END $$;

ROLLBACK;

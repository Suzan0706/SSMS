-- Normalisation pass: remove values that can be derived, and tie the copies that must stay to their source.

-- Data first, as the migration login: with FORCE RLS the owner role would see no rows and silently change nothing.
UPDATE enrolment_requirements SET education_level_id = NULL WHERE class_id IS NOT NULL;
UPDATE attendance_sessions SET stream_id = NULL WHERE kind = 'LESSON';

SET ROLE ssms_owner;

-- A stop belongs to one route, so the route comes from the stop.
ALTER TABLE transport_assignments DROP COLUMN route_id;

-- The counts come from the run's items.
ALTER TABLE reconciliation_runs DROP COLUMN matched_count, DROP COLUMN exception_count;

-- A lesson's stream comes from its timetable slot.
ALTER TABLE attendance_sessions DROP CONSTRAINT ck_as_scope;
ALTER TABLE attendance_sessions ADD CONSTRAINT ck_as_scope CHECK (
    (kind = 'GATE' AND stream_id IS NULL AND timetable_slot_id IS NULL) OR
    (kind = 'REGISTER' AND stream_id IS NOT NULL AND timetable_slot_id IS NULL) OR
    (kind = 'LESSON' AND stream_id IS NULL AND timetable_slot_id IS NOT NULL));

-- A class belongs to one level: a requirement names the level or the class, never both.
ALTER TABLE enrolment_requirements ADD CONSTRAINT ck_er_scope CHECK (education_level_id IS NULL OR class_id IS NULL);

-- These rows also stand alone (an enrolment needs no application), so the columns stay; when the link is set, the
-- database now guarantees both sides agree.
ALTER TABLE enrolment_applications
    ADD CONSTRAINT uq_ea_student_year UNIQUE (school_id, id, student_id, academic_year_id);
ALTER TABLE enrolments DROP CONSTRAINT fk_enrolments_application;
ALTER TABLE enrolments ADD CONSTRAINT fk_enrolments_application
    FOREIGN KEY (school_id, application_id, student_id, academic_year_id)
    REFERENCES enrolment_applications (school_id, id, student_id, academic_year_id);

ALTER TABLE accommodation_requests ADD CONSTRAINT uq_ar_student_term UNIQUE (school_id, id, student_id, term_id);
ALTER TABLE hostel_allocations DROP CONSTRAINT fk_ha_request;
ALTER TABLE hostel_allocations ADD CONSTRAINT fk_ha_request
    FOREIGN KEY (school_id, request_id, student_id, term_id)
    REFERENCES accommodation_requests (school_id, id, student_id, term_id);

ALTER TABLE payments ADD CONSTRAINT uq_payments_student_amount UNIQUE (school_id, id, student_id, amount_tzs);
ALTER TABLE bank_deposit_confirmations DROP CONSTRAINT fk_bd_payment;
ALTER TABLE bank_deposit_confirmations ADD CONSTRAINT fk_bd_payment
    FOREIGN KEY (school_id, payment_id, student_id, amount_tzs)
    REFERENCES payments (school_id, id, student_id, amount_tzs);

ALTER TABLE payment_reversals ADD CONSTRAINT uq_prv_payment UNIQUE (school_id, id, payment_id);
ALTER TABLE payment_reversal_requests DROP CONSTRAINT fk_prr_reversal;
ALTER TABLE payment_reversal_requests ADD CONSTRAINT fk_prr_reversal
    FOREIGN KEY (school_id, reversal_id, payment_id) REFERENCES payment_reversals (school_id, id, payment_id);

RESET ROLE;

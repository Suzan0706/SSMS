-- Phase 1 (Foundation). Runs as the migration role; objects stay owned by ssms_owner.
SET ROLE ssms_owner;

-- Admission numbers are <prefix>-<year>-<seq>, e.g. TZ-2026-0001 (matches ck_students_admission_no).
ALTER TABLE school_settings
    ADD COLUMN admission_prefix VARCHAR(4) NOT NULL DEFAULT 'TZ',
    ADD CONSTRAINT ck_school_settings_admission_prefix CHECK (admission_prefix ~ '^[A-Z]{2,4}$');

-- Phase 0 gap: the history table accepted any status text.
ALTER TABLE student_status_history
    ADD CONSTRAINT ck_status_history_old CHECK (old_status IS NULL OR old_status IN
        ('APPLICANT','ACTIVE','SUSPENDED','TRANSFERRED','GRADUATED','DROPPED_OUT')),
    ADD CONSTRAINT ck_status_history_new CHECK (new_status IN
        ('APPLICANT','ACTIVE','SUSPENDED','TRANSFERRED','GRADUATED','DROPPED_OUT'));


-- Login bookkeeping (last_login_at, failed_login_count, locked_until) is covered by explicit LOGIN /
-- LOGIN_FAILED audit events, so a change in only those columns no longer writes an UPDATE audit row.
CREATE OR REPLACE FUNCTION fn_audit_row() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_old JSONB;
    v_new JSONB;
    v_row JSONB;
    c_bookkeeping CONSTANT TEXT[] := ARRAY['updated_at','last_login_at','failed_login_count','locked_until'];
BEGIN
    IF TG_OP IN ('UPDATE','DELETE') THEN v_old := fn_redact(to_jsonb(OLD)); END IF;
    IF TG_OP IN ('INSERT','UPDATE') THEN v_new := fn_redact(to_jsonb(NEW)); END IF;
    IF TG_OP = 'UPDATE' AND (v_old - c_bookkeeping) = (v_new - c_bookkeeping) THEN
        RETURN NULL;                                       -- nothing visible changed
    END IF;
    v_row := COALESCE(v_new, v_old);
    INSERT INTO audit_logs (school_id, actor_user_id, actor_platform_id, action, entity_type, entity_id,
                            before_data, after_data, ip_address, request_id)
    VALUES ((v_row ->> 'school_id')::uuid,
            app_user_id(),
            NULLIF(current_setting('app.platform_admin_id', true), '')::uuid,
            TG_OP, TG_TABLE_NAME, (v_row ->> 'id')::uuid, v_old, v_new,
            NULLIF(current_setting('app.client_ip', true), '')::inet,
            NULLIF(current_setting('app.request_id', true), '')::uuid);
    RETURN NULL;
END $$;

RESET ROLE;

-- Phase 3 (Finance). Runs as the migration role; objects stay owned by ssms_owner.
SET ROLE ssms_owner;

-- Phase 0 defect: ck_journals_source allows 'INVOICE_CANCEL' (14 characters) but the column was VARCHAR(12).
ALTER TABLE journals ALTER COLUMN source_type TYPE VARCHAR(14);

-- A reversal is requested by one person and approved by another (maker-checker). payment_reversals keeps only
-- approved reversals (both people recorded); the request and its decision live here.
CREATE TABLE payment_reversal_requests (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      UUID         NOT NULL REFERENCES schools (id),
    payment_id     UUID         NOT NULL,
    reason         VARCHAR(300) NOT NULL,
    requested_by   UUID         NOT NULL,
    status         VARCHAR(10)  NOT NULL DEFAULT 'PENDING',
    decided_by     UUID,
    decided_at     TIMESTAMPTZ,
    decision_note  VARCHAR(300),
    reversal_id    UUID,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by     UUID,
    CONSTRAINT uq_payment_reversal_requests_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_prr_payment   FOREIGN KEY (school_id, payment_id)   REFERENCES payments (school_id, id),
    CONSTRAINT fk_prr_requester FOREIGN KEY (school_id, requested_by) REFERENCES users (school_id, id),
    CONSTRAINT fk_prr_decider   FOREIGN KEY (school_id, decided_by)   REFERENCES users (school_id, id),
    CONSTRAINT fk_prr_reversal  FOREIGN KEY (school_id, reversal_id)  REFERENCES payment_reversals (school_id, id),
    CONSTRAINT fk_prr_created_by FOREIGN KEY (school_id, created_by)  REFERENCES users (school_id, id),
    CONSTRAINT ck_prr_status CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    CONSTRAINT ck_prr_decision CHECK (status = 'PENDING' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)),
    CONSTRAINT ck_prr_approved CHECK ((status = 'APPROVED') = (reversal_id IS NOT NULL)),
    CONSTRAINT ck_prr_maker_checker CHECK (decided_by IS NULL OR decided_by <> requested_by)
);
CREATE UNIQUE INDEX uq_prr_pending ON payment_reversal_requests (school_id, payment_id) WHERE status = 'PENDING';

ALTER TABLE payment_reversal_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_reversal_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON payment_reversal_requests
    USING (school_id = app_school_id()) WITH CHECK (school_id = app_school_id());
CREATE TRIGGER trg_payment_reversal_requests_updated BEFORE UPDATE ON payment_reversal_requests
    FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at();
CREATE TRIGGER trg_payment_reversal_requests_audit AFTER INSERT OR UPDATE OR DELETE ON payment_reversal_requests
    FOR EACH ROW EXECUTE FUNCTION fn_audit_row();

RESET ROLE;
GRANT SELECT, INSERT, UPDATE ON payment_reversal_requests TO ssms_app, ssms_platform;
GRANT SELECT ON payment_reversal_requests TO ssms_reporting;

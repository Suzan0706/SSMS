-- Phase 3 of the extension (design/20 §20.7): stored_files, taken unchanged from design/sql/extension.sql §1.
SET ROLE ssms_owner;

CREATE TABLE stored_files (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID         NOT NULL REFERENCES schools (id),
    storage_key   VARCHAR(255) NOT NULL,                 -- random; never derived from the original name
    purpose       VARCHAR(20)  NOT NULL,
    original_name VARCHAR(200) NOT NULL,
    content_type  VARCHAR(100) NOT NULL,                 -- detected from the bytes, not from the extension
    size_bytes    INTEGER      NOT NULL,
    sha256        CHAR(64)     NOT NULL,
    scan_status   VARCHAR(10)  NOT NULL DEFAULT 'PENDING',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by    UUID,
    deleted_at    TIMESTAMPTZ,
    CONSTRAINT uq_stored_files_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_stored_files_key UNIQUE (storage_key),
    CONSTRAINT fk_sf_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_sf_purpose CHECK (purpose IN ('PHOTO','STUDY_MATERIAL','HOMEWORK','SUBMISSION','RECEIPT','CERT_TEMPLATE')),
    CONSTRAINT ck_sf_size CHECK (size_bytes > 0 AND size_bytes <= 20 * 1024 * 1024),
    CONSTRAINT ck_sf_scan CHECK (scan_status IN ('PENDING','CLEAN','INFECTED','SKIPPED'))
);
CREATE INDEX ix_stored_files_creator ON stored_files (school_id, created_by) WHERE deleted_at IS NULL;

ALTER TABLE stored_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE stored_files FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON stored_files USING (school_id = app_school_id()) WITH CHECK (school_id = app_school_id());
CREATE TRIGGER trg_stored_files_updated BEFORE UPDATE ON stored_files FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at();
CREATE TRIGGER trg_stored_files_audit AFTER INSERT OR UPDATE OR DELETE ON stored_files FOR EACH ROW EXECUTE FUNCTION fn_audit_row();

RESET ROLE;
GRANT SELECT, INSERT, UPDATE ON stored_files TO ssms_app;
GRANT SELECT ON stored_files TO ssms_platform, ssms_reporting;

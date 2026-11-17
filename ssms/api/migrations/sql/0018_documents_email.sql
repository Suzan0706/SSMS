-- Phase 11 of the extension (design/20 §20.7): tables taken unchanged from design/sql/extension.sql §7 and §9,
-- the last part of that file.
SET ROLE ssms_owner;

CREATE TABLE certificate_templates (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      UUID          NOT NULL REFERENCES schools (id),
    kind           VARCHAR(12)   NOT NULL,
    name           VARCHAR(80)   NOT NULL,
    language       CHAR(2)       NOT NULL,
    body           VARCHAR(4000) NOT NULL,               -- text with {{placeholders}}; rendered by the PDF service
    background_file_id UUID,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by     UUID,
    deleted_at     TIMESTAMPTZ,
    CONSTRAINT uq_certificate_templates_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ct_file FOREIGN KEY (school_id, background_file_id) REFERENCES stored_files (school_id, id),
    CONSTRAINT fk_ct_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_ct_kind CHECK (kind IN ('LEAVING','TRANSFER','CHARACTER','ACHIEVEMENT')),
    CONSTRAINT ck_ct_lang CHECK (language IN ('sw','en'))
);

CREATE TABLE certificates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id       UUID         NOT NULL REFERENCES schools (id),
    template_id     UUID         NOT NULL,
    student_id      UUID         NOT NULL,
    serial_no       VARCHAR(20)  NOT NULL,                -- from document_sequences
    issued_on       DATE         NOT NULL,
    rendered_text   VARCHAR(4000) NOT NULL,               -- frozen at issue, so later template edits never change it
    revoked_at      TIMESTAMPTZ,
    revoked_reason  VARCHAR(300),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by      UUID,
    CONSTRAINT uq_certificates_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_certificates_serial UNIQUE (school_id, serial_no),
    CONSTRAINT fk_cert_template FOREIGN KEY (school_id, template_id) REFERENCES certificate_templates (school_id, id),
    CONSTRAINT fk_cert_student FOREIGN KEY (school_id, student_id) REFERENCES students (school_id, id),
    CONSTRAINT fk_cert_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_cert_revoked CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL))
);

-- Issued certificates are frozen; only revocation may be recorded, once.
CREATE FUNCTION fn_certificates_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'certificates are never deleted; revoke them' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL
       OR (NEW.template_id, NEW.student_id, NEW.serial_no, NEW.issued_on, NEW.rendered_text)
          IS DISTINCT FROM (OLD.template_id, OLD.student_id, OLD.serial_no, OLD.issued_on, OLD.rendered_text) THEN
        RAISE EXCEPTION 'certificate % is frozen', OLD.serial_no USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_certificates_frozen BEFORE UPDATE OR DELETE ON certificates
    FOR EACH ROW EXECUTE FUNCTION fn_certificates_frozen();

CREATE TABLE identity_cards (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id    UUID        NOT NULL REFERENCES schools (id),
    user_id      UUID        NOT NULL,                    -- student or staff login
    card_no      VARCHAR(20) NOT NULL,                    -- the only thing in the QR code
    valid_until  DATE        NOT NULL,
    revoked_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   UUID,
    CONSTRAINT uq_identity_cards_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_identity_cards_no UNIQUE (school_id, card_no),
    CONSTRAINT fk_ic_user FOREIGN KEY (school_id, user_id) REFERENCES users (school_id, id),
    CONSTRAINT fk_ic_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id)
);
CREATE UNIQUE INDEX uq_identity_cards_live ON identity_cards (school_id, user_id) WHERE revoked_at IS NULL;

CREATE TABLE email_messages (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id            UUID         NOT NULL REFERENCES schools (id),
    to_user_id           UUID         NOT NULL,
    template_key         VARCHAR(40),
    language             CHAR(2)      NOT NULL,
    subject              VARCHAR(200) NOT NULL,
    body                 TEXT         NOT NULL,
    provider             VARCHAR(12)  NOT NULL,
    provider_message_id  VARCHAR(120),
    status               VARCHAR(10)  NOT NULL DEFAULT 'QUEUED',
    error                VARCHAR(300),
    idempotency_key      VARCHAR(80)  NOT NULL,
    related_entity       VARCHAR(40),
    related_id           UUID,
    queued_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    sent_at              TIMESTAMPTZ,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by           UUID,
    CONSTRAINT uq_email_messages_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_email_messages_idem UNIQUE (school_id, idempotency_key),
    CONSTRAINT fk_em_user FOREIGN KEY (school_id, to_user_id) REFERENCES users (school_id, id),
    CONSTRAINT fk_em_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_em_lang CHECK (language IN ('sw','en')),
    CONSTRAINT ck_em_provider CHECK (provider IN ('SMTP','CONSOLE')),
    CONSTRAINT ck_em_status CHECK (status IN ('QUEUED','SENT','FAILED','SKIPPED'))
);

-- A staff photograph for staff ID cards (students have photo_file_key since Phase 0).
ALTER TABLE staff ADD COLUMN photo_file_key VARCHAR(255);

-- Certificates and ID cards are numbered like invoices and receipts.
ALTER TABLE document_sequences DROP CONSTRAINT ck_document_sequences_type;
ALTER TABLE document_sequences ADD CONSTRAINT ck_document_sequences_type
    CHECK (doc_type IN ('ADMISSION','APPLICATION','INVOICE','RECEIPT','JOURNAL','CASH_ENTRY','LIBRARY_CARD',
                        'CERTIFICATE','ID_CARD'));

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['certificate_templates','certificates','identity_cards','email_messages'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (school_id = app_school_id()) '
                       'WITH CHECK (school_id = app_school_id())', t);
        EXECUTE format('CREATE TRIGGER trg_%s_updated BEFORE UPDATE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at()', t, t);
        EXECUTE format('CREATE TRIGGER trg_%s_audit AFTER INSERT OR UPDATE OR DELETE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_audit_row()', t, t);
        EXECUTE format('GRANT SELECT ON %I TO ssms_platform, ssms_reporting', t);
    END LOOP;
END $$;

RESET ROLE;
GRANT SELECT, INSERT, UPDATE ON certificate_templates, certificates, identity_cards, email_messages TO ssms_app;

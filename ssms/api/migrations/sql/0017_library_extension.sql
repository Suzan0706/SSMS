-- Phase 9 of the extension (design/20 §20.7): library tables taken unchanged from design/sql/extension.sql §8.
SET ROLE ssms_owner;

CREATE TABLE library_categories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    name        VARCHAR(80) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_library_categories_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_lc_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id)
);
CREATE UNIQUE INDEX uq_library_categories_name ON library_categories (school_id, lower(name)) WHERE deleted_at IS NULL;

CREATE TABLE library_publishers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID         NOT NULL REFERENCES schools (id),
    name        VARCHAR(120) NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_library_publishers_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_lp_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id)
);
CREATE UNIQUE INDEX uq_library_publishers_name ON library_publishers (school_id, lower(name)) WHERE deleted_at IS NULL;

ALTER TABLE library_books
    ADD COLUMN category_id  UUID,
    ADD COLUMN publisher_id UUID,
    ADD CONSTRAINT fk_lb_category  FOREIGN KEY (school_id, category_id)  REFERENCES library_categories (school_id, id),
    ADD CONSTRAINT fk_lb_publisher FOREIGN KEY (school_id, publisher_id) REFERENCES library_publishers (school_id, id);

CREATE TABLE library_cards (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    user_id     UUID        NOT NULL,
    card_no     VARCHAR(20) NOT NULL,
    issued_on   DATE        NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    CONSTRAINT uq_library_cards_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_library_cards_no UNIQUE (school_id, card_no),
    CONSTRAINT fk_lcard_user FOREIGN KEY (school_id, user_id) REFERENCES users (school_id, id),
    CONSTRAINT fk_lcard_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id)
);
CREATE UNIQUE INDEX uq_library_cards_live ON library_cards (school_id, user_id) WHERE revoked_at IS NULL;


-- Library cards are numbered like invoices and receipts.
ALTER TABLE document_sequences DROP CONSTRAINT ck_document_sequences_type;
ALTER TABLE document_sequences ADD CONSTRAINT ck_document_sequences_type
    CHECK (doc_type IN ('ADMISSION','APPLICATION','INVOICE','RECEIPT','JOURNAL','CASH_ENTRY','LIBRARY_CARD'));

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['library_categories','library_publishers','library_cards'] LOOP
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
GRANT SELECT, INSERT, UPDATE ON library_categories, library_publishers, library_cards TO ssms_app;

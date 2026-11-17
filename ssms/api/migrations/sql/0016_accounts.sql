-- Phase 8 of the extension (design/20 §20.7): tables and the journal-source change taken unchanged from
-- design/sql/extension.sql §5 and §10; then default accounts, categories and the fine fee item for every school.
SET ROLE ssms_owner;

CREATE TABLE finance_categories (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id          UUID        NOT NULL REFERENCES schools (id),
    kind               VARCHAR(7)  NOT NULL,
    name_en            VARCHAR(80) NOT NULL,
    name_sw            VARCHAR(80) NOT NULL,
    ledger_account_id  UUID        NOT NULL,              -- an INCOME or EXPENSE account (checked by the service)
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by         UUID,
    deleted_at         TIMESTAMPTZ,
    CONSTRAINT uq_finance_categories_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_fc_account FOREIGN KEY (school_id, ledger_account_id) REFERENCES ledger_accounts (school_id, id),
    CONSTRAINT fk_fc_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_fc_kind CHECK (kind IN ('INCOME','EXPENSE'))
);
CREATE UNIQUE INDEX uq_finance_categories_name ON finance_categories (school_id, kind, lower(name_en)) WHERE deleted_at IS NULL;

CREATE TABLE cash_entries (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id             UUID          NOT NULL REFERENCES schools (id),
    entry_no              VARCHAR(20)   NOT NULL,          -- from document_sequences
    category_id           UUID          NOT NULL,
    entry_date            DATE          NOT NULL,
    amount_tzs            NUMERIC(14,2) NOT NULL,
    method                VARCHAR(12)   NOT NULL,
    reference             VARCHAR(60),
    party                 VARCHAR(120),                    -- payer or payee
    description           VARCHAR(300)  NOT NULL,
    attachment_file_id    UUID,
    journal_id            UUID          NOT NULL,
    status                VARCHAR(8)    NOT NULL DEFAULT 'POSTED',
    reversal_requested_by UUID,
    reversal_approved_by  UUID,
    reversal_reason       VARCHAR(300),
    reversal_journal_id   UUID,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by            UUID,
    CONSTRAINT uq_cash_entries_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_cash_entries_no UNIQUE (school_id, entry_no),
    CONSTRAINT fk_ce_category FOREIGN KEY (school_id, category_id) REFERENCES finance_categories (school_id, id),
    CONSTRAINT fk_ce_file FOREIGN KEY (school_id, attachment_file_id) REFERENCES stored_files (school_id, id),
    CONSTRAINT fk_ce_journal FOREIGN KEY (school_id, journal_id) REFERENCES journals (school_id, id),
    CONSTRAINT fk_ce_reversal_journal FOREIGN KEY (school_id, reversal_journal_id) REFERENCES journals (school_id, id),
    CONSTRAINT fk_ce_requested FOREIGN KEY (school_id, reversal_requested_by) REFERENCES users (school_id, id),
    CONSTRAINT fk_ce_approved FOREIGN KEY (school_id, reversal_approved_by) REFERENCES users (school_id, id),
    CONSTRAINT fk_ce_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_ce_amount CHECK (amount_tzs > 0),
    CONSTRAINT ck_ce_method CHECK (method IN ('CASH','BANK','MOBILE_MONEY','CHEQUE')),
    CONSTRAINT ck_ce_status CHECK (status IN ('POSTED','REVERSED')),
    CONSTRAINT ck_ce_reversal CHECK ((status = 'REVERSED') = (reversal_journal_id IS NOT NULL AND reversal_approved_by IS NOT NULL
                                                              AND reversal_requested_by IS NOT NULL AND reversal_reason IS NOT NULL)),
    CONSTRAINT ck_ce_maker_checker CHECK (reversal_approved_by IS NULL OR reversal_approved_by <> reversal_requested_by)
);
CREATE INDEX ix_cash_entries_date ON cash_entries (school_id, entry_date);

-- Posted entries are facts: only the reversal columns may change, once.
CREATE FUNCTION fn_cash_entries_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'cash entries are never deleted; reverse them' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'REVERSED' THEN
        RAISE EXCEPTION 'cash entry % is already reversed', OLD.entry_no USING ERRCODE = 'check_violation';
    END IF;
    IF (NEW.entry_no, NEW.category_id, NEW.entry_date, NEW.amount_tzs, NEW.method, NEW.journal_id, NEW.description)
       IS DISTINCT FROM (OLD.entry_no, OLD.category_id, OLD.entry_date, OLD.amount_tzs, OLD.method, OLD.journal_id, OLD.description) THEN
        RAISE EXCEPTION 'a posted cash entry cannot be edited; reverse it and post a new one' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_cash_entries_guard BEFORE UPDATE OR DELETE ON cash_entries
    FOR EACH ROW EXECUTE FUNCTION fn_cash_entries_guard();

CREATE TABLE fine_rules (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      UUID          NOT NULL REFERENCES schools (id),
    kind           VARCHAR(12)   NOT NULL,
    fee_item_id    UUID          NOT NULL,                 -- the invoice line the fine is charged as
    amount_tzs     NUMERIC(14,2) NOT NULL,                 -- flat (LATE_FEE) or per day (LIBRARY_DAY)
    grace_days     SMALLINT      NOT NULL DEFAULT 0,
    active         BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_by     UUID,
    CONSTRAINT uq_fine_rules_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_fr_item FOREIGN KEY (school_id, fee_item_id) REFERENCES fee_items (school_id, id),
    CONSTRAINT fk_fr_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_fr_kind CHECK (kind IN ('LATE_FEE','LIBRARY_DAY')),
    CONSTRAINT ck_fr_amount CHECK (amount_tzs > 0),
    CONSTRAINT ck_fr_grace CHECK (grace_days >= 0)
);
CREATE UNIQUE INDEX uq_fine_rules_active ON fine_rules (school_id, kind) WHERE active;

-- Keep every source the constraint allows today and add the two new ones.
DO $$
DECLARE v_sources text;
BEGIN
    SELECT string_agg(quote_literal(v), ',' ORDER BY v) INTO v_sources FROM (
        SELECT m[1] AS v
        FROM pg_constraint c, regexp_matches(pg_get_constraintdef(c.oid), '''([A-Z_]+)''', 'g') m
        WHERE c.conname = 'ck_journals_source' AND c.conrelid = 'journals'::regclass
        UNION SELECT 'CASH_ENTRY' UNION SELECT 'CASH_REVERSE') s;
    ALTER TABLE journals DROP CONSTRAINT ck_journals_source;
    EXECUTE format('ALTER TABLE journals ADD CONSTRAINT ck_journals_source CHECK (source_type IN (%s))', v_sources);
END $$;

-- The late-payment fine is charged as an invoice line of its own fee item.
ALTER TABLE fee_items DROP CONSTRAINT ck_fee_items_code;
ALTER TABLE fee_items ADD CONSTRAINT ck_fee_items_code
    CHECK (code IN ('TUITION','BOARDING','TRANSPORT','MEALS','UNIFORM','EXAMINATION','DEVELOPMENT','OTHER','FINE'));

-- Cash entries are numbered like invoices and receipts.
ALTER TABLE document_sequences DROP CONSTRAINT ck_document_sequences_type;
ALTER TABLE document_sequences ADD CONSTRAINT ck_document_sequences_type
    CHECK (doc_type IN ('ADMISSION','APPLICATION','INVOICE','RECEIPT','JOURNAL','CASH_ENTRY'));

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['finance_categories','cash_entries','fine_rules'] LOOP
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
GRANT SELECT, INSERT, UPDATE ON finance_categories, cash_entries, fine_rules TO ssms_app;
-- School onboarding (platform console) creates the default categories of a new school.
GRANT INSERT, UPDATE ON finance_categories TO ssms_platform;

-- Default accounts, categories and the fine fee item for every school (as the migration login: RLS would hide the rows
-- from the owner role). New schools get the same at onboarding (app/services/onboarding.py).
INSERT INTO ledger_accounts (school_id, code, name_en, name_sw, kind, is_system)
SELECT s.id, a.code, a.en, a.sw, a.kind, TRUE
FROM schools s
CROSS JOIN (VALUES
    ('4060', 'Fines income',            'Mapato ya faini',      'INCOME'),
    ('4800', 'Other income',            'Mapato mengine',       'INCOME'),
    ('4810', 'Donations',               'Michango',             'INCOME'),
    ('5000', 'Salaries and wages',      'Mishahara',            'EXPENSE'),
    ('5100', 'Utilities',               'Maji na umeme',        'EXPENSE'),
    ('5200', 'Supplies and stationery', 'Vifaa na shajara',     'EXPENSE'),
    ('5300', 'Repairs and maintenance', 'Matengenezo',          'EXPENSE'),
    ('5900', 'Other expenses',          'Matumizi mengine',     'EXPENSE')
) AS a(code, en, sw, kind)
ON CONFLICT (school_id, code) DO NOTHING;

INSERT INTO finance_categories (school_id, kind, name_en, name_sw, ledger_account_id)
SELECT l.school_id, l.kind, l.name_en, l.name_sw, l.id
FROM ledger_accounts l
WHERE l.code IN ('4800','4810','5000','5100','5200','5300','5900')
  AND NOT EXISTS (SELECT 1 FROM finance_categories c WHERE c.school_id = l.school_id AND c.ledger_account_id = l.id);

INSERT INTO fee_items (school_id, code, name_en, name_sw, income_account_id)
SELECT l.school_id, 'FINE', 'Late payment fine', 'Faini ya kuchelewa kulipa', l.id
FROM ledger_accounts l
WHERE l.code = '4060'
  AND NOT EXISTS (SELECT 1 FROM fee_items f WHERE f.school_id = l.school_id AND f.code = 'FINE');

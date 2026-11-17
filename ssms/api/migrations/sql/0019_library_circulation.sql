-- Library circulation (2026-11-12, design: the school's library page brief): every physical copy has its own
-- accession number and status, each loan is of one copy, and each school has its borrowing rules.
-- Existing books get numbered copies and existing loans are assigned to them, so nothing already recorded is lost.
SET ROLE ssms_owner;

CREATE TABLE library_copies (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID         NOT NULL REFERENCES schools (id),
    book_id       UUID         NOT NULL,
    accession_no  VARCHAR(20)  NOT NULL,
    status        VARCHAR(10)  NOT NULL DEFAULT 'AVAILABLE',   -- in circulation, or taken out of it
    condition     VARCHAR(10)  NOT NULL DEFAULT 'GOOD',
    shelf         VARCHAR(30),
    acquired_on   DATE,
    note          VARCHAR(200),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by    UUID,
    CONSTRAINT uq_library_copies_tenant UNIQUE (school_id, id),
    CONSTRAINT uq_library_copies_accession UNIQUE (school_id, accession_no),
    CONSTRAINT fk_lcopy_book FOREIGN KEY (school_id, book_id) REFERENCES library_books (school_id, id),
    CONSTRAINT fk_lcopy_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_lcopy_status CHECK (status IN ('AVAILABLE','DAMAGED','LOST','WITHDRAWN')),
    CONSTRAINT ck_lcopy_condition CHECK (condition IN ('GOOD','FAIR','DAMAGED'))
);
CREATE INDEX ix_library_copies_book ON library_copies (school_id, book_id);

-- One row per school: the rules the circulation desk applies.
CREATE TABLE library_settings (
    school_id            UUID PRIMARY KEY REFERENCES schools (id),
    loan_days_student    SMALLINT    NOT NULL DEFAULT 14,
    loan_days_staff      SMALLINT    NOT NULL DEFAULT 30,
    max_loans_student    SMALLINT    NOT NULL DEFAULT 2,
    max_loans_staff      SMALLINT    NOT NULL DEFAULT 5,
    max_renewals         SMALLINT    NOT NULL DEFAULT 1,
    block_when_overdue   BOOLEAN     NOT NULL DEFAULT TRUE,
    next_accession       INTEGER     NOT NULL DEFAULT 1,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by           UUID,
    CONSTRAINT ck_ls_days  CHECK (loan_days_student BETWEEN 1 AND 365 AND loan_days_staff BETWEEN 1 AND 365),
    CONSTRAINT ck_ls_loans CHECK (max_loans_student BETWEEN 1 AND 50 AND max_loans_staff BETWEEN 1 AND 50),
    CONSTRAINT ck_ls_renew CHECK (max_renewals BETWEEN 0 AND 10),
    CONSTRAINT ck_ls_next  CHECK (next_accession >= 1)
);

ALTER TABLE library_loans
    ADD COLUMN copy_id          UUID,
    ADD COLUMN renewals         SMALLINT     NOT NULL DEFAULT 0,
    ADD COLUMN return_condition VARCHAR(10),
    ADD COLUMN charge_tzs       NUMERIC(12,2),
    ADD CONSTRAINT fk_ll_copy FOREIGN KEY (school_id, copy_id) REFERENCES library_copies (school_id, id),
    ADD CONSTRAINT ck_ll_return_condition CHECK (return_condition IN ('GOOD','DAMAGED','LOST')),
    ADD CONSTRAINT ck_ll_charge CHECK (charge_tzs IS NULL OR charge_tzs >= 0),
    ADD CONSTRAINT ck_ll_renewals CHECK (renewals >= 0);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['library_copies','library_settings'] LOOP
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

-- Back-fill (as the migration superuser, so every school is reached): settings, numbered copies, loans to copies.
INSERT INTO library_settings (school_id) SELECT id FROM schools ON CONFLICT DO NOTHING;

INSERT INTO library_copies (school_id, book_id, accession_no, acquired_on, created_by)
SELECT b.school_id, b.id,
       'ACC-' || lpad((row_number() OVER (PARTITION BY b.school_id ORDER BY b.created_at, b.id, g.n))::text, 6, '0'),
       b.created_at::date, b.created_by
FROM library_books b
CROSS JOIN LATERAL generate_series(1, b.copies) AS g(n)
WHERE b.deleted_at IS NULL;

UPDATE library_settings s
SET next_accession = 1 + (SELECT count(*) FROM library_copies c WHERE c.school_id = s.school_id);

-- Open loans take distinct copies of their book (the capacity guard kept them within the copy count);
-- returned loans are attached to the book's first copy so their history keeps a copy.
WITH open_loans AS (
    SELECT l.id, l.school_id, l.book_id,
           row_number() OVER (PARTITION BY l.school_id, l.book_id ORDER BY l.loaned_at, l.id) AS k
    FROM library_loans l WHERE l.returned_at IS NULL
), numbered AS (
    SELECT c.id, c.school_id, c.book_id,
           row_number() OVER (PARTITION BY c.school_id, c.book_id ORDER BY c.accession_no) AS k
    FROM library_copies c
)
UPDATE library_loans l SET copy_id = n.id
FROM open_loans o JOIN numbered n ON n.school_id = o.school_id AND n.book_id = o.book_id AND n.k = o.k
WHERE l.id = o.id;

UPDATE library_loans l SET copy_id = (
    SELECT c.id FROM library_copies c WHERE c.school_id = l.school_id AND c.book_id = l.book_id
    ORDER BY c.accession_no LIMIT 1)
WHERE l.copy_id IS NULL;

-- A copy is lent to one person at a time.
CREATE UNIQUE INDEX uq_library_loans_open_copy ON library_loans (school_id, copy_id) WHERE returned_at IS NULL;

GRANT SELECT, INSERT, UPDATE ON library_copies, library_settings TO ssms_app;

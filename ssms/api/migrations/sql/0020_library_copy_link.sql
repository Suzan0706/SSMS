-- Library copies wired to the app (2026-11-17). Migration 0019 added physical copies, but the API kept lending by
-- book: books added later had no copies, new loans had no copy, and nothing made a loan's copy belong to the
-- loan's book. This migration connects them in the database, so the existing screens and API keep working:
--   * a loan's copy must be a copy of the loan's book (composite key, as in 0009 for reversals);
--   * adding a book, or changing its number of copies, keeps its numbered copies in step;
--   * a new loan takes a free copy of its book (or is refused as full when none is free).
-- Nothing is deleted: surplus copies are marked WITHDRAWN and every loan keeps its history.

-- 1. Back-fill as the migration superuser (reaches every school through RLS).

INSERT INTO library_settings (school_id) SELECT id FROM schools ON CONFLICT DO NOTHING;

-- A copy that is not of the loan's book is dropped from the loan (the book is what the desk recorded);
-- step 1c gives the loan a copy of its own book again.
UPDATE library_loans l SET copy_id = NULL
FROM library_copies c
WHERE c.school_id = l.school_id AND c.id = l.copy_id AND c.book_id <> l.book_id;

-- 1b. Books added since 0019 (or whose count grew) get their missing numbered copies.
WITH missing AS (
    SELECT b.school_id, b.id AS book_id, b.created_at, b.created_by,
           b.copies - (SELECT count(*) FROM library_copies c
                       WHERE c.school_id = b.school_id AND c.book_id = b.id AND c.status <> 'WITHDRAWN') AS n
    FROM library_books b
    WHERE b.deleted_at IS NULL
), wanted AS (
    SELECT m.school_id, m.book_id, m.created_at, m.created_by,
           row_number() OVER (PARTITION BY m.school_id ORDER BY m.created_at, m.book_id, g.k) AS r
    FROM missing m CROSS JOIN LATERAL generate_series(1, m.n) AS g(k)
    WHERE m.n > 0
)
INSERT INTO library_copies (school_id, book_id, accession_no, acquired_on, created_by)
SELECT w.school_id, w.book_id, 'ACC-' || lpad((s.next_accession + w.r - 1)::text, 6, '0'), w.created_at::date, w.created_by
FROM wanted w JOIN library_settings s ON s.school_id = w.school_id;

UPDATE library_settings s
SET next_accession = GREATEST(s.next_accession,
                              1 + (SELECT count(*) FROM library_copies c WHERE c.school_id = s.school_id));

-- 1c. Loans without a copy: open loans take distinct free copies of their book, returned loans the first copy.
WITH open_loans AS (
    SELECT l.id, l.school_id, l.book_id,
           row_number() OVER (PARTITION BY l.school_id, l.book_id ORDER BY l.loaned_at, l.id) AS k
    FROM library_loans l WHERE l.returned_at IS NULL AND l.copy_id IS NULL
), free AS (
    SELECT c.id, c.school_id, c.book_id,
           row_number() OVER (PARTITION BY c.school_id, c.book_id ORDER BY c.accession_no) AS k
    FROM library_copies c
    WHERE c.status = 'AVAILABLE'
      AND NOT EXISTS (SELECT 1 FROM library_loans o
                      WHERE o.school_id = c.school_id AND o.copy_id = c.id AND o.returned_at IS NULL)
)
UPDATE library_loans l SET copy_id = f.id
FROM open_loans o JOIN free f ON f.school_id = o.school_id AND f.book_id = o.book_id AND f.k = o.k
WHERE l.id = o.id;

UPDATE library_loans l SET copy_id = (
    SELECT c.id FROM library_copies c WHERE c.school_id = l.school_id AND c.book_id = l.book_id
    ORDER BY c.accession_no LIMIT 1)
WHERE l.copy_id IS NULL AND l.returned_at IS NOT NULL;

-- 2. Rules and triggers, owned by ssms_owner like every other object.
SET ROLE ssms_owner;

ALTER TABLE library_copies ADD CONSTRAINT uq_library_copies_book UNIQUE (school_id, id, book_id);
ALTER TABLE library_loans
    DROP CONSTRAINT fk_ll_copy,
    ADD CONSTRAINT fk_ll_copy FOREIGN KEY (school_id, copy_id, book_id)
        REFERENCES library_copies (school_id, id, book_id);

-- Keep a book's numbered copies equal to its number of copies.
CREATE FUNCTION fn_library_book_copies() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_live  integer;
    v_first integer;
BEGIN
    IF NEW.deleted_at IS NOT NULL THEN RETURN NULL; END IF;
    SELECT count(*) INTO v_live FROM library_copies
     WHERE school_id = NEW.school_id AND book_id = NEW.id AND status <> 'WITHDRAWN';
    IF v_live < NEW.copies THEN
        INSERT INTO library_settings (school_id) VALUES (NEW.school_id) ON CONFLICT DO NOTHING;
        UPDATE library_settings SET next_accession = next_accession + (NEW.copies - v_live)
         WHERE school_id = NEW.school_id
        RETURNING next_accession - (NEW.copies - v_live) INTO v_first;
        INSERT INTO library_copies (school_id, book_id, accession_no, acquired_on, created_by)
        SELECT NEW.school_id, NEW.id, 'ACC-' || lpad((v_first + g.k - 1)::text, 6, '0'), current_date, NEW.created_by
        FROM generate_series(1, NEW.copies - v_live) AS g(k);
    ELSIF v_live > NEW.copies THEN
        -- copies not on loan leave circulation: damaged or lost ones first, then the newest
        UPDATE library_copies SET status = 'WITHDRAWN'
         WHERE id IN (SELECT c.id FROM library_copies c
                       WHERE c.school_id = NEW.school_id AND c.book_id = NEW.id AND c.status <> 'WITHDRAWN'
                         AND NOT EXISTS (SELECT 1 FROM library_loans l WHERE l.school_id = c.school_id
                                           AND l.copy_id = c.id AND l.returned_at IS NULL)
                       ORDER BY (c.status = 'AVAILABLE'), c.accession_no DESC
                       LIMIT v_live - NEW.copies);
    END IF;
    RETURN NULL;
END $$;

CREATE TRIGGER trg_library_books_copies AFTER INSERT OR UPDATE OF copies, deleted_at ON library_books
    FOR EACH ROW EXECUTE FUNCTION fn_library_book_copies();

-- A new loan takes a free copy of its book. Runs after trg_library_loans_capacity (triggers fire by name),
-- which has already locked the book row, so two desks cannot hand out the same copy.
CREATE FUNCTION fn_library_loan_copy() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.copy_id IS NOT NULL OR NEW.returned_at IS NOT NULL THEN RETURN NEW; END IF;
    SELECT c.id INTO NEW.copy_id FROM library_copies c
     WHERE c.school_id = NEW.school_id AND c.book_id = NEW.book_id AND c.status = 'AVAILABLE'
       AND NOT EXISTS (SELECT 1 FROM library_loans l WHERE l.school_id = c.school_id
                         AND l.copy_id = c.id AND l.returned_at IS NULL)
     ORDER BY c.accession_no
     LIMIT 1;
    IF NEW.copy_id IS NULL THEN
        RAISE EXCEPTION 'library_loans is full (no free copy)' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_library_loans_copy BEFORE INSERT ON library_loans
    FOR EACH ROW EXECUTE FUNCTION fn_library_loan_copy();

RESET ROLE;

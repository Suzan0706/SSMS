"""Accounting invariants checked after money operations (school A, as ssms_app)."""

from sqlalchemy import text

from tests.helpers import SCHOOL_A, as_school


async def assert_books_balance(db) -> None:
    """Every journal balances; per student the receivable (1300) equals the open invoice balances and the credit
    account (2100) equals the unallocated confirmed payments."""
    await as_school(db, SCHOOL_A)
    unbalanced = (
        await db.execute(
            text("SELECT journal_id FROM ledger_entries GROUP BY journal_id HAVING sum(debit_tzs) <> sum(credit_tzs)")
        )
    ).all()
    assert unbalanced == []
    mismatch = await db.execute(
        text("""
        WITH ledger AS (
            SELECT le.student_id,
                   sum(CASE WHEN a.code = '1300' THEN le.debit_tzs - le.credit_tzs ELSE 0 END) AS receivable,
                   sum(CASE WHEN a.code = '2100' THEN le.credit_tzs - le.debit_tzs ELSE 0 END) AS credit
            FROM ledger_entries le JOIN ledger_accounts a ON a.id = le.account_id
            WHERE le.student_id IS NOT NULL GROUP BY le.student_id)
        SELECT p.student_id, coalesce(l.receivable, 0) AS receivable, p.outstanding_tzs,
               coalesce(l.credit, 0) AS credit, p.credit_tzs
        FROM v_student_fee_position p LEFT JOIN ledger l ON l.student_id = p.student_id
        WHERE coalesce(l.receivable, 0) <> p.outstanding_tzs OR coalesce(l.credit, 0) <> p.credit_tzs""")
    )
    assert [tuple(r) for r in mismatch.all()] == []

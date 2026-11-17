"""The seeded books already satisfy the accounting invariants (so later tests start from a clean ledger)."""

from tests.finance_helpers import assert_books_balance


async def test_seed_books_balance(db):
    await assert_books_balance(db)

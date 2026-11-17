# ADR 0019: Facility fees go on the term invoice

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Transport and boarding are billed per term, but students are given a bus seat or a bed at any time — before or after
the term's invoices are generated. Separate small invoices would confuse parents (several control numbers) and would
make invoice generation skip the student ("already billed for the term").

## Decision

`services/facility_fees.py` says what a student owes for transport (the route's term fee, fee item TRANSPORT) and
boarding (the class fee structure's optional BOARDING lines) in a term. Invoice generation adds these lines. When the
term's invoice already exists, assigning a bus or approving a room adds CHARGE lines to it in the same transaction:
the invoice journal for the new lines is posted (receivable → transport/boarding income), the last installment grows
by the amount, and any student credit is applied. Ending an assignment or vacating a room does not refund; the bursar
adds a discount line when the school agrees to one.

## Consequences

One invoice and one control number per student and term; the books stay balanced (tested with the ledger
invariants). A GePG control number already issued for the old amount is not re-issued automatically (VERIFY with the
GePG partial-payment rules).

## Evidence

`app/services/{facility_fees,hostel,transport,invoices}.py`; `tests/test_facilities.py`.

# Bill prefix: one line changed in orders.py

**What changed.** In `services/orders.py`, `ensure_invoice` used to build the bill number as
`f"{fy}/{n:04d}"`. It now calls `format_bill_number(db, tenant_id, fy, n)` from the new
`services/bill_number_format.py`. Nothing else in `orders.py` changed (plus the one import line).

**Why.** Settings > Business details now has an optional "Bill prefix" (letters and numbers, up to
6, like `DS`). When it is set, numbers read `DS/26-27/0001`.

**The default is unchanged.** With no prefix the number is exactly what it was: `2026-27/0001`.
If the shop's settings can't be read, `format_bill_number` falls back to that same default, so a
sale is never lost over a number. The counter (`next_invoice_number`, restarts each April) and
credit notes (`CN/...`) are untouched.

**Things to know.**
- A prefix is checked when saved (A-Z, 0-9, up to 6), and again when read.
- Changing the prefix does not rename bills that already have a number; only new bills use it.
- Tests: `tests/test_business_bills.py` (default byte-for-byte, with prefix, fallback).

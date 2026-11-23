# Commerce leftovers (23 Nov 2026): what changed in your code and why

Everything here is additive. A shop that sets none of the new things gets the same bills, the same
reminders and the same screens as before. No migration was needed.

## 1. Bill print: logo, signature, PAN, licence, UPI, bank, terms, "Bill of supply"

The shop sets these in Settings > Business details & bills. They now print on the customer's page,
the WhatsApp picture and the PDF.

- **backend/app/services/bill_brand.py (new).** Collects the extras into one `brand` block and, for a
  composition-scheme shop, sets the title to "Bill of supply" and zeroes every tax figure. A shop that
  set nothing gets empty extras and the old title.
- **backend/app/services/orders.py, `public_bill`.** Calls `bill_brand.decorate(...)` on the bill it
  already built. This is the one place all three bill formats read from.
- **backend/app/services/bill_files.py.** The picture and the PDF draw logo, PAN and licence, "UPI: id",
  bank lines, terms and signature, only when each is set. The PDF title uses the bill's title, and a
  composition shop gets the line "Composition taxable person, not eligible to collect tax on supplies."
  There is no QR: nothing in the code makes UPI QR codes, so the UPI ID prints as text.
- **frontend/app/bill/[token]/page.tsx.** Same extras on the customer's page. Tax columns hide for a
  composition shop. The "Tax invoice" word now comes from `billTitle`.
- **frontend/lib/billBrand.ts (new) + billBrand.test.ts.** The small pure helpers the page uses.

## 2. Balance reminders on/off

- **backend/app/services/orders.py.** `balance_reminders_on` / `save_balance_reminders` (stored in
  app_settings, key `balance_reminders`; nothing stored means ON, as before). `send_due_reminders` skips
  a shop that turned it off. A skipped reminder is not counted as sent, so switching on again resumes
  day 1, 3, 7. A failed read never turns reminders off.
- **backend/app/routes/orders.py.** `GET /api/v1/orders/balance-reminders` (needs deals.view) and
  `PUT` (owner only), both return `{"on": bool}`.
- **frontend/lib/balanceRemindersApi.ts (new) + test**, and **frontend/app/dashboard/settings/payments/page.tsx**:
  the switch sits on the "Balance reminders" card. Only the owner can flip it. The three "Coming later"
  lines this batch delivers were removed.

## 3. Advance-change log

- **backend/app/services/orders.py.** `log_advance_change` writes `{from, to, by name, note}` to the
  activity log (app_audit_logs, action `order.advance_changed`; the log keeps the time). `advance_changes`
  reads them back and `order_detail` returns them as `advance_changes`. `create_bill` uses it.
- **backend/app/services/order_quotes.py.** `create_quote` uses it too (one line).
- **frontend/app/dashboard/deals/orders/[id]/page.tsx.** Shows "Advance changed ₹500 → ₹300 by Ravi,
  23 Nov" under the advance note. Older log rows with no amounts show only their written note.

## 4. Cost prices hidden from people without Orders access (deals.view)

- **backend/app/routes/catalog.py.** Item list, item page, create and update leave out
  `cost_price_paise` and add `costs_hidden: true` for people without deals.view. A cost they send is
  ignored. Owners and people with deals.view see everything as before.
- **backend/app/routes/stock_batches.py.** The Batches tab drops cost, value and the card values for the
  same people.
- **frontend:** catalog/items/[id]/page.tsx (no Cost price field, no Stock value row, cost not sent),
  catalog/ItemsTab.tsx (Stock value card says "Not shown"), catalog/BatchesTab.tsx (no Value column).
- Not covered: the stock-count screen's "at cost" figures come from a different endpoint.

## 5. WhatsApp green

`#25D366` replaced with the brand colour in components/conversation-list.tsx,
components/site/HeroInbox.tsx and the "Send on WhatsApp" button in dashboard/deals/new-bill/page.tsx.
lib/brand-guard.test.ts passes.

## 6. "Pay full or advance"

**What commit 70d9b241 does:** when the AI agent sends a quote for a product, the payment link asks only
the advance (the item's own rule, else the shop's), and the quote text says "Pay the advance here". Before
today the customer had no way to say "I will pay it all now".

**What changed:** backend/app/services/deal_actions.py. `send_quote` accepts `pay_full=true`. A new quote
then skips the advance rule. An open quote that asks an advance gets a new link for the whole balance; the
advance link is cancelled once the new one exists, and if the new link fails the advance is put back.
Default behaviour (no `pay_full`) is unchanged.

**Still to do (not in my files):** the tool schema in backend/app/services/ai_reply.py has no `pay_full`
field yet, so the AI cannot send it. The planner needs to add a boolean `pay_full` to `send_quote`, with
the description "true only when the customer says they want to pay the full amount now instead of the
advance". Until then nothing calls the new path. **Done by the planner:** `pay_full` is now in the
`send_quote` tool schema in ai_reply.py.

## Tests

backend/tests/test_commerce_leftovers.py (new, 21 tests), the new `TestPayFullInsteadOfAdvance` class in
backend/tests/test_deal_actions.py, frontend/lib/billBrand.test.ts, frontend/lib/balanceRemindersApi.test.ts.

## Found, not fixed (resolved)

The quote Accept button test failed only because its fake database made every phone look like a supplier, so
the message stopped before the Accept branch. The webhook already calls `order_quotes.accept_from_chat`; the
test now stubs the supplier lookup and passes. Nothing changed in webhook.py.

## Your files the planner touched (additive only)

- `frontend/app/dashboard/catalog/CatalogueTabs.tsx`: two tabs, "Properties" and "Courses & batches", shown
  only when `GET /api/v1/properties/availability` says the business uses them (`enabled` / `courses_enabled`).
  Products is no longer marked active on those two pages.
- `backend/app/services/deals.py` `mark_won`: calls `properties.on_deal_paid` after stock is deducted
  (counts property units once per order; never raises).

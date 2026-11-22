# Commerce: Catalogue & stock, the rest of Prem's mockup (plan, 2026-11-21)

Prem: "i want all of them to be there". Source: the Commerce mockups (Catalogue & stock tab, "Sample data · design
idea"). The 2026-11-19 build (decisions log) did Orders & payments + sizes × colours and left out "batches, stock
count, godown, barcode". This plan is everything still missing from those screens.

## Decisions taken (Prem, 2026-11-21)
1. **Stock places: any number** (Shop, Gandhipuram godown, Branch 2…). Shop + godown is the common case.
2. **Price list upload: Excel/CSV and PDF/photo.** Excel/CSV read directly; a PDF or photo read by AI. Always a
   preview to fix; nothing changes until Save.
3. **Back in stock: Anril's own template** (`anril_back_in_stock`, en / ta / tanglish, editable), submitted per
   business like the order templates. Inside 24 h a normal message; until approved the button says how many
   can't be reached yet.

## How others do it (checked 2026-11-21)
- Vyapar: godown transfers + godown-wise stock reports; batch tracking must be switched on per item before expiry
  dates; FEFO; barcode labels with name/batch/expiry, printer sizes configurable. **They ask the cashier to pick the
  batch** — we pick the first-expiring batch by itself (mockup) and let staff change it.
- Zoho Inventory: stock count = created → assigned → counted → **approved**, an unmatched count needs a reason;
  adjustment reasons are editable. Same as our mockup (staff count, owner finishes, reason per line).
- WATI / Interakt: no own back-in-stock or price-list import; shops add Shopify apps (Wapsi etc.) for "Notify me on
  WhatsApp". Our AI asking in chat + one button is ahead of them.

## Today (checked in code)
- Stock = `catalog_items.stock_quantity` and `catalog_item_variants.stock_quantity` (sizes × colours). Every change is
  a `stock_movements` row, written by `apply_stock_movement` / `apply_variant_stock_movement` (services/deals.py) and
  by Correct stock in routes/catalog.py. Held stock for unpaid links already exists.
- Exists: Correct stock with reason, Stock history, low-stock level (`low_stock_at`), `stock_waitlist` (staff add a
  person; item page shows "N on the waiting list"; nobody is ever messaged), photos per item (images only), shop
  advance rule (`orders_advance_rule`), evening summary (`day_closing.py`), Activity log (`record_audit_event`).
- Missing: everything below.

## The base (built first, invisible to clients until they use it)
- `stock_places` (name, kind shop/godown/other, which place bills take from, which place online orders pack from).
  Every business gets one place "Shop" holding all of today's stock — nothing looks different until they add one.
- `stock_levels`: quantity per item / size-colour / place / batch. The item and size totals stay in today's columns,
  kept equal to the sum by one database function, so the AI, WhatsApp Forms, Meta catalogue sync, bills and reports
  keep reading what they read now.
- One function `apply_stock_change(...)` (place, batch, reason) does every change and writes `stock_movements`; the
  two old functions become thin wrappers using the default place, so old paths keep working.
- Migration 304 (+ undo), applied by me before any code that reads it.

## The features (each is its own phase, tested and handed to Prem to push)
1. **Asked but out of stock** (tab): people asked, sales missed (asked × price), waiting for a message, per item
   (size/colour) with last asked. The AI, when an item or size is out, says so, offers a close match, and asks
   "Stock vandha message pannava?" — a yes adds them to the list. **Mark back in stock** sends the message
   (24 h → normal, else the template) once, only for what is really in stock again, and marks them notified.
   Excel download.
2. **Media: photos, PDFs and videos** linked to items: price list PDF, size chart, shop map, reels. "When the AI
   sends them" rules (e.g. "price list?" → the PDF; out-of-stock colours never sent); counts of how often each was
   sent; "3 items have no photo". Meta's size limits checked on upload.
3. **Upload price list**: Excel/CSV (sample sheet to download) or PDF/photo (AI reads it). Preview grid: each row
   marked New / Update price / Same, sizes and colours, GST, HSN, stock; fix any cell; Save applies; a summary of
   what changed goes in the Activity log.
4. **Shop & godown**: places in Settings; stock per place on the grid and item page; **Move stock** (from → to,
   items, quantity) → "On the way" → counts only when the other place taps **Received**; suggested moves (shop low,
   godown has, sold in 7 days); bills take from the counter's place, online orders from the chosen place; the AI
   says "available, ready in 1 day" when it is only in a godown. Moves today list.
5. **Batches & expiry**: switch per item (medicines, food, cosmetics); **Stock in with batch** (batch no., expiry,
   quantity, place, supplier, cost). On a bill the first-expiring batch is picked by itself (shown on the line,
   changeable); an expired batch can never be billed; batch + expiry print on the GST bill. Expired / 30 days /
   31–90 days / fine cards; per row Return to supplier, Small discount, Remove (write off), Sell first. Alerts in
   the bell and the evening summary. Supplier is a name for now (Purchases & suppliers is a later tab).
6. **Stock count**: start a count for a place (sections like "Saree rack 1"); staff count on the phone by scanning
   or typing; the screen shows system vs counted vs difference per line, who counted, and a reason per difference;
   selling continues (bills made during the count are allowed for by themselves); **Finish and fix stock** = owner
   only, every change in the Activity log with its reason; the loss shows as "Stock loss" in reports.
7. **Barcode labels**: a code for every item and size/colour (auto, short, e.g. DS-KP-RM; an existing company EAN is
   kept and never reprinted); print labels (from today's stock in / pick items / items with no barcode yet), sizes
   38×25 roll, 50×25 roll, A4 65 per page, choose what shows (shop name, item, size/colour, MRP, barcode); prints
   from the browser to any label or normal printer. **Scan to bill** and **Scan to stock in / count** with the phone
   camera or a USB scanner.
8. **Item page bits**: advance payment per item (shop rule / own rule / no advance), "What the AI agent can tell
   customers" preview with Share price & photos and Can give discount switches, and a stock-in button.

Order: base → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. 1–3 need only the base's being there; 4–6 use places; 7 feeds 6.

## Part 5 in detail: Batches & expiry (decided with Prem, 2026-11-22)
Answers: batches on items AND sizes/colours; Small discount = a % off price for that batch (bills and the AI use
it); Return to supplier = stock out AND what you owe that supplier goes down; on a bill the first-expiring batch
(or the one marked Sell first) is picked by itself, shown on the line, staff can change it; expired never billed.

- **Data (migration 310):** `catalog_items.tracks_batches`; `stock_batches` (item, size/colour, place, batch no.,
  expiry, quantity, cost, supplier, discount %, sell first, status); `deal_item_batches` (which batch each bill line
  took, so a return goes back to the same batch and the bill can print it); `supplier_returns` (credit that lowers
  dues). For a batch item the place's stock always = the sum of its batches (kept by the same SQL functions).
- **Turning it on** for an item puts today's stock into one batch "Opening stock" with no expiry, so nothing is lost.
- **Stock in:** Purchases → Stock in asks batch no. + expiry on lines of batch items; "+ Stock in with batch" on the
  tab opens that page.
- **Selling:** stock out with no batch given takes Sell-first batches, then earliest expiry, never expired;
  across places as today (bill place first). A counter bill line can name a batch.
- **Price:** when the batch that would be picked has a discount, the bill line and the AI price use it.
- **Bill:** batch no. + expiry under the line on the bill page, PDF and image.
- **Batches & expiry tab:** cards Expired / 30 days / 31–90 days / Fine / Can return to supplier; chips; By supplier;
  rows with Return to supplier, Small discount, Remove · write off (Activity log), Sell first.
- **Alerts:** one bell a day to owners when something expired or expires in 30 days; Day closing gets an
  "Expiring" block.

## The rest, decided with Prem (2026-11-22): Barcodes → Stock count → Expenses → gaps
- **Barcodes (311):** a code per item and size/colour (own short code like DS-KP-RM, made by itself; a company
  EAN typed on the item is kept and never printed). Catalogue → Barcode labels: what to print (today's stock in /
  pick items / items with no barcode yet), size (38×25 roll, 50×25 roll, A4 65 per page), what shows; prints from the
  browser. Scan (USB scanner or phone camera) on New bill, Stock in and Stock count.
- **Stock count (312):** a count per place with sections; staff count by scanning or typing; system vs counted vs
  difference, who counted, a reason per difference; bills during the count are allowed for by themselves; Pause;
  **Finish and fix stock** = owner only, each change with its reason (reason `count`), loss = "Stock loss".
  Purchases → Suppliers gets Stock value, Stock-in history and Stock corrections.
- **Expenses (313):** own tab; quick add (Rent, Salary, Electricity, Transport, Tea & food, Other; cash/UPI/bank;
  bill photo); rent and salary added by themselves each month on their date; purchases, supplier payments, Meta ads
  and the Anril plan added by themselves; Real profit = sales − refunds − cost of items sold − expenses;
  **Send month to accountant** = one Excel file. Day closing's cash expenses are the same records.
- **Gaps:** PO as a PDF to the supplier; a reminder to the supplier for pieces still to come; the bill photo adds a
  new size/colour under the same item (and never falls back to another size); staff tied to a place (Team & roles:
  their bills take from it, they receive moves to it).

## Rules for every phase
- Customer-facing words in English / Tamil / Tanglish and editable; dashboard copy plain English; "Anril" only.
- Settings apply on Save; header shows "Catalogue / <tab>"; RLS member-select on every new table; tenant_id on
  every query; migrations applied by me, never by a worker.
- Tests per phase (regression tests for stock math: totals always equal the sum, no negative stock, a move or count
  can't be applied twice); backend suite + tsc + lint; UI checked in the browser before showing.
- No commit or push without Prem's OK.

## Not in this plan
Purchases & suppliers tab, Expenses tab, purchase orders, supplier returns as documents (Return to supplier here
only takes stock out with that reason).

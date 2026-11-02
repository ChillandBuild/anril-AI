# Bulk9 SMS — superseded full-build plan

> Superseded by [approved client-only scope](2026-10-30-sms-client-only.md) on30 October2026. Historical financial/reseller decisions below are not current implementation requirements.

Date: 30 October 2026. Status: awaiting Prem's approval. Replaces the v1 scope in
`2026-10-29-bulk9-sms-integration.md` (its safety rules still apply: consent, no blind resend,
honest Submitted vs Delivered, dry-run safe locally). API facts: `docs/bulk9-api-review.md`.

Who uses what: Prem (admin) → Bulk9 reseller panel at sms.anrilaitech.com + Anril operator
console. Clients → Anril dashboard only, new page **/dashboard/sms** under "Reach".

RCS is out: Bulk9 documents no RCS send or bot-onboarding API (only credit + callbacks).

## Worked example used throughout

Client **Bright Path** (tenant), Bulk9 username brightpath, price ₹0.25/SMS.
Lead **Ravi Kumar**, +91 98xxxxxx10. Template "Hi {#var#}, your demo is on {#var#}. -BRTPTH".

## Decisions with defaults (approve or change)

| # | Decision | Default |
|---|---|---|
| D1 | Recharge money goes to **Anril's own Razorpay account** (not the client's). Uses Payment Links like the existing code; platform keys in Render env. | Yes — needs Anril's Razorpay key id/secret + webhook secret set on Render by Prem |
| D2 | Price per SMS | Set per client by Prem in operator console (default ₹0.25); recharge packs ₹500 / ₹1,000 / ₹5,000 → SMS count = amount ÷ price |
| D3 | Who can be messaged | Never opted_out leads. **Promotional** templates also need recorded SMS consent (source + date) on the lead; **service** templates (reminders, updates) don't |
| D4 | Client key storage | Same as Meta/TeleCMI keys today: `app_settings`, is_secret, masked everywhere. (Plaintext at rest like every other key — encrypting all secrets is a separate task) |
| D5 | Plan expiry | Set when credit is added (add-credit supports expiry_date). Changing it later stays in Bulk9 (needs a plan_id the API can't list) |

## What gets built

### A. Operator console → client → new "SMS" view (Prem only)
1. **Create Bulk9 account** — one click: reseller create-user (random strong password, not stored).
   Bright Path → username brightpath created.
2. **Paste client key** — field, masked after save; "Test" button shows wallet balance.
3. **Checklist** Prem ticks: DLT registered, PE–TM bound, sender added (no API → manual ticks).
4. **Enable / disable SMS** — Anril feature flag + reseller enable/disable.
5. **Price per SMS** + **Add credit manually** (free trial / cash payments) with expiry.
6. **Register delivery webhook** in the client's Bulk9 account automatically on key save
   (Bulk9 webhook API, custom header carrying a per-tenant secret).
7. **Reseller stock card** + daily low-stock alert to Prem (below 5,000 SMS).

### B. Client page /dashboard/sms — 5 tabs
**Campaigns**
- Pick leads (filters/tags like the existing Send page) → pick Ready template → map each
  {#var#} to a lead field or fixed text → preview 3 real messages → shows who's excluded and why.
- Send now or **schedule** (date + time IST). Example: 120 leads picked, 3 opted out, 7 missing
  consent → "110 will get it".
- Campaign list with counts: queued / submitted / delivered / failed.

**Templates (DLT)**
- Add entity (with proof file upload), add sender ID, add template — single or DLT Excel upload.
- Template list from Bulk9 with "Refresh"; Submitted vs Ready states; last refresh time.
- Banner: "New templates are approved on your DLT portal (Jio/Airtel/Vi), then added here."

**Reports**
- Per message: Ravi · Delivered · 1 SMS · ₹0.25 · 2:04 pm. Filters by campaign/date/status.
- Summary counts (sent/delivered/failed/blocked) and Bulk9 SMS logs.
- CSV export (from Anril's own records).

**Balance & Recharge**
- Balance card (Bulk9 wallet) + Anril history: recharges, manual credits, per-campaign spend.
- Recharge: pick pack → Razorpay link → paid → Anril adds credit in Bulk9 → balance updates.
  Example: Bright Path pays ₹500 → 2,000 SMS added at ₹0.25.

**OTP & Developer**
- Shows the client's key (owner role only, reveal on click) + link to docs.bulk9.com.
- Test console: send OTP to own number, verify, resend.

### C. Backend
- `services/bulk9_client.py` — client API (send single/multiple, DLT manager, DLR, logs,
  summary, wallet, OTP, webhooks). Key in Authorization header only; TLS verify on; POST sends only.
- `services/bulk9_reseller.py` — create-user, list, balance, enable/disable, add/debit credit.
  Reseller key = Render env BULK9_RESELLER_KEY (never in DB). Checks own stock before add-credit.
- `services/sms_campaigns.py` — durable per-recipient queue; scheduler job every minute claims
  due rows atomically, writes "sending" before calling Bulk9, records request_id + cost
  (sms_details=1). Ambiguous timeout → "unknown", reconciled via DLR, never auto-resent.
- `routes/sms.py` (client), operator routes in `routes/operator.py`, webhooks:
  `/webhook/bulk9/{tenant_id}` (constant-time secret check) and `/webhook/razorpay-sms`
  (platform HMAC, idempotent on payment id → one add-credit per payment).
- Reconcile job every 15 min: unresolved messages → DLR fetch (7-day window).
- Permissions `sms.view`, `sms.manage`, `sms.recharge` in rbac.py; feature `sms`; menu item.
- Safe mode: bulk9.com isn't in the dry-run safe hosts, so local sends are blocked; jobs respect
  SCHEDULER_ENABLED.

### D. Database — migration 237 (applied by me after showing you the SQL)
`sms_templates` (cache), `sms_campaigns`, `sms_messages` (per recipient: state, request_id,
cost, delivery status, timestamps), `sms_ledger` (recharge / manual credit / campaign spend),
`sms_payments` (Razorpay link id, status, unique payment id), lead columns
`sms_consent_source`, `sms_consent_at`. All tenant_id + RLS.

## Build order (each slice: tests → review → next)
1. Foundation: migration, permissions/feature, Bulk9 client + reseller services (mocked tests).
2. Operator SMS view (account, key, checklist, price, manual credit, webhook register, stock).
3. Templates tab + DLT adds/uploads.
4. Campaigns: compose, preview, eligibility, send now/schedule, worker.
5. Delivery webhook + reconcile + Reports tab + CSV.
6. Balance & Recharge with Razorpay + ledger + low-stock alert.
7. OTP & Developer tab.
8. Full check: pytest, typecheck, lint, security review (webhooks/payments/RLS), UI QA as the
   UI test tenant locally, then one real SMS to your test phone only.

I write slices 1, 5, 6 and the migration myself (webhooks/payments/RLS); UI and plain logic go
to workers, every diff reviewed. Commits to main locally; **no push/deploy until you say**.

## Added from the demo-video review (30 Oct)
- **Failed SMS are still charged** (video 21:15–23:32). Reports show "Failed · Invalid Header ·
  charged ₹0.25"; no automatic refund promised anywhere in the UI.
- **Your cost vs client price.** Operator view stores Prem's buy rate per SMS; ledger keeps both
  numbers per send, so the operator view shows profit per client (e.g. 2,000 SMS × (₹0.25 − ₹0.17)
  = ₹160).
- **Cost before sending = estimate** (character count × price), labelled "estimated"; the real
  charge from sms_details replaces it after sending.
- **Template request fallback.** If a client has no approved template, they submit "Request a
  template" (wording + type) in the Templates tab → Prem sees it in the operator SMS view, does
  the DLT portal work, marks it Ready/Rejected with a reason.
- **Support.** SMS page shows "SMS help" contact (Prem's support number/email from settings).
- **Free credits / signup bonus** = manual credit from Prem's stock, recorded in the ledger as
  "bonus".
- **Bulk9 self-signup stays OFF** so no one consumes stock outside Anril.

## Needed from Prem before live testing (not before building)
- Anril Razorpay keys + webhook secret on Render; BULK9_RESELLER_KEY on Render.
- One test client in Bulk9 with DLT entity, sender, one approved template, PE–TM bound.
- A test phone number to receive the one real SMS.

## Left in Bulk9 / outside (unchanged)
PE–TM binding, copying the client key, low-balance alert settings, GST/password/profile,
IP restrictions, template approval on the DLT portal, address book (not needed), RCS.

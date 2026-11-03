# SMS redesign — Bulk9 order (spec + plan)

Status: APPROVED by Prem 3 Nov 2026 (/build auto). TM = SID GROUPS PRIVATE LIMITED, 1702178720558766591. No UI check this round.
Scope agreed in chat 3 Nov 2026: copy Bulk9's menu order, build 4 screens + the sidebar first,
merge template campaigns and "Send with DLT IDs" into one Send SMS form. Smart OTP left for now.
Never show the name "Bulk9" to clients.

## 1. What the client sees

SMS becomes its own item in Anril's main sidebar (today it sits under Reach / More).
Inside SMS, a left sub-menu in Bulk9's order:

```
┌──────────────────────┐
│ ₹ 2,340.00           │  wallet, always visible
│ 12,980 SMS left      │
│ [ Add credit ]       │  → request to Prem (operator alert)
├──────────────────────┤
│ Dashboard            │  /dashboard/sms
│ DLT Setup            │  /dashboard/sms/setup     tabs: Add Entity | DLT Manager | PE-TM Binding
│ Send SMS             │  /dashboard/sms/send
│ Address Book         │  /dashboard/sms/contacts  tabs: Contact | Groups
│ Delivery Reports     │  /dashboard/sms/reports   (today's Reports + campaign list, moved as-is)
│ Transactions         │  /dashboard/sms/transactions (today's balance history, moved as-is)
│ Dev API              │  /dashboard/sms/developer (today's key + request builder, moved as-is)
│ Smart OTP            │  /dashboard/sms/otp       (today's OTP console + history, moved as-is)
└──────────────────────┘
```

Each item is its own URL, so a page can be bookmarked and the browser Back button works.
SMS-only clients (sms on; WhatsApp, inbound, outbound and telecalling off) land on
/dashboard/sms after login instead of /dashboard.

### 1.1 Sidebar wallet + Add credit

- Shows ₹ wallet and SMS count from GET /sms/balance (refreshes every 60 s and after a send).
- Amber when below 500 SMS (same rule as the low-balance alert).
- **Add credit** opens a small form: amount (₹, 100–10,00,000) + optional note → saves a request
  and raises an operator alert. The client sees "₹2,000 requested on 3 Nov · waiting".
  Prem tops up in the Bulk9 panel as today, then marks the request done in the operator console.

Worked example: Ravi has ₹80 left. He taps Add credit, types 2000, note "for Diwali".
Prem's operator bell shows "Ravi's Coaching asked for ₹2,000 SMS credit". Prem adds credit in
the reseller panel and presses Done. Within 15 minutes the balance sync shows ₹2,080 and
Transactions shows "Top-up +…".

### 1.2 Dashboard

Cards, top to bottom:
1. **Setup checklist** (only until done): DLT entity added → Sender ID approved →
   Content template approved → PE-TM binding done → Balance above zero. Each row links to the
   screen that fixes it.
2. **Wallet**: ₹ balance, SMS left, ₹ spent this month.
3. **Today** and **Last 7 days**: sent · delivered · failed · delivered %.
4. **Upcoming sends** (scheduled campaigns, Cancel button) and **Recent sends** (last 5, status,
   link to the campaign in Delivery Reports).

Worked example: on 3 Nov Ravi sees "Today: 4,210 sent · 4,102 delivered · 46 failed · 97%",
and "Tomorrow 6 PM — Diwali reminder — 4,210 numbers [Cancel]".

### 1.3 DLT Setup

**Tab 1 — Add Entity** (Bulk9: "Add your DLT approved entity details")
- Entity ID, Entity Name, proof files (1–5; Bulk9's API requires them), Submit.
- Tick "Add content template (optional)" → shows Sender ID(s), DLT Template ID, message
  with {#var#}, type (service / promotional). Submit sends the entity, then the template.

**Tab 2 — DLT Manager**, three inner tabs with counts, each a table + search + status filter +
an Add button:
- **Entity ID (n)**: S.No · Entity ID · Name · Status · Date. Status is "Submitted" until the
  entity shows up on an approved sender or template, then "Approved". Bulk9 has no entity list
  API, so the list = entities submitted from Anril + entities seen on approved senders/templates.
- **Sender ID (n)**: Sender ID · Entity · Status · Date. Add one, or import from the DLT Excel.
  Submitted senders show "Submitted" until Bulk9 lists them.
- **Content Template (n)**: today's template list (message, type service/promotional, status,
  Refresh) + Add template + import from DLT Excel + today's "request a new template".

**Tab 3 — PE-TM Binding**
- The 4 steps, the TM name and TM ID with a Copy button (from settings, not hard-coded).
- Per entity: upload the screenshot of the binding request (step 3) → operator alert.
- Prem checks it, forwards it in the reseller panel, then presses "TM approved" in the
  operator console.
- Client does the final approval in the DLT portal and presses "I've done the final approval".
- Table: Entity · TM Approval (Pending/Approved) · Final PE Confirmation (Pending/Done) · Date.
- When one entity has both done, the tenant's PE-TM switch turns on and sending unlocks.
  Prem can still tick the switch by hand (existing clients).

Worked example: Ravi copies 1702178720558766591, pastes it in his DLT portal, uploads
"binding.png" against entity 1101234567890. Row: Pending · Pending. Prem presses TM approved →
Approved · Pending. Ravi approves in the DLT portal and presses the button → Approved · Done →
Send SMS unlocks.

### 1.4 Send SMS (one form; replaces Campaigns composer and "Send with DLT IDs")

```
Template   [ Festive offer ▾ ]   (or "Type my own")
Sender ID  [ANRILT]   Entity ID [1101234567890]   Template ID [1107…]
Numbers    ( Contact | List | Excel | Leads* )
Message    Hi {#var#}, 20% off …   →  {#var#} = [ Contact name ▾ ]
           English / Unicode · 1 SMS each
Type       Promotional
Name       [ SMS 3 Nov 18:05 ]
[ Preview ]  → 4,210 will get it · 62 skipped (why) · ≈ ₹760
[ Send ]  or  [ Schedule ]  [3 Nov, 6 PM]
```
*Leads appears only for clients who have Anril leads.

- **Template picked**: Sender, Entity, Template ID, message and type fill in and lock. Each
  {#var#} gets a source (contact name, phone, an extra column, or fixed text), as Campaigns
  does today. Sent through the approved-template route.
- **"Type my own"**: Sender ID is a dropdown of approved senders (Entity fills from it, still
  editable), Template ID and message typed by hand, type chosen. No {#var#} allowed (as today).
  Sent through the DLT-IDs route.
- **Numbers**:
  - Contact: type or paste numbers (up to 5,000).
  - List: one or more Address Book groups (up to 50,000).
  - Excel: upload .csv/.xlsx; Anril reads the phone column and shows "4,120 numbers ·
    18 skipped". Up to 5,000; for more it says "save it to the Address Book as a group first".
  - Leads: today's lead picker.
- Promotional + Contact/Excel needs the consent tick (as today).
- Send is blocked with the reason when PE-TM isn't done or the balance is short (as today).

### 1.5 Address Book

- **Contact** tab: today's contacts list (search, group filter, add, delete) with Bulk9's
  button names: Add multiple contacts (upload/paste) · Add contacts in group · Add group.
- **Groups** tab: Group name · No. of contacts · Date created · **Export** (CSV download,
  new) · rename/delete (delete asks each time, as today).

## 2. Left out on purpose

- Smart OTP changes, Delivery Reports/Transactions/Dev API redesign: moved as-is now, redone later.
- Dashboard chart, test SMS, drafts, send-again, webhooks for clients, contact edit/history.
- OTP Settings and OTP template creation: no Bulk9 API.
- Per-entity send gating: sending stays gated by one per-tenant PE-TM switch.

## 3. Backend changes

### 3.1 Migration 242_sms_redesign.sql (Opus only; RLS on, anon/authenticated revoked, service_role only — same pattern as 240)

| Table | Columns | Why |
|---|---|---|
| sms_dlt_submissions | id, tenant_id, kind ('entity'/'sender'), entity_id, entity_name, sender_id, created_by, created_at; unique (tenant_id, kind, entity_id, coalesce(sender_id,'')) | Show "Submitted" rows; Bulk9 has no entity list |
| sms_pe_tm | id, tenant_id, entity_id, proof_path, tm_approved_at, tm_approved_by, pe_confirmed_at, pe_confirmed_by, created_at; unique (tenant_id, entity_id) | PE-TM per entity |
| sms_credit_requests | id, tenant_id, amount numeric(12,2) check 100–1000000, note text ≤300, status ('open'/'done'/'cancelled'), requested_by, created_at, done_at, done_by | Add credit |

### 3.2 Tenant routes (app/routes/sms.py unless noted; existing permission helpers)

| Route | Perm | Does |
|---|---|---|
| GET /sms/status | sms.view | + `pe_tm_info {tm_name, tm_id}` from env SMS_TM_NAME / SMS_TM_ID |
| GET /sms/dlt/entities | view | submissions ∪ entities on /senders + sms_templates → {entity_id, name, status, at} |
| GET /sms/senders | view | + submitted senders not yet listed, status field |
| POST /sms/dlt/entity, /dlt/sender | manage | unchanged + insert sms_dlt_submissions |
| GET /sms/pe-tm | view_no_key | rows for the tenant |
| POST /sms/pe-tm | manage_no_key | multipart: entity_id + 1 proof (existing `_store_upload`, PROOF_EXTS, 20 MB) → upsert row, operator alert |
| POST /sms/pe-tm/{id}/confirm | manage_no_key | only after tm_approved_at; sets pe_confirmed_at; sets checklist.pe_tm=true |
| GET/POST /sms/credit-requests | view_no_key / manage_no_key | list; create (max 3 open at once) + operator alert |
| POST /sms/numbers/parse | manage_no_key | Excel/CSV → `read_table` + `build_contacts`, no DB write → {numbers ≤5000, skipped, total} |
| GET /sms/contact-groups/{id}/export.csv (sms_contacts.py) | view_no_key | tenant-checked, formula-safe `cell()`, paged 1000 |
| GET /sms/reports/summary | view | unchanged; Dashboard calls it for today and 7 days |

### 3.3 Operator routes (app/routes/operator_sms.py, system admin)

- GET /operator/clients/{id}/sms/pe-tm (with 10-min signed proof URL), POST …/pe-tm/{row}/approve.
- GET /operator/sms/credit-requests?status=open, POST …/{id}/done.
- Alerts: insert into `incidents` (operator bell reads the last 48 h) for "PE-TM proof uploaded"
  and "credit requested". Verify `incidents` insert signature first (app/services/incidents.py:46).

## 4. Frontend changes

- `app/dashboard/sms/layout.tsx` (new): disabled/setup gate (moved from SmsClient) and the
  wallet bar (₹ · SMS left · Add credit) at the top of every SMS page.
- Pages: `page.tsx` (Dashboard), `setup/page.tsx`, `send/page.tsx`, `contacts/page.tsx`,
  `reports/page.tsx`, `transactions/page.tsx`, `developer/page.tsx`, `otp/page.tsx`.
  Tabs inside a page use `?tab=` so they survive refresh.
- Send SMS: new `SendForm.tsx` built from `CampaignComposer` + `ManualCampaignCard` +
  `RecipientPicker` (+ Contact/List/Excel/Leads modes); old two cards deleted after.
- DLT Setup: `AddEntityTab`, `DltManagerTab` (3 tables), `PeTmTab`; `DltForms` split into
  the Add buttons' modals.
- Address Book: existing `ContactsTab`/`GroupsPanel` + Export button + Bulk9 button names.
- Delete `SmsClient.tsx` tab shell once every page is reachable.
- Nav (decided 3 Nov): a new main-menu section **"Anril SMS"** (like Anril Engage / Reach /
  Commerce) in `components/nav/navSections.ts`, holding the 8 pages as leaves; SMS leaves Anril
  Reach. The accordion opens it on any /dashboard/sms page. No second menu inside the page.
  `MoreMenu.tsx` (phone drawer) gets the same 8 items under an "Anril SMS" heading.
  `AppHeader.tsx` title rule from exact match to `/dashboard/sms*` with a per-page title.
  **keerthi-sarav edited these files on 29 Oct and 2 Nov — fetch + rebase right before
  touching them, keep the edits to a few lines.**
- SMS-only landing: in `DashboardClient.tsx`, if sms is on and messaging, inbound, outbound and
  telecalling are all off → `router.replace("/dashboard/sms")`.
- Operator console `SmsConnectionPanel`: PE-TM rows (proof link, Approve) + open credit requests (Done).
- `lib/api.ts`: new calls for every route above.

## 5. Tasks (order, owner, done-when)

| # | Task | Owner | Done when |
|---|---|---|---|
| 1 | Migration 242 + apply live + verify tables/RLS | Opus | `list_tables` shows 3 tables, RLS on, anon insert denied |
| 2 | Backend: entities list, submissions, PE-TM, credit requests, numbers/parse, group export, status tm info + tests | Opus (upload, operator, gating), Sonnet (lists, export, parse) | new pytest file(s) green; full `python -m pytest` green |
| 3 | Security review of task 2 (upload, operator routes, export) | security-reviewer agent | no unfixed HIGH |
| 4 | Frontend shell: layout, sub-menu, wallet + Add credit, routes, move Reports/Transactions/Dev API/OTP as-is | Sonnet | every old feature reachable; tsc + eslint + vitest green |
| 5 | Dashboard page | Sonnet | cards render from real endpoints |
| 6 | DLT Setup page (3 tabs) | Sonnet | add entity/sender/template still work; tables + counts |
| 7 | Send SMS form (merge) | Sonnet; Opus reviews | both routes send in tests; helpers unit tests for the form state |
| 8 | Address Book tweaks + Export | Haiku | export downloads a group |
| 9 | Main nav + SMS-only landing + AppHeader | Opus (shared files, rebase first) | navSections test updated and green |
| 10 | Operator panel: PE-TM approve + credit requests | Sonnet | operator can approve and mark done |
| 11 | UI QA on the test tenant (needs SMS turned on + mocked/real key — ask Prem) | Opus | screenshots of each screen at desktop + phone width |
| 12 | /review, /code-simplify, one commit; push only when Prem says | Opus | — |

## 6. Risks

- **Shared nav files** are being edited by a teammate: conflicts likely; rebase just before task 9.
- **Entity status is a guess** ("Approved" once seen on an approved sender/template), because
  Bulk9 returns no entity list or status.
- **Excel in Send SMS is capped at 5,000** (the pasted-numbers limit); bigger files go through
  the Address Book.
- **PE-TM switch stays per tenant**: once any entity is bound, all sends unlock.
- **UI check needs the test tenant switched to SMS**, which changes live settings — needs Prem's OK.

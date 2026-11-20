# WhatsApp Forms — build plan

Status: **draft v2, waiting for approval** · 2026-11-20
Changes from v1: the page moves to **Catalogue → Forms**; the main use is now **Services intake**
(packages → sub-packages → add-ons → details → payment) done in one WhatsApp Form.

## What we're building

Native **WhatsApp Forms** (Meta's "Flows"): app-like screens that open inside a WhatsApp chat.
Everything happens inside WhatsApp. A form reaches the customer in one of three ways:

1. **In the chat**: Anril sends it while the customer is talking to us (the Services intake case).
2. **From a Click-to-WhatsApp ad**: the ad opens the chat, and the first reply is the form.
3. **From a broadcast**: a WhatsApp template with an "Open form" button.

## Where it lives

**Catalogue → Products | Services | Forms** (a new third tab; header "Catalogue / Forms").

- Catalogue already shows for every client with messaging, and its two tabs match our two kinds of client:
  product sellers and detail collectors like AstroTamil.
- **Services → "How Anril collects the order"**: a new choice, *Ask in chat* (today) or
  *Send a WhatsApp Form*. Choosing the form uses the Services packages and details as they are,
  with nothing set up twice.
- The Forms tab holds the intake form (made from Services) plus any other forms
  (lead enquiry, feedback, appointment request).
- **Prices, packages, sub-packages and add-ons are edited only in Services.** The form reads them.
  One source of truth, so a price can never differ between the chat and the form.

## Part A — Services intake as a WhatsApp Form (main goal)

### Today (chat), for reference
`offer_pending → awaiting_package_choice` (one tap per level: package → sub-package)
`→ awaiting_addon_choice → collecting` (AI asks the details) `→ awaiting_confirmation → awaiting_payment → paid`
([intake.py](backend/app/services/intake.py) `route_intake`). Prices are always built in Python and never written by the AI.

### With a form
Same trigger, same session, same payment. Only the middle steps move into one form:

| Screen | What the customer sees | Built from |
|---|---|---|
| 1. Choose | Packages as a single-choice list, each with its price and "what's included" line ("One Question · ₹1", "Detailed Question") | Services packages (active only) |
| 2. Choose option | **Only if** the chosen package has sub-packages: its options with prices ("1 Year · ₹999", "2 Years · ₹1,799") | That package's sub-packages |
| 3. Add-ons | **Only if** the chosen option has add-ons: tick any ("Remedies PDF · +₹199") | That leaf's add-ons |
| 4. Your details | One input per "Details to collect" item: Text → text box, Date → date picker, Choice → dropdown | Services details list |
| 5. Confirm | Their choices listed back, plus the unticked "Send me updates and offers on WhatsApp" box and a privacy-policy link | Consent rules |

Then: **Submit**. Anril checks every choice against the **live** Services setup, works out the total
in Python (package + add-ons + GST, same functions as today), replies in chat with a short summary,
and sends the Razorpay link. The session jumps straight to `awaiting_payment`, and everything after
that (payment webhook, deal, AstroTamil bridge, receipt) is unchanged.

### Rules that keep it safe
- **Single-level setup:** if there's only one active option at a level, skip that screen (same as `_resolve_choice` today).
- **Stale form:** a form published before an edit in Services may show an old option. On submit, if a
  chosen package or add-on is missing or inactive, Anril says so in chat and falls back to the chat
  flow from that step. It never charges an old price.
- **Auto-republish:** published Meta forms can't be edited, so **saving Services publishes a new form
  version** in the background and retires the old one. The Services save bar shows
  "WhatsApp Form updating… / updated".
- **Customer ignores the form and types instead:** the chat flow carries on as today. The form is
  a faster path, never a dead end.
- **Payment never moves into the form.** The link is sent in chat after submit, as today.

### ✅ Phase 0 result (2026-11-20, tested on a phone via Astro Tamil - ORG)
- Branching by `Switch` works with no live server, and empty steps are skipped with an `If` around the Continue button.
- An **explicit `routing_model` is required** whenever Continue is inside an `If`. Without it, Meta's validation still passes but the phone errors. The builder always writes it.
- **Business verification is required.** An unverified business (Anril AI: `pending_submission`) can't even send a draft (error 139000). The Forms tab must check this and show the step.
- Still to check in Phase 1: the `nfm_reply` answer shape.

### Original Phase 0 questions (kept for reference)
- Showing **screen 2/3 only for the chosen package** in a form with no live data. Plan A: Meta's
  conditional components (`If` / `Switch`) in Flow JSON. Plan B: one screen per package branch.
  Plan C: the data endpoint (Part C). Pick whichever Meta accepts.
- The maximum options in a single-choice list and the maximum screens per form, compared with the
  biggest real package tree (AstroTamil).
- Flow JSON version, permissions, publish time, and whether answers can arrive before publish finishes.

## Part B — the Forms tab (any form, any client)

- **Builder:** add fields (short text, long text, dropdown, single choice, multiple choice, date,
  opt-in), mark them required, auto-split into screens, live **phone preview** like the template
  builder, and **Publish to WhatsApp** showing Meta's status.
- **"Packages from Services" block:** any form can include the package → sub-package → add-on
  picker described above, so a lead form can also take a choice with prices.
- **Starter forms:** Lead enquiry, Appointment request, Feedback, Course/admission enquiry (Tamil + English).
- **Responses tab:** one table per form (like the Intake answers table), filters, CSV download.
- **Lead profile:** a "Form answers" card, and answers also copied into the lead's collected details.

## Consent (built in from day 1)
- An unticked opt-in on the last screen of every form; a privacy-policy link is required (block publish without one).
- The builder refuses fields asking for full card numbers, bank account numbers, Aadhaar or PAN (WhatsApp policy).
- On submit, write **one consent record** on the lead: source, exact wording, time, and scope
  (`replies` / `offers`). This is the same record the Meta lead-form consent fix uses.
- Broadcasts send only to `offers`.

## Backend pieces
- **Migration:** `whatsapp_forms` (tenant, kind = `intake` | `custom`, name, status, version,
  meta_flow_id, definition JSON) and `whatsapp_form_responses` (tenant, form, version, lead,
  intake_session, answers, flow_token, submitted_at) with **RLS**. Done by the planner (CLAUDE.md:
  migrations and RLS are never delegated).
- **Flow JSON builder:** a pure function from (fields + package tree) to screens. Option ids are the
  package/add-on `key`s, never names or prices.
- **Meta client:** create, upload JSON, publish, deprecate; Meta errors saved in plain words.
- **Send:** an interactive `flow` message inside the 24-hour window; templates with a FLOW button
  for broadcasts (Part B, phase 2).
- **Webhook:** a new `nfm_reply` branch next to `button_reply`/`list_reply` at
  [webhook.py:895](backend/app/routes/webhook.py:895). It checks the signed `flow_token`
  (tenant + lead + form + session) and saves once (duplicate submits are ignored). Intake forms go
  to a new `apply_form_submission(session, answers)` in `intake.py` that reuses `_find_leaf`,
  `_package_patch`, the GST helpers and the existing payment-link step.
- **Security:** webhook + RLS → `security-and-hardening` and `security-checklist.md`. Answers are
  customer-written text: escape them in the UI and never feed them to the AI as instructions.

## Phases

| Phase | What | Done when |
|---|---|---|
| **0 — Prove on Meta** (1–2 days, no UI) | Test WABA: publish a 3-level package form with conditional screens, send in chat, receive `nfm_reply` | Every ⚠ above answered and written into `subsystem-notes.md` |
| **1 — Services intake form** | Migration + RLS, Flow builder, auto-republish on Services save, Services "Send a WhatsApp Form" choice, webhook to session to payment link, fallback to chat | AstroTamil test number: pick package → sub-package → add-on → details → pay, with the amount matching the chat flow to the paisa |
| **2 — Forms tab** | Builder, starter forms, Responses tab, lead "Form answers" card, consent record, Conversations "Send form" | A clinic-style client can build and send a lead form without Services |
| **3 — Reach** | Template "Open form" button (broadcasts), first reply for Click-to-WhatsApp ads, AI can send a form, per-form numbers (sent → submitted → paid) | — |
| **4 — Live forms** | Data endpoint + encryption: live slots, stock, **product order form from Catalogue → Products** | — |

Product sellers get a simple order form in Phase 2 (fixed choices). Picking from a live, large
catalogue needs the data endpoint, so it waits for Phase 4.

## Tests (bug-proof the money path)
- The Flow JSON builder for a 1-, 2- and 3-level tree, with add-ons, inactive items hidden, and single-option levels skipped.
- Submission totals = the chat flow's totals for the same choices (GST on and off).
- A stale key or inactive add-on on submit leads to a chat fallback with no link sent.
- A wrong-tenant or tampered `flow_token` is rejected; a duplicate submit creates one link.
- Forbidden-field guard; consent record written with the right scope.

## Decisions needed
1. ~~Where it lives~~ → **Catalogue → Forms** ✅ (agreed 2026-11-20)
2. Is it on for every client, or switched on per client?
3. Does the **Meta lead-form consent fix** go first, or alongside Phase 0?
4. First real client to pilot the intake form: AstroTamil?

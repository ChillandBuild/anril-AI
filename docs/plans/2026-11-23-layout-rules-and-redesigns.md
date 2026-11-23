# Layout rules + 5 page redesigns — build plan (23 Nov 2026)

Mockups (all picked by Prem): https://claude.ai/artifact/EcDWFrKpXaj3EHs9SrLoRj
Rule saved: `.agents/context/identity.md` § UI Conventions, "A page's name appears once".

Six batches. Each ends with typecheck + lint + `python -m pytest` (when backend changed) and a commit on `main`. Nothing is pushed until Prem says so. Before the first edit: `git pull` (Keerthi's `e1c7a077` changed the Templates title in `AppHeader.tsx`).

---

## Batch 1 — App-wide layout rules (frontend only)

| # | Rule | Where | Size |
|---|---|---|---|
| 1.1 | Every route gets its own header title; nothing falls back to "Anril AI" | `components/AppHeader.tsx` `getBaseRouteMetadata` (:232-501), `SETTINGS_ROUTE_LABELS` (:41). Missing: `/brain/*` (3), `/call-iq/live`, `/results`, `/evaluation`, `/automations`, `/developer`, `/conversations`, `/intake`, `/consultations`, `/subscriptions`, `/catalog/courses`, `/catalog/properties`, `/leads/[id]`; "Settings / Settings" on alerts, calling-rules, packages, quick-replies, intake-config, razorpay-callback | 1 file |
| 1.2 | Remove the in-page title that repeats the header | 23 pages from the audit (Bookings, Google Ads, QR & links, Target, Payments, Open hours, Text size, Meta charges, Auto-Reply, Business details, My performance, Subscription, Day closing, Price list, Dial, Upload history, Call scripts, Broadcast tags/opted-out/history, Groups, Users/Activity log, OTP API) + 13 that become duplicates after 1.1 (`SetupShell`, `CallIqShell`, automations, developer, courses, properties, alerts, calling-rules). The shared `PageHeader` (`settings/payments/MyBusinessUi.tsx:9`) loses its `<h1>` and keeps only its intro line | ~30 files |
| 1.3 | No empty band under the header | Reports (`analytics/page.tsx`), Home (`DashboardClient.tsx`) top padding | 2 files |
| 1.4 | Full width, no narrow centre column | 22 wrappers (`max-w-3xl/4xl/5xl` list from the audit). Body text paragraphs keep a reading cap (`max-w-prose`); single inputs keep their own width | ~22 files |
| 1.5 | Sub-tabs on the same row as the buttons | `sms/ContactsTab.tsx:38`, `sms/DltManagerTab.tsx:155`, `bookings/page.tsx:75` — copy `catalog/page.tsx:69-90` (tabs left, toolbar right) | 3 files |
| 1.6 | Settings items out of the sidebar | `components/sidebar.tsx:176-178, 268-277` stop rendering `settingsNavigation` items; the Settings hub page stays the menu | 1-2 files |
| 1.7 | Settings sections always open | `settings/SettingsSection.tsx`: drop the open/close chevron and `startClosed`; update the old rule in `identity.md` ("two or more sections start collapsed") | 1 file + doc |
| 1.8 | Website form preview centred | `auto-messages/page.tsx` | 1 file |
| 1.9 | One loader on Reports → Overview | `analytics/OverviewTab.tsx`, `ReportFrame.tsx`, `CompareTab.tsx`: both fetches run together, one loader until both arrive | 3 files |

**Worked example.** Today on Bookings: header says "Engage / Bookings", then 80 px lower a big "Bookings", then the Day | Week tabs, then on the next row ‹ Today › and New booking. After: header "Engage / Bookings"; the first row under it is `Day · Week · By staff · Booking link · Services` on the left and `‹ Today ›  Download  + New booking` on the right; the day grid starts on the next line. Same content, about 140 px higher.

---

## Batch 2 — Home (layout B)

Frontend: `DashboardClient.tsx`, `home/TodayBlock.tsx`, `home/HomeBoxes.tsx`, `home/WaitingList.tsx`, the six "More details" sections.
- Left two-thirds: hot bar + "Waiting for your reply" (6 rows). Other lists (low stock, bookings, feedback) stack under it.
- Right column: "Today" numbers as rows with a 7-day line, target as a ring, Edit Today link. Works for 1 to 15 boxes.
- "More details": 6 chart cards.

Backend needed (per the data check):

| Chart | Data today | Work |
|---|---|---|
| New leads by day | `daily_leads` on `/analytics/overview` | none |
| Hot / Warm / Cold ring | `by_segment_today` | none |
| AI gauge | `ai_handled_today` + handover count | add `couldnt_answer_today` to overview (small) |
| Where leads came from (week) | only all-time or today | add `channel_breakdown_7d` in the same loop, `analytics.py:1191` (trivial) |
| Team calls per caller | `per_caller` without connected count | add `connected_today` per caller, `analytics.py:683` (small) |
| Ad spend | per-campaign totals only; daily spend is not stored | **Recommend: bars per campaign** (data exists). Per-day bars need a new table + Meta sync change |
| Box trend lines | `/home/today` has no history | add `series` (7 values) for new enquiries, won, target, follow-ups. **Hot leads waiting has no past state; recommend no trend line on that one box** (a history would need a new daily snapshot table + nightly job, and would start empty) |

**Worked example.** AstroTamil opens Home at 9 pm: left shows "Sowmya R. (Hot) waiting 2 h" with Open chat / Call, then 6 waiting chats with Reply. Right shows "New enquiries today 6" with a line that rose to 8 on Saturday, "Hot leads waiting 5" (no line), target ring empty with "Set a target ›". Below: 33 leads this week as a line chart, ring 3 Hot · 3 Warm · 4 Cold, gauge "89% answered by AI".

---

## Batch 3 — Settings → Channels (layout A)

Frontend: `settings/connect-channels/Panel.tsx`, `EmbeddedSection.tsx`, `ChannelCard.tsx`, `MarketplaceLeadsSection.tsx`, `ManualSection.tsx`. No backend.
- Summary card "5 of 8 connected" + receiving / quiet / not-connected pills + **Tealy (150 × 150)**, no green band.
- Tiles in 3 groups: Chat channels (WhatsApp, Instagram, Messenger, Telegram), Lead sources (Meta Ads, IndiaMART, JustDial), Payments (Razorpay). Each tile: badge, account line, status pill, Manage / Connect, "via Meta Business" line.
- Meta has no bar of its own: Reconnect / Switch to Coexistence / Disconnect go in the **⋯** menu on the Meta tiles. IndiaMART/JustDial lead-link and welcome-template settings move into their tile's Manage dialog.
- Advanced card with **Healy (150 × 150)**.

**Worked example.** A client whose Messenger has been silent 47 days sees its tile with an amber "Quiet" pill and "Last message 47 d ago"; IndiaMART shows grey "Not connected" with a teal Connect button that opens today's lead-link setup.

---

## Batch 4 — Business details (layout A) + new "Your account" page

- `/dashboard/settings/account` becomes business only: 5 open groups left (Name and address, Contact and logo, Tax and GST, Getting paid, Terms and signature), the existing `InvoicePreview` sticky on the right, one sticky Save bar. Fields come from `components/business-details/BusinessDetailsFields.tsx`, split into the 5 cards.
- New `/dashboard/settings/your-account`: profile card + `ChangePasswordCard` + `PasskeySettings`, moved as-is from `account/page.tsx:127-182`. Add to `SETTINGS_ITEMS` (`settingsNavigation.ts:57`) and `SETTINGS_ROUTE_LABELS`; `/dashboard/profile/settings` style links to `#security` redirect to the new page.

**Worked example.** Owner changes "Name on bills" from Astro Tamil to AstroTamil Jothidam: the bill on the right updates as they type; the Save bar shows "● Unsaved changes"; Save stores it. Their password is no longer on this page; it is under Settings → Your account.

---

## Batch 5 — Replies & handover (layout B: one page, four steps)

- One page at `/dashboard/settings/auto-reply`; `/dashboard/settings/inbox` redirects to it. Remove the two header pills (`AppHeader.tsx:60-61`, `REPLY_PAGES` in `nav/navSections.ts:253-256` → one leaf). Header: "Replies & handover".
- Top card with **Tealy** + "Try it in Test chat". Then 4 step cards left to right: 1 New lead arrives (welcome templates, per lead source) → 2 AI replies (per source) → 3 Hand to your team (`InboxConfigPanel` reasons + round-robin) → 4 When you're closed (`AfterHoursPanel`).
- One Save bar: Save fires the three existing saves together (settings PUT `automations_ai`, `/settings/inbox-config`, `/reply-settings/after-hours`) and reports any that failed. No backend change.
- Step 1 shows each source's welcome template name with a "change" link to where it lives today (Instant forms → form detail; IndiaMART/JustDial → their Channels tile).

**Worked example.** Owner turns off step 2 "AI replies" for JustDial and ticks "Customer asked the same thing again" in step 3, presses Save once: all three settings groups save; a JustDial lead now gets only the welcome template and goes to Chats › Needs you.

---

## Batch 6 — Anril Setup pages

- **Couldn't answer (A)**: top card (times with no answer · questions · answered so far) + **Tealy**; period pills and Test chat on one row; list most-asked first with a count bar; selected question opens on the right with the answer box, an "Anril will say" bubble showing the owner's own answer text, Save answer (existing `POST /ai-setup/couldnt-answer/answer`), Save and test (opens Test chat with the question filled, `TestAira initialQuestion`). Chat links use `sample_lead_ids` → Chats `?lead=`.
- **Questions & scoring**: 0–10 bar (Not interested 0 · Cold 1–3 · Warm 4–7 · Hot 8–10, confirmed in `ai_setup_report.py:423-432`) + 4 side-by-side cards. No backend change.
- **AI report card**: "handled alone" ring + one split bar (handled alone · passed to a person · couldn't answer) + Sales card + "Fix these" with **Healy** and a button per fix. Backend: return `couldnt_answer` from `report_card` (one line, `ai_setup_report.py:412`).

**Worked example.** "Online-la pay panna mudiyuma?" asked 6 times: owner clicks it, types "Yes, UPI or card. I'll send a link.", sees it in the green bubble, presses Save and test; Test chat opens with that question and Anril answers with the new text.

---

## Who does what
- Opus (this session) plans, reviews every diff, does Batch 5's combined save.
- Sonnet workers: Batches 2-4 and 6 frontend; the small backend fields (overview `couldnt_answer_today`, `channel_breakdown_7d`, `connected_today`, `/home/today` `series`, report-card `couldnt_answer`), each with a test.
- Haiku: Batch 1 mechanical edits (titles, wrappers) from the exact file list.
- No auth, payments, RLS or migrations in this plan (unless Prem wants the Hot-leads trend or per-day ad spend).

## Checks
Per batch: `npx tsc --noEmit`, `npm run lint`, `vitest` for touched tests, `python -m pytest` when backend changed, `/review` on the diff. Pages are not visually checked unless Prem asks; a local look as the UI test tenant can be added at the end.

## Not in this plan
Telecalling → Who got which lead and Templates get only the Batch 1 rules. Animated Tealy/Healy (login uses video) — still images first.

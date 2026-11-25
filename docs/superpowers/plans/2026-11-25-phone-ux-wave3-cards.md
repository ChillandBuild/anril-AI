# Phone UX Wave 3: Tables → Phone Cards — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** On phones (below `md`, 768px) every desktop table shows as a list of cards, so nothing needs a sideways swipe and each row's main action is a visible button.

**Architecture:** Per table: keep the desktop table exactly as it is but hide it below `md` (`hidden md:block` on its scroll wrapper), and render a phone list (`md:hidden`) from the SAME rows array (same filters, sorting, pagination, handlers) using `components/MobileRecord.tsx` (`MobileRecordCard`, `MobileRecordHeader`, `MobileRecordGrid`, `MobileRecordField`). Reference implementation: `app/dashboard/sms/ReportsTab.tsx:354-382`, `app/dashboard/leads/LeadsClient.tsx` phone rows.

**Tech Stack:** Next.js 14.2, React, Tailwind 3.4.19.

**Spec:** Audit report https://claude.ai/artifact/PZTUr9bMGCAed7Ng4DhDXi ("Desktop tables you have to swipe sideways"); Wave 1–2 plan `docs/superpowers/plans/2026-11-25-phone-ux-fixes.md`.

## Global Constraints

- Desktop (`md` and up) unchanged: same table, same classes, same behaviour.
- Phone card content: title = the row's main name; one subtitle line (date / phone / source); status badge as `aside` (reuse the table's badge); at most 3–4 key numbers, as one inline line ("Sent 120 · Failed 3") or a 2-column `MobileRecordGrid` when labels are needed; the row's main action as a visible button (min 36px tall, 13px+ text); rare or destructive actions in a ⋯ menu or a small secondary button with the SAME handler and confirm as the table.
- Editable rows (line items, counts, prices, permissions): one card per row, name on top, inputs in a labelled 2–3 column grid, same state handlers, keep `inputMode`, inputs `min-h-10 text-base` (no iOS zoom), remove/delete buttons ≥ 32px.
- Card list spacing `space-y-2` (or `divide-y` inside one card for long dense lists); card padding may be tightened with `className="p-3"`.
- No new data fetching; no behaviour change; no v4-only Tailwind classes; text says "Anril", never "Aira".
- No git commit/push. Edit only your files; before editing, `git status --short -- <your files>`: if a file already has changes you did not make, stop and report BLOCKED for that file.
- Verify: `npx tsc --noEmit`, `npx next lint --file <each changed file>` from `frontend/`.

## Review Focus

- Row click that opens a detail on desktop must also open it from the card, without nested-button double actions (stopPropagation on inner buttons).
- Empty, loading and filtered-to-nothing states still show on phones.
- Pagination/"load more" controls under the table still show under the cards.
- Select-all / bulk checkboxes in tables keep working on cards when the table has them.
- Totals/footer rows of a table appear on phones too.

## Tasks (one worker each, disjoint files)

| Task | Area | Files (under `frontend/`) |
|---|---|---|
| A | Orders & money | `app/dashboard/deals/OrdersTab.tsx`, `deals/new-quote/page.tsx` (editable lines), `app/dashboard/expenses/page.tsx` |
| B1 | Catalogue lists | `catalog/ItemsTab.tsx`, `catalog/BatchesTab.tsx`, `catalog/StockAsksTab.tsx`, `catalog/ShopGodownTab.tsx` |
| B2 | Catalogue editors | `catalog/StockCountTab.tsx`, `catalog/price-list/page.tsx`, `catalog/courses/FeeInstalments.tsx` |
| C | Purchases | `purchases/page.tsx` (4 tables), `purchases/PoEditor.tsx`, `purchases/stock-in/page.tsx` |
| D | Chats folders | `components/escalation-panel.tsx`, `components/chats/ChatsFolderPanel.tsx`, `components/escalations/history-tab.tsx` |
| E | Roles permissions | `app/dashboard/roles/page.tsx` (matrix ~811 → module cards with "Can see" / "Can change" chips, ≥ 32px) |
| F | Team, Call IQ, uploads | `team/PeopleView.tsx`, `components/call-iq/ResultsBoard.tsx`, `telecalling/components/assignment-log.tsx`, `telecalling/upload/page.tsx` (upload history table only) |
| G1 | Meta Ads | `meta-ads/AdPerformanceTab.tsx`, `meta-ads/AllAdsTab.tsx`, `meta-ads/InstantFormsTab.tsx`, `meta-ads/InstantFormDetail.tsx` |
| G2 | Forms & bookings | `forms/[id]/answers/page.tsx`, `bookings/SiteVisitsTab.tsx`, the Intake table with two pinned columns (`IntakeTable.tsx`, unpin the second column below md) |
| H | OTP, SMS, AI agents | `otp/HistoryTab.tsx`, `sms/ContactsTab.tsx`, `sms/BalanceTab.tsx`, `sms/ReportsTab.tsx` (second table ~473 only if it has no phone view), `agents/characters/page.tsx`, `agents/keys/page.tsx`, `agents/requests/page.tsx` |
| I | Reports | `analytics/AdsTab.tsx`, `analytics/ItemsCampaignsTabs.tsx`, `analytics/reportsUi.tsx` (shared table), `analytics/LegacySections.tsx` (templates table) |

Each task: [ ] convert every table in its files (skip a table already hidden on phones with its own phone view — say so) · [ ] tsc + lint clean · [ ] report.

Not in scope: Inbound leads, Scheduled templates, Said stop, SMS reports/campaign (already have phone views); wave 4 sizes and wording.

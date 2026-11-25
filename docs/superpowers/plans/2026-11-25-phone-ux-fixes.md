# Phone UX Fixes (Waves 1–2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the phone-view problems found in the 2026-11-25 audit that block people (hidden Save/Submit, unreachable tabs, pop-ups under the bottom bar) and cut taps on the daily jobs of every main screen.

**Architecture:** Frontend only (Next.js 14 App Router, Tailwind 3.4). Wave 1 changes shared pieces once (header tab strip, bottom-bar offset classes, dialog layer, toaster, bottom-nav highlight). Wave 2 changes one screen area per task, each in its own files, so tasks run in parallel.

**Tech Stack:** Next.js 14.2, React, Tailwind 3.4.19, sonner 2.0.7, vitest.

**Spec:** Audit report https://claude.ai/artifact/PZTUr9bMGCAed7Ng4DhDXi (findings + "Taps for 75 jobs").

## Global Constraints

- Phone = below `lg` (1024px). Bottom bar: `components/MobileDashboardNav.tsx`, `z-bottom-nav` (60), height `var(--mobile-nav-h)` (4.25rem) + `env(safe-area-inset-bottom)`. Dialog layer token: `z-dialog` (100).
- A bar that must stay visible on phones sits ABOVE the bottom bar: `bottom-[calc(var(--mobile-nav-h)+env(safe-area-inset-bottom,0px)+<gap>)]` with an `lg:` class restoring the desktop value. Reference: `app/dashboard/forms/[id]/page.tsx:466`.
- Desktop (`lg+`) look and behaviour must not change unless a task says so.
- Phone filters/chips/tabs compact: chips ~28–32px, 12–13px text, one line (scroll sideways, never wrap). 44px+ only for the main action.
- Settings apply only on Save. Customer-facing copy says "Anril", never "Aira".
- Tailwind 3.4: no v4-only classes (`backdrop-blur-xs`, `shadow-xs`, `inset-shadow-*`).
- `app/dashboard/outbound-leads/page.tsx` and `CampaignResultsDrawer.tsx` carry the owner's uncommitted edits: change only the exact lines named, never reformat.
- NO git commit, NO push (owner commits). Never run `npm run dev` (use `npx next dev`).
- Verify each task: `npx tsc --noEmit` and `npx next lint --file <changed files>` from `frontend/`, plus `npx vitest run <test>` where a test is named.

## Review Focus

- A sheet that now covers the bottom bar must still be closable (visible X / Cancel above the home indicator) — check safe-area padding on bottom sheets.
- The phone tab strip must not appear twice on Orders, Numbers or Reports (they have their own phone switches).
- Bars moved above the bottom bar must still sit flush at the bottom on desktop (`lg:` value restored).
- Opening a chat's customer sheet, then using the phone back gesture, must not leave the user stranded on a blank screen.
- Time chips must never offer a time outside the allowed window (Reach: 10 AM–9 PM rule in `reachSchedule.ts`) or in the past.

---

## Wave 1 — shared fixes

### Task 1: Header tabs on phones

**Files:**
- Create: `frontend/components/nav/headerTabs.ts` (move `HeaderTab`, `HeaderTabSet`, `HEADER_TABS`, `activeHeaderTab` here from `components/AppHeader.tsx:104-187`)
- Create: `frontend/components/nav/headerTabs.test.ts`
- Modify: `frontend/components/AppHeader.tsx` (import from the module; `HeaderTabSwitch` gets `placement?: "header" | "strip"`; render the strip after `<PageChips placement="strip" />`)

**Interfaces:**
- Produces: `phoneHeaderTabs(pathname: string): HeaderTabSet | null` — the set for pathname, or null for `/dashboard/deals`, `/dashboard/numbers`, `/dashboard/analytics` (they have their own phone switches) and for paths with no set.

- [ ] Test: `phoneHeaderTabs("/dashboard/leads")` has 5 tabs, first value `"people"`; `phoneHeaderTabs("/dashboard/deals")`, `("/dashboard/numbers")`, `("/dashboard/analytics")`, `("/dashboard/more")` are `null`; `activeHeaderTab(HEADER_TABS["/dashboard/leads"], "reengagement").value === "follow-ups"`.
- [ ] Run, see it fail; implement; run, see it pass.
- [ ] Strip look = `PageChips` strip (`min-w-0 px-3 pt-3 sm:px-4 md:hidden` wrapper, `flex w-max max-w-full overflow-x-auto` row, `px-3 py-1.5 text-xs` chips); active chip scrolled into view on mount.

### Task 2: Bars above the bottom bar

**Files (exact lines):** `templates/new/page.tsx:633`, `templates/carousel/page.tsx:559`, `templates/upload/page.tsx:349` (`sticky bottom-0 … -mx-4` → `sticky bottom-[calc(var(--mobile-nav-h)+env(safe-area-inset-bottom,0px))] lg:bottom-0 … -mx-3 sm:-mx-4`), `services/page.tsx:442` (`bottom-0` → same + `lg:bottom-0`, `-mx-4` → `-mx-3`), `settings/account/page.tsx:142` and `settings/auto-reply/page.tsx:239` (`bottom-3` → `…+0.5rem)] lg:bottom-3`), `otp/SettingsTab.tsx:389` (`bottom-4` → `…+0.5rem)] lg:bottom-4`), `subscriptions/CartBuilder.tsx:640` (`bottom-0` → `…)] lg:bottom-0`, Submit button `min-h-11 text-sm` on phone), `deals/new-bill/page.tsx:629` (`bottom-4` → `…+0.5rem)]`), `scheduled-templates/ScheduledTemplatesClient.tsx:1108` (`bottom-5` → `…+0.75rem)] lg:bottom-5`). All under `frontend/app/dashboard/`.

- [ ] Each class swapped exactly; tsc + lint pass.

### Task 3: Pop-ups on the dialog layer

**Files:** `z-50` → `z-dialog` in `analytics/reportsUi.tsx:239`, `forms/page.tsx:178`, `home/EditTodayModal.tsx:239`, `inbound-leads/InboundLeadsClient.tsx:386`, `leads/SaidStopPanel.tsx:588`, `outbound-leads/CampaignResultsDrawer.tsx:57`, `telecalling/scheduled/ScheduleModals.tsx:16`, `components/agents/KbDialog.tsx:74`, `components/first-setup/ConnectStep.tsx:52`; `z-[60]` → `z-dialog` in `otp/otpUi.tsx` overlay. Bottom sheets (`items-end`) get `pb-[env(safe-area-inset-bottom)]` on the panel footer. `components/FeedbackModal.tsx`: render through `createPortal(…, document.body)` (as `NotificationBell` does).

- [ ] Each swap exact; tsc + lint pass.

### Task 4: Toasts out of the header on phones

**Files:** Create `frontend/components/AppToaster.tsx` (client: `useIsPhone()` → phone `position="bottom-center"`, `mobileOffset={{ bottom: "calc(var(--mobile-nav-h) + env(safe-area-inset-bottom) + 12px)" }}`; desktop unchanged `top-right`; keep `richColors closeButton`). Modify `frontend/app/layout.tsx:100` to use it.

### Task 5: Bottom bar lights "More" for pages opened from More

**Files:** Create `frontend/components/nav/mobileNavActive.ts` + test; modify `MobileDashboardNav.tsx:79-82`.

**Interfaces:** `pickActiveTab(hrefs: string[], pathname: string, moreHref: string): string | undefined` — exact match for `/dashboard`, prefix match (`isActive`) for others, else `moreHref` when it is in `hrefs` and pathname starts with `/dashboard`.

- [ ] Test: `/dashboard/templates` → more; `/dashboard/leads/abc` → `/dashboard/leads`; `/dashboard` → `/dashboard`; `/dashboard/conversations` → chats; hrefs without more → undefined for `/dashboard/templates`.

### Task 6: More page search stays at the top

**Files:** `app/dashboard/more/MoreClient.tsx:71` — search wrapper `sticky top-14 z-20` with page background so rows scroll under it.

---

## Wave 2 — fewer taps (one worker per area, disjoint files)

### Task 7: Templates (files: `app/dashboard/templates/**`)
- Rejected row / modal "Fix" opens `/dashboard/templates/[id]?edit=1`; `[id]/page.tsx` starts in edit mode when `edit=1` (today `useState(false)` at :56).
- Phone list modal footer gains the desktop card's Duplicate and Use-for-broadcast actions (reuse the existing handlers in `templates/page.tsx`).
- After a successful submit (`new/page.tsx:254`) show a toast: "Sent to Meta for approval. Usually approved within minutes to 24 hours."
- Builder "Back" button hidden on phones (`hidden md:inline-flex`).
- Remove nothing else; the AstroTamil/adminweb line is the owner's call (not in scope).

### Task 8: Home quick actions (files: `app/dashboard/home/PhoneToday.tsx` or a new `home/PhoneQuickActions.tsx`)
- Phone-only row of compact buttons (h-9, 13px): New bill → `/dashboard/deals/new-bill` (needs `deals.manage` or owner), New template → `/dashboard/templates/new` (needs `templates.manage` + outbound messaging), Broadcast → `/dashboard/outbound-leads` (needs `outbound_leads.manage` + outbound messaging). Gate with the same access rules the More menu uses (`useNavAccess`). Hide the row when no action is allowed.

### Task 9: Chats (files: `app/dashboard/conversations/page.tsx`, `components/chat-thread.tsx`)
- Phone "Customer" button in the thread header opens `LeadDetailsPanel` as a full-screen sheet (`fixed inset-0 z-dialog lg:hidden`, header with close) — today it is `hidden xl:block` (page.tsx:441) and the toggle is `hidden xl:flex` (chat-thread.tsx:745). Phone users reach Assign through it.
- After a reply is sent, focus returns to the message box when it had focus (keyboard stays up).
- On touch screens (`matchMedia("(pointer: coarse)")`) Enter inserts a new line; Send button sends. Desktop unchanged.
- Phone back button closes an open chat (return to the list) — only if it can be done with Next 14.2's native `history.pushState` support without a full reload; otherwise leave it and report.

### Task 10: Calls — callback time chips (files: `app/dashboard/telecalling/components/wrapup/QuickTimePicker.tsx` + test for the time helper)
- Add a "Tomorrow" chip that reveals hour chips 9, 10, 11, 12, 2, 4, 6 (AM/PM as labelled); one tap sets tomorrow at that hour (local time). Existing presets stay. Pure helper `tomorrowAt(hour: number, now: Date): Date` with a test (e.g. now = 2026-11-25 22:30 → 2026-11-26 11:00 for 11).

### Task 11: Reach — schedule chips (files: `app/dashboard/outbound-leads/page.tsx` near :2347 only, `reachSchedule.ts` + test)
- Chips above the "Later" date-time field: "Today 6 PM" (only when still in the future and allowed), "Tomorrow 10 AM", "Tomorrow 6 PM". Tapping fills the existing field. Use the existing allowed-window rule in `reachSchedule.ts`; add a pure `scheduleChoices(now: Date)` with a test.

### Task 12: Small jumps on other screens (files listed per item)
- Customers rows: a Chat icon button beside Call (44px like Call), linking to the chat for that lead (`leads/LeadsClient.tsx`; use the conversations deep-link the page already reads).
- Roles: choosing a role or a user on phones scrolls the editor into view (`roles/page.tsx:327-353`).
- Order page: `?focus=payment` scrolls the Payments panel into view (`deals/orders/[id]/page.tsx:106`).
- New bill: qty −/+ buttons `h-8 w-8` (`deals/new-bill/page.tsx:520,522`); the size/colour picker scrolls into view when opened (:402).
- Brain workspace tabs: one line, `h-8 text-xs` below `lg`, scroll sideways (`components/brain/BrainWorkspace.tsx:389,400`).
- Teach: Offers first on phones (`teach/page.tsx:75-82`, `order-first lg:order-none`).

---

## Next (not in this plan)

- Wave 3: tables → `MobileRecord` cards (Orders, Catalogue, Purchases, Roles grid, Team, Call IQ, Meta Ads, form answers, Chats folders, OTP history, AI agents).
- Wave 4: tiles → one status line on phones, 44px secondaries down, tiny targets up, instant-save switches behind Save, plain words.
- Needs a real Android phone: keyboard viewport (`interactiveWidget`), "Save & call next" (the SIM dialer must open from the tap itself, so saving first breaks it).

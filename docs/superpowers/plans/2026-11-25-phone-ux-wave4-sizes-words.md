# Phone UX Wave 4: Sizes and Words — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** On phones, secondary controls stop taking main-action space, small often-tapped controls reach fingertip size, tall number tiles shrink to compact lines, and screen copy uses plain words.

**Architecture:** Frontend only. Shared components first (controller: `components/ui/controls.tsx` switch/tick hit areas, `components/kpi-card.tsx` and `components/stat-card.tsx` phone sizing, `components/nav/headerTabs.ts` labels), then one worker per screen area on disjoint files. Phone-only changes use `max-md:`/`max-lg:` or `md:`/`lg:` restores, so desktop stays the same.

**Spec:** Audit report https://claude.ai/artifact/PZTUr9bMGCAed7Ng4DhDXi (causes 5 "Too big" and 6 "Too small", per-area findings, "Plain words sweep"); earlier waves `2026-11-25-phone-ux-fixes.md`, `2026-11-25-phone-ux-wave3-cards.md`.

## Global Constraints

- Sizes on phones: main action (Send, Save, Reply, Call, Submit) 44px; secondary buttons 36–40px; chips and tabs 28–32px with 12–13px text on ONE line that scrolls sideways; anything tapped often ≥ 32px (an invisible hit area is fine); number tiles compact: no hint line on phones, or one line of figures.
- Settings apply only on a Save button (no instant-save switches on settings pages; a header switch only marks the page Unsaved).
- No back-link rows on phones ("← Orders", "← All forms", "Back to …"): the header and bottom bar already navigate.
- Plain words: "Anril" (never "Aira", never "AI agent" for our assistant); no RAG, rubric, dispatch, disposition, drip, tier, WABA on phone screens where a plain phrase exists.
- Desktop (lg+, and md+ where the page switches at md) must look and behave as before unless the item says otherwise.
- Tailwind 3.4 only. No new data fetching. No git commit/push.

## Review Focus

- A smaller control must still be ≥ 28px and keep its label or aria-label.
- Folding actions into a ⋯ menu must keep every action reachable on phones.
- Draft-and-Save conversions must not lose a change when the user navigates away without saving (show Unsaved; no silent save).
- Copy changes must not change values sent to the API (labels only).
- Hiding a hint line must not hide the number itself.

## Tasks (disjoint files; see dispatch briefs for the exact items)

| Task | Area | Main files (under `frontend/`) |
|---|---|---|
| S | Shared (controller) | `components/ui/controls.tsx`, `components/kpi-card.tsx`, `components/stat-card.tsx`, `components/nav/headerTabs.ts` |
| 1 | Chats | `components/chat-thread.tsx`, `components/conversation-list.tsx` |
| 2 | Customers | `app/dashboard/leads/LeadsClient.tsx`, `leads/[id]/page.tsx`, `leads/SaidStopPanel.tsx` |
| 3 | Home, More, shell | `app/dashboard/home/*` (not quickActions), `more/MoreClient.tsx`, `components/WhatsAppDisconnectedBanner.tsx`, `components/ClaimBanner.tsx`, `components/FeedbackModal.tsx`, `components/ConfirmModal.tsx`, `components/WaitingLeadsPrompt.tsx` |
| 4 | Templates | `app/dashboard/templates/**` |
| 5 | Calls | `app/dashboard/telecalling/**` (not BulkAssignment, assignment-log, quickTimes), `components/LeadDetailPanel.tsx`, `app/dashboard/notes/**`, `components/call-iq/review/**` |
| 6 | Reach & automations | `app/dashboard/outbound-leads/**`, `app/dashboard/auto-messages/**`, `app/dashboard/settings/follow-ups/**`, `app/dashboard/automations/**`, `components/automations/**` |
| 7 | Brain & knowledge | `app/dashboard/brain/**`, `app/dashboard/knowledge/**`, `app/dashboard/teach/**`, `settings/auto-reply/**`, `settings/inbox/**`, `components/brain/**` |
| 8 | WhatsApp setup & lead sources | `numbers/**`, `qr-links/**`, `forms/**`, `bookings/**`, `inbound-leads/**`, `settings/connect-channels/**`, `channels/**` |
| 9 | Team, Call IQ, Reports | `analytics/**`, `team/**`, `roles/**`, `call-iq/**`, `components/call-iq/**` (not review), `components/analytics/**` |
| 10 | Orders, catalogue, purchases | `deals/**`, `catalog/**`, `purchases/**`, `expenses/**`, `services/**` |
| 11 | Settings & account | `settings/**` (not auto-reply, inbox, follow-ups, connect-channels), `components/OpenHoursEditor.tsx`, `profile/**`, `subscription*/**`, `agents/**`, `components/agents/**`, `(auth)/**` |

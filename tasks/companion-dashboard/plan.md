# Implementation Plan: Anril Agents dashboard (companion-dashboard)

Mockup (approved look): https://claude.ai/artifact/VKtnRFjcoa5cEqaehQo6Wr (v6: product rail; "Aira" is now "Anril").
Builds on companion-core (backend done: migrations 248–250, routes/companions.py, routes/companion_public.py).
Tasks: tasks/companion-dashboard/todo.md

## Overview
Anril Agents is a second product next to Anril, not a row in Anril's menu. A thin product rail on the far left holds
one icon per product (Anril, Agents); clicking Agents swaps Anril's navy menu for the light Supermemory-style Agents
menu. Pages live at /dashboard/agents.
The backend already has almost every owner endpoint. The frontend has nothing yet. Phase 1 is frontend-only on top of
existing routes. Phases 2–3 add the few backend pieces the mockup needs that do not exist yet.

Worked example used through this plan: Astrotamil's owner opens Anril Agents, edits "Jothidar AI", tests it in the
Playground as a test person, uploads "Porutham guide.pdf" under the tag "astrology books", copies the install snippet,
and later looks up Karthik (user id 48213) on Memories to check what Jothidar learned.

## What exists vs. what is new (verified 2026-11-09)
| Page | Backend today | New backend needed |
|---|---|---|
| Characters + editor | GET/POST /companions, GET/PATCH /companions/{id} | none |
| API Keys | GET/POST/DELETE /companions/keys | none |
| Install | GET /companions/{id}/install | none |
| Playground (chat) | POST /companions/{id}/test-chat, /test-chat/continue | none |
| Settings | GET/PUT /companions/memory-settings | none |
| Knowledge | /knowledge/upload-document with campaign tag (rules already kept out of the Description for tagged files) | none |
| Memories | GET /{id}/people/{ext}/memory, DELETE one fact; forget_person() exists, no route | list people; forget-person route |
| Overview | — | small stats endpoint |
| Playground Search | _semantic_search returns scores but is private; facts have no embeddings | search endpoint |
| Playground model picker + compare | _llm_chat has no model parameter | per-call model override; no-memory flag |
| Requests | latency only logged; no request table | new table + writes + list route |
| User Insights, web-URL import | — | later, not in this plan |

## Architecture decisions
- **Product rail (the entry point):** a new ProductRail component, 56 px, fixed at the far left on lg+ screens, on
  every dashboard page including Conversations (which hides Anril's menu today; the rail stays). Two icons: Anril
  (chat bubble) and Agents (✦). The Sidebar and AppHeader shift right by the rail width through one new CSS variable
  (--product-rail-width) used next to --sidebar-width in globals.css, ClientLayout, sidebar.tsx, AppHeader.tsx,
  conversations/page.tsx and useSidebarRail.ts. Clicking a product returns to the last page you had open there;
  clicking the active product goes to its home (/dashboard or /dashboard/agents).
  Example: the Astrotamil owner is on Inbound Leads, clicks ✦ Agents, edits Jothidar AI, clicks Anril, and is back
  on Inbound Leads.
- **Route + shell:** pages stay under frontend/app/dashboard/agents/ so they reuse the dashboard's server auth check,
  onboarding redirect, subscription and role providers (a top-level /agents would have to copy all of that).
  ClientLayout adds isAgents (like isMetaAds/isInbox) and renders AgentsSidebar instead of Sidebar. No "Back to
  dashboard" link; the rail does that job.
- **Phone:** the rail is hidden below lg. MoreMenu (Anril's ☰ drawer) and the Agents drawer both get an
  "Anril | Agents" switch at the top; MobileDashboardNav (Anril's bottom bar) is hidden on Agents pages.
- **Who sees the Agents icon:** only users whose role has companions.manage (Task 1b). Without it the rail shows
  just Anril; open question below on whether tenants without a companion add-on see it.
- **Permission:** add a new key companions.manage (the dashboard rule: every new page gets its own key, in four places,
  plus a backfill migration granting it to roles that have settings.manage). Companion routes switch from
  settings.manage to companions.manage. The migration needs Prem's yes before it is applied.
- **One knowledge base:** the Agents Knowledge page uploads through the existing pipeline with the character's tag.
  Tagged uploads already skip the Description, so nothing new is needed for "facts only". Example: Porutham guide.pdf
  tagged "astrology books" adds facts Jothidar can read and leaves Anril's Business Description untouched.
- **Memory search honesty:** memory facts are not embedded, so v1 memory search is a word match with no score; only
  Knowledge results show a match score. The UI shows the score column only for Knowledge.
- **Model override is test-only:** the model picker passes a model to test-chat only; live replies keep the tenant's
  ai_reply_model. Compare-without-memory costs one extra LLM call per test message.
- **Requests log stores no message text** (rule: never log fact or message text): time, character, type, status, ms.

## Phases and tasks (details in todo.md)
Phase 1 — frontend on existing APIs
1. Product rail and Agents shell (M)
1b. companions.manage permission key (M)
2. Characters list and editor (M)
3. API Keys and Install (S)
4. Playground chat (S)
5. Knowledge page, Import style (S)
6. Settings page (XS)
Checkpoint A: typecheck, lint, backend suite; UI QA pass as the UI test tenant.

Phase 2 — small backend additions
7. Memories: list people, forget person, page (M)
8. Overview stats and page (S)
9. Playground Search: knowledge scores + memory word match (M)
10. Playground model picker and compare without memory (M)
Checkpoint B: same checks; eval that the live reply path is unchanged (test-chat override never touches live replies).

Phase 3 — new table
11. Requests log: migration, writes in public routes, list route, page (M)
Checkpoint C: migration reviewed by Prem and applied; Requests page shows rows from a widget chat.

## Risks and mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Model override leaks into live WhatsApp replies (ai_reply is shared) | High | Keyword-only parameter defaulting to None; test proves generate_reply never passes it |
| Permission switch locks out managers who use companions today | Med | Backfill migration grants companions.manage to every role with settings.manage, applied before the backend deploy |
| Request-log writes slow the public chat path | Med | One insert after the reply, errors swallowed and logged; no text stored |
| Teammate edits sidebar/ClientLayout in parallel | Med | git fetch + check HEAD..origin/main on those files before each commit. As of 2026-11-09 origin/main has an unmerged keerthi-sarav change to AppHeader.tsx: pull before Task 1 |
| Rail offset breaks a page that positions itself against --sidebar-width (Conversations, header, sidebar fold/peek) | Med | One variable for the rail width, every --sidebar-width offset listed in Task 1; screenshot Dashboard, Conversations, Meta Ads and a folded sidebar before/after |
| Search endpoint exposes another tenant's chunks | High | Same tenant filter as get_knowledge_context; tenant test |

## Open questions
- Web-URL import and User Insights stay out of this plan. OK?
- Should the Agents icon show on the rail for every plan, or only tenants with a companion add-on? (Default in this
  plan: everyone with companions.manage.)

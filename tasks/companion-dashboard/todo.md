# Anril Agents dashboard: tasks

Plan: tasks/companion-dashboard/plan.md · Mockup v6 (product rail): https://claude.ai/artifact/VKtnRFjcoa5cEqaehQo6Wr
Checks for every task: `cd backend && python -m pytest` (backend tasks), `cd frontend && npx tsc --noEmit && npm run lint` (frontend tasks).

## Phase 1: frontend on existing APIs

### - [ ] Task 1: Product rail and Agents shell (M)
Example: the Astrotamil owner is on Inbound Leads, clicks ✦ Agents on the rail, sees the Agents menu, clicks Anril, and is back on Inbound Leads.
- [ ] ProductRail (56 px, fixed far left, lg+) on every dashboard page, Conversations included: Anril icon and ✦ Agents icon; active product highlighted; click returns to the last page in that product; click on the active product goes to its home.
- [ ] Sidebar, AppHeader and page content shift right by --product-rail-width; the sidebar fold/peek and the Conversations layout still line up (no overlap, no gap).
- [ ] /dashboard/agents/* renders AgentsSidebar (Overview, Playground, Characters, Memories, Knowledge, API Keys, Install, Requests, User Insights "Later", Settings) instead of Sidebar; no "Back to dashboard" link.
- [ ] Phone (< lg): rail hidden; "Anril | Agents" switch at the top of MoreMenu and of the Agents drawer; MobileDashboardNav hidden on Agents pages; no horizontal scroll at 375 px.
- Verify: typecheck + lint; screenshots before/after of Dashboard, Conversations, Meta Ads, folded sidebar, an Agents page, and phone with each drawer open.
- Files: frontend/components/nav/ProductRail.tsx (new), frontend/components/agents/AgentsSidebar.tsx (new), frontend/app/dashboard/agents/page.tsx (new, placeholder), frontend/app/dashboard/ClientLayout.tsx, frontend/app/globals.css, frontend/components/sidebar.tsx, frontend/components/AppHeader.tsx, frontend/components/MoreMenu.tsx, frontend/app/dashboard/conversations/page.tsx, frontend/components/nav/useSidebarRail.ts (offset only, if it reads --sidebar-width)
- Before starting: pull origin/main (keerthi-sarav's AppHeader.tsx change).
- Deps: none

### - [ ] Task 1b: companions.manage permission key (M)
- [ ] companions.manage exists in PERMISSION_CATALOG, ACCESS_MODULES (Roles page), and gates the rail's Agents icon, the MoreMenu switch and every routes/companions.py route (replacing settings.manage).
- [ ] A user without the key sees only Anril on the rail; typing /dashboard/agents sends them to /dashboard.
- [ ] Migration 251 grants companions.manage to every role that has settings.manage (written, NOT applied until Prem says yes).
- Verify: route-guard test (a role without the key gets 403); backend suite.
- Files: backend/app/services/rbac.py, backend/app/routes/companions.py, backend/tests/test_companion_permission.py, backend/supabase/migrations/251_companions_permission.sql, frontend/app/dashboard/roles/page.tsx, frontend/components/nav/ProductRail.tsx, frontend/components/MoreMenu.tsx
- Deps: 1

### - [ ] Task 2: Characters list and editor (M)
Example: owner opens Jothidar AI, changes default mood to warm, picks tag "astrology books", sets status Live.
- [ ] List shows name, status pill, language, memory level; "+ New character" creates a Draft and opens it.
- [ ] Editor tabs Persona / Memory / Knowledge save through PATCH; a 422 shows the field error inline; 409 on duplicate name shows "Name already used".
- [ ] Knowledge tab tag picker lists only this tenant's tags.
- Files: frontend/lib/api.ts (companions helpers), frontend/app/dashboard/agents/characters/page.tsx, .../characters/[id]/page.tsx, frontend/components/agents/CharacterEditor.tsx
- Deps: 1

### - [ ] Task 3: API Keys and Install (S)
- [ ] Keys page lists keys (prefix, created, last used); create shows the full key once with Copy and a "you won't see it again" line; revoke asks to confirm. At 2 active keys, Create is disabled with the reason.
- [ ] Install page shows the AI prompt, widget and server snippets from GET /{id}/install, and "Create a key first" when has_active_key is false.
- Files: frontend/app/dashboard/agents/keys/page.tsx, .../install/page.tsx, frontend/lib/api.ts
- Deps: 1

### - [ ] Task 4: Playground chat (S)
Example: owner types "Kalyanam eppo nadakkum?" as Test person and sees the reply, mood and tool calls.
- [ ] Character picker; chat calls test-chat; a tool_call status shows "asked your app: get_chart(…)" and the owner can answer it by hand (test-chat/continue) or skip.
- [ ] Draft characters work; paused shows the 409 message.
- [ ] "This reply" panel: mood, model, reply time (measured in the browser).
- Files: frontend/app/dashboard/agents/playground/page.tsx, frontend/components/agents/PlaygroundChat.tsx, frontend/lib/api.ts
- Deps: 2

### - [ ] Task 5: Knowledge page, Import style (S)
Example: drop Porutham guide.pdf, tag "astrology books", Import → Processing shows it until the document is ready.
- [ ] Drop zone + browse use the existing upload endpoint with the chosen tag (default: the selected character's tag).
- [ ] "Facts only" row and "Won't change Anril's Business Description" note; Processing panel polls listDocuments until ready/error.
- [ ] Tag table: tag, files, read by (characters using it), updated.
- Files: frontend/app/dashboard/agents/knowledge/page.tsx, frontend/components/agents/ImportCard.tsx
- Deps: 2

### - [ ] Task 6: Settings page (XS)
- [ ] Memory scope (this character only / whole business) via GET/PUT memory-settings, with the Karthik example line from the mockup.
- Files: frontend/app/dashboard/agents/settings/page.tsx
- Deps: 1

### Checkpoint A
- [ ] Typecheck, lint, backend suite pass. UI QA pass as the UI test tenant (backend via `make dev-backend`), desktop + phone screenshots.
- [ ] Prem reviews; migration 251 applied with Prem's yes before any backend deploy.

## Phase 2: small backend additions

### - [ ] Task 7: Memories (M)
Example: search "48213" → Karthik, 4 facts, 46 messages; open → facts list + graph; delete one fact; "Delete this person" wipes chats and facts.
- [ ] GET /companions/{id}/people?q=&limit= returns external id, display name, fact count, message count, last seen (tenant filtered, paged).
- [ ] DELETE /companions/people/{external_user_id} calls engine.forget_person; audit-logged; 404 for unknown.
- [ ] Page: list + detail (List / Graph); privacy mode B shows the 403 reason instead of facts.
- Verify: tenant-isolation test for both routes; forget test (rows gone).
- Files: backend/app/routes/companions.py, backend/app/companion/store.py, backend/tests/test_companion_people.py, frontend/app/dashboard/agents/memories/page.tsx, frontend/lib/api.ts
- Deps: 1

### - [ ] Task 8: Overview (S)
- [ ] GET /companions/overview: live characters, people, messages this week, active keys, tenant model name.
- [ ] Page: setup checklist (character live → key created → seen on your site via key last_used_at) + 4 stat tiles + Copy prompt.
- Files: backend/app/routes/companions.py, backend/tests/test_companion_overview.py, frontend/app/dashboard/agents/page.tsx
- Deps: 1

### - [ ] Task 9: Playground Search (M)
Example: Knowledge, "lagna" → "Dasha periods explained.pdf · match 0.88"; Memories, Karthik, "lagna" → "Lagnam Kumbham…".
- [ ] POST /companions/{id}/search {in: knowledge|memories, q, limit, external_user_id?}; knowledge returns chunks with similarity from the character's tag (public wrapper over _semantic_search, same tenant filter); memories returns word-matched facts, no score.
- [ ] No message text logged; limit capped at 20.
- [ ] Playground Search tab + Knowledge/Memories toggle; score shown for Knowledge only.
- Files: backend/app/services/knowledge_service.py, backend/app/routes/companions.py, backend/tests/test_companion_search.py, frontend/components/agents/PlaygroundSearch.tsx
- Deps: 4

### - [ ] Task 10: Model picker and compare without memory (M)
Example: pick Gemini 3.1 Flash, tick Compare → two bubbles, the second labelled "Without memory".
- [ ] _llm_chat / _llm_chat_with_tools accept keyword-only model=None; test-chat accepts model (allow-list of providers the tenant has keys for) and use_memory=false.
- [ ] Test proves generate_reply and the public companion routes never pass model.
- [ ] Composer bar: model select + Compare checkbox (second call with use_memory=false).
- Files: backend/app/services/ai_reply.py, backend/app/companion/engine.py, backend/app/routes/companions.py, backend/tests/test_companion_test_chat_model.py, frontend/components/agents/PlaygroundChat.tsx
- Deps: 4

### Checkpoint B
- [ ] Suites pass; live-reply eval unchanged; UI QA screenshots of Memories, Overview, Search, Compare.

## Phase 3: request log

### - [ ] Task 11: Requests (M)
Example: Karthik chats on astrotamil.com → a row "10:42 · Chat · Jothidar AI · 48213 · 200 · 1.4 s".
- [ ] Migration 252 companion_request_log (tenant_id, companion_id, kind, external_user_id, status, ms, created_at), RLS on, no policies, index (tenant_id, created_at desc). No message text column.
- [ ] Public routes insert one row per call after responding; insert errors are swallowed and logged.
- [ ] GET /companions/requests (filters: kind, status, days) + daily counts; page with filters, stat tiles, bar chart, table.
- Verify: tenant test; a failing insert does not fail the chat.
- Files: backend/supabase/migrations/252_companion_request_log.sql, backend/app/routes/companion_public.py, backend/app/companion/store.py, backend/app/routes/companions.py, frontend/app/dashboard/agents/requests/page.tsx
- Deps: 1

### Checkpoint C
- [ ] Prem reviews and approves migration 252; applied; Requests shows rows from a real widget chat.

# companion-memory: tasks

Plan: [plan.md](plan.md) · Spec: [companion-memory design](../../docs/superpowers/specs/2026-11-09-companion-memory-design.md)
Focused test command: cd backend && python -m pytest tests/test_companion_*.py -q

## Phase 1: The card engine, end to end

### - [x] Task 1: Migration 249 and the fact store (M)
Write 249_companion_memory.sql per spec §3.1: companions.memory_engine (card/mem0, default card), companion_tenant_settings, companion_memory_facts, companion_memory_state. RLS on, zero policies. Add store functions for facts (list active + closed-in-90-days, insert, close, update, delete, count active), state (get/upsert watermark, reset), and tenant settings (get with default, upsert). Add memory_engine to the Pydantic models.
- Acceptance:
  - [x] House style (header, SET LOCAL lock_timeout, IF NOT EXISTS), tenant_id on every table, CHECKs on section/status/scope/engine, text ≤300, index (tenant_id, end_user_id, status).
  - [x] Every store query filters tenant_id; a wrong tenant reads nothing and changes nothing.
  - [x] A pair holds at most 60 fact rows: an add evicts the oldest closed fact, then the oldest active preference, else it's refused (spec §3.1); memory_engine "redis" → 422.
- Verify: test_companion_memory_store.py passes.
- Depends on: none
- Files: backend/supabase/migrations/249_companion_memory.sql, backend/app/companion/store.py, models.py, backend/tests/test_companion_memory_store.py

### - [x] Task 2: Provider wiring (S)
memory.py: tenant_id becomes the first parameter of context_for, record_turn and forget; provider_for(level, engine) returns Level1History for level 1 and the card for level 2 (Mem0 later). engine.py passes tenant_id and the character's memory_engine.
- Acceptance:
  - [ ] Level 1 behaviour and every existing companion test are unchanged.
  - [ ] A Level 2 character's prompt gets context_for's text under ABOUT THIS USER; a context_for error still gives "".
- Verify: full companion suite passes.
- Depends on: Task 1, and the Companion session's Checkpoint C commits landing
- Files: backend/app/companion/memory.py, engine.py, backend/tests/test_companion_engine.py

### - [x] Task 3: MemoryCard (M)
memory_card.py: build the extraction prompt (spec §3.3), parse the ops JSON tolerantly, validate ops, apply them, and render context_for.
- Acceptance:
  - [ ] Ops validation: unknown fact id, bad section, text over 300, more than 10 ops, or never-save content (6+ digit runs, OTP/password/aadhaar/PAN words) → that op is dropped, the rest apply.
  - [ ] Broken JSON → no change and an error the sweep can count.
  - [ ] Render: open threads first, then profile, people, life, preferences; closed facts within 90 days marked with their end date; capped at 2,000 chars.
  - [ ] Facts are written in the character's language setting (prompt test), and caplog holds no fact or message text.
- Verify: test_companion_memory_card.py passes.
- Depends on: Task 2
- Files: backend/app/companion/memory_card.py, backend/tests/test_companion_memory_card.py

### - [x] Task 4: The sweep (M)
memory_sweep.py: run_memory_sweep() finds up to 20 Level 2 pairs with messages past their watermark, sends at most 20 new messages each to the card with purpose "companion_memory", and moves the watermark on success. Register the periodic "companion-memory" task (every minute, class A, _one_at_a_time).
- Acceptance:
  - [ ] The spec §1 worked example passes: Karthik's day-1 messages → 4 facts; the job-change message closes one fact and adds one.
  - [ ] Level 1 characters and pairs with nothing new cost zero AI calls.
  - [ ] An AI error leaves the watermark; the 3rd failure in a row moves it on with a warning (no message text in the log).
  - [ ] The task has a RETRY_CLASS entry and the queue-registration tests pass.
- Verify: test_companion_memory_sweep.py passes, and the full backend suite passes.
- Depends on: Task 3
- Files: backend/app/companion/memory_sweep.py, backend/app/queue/tasks.py, backend/tests/test_companion_memory_sweep.py

### Checkpoint A: Card engine works
- [ ] Companion tests and the full backend suite pass.
- [ ] Prem reviews the migration SQL and the extraction prompt text.

## Phase 2: Scope, visibility and forget

### - [x] Task 5: Scope and visibility routes (M)
Business scope on read (own facts first, then other characters'), list_memory and forget_fact, the ABOUT THIS USER label change in prompt.py, and the routes: GET/PUT /api/v1/companions/memory-settings (declared before /{id}), GET /api/v1/companions/{id}/people/{external_user_id}/memory, DELETE .../memory/{fact_id}.
- Acceptance:
  - [x] Character scope: Vastu Guru never sees Jothidar's facts. Business scope: it does, each with learned_by.
  - [x] Privacy mode B → 403 on the owner routes; another tenant's character or fact → 404.
  - [x] The tenant-audit pre-commit hook passes on routes/companions.py.
- Verify: test_companion_memory_scope.py and test_companion_memory_routes.py pass.
- Depends on: Task 2 (parallel with Tasks 3–4)
- Files: backend/app/companion/memory.py, store.py, prompt.py, backend/app/routes/companions.py, tests

### - [x] Task 6: Forget-me for both engines and the engine switch (S)
forget_person wipes facts and state (and Mem0 data when present); switching a character's memory_engine resets its watermarks.
- Acceptance:
  - [x] After forget: 0 facts, 0 state rows for the person, across all characters; others untouched.
  - [x] Switching card → mem0 → card resets watermarks (only that character's, only on a real change).
  - [ ] "Keeps no stale facts in the prompt": open until T8. mem0 still falls back to the card, so card facts stay in the prompt; per spec §3.7 they stay until forget-me.
- Verify: extended test_companion_forget.py passes.
- Depends on: Task 4
- Files: backend/app/companion/engine.py, store.py, backend/tests/test_companion_forget.py

### Checkpoint B: Live (needs Prem's yes to apply 249)
- [ ] **Apply 249 before any push of this code.** Without it, creating a character fails (memory_engine column) and the every-minute job errors on each tick.
- [ ] Re-check the latest migration number, then apply 249. list_tables shows the new tables with RLS on, and pg_policies has 0 rows for them.
- [ ] Set a Groq key on the UI test tenant. Via make dev-backend: chat with a Level 2 Jothidar, call run_memory_sweep() directly, then confirm the next reply uses the facts and tenant_token_usage gains companion_memory rows.

## Phase 3: Mem0

### - [ ] Task 7: Mem0 spike (S, time-boxed to 2 h, scratch venv, no repo change)
Answer: can Mem0 2.2.1 use our Jina embeddings through a wrapper; can its pgvector tables be pre-created with RLS on; does Groq extraction work without JSON mode issues; what does one add() cost in calls and time.
- Acceptance: a short written result in this file; a go / no-go for Task 8.
- Depends on: none

### - [ ] Task 8: Mem0Engine (M, only after Prem's yes on mem0ai)
memory_mem0.py: one AsyncMemory per tenant (cached), MEM0_TELEMETRY=False before import, add with user_id/agent_id, search drops agent_id in business scope, card fallback for Sarvam, no Jina key, or a failed import.
- Acceptance:
  - [ ] The spec §1 worked example passes with memory_engine "mem0" (Mem0 mocked).
  - [ ] Each fallback path logs one warning and uses the card.
  - [ ] Forget-me calls delete_all(user_id).
- Verify: test_companion_memory_mem0.py passes; the app and tests still start without mem0ai installed.
- Depends on: Task 7, Prem's yes
- Files: backend/app/companion/memory_mem0.py, memory.py, requirements.txt, backend/tests/test_companion_memory_mem0.py

Review fixes (2026-11-09, code-reviewer on T1–T6), each with a test that failed before:
- HIGH: business scope showed the owner facts learned by a privacy-mode-B character. Owner list and delete now drop them; the characters still share them.
- Sweep: a pair whose conversation clock ran ahead stayed due forever (watermark now catches up); oldest activity goes first across all characters; failures back off 1, 2, 4, 8, 16 min and give up after ~31 min (was 3 min); "forget me" during the AI call writes nothing; watermarks and active conversations page past 1000 rows.
- Card: duplicate adds skipped; a non-string ref drops one op, not the batch; dd-mm-yyyy and dd.mm.yyyy birth dates kept; message text flattened to one line and the card fenced as data.
- Left as is: tenant_id isn't tied to companion_id by a composite foreign key (app code enforces it).

### Checkpoint C: Complete
- [ ] All spec §8 success criteria are met, and bash scripts/verify.sh is green.
- [ ] /review on the full diff, then /code-simplify. Nothing is pushed without Prem's yes.

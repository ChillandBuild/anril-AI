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
memory_sweep.py: run_memory_sweep() finds up to 20 Level 2 pairs with messages past their watermark, sends at most 20 new messages each to the card with purpose "companion_memory", and moves the watermark on success. Register the periodic "companion-memory" task (every minute, class A, _one_at_a_time). Superseded by Task 10 (nightly).
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

### - [x] Task 9: Recent-message count per character (S)
Prem 2026-11-09: the fixed 10 recent messages becomes a per-character setting. companions.history_messages int NOT NULL DEFAULT 10 CHECK (2–50) in migration 249; CompanionSettings and CompanionUpdate get the field; the engine reads that many recent messages.
- Acceptance:
  - [x] 1 and 51 are refused (422); a character without the column set reads 10.
  - [x] A character set to 25 sends limit 25 to recent_messages.
- Verify: test_companion_memory_store.py and test_companion_engine*.py pass; full suite passes.
- Files: backend/supabase/migrations/249_companion_memory.sql, backend/app/companion/models.py, backend/app/companion/engine.py, tests

### - [x] Task 10: Card sweep runs nightly at 2:00 AM IST (M)
Prem 2026-11-09 correction: "after every reply" was meant for Mem0; the card learns once a night. Cron "30 20 * * *" (02:00 IST). Every due pair, oldest first, at most 500 a night; chunks of 40 messages, at most 5 chunks per pair, watermark after each chunk. Failed nights are counted in companion_memory_state.failures (migration 249); the 3rd failed night moves the watermark on. The in-process backoff is removed.
- Acceptance:
  - [x] 90 new messages → 3 AI calls in one night, watermark at the 90th.
  - [x] An AI error keeps the watermark and sets failures to 1; the 3rd failed night moves it on and resets failures to 0.
  - [x] Queue test: companion-memory is at 02:00 IST, still 26 tasks.
- Verify: test_companion_memory_sweep.py and test_queue_tasks.py pass; full suite passes.
- Files: backend/app/companion/memory_sweep.py, backend/app/companion/store.py, backend/app/queue/tasks.py, backend/supabase/migrations/249_companion_memory.sql, tests

### Checkpoint B: Live (needs Prem's yes to apply 249)
- [ ] **Apply 249 before any push of this code.** Without it, creating a character fails (memory_engine and history_messages columns) and the nightly job errors.
- [ ] Re-check the latest migration number, then apply 249. list_tables shows the new tables with RLS on, and pg_policies has 0 rows for them.
- [ ] Set a Groq key on the UI test tenant. Via make dev-backend: chat with a Level 2 Jothidar, call run_memory_sweep() directly, then confirm the next reply uses the facts and tenant_token_usage gains companion_memory rows.

## Phase 3: Mem0

### - [x] Task 7: Mem0 spike (S, time-boxed to 2 h, scratch venv, no repo change)
Answer: can Mem0 2.2.1 use our Jina embeddings through a wrapper; can its pgvector tables be pre-created with RLS on; does Groq extraction work without JSON mode issues; what does one add() cost in calls and time.
- Acceptance: a short written result in this file; a go / no-go for Task 8.
- Depends on: none

**Result (2026-11-09): NO-GO for Task 8 for now; the card stays the only engine.** mem0ai 2.2.1 in a scratch venv, no keys, stubs; Postgres 16 + pgvector locally for the table check.
- Jina embedder: works, via a subclass of EmbeddingBase assigned after construction (config rejects a "jina" provider). Must be sync (Mem0 runs it in a thread). Our dimension is 512, not 1024.
- pgvector tables: can be pre-created with RLS on; Mem0 skips its DDL if they exist. No tenant column, so the tenant goes into user_id. Not proven against Supabase's role (local test used a superuser).
- LLM: JSON mode (response_format json_object), not tools. Bad JSON → 0 memories, no error. Sarvam path can't send reasoning_effort=None (our known null-content fix), so it would silently save nothing.
- Cost per add(): 1 LLM call + 2–3 Jina calls + 2 vector calls. search(): 0 LLM + 1 Jina.
- Blockers: **add() in 2.2.1 is ADD-only** (every result event is "ADD"; dedupe is exact-text only). "Quit Infosys, joined TCS" is stored next to "works at Infosys". That breaks the spec's core rule (close a fact, never pile up contradictions) and the "forget that" path. Also: forget-me leaves fact text and raw messages in Mem0's SQLite history (must be purged by hand), +200 MB of dependencies (qdrant-client, grpcio, numpy), tested on Python 3.11 only (Render runs 3.13).
- Revisit if a later Mem0 brings back update/delete in add(), or if we need semantic search over hundreds of facts per person (the card caps at 60). Full notes were in the session scratchpad (mem0-spike/RESULT.md), not kept in the repo.

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

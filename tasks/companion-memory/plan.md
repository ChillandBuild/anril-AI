# Implementation Plan: companion-memory

Spec: [docs/superpowers/specs/2026-11-09-companion-memory-design.md](../../docs/superpowers/specs/2026-11-09-companion-memory-design.md) (approved 2026-11-09 with the §9 defaults).
Tasks: [todo.md](todo.md). Kept apart from tasks/companion-core/ and from tasks/plan.md (the unfinished Sand glass login plan).

## Overview

Level 2 memory: a character remembers the person, not just the last 10 messages.
- **Card engine first** (ours, no new dependency): one row per fact, 5 sections, dated corrections.
- **A nightly sweep at 2:00 AM IST** turns the day's new messages into facts (Task 10, Prem's correction 2026-11-09); during the day the recent messages (history_messages, default 10, Task 9) cover today. Replies don't get slower.
- **Sharing between characters** is a per-business setting (default: each character keeps its own).
- **Seeing and forgetting:** the end user can see facts and forget one; the owner sees them in privacy mode A only.
- **Mem0 last,** after a time-boxed spike and Prem's yes on the new dependency.

Done means the spec §1 worked example passes as a test, and a Level 2 character on the UI test tenant remembers Karthik's interview two weeks of messages later.

## Architecture decisions (taken at plan time)

1. **Sweep, not a job per reply.** All 27 existing jobs are periodic and nothing in app/ enqueues on demand, so a periodic "companion-memory" task (class A, _one_at_a_time) follows the house pattern. Three quick replies become one AI call.
2. **record_turn stays a no-op.** core's engine awaits it inline before returning the reply (engine.py:255), so any real work there would slow every reply.
3. **tenant_id joins the MemoryProvider methods.** The protocol today has no tenant_id, and every query must filter it.
4. **Facts are rows, not one text blob.** This makes forget-one, list, the 60-fact cap and business scope plain queries.
5. **Scope is applied on read, never on write.** Each fact keeps the companion_id that learned it, so switching the setting moves no data.
6. **Mem0 is imported lazily** inside memory_mem0.py, with MEM0_TELEMETRY=False set first. The app and the tests run without mem0ai installed until T8.
7. **Migration 249 stays a file until Checkpoint B.** All tests use FakeSupabase.

## Dependency graph

```
T1 migration 249 + store + memory_engine field
 │
 ├─► T2 provider wiring (tenant_id, provider_for(level, engine))
 │     │
 │     ├─► T3 MemoryCard (prompt, ops, apply, render)
 │     │     │
 │     │     └─► T4 sweep task ──► T6 forget-me both engines + engine switch
 │     │
 │     └─► T5 scope + visibility routes + prompt label
 │
 └─► T7 Mem0 spike (time-boxed, read-only) ──► T8 Mem0Engine (needs Prem's yes on mem0ai)
```

- T3 and T5 can run in parallel after T2; they touch different files except store.py, so T5's store functions land in a separate section of the file.
- T7 runs in a scratch venv and touches no repo file, so it can run any time.

## Worked example: what works after each phase

```
After Phase 1 (T1–T4):
  test: Karthik "Job poiduchu… paiyan 10th exam March… Zoho interview 20th" → reply
  run_memory_sweep() → facts: life lost job · people son 10th · threads exam, interview
  next reply's ABOUT THIS USER → "Open threads: Zoho interview (20 Nov 2026) · son's 10th exam (Mar 2027) …"
  Level 1 character → sweep skips it, zero AI calls

After Phase 2 (T5–T6):
  PUT /api/v1/companions/memory-settings {"memory_scope":"business"}
    → Vastu Guru's context now shows Jothidar's facts, own facts first
  GET /api/v1/companions/{jothidar}/people/astro-u-8812/memory → 4 facts, learned_by "Jothidar AI"
  same on a privacy-B character → 403
  forget-me → 0 facts, 0 state rows

After Phase 3 (T7–T8):
  Jothidar with memory_engine "mem0" on a Groq tenant → same example passes with Mem0
  Sarvam tenant with memory_engine "mem0" → falls back to card, warning logged
```

## Who builds what

The planner is Opus. Migrations and auth-adjacent routes stay with the planner.

| Task | Builder | Why |
|---|---|---|
| T1 migration | planner | migrations are never delegated |
| T1 store + model field | Sonnet worker | logic from an exact spec |
| T2 provider wiring | planner | changes core files that just passed review; small |
| T3 MemoryCard | Sonnet worker | logic; the planner reviews the extraction prompt text |
| T4 sweep + queue task | Sonnet worker; the planner reviews the queue registration | shared worker |
| T5 routes + prompt label | planner | tenant filtering and privacy A/B are auth-adjacent |
| T6 forget + engine switch | Sonnet worker | |
| T7 Mem0 spike | Sonnet worker in a scratch venv | read-only research |
| T8 Mem0Engine | Sonnet worker, after Prem's yes on mem0ai | new dependency |
| running tests | Haiku worker | |

The planner runs code-review-and-quality on every worker diff before you see it.

## Coordination with the Companion (fork) session

That session is in Checkpoint C (/review and /code-simplify) on the same companion files (memory.py, engine.py, store.py). **T2 starts only after its Checkpoint C commits land**, so two sessions never edit those files at once. T1's migration file, T3 (new file) and T7 (scratch venv) can start earlier.

## Commit plan

One commit per task on main, after its tests pass. Nothing is pushed. git fetch before each commit and check HEAD..origin/main for teammate commits on the same files. On 2026-11-09 there were none, and main was 9 commits ahead of origin.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| The model returns broken JSON (no JSON mode in _llm_chat) | Med | A tolerant parser takes the first JSON array; anything else means no change and a retry next tick; 3 failures move the watermark on. Eval measures the rate. |
| The model saves wrong facts (guesses, or the character's words as the user's) | Med | Prompt rules + server-side op checks; the user can see and forget facts; eval scores fact accuracy. |
| Sensitive data saved (IDs, account numbers, OTPs) | High | Never-save list in the prompt plus a regex filter on op text (digit runs of 6+, OTP/password/aadhaar/pan words) before writing. |
| A memory AI call after every reply doubles the AI calls | Low | Sweep merges replies; Groq-sized cost; metered as companion_memory. A cheap "is there anything worth saving?" gate (an idea from a Supermemory post the fork session read) can come later if cost bites. |
| Worker off in make dev-backend, so the sweep never runs locally | Low | The smoke test calls run_memory_sweep() directly. Prod's worker could also process laptop-made chats, but that's the same live DB and the same tenant. |
| Business scope surprises users | Med | Default is per character; widget disclosure is a hard requirement in companion-chat-api. |
| Mem0 can't use our Jina embeddings, or its pgvector tables can't be pre-created with RLS | Med | T7 spike answers both before T8; if Mem0 fails the spike, the card stays the only engine and the eval compares the card against Level 1. |
| UI test tenant still has no AI key | Med | Blocks Checkpoint B's live part, as it did for core. Set a Groq key on that tenant first. |
| Migration number 249 taken before we apply | Low | Re-check the latest number right before Checkpoint B. |

## Open questions

None blocking. The spec §9 defaults are approved.

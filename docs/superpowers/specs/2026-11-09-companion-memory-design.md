# Spec: companion-memory

Module of [Aira Companion](2026-11-08-aira-companion-capability-map.md). Intent: [docs/intent/aira-companion.md](../../intent/aira-companion.md) §4. Builds on [companion-core](2026-11-08-companion-core-design.md).

- **Status:** APPROVED by Prem 2026-11-09, with the §9 defaults (card engine default; card first, Mem0 after a spike and a yes on the dependency; closed facts 90 days; learned_by shown).
- **Depends on:** companion-core (built: migration 248, engine, Level 1 history).
- **Used by:** companion-chat-api (exposes "what do you remember" and "forget that"), companion-dashboard (shows facts in privacy mode A), companion-eval (compares the two engines).

**Prem's decisions (2026-11-09):**
1. Two engines behind the memory slot: Mem0 and our own memory card. Supermemory is out. Eval picks per client language.
2. Sharing facts between characters: the **business chooses** (default: each character keeps its own).
3. Facts are saved **after every reply**.
4. The end user can see their facts and forget one; the business sees them only in privacy mode A; Anril staff never.

## 1. Objective

Level 2 memory: the character remembers **the person**, not just the last 10 messages.

**Who it's for:** businesses like Astrotamil whose users come back over weeks. Remembering family, worries and unfinished events is what makes Karthik return, and return visits are what Astrotamil earns from.

### Worked example: Karthik and Jothidar AI (memory_level 2, engine "card")

```
Day 1, 10:02  Karthik: "Job poiduchu. En paiyan ku 10th exam March la. Zoho la interview 20th."
       10:02  Jothidar replies (no change to the reply path)
       10:03  memory sweep (runs every minute) sees 2 new messages for (Jothidar, Karthik)
              → one AI call → saves:
                  life     lost job                       since Oct 2026
                  people   son, in 10th standard
                  threads  son's 10th exam                 Mar 2027
                  threads  Zoho interview                  20 Nov 2026
Day 15        (30 other messages since; Day 1 is no longer in the last 10)
       09:40  Karthik: "Hi"
              context_for → ABOUT THIS USER gets the 4 facts above
              Jothidar: "Vanakkam Karthik! Zoho interview eppadi pochu? Paiyan exam ku ready-aa?"
       09:41  Karthik: "Interview pass! Next week join pannren."
       09:42  sweep → closes "lost job", adds "works at Zoho, from Dec 2026",
              closes thread "Zoho interview"
Day 16        Karthik: "Andha job vishayam marandhudunga" (forget that job thing)
              sweep → deletes the 2 job facts. The reply already said "Sari, marandhuttaen."
```

Level 1 users (banks, delivery) see no change. Level 3 stays rejected.

**Out of scope:** Level 3 (time graph), the public "what do you remember" endpoint and widget screen (companion-chat-api), the dashboard screen (companion-dashboard), the eval test set and scoring (companion-eval), sharing memory across businesses (never).

## 2. Tech stack

- Same as core: FastAPI, Supabase service-role client with tenant_id on every query, asyncio.to_thread, Procrastinate.
- **Card engine:** no new dependency. Uses _llm_chat with the tenant's chosen model.
- **Mem0 engine:** new dependency mem0ai==2.2.1 (Apache-2.0, released 2026-09-25). **Ask first** before adding it. It needs:
  - a direct Postgres connection (the pgvector provider, psycopg3, already installed);
  - an embedder (spike: wrap our existing Jina embeddings, 512 dims, tenant's jina_api_key);
  - an LLM it supports: groq, openai or gemini. **Sarvam isn't supported**, and gemini needs google-genai (another new dependency).
  - MEM0_TELEMETRY=False set before import (PostHog telemetry is on by default).
- Checked in code this session: _llm_chat has no JSON mode (ai_reply.py:65), so the card engine parses plain JSON from the reply text. All 27 existing jobs are periodic (queue/tasks.py); there are no on-demand job calls anywhere in app/.

## 3. Design

### 3.1 Tables: migration 249_companion_memory.sql

House style as 248: header comment, SET LOCAL lock_timeout = '5s', IF NOT EXISTS, RLS on, no policies, tenant_id on every row.

| Change | Columns | Why |
|---|---|---|
| companions + 1 column | memory_engine text NOT NULL DEFAULT 'card' CHECK (card, mem0) | Which Level 2 engine this character uses. Ignored at Level 1. |
| companion_tenant_settings (new) | tenant_id PK → tenants, memory_scope text NOT NULL DEFAULT 'character' CHECK (character, business), updated_at | Prem's "business chooses" |
| companion_memory_facts (new, card engine) | id, tenant_id, companion_id (the character that learned it), end_user_id, section CHECK (profile, people, life, preferences, threads), text ≤ 300, valid_from date NULL, valid_to date NULL, status CHECK (active, closed), created_at, updated_at. Index (tenant_id, end_user_id, status). | One row per fact, so one fact can be listed or forgotten on its own |
| companion_memory_state (new) | PK (companion_id, end_user_id), tenant_id, last_message_at timestamptz, updated_at | Watermark: the newest message already turned into memory |
| Mem0 tables | Pre-created with RLS on, if the spike shows Mem0's pgvector schema (a collection and a _entities collection) can be created by us. Otherwise Mem0 creates them, and a follow-up migration enables RLS. | Mem0 stores its own vectors |

**Caps:** 60 active facts per (character, person). When an add would pass 60, the oldest closed facts are deleted first, then the oldest active preferences.

### 3.2 "After every reply": a sweep every minute

```
@queue_app.periodic(cron="* * * * *", periodic_id="companion-memory")
@queue_app.task(name="companion-memory", queue="companion", **_one_at_a_time("companion-memory"))
```
- **Retry class A:** a sweep; the next tick redoes anything missed.
- **Each tick:**
  1. find up to 20 (character, person) pairs with memory_level 2 whose newest message is after their watermark;
  2. run each pair's engine on the messages since the watermark (at most 20 messages);
  3. on success, move the watermark to the newest message processed.
- **Why a sweep, not one job per reply:** every existing job is periodic, so this follows the house pattern. Three quick replies merge into one AI call. And there's no new on-demand job call that a laptop could enqueue into the shared queue.
- **Effect:** facts are ready about a minute after each reply. The engine's record_turn stays a no-op, so the reply path gets no slower.
- **Failure:** an LLM error or unparseable answer leaves the watermark in place, so the next tick retries. After 3 failures for the same pair (counted in logs only), the watermark moves on so one bad chat can't block the sweep.
- **Cost:** at most one AI call per reply (purpose "companion_memory", metered in tenant_token_usage), usually fewer. Groq-sized for a pilot.
- **The worker is the existing one;** it already serves every queue (main.py:180). The queue name "companion" keeps it separate in the procrastinate tables. A separate worker service is for later (capability map assumption 4).

### 3.3 Card engine: memory.py (MemoryCard)

**One AI call per pair per tick.**
- **Input:** the character's language, the active facts numbered f1…fN, and the new messages.
- **Output:** a JSON list of operations:

```json
[{"op":"add","section":"threads","text":"Zoho interview","valid_from":"2026-11-20"},
 {"op":"close","ref":"f3","valid_to":"2026-11"},
 {"op":"update","ref":"f2","text":"son, in 10th standard, studies at PSBB"},
 {"op":"delete","ref":"f5"}]
```

**What the extraction prompt says:**
- Save only facts the user said about themselves or their people. Never guess, and never save what the character said as a fact about the user.
- Write facts in the character's language setting; keep names as the user wrote them.
- **Never save:** government ID numbers, bank or card numbers, passwords, OTPs, phone numbers, exact home addresses.
- **Facts that change:** close the old fact with a date and add the new one. Don't overwrite. ("lost job, since Oct 2026" → closed; "works at Zoho, from Dec 2026" → added.)
- **"Forget that" or "don't remember X":** delete the matching facts.
- Finished threads (the interview happened) are closed.

**Server-side checks:**
- Every ref must exist in the list we sent.
- Section must be valid, text at most 300 characters, and at most 10 operations per call.
- Anything invalid is dropped and logged as a count only.
- If the JSON doesn't parse, nothing changes and the next tick retries.

**context_for:**
1. One query loads the active facts, plus closed facts from the last 90 days.
2. They're sorted in this order: open threads, profile, people, life (newest first), preferences.
3. They're rendered as short lines, capped at 2,000 characters (about 500 tokens).

```
Open threads: Zoho interview (20 Nov 2026) · son's 10th exam (Mar 2027)
People: son, in 10th standard
Life: lost job (since Oct 2026)
```

### 3.4 Mem0 engine: memory.py (Mem0Engine)

- **One AsyncMemory per tenant,** built from that tenant's model choice and keys and cached in-process. Config:
  - llm: groq, openai or gemini, matching _resolve_provider;
  - embedder: the Jina wrapper from the spike;
  - vector_store: pgvector on the direct DB URL;
  - custom_instructions: the same rules as §3.3;
  - history_db_path: a temp dir.
- **record (in the sweep):** `add(new_messages, user_id=end_user_id, agent_id=companion_id, metadata={"tenant_id": …})`. This is one LLM call plus embedding calls.
- **context_for:** `search(message, filters={"user_id": end_user_id, "agent_id": companion_id}, limit=10)`. In business scope the agent_id filter is dropped. The result is rendered as lines with the same 2,000-character cap.
- **"Forget that":** Mem0's extraction is additive. So the sweep first asks it (via custom_instructions) to flag forget requests. If the spike shows that's unreliable, the sweep runs the card engine's forget step instead: search for the phrase, then delete hits with similarity ≥ 0.8.
- **Falls back to the card engine,** with a warning log, when the tenant's model is Sarvam, there's no Jina key, or the mem0 import fails. A character never loses memory because Mem0 can't run.
- Mem0 ids are kept as strings, so list and forget-one work the same as for the card (§3.6).

### 3.5 Sharing between characters (business chooses)

- **memory_scope = character (default):** context_for reads only facts this character learned. Vastu Guru knows nothing Karthik told Jothidar.
- **memory_scope = business:** context_for reads the person's facts from every character at this business. This character's own facts come first, and the cap is 2,000 characters.
- **Writes don't change:** every fact keeps the companion_id of the character that learned it. Switching the setting moves no data, and switching back hides the shared facts again.
- **Example in business scope:**
  - Karthik gives his birth details to Jothidar.
  - A week later he asks Vastu Guru about a new house.
  - Vastu Guru sees "born 12 Mar 1998, Madurai · son, 10th standard" and doesn't ask again.
- **Telling the user:** in business scope, the widget must say "Characters at Astrotamil share what you tell them" (companion-chat-api owns the wording and placement).

### 3.6 Seeing and forgetting facts

**Core functions** (companion-chat-api exposes them to end users with signed user ids):
```python
async def list_memory(tenant_id, companion_id, external_user_id) -> list[MemoryFact]
async def forget_fact(tenant_id, companion_id, external_user_id, fact_id: str) -> bool
class MemoryFact(BaseModel): id; section; text; valid_from; valid_to; status; learned_by (character name)
```
- list_memory returns what this character would see under the current scope.
- **In chat:**
  - "What do you remember about me?" works because the ABOUT THIS USER label changes to say the character may tell the user these facts in its own words. This is the one change to prompt.py.
  - "Forget that" is handled by the sweep (§3.3), and platform rule 6 already makes the character agree.

**Owner routes** (dashboard login, settings.manage, tenant-filtered; another tenant's id → 404):
- GET /api/v1/companions/memory-settings → {memory_scope}
- PUT /api/v1/companions/memory-settings {memory_scope}
  - Both are declared before /{id} so the path isn't read as a character id.
- GET /api/v1/companions/{id}/people/{external_user_id}/memory
  - **403 if the character is in privacy mode B.**
- DELETE /api/v1/companions/{id}/people/{external_user_id}/memory/{fact_id}
  - Also 403 in mode B. The business can still delete the whole person through forget-me.

**Anril staff:** no route, and nothing in the operator console. Logs carry ids, counts and timings, never fact text.

### 3.7 Forget me (extends core)

- engine.forget_person calls forget on **both** engines whatever the current setting, because a past setting may have left data in the other one.
  - **Card engine:** delete the person's facts and memory state rows.
  - **Mem0 engine:** delete_all(user_id=end_user_id), only if Mem0 was ever used by this tenant. Skipped when it can't be loaded, with a warning.
- **Switching a character's engine** resets its watermarks, so the new engine relearns from the last 20 messages. Old facts in the other engine stay until forget-me or a manual delete.

### 3.8 Changes to companion-core

| File | Change |
|---|---|
| memory.py | MemoryProvider methods gain tenant_id as the first parameter (every query must filter it). provider_for(level, engine) returns Level1History, MemoryCard or Mem0Engine. |
| engine.py | Pass tenant_id and the engine name. forget_person calls both engines (§3.7). |
| prompt.py | The ABOUT THIS USER label wording (§3.6). |
| models.py, routes/companions.py | memory_engine field on characters; the new routes. |
| queue/tasks.py | The companion-memory task and its RETRY_CLASS entry "A". |

### 3.9 Package layout

```
backend/app/companion/memory.py        protocol, Level1History, provider_for
backend/app/companion/memory_card.py   MemoryCard: prompt, op parsing, apply, render
backend/app/companion/memory_mem0.py   Mem0Engine + Jina embedder wrapper (lazy import of mem0)
backend/app/companion/memory_sweep.py  run_memory_sweep(): find pairs, call engine, move watermark
backend/app/companion/store.py         facts, state and tenant-settings queries
```

## 4. Commands

```bash
cd backend && python -m pytest tests/test_companion_*.py -q
```
```bash
bash scripts/verify.sh
```
- **Migration 249:** applied with the Supabase MCP, only after Prem says yes.
- **Smoke test:** make dev-backend, then test-chat as the UI test tenant. The worker is off in safe mode, so the smoke test calls run_memory_sweep() directly once. **Blocker carried over from core:** the UI test tenant has no AI model or key yet.

## 5. Code style

Same as core §5: all table access through store.py, type hints on every public function, and logger = logging.getLogger(__name__). Fact text, message text and Mem0 payloads are **never** logged.

## 6. Testing strategy

FakeSupabase plus a fake _llm_chat and a fake AsyncMemory. No network in tests.

| File | Covers |
|---|---|
| test_companion_memory_card.py | Op parsing and validation (bad ref, bad section, >300 chars, >10 ops, broken JSON → no change), close vs update vs delete, the 60-fact cap, render order and the 2,000-character cap, never-save list in the prompt |
| test_companion_memory_sweep.py | Picks only Level 2 pairs past the watermark; merges 3 replies into one call; LLM error keeps the watermark; 3 failures move it on; at most 20 pairs per tick |
| test_companion_memory_scope.py | Character scope hides other characters' facts; business scope shows them with own facts first; switching scope moves no data |
| test_companion_memory_mem0.py | Config built from the tenant's provider; Sarvam or no Jina key → card fallback; telemetry env set before import; forget → delete_all |
| test_companion_memory_routes.py | Privacy B → 403; other tenant → 404; scope settings get and put; forget-one |
| test_companion_forget.py (extend) | Forget-me wipes facts, state and Mem0 for every engine |

caplog checks in the sweep and route tests: no fact or message text in any log line.

## 7. Boundaries

- **Always:** tenant_id on every query; validate every AI operation before writing; card text capped; tests before each commit.
- **Ask first:**
  - applying migration 249 to the live DB;
  - adding mem0ai (and google-genai if Gemini is wanted);
  - any change to embeddings.py, ai_reply.py or knowledge_service.py;
  - a separate worker service.
- **Never:**
  - logging fact or message text;
  - a staff or operator-console view of facts;
  - sharing facts across businesses;
  - saving the never-save list (§3.3);
  - push, deploy or migrate without Prem's yes.

## 8. Success criteria

1. The §1 worked example passes as a test with a scripted fake LLM: 4 facts saved; the Day 15 context contains the interview and exam threads; the job change closes one fact and adds one; "forget that" deletes the job facts.
2. A Level 1 character makes zero memory AI calls, and its reply path is unchanged (existing core tests pass).
3. Character scope: Vastu Guru's context has none of Jothidar's facts. Business scope: it has them.
4. Privacy B → 403 on the owner memory routes, and no route exposes facts to Anril staff.
5. Forget-me leaves zero facts, zero state rows and zero Mem0 memories for the person.
6. Mem0 runs for a Groq tenant on the live smoke test, or the spike result is written down with the reason it was skipped. Sarvam tenants fall back to the card.
7. Live smoke on the UI test tenant, once it has an AI key: two chats in Tanglish and one in English give sensible facts in the character's language. Reading time: context_for under 100 ms for the card and under 500 ms for Mem0.

## 9. Open questions (spec defaults in brackets)

1. **Default engine before eval.** The capability map said Mem0. The spec default is **card**: it works with every model the tenant can pick (Sarvam too), needs no embedding key and adds no dependency. [card]
2. **Add mem0ai now, or build the card first and add Mem0 as a later task in this module?** [card first; Mem0 after a 1-hour spike, with your yes on the dependency]
3. **How long closed facts stay in the prompt.** [90 days; kept in the table until the cap or forget-me]
4. **Should the business see which character learned a fact?** [yes, learned_by in list_memory]

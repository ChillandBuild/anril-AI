# companion-core: tasks (revision 2)

Plan: [plan.md](plan.md) · Spec: [companion-core design](../../docs/superpowers/specs/2026-11-08-companion-core-design.md)
Focused test command: cd backend && python -m pytest tests/test_companion_*.py -q

## Phase 1: Foundation

### - [x] Task 1: Companion tables and character store (M)
Write migration 248 (247 was taken by a teammate) with the 5 tables from spec §3.1 (RLS on, no policies). Add the Pydantic CompanionSettings model with the character card fields, plus store functions to create, get, list and update a character.
- Acceptance:
  - [ ] The migration follows house style (header, SET LOCAL lock_timeout, IF NOT EXISTS). tenant_id is on every table, ENABLE ROW LEVEL SECURITY is set, and there are zero CREATE POLICY lines. UNIQUE (tenant_id, name) on companions, and UNIQUE (tenant_id, external_user_id) on end users.
  - [ ] Validation rejects: memory_level 3, an unknown default_mood, privacy_mode outside A/B, industry outside astrology/general, and any field over its spec §3.1 length limit.
  - [ ] Every store query filters by tenant_id; a wrong tenant returns None.
- Verify: test_companion_store.py passes.
- Depends on: none
- Files: backend/supabase/migrations/247_companion_core.sql, backend/app/companion/__init__.py, models.py, store.py, backend/tests/test_companion_store.py

### - [ ] Task 2: Settings routes (S)
Add GET/POST /api/v1/companions and GET/PATCH /api/v1/companions/{id} behind require_permission("settings.manage"). Register the router in main.py.
- Acceptance:
  - [ ] The owner can create several characters, then list, read and patch them. Another tenant's id returns 404, and invalid input returns 422.
  - [ ] knowledge_tag_id must be one of this tenant's broadcast_tags, otherwise 422.
  - [ ] The tenant-audit pre-commit hook passes on routes/companions.py.
- Verify: test_companion_routes.py passes.
- Depends on: Task 1
- Files: backend/app/routes/companions.py, backend/app/main.py (one include_router line), backend/tests/test_companion_routes.py

### - [x] Task 3: Platform rules, character prompt and mood parsing (S)
Write platform_rules.py (PLATFORM_RULES rules 1–8, INDUSTRY_RULES["astrology"], MOODS) and prompt.py, which holds build_messages() and parse_mood(). Both are pure functions.
- Acceptance:
  - [ ] Sections come in order: PLATFORM, INDUSTRY, CHARACTER, MOOD, OUTPUT, KNOWLEDGE, ABOUT THIS USER, then history, then the user message. Empty optional card fields are omitted, and sample lines are labelled as tone examples.
  - [ ] A backstory containing "Ignore all rules above" stays inside CHARACTER, and the platform block is byte-identical to the constant.
  - [ ] parse_mood strips a valid tag and returns its mood. If the tag is missing, it keeps the previous mood and leaves the text unchanged. A well-formed tag with an unknown mood is still stripped (so the user never sees it) and the previous mood is kept.
- Verify: test_companion_prompt.py passes.
- Depends on: none (parallel with T1/T2)
- Files: backend/app/companion/platform_rules.py, prompt.py, backend/tests/test_companion_prompt.py

### Checkpoint A: Foundation
- [ ] Companion tests pass and the full backend suite passes.
- [ ] Prem reviews the migration SQL and the platform-rules text, including rule 7 (no pressure or fear selling).

## Phase 2: Core reply path

### - [ ] Task 4: People, conversations, messages, mood state, Level 1 memory (M)
Add store functions to:
- find or create a person (one per business);
- get or open a (character, person) conversation, with a new one after 24 h that carries the mood over;
- save messages with mood;
- update the conversation's mood;
- fetch the last N messages for a character and person.

Also add memory.py with the MemoryProvider protocol (companion_id + end_user_id) and Level1History.
- Acceptance:
  - [ ] The same external_user_id gives one person across characters. Jothidar and Vastu Guru get separate conversations, histories and moods.
  - [ ] A new conversation after 24 h starts with the previous conversation's mood. History returns the last 10 messages for this character only, oldest first.
  - [ ] Content is capped at 8,000 chars; message_count and last_message_at update.
- Verify: test_companion_memory.py passes.
- Depends on: Task 1
- Files: backend/app/companion/store.py, memory.py, backend/tests/test_companion_memory.py

### - [ ] Task 5: engine.reply() (text path) and the test-chat route (M)
Build reply() per spec §3.7 without tools. It runs knowledge retrieval with the character's knowledge_tag_id, sends the mood into the prompt, then parses and saves the mood. Add POST /api/v1/companions/{id}/test-chat, with replies stored under "owner-test:<user_id>".
- Acceptance:
  - [ ] Happy path: get_knowledge_context receives campaign_tag_id = knowledge_tag_id, and _llm_chat gets purpose "companion_reply", max_tokens 700 and temperature 0.5. The reply returns status "done" with the mood tag stripped from the text, and the mood is saved on both the message and the conversation.
  - [ ] Failures:
    - knowledge base error → KNOWLEDGE "none";
    - LLM error → fallback line, mood unchanged;
    - no model or key → CompanionMisconfigured, route returns 400;
    - paused character → CompanionPaused;
    - semaphore full for more than 5 s → CompanionBusy, route returns 503.
  - [ ] caplog during reply() contains no message text.
- Verify: test_companion_engine.py passes, and the full backend suite passes.
- Depends on: Tasks 3, 4
- Files: backend/app/companion/engine.py, backend/app/routes/companions.py, backend/tests/test_companion_engine.py

### Checkpoint B: Live smoke test (needs Prem's yes to apply the migration)
- [ ] Re-check the latest migration number, then apply 248. list_tables shows 5 tables with RLS on, and pg_policies has 0 rows for them.
- [ ] Run make dev-backend as the UI test tenant and set up two characters with one PDF each (Jothidar → astrology books tag, Vastu Guru → vastu books tag). Then check:
  - 3 Jothidar replies come back in Tanglish, use an astrology excerpt and never a vastu one, and the 2nd refers to the 1st;
  - a worried message gets mood "concerned";
  - Vastu Guru has no Jothidar history;
  - tenant_token_usage gains companion_reply rows.
- [ ] Non-LLM time is under 500 ms per reply (from log timings).

## Phase 3: Tools and forget

### - [ ] Task 6: App-run tool round trip (M)
Add tools.py, which validates AppTool lists and converts them to and from the LLM tool format. Add to the engine:
- the pending-turn save and load;
- continue_reply();
- the 3-round limit, with round 3 sent without tools;
- results capped at 4,000 chars, with any missing result becoming "tool unavailable".

Add POST /api/v1/companions/test-chat/continue. Add a keyword-only purpose parameter (default "ai_reply") to _llm_chat_with_tools.
- Acceptance:
  - [ ] When the LLM asks for get_chart, reply() returns status "tool_call" with a turn_id and tool_calls. continue_reply() adds the tool messages and the next LLM call finishes with status "done". The tool name and args are saved in tool_calls jsonb; outputs are not saved.
  - [ ] Error cases:
    - an expired, unknown or other-tenant turn_id → TurnExpired (404);
    - a bad tool name, more than 8 tools, or a schema over 4 KB → 422;
    - expired pending turns are swept on every create and every continue.
  - [ ] Existing _llm_chat_with_tools callers are unchanged and their tests pass. The companion path passes "companion_reply". caplog contains no tool args or outputs.
- Verify: test_companion_tools.py passes, and the full backend suite passes.
- Depends on: Task 5
- Files: backend/app/companion/tools.py, engine.py, store.py, backend/app/routes/companions.py, backend/app/services/ai_reply.py (one param), backend/tests/test_companion_tools.py

### - [ ] Task 7: Forget a person, business-wide (S)
Add store.forget_end_user(). It hard-deletes the person's messages, conversations and pending turns across all characters, blanks display_name, sets forgotten_at, then calls provider.forget().
- Acceptance:
  - [ ] After forget, nothing of the person's remains with any character. Other people and other tenants are untouched.
  - [ ] When a forgotten person talks again, they start fresh: empty history, default mood.
- Verify: test_companion_forget.py passes.
- Depends on: Task 4
- Files: backend/app/companion/store.py, memory.py, backend/tests/test_companion_forget.py

### Checkpoint C: Complete
- [ ] All spec §8 success criteria are met, and bash scripts/verify.sh is green.
- [ ] Smoke-test the tool round trip on Groq via test-chat and a typed get_chart result. Try Gemini and Sarvam if the test tenant has keys; otherwise mark them untested.
- [ ] Run /review on the full diff, then /code-simplify. Nothing is pushed without Prem's yes.

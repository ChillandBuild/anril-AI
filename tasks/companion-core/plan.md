# Implementation Plan: companion-core

Spec: [docs/superpowers/specs/2026-11-08-companion-core-design.md](../../docs/superpowers/specs/2026-11-08-companion-core-design.md) (approved 2026-11-08).
Tasks: [todo.md](todo.md). This folder is separate from tasks/plan.md, which still holds the unfinished Sand glass login plan.

## Overview

This plan builds the engine of Aira Companion:
- **Storage:** 5 new tables.
- **Characters:** several per business, each with a character card, its own books and a live mood toward each user.
- **Replies:** the 5-layer prompt builder, with Level 1 memory.
- **Tools:** app-run tools, where core pauses, the client's app runs its own tool, and core finishes the reply.
- **Forget me:** wipes a person's data.

Done means an owner can create "Jothidar AI" and "Vastu Guru" and chat with both through the test-chat routes, including a hand-typed tool result. The public widget comes in companion-chat-api.

Revision 2 (2026-11-08, with Prem's yes): app-run tools replace the server-side tool registry and the echo tool; character cards and live mood are added; several characters per client.

## Architecture decisions (taken at plan time)

1. **No change to the worker queues.** run_worker_async() has no queue filter (main.py:180), and core enqueues nothing. main.py only gains one include_router line.
2. **Tools run in the client's app, not ours.** The tool list arrives with each message. A paused reply lives in companion_pending_turns for at most 2 minutes. Our servers never call a client URL, so there's no SSRF risk and no stored secrets.
3. **One small change to ai_reply.py.** _llm_chat_with_tools gets a keyword-only purpose parameter (default "ai_reply"), because it's single-shot and currently meters every call as ai_reply.
4. **People are shared across characters; chats are not.** There's one companion_end_users row per person per business. Conversations, history and mood are per character. "Forget me" is business-wide.
5. **Books per character reuse campaign tag scoping.** knowledge_tag_id passes into get_knowledge_context(campaign_tag_id=…), so a character sees its tag's books plus untagged books. No change to knowledge_service.py.
6. **Mood comes from a leading [mood: X] tag** that's parsed and stripped. This works for every provider without JSON mode.
7. **Migration 247 stays a file until Checkpoint B.** All tests use FakeSupabase.
8. **Open questions** are settled with the spec's defaults (spec §9).

## Dependency graph

```
T1 tables + store (characters)            T3 platform rules + character prompt + mood parse (pure)
 │                                          │
 ├─► T2 settings routes                     │
 │                                          │
 └─► T4 store: people / convos / messages   │
       + mood state + Level 1 memory        │
        │                                   │
        ├──────────► T5 engine.reply() + test-chat ◄─┘
        │                 │
        └─► T7 forget     └─► T6 app-run tool round trip + continue route + purpose param
```

T3 needs nothing else, so it runs in parallel with T1 and T2.

## Worked example: what works after each phase

```
After Phase 1 (T1–T3):
  POST /api/v1/companions {"name":"Jothidar AI","industry":"astrology","language":"ta-en",
     "role":"Vedic astrologer","backstory":"Learned from his grandfather in Kumbakonam…",
     "goals":["Get birth details","Calm the user","Give a simple remedy"],
     "sample_lines":["Kavalaipadaathinga…"],"memory_level":1,"privacy_mode":"A"}
    → 201 {"id":"c-…","status":"draft","default_mood":"calm",…}
  Another tenant: GET /api/v1/companions/c-… → 404
  parse_mood("[mood: concerned] Kavalaipadaathinga…", "calm") → ("Kavalaipadaathinga…", "concerned")

After Phase 2 (T4–T5):
  test-chat Jothidar "Job poiduchu, romba kavalai" → {"status":"done","text":"…","mood":"concerned"}
  next message → prompt says "Your current mood with this user: concerned"
  test-chat Vastu Guru → no Jothidar history, its own mood

After Phase 3 (T6–T7):
  test-chat {message:"12 Mar 1998 6:40am Madurai", tools:[get_chart]}
    → {"status":"tool_call","turn_id":"…","tool_calls":[{"id":"call_1","name":"get_chart",…}]}
  test-chat/continue {turn_id, results:[{id:"call_1", output:{"lagna":"Simha"}}]}
    → {"status":"done","text":"…Simha lagnam…","mood":"encouraging"}
  forget → Karthik's chats with both characters gone
```

## Who builds what

The planner is Opus. Per the project rules, migrations and anything near auth stay with the planner.

| Task | Builder | Why |
|---|---|---|
| T1 migration | planner | migrations are never delegated |
| T1 store, T4, T5, T7 | Sonnet worker | logic from an exact spec |
| T2 routes | planner | tenant filtering is auth-adjacent |
| T3 platform rules + prompt | planner | the safety layer |
| T6 tool round trip + ai_reply.py edit | Sonnet worker; the planner reviews the pending-turn tenant checks and the ai_reply.py line | shared WhatsApp code; cross-request state |
| running tests | Haiku worker | |

The planner runs code-review-and-quality on every worker diff before you see it.

## Commit plan

There's one commit per task on main, after its tests pass. Nothing is pushed. Before the first commit, run git fetch and rebase. origin/main is 2 commits ahead (keerthi-sarav, meta ads), and none of the files this plan touches overlap with them.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Tool-call follow-up messages differ per provider (Gemini converts shapes) | Med | T6 tests the loop with the Groq/OpenAI shape. Gemini and Sarvam are smoke-tested at Checkpoint C. If one fails, tools are switched off for that provider, with a log line. |
| A model ignores the [mood: X] format | Low | parse_mood keeps the previous mood and the text is unchanged; companion-eval measures how often it happens. |
| Book tags show up in the broadcast tag list | Low | Accepted for v1; companion-dashboard can hide them. |
| Pending turns hold message content | Low | 2-minute expiry, swept on every create and continue, deleted by forget. |
| Migration number 247 taken by a teammate before we apply | Low | Re-check the latest migration number right before Checkpoint B and rename if needed. |
| Companion replies starve WhatsApp replies on the one shared service | Med | A semaphore, COMPANION_MAX_CONCURRENT=4 (T5). Real per-user limits come in chat-api. |
| KB full-text fallback adds 12,000 chars to every prompt when retrieval finds nothing | Low | Accepted for v1. kb-books revisits it. Prompt size is logged as a length only. |
| UI test tenant has no AI model or key set → misconfigured error at smoke time | Low | T5 returns a clear error. Set the key in Settings before Checkpoint B. |
| make dev-backend uses the live DB | Med | The smoke test only touches the new companion tables, owned by the UI test tenant. Nothing is sent outward (dry run). |

## Open questions

None blocking. Re-verify the Tele-MANAS number (14416) before the companion goes live to real users. That isn't needed for this module's checkpoint.

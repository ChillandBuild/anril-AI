# Capability Map: Aira Companion

Approved by Prem on 2026-11-08. Revised the same day (Prem's yes): app-run tools replace astro-chart; character cards with live mood; several characters per client. Intent: [docs/intent/aira-companion.md](../../intent/aira-companion.md).
This map is the index of module specs. Module ids are fixed; never rename them.

| Module id | Job | Depends on | Spec |
|---|---|---|---|
| companion-core | Characters per tenant (character card: role, backstory, speaking style, sample lines, goals, temperament; rules, memory level, privacy A/B, own books), live mood per user, new tables, the 5-layer reply builder, platform rules, the app-run tool round trip | existing knowledge base | [2026-11-08-companion-core-design.md](2026-11-08-companion-core-design.md) |
| kb-books | Book-size knowledge: raise the 50k-char cap, chunk long books, Tamil OCR | existing knowledge base | — |
| companion-chat-api | Public chat API + secret keys + signed user ids + web widget + mock Astrotamil page; exposes app-run tools (tool list in the request, tool-call round trip, widget tool handler, copy-paste server example) | companion-core | — |
| companion-memory | Level 2 memory behind the MemoryProvider slot, picked by companion-eval from two candidates (Mem0 and our nightly memory card; Supermemory ruled out 2026-11-09) (see "Level 2 memory candidates" below; our memory card is the default (approved 2026-11-09) until eval says otherwise), plus "forget me" | companion-core | [2026-11-09-companion-memory-design.md](2026-11-09-companion-memory-design.md) |
| ~~astro-chart~~ | **Dropped 2026-11-08.** Clients run their own tools inside their app (Astrotamil uses its existing chart engine). The id stays reserved; do not reuse it. | — | — |
| companion-dashboard | Dashboard Companion section (persona, books, memory level, privacy, plugin code) + super-admin usage view | core, chat-api, memory | — |
| companion-eval | Test set in each client's chosen language (pilot: Astrotamil in Tamil and Tanglish): verified charts (via Astrotamil's engine through app-run tools) + rated answers, and a demo video | memory, chat-api | — |

```
Build order:
  companion-core ──┬─► companion-chat-api ─┐
  kb-books ────────┤   companion-memory ───┴─► companion-dashboard ─► companion-eval
Week 1: core + kb-books   Week 2: chat-api, memory   Week 3: dashboard   Week 4: eval + demo
```

kb-books, companion-chat-api and companion-memory do not depend on each other, so they can be built in parallel.

## Approved assumptions

1. The client's **server** signs its user id with the secret key. The widget never handles logins and never holds the secret.
2. Replies use each tenant's existing model choice through _llm_chat in backend/app/services/ai_reply.py. No new AI provider.
3. Mem0 runs as a Python library inside the backend and stores in our Supabase (pgvector). Supabase support to verify in the companion-memory spec.
4. v1 runs companion jobs in the existing single Render service with their own queue and per-client rate limits. A separate service once a client pays.
5. All companion data lives in new companion tables, RLS on, no read path in the operator console.
6. JS chat widget served from the frontend (Vercel), plus a mock Astrotamil page that embeds it.
7. Specs live in docs/superpowers/specs/ (project convention), not a root SPEC.md.
8. App-run tools: the client's app sends its tool list with each chat request and runs the tool itself. Nothing about the tool is stored in our dashboard, and our servers never call the client's URL. Only the key question remains for the Astrotamil call: can their app call their chart engine from code?

## Level 2 memory candidates (added 2026-11-08)

Two candidates: Mem0 and our own nightly memory card. Supermemory is out (Prem, 2026-11-09): its engine is closed and it would store user memories on a third party's servers.

companion-memory builds Level 2 behind the existing MemoryProvider slot, so a candidate swaps in without touching the engine. companion-eval runs both candidates on the same test chats and compares facts recalled, cost per session and added latency. Test chats are in the languages clients actually pick (each character's language setting: English, Tamil script, Tanglish, Hindi, Hinglish and so on), starting with the pilot's Tamil and Tanglish. The winner can differ by language, so the choice is per client, with one setting.

| Candidate | How it works | Data lives | Cost shape |
|---|---|---|---|
| Mem0 | Apache 2.0 library, extracts facts after every reply | Our Supabase | One extra LLM call per chat |
| Memory card (ours) | A job that runs every minute turns new messages into dated facts (spec 2026-11-09 moved it from nightly to after every reply) | Our Supabase | One LLM call per batch of new messages |

**Nightly memory card.** The idea comes from Supermemory's outside-in reconstruction of the Instinct assistant (supermemory.ai/blog/reverse-engineering-instinct-memory, 2026-09-20). That post has no code or benchmark, so we take only the pattern.
- **Sections per person, per character:** people (family), facts (lagna, birth details), preferences, open threads (unfinished life events such as an exam or an interview), and dated corrections ("Infosys until Oct 2026, then lost job"), never silent overwrites.
- **Who writes it:** only the nightly job. The chatting AI reads the card and never writes to it, so a chat message cannot plant a memory.
- **Same-day gap:** covered by the last 10 messages that Level 1 already sends.
- **Size:** the card is injected into ABOUT THIS USER and capped at about 500 tokens (Instinct's is about 13,000).
- **Language:** the card is written in the character's language setting, which the client chooses. Facts are stored once and recalled whatever language the user types in, so "son", "paiyan" and "beta" all match the same family fact.
- **Search:** keyword-only search misses misspellings. Mixed-script languages (Tanglish, Hinglish) have many spelling variants (kavalai, kavalaai; pareshaan, pareshan), so recall needs fuzzy or meaning-based matching.
- **Forget me:** card rows are hard-deleted, with no version history kept.
- **Example:** two weeks later, Jothidar AI reads the open thread "Zoho interview pending" and asks "Zoho interview eppadi pochu?"

If the nightly card wins eval, it is the first piece of our own memory engine for Indian languages and code-mixed chat (intent §4, future option).

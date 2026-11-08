# Capability Map: Aira Companion

Approved by Prem on 2026-11-08. Revised the same day (Prem's yes): app-run tools replace astro-chart; character cards with live mood; several characters per client. Intent: [docs/intent/aira-companion.md](../../intent/aira-companion.md).
This map is the index of module specs. Module ids are fixed; never rename them.

| Module id | Job | Depends on | Spec |
|---|---|---|---|
| companion-core | Characters per tenant (character card: role, backstory, speaking style, sample lines, goals, temperament; rules, memory level, privacy A/B, own books), live mood per user, new tables, the 5-layer reply builder, platform rules, the app-run tool round trip | existing knowledge base | [2026-11-08-companion-core-design.md](2026-11-08-companion-core-design.md) |
| kb-books | Book-size knowledge: raise the 50k-char cap, chunk long books, Tamil OCR | existing knowledge base | — |
| companion-chat-api | Public chat API + secret keys + signed user ids + web widget + mock Astrotamil page; exposes app-run tools (tool list in the request, tool-call round trip, widget tool handler, copy-paste server example) | companion-core | — |
| companion-memory | Mem0 self-hosted, Level 1/2, "forget me" | companion-core | — |
| ~~astro-chart~~ | **Dropped 2026-11-08.** Clients run their own tools inside their app (Astrotamil uses its existing chart engine). The id stays reserved; do not reuse it. | — | — |
| companion-dashboard | Dashboard Companion section (persona, books, memory level, privacy, plugin code) + super-admin usage view | core, chat-api, memory | — |
| companion-eval | Tamil test set: verified charts (via Astrotamil's engine through app-run tools) + rated answers, and a demo video | memory, chat-api | — |

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

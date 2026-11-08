# Aira Companion — Statement of Intent

Confirmed by Prem on 2026-11-08. This is the agreed intent, not a spec. The spec and plan build on it.

## 1. What it is

- One AI engine, many companies. Any business creates its own AI agent and plugs it into its own app or website.
- Built **per industry, not per client**: the engine is built once, each client self-serves its copy (~10 min), and an industry tool (e.g. the astrology chart engine) is built once and reused by every client in that industry.
- A new product **under Anril** (same company, same repo), with **its own product name** (name TBD; working name "Aira Companion").
- **Pilot: Astrotamil — a Tamil AI astrologer** that answers any astrology question and generates correct horoscopes. The product supports both "replace the astrologer" and "assist the astrologer"; how it is pitched is Prem's call.

## 2. End-to-end journey

```
1. BUY        Client sees demo → signs up on Anril → v1: onboarded by hand + invoice
2. SET UP     Anril dashboard → Companion section
                persona · rules · upload docs/books · memory level · privacy A/B
3. PLUG IN    Copy plugin code + secret key → client's dev pastes it in their app/site
4. USE        End user taps "Chat with Jothidar AI" → text chat
5. RUN        Client updates docs, reads chats (A) or stats (B) — in the Anril dashboard
6. CONTROL    Anril super-admin: clients, plans, usage, AI cost, on/off, tools enabled
              — never their chats or memories
```

Worked example (Astrotamil):

```
Karthik: "12 Mar 1998, 6:40 am, Madurai. Job eppo maarum?"
  chart engine → exact lagna, rasi, current dasha
  knowledge    → book passages on 10th house / dasha results
  memory (L2)  → saves: Karthik · Simha · worried about job switch
Jothidar AI → answer in Tanglish, timing + remedy
2 weeks later — "Hi" → "Vanakkam Karthik! Zoho interview eppadi pochu?"
```

## 3. Reply assembly — five layers

```
1. Platform rules   Anril-owned, cannot be overridden by a client: no self-harm advice,
                    no medical/legal certainty, admits it is an AI if asked,
                    "forget me" always works
2. Company persona  name, tone, language, rules             ← dashboard
3. Knowledge base   the company's docs/books                 ← reuse Aira's KB
4. Memory           facts about this end user                ← Mem0
5. Tools            exact data/actions per industry          ← astrology chart engine
```

Layer 1 sits above layer 2 so no client can make the engine lie or manipulate users under Anril's engine. Same idea as today's master prompt + per-business Description.

## 4. Memory

| Level | Remembers | Suits | Built with |
|---|---|---|---|
| 1 | Chat history only | Bank, delivery | Existing message storage |
| 2 | Key facts (rasi, worries, preferences) | Astrotamil | **Mem0 open source (Apache 2.0), self-hosted** |
| 3 | Full life journal over time | Companion/social apps | Zep's Graphiti (time-aware graph) — later |

- Each business picks its level. The end user can always say "forget that".
- Mem0 chosen because: free licence, saves ~1–2 weeks, data stays in our DB. Cost: one extra LLM call per chat for fact extraction.
- Rejected: Supermemory (engine closed; free self-host binary capped at 10,000 documents; duplicates our KB), Letta (would replace the engine), LangMem, Cognee.
- Future option: own memory engine, better than Mem0 for Tamil/Hinglish, measured on our own test set — and possibly sold to developers once it is measurably better.

## 5. Privacy

- Each business picks **A** (business can read chats) or **B** (stats only). The end user is told which.
- **No Anril staff access** to companion chats, memories or related data — enforced by design: separate tables, no operator-console view.
- Honest wording: "no staff access", not "unreadable". The LLM provider still sees each message while generating the reply; use providers that do not store or train on it.
- Trade-off: debugging a bad reply requires the client to send us a copy.

## 6. Knowledge base

- Reuse Aira's KB (upload, auto-sort, retrieval).
- Raise the 50,000-character extraction cap — astrology books are ~500k+ characters.
- Tamil OCR for scanned books (expect errors).
- Client uploads the books and owns copyright risk.

## 7. Industry tools

- Astrology chart engine: exact maths (lagna, rasi, nakshatra, dasha, porutham), never LLM-guessed. LLM only interprets.
- Engine choice open: Swiss Ephemeris commercial licence (~CHF 700, unconfirmed), a free alternative (accuracy to verify), or Astrotamil's own chart system. Decide in the spec.
- Later: banking ("check balance"), delivery ("track order").

## 8. Channels and plugin

- Text in v1; voice in v2 (~5–10× cost per minute).
- v1 plugin: web chat widget + API. No native iOS/Android SDK.

## 9. Clients who want everything in their own admin panel (later, in order)

1. Management API + webhooks (secret server-side keys, scopes, revocable).
2. White-label iframe with short-lived SSO token.
3. Embeddable admin components — only after 3+ clients ask.

**Do now:** every dashboard action goes through the FastAPI backend, so the management API is mostly existing routes with API-key auth.

## 10. Architecture rules

- Own workers, so companion load cannot slow Aira's WhatsApp replies.
- Own tables and folders — keeps the privacy promise and allows a spin-out later.
- Connectors (Drive, Notion) only when a paying client asks; Google Drive likely first.

## 11. Market and positioning

- AstroSure.ai (Chennai): AI-only astrologer, $6M seed (Jan 2025), freemium — Astrotamil's rival.
- InstaAstro: $12M Series A (Aug 2026), ₹111 cr FY26 revenue, AI assists human astrologers.
- Astrotalk: ~₹1,176 cr FY25, ~90% from human minutes (search snippets).
- Gap: nobody sells a white-label AI astrologer to astrology platforms.
- Positioning: not "like Supermemory" (a developer part). Closer to Intercom's Fin / Sierra, for Indian businesses, in regional languages.

## 12. Money

- Likely yes-price (council Buyer persona): ₹0 setup + ₹6,000/month + ~₹2/session, capped at ₹15k/month, with exit clause.
- Running cost near zero (Groq, self-hosted Mem0) + chart-engine licence if Swiss Ephemeris.

## 13. Timeline (3–4 weeks)

```
Week 1  Companion tables + own worker · 5-layer reply engine · chat API + web widget
        · chart engine
Week 2  Mem0 self-hosted (Level 1/2 + "forget me") · book-size KB + Tamil OCR
Week 3  Dashboard Companion section (persona, books, memory, privacy, plugin code)
        · super-admin usage view · privacy A/B enforced
Week 4  Test with real Tamil charts · polish · demo video
```

## 14. Out of scope (v1)

Voice · client-admin API / iframe / embeddable components · connectors · Level 3 memory · selling memory to developers · banking/delivery tools · self-serve billing · native mobile SDK.

## 15. Open items

1. Chart engine choice — at spec time.
2. Product name — before the landing page.
3. Book the Astrotamil call — flagged by the whole council; answers on "do you already compute charts?" may change the spec.

## 16. Council verdict (roast, 2026-11-07)

RESHAPE: build the astrology product first; the platform grows from it.
Contrarian 3 · Expansionist 8 · Logician 6 · Researcher 6 · Buyer 5.

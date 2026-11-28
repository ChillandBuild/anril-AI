# Aira AI — Security & Vulnerability Guidance

Read this when touching: auth, webhooks (WhatsApp/Instagram/Facebook/Telegram), payments (Razorpay), file uploads, any route reading `tenant_id`, or anything under `routes/` that writes/reads leads, calls, or recordings.

## Hard checks (from stack-and-rules.md — don't re-derive, verify against code)
1. **Tenant isolation** — every table RLS-enabled (migration 114); app layer also gates via `get_tenant_and_role()`. New table/route → confirm both layers, not just one.
2. **Webhook signatures** — WhatsApp inbound must verify `X-Hub-Signature-256` before processing; invalid sig returns 200 but drops the payload (never 4xx — Meta retries storms on non-200).
3. **`anon` role** — no EXECUTE on SECURITY DEFINER functions. New definer function → revoke `anon` explicitly in the migration.
4. **Provider keys are per-tenant** — never add a platform-level fallback key for AI/WhatsApp/Voice providers (see stack-and-rules.md Provider Decisions). A shared fallback key is a tenant-isolation break, not just a config smell.
5. **Call recordings** — Supabase Storage only, never local disk (invariant #5). Check any new recording-handling code doesn't write to `/tmp` or similar and forget to clean up.
6. **Broadcast gate** — bulk-send must reject leads with null `opt_in_source`; DNC (`do_not_call`) and `opted_out` are separate flags, don't conflate.
7. **Client IP = `_client_ip(request)` only** (`routes/auto_messages.py`) — for every per-IP rate limit, IP log or IP check. Never `request.client.host`, `X-Forwarded-For`, `True-Client-IP` or slowapi's `get_remote_address`. On Render, uvicorn replaces `request.client` with the leftmost X-Forwarded-For entry, which the caller types (proven live 2026-11-23: `X-Forwarded-For: 203.0.113.77` was logged as `203.0.113.77:0`). `_client_ip` reads `CF-Connecting-IP`, which Cloudflare overwrites and won't accept from a client (403, error 1000). Unit tests can't show this: prove any change to IP trust with a live spoofed-header request against Render (commits 8e5caa17, 75cc8944). Prem's Mac leaves from ~3–4 rotating egress IPs, so a live limit test needs ~4× the limit in requests. The app-wide slowapi key (`main._rate_limit_key`, cca94717) is "user:<id>" only for a proven Bearer token, else "ip:<_client_ip>"; never key on an unverified token's `sub`.

## Standard checklist (apply per OWASP-style categories — see skill `security-review` for full code patterns)
- **Secrets**: env vars only, never in source; check `.env` files aren't committed before any commit.
- **Input validation**: Pydantic v2 schemas on all FastAPI route bodies; reject unknown/malformed payloads.
- **SQL**: Supabase client / parameterized queries only, no string-built SQL.
- **Payments (Razorpay)**: verify webhook signatures on Razorpay callbacks before marking a payment link paid; never trust client-reported payment status.
- **Rate limiting**: webhook and broadcast endpoints are the ones actually worth limiting here (external retries + bulk-send abuse potential) — check before adding new public-facing routes.
- **Error responses**: no stack traces or internal Supabase errors surfaced to the frontend; log detail server-side only.

## Where to look, in order
1. A targeted grep for the exact file:line on the subsystem you're touching.
2. This file's Hard checks above — confirm against actual code with a targeted grep, don't assume from memory.
3. `.agents/decisions/log.md` for why a security-relevant call was made a certain way (e.g. RLS migration history).
4. Full `security-review` skill for generic code-pattern examples (Next.js/TS-flavored — adapt, don't copy verbatim since backend is FastAPI/Python).

## When to escalate to a full pass
Run `/security-review` on the diff (not just this checklist) when: new auth/authz code, new webhook endpoint, new payment code path, or any change touching RLS policies directly.

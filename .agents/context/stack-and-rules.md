# Aira AI — Stack, Configuration, & Invariants

## Technology Stack
| Layer | Tech | Location |
|---|---|---|
| Backend | FastAPI, Python 3.11+, Pydantic v2 | backend/app/ |
| DB | Supabase (PostgreSQL + Realtime) | — |
| Frontend | Next.js 14 App Router, TypeScript, Tailwind | frontend/app/dashboard/ |
| AI | Replies: per-tenant operator choice of Sarvam / Groq / Gemini / OpenAI (`ai_reply_model`, no default); Gemini 3.1 Flash-Lite for STT, doc digitization, call analysis; Gemini TTS for voice replies; Groq for scoring/coaching/digests/tuning/briefs/compaction | services/ai_reply.py, services/{sarvam,groq,gemini,openai}_client.py |
| WhatsApp | Meta Cloud API Direct | — |
| Voice | TeleCMI click-to-call + recording | services/telecmi_client.py |
| Payments | Razorpay Payment Links API | services/payment_razorpay.py |
| Scheduler | Procrastinate 3.10 task queue (Postgres schema `procrastinate`, worker inside the web process) | app/queue/ (tasks.py, safety.py, status.py), app/main.py lifespan |
| Cache | In-process prompt cache (60s TTL) | ai_reply.py:_prompt_cache |

## Provider Decisions (Locked)
- **WhatsApp**: Meta Cloud API Direct.
- **Voice**: TeleCMI (click-to-call + recording).
- **AI providers (per-workload, updated 2026-07-18)**: WhatsApp AI replies route to the tenant's explicit `ai_reply_model` choice — Sarvam, Groq, Gemini, or OpenAI as **equal peers**, no hardcoded default (operator picks per tenant, same contract as provider keys). STT (voice notes + call recordings), knowledge doc digitization, TeleCMI call evaluation (v4, 2026-09-28), lead scoring, conversation compaction and AI tuning run on Gemini 3.1 Flash-Lite; voice-reply TTS on Gemini. Groq survives only as a tenant-selectable reply model (updated 2026-09-28). Every provider key is strictly per-tenant (see subsystem-notes) — never add a platform-key fallback.
- **Payments**: Razorpay (Payment Links API — no SDK, direct httpx/httpx-async calls).
  Two ways a tenant connects (added 2026-10-30): pasted keys (`razorpay_key_id/_secret/_webhook_secret`,
  webhook `/api/v1/intake/razorpay-webhook`) or **Connect with Razorpay** OAuth
  (`services/razorpay_oauth.py`, tokens in `razorpay_oauth_*` rows, OAuth wins when both exist).
  OAuth uses one partner app for every tenant, like Meta: Render env `RAZORPAY_OAUTH_CLIENT_ID`,
  `_CLIENT_SECRET`, `_REDIRECT_URI` (frontend `/dashboard/settings/razorpay-callback`),
  `_WEBHOOK_SECRET`, `_MODE` (test|live). The app's single webhook is
  `/api/v1/intake/razorpay-oauth-webhook`, routed by payload `account_id`. Plan: docs/plans/2026-10-30-razorpay-oauth.md.

## Production Configs
- **Supabase Project ID**: `ayftynkgmfkaqmmnlmoc`
- **Supabase Region**: `ap-northeast-1`
- **WhatsApp Business Account (WABA) ID**: `meta_waba_id = 994218516456571`
- **Backend Production URL**: `https://aira-ai-5tfr.onrender.com`
- **WhatsApp Webhook URL**: `https://aira-ai-5tfr.onrender.com/webhook/whatsapp`
- **Instagram Webhook URL**: `https://aira-ai-5tfr.onrender.com/webhook/instagram` (shared — preferred). The legacy `/webhook/instagram/{tenant_id}` form still works but serves only that one tenant.
- **Facebook Webhook URL**: `https://aira-ai-5tfr.onrender.com/webhook/facebook` (shared — preferred). Legacy `/webhook/facebook/{tenant_id}` likewise.

### The Meta app — one app for every client
There is exactly **one** Meta app for all tenants. It belongs to the **Bloom Matrix** account and
holds the approved WhatsApp messaging + management permissions. Its id and secret live **only** in
Render env (`META_APP_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN`) — never per tenant, never in the
repo.
- **Production Meta App ID**: `2225044871604460` (Bloom Matrix)
- **The callback URL + verify token are app-level and now register themselves.**
  `services/meta_app_webhooks.py` calls `POST /{app-id}/subscriptions` with the shared
  tenant-agnostic URLs; it runs on every channel activation and on demand via
  `POST /api/v1/settings/webhook-subscriptions/sync`. Nothing per-client configures them
  because there is nothing per-client about them — one URL and one token serve every tenant.
  The verify token resolves from `META_VERIFY_TOKEN`, falling back to any tenant's stored
  copy (this deployment has the tenants' copies but not the env var).
- Onboarding a client adds **no** Render env var. Client-specific values (`meta_waba_id`,
  `meta_phone_number_id`, `meta_access_token`, `{facebook,instagram}_page_id`,
  `{facebook,instagram}_access_token`) are written per tenant into `app_settings` by Embedded
  Signup.
- Configuring a channel in any **other** Meta app silently breaks it: Meta signs each payload with
  the App Secret of the app owning the subscription, so every event fails verification and is
  dropped. `activate_channel` now refuses a token whose `debug_token` app id differs from
  `META_APP_ID`, and a signature rejection logs the secret's fingerprint — see
  [subsystem-notes](subsystem-notes.md#meta-webhook-signature-verification--which-apps-secret-signs-what-2026-08-30).
- **Rotating `META_APP_SECRET` does not reach existing tenants.** `_save_shared_meta_app_credentials()`
  copies it into `app_settings` only at connect time, and `get_setting` has no env fallback. Rotating
  it requires re-writing every tenant's row or every already-onboarded client breaks.
- **Telegram Webhook URL**: `https://aira-ai-5tfr.onrender.com/webhook/telegram/{tenant_id}`

## Hard Invariants (Never Break)
1. **Lead Score**: Always an integer 0–10 (0 = "Not Interested" / segment D floor, migration 164). Was 1–10 before 2026-08; corrected 2026-09-22 to match the live DB CHECK and `scoring_engine.py` — see AUDIT-2026-09.md finding C1.
2. **Segments**: A=Hot, B=Warm, C=Cold, D=Disqualified. Labels are immutable.
3. **WhatsApp Window**: 24h session window — approved templates only outside window.
4. **Segment Export**: All segment list routes must resolve: `GET /api/v1/leads?segment=A&format=csv`.
5. **Call Recordings**: Uploaded to Supabase Storage only, never saved to local disk.
6. **Multi-Tenancy & Security**: Isolation enforced at DB level (RLS policies) and app-layer (`get_tenant_and_role()`). All public tables have RLS enabled (migration 114). `anon` role EXECUTE privilege is revoked on definer functions.
7. **Broadcast Gate**: Bulk-send endpoint rejects leads with null `opt_in_source`.
8. **Template Submissions**: Meta API template submissions must use `meta_waba_id` (not `meta_phone_number_id`).
9. **Signature Checks**: WhatsApp webhooks must verify `X-Hub-Signature-256` before processing (returns 200 but drops invalid signature calls).
10. **Pipeline Independence**: `call_status` (telecalling outcomes) is orthogonal to lead `segment`. Voice outcomes do NOT write segment labels.
11. **DNC/Opt-Out**: DNC is lead-level (`do_not_call`), NOT a `call_logs.outcome` constraint. Voice opt-out sets `do_not_call`. Text opt-out sets `opted_out`.
12. **Admin Exclusion**: Owner/Admin filtered from all telecaller metrics (attendance, shift tracking, leaderboards, timeline metrics). Frontend Leaderboard filters admin via `callerIds` set. Profile page resolves admin card using `useAuthRole()`.

## Core Configuration Panels
- **InboxConfigPanel**: Chat escalation toggle on/off per behavioral triggers (A/B/C/D/F). Escales are trigger-only; handovers land `UNASSIGNED` in a shared pool.
- **TelecallingConfigPanel**: Auto-assign, per-segment routing (A/B/C/D), channels, contact recycling configurations, and shift hour limits.

## File Map & Routing Guidelines
- WhatsApp/Meta: [routes/webhook.py](../../backend/app/routes/webhook.py), [services/meta_cloud.py](../../backend/app/services/meta_cloud.py), [services/outbound_router.py](../../backend/app/services/outbound_router.py)
- Voice/Telecalling: [routes/calls.py](../../backend/app/routes/calls.py), [services/telecmi_client.py](../../backend/app/services/telecmi_client.py), [services/call_ai_pipeline.py](../../backend/app/services/call_ai_pipeline.py), [services/call_wrapup.py](../../backend/app/services/call_wrapup.py)
- Reassignment/Round-Robin: [services/assignment.py](../../backend/app/services/assignment.py), [routes/assignment_log.py](../../backend/app/routes/assignment_log.py), [main.py (scheduler sweeps)](../../backend/app/main.py)
- Upload/Scripts/Recycler: [routes/telecalling_upload.py](../../backend/app/routes/telecalling_upload.py), [routes/call_scripts.py](../../backend/app/routes/call_scripts.py), [services/contact_recycler.py](../../backend/app/services/contact_recycler.py)
- Leads & Scoring: [routes/leads.py](../../backend/app/routes/leads.py), [services/scoring_engine.py](../../backend/app/services/scoring_engine.py)
- Incidents: [routes/numbers.py](../../backend/app/routes/numbers.py), [services/failover.py](../../backend/app/services/failover.py), [routes/incidents.py](../../backend/app/routes/incidents.py)
- Broadcasts/Templates: [routes/upload.py](../../backend/app/routes/upload.py), [services/broadcast_executor.py](../../backend/app/services/broadcast_executor.py), [routes/templates.py](../../backend/app/routes/templates.py)
- Settings & Health: [routes/app_settings.py](../../backend/app/routes/app_settings.py)

## Running the Backend Tests
- `cd backend && python -m pytest`, run from `backend/`, not the repo root. 4403 tests as of 2026-10-17.
- Bare `pytest` fails at collection with `ModuleNotFoundError: No module named 'app'`: several test modules import `app.*` without adding the backend dir to `sys.path`. `python -m` puts the cwd on `sys.path`.
- Windows: run `PYTHONUTF8=1 python -m pytest`. `test_anril_rename_copy` reads every backend file and fails under the default cp1252 encoding.

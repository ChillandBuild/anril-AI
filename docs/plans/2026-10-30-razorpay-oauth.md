# Razorpay OAuth ("Connect with Razorpay") — plan

Status: draft, waiting for approval. Decisions so far (Prem, 2026-10-30):
- Test-mode partner creds exist (Development client ID + secret).
- OAuth sits **next to** pasted keys; OAuth wins when both exist.
- Scope: payment links only (same as today) → `read_write`.

Docs: https://razorpay.com/docs/partners/technology-partners/onboard-businesses/integrate-oauth/integration-steps.md

## The flow

```
Tenant admin            Frontend (Vercel)                Backend (Render)                 Razorpay
-----------             -----------------                ----------------                 --------
click "Connect" ──────► POST /settings/razorpay/oauth/start ──► make state, save it (10 min)
                        ◄── authorize_url ◄─────────────────────
browser goes to ─────────────────────────────────────────────────────────────────────────► auth.razorpay.com/authorize
                                                                                            admin clicks Authorize
lands on /dashboard/settings/razorpay-callback?code=..&state=.. ◄───────────────────────────
                        POST /settings/razorpay/oauth/complete {code, state} ──►
                                                         check state matches + not expired
                                                         POST auth.razorpay.com/token ────► access + refresh token
                                                         save tokens in app_settings
                        ◄── {connected, account_id}
```

Worked example: AstroTamil's admin clicks Connect. Backend saves
razorpay_oauth_state = "q7Xk…", expires 10:10. Razorpay sends them back with
code=def50200…&state=q7Xk…. Backend matches state, swaps code, and stores
razorpay_oauth_account_id = acc_Dhk2qDbmu6FwZH, an access token that lasts about 90 days, and a refresh token that lasts 180 days.
The next deal quote calls POST api.razorpay.com/v1/payment_links with
"Authorization: Bearer <access token>" instead of key_id:key_secret.

## Slices

### 1. Config + OAuth service (backend)
- `config.py`: new env vars RAZORPAY_OAUTH_CLIENT_ID, RAZORPAY_OAUTH_CLIENT_SECRET,
  RAZORPAY_OAUTH_REDIRECT_URI, RAZORPAY_OAUTH_WEBHOOK_SECRET, RAZORPAY_OAUTH_MODE (test|live, default live).
- New `services/razorpay_oauth.py`: `build_authorize_url`, `exchange_code`, `refresh`, `revoke`.
  Uses httpx directly, like the rest of the codebase. No SDK.
- New app_settings keys (no migration, it's key/value): razorpay_oauth_access_token,
  _refresh_token, _public_token, _account_id, _expires_at, _state, _state_expires_at.
  Tokens go into SECRET_SETTING_KEYS.
- Routes in `app_settings.py`, kept away from keerthi's meta_ads block (~:1718-1815):
  - POST /api/v1/settings/razorpay/oauth/start (settings.manage) → {authorize_url}
  - POST /api/v1/settings/razorpay/oauth/complete (settings.manage) → {account_id}
- Guards: state is single-use, lasts 10 min, and is tied to the tenant from the JWT. redirect_uri always comes from env, never from the request.
  One Razorpay account maps to one tenant: if acc_X is already linked to tenant A, tenant B is rejected (otherwise the webhooks get ambiguous).

### 2. Use the token when creating/cancelling links
- `payment_razorpay.py`: replace the inline `auth=(key_id, key_secret)` (:94, :134) with one
  `_auth_for(tenant_id)`. It returns a Bearer header when an OAuth token exists and falls back to the pasted keys otherwise.
- Refresh when fewer than 7 days are left, and retry once on a 401.
- Refresh tokens **rotate**: the old one dies the moment a new one is issued. If two workers refresh at the same time, one of them saves a dead token
  and the tenant is silently disconnected. Fix: compare-and-swap. The update only lands
  `where value = <old refresh token>`. The loser re-reads and uses the winner's token.

### 3. Webhooks
- The OAuth app has **one** webhook URL and **one** app-level secret for all connected merchants.
  The per-tenant razorpay_webhook_secret does not apply here.
- New public route POST /api/v1/intake/razorpay-oauth-webhook:
  1. Verify HMAC of the raw body with RAZORPAY_OAUTH_WEBHOOK_SECRET.
  2. Use the payload's top-level account_id to find the tenant (lookup on razorpay_oauth_account_id).
  3. `payment_link.paid/expired/cancelled` → the same handler as today. Extra check: the tenant from the
     notes (booking_id/deal_id) must equal the tenant from account_id, so tenant A can't mark tenant B's deal won.
  4. `account.app.authorization_revoked` → delete that tenant's OAuth keys. The pasted keys, if any, take over.
- The old /razorpay-webhook routes stay untouched (pasted-key tenants keep working).

### 4. Disconnect
- The existing POST /settings/disconnect {channel: "razorpay"} also calls auth.razorpay.com/revoke
  for both tokens (best effort) and deletes the OAuth keys.

### 5. Frontend
- Razorpay card (`connect-channels/channels.ts`, ChannelCard/ChannelConfigModal): "Connect with Razorpay"
  button as the main action, with "Enter API keys manually" kept as a link. When connected, it shows acc_… + Disconnect.
- New page `app/dashboard/settings/razorpay-callback/page.tsx`: reads code/state (or error=access_denied),
  POSTs to /complete, and sends the user back to Connect Channels with a toast.

### 6. Tests (pytest, httpx mocked)
Start builds the right URL. Complete rejects a wrong, expired or reused state. An account already linked elsewhere is rejected.
Tokens are stored as secrets. `_auth_for` picks Bearer over keys. The refresh CAS loser re-reads. The webhook rejects a bad signature,
an unknown account_id, and a notes-tenant ≠ account-tenant mismatch. Revoke clears the keys.

### 7. QA (test mode, local)
`make dev-backend` + frontend pointed at localhost:8000, as the UI test tenant: connect,
create a deal quote link, pay with a Razorpay test card, and confirm the webhook marks the deal won.

## What Prem must do in Razorpay (I can't)
1. Whitelist the redirect URI on the Development client:
   http://localhost:3000/dashboard/settings/razorpay-callback (local QA) and
   https://www.anrilaitech.com/dashboard/settings/razorpay-callback.
2. Applications → Manage Webhook: URL = https://<render-host>/api/v1/intake/razorpay-oauth-webhook,
   set a secret, subscribe to payment_link.paid / expired / cancelled + account.app.authorization_revoked.
   **Unverified:** the docs don't say payment_link events can be picked there. Check the event list.
   If they can't, slice 3 changes and I'll come back before building it.
3. Put the 5 env vars in backend/.env (local) and Render (when we ship).

## Risks / not in scope
- Tokens sit in plain text in app_settings, the same as today's pasted key_secret (nothing in this repo encrypts settings).
  Not made worse, but an OAuth token is worth encrypting later → backlog item.
- Going live needs Razorpay's go-live checklist and Production client creds. This plan stops at test mode.
- No refunds, no Checkout/public_token use (payment links are server-side only).

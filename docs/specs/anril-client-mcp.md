# Anril AI: the client connector (client MCP)

Status (2026-11-21): **built, not deployed, switched off.** Backend + consent screen are written
and tested, an independent security review's findings are fixed (section 6), and the Settings
page (Settings → Anril AI for Claude) is built from the approved mockup. Migration 303 is a file
only (not applied). Nothing here is live until the "To switch it on" list at the bottom is done.

Sister document: [anril-admin-mcp.md](anril-admin-mcp.md) (Prem's read-only admin connector).

## 1. What Prem asked for (confirmed 2026-11-20/21)

- **Outcome:** a connector called **Anril AI** that lets a client's owner ask about their
  business, edit lead records, send one-to-one replies and send broadcasts from their own Claude
  app. Built once, with writes included. The admin connector is renamed **Anril Admin**.
- **User:** the owner of a client the operator has switched on. **AstroTamil is the pilot.**
  Staff do not get it in version 1.
- **Constraints:** broadcasts need an approved template and stay under **500 messages a day per
  client** (the owner can change it). Sends follow the app's own rules. Its own address and its
  own sign-in app, separate from Anril Admin. A **list** of approved apps from day one.
- **Out of scope:** staff access, ChatGPT / Codex (pilot is Claude only), pricing (free in the
  pilot), and anything touching money, team and roles, deleting, settings or keys.

## 2. How one question travels

AstroTamil's owner types in Claude: "Reply to Priya that her chart is ready."

```
Claude app ──token──▶ https://mcp.anrilaitech.com/client/mcp
   1. token valid, and issued to an approved client app?        (client_mcp/auth.py)
   2. user → tenant_users: owner of exactly ONE client?          → AstroTamil
   3. AstroTamil not suspended, "claude" in enabled_features?
   4. active row in tenant_mcp_connections for this owner + app? (the owner's off switch)
   ── any "no" = 401, Claude asks to sign in again ──
   5. find_leads(search="Priya")   read, database locked against writes, audit row after
   6. reply_options(lead_id)       is free text allowed (24-hour rule), which templates fit
                                   (a blocked or undeliverable lead: nothing can be sent)
   7. send_reply(lead_id, text)    Claude shows "Allow?" → audit row BEFORE → book 1 against
                                   today's cap → the app's own send path → audit row after
```

The client is never an argument. A tool learns it only from `wrapper.tenant_id()`, which reads
the signed-in seat. A test fails if any tool grows a tenant / client / user parameter.

## 3. The 18 tools

| Kind | Tools | What protects it |
|---|---|---|
| **Ask** (14) | my_business, dashboard_summary, messaging_stats, leads_overview, find_leads, lead_details, conversations, calling_stats, broadcasts, templates, team, plan_and_usage, reply_options, preview_broadcast | Database in read-only mode. Audit row after; no row = answer withheld. |
| **Edit** (2) | assign_lead, add_lead_note | Lead must belong to the client. Calls the dashboard's own handler. Audit row before and after. |
| **Send** (2) | send_reply, send_broadcast | Marked as actions so Claude asks first. Daily cap. Repeat guard. The app's own send rules. A broadcast needs a preview token. |

Most ask tools return what the matching Operator Console read returns for one client (the same
functions the admin connector already runs live under the read-only guard), with the client
fixed by the sign-in. An audit of those ten reads found no platform cost data, secrets or other
clients' rows in their answers.

**No "change a lead's segment" tool.** In the app a segment change re-plans that lead's automatic
WhatsApp follow-ups (`sync_follow_up_jobs`), so through the connector it would message customers
outside the daily cap. It comes back only with cap booking (section 8).

### Sending rules (worked example)

"Send the Diwali offer template to all leads from October", AstroTamil, cap 500, 30 used today.

1. `preview_broadcast(template_name="diwali_offer", variables=["{name}"], created_from="2026-10-01", created_to="2026-10-31")`
   → 212 would receive it; left out: 9 opted out, 3 with no recorded opt-in; 5 sample messages;
   470 left today, fits; and a `preview_token` good for 10 minutes.
2. Claude tells the owner. Owner says yes. Claude calls `send_broadcast(..., preview_token=...)`
   and the Claude app shows its own "Allow?" prompt.
3. The server works out the audience again and checks the token. The token is a signature over
   this owner, the template and its wording, and the exact 212 leads with their filled-in
   blanks, made with a key only the server has. Same 212 → books 212 against the cap (one
   database statement, so two sends at once cannot both slip under) → saves ONE scheduled
   broadcast starting in 2 minutes.
4. The app's normal scheduler sends it. It shows in Anril → Broadcasts and can be cancelled
   there until it starts.

What refuses a send:

| Situation | Result |
|---|---|
| No preview token, a made-up one, or one older than 10 minutes | Not sent; preview again (the refusal does not say how many people it would reach) |
| Audience or wording changed since the preview (even to another 212 people) | Not sent; preview again |
| No filter, a blank or 1 to 2 letter search, or filters that match every lead (for example "created since 2000") | Refused; send from Anril itself, or list the leads with `lead_ids` |
| Template with an image / video / document header, or from a WhatsApp account no longer connected | Refused; send from Anril itself |
| Over today's cap | Not sent; says how many are left |
| Template not APPROVED, or wrong number of blanks | Refused |
| Lead opted out, blocked, undeliverable, or opt-in missing / "manual" | Left out of a broadcast (the app's own rule) |
| One-to-one message to a blocked or undeliverable lead | Refused |
| Outside 9 am to 9 pm Indian time | Refused; pass a `send_at` inside those hours |
| Same template to the same number of people within 10 minutes | Refused (a retry, not a second campaign) |
| One-to-one free text more than 24 hours after the customer's last message | Refused; send a template |
| Same text to the same lead within 2 minutes | Refused |

Assumptions I made that Prem did not state (easy to change): the 9 am to 9 pm window, the
2-minute start delay, the 10-minute life of a preview, the 10,000 hard ceiling on the cap, and
that a broadcast to every lead must be sent from Anril itself.

## 4. Where things live

| Piece | File |
|---|---|
| Who gets in | `backend/app/client_mcp/auth.py`, `backend/app/services/client_claude.py` (`owner_seat`) |
| The one door (client wall, guards, audit, limits) | `backend/app/client_mcp/wrapper.py` (`APPROVED_TOOLS`) |
| Tools | `backend/app/client_mcp/tools_read.py`, `tools_edit.py`, `tools_send.py`, `leads.py` |
| Server + annotations | `backend/app/client_mcp/server.py`; gateway reused from `admin_mcp/server.py` |
| Connection table, cap counter, 2 SQL functions | `backend/supabase/migrations/303_client_claude.sql` (+ undo) |
| Dashboard routes (`/api/v1/claude`) | `backend/app/routes/claude_connector.py` |
| Consent screen (one page for both connectors) | `frontend/app/operator/oauth/consent/page.tsx` |
| Settings → Anril AI for Claude | `frontend/app/dashboard/settings/ClaudeConnectorPanel.tsx`, `settings/claude/page.tsx`; menu entry in `frontend/components/settingsNavigation.ts` (owner + `claude` feature only); wording helpers in `frontend/lib/claude-access.ts` |
| Tests (59) | `backend/tests/test_client_mcp_core.py`, `test_client_mcp_tools.py`, `test_client_mcp_routes.py` |

Settings: `MCP_CLIENT_ENABLED` (default off = `/client/mcp` is 404) and
`MCP_CLIENT_OAUTH_CLIENT_IDS` (comma-separated approved apps; the admin app's id is dropped from
it even if someone lists it).

Limits: 60 tool calls a minute per client, 6 running at once across all clients, 90 seconds per
call, 600 requests a minute per caller address (flood guard only: every client's Claude arrives
from the same few addresses).

Audit: every call writes `app_audit_logs` with the client's id and action `claude.read`,
`claude.edit` or `claude.send`; connection and cap changes write `claude.connection.*` and
`claude.cap.change`. The owner sees them in Anril → Roles → Audit (the list now includes
`claude.%`, for the owner only). Long text is cut to 200 characters, long lists to 10 items, and
a phone typed into a search is kept as its last 4 digits. A crash inside a tool is logged on the
server; Claude only hears "something went wrong inside Anril".

## 5. Traps

- **Never call the immediate branch of `upload.bulk_send` from a tool.** It sends from a
  background task of the web request; a tool runs in a worker thread with its own short-lived
  event loop, so that task would be cancelled mid-send. Always `schedule_type="scheduled"`.
- **The backend skips row-level security.** The client wall is `own_lead` / `filtered` in
  `client_mcp/leads.py` plus handlers that take the tenant explicitly. A new tool that queries a
  table directly must filter by `tenant_id()` itself.
- **Do not call `resolve_permissions`, `get_my_subscription`, `list_team` or `client_roles` from
  a read tool.** They write, and the read-only guard stops the call.
- **Supabase has one consent path per project,** so both connectors share
  `/operator/oauth/consent`. The page asks `/api/v1/claude/consent` which connector the app is.
  If that route is missing (old backend) it treats every app as the admin app.
- **The operator login signs non-admins out,** so a signed-out owner is never sent there: the
  consent page shows "Sign in to Anril" (new tab) and a Continue button.
- **`already_consented` carries no client id, and must never be followed without a click.**
  Supabase hands back only a redirect when the person approved the app before. Following it
  automatically would let anyone who starts a sign-in in their own Claude and sends the owner
  the link get connected as that owner. The page shows "Continue to Claude" (only while one of
  our own switches is on) and the owner must press it. This applies to the admin connector too.
- **A cap booking is given back only when the app refuses the broadcast (a 4xx).** On any other
  failure the broadcast may have been saved, so the booking stays.

## 6. Security review (2026-11-21) and what is still open

An independent reviewer read every file. No way through the wall between clients was found.
Fixed: the consent page no longer continues without a click; the "who gets it" rule cannot be
passed with a blank or catch-all filter; `send_broadcast` needs a signed preview token instead
of a number Claude could guess; `set_lead_stage` removed; audit rows mask phones and cut lists;
raw errors never reach Claude; `send_reply` respects blocked / undeliverable; broadcast
templates use the app's own "can be sent" rule; migration 303 pins `search_path` and revokes
table access from `anon` / `authenticated`.

Still open (decide before or during the pilot):

- **Disconnect has two halves.** The backend switches our row off (Claude stops at once). The
  Settings page then also calls `supabase.auth.oauth.revokeGrant` in the owner's browser, which
  removes the saved approval and its refresh tokens. If that second half fails, the page says so
  and shows **Clear old approval** to retry; the consent screen's "switched off" page points
  there. A disconnect made any other way (a direct API call) only does the first half.
- Whether claude.ai ties its sign-in callback to the browser that started it is not verified.
  The Allow and Continue screens both warn "only if you started this yourself".
- Messages Claude sends are saved as sent by the owner; only the audit list shows it was Claude.
- The repeat guards check then act, so two identical calls in the same instant can both pass.
  The daily cap still bounds the total.
- The flood guard (600 requests a minute) counts per caller address before sign-in. Every
  client's Claude comes from the same few addresses, so one very noisy client could slow others.

## 6b. Not done / not proven

- Migration 303 is not applied. Nothing has run against the live database.
- No real sign-in from the Claude app has been tried: that needs the second OAuth app in
  Supabase, a deploy, and the switch on.
- The Settings page and the consent screen's client version are typechecked, linted and their
  wording helpers tested, but neither has been looked at in a browser with real data (that needs
  migration 303 applied).
- Instagram, Telegram and Facebook leads cannot be replied to through `send_reply` yet
  (WhatsApp only, the same path as the app's "Send details").
- A cancelled scheduled broadcast does not give its messages back to the day's cap.
- Renaming the admin connector to "Anril Admin" is already its server name; the name shown in
  Prem's Claude app is whatever he typed when adding it.

## 7. To switch it on (Prem)

1. Commit and push (a push deploys the backend).
2. Apply migration 303.
3. Supabase → Authentication → OAuth Apps: add a second public app (name "Anril AI", redirect
   `https://claude.ai/api/mcp/auth_callback`). Copy its client id.
4. Render env: `MCP_CLIENT_OAUTH_CLIENT_IDS=<that id>`, `MCP_CLIENT_ENABLED=true`. Push/deploy.
5. Operator Console → AstroTamil → Configuration → add the custom feature key `claude`. The
   owner now sees Settings → Anril AI for Claude, with the address and client id to copy.
6. AstroTamil's owner follows the four steps on that page: Claude → Settings → Connectors → Add
   custom connector → paste the address, Advanced → paste the client id → Connect → Allow.
7. Pilot check on AstroTamil: one question, one note, one reply to Prem's own number, one
   2-person broadcast to test numbers. Compare the audit list.

## 8. Later

Staff access (a `claude.use` permission; the per-tool permission keys are already recorded in
`APPROVED_TOOLS`), ChatGPT / Codex (add the app's id to the list, allow its return address on
the consent page), other channels for replies, pricing.

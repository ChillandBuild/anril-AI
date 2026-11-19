# Spec: Anril Admin MCP (read-only)

Status: built 2026-11-19, pushed 2026-11-20 with MCP_ENABLED off, migration 295 applied. Sign-in not yet tried against the real Claude app. See section 13 for what changed while building.

## 1. What we are building

A plug (an "MCP server") inside the Anril backend that lets the Claude app read the Operator
Console's data. Prem asks a plain question in Claude, Claude calls one of our tools, the tool
runs the same code the Operator Console page runs, and the answer comes back.

- **User:** only Prem, as platform owner (a user listed in the system_admins table).
- **Where:** the Claude app on laptop and phone, added as a custom connector.
- **Two jobs:** a health check across all clients, and a deep dive into one client.
- **Read-only:** no tool can send, change or delete anything.

```
Prem (phone)            Claude app                 Anril backend (Render)
    │  "How is Anril       │                              │
    │   today?"            │                              │
    ├─────────────────────>│  fleet_summary()             │
    │                      ├─────────────────────────────>│ 1. is the login valid?
    │                      │                              │ 2. is this user a system admin?
    │                      │                              │ 3. is the connection switched on?
    │                      │                              │ 4. run the Operator read
    │                      │                              │ 5. write one audit row
    │                      │<─────────────────────────────┤ numbers per client
    │<─────────────────────┤ "AstroTamil: 42 new leads…"  │
```

### Success (the two messages that must work from the phone)

1. "How is Anril today?" returns, for every active client: leads, messages, failed broadcasts,
   alerts and scheduler state, in one tool call. Figures that exist in the Operator Console
   match it exactly.
2. "Why did Anril reply that to this lead at AstroTamil?" returns the full chat thread with the
   full phone number, plus what Anril saw when it answered.

### Out of scope

- Any write tool (send a broadcast, change settings, pause the scheduler, clear data).
- Access for clients, for Keerthi, or for Anril's own AI agents.
- Phone masking.
- Anything that calls a paid outside service: the AI test sandbox, live SMS balance, and the
  knowledge-retrieval option of "what Anril saw" (one embedding call each time).
- Returning any credential. Client Configuration shows "set / missing" for keys today and the
  MCP keeps it that way. Private Send keys, calling-provider and SMS key reads are not wrapped.

## 2. The login (the one hard part)

The Claude app must prove to Anril that it is acting for Prem. Three ways exist. Research on
2026-11-17 against the official connector docs found:

| Way | Verdict | Why |
|---|---|---|
| No login | Rejected | Anyone who learns the address reads every client's chats. |
| A fixed key typed into the connector | Fallback only | Simplest, but the docs call it a beta for a limited set of organisations. It may not appear in Prem's "Add custom connector" dialog. The key also never expires. |
| Sign in with the Anril account (OAuth) | **Chosen** | Works on every plan and on the phone. It reuses the login Prem already has, and the existing system-admin check stays the judge. |

**Chosen design: sign in through Supabase Auth, which Anril already uses for logins.**

Worked example, the first time Prem connects:

1. Prem adds the connector in the Claude app with this address:
   ```
   https://<backend host>/mcp
   ```
2. Claude calls it with no login. The backend answers 401 and says where to sign in.
3. Claude opens the Anril sign-in page. Prem logs in as usual.
4. Anril shows a new consent screen in the Operator Console: "Claude wants to read Anril
   Operator data. Allow?" Prem clicks Allow. **This click is the approval step.**
5. The backend saves one row: connection for Prem, switched on.
6. From now on every tool call carries a short-lived login token. The backend checks, on every
   call: token valid → user is in system_admins → connection row is switched on.

Switching it off: Operator Console → new page "Claude Access" → the off switch. The very next
tool call is refused.

But what if someone steals the token? It expires on its own, it is useless once the connection
is switched off, and every call it made is in the audit log.

But what if a normal tenant user signs in on the consent screen? They pass step 3 but fail the
system-admin check in step 6, so every tool refuses. The consent screen also refuses to show
Allow to a non-admin.

**Not yet proven, so the build starts with a small trial (section 8, slice 1):**
- Supabase's sign-in tokens are stamped for audience "authenticated", not for our MCP address.
  The MCP rules want the token tied to our server. We will check the token's client id against
  the one registered for Claude instead. Needs a real test.
- Supabase's "OAuth Server" feature must be switched on in the Supabase dashboard, and it needs
  our own consent page. Prem flips that switch himself (it is a security setting).
- Claude looks for a small "where do I sign in" document at the root of the host. We serve it
  from a root route so it is found.

If the trial fails, we fall back to the fixed key (only if Prem's dialog offers "Request
headers"), using the hashed-key pattern Private Send already has.

## 3. The tools

Each tool is a thin wrapper that calls the existing Operator read function inside the backend.
No tool has its own query, except the four marked NEW.

Every answer names its source page, for example: "Operator Console → client → Health". Every
"today" means today in India (IST).

**Fleet (all clients)**

| Tool | What it answers | Runs |
|---|---|---|
| fleet_summary (NEW, composes existing reads) | "How is Anril today?" One row per client, including new leads today (a new figure, labelled as new). | overview + daily messages + broadcasts + alerts |
| list_clients | Who are the clients, status, features | list_clients |
| fleet_alerts | Active platform problems | operator_alerts |
| scheduler_health | Are the background jobs running | scheduler_health |
| system_health | Uptime, memory | system_health |
| fleet_ai_spend | AI cost per client, with trend | get_fleet_token_usage |
| open_requests | Subscription and SMS credit requests waiting | list_subscription_requests + SMS credit requests |
| audit_log | What operators (and this MCP) did | list_audit_logs |

**One client** (the client can be given by name, for example "AstroTamil", or by id)

| Tool | What it answers | Runs |
|---|---|---|
| client_overview | Totals, team size, last activity | client_overview |
| client_health | Channel health, delivery, incidents | client_health |
| client_usage | Plan, what is used vs included, AI cost | entitlements + usage + token-usage |
| client_messages | Per-day inbound / outbound / AI / human | daily-messages + analytics |
| client_leads | Segment counts and recent leads | client_dashboard_leads |
| client_conversations | Recent conversations, waiting handovers | client_dashboard_inbox |
| client_telecalling | Dialer, scheduled, notes | client_dashboard_telecalling |
| client_config | Settings, and which keys are set or missing | client_config |
| client_broadcasts (NEW) | Broadcasts in a date range: sent, delivered, failed | new Operator read |
| find_lead (NEW) | Find a lead by name or phone | new Operator read |
| lead_thread (NEW) | Full chat thread for one lead, newest first, paged | new Operator read |
| what_anril_saw | What Anril would see for this lead | what_anril_saw, retrieval off |

That is 20 tools. Why the three NEW reads: the Operator inbox today returns only the last 20
conversations with the last message cut to 80 characters, has no search, and has no broadcast
history at all. The NEW reads are added as normal Operator endpoints too, so the Console can use
them later.

Worked example, job 2:

```
Prem: "Why did Anril tell Ravi at AstroTamil the book is out of stock?"
Claude → find_lead(client="AstroTamil", query="Ravi")        → lead id, +91 98765 43210
Claude → lead_thread(client="AstroTamil", lead=<id>)         → the messages
Claude → what_anril_saw(client="AstroTamil", lead=<id>)       → the context Anril had
Claude: "Anril saw no stock entry for that book in the knowledge base, so…"
```

Limits: a tool answer stays under 150,000 characters (Claude's cap), so lists are paged with a
"next page" marker. A tool call must finish within 240 seconds; fleet_summary must finish
within 20 seconds for today's client count.

## 4. The safety nets

1. **Audit row per call.** Written with the existing record_audit_event helper, as role
   system_admin so it shows in Operator Console → Audit Log:
   ```
   action: mcp.tool_call   target_type: mcp_tool   target_id: lead_thread
   tenant_id: <AstroTamil>  metadata: {connection_id, arguments}
   ```
   One health-check question can write 5 to 10 rows, so the Audit Log page gets a "Show Claude
   reads" switch, off by default.
2. **Off switch per connection.** New table, one row per connection:
   ```
   mcp_connections: id, user_id, client_id, label, status (active / revoked),
                    created_at, last_used_at, revoked_at
   ```
   Row-level security on, no policies (only the backend's service key reads it).
3. **Read-only is tested, not promised.** One wrapper does login check, connection check and
   audit for every tool, so no tool can skip them. A test runs every tool against a fake
   database and fails if anything other than the audit row and the last-used stamp is written.
   A second test fails if a tool is registered that is not on the approved list.

## 5. Tech stack

- Backend: existing FastAPI app on Render, one new dependency: the official MCP Python SDK
  (package name mcp; research found 2.3.0 as latest stable, to be confirmed at install and
  pinned below the next major).
- Transport: Streamable HTTP, mounted in the existing app at /mcp, on the normal HTTPS port.
- Login: Supabase Auth as the sign-in server; the backend only verifies tokens.
- Frontend: two small Operator Console screens in the existing Next.js app (consent screen,
  Claude Access page), plus the Audit Log switch. Mockup: mcp-claude-access-mockup.html in the
  project root.

## 6. Commands

```bash
make dev-backend
```
```bash
cd backend && python -m pytest
```
```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```
```bash
npx @modelcontextprotocol/inspector --cli http://localhost:8000/mcp --transport http --method tools/list
```

Never plain uvicorn on a laptop (shared live database).

## 7. Project structure and code style

```
backend/app/mcp/server.py        → builds the MCP server, registers tools
backend/app/mcp/auth.py          → token check, system-admin check, connection check
backend/app/mcp/tools_fleet.py   → fleet tools
backend/app/mcp/tools_client.py  → one-client tools
backend/app/services/mcp_connections.py → connection rows (create, revoke, heartbeat)
backend/app/routes/operator_mcp.py      → Operator endpoints: list / revoke connection, the 3 NEW reads
backend/app/main.py              → mount at /mcp, start it in the existing lifespan
backend/supabase/migrations/     → one migration: mcp_connections
backend/tests/test_mcp_*.py      → tests
frontend/app/operator/(console)/claude-access/  → Claude Access page
frontend/app/operator/oauth/consent/            → consent screen
```

Style: same as the Operator routes (plain typed functions, one job each). Shape of a tool, to be
checked against the SDK docs at build time:

```python
@admin_tool(title="Client overview", source="Operator Console → client → Product Overview")
def client_overview(client: str) -> dict:
    """Totals for one client: leads, messages in the last 30 days, team size, last activity."""
    tenant_id = resolve_client(client)          # "AstroTamil" or an id → tenant id, else a clear error
    return operator.client_overview(tenant_id, _admin=current_admin())
```

The admin_tool wrapper is where the login check, the connection check, the read-only marker and
the audit row live.

## 8. Build order (thin slices, each one works on its own)

1. **Trial:** one tool (list_clients) reachable from the Claude app through the real sign-in.
   This proves or kills the login design before anything else is built.
2. Connection row, off switch, audit row, the read-only tests.
3. The tools that wrap existing reads.
4. The three NEW reads and fleet_summary.
5. Operator Console screens: Claude Access page and the Audit Log switch.

## 9. Testing

- pytest in backend/tests, same fake-database style as the existing test_operator_* files.
- Login: no token → 401; valid token of a non-admin → refused; revoked connection → refused.
- Read-only: the two tests in section 4.
- Parity: for each wrapper, the tool result equals the Operator function's result for the same
  client.
- NEW reads: tenant isolation (a lead id of another client returns not found).
- End to end, by hand: the two success messages from the phone, numbers compared with the
  Operator Console for two clients.

## 10. Boundaries

- **Always:** go through the admin_tool wrapper; name the source page in every answer; IST for
  "today"; page long lists; run the tests before any commit.
- **Ask first:** adding the mcp package; the migration; any Render env var; switching on the
  Supabase OAuth Server (Prem does this one himself); anything on the live site.
- **Never:** a tool that writes, sends or deletes; returning a key, token or password; a login
  token in a web address; push or deploy without Prem saying so; touching the scheduler.

## 11. Where the facts came from

- **Read in the code on 2026-11-17:** the system-admin check (dependencies/system_admin.py), the
  Operator read functions and their arguments (routes/operator.py, routes/operator_brain.py),
  the inbox's 20-conversation and 80-character limits, the audit helper, the Private Send
  hashed-key pattern, the existing lifespan in main.py, and that Client Configuration returns
  key status and not key values.
- **Reported by a docs search on 2026-11-17, not yet tried by us:** the Claude connector login
  options and limits, the Supabase OAuth Server behaviour, the MCP SDK version and mount code.
  Slice 1 exists to turn these into things we have seen work.

## 12. Open questions for Prem

1. ~~New leads today in fleet_summary.~~ Taken as recommended: added, labelled as a new figure.
2. **The AstroTamil Admin connector.** It already has "Claude Access → Connections". If its code
   is yours and on a machine I can read, pointing me at it would save the login trial some
   guesswork. Is it?
3. **Fallback check (30 seconds).** In the Claude app → Customize → Connectors → Add custom
   connector: is there a "Request headers" section? This tells us whether the fixed-key
   fallback is even possible.
4. ~~Audit noise.~~ Taken as recommended: rows stay in the Operator Audit Log behind a switch.

## 13. As built (2026-11-19): what differs from the sections above

1. **Folder name.** The code is in backend/app/admin_mcp/, not app/mcp/, so it cannot be confused
   with the installed package called mcp. New Operator reads are in routes/operator_leads.py and
   routes/operator_broadcasts.py; the Claude Access endpoints are in routes/operator_mcp.py.
2. **Tool name.** what_aira_saw became what_anril_saw (brand rule: the product is Anril).
3. **Read-only is enforced while a tool runs, not only tested.** While a tool runs, the database
   client refuses every insert, update, upsert, delete and unlisted RPC (app/db/supabase.py,
   read_only). Example: the Operator usage read resets a client's counters when its billing period
   has rolled over. Inside a tool that write is refused, so client_usage reads the period without
   resetting anything and says when a new period has started.
4. **Claude's token works only on the MCP.** The normal API always refuses any token that was
   issued to an OAuth client, whether MCP_ENABLED is on or off. Without this, the token the Claude
   app holds would also be a full Operator login, writes included; and turning the MCP off would
   have turned it into one.
5. **Who gets in.** A valid Supabase token, issued to an OAuth client, for a user in system_admins,
   with an active mcp_connections row for that user and client. The client must be the one in
   MCP_OAUTH_CLIENT_ID. That setting is required: left empty, the MCP does not start, nobody gets
   in, and the Allow button refuses every app.
6. **Recommended Supabase setup (changes section 2).** Keep dynamic client registration OFF. Add one
   OAuth client by hand for Claude and put its id in MCP_OAUTH_CLIENT_ID and in the Claude
   connector's "OAuth client ID" field. With dynamic registration on, any app could register itself
   as a client; it still could not read anything without the Allow click, but there is no reason
   to allow it.
7. **Switch off does two things.** It revokes our connection row (the next call is refused) and
   removes Claude's approval at Supabase (its refresh token dies). If the second step fails, the
   page says so and shows a Reset sign-in button.
8. **Today's figures.** fleet_summary counts new leads and messages from midnight in India. The
   Operator Console's own daily-messages page counts by UTC day and reads at most the default row
   limit, so client_messages (which wraps it) can differ from fleet_summary for the same day.
9. **Broadcast history** re-counts each broadcast the way the client's History tab does when it
   refreshes, without saving. It covers the client's last 50 broadcasts, like the client's page.
10. **open_requests** filters subscription requests on status "submitted" (the real value; the
    plan said "pending").


### Security review (2026-11-19, fixed before any commit)

A separate review of the finished build found these, all fixed and each with a test:

1. **Switching it on would have broken dashboard pages.** The MCP was attached at the root of the
   backend, which swallowed the "add the missing slash" redirect that pages like Numbers and
   Templates rely on (GET /api/v1/numbers answered 404 instead of 307). Now a gateway takes only
   /mcp and the sign-in document; every other address behaves exactly as before.
2. **Turning it off would have widened access.** See point 4 above.
3. **A look-alike app could have been approved.** See point 5 above. The consent screen also can
   no longer be shown inside another site's frame, and after consent the browser is only ever
   sent to an https address on claude.ai or claude.com.
4. **Audit rows lost the client** for most tools (the row said which tool, not which client).
   Fixed; and if the audit row cannot be written, the answer is withheld.
5. **The read-only guard had side doors** (file storage, user accounts, raw database access). No
   tool used them; they are now shut. Only table reads, one listed database function and user
   lookups pass.
6. **Limits added:** 120 requests a minute per address on /mcp, 3 tool calls at once, 90 seconds
   per call. Reads that used to hold up the whole backend now run in a worker thread.
7. **Audit rows keep less.** A phone number typed into find_lead is stored as its last 4 digits;
   long arguments are cut to 200 characters.
8. lead_thread returns 30 messages by default (50 full-length messages could exceed Claude's limit).

Still open, by design, to check during the trial:

- Claude's token is an ordinary signed-in Supabase token for the admin. Our backend refuses it
  everywhere except /mcp, but Supabase itself would accept it; what it could reach there is
  whatever row-level security allows that admin. Not tested yet.
- Chat messages and lead names are text written by strangers, and Claude reads them. Use a Claude
  project that has only this connector, so a message saying "send this somewhere" has nowhere to
  send it. The server's instructions tell Claude to treat that text as data.

Checked on the live database 2026-11-20: neither of the 2 system admins is a member of any client,
and the only row-level rules that mention system admins are 4 read rules. So used directly against
Supabase, Claude's token can read through those 4 rules and write nothing. This stays true only
while a system admin is never also added to a client as a team member.

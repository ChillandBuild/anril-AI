# Spec: Anril OTP (SMS + WhatsApp, with fallback)

Status: draft, waiting for Prem's review · 2026-11-14

## 1. What we are building

One OTP service inside Anril that any client can use to send login/verify codes to their customers
by SMS, WhatsApp, both, or SMS-then-WhatsApp. It works from the dashboard, from the client's own
app or website (through a new Anril OTP API), and from the Anril WhatsApp bot. Anril also uses it
for its own telecaller logins.

Everything goes out from the **client's own** Bulk9 SMS balance and **client's own** WhatsApp number.
Anril never pays for or sends from a shared account.

## 2. Delivery modes (client picks a default, can override per request)

| Mode | What happens |
|---|---|
| SMS only | Exactly today's Bulk9 Smart OTP. No change. |
| WhatsApp only | Code goes as a WhatsApp Authentication template (Copy code button). |
| SMS + WhatsApp | The **same** code goes on both at the same time. |
| SMS, then WhatsApp | SMS first. WhatsApp is sent only if the SMS fails (see 2.1). |

### 2.1 When does "SMS, then WhatsApp" switch to WhatsApp?
Any one of these, whichever comes first:
1. Bulk9 rejects the SMS straight away (error on send).
2. Bulk9's delivery report says failed.
3. The client's wait time passes (e.g. 30 s) with no "delivered" report.

WhatsApp backup is sent at most once per code. The **same** code is used.

### 2.2 "I didn't request a code" button (WhatsApp)
The WhatsApp message shows two things: the **Copy code** button and Meta's **"I didn't request a code"** button.

- Meta adds this button itself (beta, rolling out account by account). There is no field to switch it on
  when creating the template, so whether a client's messages show it depends on Meta, not Anril.
  The settings page says this plainly.
- When the customer taps it, Meta tells Anril (button reply `DID_NOT_REQUEST_CODE`). Anril then:
  1. **Cancels that code**: an Anril-made code can no longer be verified (verify answers `not_requested`).
  2. Marks it in OTP history: *"Customer said they didn't ask for this code"*, with a red tag.
  3. Sends a `not_requested` status update to the client's server (section 7). For client-made codes this is
     the only way the client learns of it, so their server must cancel the code itself.
  4. Counts it in a dashboard total ("Codes reported as not requested: 3 this week") so the client can spot abuse.
  5. Does **not** reply to the customer in chat and does **not** start the AI bot on that message.

## 3. Who makes the code

| Source | Who makes it | Who checks it | Example |
|---|---|---|---|
| Anril makes it | Anril | Anril (`/verify` call) | A new app with no OTP logic |
| Client's server makes it | Client's server | Client's server | Clinikally-style: sends us `009010`, we just deliver |

- Anril-made codes: Anril stores only a **hash** of the code (never the code itself), with expiry
  and a wrong-try counter. Wrong tries allowed is a client setting (1 to 10, default 5), then the code is dead.
- Client-made codes: Anril delivers and does not keep the code after sending (logs show it masked: `00••10`).
- SMS-only with Anril making the code keeps using Bulk9 Smart OTP as today.

## 4. Client settings (Settings → OTP, applied only on Save)

- Default delivery mode (section 2)
- Fallback wait time before WhatsApp: 10 s – 5 min (default 30 s)
- Max codes per number: per hour (default 5) — stops someone spamming a number
- Code expiry: 1 – 30 min (default 10)
- Code length: 4 – 8 digits (default 6)
- SMS template: dropdown of the client's approved DLT templates that have exactly one variable
  (e.g. Astro Tamil's #14892 "AstroTamil OTP: {#VAR#}…"); the code goes into that variable
- WhatsApp template: dropdown of the client's **approved Authentication templates** from Meta,
  or **Create new** → Anril submits a standard one (code, "do not share" line, expiry note,
  Copy code button) and shows *Waiting for approval → Ready*
- Status updates URL (section 7) + its signing secret
- The settings page warns calmly if a chosen mode can't work yet (no SMS balance / no WhatsApp number /
  no approved template) and that mode can't be saved until it's fixed.

## 5. Where it can be used

1. **Dashboard OTP page** — send a test/manual code in any mode, see history with per-channel status
   (SMS: sent/delivered/failed, WhatsApp: sent/delivered/read/failed, verified yes/no).
2. **Anril OTP API** — for the client's app or website (section 6).
3. *(Later, not built — owner 2026-11-14)* **Anril WhatsApp bot** — the bot can send a code to the person it is chatting with and check the
   code they type back (e.g. "verify your number before we book").
4. *(Later, not built — owner 2026-11-14)* **Anril's own telecaller login** (section 8).

## 6. Anril OTP API (for client servers)

- New **Anril OTP API key**, created on the Developer page. Shown once, stored as a hash, can be
  revoked/rotated. Owner only. Separate from the raw Bulk9 key shown today.
- Key goes in a header: `Authorization: Bearer anr_otp_live_…`. Server-to-server only (never in an app/browser).
- Calls (built 2026-11-14; full guide in docs/otp-api.md):
  - `POST /api/v1/otp/send` — `{phone, mode?, code?, ref?}`. Length and expiry come from settings.
    `code` present → client-made; absent → Anril makes it. Returns the request with per-channel status.
  - `POST /api/v1/otp/verify` — `{otp_id or phone, code}` → `{verified, reason, message, attempts_left}`. Anril-made only.
  - **No resend call:** Anril keeps only a hash, so it can't send the same code twice. Call send again;
    a new Anril code for a number cancels the previous open one. Counts toward the per-number limit.
  - `GET /api/v1/otp/{otp_id}` — current status (backup for when a status update was missed).
- Max 2 active keys per account (rotate without downtime).
- Errors: one clear list (bad key, number blocked by limit, no SMS balance, no WhatsApp template,
  expired, too many tries, wrong code…), each with a code and plain message.
- Rate limits on the key as well as per number.

## 7. Status updates to the client's server (push)

- Client sets a URL. Anril POSTs on every change, per channel: `sms_sent`, `sms_delivered`, `sms_failed`,
  `whatsapp_sent`, `whatsapp_delivered`, `whatsapp_read`, `whatsapp_failed`, `whatsapp_backup_sent`,
  `verified`, `locked`, `expired`, `failed` (every channel failed), `not_requested`.
- Body example: `{"otp_id":"…","ref":"…","phone":"+91…","sms":"failed","whatsapp":"delivered","event":"whatsapp_backup_sent","at":"…"}`.
  The code itself is **never** sent.
- Signed with HMAC-SHA256 (`X-Anril-Signature` header + timestamp) so the client can check it came from Anril.
- Retries with back-off on failure (e.g. 5 tries over ~1 hour), then dropped and marked in the dashboard.

## 8. Anril's own telecaller OTP — LATER, not built

Owner, 2026-11-14: not needed now. When a screen needs a code, add it there using the OTP service then.
Kept below as the agreed design.

Owner-controlled, three separate switches (Settings → Team, applied on Save):
1. **Verify number when adding a telecaller** — telecaller must enter a code sent to their phone before the account is active.
2. **Code on every login** (2-step) — password, then code.
3. **Login with code only** — no password.

Codes go through the owner's own SMS/WhatsApp using the owner's OTP settings. If the owner has no
working channel, the switches are disabled with a note saying why. Owner can never lock themselves out
(owner login is not affected by these switches).

## 9. Developer documentation (part of the build)

A proper guide for client developers, inside the Developer page and as a public doc:
- Setup: create key, pick mode, pick/create WhatsApp template, set status URL.
- Two walkthroughs: "Anril makes the code" and "My server makes the code".
- Every call with request/response examples, the full error list, status-update format and how to
  check the signature, rate limits.
- Sample code: cURL, Node.js, Python, PHP.

## 10. Not in this version

- Voice-call OTP, email OTP.
- WhatsApp One-tap / Zero-tap autofill (Android app hash needed) — Copy code only for now.
- Anril paying for messages from a shared account.
- Moving AstroTamil's existing direct-to-Bulk9 setup — it keeps working untouched.

## 11. Risks to check before building

1. **SMS with an Anril-made or client-made code.** For "SMS + WhatsApp" and "SMS, then WhatsApp" the
   SMS must carry *our* code. Bulk9's send-OTP docs (checked 2026-11-14) list an optional `otp` field
   ("Supply your own OTP value", max 10 characters). They also list `udf1`–`udf3`, which come back in the
   delivery webhook, so we can tag each SMS with our `otp_id`.
   **Live test 2026-11-14 (Astro Tamil account):**
   - Smart OTP with template #14892 → `Invalid OTP ID`. #14892 is the DLT template number, not the Smart OTP ID,
     and Bulk9 has no API that lists Smart OTP IDs. Nothing was sent.
   - Normal DLT SMS, sender ASTTML, template #14892, variable = `482913` → **Delivered in 1 second**, ₹0.13,
     and `udf1` came back in the delivery report.
   - **Decision:** when Anril or the client's server makes the code, the SMS goes as a normal DLT SMS using an
     OTP template the client picks from their approved DLT list (shown in a dropdown, no Smart OTP ID needed).
     Anril checks the code itself. Bulk9 Smart OTP stays only for the existing "SMS only, Bulk9 makes the code" flow.
2. **"I didn't request a code" is a Meta beta.** It may not appear for every client yet. Nothing breaks if
   it's missing.
3. Bulk9 delivery reports can arrive late; the wait timer covers this.
4. New API key, webhook signing and telecaller login are security-sensitive — built by the planner
   with the security checklist, never handed to workers.

## 12. Done means

- All four modes work end to end on a real number, from dashboard, API and bot.
- Fallback fires on each of the three triggers (2.1).
- Tapping "I didn't request a code" cancels the code, tags the history row and pushes `not_requested`.
- Limits, expiry and 5-wrong-tries lock all hold, tested.
- Status updates arrive signed and retry on failure.
- Telecaller switches each work and the owner can't be locked out.
- Developer docs let someone integrate without asking us.
- Backend tests pass; frontend lint + tsc pass; UI QA pass as the test tenant.

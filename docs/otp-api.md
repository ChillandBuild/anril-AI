# Anril OTP API

Send one-time codes (OTPs) to your customers by SMS or WhatsApp, and check the codes they type back. An OTP is a short, one-use number, like `482913`, that proves the person has the phone they say they have. Common uses are login, sign-up, order confirmation and payment confirmation.

Base URL: `https://ANRIL_API_BASE/api/v1/otp`. The exact base URL is shown on the dashboard's **SMS → OTP → API & docs** tab. Use that value, not this placeholder.

---

## What it does

Your server asks Anril to send a code to a phone number. The code goes out by SMS, WhatsApp, or both. Later, your server (or Anril) checks what the customer typed. Messages are sent from **your own** SMS balance (through Bulk9) and **your own** WhatsApp number.

There are four delivery modes. You pick one per request, or set a default in settings.

| Mode | What happens | When to use it |
|---|---|---|
| `sms` | Code goes by SMS only. | Simple setups, Indian numbers only. |
| `whatsapp` | Code goes by WhatsApp only. | Customers who read WhatsApp more than SMS. |
| `both` | The same code goes by SMS and WhatsApp at once. | You want the code to arrive as fast as possible, and do not mind two messages. |
| `sms_then_whatsapp` | SMS first. If SMS fails or is not confirmed as delivered in time, the same code goes by WhatsApp. | Best reach with the fewest duplicate messages. |

**Terms used in this guide**

- **SMS**: a text message to a phone number.
- **Bulk9**: the SMS provider Anril uses. Your SMS balance is held there.
- **WhatsApp template**: a message format that Meta (the company behind WhatsApp) must approve before a business can send it. Authentication templates are used for OTPs.
- **Webhook**: a message Anril sends to your server when something changes, such as "the code was delivered". Your server must have a public web address to receive it.
- **HMAC signature**: a fingerprint of a message, made with a secret key. It proves the message came from Anril and was not changed on the way.
- **Server-to-server**: your own backend talks to Anril. A customer's phone or browser never does.

---

## Before you start

Only the account **owner** can do steps 1 to 4.

**1. Connect your channels.** Connect SMS (Bulk9) and/or WhatsApp in Anril. You need at least one.

**2. Open OTP → Settings.** Set these:

- **SMS template**: pick your approved OTP template for SMS.
- **WhatsApp template**: pick an approved authentication template. If you do not have one, choose **Create new** and wait for Meta to approve it. This can take some time.
- **Default mode**: the mode used when a request does not send `mode`.
- **Rules**: code length (4 to 8 digits, default 6), expiry (1 to 30 minutes, default 10), the per-number limit (default 5 codes per hour), and the wait time before a WhatsApp backup (10 to 300 seconds, default 30).
- Click **Save**.

**3. Create an API key.** On **API & docs**, click **Create key**. Copy it and store it on your server, for example in an environment variable. Anril shows the full key **once**. After that, Anril keeps only a fingerprint (a hash), so a lost key cannot be recovered. Create a new one and revoke the old one.

**4. (Optional) Set up status updates.** On **OTP → Settings**, enter an `https://` URL under **Status updates to your server**, then create the signing secret. The secret starts with `whsec_` and is also shown once. See [Status updates](#status-updates-webhooks).

---

## Two ways to use it

Pick one per flow. Both work with every mode.

### Option A: Anril makes the code

Use this when you want Anril to create the code, store only its hash, and check it for you.

1. Your server calls `POST /send` **without** a `code`.
2. Anril makes the code (length from settings), sends it, and returns an `otp_id`.
3. The customer types the code into your app.
4. Your server calls `POST /verify` with the `otp_id` and the typed code.
5. Anril answers `verified: true` or `verified: false`, with a reason.

Rules that apply to Option A:

- Wrong tries are limited (you set the number in OTP settings: 1 to 10, default 5). After that the code is **locked**.
- A code expires after the time set in settings (1 to 30 minutes).
- Sending a new code to the same number cancels the previous open code.

### Option B: Your server makes the code

Use this when your own system must own the code, for example because you store it with an order.

1. Your server makes the code (4 to 10 letters or digits).
2. Your server calls `POST /send` **with** `code`.
3. Anril only delivers the code. It keeps a masked copy (for example `00••10`), never the full code.
4. The customer types the code into your app.
5. **Your server** compares the typed code with its own copy. Anril's `/verify` answers `409 not_checkable` for these codes, so do not call it.
6. Listen for the `not_requested` status update. If the customer taps "I didn't request a code", cancel the code on your side too.

---

## Endpoint reference

All requests need the header `Authorization: Bearer anr_otp_live_...` and `Content-Type: application/json`.

### `POST /send`

Send a code.

**Request body**

```json
{
  "phone": "+919876543210",
  "mode": "sms_then_whatsapp",
  "code": "482913",
  "ref": "order-123"
}
```

| Field | Required | Notes |
|---|---|---|
| `phone` | yes | With country code, like `+919876543210`. A bare 10-digit number is taken as Indian. |
| `mode` | no | `sms`, `whatsapp`, `both` or `sms_then_whatsapp`. Omit to use the account default. |
| `code` | no | Leave out for Option A. For Option B, 4 to 10 letters or digits. |
| `ref` | no | Your own id, up to 100 characters. It is sent back in status updates. |

Unknown fields are rejected with `422`.

**Response `200`**

```json
{
  "otp_id": "8f0c...",
  "phone": "+919876543210",
  "mode": "sms_then_whatsapp",
  "source": "anril",
  "status": "pending",
  "ref": "order-123",
  "expires_at": "2026-11-14T10:10:00+00:00",
  "verified_at": null,
  "sms": { "status": "sent", "error": null },
  "whatsapp": { "status": "none", "error": null },
  "whatsapp_backup_sent": false,
  "not_requested": false,
  "created_at": "2026-11-14T10:00:00+00:00"
}
```

Notes:

- `source` is `anril` for codes Anril made (Option A).
- `sms` mode to a non-Indian number is refused with `400 sms_india_only`. In `both` and `sms_then_whatsapp`, the SMS part is marked `failed` and WhatsApp still goes out.
- Keep `otp_id`. You need it to verify and to match status updates.

### `POST /verify`

Check a code the customer typed (Option A only).

**Request body**

```json
{ "otp_id": "8f0c...", "code": "482913" }
```

You can send `"phone"` instead of `otp_id`. Anril then checks the newest Anril-made code for that number from the last 24 hours. Prefer `otp_id`, because it is exact.

**Response `200`, correct code**

```json
{ "verified": true, "reason": null, "message": null, "attempts_left": 0, "otp_id": "8f0c..." }
```

**Response `200`, wrong code**

```json
{ "verified": false, "reason": "wrong_code", "message": "Wrong code", "attempts_left": 4, "otp_id": "8f0c..." }
```

A wrong code is still HTTP `200` with `verified: false`. Only bad requests and bad keys return `4xx`. Always read `verified` and `reason`.

**Possible `reason` values**

| Reason | Meaning |
|---|---|
| `wrong_code` | The code does not match. `attempts_left` shows how many tries remain. |
| `locked` | Too many wrong tries. Send a new code. |
| `expired` | The code is past its expiry time. Send a new code. |
| `already_verified` | This code was already used. |
| `not_requested` | The customer tapped "I didn't request a code". |
| `failed` | The code was never delivered on any channel. |
| `not_found` | No such code. |

### `GET /{otp_id}`

Return the current state of one code. It has the same shape as the `/send` response. Use it if you missed a status update.

```text
GET https://ANRIL_API_BASE/api/v1/otp/8f0c...
```

---

## Status values

**Request `status`** (the whole code)

| Value | Meaning |
|---|---|
| `pending` | Sent, waiting for the customer. |
| `verified` | The customer typed the right code. |
| `expired` | Past its expiry time. |
| `locked` | Too many wrong tries. |
| `not_requested` | The customer said they did not ask for it. |
| `failed` | Every channel failed. |

**`sms.status`**: `none`, `sent`, `delivered`, `failed`.

**`whatsapp.status`**: `none`, `sent`, `delivered`, `read`, `failed`.

`none` means that channel was not used for this code.

---

## Errors

Every error has the same JSON shape:

```json
{ "error": "Plain message for people", "code": "machine_code" }
```

Check `code` in your code. `error` is for logs and humans, and its wording may change.

| HTTP | `code` | What it means and what to do |
|---|---|---|
| 401 | `invalid_key` | The key is missing or wrong. Check the header. |
| 401 | `revoked_key` | The key was revoked. Use another key or create one. |
| 400 | `invalid_phone` | The number is not valid. Include the country code. |
| 400 | `invalid_mode` | `mode` is not one of the four values. |
| 400 | `invalid_code` | Your `code` is not 4 to 10 letters or digits. |
| 400 | `sms_india_only` | `sms` mode was used for a non-Indian number. Use `whatsapp` or `both`. |
| 400 | `missing_target` | `/verify` needs `otp_id` or `phone`. |
| 404 | `not_found` | No code with that `otp_id`. |
| 409 | `channel_not_ready` | The channel is not set up. The message says what is missing, such as no WhatsApp template chosen or SMS not connected. |
| 409 | `not_checkable` | You called `/verify` for a code your server made (Option B). Check it on your side. |
| 422 | (validation) | The body has an unknown or badly typed field. |
| 429 | `too_many_codes` | The per-number limit was hit. Read `Retry-After` (3600 seconds). Wait before sending again. |
| 429 | `rate_limited` | Too many requests. Read `Retry-After` (60 seconds) and slow down. |
| 503 | `not_configured` | OTP is not configured for this account. Finish the setup steps above. |

---

## Status updates (webhooks)

Anril can POST a JSON message to your server each time a code changes state. You do not have to poll `GET /{otp_id}`.

**Set it up:** On **OTP → Settings**, enter a public `https://` URL under **Status updates to your server**. Create the signing secret. Anril shows it once. Save it as an environment variable. The URL must be public HTTPS. Anril does **not** follow redirects.

**Events**

`sms_sent`, `sms_delivered`, `sms_failed`, `whatsapp_sent`, `whatsapp_delivered`, `whatsapp_read`, `whatsapp_failed`, `whatsapp_backup_sent`, `verified`, `locked`, `expired`, `failed` (every channel failed), `not_requested`, and `test` (sent by the **Send test update** button on the dashboard).

**The code is never included.**

**Example body**

```json
{
  "id": "evt_3f9a...",
  "event": "whatsapp_backup_sent",
  "at": "2026-11-14T10:00:31+00:00",
  "otp_id": "8f0c...",
  "ref": "order-123",
  "phone": "+919876543210",
  "mode": "sms_then_whatsapp",
  "source": "anril",
  "status": "pending",
  "sms": "failed",
  "whatsapp": "sent",
  "whatsapp_backup_sent": true
}
```

**Headers**

| Header | Value |
|---|---|
| `X-Anril-Event` | The event name, such as `verified`. |
| `X-Anril-Delivery` | The same as the body `id`. Use it to ignore duplicates. |
| `X-Anril-Timestamp` | Unix time in seconds, when the message was sent. |
| `X-Anril-Signature` | `v1=<hex>`, the signature (see below). |

**Check the signature**

1. Read the timestamp from `X-Anril-Timestamp`. Reject it if it is more than 5 minutes away from your clock. This stops replayed messages.
2. Build the signed text: the timestamp, a dot, then the **raw body bytes exactly as received**. Do not parse and re-serialise the JSON first.
3. Compute HMAC-SHA256 of that text, using the whole `whsec_...` secret as the key. Write the result as lowercase hex, and prefix it with `v1=`.
4. Compare it with `X-Anril-Signature` using a **constant-time** comparison (`timingSafeEqual`, `hmac.compare_digest` or `hash_equals`). Reject the message if they differ.
5. Ignore a `X-Anril-Delivery` you have already handled.

Sample code for these steps is in [Sample code](#sample-code).

**Answer fast.** Return any `2xx` status within **10 seconds**. Do the real work after you reply, or put it on a queue.

**Retries.** If your server does not return `2xx`, Anril retries after 1, 5, 15 and 30 minutes. That is 5 tries in total. After that it gives up and shows the failed delivery on the dashboard.

---

## "I didn't request a code"

WhatsApp authentication messages have a **Copy code** button. For some accounts, Meta (in beta) also adds an **I didn't request a code** button.

If the customer taps it:

- Anril cancels that code. A later `/verify` answers `reason: "not_requested"`.
- Anril sends your server a `not_requested` status update.
- If **your** server made the code (Option B), cancel it on your side too.

---

## Limits

| Limit | Value |
|---|---|
| Active API keys per account | 2 (create a second one to rotate with no downtime) |
| Requests per key or per IP | 120 a minute (429 `rate_limited`, `Retry-After: 60`) |
| `/verify` requests per key | 60 a minute |
| Codes per phone number | 5 an hour by default, changeable in settings (429 `too_many_codes`, `Retry-After: 3600`) |
| Wrong tries per code | Set in OTP settings: 1 to 10, default 5. Then the code locks. |
| Code length (Option A) | 4 to 8 digits, default 6 |
| Code length (Option B) | 4 to 10 letters or digits |
| Code expiry | 1 to 30 minutes, default 10 |
| WhatsApp backup wait | 10 to 300 seconds, default 30 |
| `ref` length | 100 characters |
| Status update retries | 5 tries in total (at 1, 5, 15 and 30 minutes) |
| Status update response time | 2xx within 10 seconds |

---

## Security tips

- **Keep the key on your server only.** Never put it in a mobile app, a browser script or a website's front end. Anyone with the key can send codes from your SMS balance and WhatsApp number.
- **Rotate with two keys.** Create the new key, deploy it, then revoke the old one. Revoked keys stop working straight away.
- **Never log codes.** Log `otp_id`, `ref` and `reason`, not the code. For Option B, store your copy hashed, with its expiry time.
- **Verify every status update's signature** before you trust it.
- **Use HTTPS** for your status URL. Anril will not send to plain HTTP.
- **Rate-limit your own "send" endpoint** per user, so an attacker cannot use your form to spam someone's phone.

---

## Sample code

Each sample reads the key and secret from environment variables. Set them first:

```bash
export ANRIL_API_URL="https://ANRIL_API_BASE"    # copy the exact value from the API & docs tab
export ANRIL_OTP_KEY="anr_otp_live_..."          # your secret key
export ANRIL_WEBHOOK_SECRET="whsec_..."          # only for the webhook samples
```

### cURL

Send a code (Option A):

```bash
curl -sS -X POST "$ANRIL_API_URL/api/v1/otp/send" \
  -H "Authorization: Bearer $ANRIL_OTP_KEY" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+919876543210","mode":"sms_then_whatsapp","ref":"order-123"}'
```

Check the typed code (Option A):

```bash
curl -sS -X POST "$ANRIL_API_URL/api/v1/otp/verify" \
  -H "Authorization: Bearer $ANRIL_OTP_KEY" \
  -H "Content-Type: application/json" \
  -d '{"otp_id":"PASTE_OTP_ID_HERE","code":"482913"}'
```

### Node.js (18 or newer)

Save as `otp.mjs` and run `node otp.mjs`. It uses the built-in `fetch`.

```js
// otp.mjs
const BASE = process.env.ANRIL_API_URL;
const KEY = process.env.ANRIL_OTP_KEY;

async function anril(path, body) {
  const res = await fetch(`${BASE}/api/v1/otp${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(`${data.code}: ${data.error}`);
  return data;
}

// Option A: Anril makes the code and sends it.
const sent = await anril("/send", { phone: "+919876543210", mode: "sms_then_whatsapp", ref: "order-123" });
console.log("otp_id:", sent.otp_id);

// Later, when the customer has typed the code:
const check = await anril("/verify", { otp_id: sent.otp_id, code: "482913" });
console.log(check.verified ? "Correct" : `Not verified: ${check.reason}`);
```

Webhook receiver with Express and a signature check. Save as `webhook.mjs`, run `npm install express`, then `node webhook.mjs`.

```js
// webhook.mjs
import crypto from "node:crypto";
import express from "express";

const WEBHOOK_SECRET = process.env.ANRIL_WEBHOOK_SECRET; // the whole whsec_... string
const processed = new Set(); // in production, store delivery ids in a database table

const app = express();

// Use express.raw for this route. It keeps the exact bytes Anril signed.
// Put this route before any express.json() middleware, or the raw body is lost.
app.post("/anril/webhook", express.raw({ type: "application/json" }), (req, res) => {
  const timestamp = req.get("X-Anril-Timestamp") ?? "";
  const signature = req.get("X-Anril-Signature") ?? "";
  const delivery = req.get("X-Anril-Delivery") ?? "";
  const body = req.body; // a Buffer of the raw bytes

  // 1. Reject old or malformed timestamps (more than 5 minutes away).
  const age = Math.abs(Date.now() / 1000 - Number(timestamp));
  if (!/^\d+$/.test(timestamp) || age > 300) return res.sendStatus(400);

  // 2. Recompute the signature over "timestamp." + raw body.
  const expected = "v1=" + crypto
    .createHmac("sha256", WEBHOOK_SECRET)
    .update(`${timestamp}.`)
    .update(body)
    .digest("hex");

  // 3. Constant-time compare. timingSafeEqual needs equal lengths, so check those first.
  const given = Buffer.from(signature);
  const want = Buffer.from(expected);
  if (given.length !== want.length || !crypto.timingSafeEqual(given, want)) {
    return res.sendStatus(401);
  }

  // 4. Ignore duplicates, then handle the event. Reply 2xx quickly (within 10 seconds).
  if (!processed.has(delivery)) {
    processed.add(delivery);
    const event = JSON.parse(body.toString("utf8"));
    console.log(event.event, event.ref, event.status);
  }
  return res.sendStatus(200);
});

app.listen(3000, () => console.log("Listening on port 3000"));
```

### Python (requests and Flask)

Send and check (Option A). Save as `otp.py`, run `pip install requests` and `python otp.py`.

```python
# otp.py
import os
import requests

BASE = os.environ["ANRIL_API_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['ANRIL_OTP_KEY']}"}


def anril(path, body):
    r = requests.post(f"{BASE}/api/v1/otp{path}", json=body, headers=HEADERS, timeout=15)
    data = r.json()
    if not r.ok:
        raise RuntimeError(f"{data.get('code')}: {data.get('error')}")
    return data


# Option A: Anril makes the code and sends it.
sent = anril("/send", {"phone": "+919876543210", "mode": "sms_then_whatsapp", "ref": "order-123"})
print("otp_id:", sent["otp_id"])

# Later, when the customer has typed the code:
check = anril("/verify", {"otp_id": sent["otp_id"], "code": "482913"})
print("Correct" if check["verified"] else f"Not verified: {check['reason']}")
```

Webhook receiver with Flask and a signature check. Save as `webhook.py`, run `pip install flask`, then `python webhook.py`.

```python
# webhook.py
import hashlib
import hmac
import json
import os
import time

from flask import Flask, abort, request

WEBHOOK_SECRET = os.environ["ANRIL_WEBHOOK_SECRET"].encode()  # the whole whsec_... string
processed = set()  # in production, store delivery ids in a database table

app = Flask(__name__)


@app.post("/anril/webhook")
def anril_webhook():
    raw = request.get_data()  # the exact bytes Anril signed, before any JSON parsing
    timestamp = request.headers.get("X-Anril-Timestamp", "")
    signature = request.headers.get("X-Anril-Signature", "")
    delivery = request.headers.get("X-Anril-Delivery", "")

    # 1. Reject old or malformed timestamps (more than 5 minutes away).
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
        abort(400)

    # 2. Recompute the signature over "timestamp." + raw body.
    signed = f"{timestamp}.".encode() + raw
    expected = "v1=" + hmac.new(WEBHOOK_SECRET, signed, hashlib.sha256).hexdigest()

    # 3. Constant-time compare.
    if not hmac.compare_digest(signature.encode(), expected.encode()):
        abort(401)

    # 4. Ignore duplicates, then handle the event. Reply 2xx quickly (within 10 seconds).
    if delivery not in processed:
        processed.add(delivery)
        event = json.loads(raw)
        print(event["event"], event.get("ref"), event.get("status"))
    return "", 200


if __name__ == "__main__":
    app.run(port=3000)
```

### PHP (cURL and hash_hmac)

Send and check (Option A). Save as `otp.php`, run `php otp.php`. Needs the PHP cURL extension.

```php
<?php
// otp.php
$base = getenv('ANRIL_API_URL');
$key  = getenv('ANRIL_OTP_KEY');

function anril_post(string $url, string $key, array $body): array
{
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => json_encode($body),
        CURLOPT_HTTPHEADER     => ['Authorization: Bearer ' . $key, 'Content-Type: application/json'],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 15,
    ]);
    $raw = curl_exec($ch);
    if ($raw === false) {
        $err = curl_error($ch);
        throw new RuntimeException('Network error: ' . $err);
    }
    $status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $data = json_decode($raw, true) ?? [];
    if ($status >= 400) {
        throw new RuntimeException(($data['code'] ?? 'error') . ': ' . ($data['error'] ?? 'request failed'));
    }
    return $data;
}

// Option A: Anril makes the code and sends it.
$sent = anril_post("$base/api/v1/otp/send", $key, [
    'phone' => '+919876543210',
    'mode'  => 'sms_then_whatsapp',
    'ref'   => 'order-123',
]);
echo 'otp_id: ' . $sent['otp_id'] . PHP_EOL;

// Later, when the customer has typed the code:
$check = anril_post("$base/api/v1/otp/verify", $key, [
    'otp_id' => $sent['otp_id'],
    'code'   => '482913',
]);
echo $check['verified'] ? "Correct\n" : 'Not verified: ' . $check['reason'] . "\n";
```

Webhook receiver. Save as `webhook.php` on a server with HTTPS, and set its URL as your status URL.

```php
<?php
// webhook.php
$secret    = getenv('ANRIL_WEBHOOK_SECRET'); // the whole whsec_... string
$raw       = file_get_contents('php://input'); // the exact bytes Anril signed
$timestamp = $_SERVER['HTTP_X_ANRIL_TIMESTAMP'] ?? '';
$signature = $_SERVER['HTTP_X_ANRIL_SIGNATURE'] ?? '';
$delivery  = $_SERVER['HTTP_X_ANRIL_DELIVERY'] ?? '';

// 1. Reject old or malformed timestamps (more than 5 minutes away).
if (!ctype_digit($timestamp) || abs(time() - (int) $timestamp) > 300) {
    http_response_code(400);
    exit;
}

// 2. Recompute the signature over "timestamp." + raw body.
$expected = 'v1=' . hash_hmac('sha256', $timestamp . '.' . $raw, $secret);

// 3. Constant-time compare.
if (!hash_equals($expected, $signature)) {
    http_response_code(401);
    exit;
}

// 4. Handle the event. Ignore duplicates with a database table of delivery ids in production.
$event = json_decode($raw, true);
error_log('Anril ' . ($event['event'] ?? '?') . ' ref=' . ($event['ref'] ?? '-') . ' delivery=' . $delivery);
http_response_code(200);
```

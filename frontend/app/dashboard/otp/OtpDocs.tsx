"use client";

import { useState, type ReactNode } from "react";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { Btn, Card, CardHeader, Notice, TableWrap, tdCls, thCls } from "../sms/ui";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://YOUR-ANRIL-API";
const OTP_BASE = `${API_BASE}/api/v1/otp`;

type Lang = "curl" | "node" | "python" | "php";

const LANGS: { id: Lang; label: string }[] = [
  { id: "curl", label: "cURL" },
  { id: "node", label: "Node.js" },
  { id: "python", label: "Python" },
  { id: "php", label: "PHP" },
];

// Snippets are plain strings (String.raw), so the code is copied exactly as written.
// They read the base URL and keys from environment variables, not from this page.

const ENV_SETUP = `export ANRIL_API_URL="${API_BASE}"    # Anril's API address
export ANRIL_OTP_KEY="anr_otp_live_..."          # your secret key
export ANRIL_WEBHOOK_SECRET="whsec_..."          # only for the webhook samples`;

const SAMPLE_SEND: Record<Lang, string> = {
  curl: String.raw`curl -sS -X POST "$ANRIL_API_URL/api/v1/otp/send" \
  -H "Authorization: Bearer $ANRIL_OTP_KEY" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+919876543210","mode":"sms_then_whatsapp","ref":"order-123"}'

curl -sS -X POST "$ANRIL_API_URL/api/v1/otp/verify" \
  -H "Authorization: Bearer $ANRIL_OTP_KEY" \
  -H "Content-Type: application/json" \
  -d '{"otp_id":"PASTE_OTP_ID_HERE","code":"482913"}'`,
  node: String.raw`// otp.mjs
const BASE = process.env.ANRIL_API_URL;
const KEY = process.env.ANRIL_OTP_KEY;

async function anril(path, body) {
  const res = await fetch(BASE + "/api/v1/otp" + path, {
    method: "POST",
    headers: { Authorization: "Bearer " + KEY, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.code + ": " + data.error);
  return data;
}

// Option A: Anril makes the code and sends it.
const sent = await anril("/send", { phone: "+919876543210", mode: "sms_then_whatsapp", ref: "order-123" });
console.log("otp_id:", sent.otp_id);

// Later, when the customer has typed the code:
const check = await anril("/verify", { otp_id: sent.otp_id, code: "482913" });
console.log(check.verified ? "Correct" : "Not verified: " + check.reason);`,
  python: String.raw`# otp.py
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
print("Correct" if check["verified"] else f"Not verified: {check['reason']}")`,
  php: String.raw`<?php
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
echo $check['verified'] ? "Correct\n" : 'Not verified: ' . $check['reason'] . "\n";`,
};

const SAMPLE_WEBHOOK: Record<Exclude<Lang, "curl">, string> = {
  node: String.raw`// webhook.mjs  (npm install express)
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
    .update(timestamp + ".")
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

app.listen(3000, () => console.log("Listening on port 3000"));`,
  python: String.raw`# webhook.py  (pip install flask)
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
    app.run(port=3000)`,
  php: String.raw`<?php
// webhook.php  (serve over HTTPS and use its URL as your status URL)
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

// 4. Handle the event. In production, ignore duplicates using a table of delivery ids.
$event = json_decode($raw, true);
error_log('Anril ' . ($event['event'] ?? '?') . ' ref=' . ($event['ref'] ?? '-') . ' delivery=' . $delivery);
http_response_code(200);`,
};

const SEND_BODY = String.raw`{
  "phone": "+919876543210",
  "mode": "sms_then_whatsapp",
  "code": "482913",
  "ref": "order-123"
}`;

const SEND_RESPONSE = String.raw`{
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
}`;

const VERIFY_BODY = String.raw`{ "otp_id": "8f0c...", "code": "482913" }`;

const VERIFY_OK = String.raw`{ "verified": true, "reason": null, "message": null, "attempts_left": 0, "otp_id": "8f0c..." }`;

const VERIFY_WRONG = String.raw`{ "verified": false, "reason": "wrong_code", "message": "Wrong code", "attempts_left": 4, "otp_id": "8f0c..." }`;

const WEBHOOK_BODY = String.raw`{
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
}`;

const GET_EXAMPLE = `GET ${OTP_BASE}/8f0c...`;

function Code({ children }: { children: ReactNode }) {
  return <code className="rounded bg-[#f1f5f9] px-1 py-0.5 font-mono text-[12px] text-[#0A1528] break-all">{children}</code>;
}

function Lead({ children }: { children: ReactNode }) {
  return <p className="text-sm leading-relaxed text-[#334155]">{children}</p>;
}

function List({ children }: { children: ReactNode }) {
  return <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-[#334155]">{children}</ul>;
}

function Steps({ children }: { children: ReactNode }) {
  return <ol className="list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-[#334155]">{children}</ol>;
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader title={title} hint={hint} />
      <div className="space-y-4 p-4 sm:p-5">{children}</div>
    </Card>
  );
}

function SubHead({ children }: { children: ReactNode }) {
  return <h3 className="pt-1 text-sm font-bold text-[#0A1528]">{children}</h3>;
}

function CodeBlock({ code, label }: { code: string; label: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy. Select the code and copy it by hand.");
    }
  }

  return (
    <div className="min-w-0">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[11px] font-bold uppercase tracking-wider text-[#64748b]">{label}</span>
        <Btn variant="outline" className="h-8 px-2.5 text-xs" onClick={() => void copy()} aria-label={`Copy ${label}`}>
          <Copy size={12} /> {copied ? "Copied" : "Copy"}
        </Btn>
      </div>
      <pre className="overflow-x-auto rounded-xl bg-[#0A1528] p-4 text-xs text-[#e2e8f0]">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function EndpointHead({ method, path, what }: { method: string; path: string; what: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="rounded-md bg-primary/10 px-2 py-0.5 font-mono text-[11px] font-bold text-primary">{method}</span>
      <code className="break-all font-mono text-sm font-bold text-[#0A1528]">{path}</code>
      <span className="text-sm text-[#64748b]">{what}</span>
    </div>
  );
}

function SampleCode() {
  const [lang, setLang] = useState<Lang>("curl");
  const webhook = lang === "curl" ? null : SAMPLE_WEBHOOK[lang];

  return (
    <>
      <Lead>
        Each sample reads the base URL and keys from environment variables. Set them once, then run the sample.
      </Lead>
      <CodeBlock code={ENV_SETUP} label="Environment variables" />

      <div role="tablist" aria-label="Language" className="flex flex-wrap gap-2">
        {LANGS.map((l) => (
          <Btn
            key={l.id}
            role="tab"
            aria-selected={lang === l.id}
            variant={lang === l.id ? "primary" : "outline"}
            className="h-9"
            onClick={() => setLang(l.id)}
          >
            {l.label}
          </Btn>
        ))}
      </div>

      <SubHead>Send a code and check it (Option A)</SubHead>
      <CodeBlock code={SAMPLE_SEND[lang]} label={`${LANGS.find((l) => l.id === lang)?.label ?? ""} send and verify`} />

      <SubHead>Receive status updates (webhook) with a signature check</SubHead>
      {webhook ? (
        <CodeBlock code={webhook} label={`${LANGS.find((l) => l.id === lang)?.label ?? ""} webhook`} />
      ) : (
        <Notice tone="info">cURL can only send requests. For the webhook receiver, pick Node.js, Python or PHP above.</Notice>
      )}
    </>
  );
}

export function OtpDocs() {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Anril OTP API" hint="Send one-time codes by SMS or WhatsApp, and check the codes your customers type back." />
        <div className="space-y-3 p-4 sm:p-5">
          <Lead>
            An OTP is a short, one-use number, like <Code>482913</Code>, that proves the person has the phone they say they have. Common uses are login, sign-up, order confirmation and payment confirmation.
          </Lead>
          <Lead>
            Base URL: <Code>{OTP_BASE}</Code>.
          </Lead>
        </div>
      </Card>

      <Section title="What it does" hint="Your server asks Anril to send a code. Later, your server (or Anril) checks what the customer typed.">
        <Lead>
          Messages are sent from <strong>your own</strong> SMS balance (through Bulk9) and <strong>your own</strong> WhatsApp number. Pick one of four delivery modes per request, or set a default in settings.
        </Lead>
        <TableWrap>
          <table className="min-w-full">
            <thead className="border-b border-[#e2e8f0] bg-[#f8fafc]">
              <tr>
                <th className={thCls}>Mode</th>
                <th className={thCls}>What happens</th>
                <th className={thCls}>When to use it</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0]">
              <tr>
                <td className={tdCls}><Code>sms</Code></td>
                <td className={tdCls}>Code goes by SMS only.</td>
                <td className={tdCls}>Simple setups. Indian numbers only.</td>
              </tr>
              <tr>
                <td className={tdCls}><Code>whatsapp</Code></td>
                <td className={tdCls}>Code goes by WhatsApp only.</td>
                <td className={tdCls}>Customers who read WhatsApp more than SMS.</td>
              </tr>
              <tr>
                <td className={tdCls}><Code>both</Code></td>
                <td className={tdCls}>The same code goes by SMS and WhatsApp at once.</td>
                <td className={tdCls}>The fastest arrival. Two messages are sent.</td>
              </tr>
              <tr>
                <td className={tdCls}><Code>sms_then_whatsapp</Code></td>
                <td className={tdCls}>SMS first. If SMS fails or is not confirmed as delivered in time, the same code goes by WhatsApp.</td>
                <td className={tdCls}>Best reach with the fewest duplicate messages.</td>
              </tr>
            </tbody>
          </table>
        </TableWrap>
        <SubHead>Terms used in this guide</SubHead>
        <List>
          <li><strong>SMS:</strong> a text message to a phone number.</li>
          <li><strong>Bulk9:</strong> the SMS provider Anril uses. Your SMS balance is held there.</li>
          <li><strong>WhatsApp template:</strong> a message format that Meta (the company behind WhatsApp) must approve before a business can send it. OTPs use authentication templates.</li>
          <li><strong>Webhook:</strong> a message Anril sends to your server when something changes, such as &quot;the code was delivered&quot;. Your server needs a public web address to receive it.</li>
          <li><strong>HMAC signature:</strong> a fingerprint of a message, made with a secret key. It proves the message came from Anril and was not changed.</li>
          <li><strong>Server-to-server:</strong> your own backend talks to Anril. A customer&apos;s phone or browser never does.</li>
        </List>
      </Section>

      <Section title="Before you start" hint="Only the account owner can do steps 1 to 4.">
        <Steps>
          <li><strong>Connect your channels.</strong> Connect SMS (Bulk9) and/or WhatsApp in Anril. You need at least one.</li>
          <li>
            <strong>Open OTP → Settings.</strong> Pick an SMS template and a WhatsApp template (an approved authentication template, or choose <strong>Create new</strong> and wait for Meta to approve it). Set the default mode and the rules: code length (4 to 8 digits, default 6), expiry (1 to 30 minutes, default 10), the per-number limit (default 5 codes an hour), and the WhatsApp backup wait (10 to 300 seconds, default 30). Click <strong>Save</strong>.
          </li>
          <li>
            <strong>Create an API key.</strong> On <strong>API &amp; docs</strong>, click <strong>Create key</strong>. Copy it and store it on your server, for example in an environment variable. Anril shows the full key <strong>once</strong> and keeps only a fingerprint, so a lost key cannot be recovered. Create a new one and revoke the old one.
          </li>
          <li>
            <strong>(Optional) Set up status updates.</strong> Under <strong>Status updates to your server</strong> in settings, enter an <Code>https://</Code> URL, then create the signing secret. It starts with <Code>whsec_</Code> and is also shown once.
          </li>
        </Steps>
      </Section>

      <Section title="Two ways to use it" hint="Pick one per flow. Both work with every mode.">
        <SubHead>Option A: Anril makes the code</SubHead>
        <Lead>Use this when you want Anril to create the code, keep only its hash, and check it for you.</Lead>
        <Steps>
          <li>Your server calls <Code>POST /send</Code> without a <Code>code</Code>.</li>
          <li>Anril makes the code (length from settings), sends it, and returns an <Code>otp_id</Code>.</li>
          <li>The customer types the code into your app.</li>
          <li>Your server calls <Code>POST /verify</Code> with the <Code>otp_id</Code> and the typed code.</li>
          <li>Anril answers <Code>verified: true</Code> or <Code>verified: false</Code>, with a reason.</li>
        </Steps>
        <List>
          <li>Wrong tries are limited (you set the number in OTP settings: 1 to 10, default 5). After that the code is <strong>locked</strong>.</li>
          <li>A code expires after the time set in settings (1 to 30 minutes).</li>
          <li>Sending a new code to the same number cancels the previous open code.</li>
        </List>

        <SubHead>Option B: Your server makes the code</SubHead>
        <Lead>Use this when your own system must own the code, for example because you store it with an order.</Lead>
        <Steps>
          <li>Your server makes the code (4 to 10 letters or digits).</li>
          <li>Your server calls <Code>POST /send</Code> <strong>with</strong> the <Code>code</Code>.</li>
          <li>Anril only delivers the code. It keeps a masked copy (for example <Code>00••10</Code>), never the full code.</li>
          <li>The customer types the code into your app.</li>
          <li><strong>Your server</strong> compares the typed code with its own copy. Anril&apos;s <Code>/verify</Code> answers <Code>409 not_checkable</Code> for these codes, so do not call it.</li>
          <li>Listen for the <Code>not_requested</Code> status update. If the customer taps &quot;I didn&apos;t request a code&quot;, cancel the code on your side too.</li>
        </Steps>
      </Section>

      <Section title="Endpoints" hint="All requests need Authorization: Bearer anr_otp_live_... and Content-Type: application/json.">
        <div className="space-y-3">
          <EndpointHead method="POST" path="/send" what="Send a code." />
          <Lead>
            <strong>Request body.</strong> <Code>phone</Code> is required, with the country code (a bare 10-digit number is taken as Indian). <Code>mode</Code> is optional and defaults to your account setting. <Code>code</Code> is only for Option B. <Code>ref</Code> is your own id, up to 100 characters, sent back in status updates. Unknown fields are rejected with <Code>422</Code>.
          </Lead>
          <CodeBlock code={SEND_BODY} label="Request body" />
          <CodeBlock code={SEND_RESPONSE} label="Response 200" />
          <List>
            <li><Code>source</Code> is <Code>anril</Code> for codes Anril made (Option A).</li>
            <li><Code>sms</Code> mode to a non-Indian number is refused with <Code>400 sms_india_only</Code>. In <Code>both</Code> and <Code>sms_then_whatsapp</Code>, the SMS part is marked failed and WhatsApp still goes out.</li>
            <li>Keep <Code>otp_id</Code>. You need it to verify and to match status updates.</li>
          </List>
        </div>

        <div className="space-y-3 border-t border-[#e2e8f0] pt-4">
          <EndpointHead method="POST" path="/verify" what="Check a code the customer typed (Option A only)." />
          <CodeBlock code={VERIFY_BODY} label="Request body" />
          <Lead>
            You can send <Code>&quot;phone&quot;</Code> instead of <Code>otp_id</Code>. Anril then checks the newest Anril-made code for that number from the last 24 hours. Prefer <Code>otp_id</Code>, because it is exact.
          </Lead>
          <CodeBlock code={VERIFY_OK} label="Response 200, correct code" />
          <CodeBlock code={VERIFY_WRONG} label="Response 200, wrong code" />
          <Lead>A wrong code is still HTTP 200 with <Code>verified: false</Code>. Only bad requests and bad keys return 4xx. Always read <Code>verified</Code> and <Code>reason</Code>.</Lead>
          <TableWrap>
            <table className="min-w-full">
              <thead className="border-b border-[#e2e8f0] bg-[#f8fafc]">
                <tr>
                  <th className={thCls}>Reason</th>
                  <th className={thCls}>Meaning</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e2e8f0]">
                <tr><td className={tdCls}><Code>wrong_code</Code></td><td className={tdCls}>The code does not match. <Code>attempts_left</Code> shows the tries left.</td></tr>
                <tr><td className={tdCls}><Code>locked</Code></td><td className={tdCls}>Too many wrong tries. Send a new code.</td></tr>
                <tr><td className={tdCls}><Code>expired</Code></td><td className={tdCls}>Past its expiry time. Send a new code.</td></tr>
                <tr><td className={tdCls}><Code>already_verified</Code></td><td className={tdCls}>This code was already used.</td></tr>
                <tr><td className={tdCls}><Code>not_requested</Code></td><td className={tdCls}>The customer tapped &quot;I didn&apos;t request a code&quot;.</td></tr>
                <tr><td className={tdCls}><Code>failed</Code></td><td className={tdCls}>The code was never delivered on any channel.</td></tr>
                <tr><td className={tdCls}><Code>not_found</Code></td><td className={tdCls}>No such code.</td></tr>
              </tbody>
            </table>
          </TableWrap>
        </div>

        <div className="space-y-3 border-t border-[#e2e8f0] pt-4">
          <EndpointHead method="GET" path="/{otp_id}" what="Current state of one code." />
          <Lead>Returns the same shape as the <Code>/send</Code> response. Use it if you missed a status update.</Lead>
          <CodeBlock code={GET_EXAMPLE} label="Example" />
        </div>
      </Section>

      <Section title="Status values">
        <TableWrap>
          <table className="min-w-full">
            <thead className="border-b border-[#e2e8f0] bg-[#f8fafc]">
              <tr>
                <th className={thCls}>Field</th>
                <th className={thCls}>Values</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0]">
              <tr><td className={tdCls}>Request <Code>status</Code></td><td className={tdCls}><Code>pending</Code>, <Code>verified</Code>, <Code>expired</Code>, <Code>locked</Code>, <Code>not_requested</Code>, <Code>failed</Code></td></tr>
              <tr><td className={tdCls}><Code>sms.status</Code></td><td className={tdCls}><Code>none</Code>, <Code>sent</Code>, <Code>delivered</Code>, <Code>failed</Code></td></tr>
              <tr><td className={tdCls}><Code>whatsapp.status</Code></td><td className={tdCls}><Code>none</Code>, <Code>sent</Code>, <Code>delivered</Code>, <Code>read</Code>, <Code>failed</Code></td></tr>
            </tbody>
          </table>
        </TableWrap>
        <Lead><Code>none</Code> means that channel was not used for this code.</Lead>
      </Section>

      <Section title="Errors" hint="Every error has the same JSON shape. Check the code field in your code; the error text is for people and may change.">
        <CodeBlock code={String.raw`{ "error": "Plain message for people", "code": "machine_code" }`} label="Error body" />
        <TableWrap>
          <table className="min-w-full">
            <thead className="border-b border-[#e2e8f0] bg-[#f8fafc]">
              <tr>
                <th className={thCls}>HTTP</th>
                <th className={thCls}>code</th>
                <th className={thCls}>What it means and what to do</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0]">
              <tr><td className={tdCls}>401</td><td className={tdCls}><Code>invalid_key</Code></td><td className={tdCls}>The key is missing or wrong. Check the header.</td></tr>
              <tr><td className={tdCls}>401</td><td className={tdCls}><Code>revoked_key</Code></td><td className={tdCls}>The key was revoked. Use another key or create one.</td></tr>
              <tr><td className={tdCls}>400</td><td className={tdCls}><Code>invalid_phone</Code></td><td className={tdCls}>The number is not valid. Include the country code.</td></tr>
              <tr><td className={tdCls}>400</td><td className={tdCls}><Code>invalid_mode</Code></td><td className={tdCls}><Code>mode</Code> is not one of the four values.</td></tr>
              <tr><td className={tdCls}>400</td><td className={tdCls}><Code>invalid_code</Code></td><td className={tdCls}>Your <Code>code</Code> is not 4 to 10 letters or digits.</td></tr>
              <tr><td className={tdCls}>400</td><td className={tdCls}><Code>sms_india_only</Code></td><td className={tdCls}><Code>sms</Code> mode was used for a non-Indian number. Use <Code>whatsapp</Code> or <Code>both</Code>.</td></tr>
              <tr><td className={tdCls}>400</td><td className={tdCls}><Code>missing_target</Code></td><td className={tdCls}><Code>/verify</Code> needs <Code>otp_id</Code> or <Code>phone</Code>.</td></tr>
              <tr><td className={tdCls}>404</td><td className={tdCls}><Code>not_found</Code></td><td className={tdCls}>No code with that <Code>otp_id</Code>.</td></tr>
              <tr><td className={tdCls}>409</td><td className={tdCls}><Code>channel_not_ready</Code></td><td className={tdCls}>The channel is not set up. The message says what is missing, such as no WhatsApp template chosen.</td></tr>
              <tr><td className={tdCls}>409</td><td className={tdCls}><Code>not_checkable</Code></td><td className={tdCls}>You called <Code>/verify</Code> for a code your server made (Option B). Check it on your side.</td></tr>
              <tr><td className={tdCls}>422</td><td className={tdCls}>(validation)</td><td className={tdCls}>The body has an unknown or badly typed field.</td></tr>
              <tr><td className={tdCls}>429</td><td className={tdCls}><Code>too_many_codes</Code></td><td className={tdCls}>The per-number limit was hit. Read <Code>Retry-After</Code> (3600 seconds).</td></tr>
              <tr><td className={tdCls}>429</td><td className={tdCls}><Code>rate_limited</Code></td><td className={tdCls}>Too many requests. Read <Code>Retry-After</Code> (60 seconds) and slow down.</td></tr>
              <tr><td className={tdCls}>503</td><td className={tdCls}><Code>not_configured</Code></td><td className={tdCls}>OTP is not configured for this account. Finish the setup steps.</td></tr>
            </tbody>
          </table>
        </TableWrap>
      </Section>

      <Section title="Status updates (webhooks)" hint="Anril can POST a JSON message to your server each time a code changes state, so you do not have to poll.">
        <Lead>
          Set a public <Code>https://</Code> URL under <strong>Status updates to your server</strong> and create the signing secret. Anril does <strong>not</strong> follow redirects. The URL must be public HTTPS.
        </Lead>
        <Lead>
          <strong>Events:</strong> <Code>sms_sent</Code>, <Code>sms_delivered</Code>, <Code>sms_failed</Code>, <Code>whatsapp_sent</Code>, <Code>whatsapp_delivered</Code>, <Code>whatsapp_read</Code>, <Code>whatsapp_failed</Code>, <Code>whatsapp_backup_sent</Code>, <Code>verified</Code>, <Code>locked</Code>, <Code>expired</Code>, <Code>failed</Code> (every channel failed), <Code>not_requested</Code>, and <Code>test</Code> (from the &quot;Send test update&quot; button).
        </Lead>
        <Notice tone="info">The code itself is <strong>never</strong> included in a status update.</Notice>
        <CodeBlock code={WEBHOOK_BODY} label="Example body" />
        <TableWrap>
          <table className="min-w-full">
            <thead className="border-b border-[#e2e8f0] bg-[#f8fafc]">
              <tr>
                <th className={thCls}>Header</th>
                <th className={thCls}>Value</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0]">
              <tr><td className={tdCls}><Code>X-Anril-Event</Code></td><td className={tdCls}>The event name, such as <Code>verified</Code>.</td></tr>
              <tr><td className={tdCls}><Code>X-Anril-Delivery</Code></td><td className={tdCls}>Same as the body <Code>id</Code>. Use it to ignore duplicates.</td></tr>
              <tr><td className={tdCls}><Code>X-Anril-Timestamp</Code></td><td className={tdCls}>Unix time in seconds, when the message was sent.</td></tr>
              <tr><td className={tdCls}><Code>X-Anril-Signature</Code></td><td className={tdCls}><Code>v1=&lt;hex&gt;</Code>, the signature (below).</td></tr>
            </tbody>
          </table>
        </TableWrap>
        <SubHead>Check the signature</SubHead>
        <Steps>
          <li>Read <Code>X-Anril-Timestamp</Code>. Reject it if it is more than 5 minutes away from your clock. This stops replayed messages.</li>
          <li>Build the signed text: the timestamp, a dot, then the <strong>raw body bytes exactly as received</strong>. Do not parse and re-write the JSON first.</li>
          <li>Compute HMAC-SHA256 of that text, using the whole <Code>whsec_...</Code> secret as the key. Write the result as lowercase hex and put <Code>v1=</Code> in front.</li>
          <li>Compare it with <Code>X-Anril-Signature</Code> using a <strong>constant-time</strong> comparison (<Code>timingSafeEqual</Code>, <Code>hmac.compare_digest</Code> or <Code>hash_equals</Code>). Reject the message if they differ.</li>
          <li>Ignore any <Code>X-Anril-Delivery</Code> you have already handled.</li>
        </Steps>
        <Lead>
          <strong>Answer fast.</strong> Return any 2xx status within <strong>10 seconds</strong>. Do the real work after you reply, or put it on a queue.
        </Lead>
        <Lead>
          <strong>Retries.</strong> If your server does not return 2xx, Anril retries after 1, 5, 15 and 30 minutes: 5 tries in total. After that it gives up and shows the failed delivery on the dashboard.
        </Lead>
      </Section>

      <Section title={"\"I didn't request a code\""}>
        <Lead>
          WhatsApp authentication messages have a <strong>Copy code</strong> button. For some accounts, Meta (in beta) also adds an <strong>I didn&apos;t request a code</strong> button. If the customer taps it:
        </Lead>
        <List>
          <li>Anril cancels that code. A later <Code>/verify</Code> answers <Code>reason: &quot;not_requested&quot;</Code>.</li>
          <li>Anril sends your server a <Code>not_requested</Code> status update.</li>
          <li>If <strong>your</strong> server made the code (Option B), cancel it on your side too.</li>
        </List>
      </Section>

      <Section title="Limits">
        <TableWrap>
          <table className="min-w-full">
            <thead className="border-b border-[#e2e8f0] bg-[#f8fafc]">
              <tr>
                <th className={thCls}>Limit</th>
                <th className={thCls}>Value</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0]">
              <tr><td className={tdCls}>Active API keys per account</td><td className={tdCls}>2. Create a second one to rotate with no downtime.</td></tr>
              <tr><td className={tdCls}>Requests per key or per IP</td><td className={tdCls}>120 a minute (429 <Code>rate_limited</Code>, <Code>Retry-After: 60</Code>)</td></tr>
              <tr><td className={tdCls}><Code>/verify</Code> requests per key</td><td className={tdCls}>60 a minute</td></tr>
              <tr><td className={tdCls}>Codes per phone number</td><td className={tdCls}>5 an hour by default, changeable in settings (429 <Code>too_many_codes</Code>, <Code>Retry-After: 3600</Code>)</td></tr>
              <tr><td className={tdCls}>Wrong tries per code</td><td className={tdCls}>Set in OTP settings: 1 to 10, default 5. Then the code locks.</td></tr>
              <tr><td className={tdCls}>Code length, Option A</td><td className={tdCls}>4 to 8 digits, default 6</td></tr>
              <tr><td className={tdCls}>Code length, Option B</td><td className={tdCls}>4 to 10 letters or digits</td></tr>
              <tr><td className={tdCls}>Code expiry</td><td className={tdCls}>1 to 30 minutes, default 10</td></tr>
              <tr><td className={tdCls}>WhatsApp backup wait</td><td className={tdCls}>10 to 300 seconds, default 30</td></tr>
              <tr><td className={tdCls}><Code>ref</Code> length</td><td className={tdCls}>100 characters</td></tr>
              <tr><td className={tdCls}>Status update tries</td><td className={tdCls}>5 in total (at 1, 5, 15 and 30 minutes)</td></tr>
              <tr><td className={tdCls}>Status update response time</td><td className={tdCls}>2xx within 10 seconds</td></tr>
            </tbody>
          </table>
        </TableWrap>
      </Section>

      <Section title="Security tips">
        <List>
          <li><strong>Keep the key on your server only.</strong> Never put it in a mobile app, a browser script or a website&apos;s front end. Anyone with the key can send codes from your SMS balance and WhatsApp number.</li>
          <li><strong>Rotate with two keys.</strong> Create the new key, deploy it, then revoke the old one. Revoked keys stop working straight away.</li>
          <li><strong>Never log codes.</strong> Log <Code>otp_id</Code>, <Code>ref</Code> and <Code>reason</Code>, not the code. For Option B, store your copy hashed, with its expiry time.</li>
          <li><strong>Verify every status update&apos;s signature</strong> before you trust it.</li>
          <li><strong>Use HTTPS</strong> for your status URL.</li>
          <li><strong>Rate-limit your own send endpoint</strong> per user, so your form cannot be used to spam someone&apos;s phone.</li>
        </List>
      </Section>

      <Card>
        <CardHeader title="Sample code" hint="Complete, runnable examples. Pick a language." />
        <div className="space-y-4 p-4 sm:p-5">
          <SampleCode />
        </div>
      </Card>
    </div>
  );
}

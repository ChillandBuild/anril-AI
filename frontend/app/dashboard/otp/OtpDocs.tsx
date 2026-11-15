"use client";

import { Children, useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Notice, TableWrap, tdCls, thCls } from "../sms/ui";
import { CodePanel, MethodBadge, type CodeTab } from "./otpUi";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://YOUR-ANRIL-API";
export const OTP_BASE = `${API_BASE}/api/v1/otp`;

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

// One endpoint at a time, for the Request panel of each endpoint section.

const SEND_REQUEST: Record<Lang, string> = {
  curl: String.raw`curl -sS -X POST "$ANRIL_API_URL/api/v1/otp/send" \
  -H "Authorization: Bearer $ANRIL_OTP_KEY" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+919876543210","mode":"sms_then_whatsapp","ref":"order-123"}'`,
  node: String.raw`// send.mjs
const res = await fetch(process.env.ANRIL_API_URL + "/api/v1/otp/send", {
  method: "POST",
  headers: {
    Authorization: "Bearer " + process.env.ANRIL_OTP_KEY,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ phone: "+919876543210", mode: "sms_then_whatsapp", ref: "order-123" }),
});
const data = await res.json();
if (!res.ok) throw new Error(data.code + ": " + data.error);
console.log("otp_id:", data.otp_id);`,
  python: String.raw`# send.py
import os
import requests

r = requests.post(
    os.environ["ANRIL_API_URL"] + "/api/v1/otp/send",
    headers={"Authorization": f"Bearer {os.environ['ANRIL_OTP_KEY']}"},
    json={"phone": "+919876543210", "mode": "sms_then_whatsapp", "ref": "order-123"},
    timeout=15,
)
data = r.json()
if not r.ok:
    raise RuntimeError(f"{data.get('code')}: {data.get('error')}")
print("otp_id:", data["otp_id"])`,
  php: String.raw`<?php
// send.php
$ch = curl_init(getenv('ANRIL_API_URL') . '/api/v1/otp/send');
curl_setopt_array($ch, [
    CURLOPT_POST           => true,
    CURLOPT_POSTFIELDS     => json_encode([
        'phone' => '+919876543210',
        'mode'  => 'sms_then_whatsapp',
        'ref'   => 'order-123',
    ]),
    CURLOPT_HTTPHEADER     => ['Authorization: Bearer ' . getenv('ANRIL_OTP_KEY'), 'Content-Type: application/json'],
    CURLOPT_RETURNTRANSFER => true,
]);
$data   = json_decode(curl_exec($ch), true) ?? [];
$status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
if ($status >= 400) {
    exit(($data['code'] ?? 'error') . ': ' . ($data['error'] ?? 'request failed') . PHP_EOL);
}
echo 'otp_id: ' . $data['otp_id'] . PHP_EOL;`,
};

const VERIFY_REQUEST: Record<Lang, string> = {
  curl: String.raw`curl -sS -X POST "$ANRIL_API_URL/api/v1/otp/verify" \
  -H "Authorization: Bearer $ANRIL_OTP_KEY" \
  -H "Content-Type: application/json" \
  -d '{"otp_id":"PASTE_OTP_ID_HERE","code":"482913"}'`,
  node: String.raw`// verify.mjs
const res = await fetch(process.env.ANRIL_API_URL + "/api/v1/otp/verify", {
  method: "POST",
  headers: {
    Authorization: "Bearer " + process.env.ANRIL_OTP_KEY,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ otp_id: "PASTE_OTP_ID_HERE", code: "482913" }),
});
const data = await res.json();
if (!res.ok) throw new Error(data.code + ": " + data.error);
console.log(data.verified ? "Correct" : "Not verified: " + data.reason);`,
  python: String.raw`# verify.py
import os
import requests

r = requests.post(
    os.environ["ANRIL_API_URL"] + "/api/v1/otp/verify",
    headers={"Authorization": f"Bearer {os.environ['ANRIL_OTP_KEY']}"},
    json={"otp_id": "PASTE_OTP_ID_HERE", "code": "482913"},
    timeout=15,
)
data = r.json()
if not r.ok:
    raise RuntimeError(f"{data.get('code')}: {data.get('error')}")
print("Correct" if data["verified"] else f"Not verified: {data['reason']}")`,
  php: String.raw`<?php
// verify.php
$ch = curl_init(getenv('ANRIL_API_URL') . '/api/v1/otp/verify');
curl_setopt_array($ch, [
    CURLOPT_POST           => true,
    CURLOPT_POSTFIELDS     => json_encode(['otp_id' => 'PASTE_OTP_ID_HERE', 'code' => '482913']),
    CURLOPT_HTTPHEADER     => ['Authorization: Bearer ' . getenv('ANRIL_OTP_KEY'), 'Content-Type: application/json'],
    CURLOPT_RETURNTRANSFER => true,
]);
$data   = json_decode(curl_exec($ch), true) ?? [];
$status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
if ($status >= 400) {
    exit(($data['code'] ?? 'error') . ': ' . ($data['error'] ?? 'request failed') . PHP_EOL);
}
echo $data['verified'] ? "Correct\n" : 'Not verified: ' . $data['reason'] . "\n";`,
};

const STATUS_REQUEST: Record<Lang, string> = {
  curl: String.raw`curl -sS "$ANRIL_API_URL/api/v1/otp/PASTE_OTP_ID_HERE" \
  -H "Authorization: Bearer $ANRIL_OTP_KEY"`,
  node: String.raw`// status.mjs
const res = await fetch(process.env.ANRIL_API_URL + "/api/v1/otp/PASTE_OTP_ID_HERE", {
  headers: { Authorization: "Bearer " + process.env.ANRIL_OTP_KEY },
});
const data = await res.json();
if (!res.ok) throw new Error(data.code + ": " + data.error);
console.log(data.status, data.sms.status, data.whatsapp.status);`,
  python: String.raw`# status.py
import os
import requests

r = requests.get(
    os.environ["ANRIL_API_URL"] + "/api/v1/otp/PASTE_OTP_ID_HERE",
    headers={"Authorization": f"Bearer {os.environ['ANRIL_OTP_KEY']}"},
    timeout=15,
)
data = r.json()
if not r.ok:
    raise RuntimeError(f"{data.get('code')}: {data.get('error')}")
print(data["status"], data["sms"]["status"], data["whatsapp"]["status"])`,
  php: String.raw`<?php
// status.php
$ch = curl_init(getenv('ANRIL_API_URL') . '/api/v1/otp/PASTE_OTP_ID_HERE');
curl_setopt_array($ch, [
    CURLOPT_HTTPHEADER     => ['Authorization: Bearer ' . getenv('ANRIL_OTP_KEY')],
    CURLOPT_RETURNTRANSFER => true,
]);
$data   = json_decode(curl_exec($ch), true) ?? [];
$status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
if ($status >= 400) {
    exit(($data['code'] ?? 'error') . ': ' . ($data['error'] ?? 'request failed') . PHP_EOL);
}
echo $data['status'] . ' sms=' . $data['sms']['status'] . ' whatsapp=' . $data['whatsapp']['status'] . PHP_EOL;`,
};

// Full runnable samples (the "Sample code" section).

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

const WEBHOOK_TABS: CodeTab[] = [
  { id: "node", label: "Node.js", code: SAMPLE_WEBHOOK.node },
  { id: "python", label: "Python", code: SAMPLE_WEBHOOK.python },
  { id: "php", label: "PHP", code: SAMPLE_WEBHOOK.php },
];

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

const ERROR_BODY = String.raw`{ "error": "Plain message for people", "code": "machine_code" }`;

// ---------------------------------------------------------------- table of contents

const TOC: { id: string; label: string; indent?: boolean }[] = [
  { id: "overview", label: "What an OTP is" },
  { id: "modes", label: "What it does" },
  { id: "setup", label: "Before you start" },
  { id: "two-ways", label: "Two ways to use it" },
  { id: "endpoints", label: "Endpoints" },
  { id: "send", label: "Send a code", indent: true },
  { id: "verify", label: "Check a code", indent: true },
  { id: "status", label: "Get one code's state", indent: true },
  { id: "status-values", label: "Status values" },
  { id: "errors", label: "Errors" },
  { id: "webhooks", label: "Status updates (webhooks)" },
  { id: "not-requested", label: "I didn't request a code" },
  { id: "limits", label: "Limits" },
  { id: "security", label: "Security tips" },
  { id: "samples", label: "Sample code" },
];

// ---------------------------------------------------------------- building blocks

function Code({ children }: { children: ReactNode }) {
  return <code className="rounded-md bg-[#f1f5f9] px-1.5 py-0.5 font-mono text-[12.5px] text-[#0A1528] break-words">{children}</code>;
}

function Lead({ children }: { children: ReactNode }) {
  return <p className="max-w-3xl text-sm leading-7 text-[#334155]">{children}</p>;
}

function List({ children }: { children: ReactNode }) {
  return <ul className="max-w-3xl list-disc space-y-1.5 pl-5 text-sm leading-7 text-[#334155]">{children}</ul>;
}

/** Marker for one numbered step. Steps renders the number. */
function Step({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

function Steps({ children }: { children: ReactNode }) {
  return (
    <ol className="max-w-3xl space-y-3">
      {Children.toArray(children).map((child, i) => (
        <li key={i} className="flex gap-3 text-sm leading-7 text-[#334155]">
          <span
            aria-hidden="true"
            className="mt-1 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-bold tabular-nums text-white"
          >
            {i + 1}
          </span>
          <div className="min-w-0 flex-1">{child}</div>
        </li>
      ))}
    </ol>
  );
}

function SubHead({ children }: { children: ReactNode }) {
  return <h3 className="pt-2 font-display text-[15px] font-bold text-[#0A1528]">{children}</h3>;
}

function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("text-[11px] font-bold uppercase tracking-[0.08em] text-[#64748b]", className)}>{children}</p>;
}

function DocTable({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <TableWrap>
      <table className="min-w-full">
        <thead className="border-b border-[#e2e8f0] bg-[#f8fafc]">
          <tr>
            {headers.map((h) => (
              <th key={h} className={thCls}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#e2e8f0]">{children}</tbody>
      </table>
    </TableWrap>
  );
}

type Param = { name: string; type: string; required: string; desc: ReactNode };

function ParamTable({ rows }: { rows: Param[] }) {
  return (
    <DocTable headers={["Name", "Type", "Required", "Description"]}>
      {rows.map((r) => (
        <tr key={r.name}>
          <td className={tdCls}>
            <Code>{r.name}</Code>
          </td>
          <td className={tdCls}>{r.type}</td>
          <td className={tdCls}>{r.required}</td>
          <td className={tdCls}>{r.desc}</td>
        </tr>
      ))}
    </DocTable>
  );
}

/** Section wrapper. The sections sit in one card, separated by dividers, and each has an id for the table of contents. */
function DocSection({ id, title, description, children }: { id: string; title: ReactNode; description?: string; children?: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 space-y-5 px-5 py-8 sm:px-6">
      <div>
        <h2 className="font-display text-lg font-bold text-[#0A1528]">{title}</h2>
        {description && <p className="mt-1 max-w-3xl text-sm leading-6 text-[#64748b]">{description}</p>}
      </div>
      {children}
    </section>
  );
}

function EndpointTitle({ method, path, what }: { method: string; path: string; what: string }) {
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <MethodBadge method={method} />
      <code className="break-all font-mono text-base font-bold text-[#0A1528]">{path}</code>
      <span className="text-sm font-normal text-[#64748b]">{what}</span>
    </span>
  );
}

/** Tabs for one endpoint's code, in cURL / Node.js / Python / PHP order. */
function tabsFor(snippets: Record<Lang, string>): CodeTab[] {
  return LANGS.map((l) => ({ id: l.id, label: l.label, code: snippets[l.id] }));
}

function DocToc({ active }: { active: string }) {
  return (
    <nav aria-label="On this page" className="hidden lg:sticky lg:top-20 lg:block lg:self-start">
      <p className="mb-2 px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-[#64748b]">On this page</p>
      <ul className="space-y-0.5">
        {TOC.map((item) => {
          const on = item.id === active;
          return (
            <li key={item.id}>
              <a
                href={`#${item.id}`}
                aria-current={on ? "true" : undefined}
                className={cn(
                  "relative block rounded-md py-1.5 pr-2 text-[13px] transition-colors hover:text-[#0A1528] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
                  item.indent ? "pl-6" : "pl-3",
                  on ? "font-semibold text-primary" : "text-[#64748b]",
                )}
              >
                {on && <span aria-hidden="true" className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-primary" />}
                {item.label}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

// ---------------------------------------------------------------- page

function SampleCode({ lang, pick }: { lang: Lang; pick: (id: string) => void }) {
  return (
    <>
      <Lead>Each sample reads the base URL and keys from environment variables. Set them once, then run the sample.</Lead>
      <CodePanel tabs={[{ id: "env", label: "Environment variables", code: ENV_SETUP }]} title="Environment variables" />

      <SubHead>Send a code and check it (Option A)</SubHead>
      <CodePanel
        tabs={tabsFor(SAMPLE_SEND)}
        value={lang}
        onChange={pick}
      />

      <SubHead>Receive status updates (webhook) with a signature check</SubHead>
      {lang === "curl" ? (
        <Notice tone="info">cURL can only send requests. For the webhook receiver, pick Node.js, Python or PHP above.</Notice>
      ) : (
        <CodePanel tabs={WEBHOOK_TABS} value={lang} onChange={pick} />
      )}
    </>
  );
}

export function OtpDocs() {
  const [lang, setLang] = useState<Lang>("curl");
  const [active, setActive] = useState(TOC[0].id);

  // One language choice for the whole page. Every multi-language panel reads it.
  function pick(id: string) {
    setLang(id as Lang);
  }

  // Highlight the section in the table of contents that is currently on screen.
  // The active one is the last section whose top has passed a line just below the sticky header.
  useEffect(() => {
    let frame = 0;
    function update() {
      frame = 0;
      let current = TOC[0]?.id;
      for (const item of TOC) {
        const el = document.getElementById(item.id);
        if (el && el.getBoundingClientRect().top <= 140) current = item.id;
      }
      if (current) setActive(current);
    }
    function onScroll() {
      if (!frame) frame = window.requestAnimationFrame(update);
    }
    update();
    window.addEventListener("scroll", onScroll, { passive: true, capture: true });
    return () => {
      window.removeEventListener("scroll", onScroll, { capture: true });
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div className="lg:grid lg:grid-cols-[200px_minmax(0,1fr)] lg:items-start lg:gap-8">
      <DocToc active={active} />

      <div className="min-w-0 rounded-2xl border border-[#e2e8f0] bg-white shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
        <div className="divide-y divide-[#e2e8f0]">
          <DocSection id="overview" title="What an OTP is">
            <Lead>
              An OTP is a short, one-use number, like <Code>482913</Code>, that proves the person has the phone they say they have. Common uses are login, sign-up, order confirmation and payment confirmation.
            </Lead>
            <Lead>
              Base URL: <Code>{OTP_BASE}</Code>.
            </Lead>
          </DocSection>

          <DocSection
            id="modes"
            title="What it does"
            description="Your server asks Anril to send a code. Later, your server (or Anril) checks what the customer typed."
          >
            <Lead>
              Messages are sent from <strong>your own</strong> SMS balance (through Bulk9) and <strong>your own</strong> WhatsApp number. Pick one of four delivery modes per request, or set a default in settings.
            </Lead>
            <DocTable headers={["Mode", "What happens", "When to use it"]}>
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
            </DocTable>
            <SubHead>Terms used in this guide</SubHead>
            <List>
              <li><strong>SMS:</strong> a text message to a phone number.</li>
              <li><strong>Bulk9:</strong> the SMS provider Anril uses. Your SMS balance is held there.</li>
              <li><strong>WhatsApp template:</strong> a message format that Meta (the company behind WhatsApp) must approve before a business can send it. OTPs use authentication templates.</li>
              <li><strong>Webhook:</strong> a message Anril sends to your server when something changes, such as &quot;the code was delivered&quot;. Your server needs a public web address to receive it.</li>
              <li><strong>HMAC signature:</strong> a fingerprint of a message, made with a secret key. It proves the message came from Anril and was not changed.</li>
              <li><strong>Server-to-server:</strong> your own backend talks to Anril. A customer&apos;s phone or browser never does.</li>
            </List>
          </DocSection>

          <DocSection id="setup" title="Before you start" description="Only the account owner can do steps 1 to 4.">
            <Steps>
              <Step>
                <strong>Connect your channels.</strong> Connect SMS (Bulk9) and/or WhatsApp in Anril. You need at least one.
              </Step>
              <Step>
                <strong>Open Anril OTP → Settings.</strong> Pick an SMS template and a WhatsApp template (an approved authentication template, or choose <strong>Create new</strong> and wait for Meta to approve it). Set the default mode and the rules: code length (4 to 8 digits, default 6), expiry (1 to 30 minutes, default 10), the per-number limit (default 5 codes an hour), and the WhatsApp backup wait (10 to 300 seconds, default 30). Click <strong>Save</strong>.
              </Step>
              <Step>
                <strong>Create an API key.</strong> On <strong>API &amp; docs</strong>, click <strong>Create key</strong>. Copy it and store it on your server, for example in an environment variable. Anril shows the full key <strong>once</strong> and keeps only a fingerprint, so a lost key cannot be recovered. Create a new one and revoke the old one.
              </Step>
              <Step>
                <strong>(Optional) Set up status updates.</strong> Under <strong>Status updates to your server</strong> in settings, enter an <Code>https://</Code> URL, then create the signing secret. It starts with <Code>whsec_</Code> and is also shown once.
              </Step>
            </Steps>
          </DocSection>

          <DocSection id="two-ways" title="Two ways to use it" description="Pick one per flow. Both work with every mode.">
            <div className="space-y-4">
              <SubHead>Option A: Anril makes the code</SubHead>
              <Lead>Use this when you want Anril to create the code, keep only its hash, and check it for you.</Lead>
              <Steps>
                <Step>Your server calls <Code>POST /send</Code> without a <Code>code</Code>.</Step>
                <Step>Anril makes the code (length from settings), sends it, and returns an <Code>otp_id</Code>.</Step>
                <Step>The customer types the code into your app.</Step>
                <Step>Your server calls <Code>POST /verify</Code> with the <Code>otp_id</Code> and the typed code.</Step>
                <Step>Anril answers <Code>verified: true</Code> or <Code>verified: false</Code>, with a reason.</Step>
              </Steps>
              <List>
                <li>Wrong tries are limited (you set the number in OTP settings: 1 to 10, default 5). After that the code is <strong>locked</strong>.</li>
                <li>A code expires after the time set in settings (1 to 30 minutes).</li>
                <li>Sending a new code to the same number cancels the previous open code.</li>
              </List>
            </div>

            <div className="space-y-4">
              <SubHead>Option B: Your server makes the code</SubHead>
              <Lead>Use this when your own system must own the code, for example because you store it with an order.</Lead>
              <Steps>
                <Step>Your server makes the code (4 to 10 letters or digits).</Step>
                <Step>Your server calls <Code>POST /send</Code> <strong>with</strong> the <Code>code</Code>.</Step>
                <Step>Anril only delivers the code. It keeps a masked copy (for example <Code>00••10</Code>), never the full code.</Step>
                <Step>The customer types the code into your app.</Step>
                <Step>
                  <strong>Your server</strong> compares the typed code with its own copy. Anril&apos;s <Code>/verify</Code> answers <Code>409 not_checkable</Code> for these codes, so do not call it.
                </Step>
                <Step>Listen for the <Code>not_requested</Code> status update. If the customer taps &quot;I didn&apos;t request a code&quot;, cancel the code on your side too.</Step>
              </Steps>
            </div>
          </DocSection>

          <DocSection
            id="endpoints"
            title="Endpoints"
            description="All requests need Authorization: Bearer anr_otp_live_... and Content-Type: application/json."
          />

          <DocSection id="send" title={<EndpointTitle method="POST" path="/send" what="Send a code." />}>
            <div className="grid gap-6 xl:grid-cols-2 xl:gap-8">
              <div className="min-w-0 space-y-5">
                <Lead>
                  <strong>Request body.</strong> <Code>phone</Code> is required, with the country code (a bare 10-digit number is taken as Indian). <Code>mode</Code> is optional and defaults to your account setting. <Code>code</Code> is only for Option B. <Code>ref</Code> is your own id, up to 100 characters, sent back in status updates. Unknown fields are rejected with <Code>422</Code>.
                </Lead>
                <ParamTable
                  rows={[
                    { name: "phone", type: "string", required: "Yes", desc: "The number, with the country code. A bare 10-digit number is taken as Indian." },
                    { name: "mode", type: "string", required: "No", desc: <>One of <Code>sms</Code>, <Code>whatsapp</Code>, <Code>both</Code>, <Code>sms_then_whatsapp</Code>. Defaults to your account setting.</> },
                    { name: "code", type: "string", required: "No", desc: "Only for Option B: 4 to 10 letters or digits. Leave it out and Anril makes the code." },
                    { name: "ref", type: "string", required: "No", desc: "Your own id, up to 100 characters. Sent back in status updates." },
                  ]}
                />
                <CodePanel tabs={[{ id: "body", label: "Request body", code: SEND_BODY }]} title="Request body" />
                <List>
                  <li><Code>source</Code> is <Code>anril</Code> for codes Anril made (Option A).</li>
                  <li><Code>sms</Code> mode to a non-Indian number is refused with <Code>400 sms_india_only</Code>. In <Code>both</Code> and <Code>sms_then_whatsapp</Code>, the SMS part is marked failed and WhatsApp still goes out.</li>
                  <li>Keep <Code>otp_id</Code>. You need it to verify and to match status updates.</li>
                </List>
              </div>

              <div className="min-w-0 space-y-5">
                <div>
                  <Eyebrow className="mb-2">Request</Eyebrow>
                  <CodePanel tabs={tabsFor(SEND_REQUEST)} value={lang} onChange={pick} />
                </div>
                <CodePanel tabs={[{ id: "res", label: "Response 200", code: SEND_RESPONSE }]} title="Response 200" />
              </div>
            </div>
          </DocSection>

          <DocSection id="verify" title={<EndpointTitle method="POST" path="/verify" what="Check a code the customer typed (Option A only)." />}>
            <div className="grid gap-6 xl:grid-cols-2 xl:gap-8">
              <div className="min-w-0 space-y-5">
                <ParamTable
                  rows={[
                    { name: "otp_id", type: "string", required: "Yes, or phone", desc: "The id from /send. Use it when you can, because it is exact." },
                    { name: "phone", type: "string", required: "Yes, or otp_id", desc: "Anril checks the newest Anril-made code for that number from the last 24 hours." },
                    { name: "code", type: "string", required: "Yes", desc: "The code the customer typed." },
                  ]}
                />
                <CodePanel tabs={[{ id: "body", label: "Request body", code: VERIFY_BODY }]} title="Request body" />
                <Lead>
                  You can send <Code>&quot;phone&quot;</Code> instead of <Code>otp_id</Code>. Anril then checks the newest Anril-made code for that number from the last 24 hours. Prefer <Code>otp_id</Code>, because it is exact.
                </Lead>
                <Lead>A wrong code is still HTTP 200 with <Code>verified: false</Code>. Only bad requests and bad keys return 4xx. Always read <Code>verified</Code> and <Code>reason</Code>.</Lead>
                <DocTable headers={["Reason", "Meaning"]}>
                  <tr><td className={tdCls}><Code>wrong_code</Code></td><td className={tdCls}>The code does not match. <Code>attempts_left</Code> shows the tries left.</td></tr>
                  <tr><td className={tdCls}><Code>locked</Code></td><td className={tdCls}>Too many wrong tries. Send a new code.</td></tr>
                  <tr><td className={tdCls}><Code>expired</Code></td><td className={tdCls}>Past its expiry time. Send a new code.</td></tr>
                  <tr><td className={tdCls}><Code>already_verified</Code></td><td className={tdCls}>This code was already used.</td></tr>
                  <tr><td className={tdCls}><Code>not_requested</Code></td><td className={tdCls}>The customer tapped &quot;I didn&apos;t request a code&quot;.</td></tr>
                  <tr><td className={tdCls}><Code>failed</Code></td><td className={tdCls}>The code was never delivered on any channel.</td></tr>
                  <tr><td className={tdCls}><Code>not_found</Code></td><td className={tdCls}>No such code.</td></tr>
                </DocTable>
              </div>

              <div className="min-w-0 space-y-5">
                <div>
                  <Eyebrow className="mb-2">Request</Eyebrow>
                  <CodePanel tabs={tabsFor(VERIFY_REQUEST)} value={lang} onChange={pick} />
                </div>
                <CodePanel tabs={[{ id: "ok", label: "Response 200, correct code", code: VERIFY_OK }]} title="Response 200, correct code" />
                <CodePanel tabs={[{ id: "wrong", label: "Response 200, wrong code", code: VERIFY_WRONG }]} title="Response 200, wrong code" />
              </div>
            </div>
          </DocSection>

          <DocSection id="status" title={<EndpointTitle method="GET" path="/{otp_id}" what="Current state of one code." />}>
            <div className="grid gap-6 xl:grid-cols-2 xl:gap-8">
              <div className="min-w-0 space-y-5">
                <Lead>Returns the same shape as the <Code>/send</Code> response. Use it if you missed a status update.</Lead>
              </div>

              <div className="min-w-0 space-y-5">
                <div>
                  <Eyebrow className="mb-2">Request</Eyebrow>
                  <CodePanel tabs={tabsFor(STATUS_REQUEST)} value={lang} onChange={pick} />
                </div>
                <CodePanel tabs={[{ id: "example", label: "Example", code: GET_EXAMPLE }]} title="Example" />
              </div>
            </div>
          </DocSection>

          <DocSection id="status-values" title="Status values">
            <DocTable headers={["Field", "Values"]}>
              <tr><td className={tdCls}>Request <Code>status</Code></td><td className={tdCls}><Code>pending</Code>, <Code>verified</Code>, <Code>expired</Code>, <Code>locked</Code>, <Code>not_requested</Code>, <Code>failed</Code></td></tr>
              <tr><td className={tdCls}><Code>sms.status</Code></td><td className={tdCls}><Code>none</Code>, <Code>sent</Code>, <Code>delivered</Code>, <Code>failed</Code></td></tr>
              <tr><td className={tdCls}><Code>whatsapp.status</Code></td><td className={tdCls}><Code>none</Code>, <Code>sent</Code>, <Code>delivered</Code>, <Code>read</Code>, <Code>failed</Code></td></tr>
            </DocTable>
            <Lead><Code>none</Code> means that channel was not used for this code.</Lead>
          </DocSection>

          <DocSection
            id="errors"
            title="Errors"
            description="Every error has the same JSON shape. Check the code field in your code; the error text is for people and may change."
          >
            <CodePanel tabs={[{ id: "error", label: "Error body", code: ERROR_BODY }]} title="Error body" />
            <DocTable headers={["HTTP", "code", "What it means and what to do"]}>
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
            </DocTable>
          </DocSection>

          <DocSection
            id="webhooks"
            title="Status updates (webhooks)"
            description="Anril can POST a JSON message to your server each time a code changes state, so you do not have to poll."
          >
            <Lead>
              Set a public <Code>https://</Code> URL under <strong>Status updates to your server</strong> and create the signing secret. Anril does <strong>not</strong> follow redirects. The URL must be public HTTPS.
            </Lead>
            <Lead>
              <strong>Events:</strong> <Code>sms_sent</Code>, <Code>sms_delivered</Code>, <Code>sms_failed</Code>, <Code>whatsapp_sent</Code>, <Code>whatsapp_delivered</Code>, <Code>whatsapp_read</Code>, <Code>whatsapp_failed</Code>, <Code>whatsapp_backup_sent</Code>, <Code>verified</Code>, <Code>locked</Code>, <Code>expired</Code>, <Code>failed</Code> (every channel failed), <Code>not_requested</Code>, and <Code>test</Code> (from the &quot;Send test update&quot; button).
            </Lead>
            <Notice tone="info">The code itself is <strong>never</strong> included in a status update.</Notice>
            <CodePanel tabs={[{ id: "body", label: "Example body", code: WEBHOOK_BODY }]} title="Example body" />
            <DocTable headers={["Header", "Value"]}>
              <tr><td className={tdCls}><Code>X-Anril-Event</Code></td><td className={tdCls}>The event name, such as <Code>verified</Code>.</td></tr>
              <tr><td className={tdCls}><Code>X-Anril-Delivery</Code></td><td className={tdCls}>Same as the body <Code>id</Code>. Use it to ignore duplicates.</td></tr>
              <tr><td className={tdCls}><Code>X-Anril-Timestamp</Code></td><td className={tdCls}>Unix time in seconds, when the message was sent.</td></tr>
              <tr><td className={tdCls}><Code>X-Anril-Signature</Code></td><td className={tdCls}><Code>v1=&lt;hex&gt;</Code>, the signature (below).</td></tr>
            </DocTable>

            <SubHead>Check the signature</SubHead>
            <Steps>
              <Step>Read <Code>X-Anril-Timestamp</Code>. Reject it if it is more than 5 minutes away from your clock. This stops replayed messages.</Step>
              <Step>Build the signed text: the timestamp, a dot, then the <strong>raw body bytes exactly as received</strong>. Do not parse and re-write the JSON first.</Step>
              <Step>Compute HMAC-SHA256 of that text, using the whole <Code>whsec_...</Code> secret as the key. Write the result as lowercase hex and put <Code>v1=</Code> in front.</Step>
              <Step>Compare it with <Code>X-Anril-Signature</Code> using a <strong>constant-time</strong> comparison (<Code>timingSafeEqual</Code>, <Code>hmac.compare_digest</Code> or <Code>hash_equals</Code>). Reject the message if they differ.</Step>
              <Step>Ignore any <Code>X-Anril-Delivery</Code> you have already handled.</Step>
            </Steps>

            <div className="space-y-3">
              <Eyebrow>Webhook receiver</Eyebrow>
              <CodePanel tabs={WEBHOOK_TABS} value={lang} onChange={pick} />
            </div>

            <Lead>
              <strong>Answer fast.</strong> Return any 2xx status within <strong>10 seconds</strong>. Do the real work after you reply, or put it on a queue.
            </Lead>
            <Lead>
              <strong>Retries.</strong> If your server does not return 2xx, Anril retries after 1, 5, 15 and 30 minutes: 5 tries in total. After that it gives up and shows the failed delivery on the dashboard.
            </Lead>
          </DocSection>

          <DocSection id="not-requested" title={"\"I didn't request a code\""}>
            <Lead>
              WhatsApp authentication messages have a <strong>Copy code</strong> button. For some accounts, Meta (in beta) also adds an <strong>I didn&apos;t request a code</strong> button. If the customer taps it:
            </Lead>
            <List>
              <li>Anril cancels that code. A later <Code>/verify</Code> answers <Code>reason: &quot;not_requested&quot;</Code>.</li>
              <li>Anril sends your server a <Code>not_requested</Code> status update.</li>
              <li>If <strong>your</strong> server made the code (Option B), cancel it on your side too.</li>
            </List>
          </DocSection>

          <DocSection id="limits" title="Limits">
            <DocTable headers={["Limit", "Value"]}>
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
            </DocTable>
          </DocSection>

          <DocSection id="security" title="Security tips">
            <List>
              <li><strong>Keep the key on your server only.</strong> Never put it in a mobile app, a browser script or a website&apos;s front end. Anyone with the key can send codes from your SMS balance and WhatsApp number.</li>
              <li><strong>Rotate with two keys.</strong> Create the new key, deploy it, then revoke the old one. Revoked keys stop working straight away.</li>
              <li><strong>Never log codes.</strong> Log <Code>otp_id</Code>, <Code>ref</Code> and <Code>reason</Code>, not the code. For Option B, store your copy hashed, with its expiry time.</li>
              <li><strong>Verify every status update&apos;s signature</strong> before you trust it.</li>
              <li><strong>Use HTTPS</strong> for your status URL.</li>
              <li><strong>Rate-limit your own send endpoint</strong> per user, so your form cannot be used to spam someone&apos;s phone.</li>
            </List>
          </DocSection>

          <DocSection id="samples" title="Sample code" description="Complete, runnable examples. Pick a language.">
            <SampleCode lang={lang} pick={pick} />
          </DocSection>
        </div>
      </div>
    </div>
  );
}

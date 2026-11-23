"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Code2,
  Copy,
  KeyRound,
  Hash,
  Send,
  ShieldCheck,
  Reply,
  ListChecks,
  AlertTriangle,
} from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { usePrivateSend } from "@/app/dashboard/auto-messages/PrivateSend";
import { DoorChooser } from "./DoorChooser";
import { ErrorLine } from "./DevSection";
import { EventModeSubsection } from "./EventModeSubsection";
import type { PartnerSendMode } from "./privateSendClient";
import { SendModePicker, usePartnerSendMode } from "./SendModePicker";
import { SendFromServerSection } from "./SendFromServerSection";

/*
  Developer — the page another company's developer reads to connect their own
  app to this Anril account. Everything on it is either public contract (paths,
  body shapes, error codes) or this tenant's own non-secret identifiers. The
  shared secret is never shown: ops issue it, and the page only says whether
  one is on file.
*/

type PartnerConfig = {
  tenant_id: string;
  secret_set: boolean;
  bridge_url_set: boolean;
  api_key_set: boolean;
  paths: {
    send_template: string;
    send_text: string;
    reply_callback: string;
    legacy_prefix: string;
  };
};

const DEFAULT_PATHS: PartnerConfig["paths"] = {
  send_template: "/api/v1/intake/partner/send-template",
  send_text: "/api/v1/intake/partner/send-text",
  reply_callback: "/api/v1/intake/astro-reply",
  legacy_prefix: "/api/v1/expert-handoff",
};

// A localhost base means the page is being read on a developer's own machine
// against a local Anril, not the real service. Say so, or a junior reading the
// page copies "http://localhost:8001" into production config.
const IS_LOCAL_API = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(:\d+)?/i.test(API_URL);

/* ── small UI pieces ─────────────────────────────────────────────── */

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can be blocked; the value stays selectable.
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      title={label}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition-colors ${
        copied
          ? "border-emerald-300 bg-emerald-50 text-emerald-700"
          : "border-border bg-white text-ink-secondary hover:border-primary-300 hover:text-ink"
      }`}
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {copied ? "Copied" : label}
    </button>
  );
}

function Value({ label, value, hint, mono = true }: { label: string; value: string; hint?: string; mono?: boolean }) {
  return (
    <div className="rounded-2xl border border-border-subtle bg-white p-4">
      <p className="font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted">{label}</p>
      <div className="mt-1.5 flex items-center gap-2">
        <code className={`min-w-0 flex-1 break-all rounded-lg bg-surface-subtle px-3 py-2 text-xs text-ink ${mono ? "font-mono" : "font-body"}`}>
          {value}
        </code>
        <CopyButton text={value} />
      </div>
      {hint && <p className="mt-1.5 font-body text-[11px] text-ink-muted">{hint}</p>}
    </div>
  );
}

function Section({ id, icon: Icon, title, intro, children }: {
  id: string;
  icon: React.ElementType;
  title: string;
  intro?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="card rounded-3xl p-6 scroll-mt-24">
      <div className="mb-4 flex items-start gap-3">
        <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
          <Icon size={16} />
        </span>
        <div>
          <h2 className="font-display text-lg font-bold text-ink">{title}</h2>
          {intro && <p className="mt-0.5 font-body text-sm text-ink-secondary">{intro}</p>}
        </div>
      </div>
      <div className="space-y-4 font-body text-sm text-ink-secondary">{children}</div>
    </section>
  );
}

function Code({ children, copy }: { children: string; copy?: boolean }) {
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-2xl border border-border-subtle bg-[#0A1528] p-4 font-mono text-[12px] leading-relaxed text-[#f5f3ef]">
        {children}
      </pre>
      {copy !== false && (
        <div className="absolute right-3 top-3">
          <CopyButton text={children} />
        </div>
      )}
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | React.ReactNode)[][] }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-border-subtle">
      <table className="w-full text-left text-xs">
        <thead className="bg-surface-subtle text-[11px] font-bold uppercase tracking-wider text-ink-muted">
          <tr>{head.map((h) => <th key={h} className="px-4 py-2.5">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-border-subtle">
          {rows.map((r, i) => (
            <tr key={i} className="align-top">
              {r.map((c, j) => (
                <td key={j} className={`px-4 py-2.5 ${j === 0 ? "font-mono text-ink" : "text-ink-secondary"}`}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── signature calculator (runs only in the browser) ─────────────── */

async function hmacSha256Hex(secret: string, body: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(body));
  return Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function SignatureCalculator({ tenantId, mode }: { tenantId: string; mode: PartnerSendMode | null }) {
  const sample = useMemo(
    () => JSON.stringify(
      mode === "event"
        ? { tenant_id: tenantId || "<tenant-id>", phone: "+919876543210", event: "purchased", name: "Priya", extra: { order_id: "INV-1042" }, reference: "order:1042" }
        : { tenant_id: tenantId || "<tenant-id>", template_code: "123456", phone: "+919876543210", variables: ["Ansar", "Free Question"], reference: "question:42" },
    ),
    [tenantId, mode],
  );
  const [secret, setSecret] = useState("");
  const [body, setBody] = useState(sample);
  const [sig, setSig] = useState("");

  useEffect(() => { setBody(sample); }, [sample]);
  useEffect(() => {
    let live = true;
    if (!secret) { setSig(""); return; }
    hmacSha256Hex(secret, body).then((h) => { if (live) setSig(h); }).catch(() => { if (live) setSig(""); });
    return () => { live = false; };
  }, [secret, body]);

  return (
    <div className="rounded-2xl border border-border-subtle bg-surface-subtle p-4">
      <p className="font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted">Signature calculator</p>
      <p className="mt-1 text-[11px] text-ink-muted">
        Runs in your browser only. Nothing you type here is sent anywhere. Use it to compare your code&apos;s signature against a known-good one.
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="block">
          <span className="text-[11px] font-semibold text-ink">Shared secret</span>
          <input
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder="paste the secret ops gave you"
            className="mt-1 w-full rounded-xl border border-border bg-white px-3 py-2 font-mono text-xs"
            autoComplete="off"
          />
        </label>
        <label className="block md:col-span-2">
          <span className="text-[11px] font-semibold text-ink">Raw request body (exact bytes you will send)</span>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-xl border border-border bg-white px-3 py-2 font-mono text-xs"
          />
        </label>
      </div>
      <div className="mt-3">
        <span className="text-[11px] font-semibold text-ink">X-Anril-Signature</span>
        <div className="mt-1 flex items-center gap-2">
          <code className="min-w-0 flex-1 break-all rounded-lg bg-white px-3 py-2 font-mono text-xs text-ink">
            {sig ? `sha256=${sig}` : "sha256=<enter the secret above>"}
          </code>
          {sig && <CopyButton text={`sha256=${sig}`} />}
        </div>
      </div>
    </div>
  );
}

/* ── code samples ────────────────────────────────────────────────── */

function samples(base: string, tenantId: string, path: string) {
  const tid = tenantId || "<tenant-id>";
  const curl = `BODY='{"tenant_id":"${tid}","template_code":"123456","phone":"+919876543210","variables":["Ansar","Free Question"],"reference":"question:42"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$ANRIL_SECRET" | sed 's/^.* //')
curl -X POST "${base}${path}" \\
  -H "Content-Type: application/json" \\
  -H "X-Anril-Signature: sha256=$SIG" \\
  --data "$BODY"`;

  const python = `import hmac, hashlib, json, requests

ANRIL_BASE = "${base}"
TENANT_ID = "${tid}"
SECRET = "<the shared secret>"          # keep it in an env var

def send_template(phone, template_code, variables=(), reference=""):
    body = json.dumps({
        "tenant_id": TENANT_ID,
        "template_code": template_code,   # the 6-digit Anril ID
        "phone": phone,
        "variables": list(variables),
        "reference": reference,
    }).encode()                            # sign EXACTLY these bytes
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    r = requests.post(
        ANRIL_BASE + "${path}",
        data=body,
        headers={"Content-Type": "application/json",
                 "X-Anril-Signature": f"sha256={sig}"},
        timeout=20,
    )
    return r.status_code, r.json()

print(send_template("+919876543210", "123456", ["Ansar", "Free Question"], "question:42"))`;

  const node = `import crypto from "node:crypto";

const ANRIL_BASE = "${base}";
const TENANT_ID = "${tid}";
const SECRET = process.env.ANRIL_SECRET;

export async function sendTemplate(phone, templateCode, variables = [], reference = "") {
  const body = JSON.stringify({
    tenant_id: TENANT_ID,
    template_code: templateCode,   // the 6-digit Anril ID
    phone,
    variables,
    reference,
  });                               // sign EXACTLY this string
  const sig = crypto.createHmac("sha256", SECRET).update(body).digest("hex");
  const res = await fetch(ANRIL_BASE + "${path}", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Anril-Signature": \`sha256=\${sig}\` },
    body,
  });
  return [res.status, await res.json()];
}`;

  return { curl, python, node };
}

/* ── page ────────────────────────────────────────────────────────── */

export default function DeveloperPage() {
  const [config, setConfig] = useState<PartnerConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"curl" | "python" | "node">("python");
  const privateSend = usePrivateSend();
  const { mode: sendMode, failed: sendModeFailed, setMode: setSendMode } = usePartnerSendMode();
  const isTemplateMode = sendMode === "template";

  const load = useCallback(async () => {
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/intake/partner/config`, { headers: auth });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setConfig(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load your connection details.");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const paths = config?.paths ?? DEFAULT_PATHS;
  const tenantId = config?.tenant_id ?? "";
  const code = samples(API_URL, tenantId, paths.send_template);

  return (
    <div className="w-full space-y-6 pb-16">
      {/* Header */}
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="max-w-prose font-body text-sm text-ink-secondary">
            Everything a developer needs to send WhatsApp messages from this account and to receive what Anril sends
            back. Read top to bottom once; the code samples at the end are ready to paste.
          </p>
        </div>
        <nav className="flex flex-wrap gap-1.5 text-[11px] font-semibold text-ink-secondary">
          {[
            ["which-door", "Which one?"],
            ...(privateSend ? [["send-from-server", "From your server"]] : []),
            ["connection", "Connection"], ["auth", "Signing"], ["send-template", "Send"],
            ["send-text", "Send text"],
            ...(isTemplateMode ? [["variables", "Variables"], ["anril-id", "Anril ID"]] : []),
            ["errors", "Errors"], ["callbacks", "Callbacks"],
            ...(isTemplateMode ? [["samples", "Code"]] : []),
            ["checklist", "Go-live"],
          ].map(([id, label]) => (
            <a key={id} href={`#${id}`} className="rounded-full border border-border bg-white px-2.5 py-1 hover:border-primary-300 hover:text-ink">{label}</a>
          ))}
        </nav>
      </div>

      {IS_LOCAL_API && (
        <div className="flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            <strong>Local test setup.</strong> This dashboard is talking to a copy of Anril on this machine ({API_URL}). Every URL on this page
            points there. The contract is the same on production; only the base URL changes, and your Anril contact gives you that one.
          </span>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          <AlertTriangle size={14} /> Could not load your connection details ({error}). The contract below is still correct.
        </div>
      )}

      <DoorChooser sendFromServerOn={privateSend !== null} />

      {/* 1. Connection */}
      <Section id="connection" icon={KeyRound} title="Your connection" intro="Three things identify your app to Anril. Two are shown here; the third is a secret that Anril's operations team gives you directly.">
        <div className="grid gap-3 md:grid-cols-2">
          <Value label="Tenant ID" value={tenantId || "loading…"} hint="Goes in every request body as tenant_id. It is your account's id inside Anril and is safe to keep in config." />
          <Value
            label={IS_LOCAL_API ? "API base URL — local test setup only" : "API base URL"}
            value={API_URL}
            hint={IS_LOCAL_API
              ? "This is a copy of Anril running on this machine, for testing only. It does not exist on production. For the live URL, ask your Anril contact; it looks like https://….aira…"
              : "Prefix for every path on this page. This is the live service."}
          />
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {[
            ["Shared secret", config?.secret_set, "Signs every request you send to Anril and every callback Anril sends you."],
            ["Your app's URL", config?.bridge_url_set, "Where Anril pushes paid consultations (only needed for the consultation flow)."],
            ["Your app's API key", config?.api_key_set, "Anril sends it as X-API-Key when it calls your app (consultation flow only)."],
          ].map(([label, set, hint]) => (
            <div key={String(label)} className="rounded-2xl border border-border-subtle bg-white p-4">
              <p className="font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted">{label as string}</p>
              <p className={`mt-1.5 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${set ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-500"}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${set ? "bg-emerald-500" : "bg-gray-400"}`} />
                {config ? (set ? "On file" : "Not set") : "…"}
              </p>
              <p className="mt-1.5 text-[11px] text-ink-muted">{hint as string}</p>
            </div>
          ))}
        </div>
        <p className="text-xs">
          The secret, your app&apos;s URL and API key are entered by Anril operations, not on this screen. If any shows
          &ldquo;Not set&rdquo;, ask your Anril contact. Never put the secret in a browser, a repository or a chat message.
        </p>
      </Section>

      {/* 2. Signing */}
      <Section id="auth" icon={ShieldCheck} title="How requests are signed" intro="There is no login and no token. Every request carries one header computed from the shared secret and the exact bytes of the body.">
        <ol className="list-decimal space-y-1.5 pl-5">
          <li>Build the JSON body, including <code className="font-mono">tenant_id</code>.</li>
          <li>Serialise it to bytes once. Sign <strong>those exact bytes</strong>; re-serialising on the way out, or pretty-printing, changes the signature.</li>
          <li>Compute HMAC-SHA256 with the shared secret as the key, hex-encoded, lower case.</li>
          <li>Send it as <code className="font-mono">X-Anril-Signature: sha256=&lt;hex&gt;</code> with <code className="font-mono">Content-Type: application/json</code>.</li>
        </ol>
        <p className="text-xs">
          Integrations built before the Anril rename used the header names <code className="font-mono">X-Aira-Signature</code> or <code className="font-mono">X-Astro-Signature</code>. Both are still accepted; new code should use <code className="font-mono">X-Anril-Signature</code>.
        </p>
        <p className="text-xs">
          A wrong signature, a missing header, an unknown tenant or no secret on file all return the <strong>same 401</strong>
          <code className="ml-1 font-mono">{`{"error":"Unauthorized","code":"unauthorized"}`}</code>. That is deliberate: it stops anyone probing which tenants exist.
          Non-JSON bodies return 400 <code className="font-mono">invalid_json</code>.
        </p>
        <SignatureCalculator tenantId={tenantId} mode={sendMode} />
      </Section>

      {/* 3. Send: one way per account, chosen here */}
      <Section
        id="send-template"
        icon={Send}
        title={sendMode === null ? "Send a WhatsApp message" : isTemplateMode ? "Send a WhatsApp template" : "Send a WhatsApp event"}
        intro={
          isTemplateMode
            ? "The call your app makes when a customer should get a message outside WhatsApp's 24-hour window: a receipt, a status change, an answer ready."
            : "Each account's app calls one signed address in one way: with a template ID or with an event. Pick this account's way below."
        }
      >
        {sendMode && <SendModePicker mode={sendMode} onSaved={setSendMode} />}
        {sendMode === null && sendModeFailed && (
          <ErrorLine message="Couldn't load how this account sends. Reload the page to try again." />
        )}
        {sendMode === null && !sendModeFailed && (
          <div className="h-24 animate-pulse rounded-2xl bg-border-subtle" aria-busy="true" aria-label="Loading send settings" />
        )}
        {isTemplateMode && (
          <>
          <Code copy>{`POST ${API_URL}${paths.send_template}`}</Code>
          <Table
            head={["Field", "Required", "Meaning"]}
            rows={[
              ["tenant_id", "yes", "Your Tenant ID from above."],
              ["template_code", "yes", "The 6-digit Anril ID of an APPROVED template (see Anril ID below)."],
              ["phone", "yes", <>Recipient. <code className="font-mono">+919876543210</code>, <code className="font-mono">919876543210</code> or a bare 10-digit Indian mobile all work.</>],
              ["variables", "no", "List of strings for the body placeholders {{1}}, {{2}}… in order. Extra values are dropped; too few is a 400."],
              ["reference", "no", "Up to 120 characters, stored with the log only. Use your own id (e.g. order:42) so you can trace a send later."],
            ]}
          />
          <p className="text-xs font-semibold text-ink">Success — HTTP 200</p>
          <Code copy={false}>{`{"ok": true, "message_id": "wamid.HBg…", "template": {"code": "123456", "name": "order_update", "language": "en"}}`}</Code>
          <p className="text-xs">
            <code className="font-mono">message_id</code> is Meta&apos;s id for the message. Keep it with your log; it is what support asks for when a message is questioned.
            Only templates whose placeholders are all in the body are supported: a template with a variable in the header or in a URL button is refused as
            <code className="ml-1 font-mono">unsupported_template</code>.
          </p>
          </>
        )}
        {sendMode === "event" && (
          <EventModeSubsection apiUrl={API_URL} sendTemplatePath={paths.send_template} tenantId={tenantId} />
        )}
      </Section>

      {/* 4. Send text */}
      <Section id="send-text" icon={Send} title="Send a plain text message" intro="Free text is only delivered by WhatsApp inside the 24-hour window after the customer last wrote to this number. Outside it, use a template.">
        <Code copy>{`POST ${API_URL}${paths.send_text}`}</Code>
        <Table
          head={["Field", "Required", "Meaning"]}
          rows={[
            ["tenant_id", "yes", "Your Tenant ID."],
            ["phone", "yes", "Recipient, same formats as above."],
            ["text", "yes", "1 to 4096 characters."],
            ["reference", "no", "Same as for templates."],
          ]}
        />
        <Code copy={false}>{`{"ok": true, "message_id": "wamid.HBg…"}`}</Code>
      </Section>

      {isTemplateMode && (
        <>
          {/* 5. Variables */}
          <Section id="variables" icon={Hash} title="Template variables" intro="A template's body may contain numbered placeholders. Your values fill them in order.">
            <ul className="list-disc space-y-1.5 pl-5">
              <li><code className="font-mono">variables[0]</code> fills <code className="font-mono">{"{{1}}"}</code>, <code className="font-mono">variables[1]</code> fills <code className="font-mono">{"{{2}}"}</code>, and so on.</li>
              <li>Send <strong>more</strong> values than the template has placeholders and the extras are ignored. This lets your app always send one fixed set and let each template pick what it uses.</li>
              <li>Send <strong>fewer</strong> and the request is refused with 400 <code className="font-mono">variables_mismatch</code>, because WhatsApp would refuse it too.</li>
              <li>Values must not contain new lines or tabs, and WhatsApp limits each to 1024 characters. Collapse whitespace before sending.</li>
            </ul>
            <p className="text-xs">
              A good pattern: decide one fixed set for your whole app, for example <code className="font-mono">[customer name, order or service name, your brand]</code>, and send it on every call.
              A template written as &ldquo;Hi <code className="font-mono">{"{{1}}"}</code>, your <code className="font-mono">{"{{2}}"}</code> is ready&rdquo; uses the first two; one with no placeholders uses none. Same code, no per-template logic.
            </p>
          </Section>

          {/* 6. Anril ID */}
          <Section id="anril-id" icon={Hash} title="Where the Anril ID comes from" intro="Every template in this account has a 6-digit Anril ID. It is what your app stores and sends as template_code.">
            <ul className="list-disc space-y-1.5 pl-5">
              <li>Open <strong>Templates</strong> in this dashboard. Each card, table row and detail view shows the ID with a copy button. The search box also finds a template by its ID.</li>
              <li>Only an <strong>APPROVED</strong> template can be sent. A pending or rejected one returns 409 <code className="font-mono">template_not_approved</code>.</li>
              <li>The ID is unique inside this account only. Another Anril account, or a separate test installation, gives the same WhatsApp template a different number. Always copy the ID from the account you are sending through.</li>
              <li>Templates themselves are created and submitted to Meta from the Templates page. Your app never creates templates through this API.</li>
            </ul>
          </Section>
        </>
      )}

      {/* 7. Errors */}
      <Section id="errors" icon={AlertTriangle} title="Error codes" intro="Every error is JSON with ok:false, a stable code for your program and a readable error for your log.">
        <Table
          head={["HTTP", "code", "When"]}
          rows={[
            ["401", "unauthorized", "Bad or missing signature, unknown tenant_id, or no secret on file. Always identical."],
            ["400", "invalid_json", "Body is not valid JSON."],
            ["400", "invalid_request", "template_code missing (event on an Event account), variables not a list, text empty or too long."],
            ["400", "wrong_mode", "The call does not match how this account sends: an event on a Template ID account, or a template_code on an Event account. Switch the setting in Send above, or change the call."],
            ["400", "invalid_phone", "Phone could not be read as a mobile number."],
            ["400", "variables_mismatch", "Fewer values than the template's placeholders."],
            ["400", "unsupported_template", "Template has a header or URL-button variable."],
            ["404", "template_not_found", "No template in this account with that Anril ID."],
            ["409", "template_not_approved", "Template exists but Meta has not approved it."],
            ["502", "meta_error", "WhatsApp refused the send. error carries Meta's own message, e.g. an expired access token or a number that is not on WhatsApp."],
          ]}
        />
        <p className="text-xs">Treat 502 as retryable after a pause, 401 and 4xx as bugs on the calling side to fix, not retry.</p>
      </Section>

      {/* 8. Callbacks */}
      <Section id="callbacks" icon={Reply} title="Expert hand-off: what Anril sends to your app" intro="An optional feature, switched on by Anril operations. Skip this section if your app only sends notifications.">
        <p>
          With hand-off on, when a customer pays inside WhatsApp for a question that your own experts answer, Anril pushes that paid request to your app. When your expert has answered, your app tells Anril, and Anril notifies the customer on WhatsApp.
        </p>
        <Table
          head={["Direction", "Call", "Auth"]}
          rows={[
            ["Anril → your app", <>POST to your hand-off endpoint (its URL is on file with operations) with the paid request: <code className="font-mono">external_ref</code> (the idempotency key, so one request is never two records), <code className="font-mono">phone</code>, <code className="font-mono">customer_name</code>, the details the customer entered (<code className="font-mono">person_*</code> fields), <code className="font-mono">question_text</code>, <code className="font-mono">amount</code>, <code className="font-mono">tenant_id</code>. Reply <code className="font-mono">{`{success:true, question_id, …}`}</code>.</>, "X-API-Key: your app's API key"],
            ["Your app → Anril", <>POST <code className="font-mono">{API_URL}{paths.reply_callback}</code> with <code className="font-mono">external_ref</code>, <code className="font-mono">reply_text</code>, the expert&apos;s name as <code className="font-mono">astrologer_name</code>, and <code className="font-mono">replied_at</code>. Anril notifies the customer. A repeat of the same reply returns <code className="font-mono">duplicate:true</code>; do not retry.</>, "X-Anril-Signature, same as above"],
          ]}
        />
        <p className="text-xs">
          Operations enter your app&apos;s URL and API key on their side (the two &ldquo;On file&rdquo; badges at the top). The paths above and the
          legacy prefix <code className="font-mono">{paths.legacy_prefix}</code> are kept stable; an existing integration on the old prefix keeps working.
        </p>
      </Section>

      {isTemplateMode && (
        <>
          {/* 9. Code samples */}
          <Section id="samples" icon={Code2} title="Code samples" intro="Each one sends a template with two values. Your Tenant ID and the real URL are already filled in.">
            <div className="flex gap-1 rounded-xl bg-surface-subtle p-1 text-xs font-semibold">
              {(["python", "node", "curl"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTab(t)}
                  className={`rounded-lg px-3 py-1.5 transition-colors ${tab === t ? "bg-white text-primary shadow-sm" : "text-ink-muted hover:text-ink"}`}
                >
                  {t === "python" ? "Python" : t === "node" ? "Node.js" : "curl"}
                </button>
              ))}
            </div>
            <Code copy>{code[tab]}</Code>
            {IS_LOCAL_API && (
              <p className="text-xs text-amber-800">
                The URL in this sample is a local test copy of Anril. Replace it with the live base URL from your Anril contact before deploying.
              </p>
            )}
            <p className="text-xs">
              Call it from a background job or a thread, never on the request that your own user is waiting on: a slow network to Anril must not slow your app down.
              Keep a log row per send with your <code className="font-mono">reference</code>, the returned <code className="font-mono">message_id</code> and any error.
            </p>
          </Section>
        </>
      )}

      {/* 10. Checklist */}
      <Section id="checklist" icon={ListChecks} title="Go-live checklist">
        <ol className="list-decimal space-y-1.5 pl-5">
          <li>Shared secret received from Anril operations and stored in your server&apos;s environment, not in code.</li>
          <li>Tenant ID and API base URL from the top of this page in your config.</li>
          <li>Your signature matches the calculator above for the same body and secret.</li>
          {sendMode === "event" ? (
            <li>Every event your app sends has a message set on the <strong>Auto Messages</strong> page, and its template shows <strong>APPROVED</strong>.</li>
          ) : (
            <>
              <li>The templates you need exist under <strong>Templates</strong> and show <strong>APPROVED</strong>.</li>
              <li>Each template&apos;s Anril ID is stored where your app can change it without a deploy.</li>
            </>
          )}
          <li>One test send to your own number returns <code className="font-mono">ok:true</code> and arrives on the phone.</li>
          <li>Your app logs every send with its reference, message id and error, and switches a message off without a deploy.</li>
        </ol>
      </Section>

      <SendFromServerSection status={privateSend} />
    </div>
  );
}

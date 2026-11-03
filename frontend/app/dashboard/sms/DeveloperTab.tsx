"use client";

import { useState } from "react";
import { Copy, Eye, EyeOff, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { OTP_EXPIRY_RANGE, OTP_EXTRA_MAX, OTP_LENGTH_RANGE, friendlyError, parseOtpSettings } from "./helpers";
import { Btn, Card, CardHeader, Field, Notice, inputCls, textareaCls } from "./ui";
import { usePerm } from "./usePerm";

export function DeveloperTab() {
  return (
    <div className="space-y-4">
      <ApiKeyCard />
      <OtpConsole />
      <ManualSendCard />
    </div>
  );
}

function ApiKeyCard() {
  const { isOwner } = usePerm();
  const [key, setKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reveal() {
    setBusy(true);
    setError(null);
    try {
      setKey((await api.sms.developerKey()).api_key);
    } catch (err) {
      setError(friendlyError(err, "Couldn't load the key"));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!key) return;
    try {
      await navigator.clipboard.writeText(key);
      toast.success("Key copied.");
    } catch {
      toast.error("Couldn't copy. Select the key and copy it by hand.");
    }
  }

  return (
    <Card>
      <CardHeader
        title="API key"
        hint="For developers who want to send SMS from their own software."
        action={
          <a href="https://docs.bulk9.com" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-sm font-bold text-primary hover:underline">
            API docs <ExternalLink size={13} />
          </a>
        }
      />
      <div className="space-y-3 p-4 sm:p-5">
        {!isOwner ? (
          <Notice tone="info">Only the account owner can see the API key.</Notice>
        ) : (
          <>
            <Notice tone="warn">Anyone with this key can send SMS from your balance.</Notice>
            {error && <Notice tone="danger">{error}</Notice>}
            {key ? (
              <div className="flex flex-wrap items-center gap-2">
                <code className="min-w-0 flex-1 break-all rounded-xl bg-[#f8fafc] px-3 py-2.5 text-sm text-[#0A1528]">{key}</code>
                <Btn variant="outline" onClick={() => void copy()}>
                  <Copy size={14} /> Copy
                </Btn>
                <Btn variant="outline" onClick={() => setKey(null)}>
                  <EyeOff size={14} /> Hide
                </Btn>
              </div>
            ) : (
              <Btn variant="outline" busy={busy} onClick={() => void reveal()}>
                <Eye size={14} /> Show API key
              </Btn>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

function OtpConsole() {
  const { canManage } = usePerm();
  const [mobile, setMobile] = useState("");
  const [otpId, setOtpId] = useState("");
  const [otp, setOtp] = useState("");
  const [otpLength, setOtpLength] = useState("6");
  const [otpExpiry, setOtpExpiry] = useState("15");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState<"send" | "verify" | "resend" | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  async function run(kind: "send" | "verify" | "resend") {
    if (busy) return;
    setResult(null);
    const settings = parseOtpSettings({ length: otpLength, expiry: otpExpiry, extra });
    if (kind === "send" && settings.error !== null) {
      setResult({ ok: false, text: settings.error });
      return;
    }
    setBusy(kind);
    try {
      const m = mobile.trim();
      let res;
      if (kind === "send" && settings.error === null) {
        res = await api.sms.otpSend({ mobile: m, otp_id: otpId.trim(), otp_length: settings.length, otp_expiry: settings.expiry, variables_values: settings.extra });
      } else if (kind === "verify") {
        res = await api.sms.otpVerify({ mobile: m, otp: otp.trim() });
      } else {
        res = await api.sms.otpResend({ mobile: m });
      }
      setResult({ ok: res.ok, text: res.message || (res.ok ? "Done." : "That didn't work.") });
    } catch (err) {
      setResult({ ok: false, text: friendlyError(err, "That didn't go through.") });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader title="OTP test console" hint="Try the OTP flow with your own number. Each send uses SMS from your balance." />
      <div className="space-y-3 p-4 sm:p-5">
        {!canManage ? (
          <Notice tone="info">You need SMS manage access to use the test console.</Notice>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Mobile number" hint="10 digits, or with +91">
                <input className={inputCls} inputMode="tel" value={mobile} onChange={(e) => setMobile(e.target.value)} />
              </Field>
              <Field label="OTP template ID" hint="The OTP id from your approved OTP template">
                <input className={inputCls} value={otpId} onChange={(e) => setOtpId(e.target.value)} />
              </Field>
              <Field label="OTP received">
                <input className={inputCls} inputMode="numeric" maxLength={8} value={otp} onChange={(e) => setOtp(e.target.value)} />
              </Field>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="OTP length" hint={`${OTP_LENGTH_RANGE.min} to ${OTP_LENGTH_RANGE.max} digits`}>
                <input className={inputCls} type="number" inputMode="numeric" min={OTP_LENGTH_RANGE.min} max={OTP_LENGTH_RANGE.max} value={otpLength} onChange={(e) => setOtpLength(e.target.value)} />
              </Field>
              <Field label="Expires after (minutes)" hint={`${OTP_EXPIRY_RANGE.min} to ${OTP_EXPIRY_RANGE.max.toLocaleString("en-IN")} minutes`}>
                <input className={inputCls} type="number" inputMode="numeric" min={OTP_EXPIRY_RANGE.min} max={OTP_EXPIRY_RANGE.max} value={otpExpiry} onChange={(e) => setOtpExpiry(e.target.value)} />
              </Field>
              <Field label="Extra message values (optional)" hint="Values for other {#var#} in your OTP template, separated by |">
                <input className={inputCls} maxLength={OTP_EXTRA_MAX} value={extra} onChange={(e) => setExtra(e.target.value)} />
              </Field>
            </div>
            <div className="flex flex-wrap gap-2">
              <Btn busy={busy === "send"} disabled={!mobile.trim() || !otpId.trim() || !!busy} onClick={() => void run("send")}>
                Send OTP
              </Btn>
              <Btn variant="outline" busy={busy === "verify"} disabled={!mobile.trim() || !otp.trim() || !!busy} onClick={() => void run("verify")}>
                Verify
              </Btn>
              <Btn variant="outline" busy={busy === "resend"} disabled={!mobile.trim() || !!busy} onClick={() => void run("resend")}>
                Resend
              </Btn>
            </div>
            {result && <Notice tone={result.ok ? "success" : "danger"}>{result.text}</Notice>}
          </>
        )}
      </div>
    </Card>
  );
}

function ManualSendCard() {
  const { canManage } = usePerm();
  const [form, setForm] = useState({ sender_id: "", entity_id: "", template_id: "", message: "", mobile: "" });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  if (!canManage) return null;

  const set = (key: keyof typeof form) => (value: string) => setForm((f) => ({ ...f, [key]: value }));
  const complete = Object.values(form).every((v) => v.trim());

  async function send() {
    if (busy || !complete) return;
    setBusy(true);
    setResult(null);
    try {
      const res = await api.sms.manualSend({
        sender_id: form.sender_id.trim(),
        entity_id: form.entity_id.trim(),
        template_id: form.template_id.trim(),
        message: form.message,
        mobile: form.mobile.trim(),
      });
      const id = res.request_id ? ` Request ID: ${res.request_id}` : "";
      setResult({ ok: res.ok, text: `${res.message || (res.ok ? "SMS sent." : "That didn't work.")}${id}` });
    } catch (err) {
      setResult({ ok: false, text: friendlyError(err, "That didn't go through.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Send one SMS with DLT IDs"
        hint="For testing an approved template that isn't in your template list. The wording must match DLT exactly or it will fail."
      />
      <div className="space-y-3 p-4 sm:p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Sender ID">
            <input className={inputCls} value={form.sender_id} onChange={(e) => set("sender_id")(e.target.value)} />
          </Field>
          <Field label="DLT entity ID">
            <input className={inputCls} value={form.entity_id} onChange={(e) => set("entity_id")(e.target.value)} />
          </Field>
          <Field label="DLT template ID">
            <input className={inputCls} value={form.template_id} onChange={(e) => set("template_id")(e.target.value)} />
          </Field>
        </div>
        <Field label="Message" hint="Exact approved wording">
          <textarea className={textareaCls} rows={3} value={form.message} onChange={(e) => set("message")(e.target.value)} />
        </Field>
        <Field label="Mobile number" hint="10 digits, or with +91" className="sm:max-w-xs">
          <input className={inputCls} inputMode="tel" value={form.mobile} onChange={(e) => set("mobile")(e.target.value)} />
        </Field>
        <Btn busy={busy} disabled={!complete} onClick={() => void send()}>
          Send SMS
        </Btn>
        {result && <Notice tone={result.ok ? "success" : "danger"}>{result.text}</Notice>}
      </div>
    </Card>
  );
}

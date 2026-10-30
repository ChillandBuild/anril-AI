"use client";

import { useState } from "react";
import { Copy, Eye, EyeOff, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { friendlyError } from "./helpers";
import { Btn, Card, CardHeader, Field, Notice, inputCls } from "./ui";
import { usePerm } from "./usePerm";

export function DeveloperTab() {
  return (
    <div className="space-y-4">
      <ApiKeyCard />
      <OtpConsole />
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
  const [busy, setBusy] = useState<"send" | "verify" | "resend" | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  async function run(kind: "send" | "verify" | "resend") {
    if (busy) return;
    setBusy(kind);
    setResult(null);
    try {
      const m = mobile.trim();
      const res =
        kind === "send"
          ? await api.sms.otpSend({ mobile: m, otp_id: otpId.trim() })
          : kind === "verify"
            ? await api.sms.otpVerify({ mobile: m, otp: otp.trim() })
            : await api.sms.otpResend({ mobile: m });
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

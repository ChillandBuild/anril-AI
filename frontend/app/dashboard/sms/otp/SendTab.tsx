"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, type OtpMode, type OtpOverview, type OtpVerifyResult, type OtpView } from "@/lib/api";
import { formatCount } from "../helpers";
import { usePerm } from "../usePerm";
import { Badge, Btn, Card, CardHeader, Field, LoadError, Notice, Skeleton, inputCls } from "../ui";
import { ChannelBadge, ModePicker, OTP_BASE, OTP_OVERVIEW_KEY, ResultBadge, otpError, otpIsSettled } from "./otpShared";

const POLL_INTERVAL_MS = 3000;
const POLL_WINDOW_MS = 2 * 60 * 1000;

export function SendTab() {
  const { canManage } = usePerm();
  const { data, error, isLoading, mutate } = useSWR(OTP_OVERVIEW_KEY, () => api.otp.overview(), { revalidateOnFocus: false });

  if (error && !data) {
    return (
      <Card>
        <LoadError message={otpError(error, "Try again in a moment.")} onRetry={() => void mutate()} />
      </Card>
    );
  }
  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40" />
        <Skeleton className="h-96" />
      </div>
    );
  }
  return <SendContent overview={data} canManage={canManage} />;
}

function SendContent({ overview, canManage }: { overview: OtpOverview; canManage: boolean }) {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [pick, setPick] = useState<OtpMode | null>(null);
  const [ownCode, setOwnCode] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [result, setResult] = useState<OtpView | null>(null);
  // Latest copy of the result from polling, or a verify outcome; `result` is what the send returned.
  const [live, setLive] = useState<OtpView | null>(null);
  const [code, setCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [verdict, setVerdict] = useState<OtpVerifyResult | null>(null);
  const [verifyError, setVerifyError] = useState("");

  const mode: OtpMode = pick ?? overview.settings.default_mode;
  const shown = result && live?.otp_id === result.otp_id ? live : result;

  // Poll the request every 3 s for up to 2 minutes while channels are still moving.
  useEffect(() => {
    if (!result || otpIsSettled(result)) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const started = Date.now();
    const tick = async () => {
      try {
        const { item } = await api.otp.historyItem(result.otp_id);
        if (cancelled) return;
        setLive(item);
        if (otpIsSettled(item)) return;
      } catch {
        // A missed check is fine; the next one tries again.
      }
      if (!cancelled && Date.now() - started < POLL_WINDOW_MS) timer = setTimeout(tick, POLL_INTERVAL_MS);
    };
    timer = setTimeout(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [result]);

  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSending(true);
    setSendError("");
    setResult(null);
    setLive(null);
    setCode("");
    setVerdict(null);
    setVerifyError("");
    try {
      const res = await api.otp.send({ phone: phone.trim(), mode, code: ownCode.trim() || undefined });
      setResult(res);
    } catch (err) {
      setSendError(otpError(err, "Couldn't send the code. Try again."));
    } finally {
      setSending(false);
    }
  }

  async function verify() {
    if (!shown) return;
    setVerifying(true);
    setVerifyError("");
    setVerdict(null);
    try {
      const res = await api.otp.verify({ otp_id: shown.otp_id, code: code.trim() });
      setVerdict(res);
      if (res.verified) setLive({ ...shown, status: "verified" });
    } catch (err) {
      setVerifyError(otpError(err, "Couldn't check the code. Try again."));
    } finally {
      setVerifying(false);
    }
  }

  const notRequested = overview.not_requested_7d;
  const failedUpdates = overview.failed_updates_7d;

  return (
    <div className="space-y-4">
      {notRequested > 0 && (
        <Notice tone="warn">
          {`${formatCount(notRequested)} ${notRequested === 1 ? "customer said" : "customers said"} they didn't ask for a code this week. Check History for numbers being misused.`}
        </Notice>
      )}
      {failedUpdates > 0 && (
        <Notice tone="warn">
          {`${formatCount(failedUpdates)} ${failedUpdates === 1 ? "status update couldn't" : "status updates couldn't"} reach your server this week.`}
        </Notice>
      )}

      <Card>
        <CardHeader title="Channels" hint="Where codes can go. A way of sending works only when its channels are ready." />
        <div className="divide-y divide-[#e2e8f0] px-4 sm:px-5">
          <ChannelRow name="SMS" ready={overview.channels.sms.ready} problem={overview.channels.sms.problem} onOpenSettings={() => router.push(`${OTP_BASE}?tab=settings`)} />
          <ChannelRow name="WhatsApp" ready={overview.channels.whatsapp.ready} problem={overview.channels.whatsapp.problem} onOpenSettings={() => router.push(`${OTP_BASE}?tab=settings`)} />
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
        {canManage ? (
          <Card>
            <CardHeader title="Send a test code" hint="Sends a real code to the number you type." />
            <form onSubmit={send} className="space-y-4 p-4 sm:p-5">
              <Field label="Phone number" hint="With country code, e.g. +91 98765 43210">
                <input className={inputCls} type="tel" inputMode="tel" autoComplete="off" value={phone} onChange={(e) => setPhone(e.target.value)} />
              </Field>
              <div>
                <span className="mb-1 block text-xs font-bold text-[#334155]">How to send</span>
                <ModePicker value={mode} onChange={setPick} disabled={sending} />
              </div>
              <Field label="Your own code (optional)" hint="Leave empty and Anril makes the code. Fill it to test 'my server makes the code'.">
                <input className={inputCls} inputMode="numeric" autoComplete="off" maxLength={10} value={ownCode} onChange={(e) => setOwnCode(e.target.value)} />
              </Field>
              {sendError && <Notice tone="danger">{sendError}</Notice>}
              <div className="flex justify-end">
                <Btn type="submit" busy={sending} disabled={!phone.trim()}>
                  Send code
                </Btn>
              </div>
            </form>
          </Card>
        ) : (
          <Notice tone="info">Only people with SMS permission can send test codes. Ask the account owner.</Notice>
        )}

        {shown && (
          <Card>
            <CardHeader title="Result" hint={`Sent to ${shown.phone}`} />
            <div className="space-y-4 p-4 sm:p-5">
              <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-3 text-sm">
                <dt className="font-bold text-[#334155]">SMS</dt>
                <dd>
                  <ChannelBadge status={shown.sms.status} />
                  {shown.sms.error && <p className="mt-1 break-words text-xs text-danger">{shown.sms.error}</p>}
                </dd>
                <dt className="font-bold text-[#334155]">WhatsApp</dt>
                <dd>
                  <ChannelBadge status={shown.whatsapp.status} />
                  {shown.whatsapp.error && <p className="mt-1 break-words text-xs text-danger">{shown.whatsapp.error}</p>}
                </dd>
                <dt className="font-bold text-[#334155]">Overall</dt>
                <dd className="flex flex-wrap items-center gap-2">
                  <ResultBadge status={shown.status} />
                  {shown.whatsapp_backup_sent && <Badge tone="info">WhatsApp backup sent</Badge>}
                  {shown.not_requested && shown.status !== "not_requested" && <Badge tone="danger">Didn&apos;t ask for it</Badge>}
                </dd>
              </dl>
              {!otpIsSettled(shown) && <p className="text-xs text-[#64748b]">Updates appear here on their own.</p>}

              {shown.source === "anril" ? (
                <div className="space-y-3 border-t border-[#e2e8f0] pt-4">
                  <Field label="Check the code" hint="Type the code the customer got, to test it.">
                    <input
                      className={inputCls}
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={10}
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                    />
                  </Field>
                  <div className="flex justify-end">
                    <Btn variant="outline" busy={verifying} disabled={!code.trim()} onClick={() => void verify()}>
                      Verify
                    </Btn>
                  </div>
                  {verifyError && <Notice tone="danger">{verifyError}</Notice>}
                  {verdict?.verified && <Notice tone="success">Code is correct</Notice>}
                  {verdict && !verdict.verified && (
                    <Notice tone="danger">
                      {`${verdict.message ?? "That code isn't right."} ${verdict.attempts_left} ${verdict.attempts_left === 1 ? "try" : "tries"} left.`}
                    </Notice>
                  )}
                </div>
              ) : (
                <Notice tone="info">Your server made this code, so Anril doesn&apos;t check it. Check it on your side.</Notice>
              )}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function ChannelRow({
  name,
  ready,
  problem,
  onOpenSettings,
}: {
  name: string;
  ready: boolean;
  problem: string | null;
  onOpenSettings: () => void;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-bold text-[#0A1528]">{name}</p>
          <Badge tone={ready ? "success" : "warn"}>{ready ? "Ready" : "Not set up"}</Badge>
        </div>
        {!ready && problem && <p className="mt-1 break-words text-xs text-[#64748b]">{problem}</p>}
      </div>
      {!ready && (
        <Btn variant="link" onClick={onOpenSettings}>
          Open settings
        </Btn>
      )}
    </div>
  );
}

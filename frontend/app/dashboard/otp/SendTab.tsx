"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { ChevronDown, Phone, Radio, Route, Send } from "lucide-react";
import { api, type OtpMode, type OtpOverview, type OtpVerifyResult, type OtpView } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatCount, formatIst } from "../sms/helpers";
import { usePerm } from "../sms/usePerm";
import { Btn, Field, LoadError, Notice, Skeleton, inputCls } from "../sms/ui";
import { OTP_BASE, OTP_OVERVIEW_KEY, modeShortLabel, otpError, otpIsSettled, otpTimeline, sourceLabel } from "./otpShared";
import { ChannelIcon, ModeCards, ResultStatus, SectionCard, StatusPill, Timeline } from "./otpUi";

const POLL_INTERVAL_MS = 3000;
const POLL_WINDOW_MS = 2 * 60 * 1000;

export function SendTab() {
  const { canManage } = usePerm();
  const { data, error, isLoading, mutate } = useSWR(OTP_OVERVIEW_KEY, () => api.otp.overview(), { revalidateOnFocus: false });

  if (error && !data) {
    return (
      <div className="rounded-2xl border border-[#e2e8f0] bg-white shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
        <LoadError message={otpError(error, "Try again in a moment.")} onRetry={() => void mutate()} />
      </div>
    );
  }
  if (isLoading || !data) {
    return (
      <div className="space-y-6">
        <div className="grid gap-4 md:grid-cols-3">
          <Skeleton className="h-24 rounded-2xl" />
          <Skeleton className="h-24 rounded-2xl" />
          <Skeleton className="h-24 rounded-2xl" />
        </div>
        <div className="grid gap-6 lg:grid-cols-2">
          <Skeleton className="h-96 rounded-2xl" />
          <Skeleton className="h-96 rounded-2xl" />
        </div>
      </div>
    );
  }
  return <SendContent overview={data} canManage={canManage} />;
}

function SendContent({ overview, canManage }: { overview: OtpOverview; canManage: boolean }) {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [pick, setPick] = useState<OtpMode | null>(null);
  const [ownOpen, setOwnOpen] = useState(false);
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

  function toggleOwnCode() {
    // Collapsing clears the field, so a hidden code is never sent.
    setOwnOpen((open) => {
      if (open) setOwnCode("");
      return !open;
    });
  }

  const notRequested = overview.not_requested_7d;
  const failedUpdates = overview.failed_updates_7d;
  const settingsHref = `${OTP_BASE}/settings`;
  const { sms, whatsapp } = overview.channels;

  return (
    <div className="space-y-6">
      {/* Status row. minmax(0,…) lets the truncated lines shrink instead of widening the page on phones. */}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-[repeat(3,minmax(0,1fr))]">
        <ChannelCard
          channel="sms"
          name="SMS"
          ready={sms.ready}
          problem={sms.problem}
          readyLine={`Sender ${overview.settings.sms_sender_id ?? "—"} · Template ${overview.settings.sms_message_id ?? "—"}`}
          onOpenSettings={() => router.push(settingsHref)}
        />
        <ChannelCard
          channel="whatsapp"
          name="WhatsApp"
          ready={whatsapp.ready}
          problem={whatsapp.problem}
          readyLine={`Template ${overview.settings.wa_template_name ?? "—"} (${overview.settings.wa_template_language ?? "—"})`}
          onOpenSettings={() => router.push(settingsHref)}
        />
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
          <div className="flex items-start gap-3">
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary" aria-hidden="true">
              <Route size={16} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold text-[#0A1528]">Default way</p>
              <p className="mt-1 truncate text-xs text-[#64748b]">{modeShortLabel(overview.settings.default_mode)}</p>
            </div>
            <Btn variant="link" className="shrink-0" onClick={() => router.push(settingsHref)}>
              Change
            </Btn>
          </div>
        </div>
      </div>

      {(notRequested > 0 || failedUpdates > 0) && (
        <div className="space-y-3">
          {notRequested > 0 && (
            <Notice tone="warn">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span>{`${formatCount(notRequested)} ${notRequested === 1 ? "customer said" : "customers said"} they didn't ask for a code this week. Check History for numbers being misused.`}</span>
                <Btn variant="link" onClick={() => router.push(`${OTP_BASE}/history?status=not_requested`)}>
                  Review in History
                </Btn>
              </div>
            </Notice>
          )}
          {failedUpdates > 0 && (
            <Notice tone="warn">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span>{`${formatCount(failedUpdates)} ${failedUpdates === 1 ? "status update couldn't" : "status updates couldn't"} reach your server this week.`}</span>
                <Btn variant="link" onClick={() => router.push(settingsHref)}>
                  Open settings
                </Btn>
              </div>
            </Notice>
          )}
        </div>
      )}

      {/* Work area */}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[repeat(2,minmax(0,1fr))] lg:items-start">
        <SectionCard title="Send a test code" description="Sends a real code to a phone you have. It uses your SMS balance or WhatsApp.">
          {canManage ? (
            <form onSubmit={send} className="space-y-5">
              <Field label="Phone number" hint="With country code, e.g. +91 98765 43210">
                <div className="relative">
                  <Phone size={16} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
                  <input
                    className={cn(inputCls, "pl-9")}
                    type="tel"
                    inputMode="tel"
                    autoComplete="off"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    disabled={sending}
                  />
                </div>
              </Field>

              <div>
                <p className="mb-2 text-xs font-bold text-[#334155]">How to send</p>
                <ModeCards value={mode} onChange={setPick} disabled={sending} />
              </div>

              <div className="space-y-3">
                <button
                  type="button"
                  aria-expanded={ownOpen}
                  onClick={toggleOwnCode}
                  className="inline-flex items-center gap-1.5 rounded-md text-sm font-semibold text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                >
                  Use my own code
                  <ChevronDown size={16} aria-hidden="true" className={cn("transition-transform", ownOpen && "rotate-180")} />
                </button>
                {ownOpen && (
                  <Field label="Your own code" hint="Leave empty and Anril makes the code. Fill it to test codes made by your server.">
                    <input
                      className={inputCls}
                      inputMode="numeric"
                      autoComplete="off"
                      maxLength={10}
                      value={ownCode}
                      onChange={(e) => setOwnCode(e.target.value)}
                      disabled={sending}
                    />
                  </Field>
                )}
              </div>

              {sendError && <Notice tone="danger">{sendError}</Notice>}

              <div className="flex justify-stretch sm:justify-end">
                <Btn type="submit" busy={sending} disabled={!phone.trim()} className="w-full sm:w-auto">
                  <Send size={14} aria-hidden="true" />
                  Send code
                </Btn>
              </div>
            </form>
          ) : (
            <div className="rounded-xl bg-[#f8fafc] p-4 text-sm text-[#64748b]">
              Only people with SMS permission can send test codes. Ask the account owner.
            </div>
          )}
        </SectionCard>

        <SectionCard title="Live result">
          {!shown ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-[#f1f5f9]" aria-hidden="true">
                <Radio size={20} className="text-[#64748b]" />
              </span>
              <p className="mt-4 text-sm font-bold text-[#0A1528]">Nothing sent yet</p>
              <p className="mt-1 text-xs text-[#64748b]">Send a test code and watch each step here as it happens.</p>
            </div>
          ) : (
            <div>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <p className="font-display text-lg font-bold tabular-nums text-[#0A1528]">{shown.phone}</p>
                <ResultStatus status={shown.status} />
              </div>
              <p className="mt-1 text-xs text-[#64748b]">
                {`${modeShortLabel(shown.mode)} · Made by ${sourceLabel(shown.source)} · Expires ${formatIst(shown.expires_at)}`}
              </p>
              {shown.not_requested && shown.status !== "not_requested" && (
                <div className="mt-2">
                  <StatusPill tone="danger">Didn&apos;t ask for it</StatusPill>
                </div>
              )}
              {!otpIsSettled(shown) && (
                <p className="mt-3 flex items-center gap-2 text-xs text-[#64748b]">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                  Updates appear here on their own.
                </p>
              )}

              <div className="mt-5">
                <Timeline items={otpTimeline(shown, formatIst)} />
              </div>

              {shown.source === "anril" ? (
                <div className="mt-5 space-y-4 border-t border-[#eef2f6] pt-5">
                  <div>
                    <p className="text-sm font-bold text-[#0A1528]">Check the code</p>
                    <p className="mt-0.5 text-xs text-[#64748b]">Type the code the phone got.</p>
                  </div>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                    <div className="min-w-0 flex-1">
                      <input
                        aria-label="Code to check"
                        className={cn(inputCls, "h-12 text-center font-mono text-xl tracking-[0.35em]")}
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={10}
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                      />
                    </div>
                    <Btn variant="outline" busy={verifying} disabled={!code.trim()} onClick={() => void verify()} className="h-12 w-full sm:w-auto">
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
                <div className="mt-5 border-t border-[#eef2f6] pt-5">
                  <Notice tone="info">Your server made this code, so Anril doesn&apos;t check it. Check it on your side.</Notice>
                </div>
              )}

              <div className="mt-5 flex justify-end border-t border-[#eef2f6] pt-4">
                <Btn variant="link" onClick={() => router.push(`${OTP_BASE}/history?open=${shown.otp_id}`)}>
                  Open in History →
                </Btn>
              </div>
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}

function ChannelCard({
  channel,
  name,
  ready,
  problem,
  readyLine,
  onOpenSettings,
}: {
  channel: "sms" | "whatsapp";
  name: string;
  ready: boolean;
  problem: string | null;
  readyLine: string;
  onOpenSettings: () => void;
}) {
  const line = ready ? readyLine : (problem ?? "Not set up yet.");
  return (
    <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <div className="flex items-start gap-3">
        <ChannelIcon channel={channel} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-bold text-[#0A1528]">{name}</p>
            {ready ? <StatusPill tone="success">Ready</StatusPill> : <StatusPill tone="warn">Needs setup</StatusPill>}
          </div>
          <p className="mt-1 truncate text-xs text-[#64748b]" title={line}>
            {line}
          </p>
        </div>
        <Btn variant="link" className="shrink-0" onClick={onOpenSettings}>
          {ready ? "Change" : "Set up"}
        </Btn>
      </div>
    </div>
  );
}

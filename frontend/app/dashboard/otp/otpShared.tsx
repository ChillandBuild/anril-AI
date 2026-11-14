"use client";

import type { OtpHistoryItem, OtpMode, OtpView } from "@/lib/api";
import type { Tone } from "../sms/helpers";
import { Badge, Btn } from "../sms/ui";

/** The backend puts a plain-English message in `detail`, which apiFetch copies to err.message. */
export function otpError(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export const OTP_BASE = "/dashboard/otp";

/** Shared SWR key so the Send, Settings and History tabs see one overview. */
export const OTP_OVERVIEW_KEY = "otp:overview";

export const MODE_OPTIONS: { value: OtpMode; label: string; hint: string }[] = [
  { value: "sms", label: "SMS only", hint: "Sent by SMS from your SMS balance." },
  { value: "whatsapp", label: "WhatsApp only", hint: "Sent as a WhatsApp message with a Copy code button." },
  { value: "both", label: "SMS + WhatsApp", hint: "The same code goes on both at once." },
  { value: "sms_then_whatsapp", label: "SMS, then WhatsApp if it fails", hint: "SMS first. If it fails or isn't delivered in time, the same code goes on WhatsApp." },
];

/** Short names for tables, e.g. the History "How sent" column. */
const MODE_SHORT: Record<OtpMode, string> = {
  sms: "SMS only",
  whatsapp: "WhatsApp only",
  both: "SMS + WhatsApp",
  sms_then_whatsapp: "SMS, then WhatsApp",
};

export function modeShortLabel(mode: OtpMode): string {
  return MODE_SHORT[mode] ?? mode;
}

/** Segmented choice of how to send a code. The chosen option is filled, the others outlined. */
export function ModePicker({
  value,
  onChange,
  disabled,
  showHints,
}: {
  value: OtpMode;
  onChange: (mode: OtpMode) => void;
  disabled?: boolean;
  showHints?: boolean;
}) {
  return (
    <div role="group" aria-label="How to send the code" className="grid gap-2 sm:grid-cols-2">
      {MODE_OPTIONS.map((opt) => {
        const selected = opt.value === value;
        return (
          <Btn
            key={opt.value}
            variant={selected ? "primary" : "outline"}
            aria-pressed={selected}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            className="h-auto min-h-10 w-full flex-col items-start whitespace-normal py-2.5 text-left"
          >
            <span>{opt.label}</span>
            {showHints && (
              <span className={selected ? "text-xs font-normal text-white/85" : "text-xs font-normal text-[#64748b]"}>{opt.hint}</span>
            )}
          </Btn>
        );
      })}
    </div>
  );
}

type ChannelStatus = OtpView["sms"]["status"] | OtpView["whatsapp"]["status"];

/** Badge for one channel's delivery state. */
export function channelBadge(status: ChannelStatus): { label: string; tone: Tone } {
  switch (status) {
    case "sent":
      return { label: "Sent", tone: "info" };
    case "delivered":
      return { label: "Delivered", tone: "success" };
    case "read":
      return { label: "Read", tone: "success" };
    case "failed":
      return { label: "Failed", tone: "danger" };
    default:
      return { label: "Not used", tone: "neutral" };
  }
}

export function ChannelBadge({ status }: { status: ChannelStatus }) {
  const b = channelBadge(status);
  return <Badge tone={b.tone}>{b.label}</Badge>;
}

/** Plain wording for an OTP's overall result. */
export function resultLabel(status: OtpHistoryItem["status"]): { label: string; tone: Tone } {
  switch (status) {
    case "verified":
      return { label: "Verified", tone: "success" };
    case "expired":
      return { label: "Expired", tone: "neutral" };
    case "locked":
      return { label: "Locked (too many tries)", tone: "danger" };
    case "failed":
      return { label: "Not delivered", tone: "danger" };
    case "not_requested":
      return { label: "Customer didn't ask for it", tone: "danger" };
    default:
      return { label: "Waiting", tone: "neutral" };
  }
}

export function ResultBadge({ status }: { status: OtpHistoryItem["status"] }) {
  const r = resultLabel(status);
  return <Badge tone={r.tone}>{r.label}</Badge>;
}

/** True once an OTP has stopped changing, so live polling can stop. */
export function otpIsSettled(v: Pick<OtpView, "status" | "sms" | "whatsapp">): boolean {
  if (v.status !== "pending") return true;
  const smsDone = v.sms.status === "none" || v.sms.status === "delivered" || v.sms.status === "failed";
  const waDone = v.whatsapp.status === "none" || v.whatsapp.status === "delivered" || v.whatsapp.status === "read" || v.whatsapp.status === "failed";
  return smsDone && waDone;
}

export const ORIGIN_LABELS: Record<OtpHistoryItem["origin"], string> = {
  dashboard: "Dashboard",
  api: "API",
  bot: "WhatsApp bot",
  telecaller: "Telecaller login",
};

export function sourceLabel(source: OtpView["source"]): string {
  return source === "anril" ? "Anril" : "Your server";
}

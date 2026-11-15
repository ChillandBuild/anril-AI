"use client";

import type { OtpHistoryItem, OtpMode, OtpView } from "@/lib/api";
import type { Tone } from "../sms/helpers";

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

/** One step in a code's journey, for the Timeline component in otpUi. */
export type OtpStep = { key: string; title: string; time?: string; detail?: string; tone: Tone };

/** What happened to one code, in order. Only the send, verify and not-requested moments have times;
 *  channel steps don't (Anril keeps their status, not when each change happened). */
export function otpTimeline(v: OtpView, formatTime: (iso: string) => string): OtpStep[] {
  const steps: OtpStep[] = [
    { key: "created", title: v.source === "anril" ? "Code made by Anril" : "Code received from your server", time: formatTime(v.created_at), tone: "info" },
  ];
  const sms = v.sms.status;
  if (sms !== "none") {
    const title = sms === "delivered" ? "SMS delivered" : sms === "failed" ? "SMS not delivered" : "SMS sent";
    steps.push({ key: "sms", title, detail: v.sms.error ?? undefined, tone: sms === "delivered" ? "success" : sms === "failed" ? "danger" : "info" });
  }
  const wa = v.whatsapp.status;
  if (wa !== "none") {
    const via = v.whatsapp_backup_sent ? "WhatsApp backup" : "WhatsApp";
    const title = wa === "read" ? `${via} read` : wa === "delivered" ? `${via} delivered` : wa === "failed" ? `${via} not delivered` : `${via} sent`;
    steps.push({ key: "whatsapp", title, detail: v.whatsapp.error ?? undefined, tone: wa === "read" || wa === "delivered" ? "success" : wa === "failed" ? "danger" : "info" });
  }
  if (v.not_requested) {
    steps.push({ key: "not_requested", title: "Customer said they didn't ask for this code", detail: "Anril cancelled the code.", tone: "danger" });
  }
  switch (v.status) {
    case "verified":
      steps.push({ key: "end", title: "Code verified", time: v.verified_at ? formatTime(v.verified_at) : undefined, tone: "success" });
      break;
    case "locked":
      steps.push({ key: "end", title: "Locked after too many wrong tries", tone: "danger" });
      break;
    case "expired":
      steps.push({ key: "end", title: "Expired before it was used", time: v.expires_at ? formatTime(v.expires_at) : undefined, tone: "neutral" });
      break;
    case "failed":
      steps.push({ key: "end", title: "Didn't reach the customer on any channel", tone: "danger" });
      break;
    case "pending":
      if (!otpIsSettled(v)) steps.push({ key: "end", title: "Waiting for a delivery report…", tone: "neutral" });
      break;
  }
  return steps;
}

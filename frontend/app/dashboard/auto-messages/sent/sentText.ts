import type { AutoMessageSentRow } from "@/lib/api";

/** Banner line for the Sent page. */
export function notSentBanner(n: number): string {
  const what = n === 1 ? "1 message didn't" : `${n} messages didn't`;
  return `${what} go out today. Each one shows the reason in plain words and what to do. Nothing is sent twice.`;
}

export const SENT_STATUS: Record<AutoMessageSentRow["status"], { label: string; cls: string }> = {
  delivered: { label: "Delivered", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  read: { label: "Read", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  sent: { label: "Sent", cls: "bg-sky-50 text-sky-700 border-sky-200" },
  not_sent: { label: "Not sent", cls: "bg-amber-50 text-amber-800 border-amber-200" },
  will_retry: { label: "Will retry", cls: "bg-sky-50 text-sky-700 border-sky-200" },
};

export const RANGES: { days: 7 | 30; label: string }[] = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];

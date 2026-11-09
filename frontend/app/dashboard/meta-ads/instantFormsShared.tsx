import { CircleAlert, IndianRupee, Reply, Send, Users, type LucideIcon } from "lucide-react";
import type { InstantFormStats, InstantFormTemplateStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Today or a number of days back, as a local YYYY-MM-DD. */
export function localDate(daysBack = 0): string {
  const date = new Date();
  date.setDate(date.getDate() - daysBack);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function countText(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString("en-IN");
}

export function inrText(value: number | null | undefined): string {
  return value == null
    ? "—"
    : `₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** part / whole as a rounded percentage; "—" when there is nothing to divide by. */
export function percentText(part: number, whole: number): string {
  return whole > 0 ? `${Math.round((part / whole) * 100)}%` : "—";
}

/** "2026-11-09T16:05:00Z" -> "9 Nov, 4:05 pm". */
export function dateTimeText(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });
}

/** "2026-11-09" -> "9 Nov 2026". */
export function dateText(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export const TEMPLATE_STATUS: Record<InstantFormTemplateStatus, { label: string; className: string }> = {
  sent: { label: "Sent", className: "bg-emerald-50 text-emerald-700" },
  failed: { label: "Failed", className: "bg-red-50 text-red-700" },
  no_template: { label: "No template", className: "bg-[#f1f5f9] text-[#475569]" },
  no_phone: { label: "No phone", className: "bg-[#f1f5f9] text-[#475569]" },
  skipped_old: { label: "Older lead", className: "bg-[#f1f5f9] text-[#475569]" },
  pending: { label: "Sending…", className: "bg-blue-50 text-blue-700" },
  sending: { label: "Sending…", className: "bg-blue-50 text-blue-700" },
};

export function TemplateStatusBadge({ status, error }: { status: InstantFormTemplateStatus; error?: string | null }) {
  const look = TEMPLATE_STATUS[status] ?? TEMPLATE_STATUS.pending;
  return (
    <span
      title={status === "failed" && error ? error : undefined}
      className={cn("inline-flex shrink-0 items-center rounded-full px-2 py-0.5 font-label text-[11px] font-bold", look.className)}
    >
      {look.label}
    </span>
  );
}

export function FormStatusBadge({ status }: { status: string | null }) {
  const active = status === "ACTIVE";
  const label = active ? "Active" : status ? status.charAt(0) + status.slice(1).toLowerCase() : "Unknown";
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 font-label text-[11px] font-bold",
        active ? "bg-emerald-50 text-emerald-700" : "bg-[#f1f5f9] text-[#475569]",
      )}
    >
      {label}
    </span>
  );
}

type StatCard = {
  key: string;
  icon: LucideIcon;
  tint: string;
  label: string;
  value: string;
  caption: string;
  stats: { label: string; value: string }[];
  note?: string;
};

/** The four numbers at the top of both screens. Not clickable, unlike the All ads cards. */
export function InstantFormStatCards({
  stats,
  spendAvailable,
  leadsExtra,
}: {
  stats: InstantFormStats | undefined;
  spendAvailable: boolean | undefined;
  /** The third figure under Leads: "Forms" on the overview, "Questions" on one form. */
  leadsExtra: { label: string; value: number | undefined };
}) {
  const leads = stats?.leads ?? 0;
  const sent = stats?.template_sent ?? 0;
  const failed = stats?.template_failed ?? 0;
  const replied = stats?.replied ?? 0;
  const notSent = Math.max(0, leads - sent - failed);

  const cards: StatCard[] = [
    {
      key: "leads",
      icon: Users,
      tint: "bg-primary-50 text-primary-700",
      label: "Leads",
      value: countText(stats?.leads),
      caption: "",
      stats: [
        { label: "From ads", value: countText(stats?.from_ads) },
        { label: "With phone", value: countText(stats?.with_phone) },
        { label: leadsExtra.label, value: countText(leadsExtra.value) },
      ],
    },
    {
      key: "cost",
      icon: IndianRupee,
      tint: "bg-amber-50 text-amber-700",
      label: "Cost per lead",
      value: inrText(stats?.cost_per_lead),
      caption: "per lead",
      stats: [
        { label: "Spend", value: inrText(stats?.spend) },
        { label: "Leads", value: countText(stats?.leads) },
        { label: "Source", value: "Meta" },
      ],
      note: spendAvailable === false ? "Meta didn't return spend" : undefined,
    },
    {
      key: "sent",
      icon: Send,
      tint: "bg-emerald-50 text-emerald-700",
      label: "WhatsApp sent",
      value: countText(stats?.template_sent),
      caption: "sent",
      stats: [
        { label: "Failed", value: countText(stats?.template_failed) },
        { label: "Not sent", value: stats ? countText(notSent) : "—" },
        { label: "Rate", value: stats ? percentText(sent, leads) : "—" },
      ],
    },
    {
      key: "replied",
      icon: Reply,
      tint: "bg-sky-50 text-sky-700",
      label: "Replied",
      value: countText(stats?.replied),
      caption: "replied",
      stats: [
        { label: "Reply rate", value: stats ? percentText(replied, sent) : "—" },
        { label: "Sent", value: countText(stats?.template_sent) },
        { label: "Leads", value: countText(stats?.leads) },
      ],
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => (
        <div
          key={card.key}
          className="flex min-w-0 flex-col gap-3.5 rounded-2xl border border-[#e8edf2] bg-white p-4 shadow-sm sm:p-[18px]"
        >
          <div className="flex items-center gap-2.5">
            <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px]", card.tint)} aria-hidden="true">
              <card.icon size={16} />
            </span>
            <span className="min-w-0 flex-1 truncate font-label text-[13px] font-bold text-[#0A1528]">{card.label}</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-display text-[28px] font-extrabold leading-none tracking-tight text-[#0A1528] tabular-nums">
              {card.value}
            </span>
            {card.caption && <span className="font-label text-xs font-semibold text-[#64748b]">{card.caption}</span>}
          </div>
          <div className="grid grid-cols-3 gap-2 border-t border-dashed border-[#e2e8f0] pt-3">
            {card.stats.map((stat) => (
              <div key={stat.label} className="min-w-0">
                <span className="block truncate font-label text-[10px] font-bold uppercase tracking-wider text-[#64748b]">{stat.label}</span>
                <span className="mt-0.5 block truncate font-label text-[13px] font-bold text-[#0A1528] tabular-nums">{stat.value}</span>
              </div>
            ))}
          </div>
          {card.note && <p className="font-body text-[11px] text-[#94a3b8]">{card.note}</p>}
        </div>
      ))}
    </div>
  );
}

export function StatCardsSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4" aria-hidden="true">
      {Array.from({ length: 4 }, (_, index) => (
        <div key={index} className="flex flex-col gap-3.5 rounded-2xl border border-[#e8edf2] bg-white p-4 shadow-sm sm:p-[18px]">
          <div className="h-8 w-32 animate-pulse rounded-lg bg-stone-200/70" />
          <div className="h-7 w-24 animate-pulse rounded bg-stone-200/70" />
          <div className="h-4 w-full animate-pulse rounded bg-stone-200/70" />
        </div>
      ))}
    </div>
  );
}

export function errorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "Something went wrong. Try again in a moment.";
}

/** A centred card for a load that failed, with a Retry button. */
export function LoadErrorCard({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry: () => unknown;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-[#e2e8f0] bg-white px-4 py-14 text-center shadow-sm">
      <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-red-50">
        <CircleAlert size={24} className="text-red-400" />
      </div>
      <h3 className="mb-1 text-base font-bold text-[#1e293b]">{title}</h3>
      <p className="mb-4 max-w-md text-sm leading-relaxed text-[#94a3b8]">{message}</p>
      <button
        type="button"
        onClick={() => onRetry()}
        className="flex h-9 items-center justify-center rounded-xl border border-[#e2e8f0] bg-white px-4 font-label text-xs font-bold text-[#0A1528] shadow-sm transition-colors hover:border-primary-200 hover:text-primary-700"
      >
        Retry
      </button>
    </div>
  );
}

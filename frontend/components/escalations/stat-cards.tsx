"use client";
import { cn } from "@/lib/utils";
import { KpiCard } from "@/components/kpi-card";

export type StatTone = "neutral" | "positive" | "warning" | "critical";

const TONE: Record<StatTone, { value: string; edge: string }> = {
  neutral: { value: "text-gray-900", edge: "bg-slate-400" },
  positive: { value: "text-emerald-600", edge: "bg-emerald-500" },
  warning: { value: "text-amber-600", edge: "bg-amber-400" },
  critical: { value: "text-rose-600", edge: "bg-rose-500" },
};

export type StatItem = {
  label: string;
  value: string;
  tone?: StatTone;
  /** The line under the figure — what the number is made of, not a restatement. */
  detail?: string;
};

/**
 * A figure is a count or a duration ("13", "7h 5m", "<1m", "—"). Everything
 * else is prose — a person's name, a trigger label.
 */
function isFigure(value: string): boolean {
  return /^[<>~]?\d/.test(value) || value === "—";
}

/** Header KPI cards. Sized to be read at a glance without costing the table its fold */
export function StatCards({ items }: { items: StatItem[] }) {
  return (
    <div className="min-w-0 flex-1 max-md:basis-full">
      {/* Phones: one compact line of figures, so the list starts on the first screen. */}
      <div className="flex gap-2 overflow-x-auto [scrollbar-width:none] md:hidden [&::-webkit-scrollbar]:hidden">
        {items.map((item) => (
          <div key={item.label} className="flex shrink-0 items-baseline gap-1.5 rounded-xl border border-border bg-white px-3 py-1.5">
            <span className={cn("max-w-[9rem] truncate font-display text-base font-bold leading-none tabular-nums", TONE[item.tone ?? "neutral"].value)}>{item.value}</span>
            <span className="whitespace-nowrap text-xs text-ink-muted">{item.label}</span>
          </div>
        ))}
      </div>
    <div className="hidden flex-wrap gap-2.5 md:flex">
      {items.map((item) => {
        const tone = TONE[item.tone ?? "neutral"];
        const figure = isFigure(item.value);
        return (
          <KpiCard
            key={item.label}
            stacked
            label={item.label}
            value={item.value}
            hint={item.detail}
            edge={tone.edge}
            title={figure ? undefined : item.value}
            valueClassName={cn(
              "tracking-tight",
              figure ? "text-[22px] leading-none" : "min-w-0 shrink truncate text-sm leading-tight",
              tone.value
            )}
            className="min-w-[145px] flex-1"
          />
        );
      })}
    </div>
    </div>
  );
}

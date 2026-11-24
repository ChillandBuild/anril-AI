"use client";
import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: number | string;
  sub?: string;
  accent?: boolean;
  tone?: string;
}

export function StatCard({ label, value, sub, accent, tone }: StatCardProps) {
  return (
    <div
      className={cn(
        "rounded-card border border-border border-t-4 p-6 shadow-card transition-all hover:shadow-md",
        accent
          ? "border-transparent text-white"
          : cn("bg-surface", tone ?? "border-t-primary-500")
      )}
      style={accent ? { background: "var(--primary)" } : {}}
    >
      <p className={cn(
        "stat-label mb-2",
        accent ? "text-primary-200/60" : ""
      )}>
        {label}
      </p>
      <p className={cn(
        "stat-num",
        accent ? "text-white" : "text-ink"
      )}>
        {value}
      </p>
      {sub && (
        <p className={cn(
          "mt-1 text-xs",
          accent ? "text-primary-200/60" : "text-ink-muted"
        )}>
          {sub}
        </p>
      )}
    </div>
  );
}

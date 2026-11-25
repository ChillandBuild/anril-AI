"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { AiraLoader } from "@/components/AiraLoader";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";

/** The page frame every Call IQ report screen shares: title, one plain line, then the content. */
export function CallIqPage({ intro, children }: { title: string; intro: string; children: ReactNode }) {
  return (
    <div className="w-full min-w-0 max-w-[1400px] space-y-5 overflow-x-hidden px-0 py-0 pb-4 md:p-7">
      <header>
        <p className="font-label text-sm text-ink-secondary">{intro}</p>
      </header>
      {children}
    </div>
  );
}

/** Shows the page only to people who may open it; waits for the role to load first. */
export function CallIqGate({ allow, children }: { allow: (role: string | null, permissions: string[]) => boolean; children: ReactNode }) {
  const { role, permissions, loading } = useAuthRole();
  if (loading) return <AiraLoader inline className="min-h-40" />;
  if (!allow(role, permissions)) {
    return (
      <div className="px-4 py-10 md:p-7">
        <p className="rounded-xl bg-surface p-5 font-label text-sm text-ink-secondary ring-1 ring-[#c4c7c7]/30">
          You do not have access to this page. Ask the owner to give you access.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-xl bg-red-50 p-4 font-label text-sm text-red-800 ring-1 ring-red-200">
      <span>{message}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="shrink-0 rounded-lg bg-red-100 px-3 py-2 font-label text-xs font-bold text-red-800 hover:bg-red-200">
          Try again
        </button>
      )}
    </div>
  );
}

export function PeriodPicker<T extends string>({
  options, value, onChange, label,
}: { options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="inline-flex max-w-full flex-wrap gap-1 rounded-xl bg-surface p-1 ring-1 ring-[#c4c7c7]/30">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "min-h-10 rounded-lg px-3 font-label text-sm font-bold",
            o.value === value ? "bg-primary text-white" : "text-ink-secondary hover:bg-black/5",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cn("min-w-0 rounded-card bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15", className)}>{children}</section>;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0">
      <p className="font-label text-xs font-bold uppercase tracking-wide text-ink-secondary">{label}</p>
      <p className="mt-0.5 font-display text-lg font-bold text-primary">{value}</p>
      {hint ? <p className="font-label text-xs text-ink-secondary">{hint}</p> : null}
    </div>
  );
}

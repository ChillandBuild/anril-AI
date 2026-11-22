"use client";
// Small pieces shared by the two "My business" pages (Payments & advance, Target & profit).
// Looks like the other settings pages: white rounded cards, nothing under 12px.
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export const CARD = "rounded-2xl border border-border/70 bg-white p-4 shadow-[0_1px_2px_rgba(28,25,23,0.03)] sm:p-5";

export function PageHeader({ icon: Icon, title, subtitle }: { icon: LucideIcon; title: string; subtitle: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary">
        <Icon size={18} strokeWidth={1.6} aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <h1 className="font-display text-xl font-bold text-ink">{title}</h1>
        <p className="mt-0.5 text-sm text-ink-muted">{subtitle}</p>
      </div>
    </div>
  );
}

export function Card({ id, title, hint, children }: { id: string; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className={CARD} aria-labelledby={id}>
      <h2 id={id} className="text-sm font-semibold text-ink">{title}</h2>
      {hint ? <p className="mt-0.5 text-sm text-ink-muted">{hint}</p> : null}
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** One plain sentence under the title, like "In short" on the other pages. */
export function InShort({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-xl bg-primary-50 px-4 py-3 text-sm font-semibold text-ink">
      <span className="text-primary-800">In short: </span>
      {children}
    </p>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-2xl border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger" role="alert">
      {message}{" "}
      <button type="button" onClick={onRetry} className="min-h-11 font-semibold underline">
        Try again
      </button>
    </div>
  );
}

/** Green / amber / grey dot with its words, so colour is never the only signal. */
export function StatusDot({ ok, okLabel, badLabel, unknownLabel }: { ok: boolean | null; okLabel: string; badLabel: string; unknownLabel: string }) {
  const label = ok === true ? okLabel : ok === false ? badLabel : unknownLabel;
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 text-sm font-semibold text-ink">
      <span aria-hidden className={cn("h-2.5 w-2.5 rounded-full", ok === true ? "bg-emerald-500" : ok === false ? "bg-amber-500" : "bg-slate-400")} />
      {label}
    </span>
  );
}

/** The greyed "Coming later" list: planned, not working yet. */
export function ComingLater({ items }: { items: string[] }) {
  return (
    <section className={cn(CARD, "bg-surface-subtle/60")} aria-labelledby="coming-later">
      <h2 id="coming-later" className="text-sm font-semibold text-ink-muted">Coming later</h2>
      <ul className="mt-2 space-y-1.5">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-2 text-sm text-ink-muted">
            <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-300" />
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}

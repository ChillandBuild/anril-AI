"use client";

import { Check } from "lucide-react";

/** One numbered section of a template builder (Create Template, Carousel): its number,
 * or a green tick once nothing in it needs fixing. */
export default function Section({
  n, title, hint, done, active = false, children, className = "", right,
}: {
  n: number; title: string; hint?: string; done: boolean; active?: boolean; children: React.ReactNode; className?: string;
  /** Something on the right of the title row, e.g. "4 of 10". */
  right?: React.ReactNode;
}) {
  return (
    <section
      className={`rounded-2xl border bg-white p-3 shadow-sm md:p-6 ${
        active ? "border-primary-300 ring-4 ring-primary-50" : "border-[#e7e2da]"
      } ${className}`}
    >
      <div className="mb-4 flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[13px] font-bold ${
            done ? "bg-emerald-50 text-emerald-600" : "bg-primary text-white"
          }`}
          aria-hidden="true"
        >
          {done ? <Check size={15} strokeWidth={3} /> : n}
        </span>
        <h2 className="font-display text-base font-bold text-ink">{title}</h2>
        {hint && <span className="text-[12.5px] text-ink-muted">{hint}</span>}
        {right && <span className="ml-auto text-[12.5px] text-ink-muted">{right}</span>}
      </div>
      {children}
    </section>
  );
}

/** "Check before sending to Meta": the rules that block Submit, in plain words. */
export function ChecklistCard({ checks, title = "Check before sending to Meta" }: { checks: { ok: boolean; text: string }[]; title?: string }) {
  return (
    <section className="rounded-2xl border border-[#e7e2da] bg-white p-4">
      <h3 className="mb-2.5 text-sm font-bold text-ink">{title}</h3>
      <ul className="grid gap-1.5 text-[12.5px] font-medium sm:grid-cols-2 xl:grid-cols-1">
        {checks.map((c) => (
          <li key={c.text} className={`flex items-center gap-1.5 ${c.ok ? "text-emerald-700" : "text-ink-muted"}`}>
            {c.ok ? <Check size={13} strokeWidth={3} aria-hidden="true" /> : <span className="h-3 w-3 shrink-0 rounded-full border-[1.5px] border-current" aria-hidden="true" />}
            {c.text}
          </li>
        ))}
      </ul>
    </section>
  );
}

"use client";

import { forwardRef } from "react";
import { Loader2 } from "lucide-react";

// Shared look for the public booking pages: a narrow phone-first column on a light background,
// like the bill page.

export function BookShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-slate-50 px-4 py-6 sm:py-10">
      <div className="mx-auto w-full max-w-md">{children}</div>
    </main>
  );
}

export function BookLoading() {
  return (
    <div role="status" aria-label="Loading" className="flex justify-center py-24">
      <Loader2 className="animate-spin text-slate-400" />
    </div>
  );
}

export function BookMessage({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-5 py-10 text-center shadow-sm">
      <p className="text-sm leading-6 text-slate-600">{children}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm text-rose-800">
      {children}
    </p>
  );
}

/** A step heading that can take focus when the step opens (keyboard and screen-reader users land on it). */
export const StepHeading = forwardRef<HTMLHeadingElement, { children: React.ReactNode }>(function StepHeading(
  { children },
  ref,
) {
  return (
    <h2 ref={ref} tabIndex={-1} className="text-base font-bold text-slate-900 outline-none focus-visible:ring-2 focus-visible:ring-emerald-500">
      {children}
    </h2>
  );
});

export const primaryBtn =
  "inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-3 text-base font-bold text-white shadow-sm hover:bg-emerald-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 disabled:opacity-60";
export const secondaryBtn =
  "inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-bold text-slate-700 shadow-sm hover:border-slate-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 disabled:opacity-60";
export const choiceBtn =
  "flex min-h-[52px] w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-left hover:border-emerald-400 hover:bg-emerald-50/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700";

import type { ReactNode } from "react";

interface WaitingRowProps {
  title: string;
  meta?: string;
  children: ReactNode;
}

export function WaitingRow({ title, meta, children }: WaitingRowProps) {
  return (
    <li className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-xl border border-border-subtle bg-surface-low px-3 py-2.5">
      <div className="min-w-0 flex-1 basis-40">
        <p className="break-words font-body text-sm font-semibold text-ink">{title}</p>
        {meta && <p className="font-body text-xs text-ink-secondary">{meta}</p>}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">{children}</div>
    </li>
  );
}

export const ROW_BUTTON_CLASS =
  "inline-flex min-h-9 items-center justify-center rounded-lg border border-primary-200 bg-primary-50 px-3 font-label text-xs font-bold text-primary transition hover:bg-primary-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-50";

export const ROW_LINK_CLASS =
  "inline-flex min-h-8 items-center px-2 font-label text-xs font-bold text-primary hover:text-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";

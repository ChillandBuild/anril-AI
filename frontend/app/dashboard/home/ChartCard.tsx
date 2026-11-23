import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** The shell every "More details" chart sits in: a title on the left, a small grey note on the right. */
export function ChartCard({
  title,
  note,
  className,
  children,
}: {
  title: string;
  note?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={cn("min-w-0 rounded-2xl border border-border bg-white px-5 py-4 shadow-sm", className)} aria-label={title}>
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h3 className="font-display text-[15px] font-extrabold text-ink">{title}</h3>
        {note ? <span className="text-right font-label text-xs text-ink-muted">{note}</span> : null}
      </div>
      {children}
    </section>
  );
}

/** Width classes for the cards: the line chart is twice as wide, the others share what is left. */
export const WIDE_CARD = "flex-[2_1_660px]";
export const CARD = "flex-[1_1_320px]";

/** A same-size grey block held in a chart's place while its data is on the way, so nothing below jumps. */
export function ChartCardSkeleton() {
  return <div className={cn(CARD, "h-[190px] animate-pulse rounded-2xl border border-border bg-white")} aria-hidden />;
}

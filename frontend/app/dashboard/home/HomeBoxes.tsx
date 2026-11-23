"use client";
import Link from "next/link";
import { cn } from "@/lib/utils";
import type { HomeBox } from "@/lib/api";
import { BOX_META, boxSub, formatBoxValue, isLoss, type BoxKey } from "./todayLayout";

/** The number boxes: 6 per row on a laptop, 3 on a tablet, 2 on a phone. Each one is a link. */
export function HomeBoxes({ keys, boxes }: { keys: BoxKey[]; boxes: Partial<Record<BoxKey, HomeBox>> }) {
  const shown = keys.filter((k) => boxes[k]);
  if (shown.length === 0) return null;
  return (
    <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" aria-label="Today in numbers">
      {shown.map((key) => (
        <li key={key} className="min-w-0">
          <HomeBoxCard boxKey={key} box={boxes[key] as HomeBox} />
        </li>
      ))}
    </ul>
  );
}

function HomeBoxCard({ boxKey, box }: { boxKey: BoxKey; box: HomeBox }) {
  const meta = BOX_META[boxKey];
  const Icon = meta.icon;
  const sub = boxSub(boxKey, box);
  return (
    <Link
      href={box.href}
      className={cn(
        "flex h-full min-w-0 flex-col gap-1 rounded-2xl border border-[#e8edf2] bg-white px-4 py-3.5 shadow-sm transition-colors",
        "hover:border-slate-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
      )}
    >
      <span className="flex items-start gap-2">
        <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-[9px]", meta.tint)} aria-hidden>
          <Icon size={15} />
        </span>
        <span className="min-w-0 font-label text-[13px] font-bold leading-tight text-ink">{meta.label}</span>
      </span>
      <span
        className={cn(
          "mt-1 truncate font-display text-2xl font-extrabold leading-none tracking-tight tabular-nums",
          isLoss(boxKey, box) ? "text-rose-700" : "text-ink",
        )}
      >
        {formatBoxValue(box)}
      </span>
      {sub ? <span className="font-label text-xs font-semibold leading-snug text-ink-muted">{sub}</span> : null}
    </Link>
  );
}

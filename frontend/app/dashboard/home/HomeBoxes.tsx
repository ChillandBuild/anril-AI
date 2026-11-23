"use client";
import Link from "next/link";
import { cn } from "@/lib/utils";
import type { HomeBox } from "@/lib/api";
import { todayIst } from "../bookings/bookingsTime";
import { BOX_META, boxSub, formatBoxValue, formatRupees, isLoss, type BoxKey } from "./todayLayout";
import { boxSeries, ringDash, seriesCaption, targetPct, weekdayLabels } from "./homeCharts";
import { Sparkline } from "./Sparkline";

const ROW =
  "flex items-center gap-3 py-3 text-ink hover:bg-surface-mid/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary";

/**
 * The Today boxes as rows: label and small line under it on the left, a 7-day line (when the server sent
 * one) and the big number on the right. The target box is a ring. Any number of boxes, one under the other.
 */
export function HomeBoxes({ keys, boxes }: { keys: BoxKey[]; boxes: Partial<Record<BoxKey, HomeBox>> }) {
  const shown = keys.filter((k) => boxes[k]);
  if (shown.length === 0) return null;
  const labels = weekdayLabels(todayIst(), 7);
  return (
    <ul className="divide-y divide-border-subtle border-t border-border-subtle" aria-label="Today in numbers">
      {shown.map((key) => {
        const box = boxes[key] as HomeBox;
        return (
          <li key={key} className="min-w-0">
            {key === "target_month" ? <TargetRow box={box} /> : <NumberRow boxKey={key} box={box} labels={labels} />}
          </li>
        );
      })}
    </ul>
  );
}

function NumberRow({ boxKey, box, labels }: { boxKey: BoxKey; box: HomeBox; labels: string[] }) {
  const meta = BOX_META[boxKey];
  const sub = boxSub(boxKey, box);
  const series = boxSeries(box);
  const caption = seriesCaption(boxKey, meta.label);
  const format = box.unit === "paise" ? (v: number) => formatRupees(v) : undefined;
  return (
    <Link href={box.href} className={ROW}>
      <span className="min-w-0 flex-1">
        <span className="block font-label text-sm font-semibold leading-tight">{meta.label}</span>
        {sub ? <span className="mt-0.5 block font-label text-xs font-medium leading-snug text-ink-muted">{sub}</span> : null}
      </span>
      {series && (
        <span className="flex shrink-0 flex-col items-end gap-0.5">
          <Sparkline values={series} labels={labels} label={caption} format={format} />
          <span className="font-label text-[10px] font-medium leading-none text-ink-muted">{caption}</span>
        </span>
      )}
      <span
        className={cn(
          "max-w-[9rem] shrink-0 truncate text-right font-display text-2xl font-extrabold leading-none tracking-tight tabular-nums",
          isLoss(boxKey, box) ? "text-rose-700" : "text-ink",
        )}
      >
        {formatBoxValue(box)}
      </span>
    </Link>
  );
}

const RING_R = 26;

/** The target box: a ring that fills as money comes in. No target set yet: a dashed empty ring and "Set a target". */
function TargetRow({ box }: { box: HomeBox }) {
  const meta = BOX_META.target_month;
  const pct = targetPct(box);
  const unset = box.unit === "set_target";
  return (
    <Link href={box.href} className={cn(ROW, "gap-4")}>
      <svg width={64} height={64} viewBox="0 0 64 64" role="img" aria-label={pct != null ? `${pct} percent of the target` : "No target set"} className="shrink-0">
        {pct != null && <title>{`${pct}% of the target`}</title>}
        <circle cx={32} cy={32} r={RING_R} fill="none" className="stroke-surface-mid" strokeWidth={8} />
        {pct != null && pct > 0 && (
          <circle
            cx={32}
            cy={32}
            r={RING_R}
            fill="none"
            className="stroke-primary-800"
            strokeWidth={8}
            strokeLinecap="round"
            strokeDasharray={ringDash(pct, RING_R)}
            transform="rotate(-90 32 32)"
          />
        )}
        {unset && (
          <circle cx={32} cy={32} r={RING_R} fill="none" className="stroke-primary-800" strokeWidth={8} strokeDasharray="4 6" opacity={0.5} />
        )}
        <text x={32} y={37} textAnchor="middle" fontSize={13} fontWeight={800} className="fill-ink">
          {pct != null ? `${pct}%` : "—"}
        </text>
      </svg>
      <span className="min-w-0 flex-1">
        <span className="block font-label text-sm font-semibold leading-tight">{meta.label}</span>
        {unset ? (
          <>
            <span className="mt-0.5 block font-label text-[13px] font-bold text-primary-700">Set a target ›</span>
            <span className="block font-label text-xs text-ink-muted">The ring fills as money comes in</span>
          </>
        ) : (
          <>
            <span className="mt-0.5 block truncate font-display text-lg font-extrabold leading-tight tabular-nums">{formatBoxValue(box)}</span>
            {box.sub ? <span className="block font-label text-xs font-medium text-ink-muted">{box.sub}</span> : null}
          </>
        )}
      </span>
    </Link>
  );
}

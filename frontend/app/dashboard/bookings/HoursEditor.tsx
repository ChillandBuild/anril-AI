"use client";
import { cn } from "@/lib/utils";
import type { HoursBlock, WeekHours } from "@/lib/bookingsApi";
import { MAX_BLOCKS_PER_DAY, addBlock, copyDayToAll, hoursSummary, normaliseHours, validateDay } from "./bookingsLogic";
import { DAY_NAMES } from "./bookingsTime";

/** Mon-Sun hours: up to 2 blocks a day, and "Copy to all days". Read-only shows a summary. */
export function HoursEditor({ value, onChange, readOnly, idPrefix }: { value: WeekHours; onChange: (next: WeekHours) => void; readOnly?: boolean; idPrefix: string }) {
  const hours = normaliseHours(value);
  const setDay = (d: number, blocks: HoursBlock[]) => onChange({ ...hours, [String(d)]: blocks });

  return (
    <ul className="space-y-2">
      {DAY_NAMES.map((name, d) => {
        const blocks = hours[String(d)];
        const error = validateDay(blocks);
        return (
          <li key={name} className="rounded-xl border border-[#eef2f6] bg-white px-3 py-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="w-24 shrink-0 text-sm font-semibold text-ink">{name}</span>
              {readOnly ? (
                <span className="text-sm text-ink-secondary">{hoursSummary(blocks)}</span>
              ) : (
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                  {blocks.length === 0 && <span className="text-sm text-ink-muted">Day off</span>}
                  {blocks.map((b, i) => (
                    <span key={i} className="inline-flex items-center gap-1">
                      <input
                        type="time"
                        step={900}
                        aria-label={`${name} block ${i + 1} starts`}
                        id={`${idPrefix}-${d}-${i}-s`}
                        value={b[0]}
                        onChange={(e) => setDay(d, blocks.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))}
                        className="h-9 rounded-lg border border-[#e2e8f0] px-2 text-sm"
                      />
                      <span aria-hidden>–</span>
                      <input
                        type="time"
                        step={900}
                        aria-label={`${name} block ${i + 1} ends`}
                        value={b[1]}
                        onChange={(e) => setDay(d, blocks.map((x, j) => (j === i ? [x[0], e.target.value] : x)))}
                        className="h-9 rounded-lg border border-[#e2e8f0] px-2 text-sm"
                      />
                      <button type="button" aria-label={`Remove ${name} block ${i + 1}`} onClick={() => setDay(d, blocks.filter((_, j) => j !== i))} className="h-9 rounded-lg px-2 text-sm text-ink-muted hover:bg-slate-100">
                        ✕
                      </button>
                    </span>
                  ))}
                  <div className="ml-auto flex gap-1">
                    {blocks.length < MAX_BLOCKS_PER_DAY && (
                      <button type="button" onClick={() => setDay(d, addBlock(blocks))} className="rounded-lg px-2 py-1.5 text-xs font-bold text-primary-700 hover:bg-primary/10">
                        ＋ Add time
                      </button>
                    )}
                    <button type="button" onClick={() => onChange(copyDayToAll(hours, d))} className="rounded-lg px-2 py-1.5 text-xs font-bold text-primary-700 hover:bg-primary/10">
                      Copy to all days
                    </button>
                  </div>
                </div>
              )}
            </div>
            {error && !readOnly && (
              <p role="alert" className={cn("mt-1 text-xs font-semibold text-rose-700")}>
                {error}
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

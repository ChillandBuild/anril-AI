"use client";
import { useState } from "react";
import { CalendarClock, ChevronDown, X } from "lucide-react";
import { formatIstWhen, fromIstInputs, quickTimes, toIstInputs } from "@/lib/call-wrapup";
import { TOMORROW_HOURS, tomorrowAt } from "./quickTimes";

interface QuickTimePickerProps {
  value: string | null;
  onChange: (iso: string | null) => void;
  now: Date;
  optional?: boolean;
  suggested?: string | null;
}

const CHIP = "px-3 py-1.5 rounded-full border font-label text-[11px] font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed";
const ON = "bg-primary border-primary text-white shadow-sm";
const OFF = "bg-white border-[#e2e8f0] text-[#334155] hover:border-primary-muted hover:text-primary";
const HOUR_CHIP = "h-8 shrink-0 whitespace-nowrap px-3 rounded-full border font-label text-xs font-bold transition-all";
const INPUT = "flex-1 min-w-0 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-body text-xs focus:outline-none focus:ring-2 focus:ring-primary";

/** In 1 hour · This evening 6 PM · Tomorrow 10 AM · Pick a date & time — all in IST. */
export default function QuickTimePicker({ value, onChange, now, optional = false, suggested = null }: QuickTimePickerProps) {
  const [custom, setCustom] = useState(false);
  const [tomorrowOpen, setTomorrowOpen] = useState(false);
  const quick = quickTimes(now);
  const picked = value ? new Date(value) : null;
  const matched = picked ? quick.find((q) => Math.abs(q.at.getTime() - picked.getTime()) < 60_000)?.key ?? null : null;
  const showCustom = custom || (picked !== null && matched === null && value !== suggested);
  const inputs = toIstInputs(picked ?? quick[0].at);

  function setPart(part: "date" | "time", next: string) {
    const merged = { ...inputs, [part]: next };
    const at = fromIstInputs(merged.date, merged.time);
    if (at) onChange(at.toISOString());
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {quick.map((q) => (
          <button
            key={q.key}
            type="button"
            disabled={q.disabled}
            onClick={() => {
              setCustom(false);
              onChange(q.at.toISOString());
            }}
            className={`${CHIP} ${matched === q.key && !custom ? ON : OFF}`}
          >
            {q.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setTomorrowOpen((o) => !o)}
          aria-expanded={tomorrowOpen}
          className={`${CHIP} inline-flex items-center gap-1 ${tomorrowOpen ? ON : OFF}`}
        >
          Tomorrow at <ChevronDown size={11} className={tomorrowOpen ? "rotate-180" : ""} />
        </button>
        <button
          type="button"
          onClick={() => {
            setCustom(true);
            if (!picked) onChange(quick[0].at.toISOString());
          }}
          className={`${CHIP} inline-flex items-center gap-1 ${showCustom ? ON : OFF}`}
        >
          <CalendarClock size={11} /> Pick a date &amp; time
        </button>
        {optional && value && (
          <button
            type="button"
            onClick={() => {
              setCustom(false);
              onChange(null);
            }}
            className={`${CHIP} inline-flex items-center gap-1 bg-white border-[#e2e8f0] text-[#94a3b8] hover:text-rose-600`}
          >
            <X size={11} /> No follow-up
          </button>
        )}
      </div>
      {tomorrowOpen && (
        <div className="flex gap-1.5 overflow-x-auto pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {TOMORROW_HOURS.map((h) => {
            const at = tomorrowAt(h.hour, now);
            const on = picked !== null && Math.abs(at.getTime() - picked.getTime()) < 60_000 && !custom;
            return (
              <button
                key={h.hour}
                type="button"
                onClick={() => {
                  setCustom(false);
                  onChange(at.toISOString());
                }}
                className={`${HOUR_CHIP} ${on ? ON : OFF}`}
              >
                {h.label}
              </button>
            );
          })}
        </div>
      )}
      {showCustom && (
        <div className="flex items-center gap-2">
          <input type="date" aria-label="Date" value={inputs.date} min={toIstInputs(now).date} onChange={(e) => setPart("date", e.target.value)} className={INPUT} />
          <input type="time" aria-label="Time" value={inputs.time} onChange={(e) => setPart("time", e.target.value)} className={INPUT} />
          <span className="font-label text-[10px] font-bold text-[#94a3b8]">IST</span>
        </div>
      )}
      {picked && (
        <p className="font-label text-[11px] text-[#334155]">
          <span className="font-bold text-[#13284A]">{formatIstWhen(picked, now)}</span>
          {value === suggested && (
            <span className="ml-1.5 rounded-full bg-primary-light px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider text-primary">
              Suggested
            </span>
          )}
        </p>
      )}
    </div>
  );
}

"use client";
import { useMemo } from "react";
import { AlertTriangle, CalendarClock, Clock, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type WhenValue,
  clockOf,
  dateBounds,
  formatSendTime,
  quickSlots,
  resolveWhen,
  toIstInputs,
  untilSend,
} from "@/lib/schedule-time";

interface WhenToSendProps {
  /** Unique on the page: ties the labels to the date and time fields. */
  idPrefix: string;
  value: WhenValue;
  onChange: (next: WhenValue) => void;
  /** "card" is the compact look inside the Send details card; "form" matches the dialogs' form fields. */
  variant?: "card" | "form";
  disabled?: boolean;
}

/** Send now, or pick a time. The same control wherever a template can be sent. */
export function WhenToSend({ idPrefix, value, onChange, variant = "card", disabled = false }: WhenToSendProps) {
  const compact = variant === "card";
  // Fixed when the control opens, so the quick times don't shift while someone is choosing.
  const slots = useMemo(() => quickSlots(new Date()), []);
  const now = new Date();
  const bounds = dateBounds(now);
  const resolved = resolveWhen(value, now);

  const labelClass = compact
    ? "sr-only"
    : "font-label text-xs font-semibold uppercase tracking-wider text-on-surface-muted";
  const fieldClass = cn(
    "w-full min-w-0 border border-[#e2e8f0] bg-white font-body text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-60",
    compact ? "rounded-[10px] px-2.5 py-1.5 text-xs" : "rounded-xl px-4 py-2.5 text-sm",
  );

  return (
    <div className="flex flex-col gap-2">
      <span id={`${idPrefix}-when-label`} className={labelClass}>
        When to send
      </span>
      <div
        role="tablist"
        aria-labelledby={`${idPrefix}-when-label`}
        className={cn("grid grid-cols-2 gap-1 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] p-1", !compact && "mt-0")}
      >
        {([
          ["now", "Send now", Send],
          ["later", "Schedule", CalendarClock],
        ] as const).map(([mode, label, Icon]) => (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={value.mode === mode}
            disabled={disabled}
            onClick={() => onChange({ ...value, mode })}
            className={cn(
              "flex items-center justify-center gap-1.5 rounded-lg py-2 font-label text-xs font-bold transition-all disabled:opacity-60",
              value.mode === mode ? "bg-white text-primary shadow-sm" : "text-[#64748b] hover:text-[#0A1528]",
            )}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>

      {value.mode === "later" && (
        <div className="flex flex-col gap-2 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2.5">
          <div role="group" aria-label="Quick times" className="flex flex-wrap gap-1.5">
            {slots.map((slot) => {
              const inputs = toIstInputs(slot.at);
              const pressed = inputs.date === value.date && inputs.time === value.time;
              return (
                <button
                  key={slot.key}
                  type="button"
                  aria-pressed={pressed}
                  disabled={disabled}
                  onClick={() => onChange({ mode: "later", ...inputs })}
                  className={cn(
                    "inline-flex items-baseline gap-1.5 rounded-full border px-3 py-1 font-label text-[11px] font-bold transition-colors disabled:opacity-60",
                    pressed
                      ? "border-primary bg-primary-light text-primary"
                      : "border-[#e2e8f0] bg-white text-[#13284A] hover:border-primary",
                  )}
                >
                  {slot.label}
                  <span className="font-semibold text-[#64748b]">{clockOf(slot.at)}</span>
                </button>
              );
            })}
          </div>

          <div className="grid grid-cols-1 gap-2 min-[480px]:grid-cols-[1.25fr_1fr]">
            <div className="flex min-w-0 flex-col gap-1">
              <label htmlFor={`${idPrefix}-date`} className={labelClass}>
                Date
              </label>
              <input
                id={`${idPrefix}-date`}
                type="date"
                value={value.date}
                min={bounds.min}
                max={bounds.max}
                disabled={disabled}
                onChange={(e) => onChange({ ...value, date: e.target.value })}
                className={fieldClass}
              />
            </div>
            <div className="flex min-w-0 flex-col gap-1">
              <label htmlFor={`${idPrefix}-time`} className={labelClass}>
                Time (IST)
              </label>
              <input
                id={`${idPrefix}-time`}
                type="time"
                step={300}
                value={value.time}
                disabled={disabled}
                onChange={(e) => onChange({ ...value, time: e.target.value })}
                className={fieldClass}
              />
            </div>
          </div>

          <p
            aria-live="polite"
            className={cn("flex items-start gap-1.5 font-label text-xs", resolved.error ? "text-red-700" : "text-[#13284A]")}
          >
            {resolved.error ? (
              <AlertTriangle size={13} className="mt-0.5 shrink-0 text-red-600" />
            ) : (
              <Clock size={13} className="mt-0.5 shrink-0 text-primary" />
            )}
            {resolved.error ? (
              <span>{resolved.error}</span>
            ) : (
              resolved.at && (
                <span>
                  Sends <strong className="font-bold">{formatSendTime(resolved.at)}</strong> IST · {untilSend(resolved.at, now)}
                </span>
              )
            )}
          </p>
        </div>
      )}
    </div>
  );
}

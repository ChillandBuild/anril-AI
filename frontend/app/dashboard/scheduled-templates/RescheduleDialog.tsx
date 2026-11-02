"use client";

import { useEffect, useState } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  clockOf,
  dateBounds,
  defaultWhen,
  formatSendTime,
  quickSlots,
  resolveWhen,
  toIstInputs,
  untilSend,
  type WhenValue,
} from "@/lib/schedule-time";

interface RescheduleDialogProps {
  title: string;
  /** One line under the title: what is moving and when it goes out now. */
  subject: string;
  count: number;
  /** Pre-fills the date and time when the send is still ahead. */
  currentAt: Date | null;
  onClose: () => void;
  /** Resolves with the server's plain-words reason when the move was refused, or null once it went through. */
  onSubmit: (at: Date) => Promise<string | null>;
}

function initialWhen(currentAt: Date | null, now: Date): WhenValue {
  if (currentAt && currentAt.getTime() > now.getTime()) return { mode: "later", ...toIstInputs(currentAt) };
  return defaultWhen(now);
}

export function RescheduleDialog({ title, subject, count, currentAt, onClose, onSubmit }: RescheduleDialogProps) {
  const [now] = useState(() => new Date());
  const [value, setValue] = useState<WhenValue>(() => initialWhen(currentAt, now));
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState("");

  const resolved = resolveWhen(value, now);
  const at = resolved.at;
  const bounds = dateBounds(now);
  const slots = quickSlots(now);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit() {
    if (!at || resolved.error || busy) return;
    setBusy(true);
    setServerError("");
    const reason = await onSubmit(at);
    setBusy(false);
    if (reason) setServerError(reason);
  }

  const preview = resolved.error || (at ? `Sends ${formatSendTime(at)} IST · ${untilSend(at, now)}` : "Pick a date and time.");
  const invalid = !at || !!resolved.error;

  return (
    <div
      className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="reschedule-title"
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="reschedule-title" className="font-display text-lg font-bold text-[#0A1528]">
          {title}
        </h2>
        <p className="mt-1 text-sm text-[#64748b]">{subject}</p>

        <div className="mt-5 flex flex-wrap gap-2">
          {slots.map((slot) => {
            const active = !!at && slot.at.getTime() === at.getTime();
            return (
              <button
                key={slot.key}
                type="button"
                aria-pressed={active}
                onClick={() => setValue({ mode: "later", ...toIstInputs(slot.at) })}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-xs font-bold transition-colors",
                  active
                    ? "border-primary bg-primary/5 text-primary-dark"
                    : "border-[#e2e8f0] bg-white text-[#0A1528] hover:bg-[#f8fafc]",
                )}
              >
                {slot.label}
                <span className="ml-1 font-medium text-[#64748b]">{clockOf(slot.at)}</span>
              </button>
            );
          })}
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2.5">
          <input
            type="date"
            aria-label="Date"
            min={bounds.min}
            max={bounds.max}
            value={value.date}
            onChange={(e) => setValue((v) => ({ ...v, mode: "later", date: e.target.value }))}
            className="h-11 w-full rounded-xl border border-[#e2e8f0] bg-white px-3 text-sm text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
          <input
            type="time"
            aria-label="Time"
            value={value.time}
            onChange={(e) => setValue((v) => ({ ...v, mode: "later", time: e.target.value }))}
            className="h-11 w-full rounded-xl border border-[#e2e8f0] bg-white px-3 text-sm text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
        </div>

        <div
          className={cn(
            "mt-4 rounded-xl px-3.5 py-2.5 text-sm font-bold",
            invalid ? "bg-[#fff1ec] text-[#c2410c]" : "bg-primary/5 text-primary-dark",
          )}
        >
          {preview}
        </div>

        {count > 1 && (
          <div className="mt-3 flex items-start gap-2 text-xs text-[#64748b]">
            <Info size={14} className="mt-0.5 shrink-0" />
            <span>All {count} will be sent at the same time.</span>
          </div>
        )}

        {serverError && (
          <p role="alert" className="mt-3 text-sm text-red-700">
            {serverError}
          </p>
        )}

        <div className="mt-6 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={onClose}
            className="h-10 rounded-xl border border-[#e2e8f0] bg-white px-4 text-sm font-bold text-[#0A1528] hover:bg-[#f8fafc]"
          >
            Keep as is
          </button>
          <button
            type="button"
            autoFocus
            disabled={invalid || busy}
            onClick={() => void submit()}
            className="h-10 rounded-xl bg-primary px-4 text-sm font-bold text-white hover:opacity-90 disabled:opacity-40"
          >
            {busy ? "Saving…" : "Reschedule"}
          </button>
        </div>
      </div>
    </div>
  );
}

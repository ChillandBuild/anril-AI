"use client";
import { useState } from "react";
import { AlertTriangle, CalendarClock, Clock } from "lucide-react";
import type { ScheduledTemplate } from "@/lib/api";
import { cn } from "@/lib/utils";
import { checkSendAt, formatSendTime, fromIstInputs, toIstInputs } from "@/lib/schedule-time";

const WAITING: ScheduledTemplate["status"][] = ["scheduled", "sending"];

/** One compact line per waiting template, with Cancel: shown inside the Send details card. */
export function ScheduledRows({
  items,
  canChange,
  onCancel,
}: {
  items: ScheduledTemplate[];
  canChange: boolean;
  onCancel: (id: string) => void;
}) {
  const waiting = items.filter((i) => WAITING.includes(i.status));
  if (waiting.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5" aria-label="Already scheduled for this lead">
      {waiting.map((item) => (
        <div key={item.id} className="flex items-center gap-2.5 rounded-xl border border-primary-100 bg-primary-50 py-1 pl-2.5 pr-1.5">
          <CalendarClock size={15} className="shrink-0 text-primary" />
          <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2">
            <b className="font-label text-xs text-[#13284A]">
              {item.status === "sending" ? "Sending now" : `Scheduled · ${formatSendTime(new Date(item.send_at))} IST`}
            </b>
            <code className="break-all font-mono text-[10.5px] text-[#64748b]">{item.template_name}</code>
          </div>
          {item.status === "scheduled" && canChange && (
            <button
              type="button"
              onClick={() => onCancel(item.id)}
              className="rounded-lg px-2 py-1 font-label text-xs font-bold text-red-700 hover:bg-red-50"
            >
              Cancel
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function Bubble({
  item,
  canChange,
  onCancel,
  onReschedule,
}: {
  item: ScheduledTemplate;
  canChange: boolean;
  onCancel: (id: string) => void;
  onReschedule: (id: string, at: Date) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const notSent = item.status === "failed" || item.status === "skipped";
  if (notSent) {
    return (
      <div className="flex justify-end">
        <div
          className={cn(
            "flex max-w-[88%] flex-col gap-1.5 rounded-2xl border px-3.5 py-2.5",
            item.status === "failed" ? "border-red-200 bg-red-50" : "border-[#e2e8f0] bg-[#f8fafc]",
          )}
        >
          <p
            className={cn(
              "flex items-center gap-1.5 font-label text-[10px] font-extrabold uppercase tracking-wider",
              item.status === "failed" ? "text-red-700" : "text-[#64748b]",
            )}
          >
            <AlertTriangle size={12} className="shrink-0" />
            <span>
              Not sent
              {item.reason && <span className="font-body text-[11.5px] font-semibold normal-case tracking-normal"> · {item.reason}</span>}
            </span>
          </p>
          <p className="whitespace-pre-wrap font-body text-[12.5px] leading-relaxed text-[#475569]">{item.content}</p>
        </div>
      </div>
    );
  }

  function startEdit() {
    const inputs = toIstInputs(new Date(item.send_at));
    setDate(inputs.date);
    setTime(inputs.time);
    setError("");
    setEditing(true);
  }

  async function save() {
    const at = fromIstInputs(date, time);
    const problem = checkSendAt(at, new Date());
    if (problem || !at) {
      setError(problem || "Pick a date and time.");
      return;
    }
    setSaving(true);
    try {
      await onReschedule(item.id, at);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't change the time");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex justify-end">
      <div className="flex max-w-[88%] flex-col gap-1.5 rounded-2xl border-[1.5px] border-dashed border-primary bg-white px-3.5 py-2.5">
        <p className="flex items-center gap-1.5 font-label text-[10px] font-extrabold uppercase tracking-wider text-primary-900">
          <Clock size={12} />
          {item.status === "sending" ? "Sending now" : `Scheduled · ${formatSendTime(new Date(item.send_at))} IST`}
        </p>
        <p className="whitespace-pre-wrap font-body text-[12.5px] leading-relaxed text-[#13284A]">{item.content}</p>
        {item.status === "scheduled" && canChange && !editing && (
          <div className="mt-0.5 flex gap-0.5 border-t border-primary-100 pt-1.5">
            <button type="button" onClick={startEdit} className="rounded-lg px-2 py-1 font-label text-xs font-bold text-primary hover:bg-primary-50">
              Change time
            </button>
            <button type="button" onClick={() => onCancel(item.id)} className="rounded-lg px-2 py-1 font-label text-xs font-bold text-red-700 hover:bg-red-50">
              Cancel
            </button>
          </div>
        )}
        {editing && (
          <div className="flex flex-col gap-1.5 border-t border-primary-100 pt-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                aria-label="New date"
                className="min-w-0 flex-1 rounded-[10px] border border-[#e2e8f0] bg-white px-2.5 py-1.5 font-body text-xs focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <input
                type="time"
                step={300}
                value={time}
                onChange={(e) => setTime(e.target.value)}
                aria-label="New time (IST)"
                className="min-w-0 flex-1 rounded-[10px] border border-[#e2e8f0] bg-white px-2.5 py-1.5 font-body text-xs focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving}
                className="rounded-lg px-2 py-1 font-label text-xs font-bold text-primary hover:bg-primary-50 disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save"}
              </button>
              <button type="button" onClick={() => setEditing(false)} className="rounded-lg px-2 py-1 font-label text-xs font-bold text-[#64748b] hover:bg-[#f1f5f9]">
                Discard
              </button>
            </div>
            {error && (
              <p className="flex items-start gap-1.5 font-label text-xs text-red-700">
                <AlertTriangle size={13} className="mt-0.5 shrink-0 text-red-600" />
                {error}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** The thread's waiting templates as dashed bubbles, and a line for any that were not sent. */
export function ScheduledBubbles({
  items,
  canChange,
  onCancel,
  onReschedule,
}: {
  items: ScheduledTemplate[];
  canChange: boolean;
  onCancel: (id: string) => void;
  onReschedule: (id: string, at: Date) => Promise<void>;
}) {
  return (
    <>
      {items.map((item) => (
        <Bubble key={item.id} item={item} canChange={canChange} onCancel={onCancel} onReschedule={onReschedule} />
      ))}
    </>
  );
}

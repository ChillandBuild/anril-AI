"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { CalendarDays, History, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useSyncStart } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

function isoLocal(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localDate(daysBack = 0) {
  const date = new Date();
  date.setDate(date.getDate() - daysBack);
  return isoLocal(date);
}

/** Today minus N months, clamped to the end of the target month (31 Mar - 1 month = 28/29 Feb). */
function monthsBack(months: number) {
  const today = new Date();
  const target = new Date(today.getFullYear(), today.getMonth() - months, 1);
  const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(today.getDate(), lastDay));
  return isoLocal(target);
}

/** "2026-08-24" -> "24 Aug 2026". */
function formatDay(iso: string) {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

type SyncOption = { value: string; label: string; date?: string };

/**
 * Data-from presets. A preset may never reach before the account's first ad:
 * any preset dated on or before it collapses into one "Since your first ad" option
 * dated to that ad, so no two options share a date.
 */
function buildSyncOptions(earliestAd: string): SyncOption[] {
  const presets = [1, 2, 3].map((months) => ({
    date: monthsBack(months),
    label: months === 1 ? "Last 1 month" : `Last ${months} months`,
  }));
  const asOption = (preset: { date: string; label: string }): SyncOption => ({ value: preset.date, label: preset.label, date: preset.date });
  const custom: SyncOption = { value: "custom", label: "Custom date" };
  if (!earliestAd || presets.every((preset) => preset.date > earliestAd)) return [...presets.map(asOption), custom];
  return [
    ...presets.filter((preset) => preset.date > earliestAd).map(asOption),
    { value: earliestAd, label: "Since your first ad", date: earliestAd },
    custom,
  ];
}

/**
 * "Data from: 11 Aug 2026" and its popup: how far back Anril pulls ad data from
 * Meta. One setting per ad account, shared by the Messaging ads and All ads tabs.
 * Saving re-pulls history in the background; `onSaved` reloads the caller's table.
 */
export function DataFromPicker({
  canManage,
  note,
  onSaved,
  className,
  variant = "button",
}: {
  canManage: boolean;
  note: ReactNode;
  onSaved?: () => unknown;
  className?: string;
  /** "inline": a one-line "Anril has ad data from … · Change" row whose choices open in place (inside the Dates menu). */
  variant?: "button" | "inline";
}) {
  const { data: syncStart, mutate: mutateSyncStart } = useSyncStart();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState("custom");
  const [customDate, setCustomDate] = useState("");
  const [saving, setSaving] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const label = syncStart?.start_date ? formatDay(syncStart.start_date) : "last 30 days";
  const today = localDate();
  const historyFloor = syncStart ? localDate(syncStart.max_history_days) : "";
  const earliestAd = (syncStart?.earliest_ad_start ?? "").slice(0, 10);
  // Custom date may go no earlier than the later of: the earliest ad's start, or the history limit.
  const customMin = earliestAd && earliestAd > historyFloor ? earliestAd : historyFloor;
  const options = buildSyncOptions(earliestAd);
  const chosen = choice === "custom" ? customDate : choice;

  function toggle() {
    const current = (syncStart?.start_date ?? "").slice(0, 10);
    const match = options.find((option) => option.date === current);
    setChoice(match ? match.value : "custom");
    setCustomDate(current || customMin || today);
    setOpen((visible) => !visible);
  }

  async function save() {
    if (!chosen) return;
    setSaving(true);
    try {
      await api.inboundLeads.setSyncStart(chosen);
      toast.success(`Pulling ad data from ${formatDay(chosen)} — this can take a few minutes.`);
      setOpen(false);
      await Promise.all([mutateSyncStart(), onSaved?.()]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save the history date");
    } finally {
      setSaving(false);
    }
  }

  const panel = (
    <>
          <p className="font-label text-xs font-bold text-[#13284A]">How far back should Anril pull ad data?</p>
          <div role="radiogroup" aria-label="History range" className="mt-3 space-y-1">
            {options.map((option) => {
              const tooOld = option.date !== undefined && Boolean(historyFloor) && option.date < historyFloor;
              return (
                <label key={option.value}
                  className={cn(
                    "flex items-center gap-2 rounded-xl px-2 py-2 font-label text-[11px] font-bold text-stone-700 hover:bg-stone-50",
                    tooOld && "cursor-not-allowed opacity-40",
                  )}>
                  <input type="radio" name="sync-start-range" value={option.value}
                    checked={choice === option.value} disabled={tooOld}
                    onChange={() => setChoice(option.value)}
                    className="h-3.5 w-3.5 accent-primary-600" />
                  <span className="flex-1">{option.label}</span>
                  {option.date && <span className="font-body text-[10px] font-medium text-stone-400">from {formatDay(option.date)}</span>}
                </label>
              );
            })}
          </div>
          {choice === "custom" && (
            <input type="date" aria-label="Custom start date" value={customDate}
              min={customMin || undefined} max={today}
              onChange={(event) => setCustomDate(event.target.value)}
              className="mt-2 h-9 w-full rounded-xl border border-surface-mid bg-white px-3 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200" />
          )}
          <p className="mt-3 font-body text-[10px] leading-4 text-stone-500">{note}</p>
          {earliestAd && (
            <p className="mt-1.5 font-body text-[10px] leading-4 text-stone-500">
              Your first ad on this account was created on {formatDay(earliestAd)}.
            </p>
          )}
          <button type="button" onClick={save} disabled={saving || !chosen}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2 font-label text-xs font-bold text-white transition hover:bg-primary/90 disabled:opacity-40">
            {saving && <Loader2 size={13} className="animate-spin" />}
            {saving ? "Saving…" : "Save"}
          </button>
    </>
  );

  if (variant === "inline") {
    return (
      <div ref={rootRef} className={className}>
        <div className="flex items-center gap-2.5 rounded-xl border border-[#eef2f6] bg-[#f8fafc] px-3 py-2">
          <History size={14} className="shrink-0 text-[#64748b]" aria-hidden="true" />
          <span className="min-w-0 flex-1 font-body text-[11px] leading-4 text-[#475569]">
            {syncStart?.start_date
              ? <>Anril has ad data from <b className="text-[#0A1528]">{label}</b></>
              : <>No history date set for this account</>}
          </span>
          {canManage && (
            <button type="button" onClick={toggle} aria-expanded={open}
              className="shrink-0 font-label text-[11px] font-bold text-primary-700 hover:text-primary-900">
              {open ? "Close" : "Change"}
            </button>
          )}
        </div>
        {canManage && open && (
          <div role="group" aria-label="How far back to pull ad data" className="mt-2 rounded-xl border border-[#e2e8f0] p-3">
            {panel}
          </div>
        )}
      </div>
    );
  }

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      {canManage ? (
        <button type="button" onClick={toggle}
          aria-expanded={open} aria-haspopup="dialog"
          title="Choose how far back Anril pulls ad data from Meta"
          className="flex h-9 w-full items-center justify-center gap-2 whitespace-nowrap rounded-xl border border-surface-mid bg-white px-3 py-2 font-label text-xs font-bold text-on-surface shadow-sm transition-all hover:border-primary-300 hover:text-primary-700">
          <CalendarDays size={12} /> Data from: {label}
        </button>
      ) : (
        <div className="flex h-9 w-full items-center justify-center gap-2 whitespace-nowrap rounded-xl border border-surface-mid bg-white px-3 py-2 font-label text-xs font-bold text-on-surface-muted shadow-sm">
          <CalendarDays size={12} /> Data from: {label}
        </div>
      )}
      {canManage && open && (
        <div role="dialog" aria-label="How far back to pull ad data"
          className="absolute right-0 top-11 z-30 w-[300px] max-w-[calc(100vw-2rem)] rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-xl">
          {panel}
        </div>
      )}
    </div>
  );
}

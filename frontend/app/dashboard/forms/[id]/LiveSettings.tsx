"use client";
import { Plus, X } from "lucide-react";
import type { WaBookingSettings, WaFormSettings, WaOrderSettings } from "@/lib/api";
import { cn } from "@/lib/utils";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { SwitchPill } from "@/components/ui/controls";

/* Options of a live form (backend services/whatsapp_live_forms.clean_settings). Changes apply on Save. */

const DAYS: { key: string; name: string }[] = [
  { key: "mon", name: "Monday" }, { key: "tue", name: "Tuesday" }, { key: "wed", name: "Wednesday" },
  { key: "thu", name: "Thursday" }, { key: "fri", name: "Friday" }, { key: "sat", name: "Saturday" },
  { key: "sun", name: "Sunday" },
];
const MAX_RANGES = 4;

const card = "space-y-4 rounded-2xl bg-surface p-5 ring-1 ring-surface-mid";

function NumberSetting({
  label, hint, value, min, max, unit, disabled, onChange,
}: {
  label: string; hint: string; value: number; min: number; max: number; unit: string; disabled?: boolean;
  onChange: (v: number) => void;
}) {
  const bad = !Number.isFinite(value) || value < min || value > max;
  return (
    <label className="block space-y-1.5">
      <span className="font-label text-xs font-semibold text-ink">{label}</span>
      <span className="flex items-center gap-2">
        <input
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          value={Number.isFinite(value) ? value : ""}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value === "" ? NaN : Math.round(Number(e.target.value)))}
          className={cn(
            "w-24 rounded-lg border bg-surface px-3 py-2 font-body text-sm tabular-nums text-ink focus:outline-none focus:ring-2 focus:ring-primary/15",
            bad ? "border-red-300" : "border-surface-mid focus:border-primary/40",
          )}
        />
        <span className="font-body text-xs text-ink-secondary">{unit}</span>
      </span>
      <span className={cn("block font-body text-[11px]", bad ? "font-semibold text-red-600" : "text-ink-muted")}>
        {bad ? `Use a number from ${min} to ${max}.` : hint}
      </span>
    </label>
  );
}

export function OrderSettingsEditor({
  settings, disabled, onChange,
}: { settings: WaFormSettings; disabled?: boolean; onChange: (s: WaOrderSettings) => void }) {
  const current: WaOrderSettings = { max_items: settings.max_items ?? 3, ask_address: settings.ask_address ?? true };
  return (
    <section className={card}>
      <div className="space-y-1.5">
        <span className="font-label text-xs font-semibold text-ink">Products in one order</span>
        <SegmentedControl
          aria-label="Products in one order"
          value={String(current.max_items)}
          disabled={disabled}
          onChange={(v) => onChange({ ...current, max_items: Number(v) })}
          options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))}
        />
        <p className="font-body text-[11px] text-ink-muted">
          How many different products a customer can tick. Quantities never go above your stock.
        </p>
      </div>
      <label className="flex items-start justify-between gap-4 border-t border-surface-mid pt-4">
        <span className="space-y-0.5">
          <span className="block font-label text-xs font-semibold text-ink">Ask for a delivery address</span>
          <span className="block font-body text-[11px] text-ink-muted">Turn off for pickup or digital products.</span>
        </span>
        <SwitchPill
          size="sm"
          on={current.ask_address}
          disabled={disabled}
          onChange={(v) => onChange({ ...current, ask_address: v })}
          aria-label="Ask for a delivery address"
        />
      </label>
    </section>
  );
}

/** What's wrong with the booking options, in plain words (the server checks again on Save). */
export function bookingProblems(settings: WaFormSettings): string[] {
  const out: string[] = [];
  const hours = settings.hours ?? {};
  if (!DAYS.some((d) => (hours[d.key] ?? []).length > 0)) out.push("Add the hours you take bookings on at least one day.");
  for (const d of DAYS) {
    for (const [start, end] of hours[d.key] ?? []) {
      if (!start || !end) out.push(`${d.name}: fill in both times.`);
      else if (start >= end) out.push(`${d.name}: the closing time must be after the opening time.`);
    }
  }
  const ranges: [keyof WaBookingSettings, number, number, string][] = [
    ["days_ahead", 1, 60, "Days ahead"], ["slot_minutes", 10, 480, "Slot length"],
    ["capacity", 1, 50, "Customers per slot"], ["min_notice_minutes", 0, 10080, "Notice"],
  ];
  for (const [key, min, max, name] of ranges) {
    const v = settings[key] as number | undefined;
    if (v === undefined || !Number.isFinite(v) || v < min || v > max) out.push(`${name}: use a number from ${min} to ${max}.`);
  }
  return out;
}

export function BookingSettingsEditor({
  settings, disabled, onChange,
}: { settings: WaFormSettings; disabled?: boolean; onChange: (s: WaFormSettings) => void }) {
  const hours = settings.hours ?? {};
  const set = (patch: WaFormSettings) => onChange({ ...settings, ...patch });
  const setDay = (day: string, ranges: [string, string][]) => set({ hours: { ...hours, [day]: ranges } });

  return (
    <div className="space-y-4">
      <section className={card}>
        <div className="grid gap-5 sm:grid-cols-2">
          <NumberSetting label="Slot length" hint="How long each appointment is." unit="minutes" min={10} max={480}
            value={settings.slot_minutes ?? 30} disabled={disabled} onChange={(v) => set({ slot_minutes: v })} />
          <NumberSetting label="Customers per slot" hint="1 = one customer at a time." unit="per slot" min={1} max={50}
            value={settings.capacity ?? 1} disabled={disabled} onChange={(v) => set({ capacity: v })} />
          <NumberSetting label="Book how far ahead" hint="Only these days show on the form." unit="days" min={1} max={60}
            value={settings.days_ahead ?? 14} disabled={disabled} onChange={(v) => set({ days_ahead: v })} />
          <NumberSetting label="Notice needed" hint="A time this soon from now isn't offered. 0 = none." unit="minutes" min={0} max={10080}
            value={settings.min_notice_minutes ?? 60} disabled={disabled} onChange={(v) => set({ min_notice_minutes: v })} />
        </div>
      </section>

      <section className={cn(card, "space-y-0 divide-y divide-surface-mid p-0")} aria-label="Booking hours">
        <p className="px-5 py-3 font-body text-xs text-ink-secondary">
          Weekly hours, in India time. Times already booked or too soon are left out by themselves.
        </p>
        {DAYS.map((d) => {
          const ranges = hours[d.key] ?? [];
          const open = ranges.length > 0;
          return (
            <div key={d.key} className="flex flex-wrap items-start gap-x-4 gap-y-2 px-5 py-3">
              <label className="flex w-36 shrink-0 items-center gap-2 pt-1.5 font-label text-xs font-semibold text-ink">
                <SwitchPill
                  size="sm"
                  on={open}
                  disabled={disabled}
                  onChange={(v) => setDay(d.key, v ? [["10:00", "18:00"]] : [])}
                  aria-label={`Open on ${d.name}`}
                />
                {d.name}
              </label>
              {open ? (
                <div className="min-w-0 flex-1 space-y-2">
                  {ranges.map(([start, end], i) => (
                    <div key={i} className="flex flex-wrap items-center gap-2">
                      <input
                        type="time"
                        aria-label={`${d.name} opens`}
                        value={start}
                        disabled={disabled}
                        onChange={(e) => setDay(d.key, ranges.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))}
                        className="rounded-lg border border-surface-mid bg-surface px-2.5 py-1.5 font-body text-sm tabular-nums text-ink focus:border-primary/40 focus:outline-none"
                      />
                      <span className="font-body text-xs text-ink-muted">to</span>
                      <input
                        type="time"
                        aria-label={`${d.name} closes`}
                        value={end}
                        disabled={disabled}
                        onChange={(e) => setDay(d.key, ranges.map((r, j) => (j === i ? [r[0], e.target.value] : r)))}
                        className={cn(
                          "rounded-lg border bg-surface px-2.5 py-1.5 font-body text-sm tabular-nums text-ink focus:outline-none",
                          start && end && start >= end ? "border-red-300" : "border-surface-mid focus:border-primary/40",
                        )}
                      />
                      {!disabled && (
                        <button
                          type="button"
                          aria-label={`Remove ${d.name} hours ${i + 1}`}
                          onClick={() => setDay(d.key, ranges.filter((_, j) => j !== i))}
                          className="rounded-lg p-1 text-ink-muted hover:bg-red-50 hover:text-red-600"
                        >
                          <X size={14} />
                        </button>
                      )}
                    </div>
                  ))}
                  {!disabled && ranges.length < MAX_RANGES && (
                    <button
                      type="button"
                      onClick={() => setDay(d.key, [...ranges, ["", ""]])}
                      className="inline-flex items-center gap-1 font-label text-xs font-semibold text-primary-600 hover:text-primary-700"
                    >
                      <Plus size={13} /> Add hours (e.g. after lunch)
                    </button>
                  )}
                </div>
              ) : (
                <p className="pt-1.5 font-body text-xs text-ink-muted">Closed</p>
              )}
            </div>
          );
        })}
      </section>
    </div>
  );
}

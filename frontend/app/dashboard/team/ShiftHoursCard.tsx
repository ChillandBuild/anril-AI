"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Check, Clock, Loader2 } from "lucide-react";
import { Select } from "@/components/ui/Select";
import { api, type Caller } from "@/lib/api";
import { formatHour, type ShiftConfig } from "./shiftHours";

const HOURS = Array.from({ length: 24 }, (_, i) => i);

interface ShiftHoursCardProps {
  callers: Caller[];
  shiftConfig: ShiftConfig;
  onShiftConfigSave: (config: ShiftConfig) => Promise<void>;
  onCallersChange: (updater: (prev: Caller[]) => Caller[]) => void;
  canManageShifts: boolean;
}

/** Work shift hours: one shift for everyone, or one per person. Used for late and idle time and the day timeline.
 *  Not the same as Settings › Calling rules, which stops calls outside its hours. */
export default function ShiftHoursCard({ callers, shiftConfig, onShiftConfigSave, onCallersChange, canManageShifts }: ShiftHoursCardProps) {
  const [local, setLocal] = useState<ShiftConfig>(shiftConfig);
  const [lastExternal, setLastExternal] = useState(shiftConfig);
  const [saving, setSaving] = useState(false);
  const [personId, setPersonId] = useState("");
  const [personStart, setPersonStart] = useState(9);
  const [personEnd, setPersonEnd] = useState(19);

  // Take the saved config when the parent loads or saves a new one.
  if (
    shiftConfig.shift_mode !== lastExternal.shift_mode ||
    shiftConfig.shift_start_hour !== lastExternal.shift_start_hour ||
    shiftConfig.shift_end_hour !== lastExternal.shift_end_hour
  ) {
    setLastExternal(shiftConfig);
    setLocal(shiftConfig);
  }

  const editingPerson = local.shift_mode === "individual" && !!personId;

  const save = async () => {
    if (!canManageShifts) return;
    setSaving(true);
    try {
      await onShiftConfigSave(local);
      if (editingPerson) {
        const { data: updated } = await api.team.updateCallerShift(personId, personStart, personEnd);
        onCallersChange((prev) =>
          prev.map((c) => (c.id === personId ? { ...c, shift_start_hour: updated.shift_start_hour, shift_end_hour: updated.shift_end_hour } : c)),
        );
        toast.success("Shift saved for this person");
      }
    } catch {
      toast.error("The shift was not saved. Try again.");
    } finally {
      setSaving(false);
    }
  };

  const modeButton = (mode: ShiftConfig["shift_mode"], label: string) => (
    <button
      type="button"
      aria-pressed={local.shift_mode === mode}
      disabled={!canManageShifts}
      onClick={() => {
        setLocal((prev) => ({ ...prev, shift_mode: mode }));
        if (mode === "common") setPersonId("");
      }}
      className={`min-h-10 px-3 font-label text-sm font-bold ${local.shift_mode === mode ? "bg-primary text-white" : "bg-white text-ink-secondary hover:bg-black/5"}`}
    >
      {label}
    </button>
  );

  return (
    <section className="rounded-card bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15">
      <h2 className="flex items-center gap-2 font-display text-base font-bold text-primary">
        <Clock size={16} aria-hidden /> Shift hours
      </h2>
      <p className="mt-1 font-label text-xs text-ink-secondary">
        When each person is meant to work. Calls outside set hours are stopped in Settings › Calling rules.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <div className="flex overflow-hidden rounded-lg ring-1 ring-[#c4c7c7]/40" role="group" aria-label="One shift or one per person">
          {modeButton("common", "Same for everyone")}
          {modeButton("individual", "One per person")}
        </div>
        {local.shift_mode === "individual" && (
          <Select
            size="sm"
            className="w-auto min-w-[180px]"
            aria-label="Telecaller"
            value={personId}
            disabled={!canManageShifts}
            onChange={(id) => {
              setPersonId(id);
              const person = callers.find((c) => c.id === id);
              setPersonStart(person?.shift_start_hour ?? local.shift_start_hour);
              setPersonEnd(person?.shift_end_hour ?? local.shift_end_hour);
            }}
            options={[{ value: "", label: "Pick a telecaller" }, ...callers.map((c) => ({ value: c.id, label: c.name }))]}
          />
        )}
        <div className="flex items-center gap-1.5 font-label text-sm">
          <span className="text-ink-secondary">From</span>
          <Select
            size="sm"
            className="w-auto min-w-[96px]"
            aria-label="Shift start"
            value={String(editingPerson ? personStart : local.shift_start_hour)}
            disabled={!canManageShifts}
            onChange={(v) => (editingPerson ? setPersonStart(Number(v)) : setLocal((prev) => ({ ...prev, shift_start_hour: Number(v) })))}
            options={HOURS.map((h) => ({ value: String(h), label: formatHour(h) }))}
          />
          <span className="text-ink-secondary">to</span>
          <Select
            size="sm"
            className="w-auto min-w-[96px]"
            aria-label="Shift end"
            value={String(editingPerson ? personEnd : local.shift_end_hour)}
            disabled={!canManageShifts}
            onChange={(v) => (editingPerson ? setPersonEnd(Number(v)) : setLocal((prev) => ({ ...prev, shift_end_hour: Number(v) })))}
            options={HOURS.map((h) => ({ value: String(h), label: formatHour(h) }))}
          />
        </div>
        <button
          type="button"
          onClick={save}
          disabled={saving || !canManageShifts}
          title={canManageShifts ? undefined : "Your role cannot change shifts"}
          className="inline-flex min-h-10 items-center gap-1.5 rounded-lg bg-primary px-3 font-label text-sm font-bold text-white hover:bg-primary/95 disabled:opacity-50"
        >
          {saving ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Check size={14} aria-hidden />}
          Save
        </button>
      </div>
    </section>
  );
}

"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Select } from "@/components/ui/Select";
import { Users, Check, Loader2, Clock } from "lucide-react";
import { api, type Caller } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

interface ShiftConfig {
  shift_mode: "common" | "individual";
  shift_start_hour: number;
  shift_end_hour: number;
}

interface LiveAgentStatusProps {
  callers: Caller[];
  adminCaller: Caller | null;
  selectedCallerId: string | null;
  onSelectCaller: (id: string | null) => void;
  statsFrom: string;
  statsTo: string;
  onStatsFromChange: (v: string) => void;
  onStatsToChange: (v: string) => void;
  onCallersChange: (updater: (prev: Caller[]) => Caller[]) => void;
  shiftConfig: ShiftConfig;
  onShiftConfigSave: (config: ShiftConfig) => Promise<void>;
  callingProvider: "telecmi" | "sim_basic";
  canManageShifts: boolean;
}

function formatHour(h: number): string {
  return `${h.toString().padStart(2, "0")}:00`;
}

const HOURS = Array.from({ length: 24 }, (_, i) => i);

function AdminCallerCard({ caller, callingProvider }: {
  caller: Caller;
  callingProvider: "telecmi" | "sim_basic";
}) {
  const isTelecmi = callingProvider === "telecmi";
  const needsSetup = isTelecmi
    ? !caller.phone || !caller.telecmi_agent_id
    : !caller.phone;

  return (
    <div className="inline-flex max-w-full flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-primary-300/60 bg-gradient-to-r from-primary-50 via-white to-white py-1 pl-1 pr-3 text-xs shadow-[0_0_0_2px_rgba(var(--primary-500-rgb),0.08),0_4px_14px_-6px_rgba(var(--primary-600-rgb),0.4)]">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-brand-gradient text-[11px] font-bold text-white shadow-[0_0_12px_rgba(var(--primary-500-rgb),0.55)]">
        {caller.name.trim().charAt(0).toUpperCase() || "A"}
      </span>
      <span className="font-bold text-[#13284A] truncate">{caller.name}</span>
      <span className="shrink-0 px-2 py-0.5 rounded-full border text-[10px] font-bold text-primary bg-primary/10 border-primary/20">
        Admin
      </span>
      <span className="h-4 w-px bg-primary-200" aria-hidden />
      <span className="flex items-center gap-1.5 text-[#334155]">
        <span className="text-[10px] font-bold uppercase text-[#94a3b8]">Phone</span>
        {caller.phone || <span className="text-[#94a3b8] italic">Not set</span>}
      </span>
      {isTelecmi && (
        <span className="flex items-center gap-1.5 text-[#334155]">
          <span className="text-[10px] font-bold uppercase text-[#94a3b8]">User ID</span>
          {caller.telecmi_agent_id || <span className="text-[#94a3b8] italic">Not set</span>}
        </span>
      )}
      {needsSetup && (
        <span className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5 font-medium">
          {isTelecmi
            ? "Set phone + User ID in Roles → Users to enable click-to-call"
            : "Set phone in Roles → Users to enable SIM calling"}
        </span>
      )}
    </div>
  );
}

export default function LiveAgentStatus({
  callers, adminCaller, selectedCallerId, onSelectCaller,
  statsFrom, statsTo, onStatsFromChange, onStatsToChange,
  onCallersChange,
  shiftConfig, onShiftConfigSave,
  callingProvider, canManageShifts,
}: LiveAgentStatusProps) {

  // Shift config local editing state
  const [localShiftConfig, setLocalShiftConfig] = useState<ShiftConfig>(shiftConfig);
  const [savingShiftConfig, setSavingShiftConfig] = useState(false);

  // Individual mode: selected caller for shift edit
  const [individualCallerId, setIndividualCallerId] = useState<string>("");
  const [individualStart, setIndividualStart] = useState<number>(9);
  const [individualEnd, setIndividualEnd] = useState<number>(19);
  const [savingIndividual, setSavingIndividual] = useState(false);

  // Keep local config in sync when parent pushes new config
  const [lastExternalConfig, setLastExternalConfig] = useState(shiftConfig);
  if (
    shiftConfig.shift_mode !== lastExternalConfig.shift_mode ||
    shiftConfig.shift_start_hour !== lastExternalConfig.shift_start_hour ||
    shiftConfig.shift_end_hour !== lastExternalConfig.shift_end_hour
  ) {
    setLastExternalConfig(shiftConfig);
    setLocalShiftConfig(shiftConfig);
  }

  const totalAgentsCount = callers.length;
  const breakAgents = callers.filter((c) => c.status === "break");
  const activeAgents = callers.filter((c) => (c.status || "active") === "active");
  const offlineAgents = callers.filter((c) => c.status === "logged_out");

  const handleSaveShiftConfig = async () => {
    if (!canManageShifts) return;
    setSavingShiftConfig(true);
    try {
      await onShiftConfigSave(localShiftConfig);
    } finally {
      setSavingShiftConfig(false);
    }
  };

  const handleSaveIndividualShift = async () => {
    if (!canManageShifts || !individualCallerId) return;
    setSavingIndividual(true);
    try {
      await onShiftConfigSave(localShiftConfig);
      const { data: updated } = await api.team.updateCallerShift(individualCallerId, individualStart, individualEnd);
      onCallersChange((prev) =>
        prev.map((c) =>
          c.id === individualCallerId
            ? { ...c, shift_start_hour: updated.shift_start_hour, shift_end_hour: updated.shift_end_hour }
            : c
        )
      );
      toast.success("Caller shift updated");
    } catch (err) {
      console.error("Failed to update caller shift:", err);
      toast.error("Failed to update caller shift");
    } finally {
      setSavingIndividual(false);
    }
  };

  return (
    <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-3">
        <h2 className="font-display text-sm font-bold text-primary flex items-center gap-2">
          <Users size={16} className="text-primary" /> Live Agent Status
        </h2>
        <div className="flex items-center gap-1.5 bg-[#f8fafc] p-1.5 rounded-xl border border-[#e2e8f0]">
          <span className="font-label text-[10px] text-[#475569] font-bold uppercase pl-1">Range:</span>
          <input type="date" value={statsFrom} onChange={(e) => onStatsFromChange(e.target.value)} className="px-1.5 py-0.5 rounded bg-white border border-[#e2e8f0] font-body text-xs text-[#13284A] focus:outline-none" />
          <span className="text-[#94a3b8] text-xs">to</span>
          <input type="date" value={statsTo} onChange={(e) => onStatsToChange(e.target.value)} className="px-1.5 py-0.5 rounded bg-white border border-[#e2e8f0] font-body text-xs text-[#13284A] focus:outline-none" />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-4 text-xs">
        <div className="flex items-center gap-2 bg-[#f8fafc] border border-[#e2e8f0] px-3 py-1.5 rounded-lg">
          <span className="font-bold text-[#1e293b]">{totalAgentsCount} Total</span>
        </div>
        <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 text-emerald-700 px-3 py-1.5 rounded-lg">
          <span className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
          <span className="font-bold">{activeAgents.length} Ready</span>
        </div>
        <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 text-amber-700 px-3 py-1.5 rounded-lg">
          <span className="w-2 h-2 bg-amber-500 rounded-full" />
          <span className="font-bold">{breakAgents.length} On Break</span>
        </div>
        <div className="flex items-center gap-2 bg-[#f1f5f9] border border-[#d6cfc9] text-[#334155] px-3 py-1.5 rounded-lg">
          <span className="w-2 h-2 bg-[#94a3b8] rounded-full" />
          <span className="font-bold">{offlineAgents.length} Offline</span>
        </div>
      </div>

      {/* Shift Hours config section */}
      <div className="mt-4 p-3 bg-[#f8fafc] rounded-xl border border-[#e2e8f0]">
        <div className="flex items-center gap-2 mb-2">
          <Clock size={14} className="text-[#475569]" />
          <span className="font-label text-xs font-bold text-[#1e293b] uppercase">Shift Hours</span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {/* Mode toggle pill */}
          <div className="flex rounded-lg border border-[#e2e8f0] overflow-hidden">
            <button
              onClick={() => { setLocalShiftConfig((prev) => ({ ...prev, shift_mode: "common" })); setIndividualCallerId(""); }}
              disabled={!canManageShifts}
              className={`px-3 py-1 text-xs font-bold transition-colors ${
                localShiftConfig.shift_mode === "common"
                  ? "bg-primary text-white"
                  : "bg-white text-[#334155] hover:bg-[#f1f5f9]"
              }`}
            >
              Common
            </button>
            <button
              onClick={() => setLocalShiftConfig((prev) => ({ ...prev, shift_mode: "individual" }))}
              disabled={!canManageShifts}
              className={`px-3 py-1 text-xs font-bold transition-colors ${
                localShiftConfig.shift_mode === "individual"
                  ? "bg-primary text-white"
                  : "bg-white text-[#334155] hover:bg-[#f1f5f9]"
              }`}
            >
              Individual
            </button>
          </div>

          {/* Caller dropdown — only in individual mode */}
          {localShiftConfig.shift_mode === "individual" && (
            <Select
              size="sm"
              className="w-auto min-w-[180px]"
              aria-label="Telecaller"
              value={individualCallerId}
              disabled={!canManageShifts}
              onChange={(id) => {
                setIndividualCallerId(id);
                if (id) {
                  const caller = callers.find((c) => c.id === id);
                  setIndividualStart(caller?.shift_start_hour ?? localShiftConfig.shift_start_hour);
                  setIndividualEnd(caller?.shift_end_hour ?? localShiftConfig.shift_end_hour);
                }
              }}
              options={[{ value: "", label: "Select telecaller" }, ...callers.map((c) => ({ value: c.id, label: c.name }))]}
            />
          )}

          {/* Start / End hour selects */}
          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-[#475569] font-medium">Start:</span>
            <Select
              size="sm"
              className="w-auto min-w-[96px]"
              aria-label="Shift start"
              value={String(localShiftConfig.shift_mode === "individual" && individualCallerId ? individualStart : localShiftConfig.shift_start_hour)}
              disabled={!canManageShifts}
              onChange={(v) => {
                const val = parseInt(v);
                if (localShiftConfig.shift_mode === "individual" && individualCallerId) {
                  setIndividualStart(val);
                } else {
                  setLocalShiftConfig((prev) => ({ ...prev, shift_start_hour: val }));
                }
              }}
              options={HOURS.map((h) => ({ value: String(h), label: formatHour(h) }))}
            />
            <span className="text-[#475569] font-medium ml-1">End:</span>
            <Select
              size="sm"
              className="w-auto min-w-[96px]"
              aria-label="Shift end"
              value={String(localShiftConfig.shift_mode === "individual" && individualCallerId ? individualEnd : localShiftConfig.shift_end_hour)}
              disabled={!canManageShifts}
              onChange={(v) => {
                const val = parseInt(v);
                if (localShiftConfig.shift_mode === "individual" && individualCallerId) {
                  setIndividualEnd(val);
                } else {
                  setLocalShiftConfig((prev) => ({ ...prev, shift_end_hour: val }));
                }
              }}
              options={HOURS.map((h) => ({ value: String(h), label: formatHour(h) }))}
            />
          </div>

          {/* Single Save button */}
          <button
            onClick={localShiftConfig.shift_mode === "individual" && individualCallerId ? handleSaveIndividualShift : handleSaveShiftConfig}
            disabled={savingShiftConfig || savingIndividual || !canManageShifts}
            title={canManageShifts ? "Save shift hours" : "Read-only role: shift changes are disabled"}
            className="flex items-center gap-1 px-3 py-1 bg-primary text-white rounded-lg hover:bg-primary/95 disabled:opacity-50 disabled:blur-[0.5px] font-label text-xs font-semibold transition-colors"
          >
            {(savingShiftConfig || savingIndividual) ? <Loader2 className="animate-spin" size={12} /> : <Check size={12} />}
            Save
          </button>
        </div>
      </div>

      {/* Admin caller card — separate from team, non-deletable */}
      {adminCaller && (
        <div className="mt-3">
          <span className="font-label text-[10px] font-bold text-[#475569] uppercase tracking-wide">Admin</span>
          <div className="mt-1">
            <AdminCallerCard caller={adminCaller} callingProvider={callingProvider} />
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-3 mt-3">
        {callers.map((c) => {
          const st = c.status || "active";
          const statusColor = st === "active" ? "text-emerald-700 bg-emerald-50 border-emerald-200" : st === "break" ? "text-amber-700 bg-amber-50 border-amber-200" : "text-[#475569] bg-[#f1f5f9] border-[#e2e8f0]";
          const isSelected = selectedCallerId === c.id;

          // Effective shift for this caller
          const effectiveStart = localShiftConfig.shift_mode === "individual" && c.shift_start_hour != null
            ? c.shift_start_hour
            : localShiftConfig.shift_start_hour;
          const effectiveEnd = localShiftConfig.shift_mode === "individual" && c.shift_end_hour != null
            ? c.shift_end_hour
            : localShiftConfig.shift_end_hour;

          const nowIST = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
          const currentHour = nowIST.getHours();
          const isOutsideShift = currentHour < effectiveStart || currentHour >= effectiveEnd;

          return (
            <div
              key={c.id}
              onClick={() => onSelectCaller(selectedCallerId === c.id ? null : c.id)}
              className={`relative flex items-center justify-between p-2.5 bg-surface-low rounded-xl border text-xs cursor-pointer transition-all ${
                isSelected ? "ring-2 ring-primary border-primary/40 bg-primary/5" : "border-[#f1f5f9] hover:border-[#e2e8f0]"
              }`}
            >
              <div className="truncate pr-2">
                <span className="font-bold text-[#13284A]">{c.name}</span>
                {c.status_changed_at && (
                  <span className="block text-[10px] text-[#94a3b8] font-medium">Since {timeAgo(c.status_changed_at)}</span>
                )}
                <div className="flex items-center gap-1.5 text-xs text-[#475569] mt-0.5">
                  <span>{c.phone || "—"}</span>
                  {callingProvider === "telecmi" && (
                    <>
                      <span className="text-[#d6cfc9]">&middot;</span>
                      <span>{c.telecmi_agent_id || "—"}</span>
                    </>
                  )}
                </div>
                {/* Shift time display (read-only) */}
                <div className="flex items-center gap-1 mt-0.5">
                  <Clock size={9} className={isOutsideShift ? "text-amber-500" : "text-[#94a3b8]"} />
                  <span className={`text-[10px] font-medium ${isOutsideShift ? "text-amber-500" : "text-[#94a3b8]"}`}>
                    {formatHour(effectiveStart)}&ndash;{formatHour(effectiveEnd)}
                  </span>
                </div>
              </div>
              <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold shrink-0 ${statusColor}`}>
                {st === "logged_out" ? "Offline" : st}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Check, Loader2, X } from "lucide-react";
import { api, API_URL, getAuthHeaders, type Caller } from "@/lib/api";
import { cn, istTodayIso } from "@/lib/utils";
import { useAuthRole } from "../contexts/AuthRoleContext";
import TeamAttendanceGrid from "./TeamAttendanceGrid";
import ShiftHoursCard from "./ShiftHoursCard";
import { effectiveShift, formatHour, type ShiftConfig } from "./shiftHours";
import FeedbackOversight from "../telecalling/components/sections/FeedbackOversight";
import ShiftTimeline from "../telecalling/components/sections/ShiftTimeline";
import BulkAssignment from "../telecalling/components/sections/BulkAssignment";

interface PeopleViewProps {
  callers: Caller[];
  adminCaller?: Caller | null;
  callingProvider?: "telecmi" | "sim_basic";
  /** Show only this team's telecallers (callers.team_id). null/undefined = everyone. */
  teamFilter?: string | null;
}

function AdminCallerCard({ caller, cloud }: { caller: Caller; cloud: boolean }) {
  const needsSetup = cloud ? !caller.phone || !caller.telecmi_agent_id : !caller.phone;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-primary/5 px-3 py-2 font-label text-sm ring-1 ring-primary/15">
      <span className="font-bold text-primary">{caller.name}</span>
      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-bold text-primary">Admin</span>
      <span className="text-ink-secondary">Phone {caller.phone || "not set"}</span>
      {cloud ? <span className="text-ink-secondary">User ID {caller.telecmi_agent_id || "not set"}</span> : null}
      {needsSetup ? (
        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-200">
          {cloud ? "Set phone + User ID in Roles › Users to call from here" : "Set phone in Roles › Users to call from your SIM"}
        </span>
      ) : null}
    </div>
  );
}

/** Team = the people: shift hours, daily targets, attendance, the day timeline, and moving leads.
 *  How they are doing lives on Call IQ › Live, Evaluation and Results. */
export default function PeopleView({ callers, adminCaller, callingProvider, teamFilter }: PeopleViewProps) {
  const { role, roleSlug, permissions } = useAuthRole();
  const canManageTeam = role === "owner" || permissions.includes("team.manage");
  // A Team leader works their team but cannot change business-wide shifts or targets.
  const canChangeShifts = canManageTeam && roleSlug !== "team_leader";
  // Same rules as the server: only the owner sets daily targets; the owner or a Team leader moves leads.
  const canSetTargets = role === "owner";
  const canMoveLeads = role === "owner" || roleSlug === "team_leader";
  const cloud = callingProvider !== "sim_basic";

  const [people, setPeople] = useState<Caller[]>(callers);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [targets, setTargets] = useState<Record<string, number>>({});
  const [savingTargetId, setSavingTargetId] = useState<string | null>(null);
  const [shiftConfig, setShiftConfig] = useState<ShiftConfig>({ shift_mode: "common", shift_start_hour: 9, shift_end_hour: 19 });

  const loadPeople = useCallback(async () => {
    try {
      setPeople((await api.callers.list()).data);
    } catch {
      // keep the list the page already has
    }
  }, []);

  useEffect(() => {
    void loadPeople();
  }, [loadPeople]);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/settings/telecalling-config`, { headers: await getAuthHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        setShiftConfig({
          shift_mode: data.shift_mode || "common",
          shift_start_hour: data.shift_start_hour ?? 9,
          shift_end_hour: data.shift_end_hour ?? 19,
        });
      } catch {
        // the defaults stay
      }
    })();
  }, []);

  async function saveShiftConfig(config: ShiftConfig) {
    if (!canChangeShifts) return;
    setShiftConfig(await api.team.updateShiftConfig(config));
    toast.success("Shift hours saved");
  }

  async function saveTarget(callerId: string) {
    const value = targets[callerId];
    if (value === undefined) return;
    setSavingTargetId(callerId);
    try {
      await api.callers.updateTarget(callerId, value);
      setPeople((prev) => prev.map((c) => (c.id === callerId ? { ...c, target: value } : c)));
      setTargets((prev) => {
        const next = { ...prev };
        delete next[callerId];
        return next;
      });
      toast.success("Daily target saved");
    } catch {
      toast.error("The target was not saved. Try again.");
    } finally {
      setSavingTargetId(null);
    }
  }

  const shown = people.filter((c) => !teamFilter || c.team_id === teamFilter);
  const selected = people.find((c) => c.id === selectedId) ?? null;
  const today = istTodayIso();

  return (
    <div className="space-y-5 pb-12">
      <p className="font-label text-sm text-ink-secondary">
        Who is calling now is on <Link href="/dashboard/call-iq/live" className="font-bold text-primary underline">Live</Link>, call scores
        on <Link href="/dashboard/call-iq/evaluation" className="font-bold text-primary underline">Evaluation</Link>, calls and orders
        on <Link href="/dashboard/call-iq/results" className="font-bold text-primary underline">Results</Link>.
      </p>

      <ShiftHoursCard
        callers={people}
        shiftConfig={shiftConfig}
        onShiftConfigSave={saveShiftConfig}
        onCallersChange={setPeople}
        canManageShifts={canChangeShifts}
      />

      <section className="rounded-card bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15">
        <h2 className="font-display text-base font-bold text-primary">Telecallers</h2>
        <p className="mt-1 font-label text-xs text-ink-secondary">Tap a person to see their attendance and today&apos;s timeline below.</p>
        {adminCaller ? <div className="mt-3"><AdminCallerCard caller={adminCaller} cloud={cloud} /></div> : null}
        {shown.length === 0 ? (
          <p className="mt-3 font-label text-sm text-ink-secondary">No telecallers yet.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-left font-label text-sm">
              <thead>
                <tr className="border-b border-[#c4c7c7]/40 text-ink-secondary">
                  <th scope="col" className="py-2 pr-3 font-bold">Name</th>
                  <th scope="col" className="py-2 pr-3 font-bold">Phone</th>
                  {cloud ? <th scope="col" className="py-2 pr-3 font-bold">User ID</th> : null}
                  <th scope="col" className="py-2 pr-3 font-bold">Shift</th>
                  <th scope="col" className="py-2 pr-3 font-bold">Daily target</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((c) => {
                  const shift = effectiveShift(shiftConfig, c);
                  const target = targets[c.id] ?? c.target ?? 0;
                  const isSelected = selectedId === c.id;
                  return (
                    <tr key={c.id} className={cn("border-b border-[#c4c7c7]/20 last:border-0", isSelected && "bg-primary/5")}>
                      <td className="py-2 pr-3">
                        <button
                          type="button"
                          aria-pressed={isSelected}
                          onClick={() => setSelectedId(isSelected ? null : c.id)}
                          className="min-h-10 text-left font-bold text-primary hover:underline"
                        >
                          {c.name}
                        </button>
                        {c.team_name ? <span className="ml-2 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">{c.team_name}</span> : null}
                      </td>
                      <td className="py-2 pr-3 text-ink-secondary">{c.phone || "Not set"}</td>
                      {cloud ? <td className="py-2 pr-3 text-ink-secondary">{c.telecmi_agent_id || "Not set"}</td> : null}
                      <td className="py-2 pr-3 text-ink-secondary">{formatHour(shift.start)} to {formatHour(shift.end)}</td>
                      <td className="py-2 pr-3">
                        <div className="flex items-center gap-1.5">
                          <input
                            type="number"
                            min={0}
                            aria-label={`Daily target for ${c.name}`}
                            value={target}
                            disabled={!canSetTargets}
                            onChange={(e) => setTargets((prev) => ({ ...prev, [c.id]: parseInt(e.target.value, 10) || 0 }))}
                            className="min-h-10 w-20 rounded-lg bg-white px-2 text-center font-bold text-primary ring-1 ring-[#c4c7c7]/50 focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-60"
                          />
                          {targets[c.id] !== undefined ? (
                            <button
                              type="button"
                              onClick={() => saveTarget(c.id)}
                              disabled={savingTargetId === c.id}
                              aria-label={`Save daily target for ${c.name}`}
                              className="inline-flex min-h-10 min-w-10 items-center justify-center rounded-lg text-emerald-700 ring-1 ring-emerald-200 hover:bg-emerald-50"
                            >
                              {savingTargetId === c.id ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Check size={14} aria-hidden />}
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {callingProvider === "sim_basic" && role === "owner" ? <FeedbackOversight /> : null}

      {selected ? (
        <div className="flex flex-wrap items-center gap-2 font-label text-sm">
          <span className="text-ink-secondary">Showing <span className="font-bold text-primary">{selected.name}</span></span>
          <button
            type="button"
            onClick={() => setSelectedId(null)}
            className="inline-flex min-h-10 items-center gap-1 rounded-lg px-2 font-bold text-ink-secondary hover:bg-black/5"
          >
            <X size={14} aria-hidden /> Show everyone
          </button>
        </div>
      ) : null}

      <TeamAttendanceGrid selectedCallerId={selectedId} selectedCallerName={selected?.name} />

      {selected ? (
        <ShiftTimeline
          callerId={selected.id}
          statsFrom={today}
          statsTo={today}
          shiftStartHour={effectiveShift(shiftConfig, selected).start}
          shiftEndHour={effectiveShift(shiftConfig, selected).end}
        />
      ) : null}

      {canMoveLeads ? <BulkAssignment callers={people} /> : null}
    </div>
  );
}

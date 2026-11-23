"use client";
import { useEffect, useState, useMemo, useCallback } from "react";
import { format, parseISO, startOfMonth, addDays } from "date-fns";
import { Loader2, CalendarCheck, UserCheck, UserX, Percent, CheckCircle2, XCircle, Download, Sun, Users } from "lucide-react";
import { toast } from "sonner";
import { api, TeamAttendanceGridData } from "@/lib/api";
import { dotColorClass, WEEKDAY_LABELS, buildMiniMonths } from "./helpers";
import { useAuthRole } from "../contexts/AuthRoleContext";

interface TeamAttendanceGridProps {
  selectedCallerId?: string | null;
  selectedCallerName?: string | null;
}

export default function TeamAttendanceGrid({ selectedCallerId, selectedCallerName }: TeamAttendanceGridProps) {
  const { role, permissions } = useAuthRole();
  const canManageTeam = role === "owner" || permissions.includes("team.manage");
  const today = format(new Date(), "yyyy-MM-dd");
  const [from, setFrom] = useState(() => format(startOfMonth(new Date()), "yyyy-MM-dd"));
  const [to, setTo] = useState(() => format(new Date(), "yyyy-MM-dd"));
  const [data, setData] = useState<TeamAttendanceGridData | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  const [sixMonthDays, setSixMonthDays] = useState<{ date: string; status: string }[]>([]);
  const [sixMonthLoading, setSixMonthLoading] = useState(true);
  const [sixMonthCallerName, setSixMonthCallerName] = useState<string>("");

  const [markDate, setMarkDate] = useState(today);
  const [marking, setMarking] = useState(false);

  const [holidayDate, setHolidayDate] = useState(today);
  const [markingHoliday, setMarkingHoliday] = useState(false);
  const maxHolidayDate = format(addDays(new Date(), 14), "yyyy-MM-dd");

  const fetchGrid = useCallback(() => {
    setLoading(true);
    return api.team.attendanceGrid({ from, to })
      .then((res) => setData(res.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [from, to]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.team.attendanceGrid({ from, to })
      .then((res) => { if (!cancelled) setData(res.data); })
      .catch(() => { if (!cancelled) setData(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [from, to]);

  // Compute how many holidays are in the current days range
  const holidayCount = useMemo(() => {
    if (!data) return 0;
    const holidayDays = data.days.filter((d) => {
      return data.callers.some((c) => data.grid[c.caller_id]?.[d] === "holiday");
    });
    return holidayDays.length;
  }, [data]);

  const rows = useMemo(() => {
    if (!data) return [];
    return data.callers;
  }, [data]);

  // Resolve which caller's 6-month calendar to show (only if selected)
  const sixMonthCallerId = useMemo(() => {
    if (selectedCallerId) return selectedCallerId;
    return null;
  }, [selectedCallerId]);

  const fetchSixMonth = useCallback(() => {
    if (!sixMonthCallerId) {
      setSixMonthDays([]);
      setSixMonthLoading(false);
      return Promise.resolve();
    }
    setSixMonthLoading(true);
    return api.team.attendanceForCaller(sixMonthCallerId, 6)
      .then((res) => {
        setSixMonthDays(res.data.days);
        if (selectedCallerId) {
          setSixMonthCallerName(selectedCallerName ?? "");
        } else {
          const caller = data?.callers.find((c) => c.caller_id === sixMonthCallerId);
          setSixMonthCallerName(caller?.name ?? "");
        }
      })
      .catch(() => setSixMonthDays([]))
      .finally(() => setSixMonthLoading(false));
  }, [sixMonthCallerId, data, selectedCallerId, selectedCallerName]);

  useEffect(() => {
    if (!sixMonthCallerId) {
      setSixMonthDays([]);
      setSixMonthLoading(false);
      return;
    }
    let cancelled = false;
    setSixMonthLoading(true);
    api.team.attendanceForCaller(sixMonthCallerId, 6)
      .then((res) => {
        if (cancelled) return;
        setSixMonthDays(res.data.days);
        if (selectedCallerId) {
          setSixMonthCallerName(selectedCallerName ?? "");
        } else {
          const caller = data?.callers.find((c) => c.caller_id === sixMonthCallerId);
          setSixMonthCallerName(caller?.name ?? "");
        }
      })
      .catch(() => { if (!cancelled) setSixMonthDays([]); })
      .finally(() => { if (!cancelled) setSixMonthLoading(false); });
    return () => { cancelled = true; };
  }, [sixMonthCallerId, data, selectedCallerId, selectedCallerName]);

  const sixMonths = useMemo(() => buildMiniMonths(sixMonthDays, 6), [sixMonthDays]);

  const handleMark = async (status: "present" | "absent") => {
    if (!canManageTeam || !selectedCallerId || marking) return;
    setMarking(true);
    try {
      await api.team.markAttendance(selectedCallerId, markDate, status);
      await Promise.all([fetchGrid(), fetchSixMonth()]);
    } catch {
      // ignore
    } finally {
      setMarking(false);
    }
  };

  const handleMarkHoliday = async () => {
    if (!canManageTeam || markingHoliday) return;
    setMarkingHoliday(true);
    try {
      const res = await api.team.markHoliday(holidayDate);
      toast.success(`Marked ${holidayDate} as a holiday for all ${res.data.caller_count} telecallers`);
      if (holidayDate > to) {
        setTo(holidayDate);
      } else {
        await Promise.all([fetchGrid(), fetchSixMonth()]);
      }
    } catch {
      toast.error("Failed to mark holiday");
    } finally {
      setMarkingHoliday(false);
    }
  };

  const handleExportCsv = () => {
    if (!data) return;
    setExporting(true);
    try {
      let csv: string;
      let filename: string;

      if (selectedCallerId) {
        const callerGrid = data.grid[selectedCallerId] ?? {};
        const rowsCsv = data.days.map((d) => `${d},${callerGrid[d] ?? "future"}`);
        csv = ["Date,Status", ...rowsCsv].join("\n");
        const safeName = (selectedCallerName ?? "telecaller").replace(/[^a-zA-Z0-9]/g, "_");
        filename = `attendance_${safeName}_${from}_to_${to}.csv`;
      } else {
        const header = `Caller,${data.days.join(",")}`;
        const rowsCsv = data.callers.map((c) => {
          const statuses = data.days.map((d) => data.grid[c.caller_id]?.[d] ?? "future");
          return `${c.name},${statuses.join(",")}`;
        });
        csv = [header, ...rowsCsv].join("\n");
        filename = `team_attendance_${from}_to_${to}.csv`;
      }

      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <h2 className="font-display text-sm font-bold text-primary flex items-center gap-2">
          <CalendarCheck size={16} className="text-primary" /> Team Attendance
        </h2>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1.5 bg-[#f8fafc] p-1.5 rounded-xl border border-[#e2e8f0]">
            <span className="font-label text-[10px] text-[#475569] font-bold uppercase pl-1">Export Attendance:</span>
            <input
              type="date"
              value={from}
              max={to}
              onChange={(e) => setFrom(e.target.value)}
              className="px-1.5 py-0.5 rounded bg-white border border-[#e2e8f0] font-body text-xs text-[#13284A] focus:outline-none"
            />
            <span className="text-[#94a3b8] text-xs">to</span>
            <input
              type="date"
              value={to}
              min={from}
              max={maxHolidayDate}
              onChange={(e) => setTo(e.target.value)}
              className="px-1.5 py-0.5 rounded bg-white border border-[#e2e8f0] font-body text-xs text-[#13284A] focus:outline-none"
            />
            <button
              onClick={handleExportCsv}
              disabled={exporting || !data}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white rounded-lg hover:bg-primary/95 disabled:opacity-50 font-label text-xs font-semibold transition-colors"
            >
              {exporting ? <Loader2 className="animate-spin" size={12} /> : <Download size={12} />} CSV
            </button>
          </div>

          <div className="flex items-center gap-1.5 bg-sky-50 p-1.5 rounded-xl border border-sky-200">
            <span className="font-label text-[10px] text-sky-600 font-bold uppercase pl-1">Mark Holiday:</span>
            <input
              type="date"
              value={holidayDate}
              max={maxHolidayDate}
              onChange={(e) => setHolidayDate(e.target.value)}
              disabled={!canManageTeam}
              className="px-1.5 py-0.5 rounded bg-white border border-sky-200 font-body text-xs text-[#13284A] focus:outline-none"
            />
            <button
              onClick={handleMarkHoliday}
              disabled={markingHoliday || !canManageTeam}
              title={canManageTeam ? "Mark holiday" : "Read-only role: holiday marking is disabled"}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white rounded-lg hover:bg-primary-dark disabled:opacity-50 disabled:blur-[0.5px] font-label text-xs font-semibold transition-colors"
            >
              {markingHoliday ? <Loader2 className="animate-spin" size={12} /> : <Sun size={12} />}
              Whole Team
            </button>
          </div>

          {selectedCallerId && (
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-primary/10 text-primary font-label text-[11px] font-bold">
              Showing: {selectedCallerName ?? "Telecaller"}
            </span>
          )}
        </div>
      </div>

      {selectedCallerId && (
        <div className="flex items-center gap-2 mb-4 flex-wrap bg-surface-mid/10 border border-border-subtle rounded-xl px-3 py-2">
          <span className="font-label text-[10px] text-ink-muted font-bold uppercase">Mark Attendance:</span>
          <input
            type="date"
            value={markDate}
            max={today}
            onChange={(e) => setMarkDate(e.target.value)}
            disabled={!canManageTeam}
            className="px-2 py-1 rounded bg-white border border-[#e2e8f0] font-body text-[11px] text-[#13284A] h-7 focus:outline-none"
          />
          <button
            onClick={() => handleMark("present")}
            disabled={marking || !canManageTeam}
            className="flex items-center gap-1 px-2 py-1 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 font-label text-[11px] font-bold disabled:opacity-50 transition-colors"
          >
            <CheckCircle2 size={12} /> Present
          </button>
          <button
            onClick={() => handleMark("absent")}
            disabled={marking || !canManageTeam}
            className="flex items-center gap-1 px-2 py-1 rounded-lg bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 font-label text-[11px] font-bold disabled:opacity-50 transition-colors"
          >
            <XCircle size={12} /> Absent
          </button>
          {marking && <Loader2 className="animate-spin text-primary" size={12} />}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-5">
        <div className="bg-[#f8fafc] rounded-xl p-3 border border-[#f1f5f9] flex flex-col justify-between shadow-sm">
          <div className="p-1.5 rounded-lg bg-[#f1f5f9] w-fit mb-1 text-[#334155]"><Users size={14} /></div>
          <div>
            <span className="block text-base font-display font-black text-[#13284A] leading-tight">{data?.callers.length ?? 0}</span>
            <span className="text-[#475569] font-label text-[9px] uppercase font-bold tracking-wider mt-0.5 block">Total Team</span>
          </div>
        </div>
        <div className="bg-emerald-50 rounded-xl p-3 border border-emerald-100 flex flex-col justify-between shadow-sm">
          <div className="p-1.5 rounded-lg bg-emerald-100 w-fit mb-1 text-emerald-600"><UserCheck size={14} /></div>
          <div>
            <span className="block text-base font-display font-black text-[#13284A] leading-tight">{data?.summary.present_today ?? 0}</span>
            <span className="text-emerald-700 font-label text-[9px] uppercase font-bold tracking-wider mt-0.5 block">Present Today</span>
          </div>
        </div>
        <div className="bg-rose-50 rounded-xl p-3 border border-rose-100 flex flex-col justify-between shadow-sm">
          <div className="p-1.5 rounded-lg bg-rose-100 w-fit mb-1 text-rose-600"><UserX size={14} /></div>
          <div>
            <span className="block text-base font-display font-black text-[#13284A] leading-tight">{data?.summary.absent_today ?? 0}</span>
            <span className="text-rose-700 font-label text-[9px] uppercase font-bold tracking-wider mt-0.5 block">Absent Today</span>
          </div>
        </div>
        <div className="bg-sky-50 rounded-xl p-3 border border-sky-100 flex flex-col justify-between shadow-sm">
          <div className="p-1.5 rounded-lg bg-sky-100 w-fit mb-1 text-sky-600"><Sun size={14} /></div>
          <div>
            <span className="block text-base font-display font-black text-[#13284A] leading-tight">{holidayCount}</span>
            <span className="text-sky-700 font-label text-[9px] uppercase font-bold tracking-wider mt-0.5 block">Holidays (Range)</span>
          </div>
        </div>
        <div className="bg-primary-light rounded-xl p-3 border border-primary-muted flex flex-col justify-between shadow-sm">
          <div className="p-1.5 rounded-lg bg-primary-light w-fit mb-1 text-primary"><Percent size={14} /></div>
          <div>
            <span className="block text-base font-display font-black text-[#13284A] leading-tight">
              {data ? Math.round(data.summary.attendance_rate_month * 100) : 0}%
            </span>
            <span className="text-primary font-label text-[9px] uppercase font-bold tracking-wider mt-0.5 block">Attendance (Month)</span>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-10"><Loader2 className="animate-spin text-primary" size={20} /></div>
      ) : !data || rows.length === 0 ? (
        <div className="text-center py-8 text-sm text-ink-muted font-body">No telecallers found.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className="text-left font-label text-ink-muted px-2 py-1 sticky left-0 bg-surface">Telecaller</th>
                {data.days.map((d) => (
                  <th key={d} className="px-0.5 py-1 text-center font-label text-ink-muted/60 text-[9px]">
                    {format(new Date(`${d}T00:00:00`), "d")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const isSelected = selectedCallerId === c.caller_id;
                return (
                  <tr
                    key={c.caller_id}
                    className={`border-t border-border-subtle transition-colors ${
                      isSelected ? "bg-primary/5 font-bold animate-pulse" : "hover:bg-[#f8fafc]/40"
                    }`}
                  >
                    <td className={`px-2 py-1.5 font-label font-semibold whitespace-nowrap sticky left-0 transition-colors ${
                      isSelected ? "bg-primary/10 text-primary font-extrabold" : "bg-surface text-ink"
                    }`}>
                      {c.name}
                    </td>
                    {data.days.map((d) => {
                      const status = data.grid[c.caller_id]?.[d] ?? "future";
                      return (
                        <td key={d} className="px-0.5 py-1.5 text-center">
                          <span
                            title={`${c.name} — ${format(new Date(`${d}T00:00:00`), "MMM d")}: ${status}`}
                            className={`inline-block w-3.5 h-3.5 rounded-full border border-black/5 shadow-sm transition-transform hover:scale-110 cursor-pointer ${dotColorClass(status)}`}
                          />
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center gap-4 mt-4 pt-3 border-t border-border-subtle text-[10px] text-ink-muted font-body">
        <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> Present</div>
        <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> Absent</div>
        <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-sky-500 inline-block" /> Holiday</div>
        <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-surface-mid/30 inline-block" /> Future</div>
      </div>

      {/* 6-Month Overview */}
      {selectedCallerId && !loading && data && data.callers.length > 0 && (
        <div className="mt-5 pt-4 border-t border-border-subtle bg-[#f8fafc]/30 rounded-xl p-3">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <h3 className="font-display text-xs font-bold text-primary flex items-center gap-1.5">
              <span className="w-1.5 h-3 bg-primary rounded-full inline-block" />
              6-Month Overview
            </h3>
            {sixMonthCallerName && (
              <p className="text-[10px] text-ink-muted font-body">
                Showing 6-month history for <span className="font-semibold text-primary">{sixMonthCallerName}</span>.
              </p>
            )}
          </div>
          {sixMonthLoading ? (
            <div className="flex justify-center py-6"><Loader2 className="animate-spin text-primary" size={18} /></div>
          ) : sixMonths.length === 0 ? (
            <div className="text-center py-4 text-xs text-ink-muted font-body">No attendance history yet.</div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {sixMonths.map((m) => (
                <div
                  key={m.key}
                  className="rounded-xl border border-border-subtle/80 bg-surface p-1.5 sm:p-2 shadow-sm hover:shadow-md hover:border-primary/20 transition-all duration-150"
                >
                  <div className="text-center text-[10px] font-label font-bold text-primary mb-1.5 tracking-wide bg-[#f8fafc] py-0.5 rounded-md border border-[#f1f5f9]">{m.label}</div>
                  <div className="grid grid-cols-7 gap-[1.5px] mb-1">
                    {WEEKDAY_LABELS.map((d, i) => (
                      <div key={i} className="text-center text-[7px] font-label font-semibold text-ink-muted/50 uppercase">{d}</div>
                    ))}
                  </div>
                  {m.weeks.map((week, wi) => (
                    <div key={wi} className="grid grid-cols-7 gap-[1.5px] mb-[1.5px]">
                      {week.map((cell, di) => {
                        if (!cell) {
                          return <span key={`pad-${wi}-${di}`} className="block w-full aspect-square" />;
                        }

                        let cellClass = "";
                        let textClass = "";

                        if (cell.status === "present") {
                          cellClass = "bg-gradient-to-br from-emerald-400 to-emerald-500 border border-emerald-500/20 shadow-[0_1px_2px_rgba(16,185,129,0.15)] hover:from-emerald-500 hover:to-emerald-600";
                          textClass = "text-white font-bold";
                        } else if (cell.status === "absent") {
                          cellClass = "bg-gradient-to-br from-rose-400 to-rose-500 border border-rose-500/20 shadow-[0_1px_2px_rgba(244,63,94,0.15)] hover:from-rose-500 hover:to-rose-600";
                          textClass = "text-white font-bold";
                        } else if (cell.status === "holiday") {
                          cellClass = "bg-gradient-to-br from-sky-400 to-sky-500 border border-sky-500/20 shadow-[0_1px_2px_rgba(14,165,233,0.15)] hover:from-sky-500 hover:to-sky-600";
                          textClass = "text-white font-bold";
                        } else {
                          cellClass = "bg-[#f8fafc] border border-[#f1f5f9] hover:bg-[#f1f5f9]";
                          textClass = "text-[#94a3b8]/80 font-medium";
                        }

                        return (
                          <span
                            key={cell.date}
                            title={`${format(parseISO(cell.date), "MMM d, yyyy")}: ${cell.status}`}
                            className={`relative flex items-center justify-center w-full aspect-square rounded-[4px] transition-all duration-150 cursor-default select-none ${cellClass}`}
                          >
                            <span className={`text-[7px] sm:text-[8px] leading-none ${textClass}`}>
                              {format(parseISO(cell.date), "d")}
                            </span>
                          </span>
                        );
                      })}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

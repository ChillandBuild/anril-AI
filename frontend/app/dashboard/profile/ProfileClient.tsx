"use client";
import { useState } from "react";
import Link from "next/link";
import {
  Phone,
  TrendingUp,
  Clock,
  Target,
  RefreshCw,
  Upload,
  BarChart2,
  Settings,
  Users,
  Crown,
} from "lucide-react";
import { api } from "@/lib/api";
import type { CallerStats, CallLog } from "@/lib/api";
import { toast } from "sonner";
import { AiraLoader } from "@/components/AiraLoader";
import { useMyStats, useMyPerformance, useCallerLogs } from "@/hooks/useApi";
import { useAuthRole } from "../contexts/AuthRoleContext";
import AttendanceMini from "../team/AttendanceMini";
import { TONE_DOT, callResultKey, callResultLabel, callResultTone } from "@/lib/call-wrapup";

export interface ProfileClientProps {
  fallbackStats: CallerStats | null;
  fallbackPerformance: { target: number; achieved: number } | null;
  fallbackLogs: CallLog[] | null;
  userEmail?: string | null;
  userName?: string | null;
  userCreatedAt?: string | null;
}

export function ProfileClient({
  fallbackStats,
  fallbackPerformance,
  fallbackLogs,
  userEmail,
  userName,
  userCreatedAt,
}: ProfileClientProps) {
  const { role } = useAuthRole();
  const isAdmin = role === "owner";

  const { data: stats, mutate: mutateStats } = useMyStats(!isAdmin, fallbackStats ?? undefined);
  const { data: performanceData, isLoading: performanceLoading } = useMyPerformance(!isAdmin, fallbackPerformance ?? undefined);
  const { data: logsData, isLoading: logsLoading } = useCallerLogs(stats?.caller_id ?? null, !isAdmin, fallbackLogs ?? undefined);

  const [togglingStatus, setTogglingStatus] = useState(false);

  // Until the first answer arrives, show "—" / a loader instead of the made-up 0 / 50 and an empty log.
  const performance = performanceData ?? { target: 50, achieved: 0 };
  const logs = logsData ?? [];

  const toggleMyStatus = async () => {
    if (!stats) return;
    const currentStatus = (stats.status as "active" | "break") || "active";
    const next = currentStatus === "active" ? "break" : "active";
    setTogglingStatus(true);
    try {
      await api.callers.setMyStatus(next);
      mutateStats({ ...stats, status: next });
      toast.success(next === "active" ? "You are now active" : "Break mode enabled");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setTogglingStatus(false);
    }
  };

  function formatDuration(seconds: number | null): string {
    if (!seconds) return "—";
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}m ${s}s`;
  }

  function timeAgo(dateStr: string): string {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  }


  if (isAdmin) {
    const adminName = userName || userEmail?.split("@")[0] || "Admin";
    const initials = adminName.split(" ").map((n: string) => n[0]).join("").toUpperCase().slice(0, 2);
    const memberSince = userCreatedAt ? new Date(userCreatedAt).toLocaleDateString("en-IN", { month: "long", year: "numeric" }) : null;

    const now = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
    const hour = now.getHours();
    const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

    const quickLinks = [
      { href: "/dashboard", icon: BarChart2, label: "Dashboard", desc: "Team overview & metrics", color: "from-primary to-primary-500" },
      { href: "/dashboard/telecalling/upload", icon: Upload, label: "Upload Contacts", desc: "Import CSV & manage scripts", color: "from-emerald-500 to-teal-500" },
      { href: "/dashboard/telecalling", icon: Phone, label: "Telecalling", desc: "Dialer & lead queue", color: "from-amber-500 to-orange-500" },
      { href: "/dashboard/team", icon: Users, label: "Team", desc: "Manage telecallers", color: "from-blue-500 to-cyan-500" },
      { href: "/dashboard/settings", icon: Settings, label: "Settings", desc: "Config & channels", color: "from-[#475569] to-[#475569]" },
      { href: "/dashboard/analytics", icon: TrendingUp, label: "Analytics", desc: "Performance reports", color: "from-rose-500 to-pink-500" },
    ];

    return (
      <div>
        <div className="mb-8">
          <h1 className="font-display text-3xl font-bold text-primary">My performance</h1>
          <p className="font-body text-on-surface-muted mt-1">{greeting}, {adminName.split(" ")[0]}</p>
        </div>

        {/* Admin Identity Card */}
        <div className="bg-gradient-to-br from-[#0A1528] via-[#13284A] to-[#0A1528] rounded-[2rem] p-8 shadow-xl mb-8 relative overflow-hidden">
          <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-bl from-primary/10 to-transparent rounded-full -translate-y-1/2 translate-x-1/3" />
          <div className="absolute bottom-0 left-0 w-48 h-48 bg-gradient-to-tr from-amber-500/10 to-transparent rounded-full translate-y-1/2 -translate-x-1/4" />

          <div className="relative flex items-center gap-6">
            <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-[var(--primary-950)] to-primary flex items-center justify-center shadow-lg shadow-primary/25">
              <span className="font-display text-3xl font-bold text-white">{initials}</span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 flex-wrap">
                <h2 className="font-display text-2xl font-bold text-white">{adminName}</h2>
                <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/15 border border-amber-500/30">
                  <Crown size={12} className="text-amber-400" />
                  <span className="font-label text-xs font-bold text-amber-300 uppercase tracking-wider">Admin</span>
                </span>
              </div>
              {userEmail && (
                <p className="font-body text-sm text-[#94a3b8] mt-1">{userEmail}</p>
              )}
              <div className="flex items-center gap-4 mt-3">
                {memberSince && (
                  <span className="font-label text-xs text-[#475569]">Member since {memberSince}</span>
                )}
                <span className="flex items-center gap-1.5 font-label text-xs text-emerald-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  All systems online
                </span>
              </div>
            </div>
          </div>

          {/* Signature quote */}
          <div className="relative mt-6 pt-6 border-t border-[#1e293b]/50">
            <p className="font-body text-sm text-[#94a3b8] italic leading-relaxed">
              &quot;The best leaders don&apos;t create followers — they create more leaders.&quot;
            </p>
            <p className="font-label text-[10px] text-[#334155] mt-1 uppercase tracking-widest">Your role: Empower your team</p>
          </div>
        </div>

        {/* Quick Navigation */}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {quickLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="group bg-surface rounded-2xl p-5 shadow-card ring-1 ring-[#c4c7c7]/15 hover:shadow-lg hover:ring-primary/20 transition-all duration-200"
            >
              <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${link.color} flex items-center justify-center mb-3 shadow-sm group-hover:scale-110 transition-transform`}>
                <link.icon size={18} className="text-white" />
              </div>
              <h3 className="font-display text-sm font-bold text-on-surface">{link.label}</h3>
              <p className="font-body text-xs text-on-surface-muted mt-0.5">{link.desc}</p>
            </Link>
          ))}
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <RefreshCw size={24} className="animate-spin text-primary" />
      </div>
    );
  }

  // SIM clients get no evaluation at all: /callers/my-stats already omits
  // avg_score_month for them, so its absence is the tenant's own signal --
  // no extra request, and no dependency on a permission a caller may lack.
  const isSim = stats.avg_score_month === undefined;

  return (
    <div>
      {/* Profile Card + Stats */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        {/* Profile Card */}
        <div className="bg-surface rounded-card p-6 shadow-card ring-1 ring-[#c4c7c7]/15">
          <div className="flex items-center gap-4 mb-4">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary/20 to-secondary/20 flex items-center justify-center">
              <span className="font-display text-2xl font-bold text-primary">
                {stats.name
                  ?.split(" ")
                  .map((n: string) => n[0])
                  .join("")
                  .toUpperCase() || "?"}
              </span>
            </div>
            <div>
              <h2 className="font-display text-xl font-bold text-on-surface">
                {stats.name}
              </h2>
              <p className="font-label text-sm text-on-surface-muted">
                {stats.phone || "—"}
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                <button
                  onClick={toggleMyStatus}
                  disabled={togglingStatus}
                  className={`px-3 py-1 rounded-full font-label text-xs font-semibold transition-all flex items-center gap-1.5 shadow-sm border ${
                    stats.status === "active"
                      ? "bg-emerald-50 border-emerald-200 text-emerald-700 hover:bg-emerald-100"
                      : "bg-amber-50 border-amber-200 text-amber-700 hover:bg-amber-100"
                  } disabled:opacity-60`}
                  title="Click to toggle status"
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${stats.status === "active" ? "bg-emerald-500 animate-pulse" : "bg-amber-500"}`} />
                  {stats.status === "active" ? "🟢 Active" : "🟡 On Break"}
                </button>
              </div>
            </div>
          </div>

          {/* This month's average call score -- SIM clients get no evaluation at all */}
          {!isSim && (
          <div className="mt-4 pt-4 border-t border-surface-mid">
            <p className="font-label text-xs text-on-surface-muted uppercase tracking-wider mb-1">
              Avg Call Score · This Month
            </p>
            <div className="flex items-baseline gap-2">
              <span className="font-display text-4xl font-bold text-primary">
                {stats.avg_score_month != null ? stats.avg_score_month.toFixed(1) : "\u2014"}
              </span>
              <span className="font-label text-sm text-on-surface-muted">
                / 100
              </span>
            </div>
            <p className="font-label text-xs text-on-surface-muted mt-1">
              {stats.scored_calls_month} scored of {stats.total_calls_month} calls
            </p>
          </div>
          )}
        </div>

        {/* Stats Grid */}
        <div className="lg:col-span-2 grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15 flex flex-col">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 rounded-xl bg-primary/10">
                <Phone size={16} className="text-primary" />
              </div>
            </div>
            <span className="font-display text-3xl font-bold text-on-surface">
              {stats.calls_today}
            </span>
            <span className="font-label text-xs text-on-surface-muted mt-1">
              Calls Today
            </span>
          </div>

          <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15 flex flex-col">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 rounded-xl bg-green-100">
                <Target size={16} className="text-green-600" />
              </div>
            </div>
            <span className="font-display text-3xl font-bold text-on-surface">
              {(stats.conversion_rate_week * 100).toFixed(0)}%
            </span>
            <span className="font-label text-xs text-on-surface-muted mt-1">
              Conv. Rate (Week)
            </span>
          </div>

          <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15 flex flex-col">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 rounded-xl bg-blue-100">
                <Clock size={16} className="text-blue-600" />
              </div>
            </div>
            <span className="font-display text-3xl font-bold text-on-surface">
              {stats.avg_duration_seconds
                ? formatDuration(stats.avg_duration_seconds)
                : "—"}
            </span>
            <span className="font-label text-xs text-on-surface-muted mt-1">
              Avg Duration
            </span>
          </div>

          <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15 flex flex-col">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 rounded-xl bg-red-100">
                <TrendingUp size={16} className="text-red-500" />
              </div>
            </div>
            <span className="font-display text-3xl font-bold text-on-surface">
              {stats.pending_hot_leads}
            </span>
            <span className="font-label text-xs text-on-surface-muted mt-1">
              Pending Hot Leads
            </span>
          </div>

          <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15 flex flex-col col-span-2">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 rounded-xl bg-secondary/10">
                <Phone size={16} className="text-secondary" />
              </div>
            </div>
            <span className="font-display text-3xl font-bold text-on-surface">
              {stats.calls_this_week}
            </span>
            <span className="font-label text-xs text-on-surface-muted mt-1">
              Calls This Week
            </span>
          </div>

          <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15 flex col-span-2 justify-between items-center">
            <div className="flex-1 flex flex-col justify-between h-full min-h-[90px]">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <div className="p-1.5 rounded-lg bg-primary-light">
                    <Target size={14} className="text-primary" />
                  </div>
                  <span className="font-label text-xs text-on-surface-muted font-bold tracking-wider uppercase">
                    Daily Target
                  </span>
                </div>
                <p className="font-display text-lg font-extrabold text-on-surface mt-1">
                  {performanceLoading ? "—" : `${performance.achieved} / ${performance.target} Calls`}
                </p>
              </div>
              
              <div className="flex items-center gap-2 mt-2 pt-2 border-t border-surface-low">
                {performanceLoading ? (
                  <span className="text-[10px] text-on-surface-muted font-semibold px-2.5 py-0.5">—</span>
                ) : performance.achieved >= performance.target ? (
                  <span className="text-[10px] text-green-600 font-bold bg-emerald-50 border border-emerald-100 px-2.5 py-0.5 rounded-full animate-pulse">
                    🎉 Target Met!
                  </span>
                ) : (
                  <span className="text-[10px] text-amber-600 font-semibold bg-amber-50 border border-amber-100 px-2.5 py-0.5 rounded-full">
                    {performance.target - performance.achieved} calls to go 🎯
                  </span>
                )}
              </div>
            </div>

            {/* Circular SVG Progress Ring */}
            <div className="relative flex items-center justify-center shrink-0 ml-4">
              <svg height="96" width="96" className="rotate-[-90deg]">
                <circle
                  stroke="rgba(226, 232, 240, 0.5)"
                  fill="transparent"
                  strokeWidth="8"
                  r="38"
                  cx="48"
                  cy="48"
                />
                <circle
                  stroke="url(#targetRingGradient)"
                  fill="transparent"
                  strokeWidth="8"
                  strokeDasharray="238.76"
                  strokeDashoffset={238.76 - (Math.min(100, !performanceLoading && performance.target > 0 ? (performance.achieved / performance.target) * 100 : 0) / 100) * 238.76}
                  strokeLinecap="round"
                  r="38"
                  cx="48"
                  cy="48"
                  className="transition-all duration-500"
                />
                <defs>
                  <linearGradient id="targetRingGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#6366f1" />
                    <stop offset="100%" stopColor="var(--primary-500)" />
                  </linearGradient>
                </defs>
              </svg>
              <div className="absolute flex flex-col items-center justify-center">
                <span className="font-display text-sm font-black text-on-surface">
                  {performanceLoading ? "—" : performance.target > 0 ? Math.round((performance.achieved / performance.target) * 100) : 0}%
                </span>
                <span className="font-label text-[8px] text-on-surface-muted uppercase tracking-wider font-bold">
                  done
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Attendance History */}
      <div className="mb-8">
        <AttendanceMini callerId={stats.caller_id} readOnly={true} />
      </div>

      {/* Call History */}
      <div className="bg-surface rounded-card p-6 shadow-card ring-1 ring-[#c4c7c7]/15">
        <h2 className="font-display text-base font-bold text-primary mb-4 flex items-center gap-2">
          <Phone size={16} className="text-secondary" /> Recent Call History
        </h2>

        {logsLoading ? (
          <AiraLoader inline className="min-h-[200px]" />
        ) : logs.length === 0 ? (
          <p className="font-body text-sm text-on-surface-muted py-8 text-center">
            No calls yet. Start calling your assigned leads!
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-surface-mid">
                  <th className="pb-3 font-label text-xs text-on-surface-muted uppercase tracking-wider">
                    Lead
                  </th>
                  <th className="pb-3 font-label text-xs text-on-surface-muted uppercase tracking-wider">
                    Phone
                  </th>
                  <th className="pb-3 font-label text-xs text-on-surface-muted uppercase tracking-wider">
                    Duration
                  </th>
                  <th className="pb-3 font-label text-xs text-on-surface-muted uppercase tracking-wider">
                    Outcome
                  </th>
                  <th className="pb-3 font-label text-xs text-on-surface-muted uppercase tracking-wider text-right">
                    When
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-low">
                {logs.map((log: CallLog) => (
                  <tr key={log.id} className="hover:bg-surface-low transition-colors">
                    <td className="py-3 pr-4">
                      <span className="font-body text-sm font-semibold text-on-surface">
                        {log.leads?.name || "Unknown"}
                      </span>
                    </td>
                    <td className="py-3 pr-4">
                      <span className="font-label text-xs text-on-surface-muted">
                        {log.leads?.phone || "—"}
                      </span>
                    </td>
                    <td className="py-3 pr-4">
                      <span className="font-label text-xs text-on-surface">
                        {formatDuration(log.duration_seconds)}
                      </span>
                    </td>
                    <td className="py-3 pr-4">
                      <span className="flex items-center gap-1.5 font-label text-xs">
                        <span className={`h-2 w-2 rounded-full ${TONE_DOT[callResultTone(callResultKey(log))]}`} />
                        {callResultLabel(callResultKey(log)) ?? "—"}
                      </span>
                    </td>
                    <td className="py-3 text-right">
                      <span className="font-label text-xs text-on-surface-muted">
                        {timeAgo(log.created_at)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

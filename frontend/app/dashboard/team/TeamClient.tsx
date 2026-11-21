"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AlertCircle, Loader2 } from "lucide-react";
import useSWR from "swr";
import { api, Caller, CallTeamsResponse, TeamMember } from "@/lib/api";
import { cn } from "@/lib/utils";
import { showsEvaluation } from "@/lib/evaluation-visibility";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { useCallers, useTeamList } from "@/hooks/useApi";

import AssignmentLog from "../telecalling/components/assignment-log";
import PerformanceView from "../telecalling/components/performance-view";
import WinnerBanner from "./WinnerBanner";
import TeamsPanel from "./TeamsPanel";

interface TeamClientProps {
  fallbackTeam: { data: TeamMember[]; calling_provider?: "telecmi" | "sim_basic" } | null;
  fallbackCallers: Caller[] | null;
}

export function TeamClient({ fallbackTeam, fallbackCallers }: TeamClientProps) {
  const { role, roleSlug, permissions, loading: roleLoading } = useAuthRole();
  const isLeader = roleSlug === "team_leader";
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  // The assignment log is owner-level; a Team leader only gets the performance view.
  const tab = (rawTab === "log" && !isLeader ? "log" : "performance") as "performance" | "log";
  const canViewTeam = role === "owner" || permissions.includes("team.view") || fallbackTeam !== null;

  const { data: callersData, mutate: reloadCallers } = useCallers(
    canViewTeam,
    fallbackCallers ?? undefined,
  );
  // team/list is gated on the same team.view permission as this page, so it's
  // a safe source for calling_provider (unlike settings, which callers with
  // only team.view may not be able to read).
  const { data: teamData } = useTeamList(canViewTeam, fallbackTeam ?? undefined);

  // Teams: managers get the editor; a Team leader gets only the team they lead (and no editor).
  const { data: teamsData, mutate: reloadTeams } = useSWR<CallTeamsResponse>(
    canViewTeam && !roleLoading ? "call-teams" : null,
    () => api.callTeams.list(),
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  const canEditTeams = !!teamsData?.can_manage && !isLeader;
  const [teamFilter, setTeamFilter] = useState<string | null>(null);

  const callers = callersData?.data ?? [];
  const adminCaller = callersData?.admin_caller ?? null;
  // SIM clients get no evaluation at all: no winner banner, no /winners request.
  // Unknown (still loading) resolves to false, so it can't flash in for SIM.
  const showWinners = showsEvaluation(teamData?.calling_provider);

  const [showTelecallerHint, setShowTelecallerHint] = useState(true);
  const [dismissingHint, setDismissingHint] = useState(false);

  useEffect(() => {
    const dismissTimer = setTimeout(() => setDismissingHint(true), 10000);
    return () => clearTimeout(dismissTimer);
  }, []);

  useEffect(() => {
    if (!dismissingHint) return;
    const removeTimer = setTimeout(() => setShowTelecallerHint(false), 300);
    return () => clearTimeout(removeTimer);
  }, [dismissingHint]);

  if (roleLoading && !fallbackTeam) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <Loader2 size={24} className="animate-spin text-primary" />
      </div>
    );
  }

  if (!canViewTeam) {
    return (
      <div className="py-20 text-center">
        <p className="font-body text-sm text-ink-muted">This section is only available for users with team access.</p>
      </div>
    );
  }

  return (
    <div className="min-w-0">
      {showTelecallerHint && (
        <div className="mb-5 flex min-w-0 justify-end">
          <div
            className={cn(
              "flex items-center gap-2 rounded-2xl border border-amber-100 bg-amber-50 px-4 py-2 font-body text-xs font-semibold text-amber-800 transition-opacity duration-300",
              dismissingHint ? "opacity-0" : "opacity-100"
            )}
          >
            <AlertCircle size={14} className="shrink-0" />
            Add telecallers from Roles by assigning the Telecaller role.
          </div>
        </div>
      )}

      {canEditTeams && teamsData && (
        <TeamsPanel
          data={teamsData}
          onChanged={async () => {
            await Promise.all([reloadTeams(), reloadCallers()]);
          }}
        />
      )}

      {/* Team filter: only for people who see every team (a Team leader already sees just theirs). */}
      {!isLeader && teamsData && teamsData.data.length > 0 && tab === "performance" && (
        <div className="mb-5 flex flex-wrap items-center gap-2" role="group" aria-label="Filter by team">
          <span className="font-body text-xs font-semibold text-ink-muted">Team</span>
          {[{ id: null as string | null, name: "All" }, ...teamsData.data].map((t) => (
            <button
              key={t.id ?? "all"}
              type="button"
              onClick={() => setTeamFilter(t.id)}
              aria-pressed={teamFilter === t.id}
              className={cn(
                "rounded-full border px-3 py-1 font-body text-xs font-semibold transition-colors",
                teamFilter === t.id ? "border-primary bg-primary text-white" : "border-border bg-white text-ink-muted hover:bg-surface-soft",
              )}
            >
              {t.name}
            </button>
          ))}
        </div>
      )}

      {showWinners && !isLeader && <WinnerBanner />}

      {tab === "log" ? (
        <AssignmentLog callers={callers} />
      ) : (
        <PerformanceView callers={callers} adminCaller={adminCaller} callingProvider={teamData?.calling_provider} teamFilter={teamFilter} />
      )}
    </div>
  );
}

"use client";

import type { TelecallingAnalyticsExtended } from "@/lib/api";
import { KpiCard } from "@/components/kpi-card";
import { showsEvaluation } from "@/lib/evaluation-visibility";
import {
  formatTalk, formatPct, formatMinutes,
  computeDelta, deltaColor, deltaLabel, type Delta,
} from "./performance-format";

type PerCaller = TelecallingAnalyticsExtended["per_caller"][number];

interface PerformanceKpisProps {
  stats: TelecallingAnalyticsExtended | null;
  callerStats: PerCaller | null | undefined;
  selectedCallerId: string | null;
  loading: boolean;
  // Deltas compare against real yesterday / trailing-7d, so only show them when
  // the KPI values themselves cover "today" (no custom from/to range applied).
  showDeltas: boolean;
  // SIM clients get no evaluation at all: no Avg Score tile. undefined = not
  // loaded yet, which hides the tile same as SIM (no flash before confirmed).
  callingProvider?: "telecmi" | "sim_basic";
}

interface TileDeltas {
  yesterday: Delta | null;
  avg7d: Delta | null;
}

function DeltaRow({ deltas, asPct, unit }: { deltas: TileDeltas; asPct?: boolean; unit?: string }) {
  if (!deltas.yesterday && !deltas.avg7d) return null;
  return (
    <div className="flex flex-col gap-0.5 text-[10px] font-bold">
      {deltas.yesterday && (
        <span className={deltaColor(deltas.yesterday)}>
          {deltaLabel(deltas.yesterday, { asPct, unit })} <span className="text-[#94a3b8] font-medium">vs yesterday</span>
        </span>
      )}
      {deltas.avg7d && (
        <span className={deltaColor(deltas.avg7d)}>
          {deltaLabel(deltas.avg7d, { asPct, unit })} <span className="text-[#94a3b8] font-medium">vs 7-day avg</span>
        </span>
      )}
    </div>
  );
}

interface TileProps {
  value: string;
  label: string;
  tooltip: string;
  loading: boolean;
  deltas?: TileDeltas;
  deltaOpts?: { asPct?: boolean; unit?: string };
  edge?: string;
}

function Tile({ value, label, tooltip, loading, deltas, deltaOpts, edge = "bg-primary" }: TileProps) {
  const showDeltas = !loading && deltas && (deltas.yesterday || deltas.avg7d);
  return (
    <KpiCard stacked label={label} value={value} loading={loading} title={tooltip} edge={edge}>
      {showDeltas ? <DeltaRow deltas={deltas} asPct={deltaOpts?.asPct} unit={deltaOpts?.unit} /> : null}
    </KpiCard>
  );
}

export default function PerformanceKpis({ stats, callerStats, selectedCallerId, loading, showDeltas, callingProvider }: PerformanceKpisProps) {
  const isTeam = !selectedCallerId;
  const evaluationVisible = showsEvaluation(callingProvider);
  // Deltas only at team level (comparison is team-wide) AND only on the today view.
  const comp = isTeam && showDeltas ? stats?.comparison : undefined;

  const callsVal = selectedCallerId ? (callerStats?.calls_today ?? 0) : (stats?.calls_today ?? 0);
  const connectRate = selectedCallerId ? (callerStats?.connect_rate ?? 0) : (stats?.connect_rate ?? 0);
  const avgTalk = selectedCallerId ? (callerStats?.avg_talk_seconds ?? 0) : (stats?.avg_talk_seconds ?? 0);
  const idle = selectedCallerId ? (callerStats?.idle_minutes_today ?? 0) : (stats?.idle_minutes_today ?? 0);
  const conversions = stats?.conversions_today ?? stats?.outcome_breakdown?.converted ?? 0;
  const convRate = selectedCallerId
    ? (callerStats?.conversion_rate ?? 0)
    : (callsVal > 0 ? conversions / callsVal : 0);
  const quality = callerStats?.overall_score;
  const speedToLead = callerStats?.speed_to_lead_min;
  const talkMinutes = callerStats?.talk_minutes_today ?? 0;

  const compConvRate = (m: { conversions: number; calls: number }) => (m.calls > 0 ? (m.conversions / m.calls) * 100 : 0);

  // Deltas only meaningful at team level (comparison is team-wide, no per-caller history).
  const callsDeltas: TileDeltas = {
    yesterday: comp ? computeDelta(callsVal, comp.yesterday.calls) : null,
    avg7d: comp ? computeDelta(callsVal, comp.avg_7d.calls) : null,
  };
  const connectDeltas: TileDeltas = {
    yesterday: comp ? computeDelta(connectRate * 100, comp.yesterday.connect_rate * 100) : null,
    avg7d: comp ? computeDelta(connectRate * 100, comp.avg_7d.connect_rate * 100) : null,
  };
  const talkDeltas: TileDeltas = {
    yesterday: comp ? computeDelta(avgTalk, comp.yesterday.avg_talk_seconds) : null,
    avg7d: comp ? computeDelta(avgTalk, comp.avg_7d.avg_talk_seconds) : null,
  };
  const idleDeltas: TileDeltas = {
    yesterday: comp ? computeDelta(idle, comp.yesterday.idle_minutes, true) : null,
    avg7d: comp ? computeDelta(idle, comp.avg_7d.idle_minutes, true) : null,
  };
  const convDeltas: TileDeltas = {
    yesterday: comp ? computeDelta(conversions, comp.yesterday.conversions) : null,
    avg7d: comp ? computeDelta(conversions, comp.avg_7d.conversions) : null,
  };
  const convRateDeltas: TileDeltas = {
    yesterday: comp ? computeDelta(convRate * 100, compConvRate(comp.yesterday)) : null,
    avg7d: comp ? computeDelta(convRate * 100, compConvRate(comp.avg_7d)) : null,
  };

  const teamOnly = isTeam ? undefined : { yesterday: null, avg7d: null };
  // Per-caller view drops to 8 tiles instead of 9 when the Avg Score tile is
  // hidden -- 4 columns (2x4) keeps the last row full instead of leaving a
  // gap. Team view is always 6 tiles regardless of provider, so unaffected.
  const gridClass = !isTeam && !evaluationVisible
    ? "grid grid-cols-2 md:grid-cols-4 gap-4"
    : "grid grid-cols-2 md:grid-cols-3 gap-4";

  return (
    <div className={gridClass}>
      <Tile
        loading={loading}
        value={formatPct(connectRate)}
        label="Connection Rate"
        tooltip="Connect Rate = answered ÷ dialed"
        deltas={isTeam ? connectDeltas : teamOnly}
        deltaOpts={{ unit: "pts" }}
        edge="bg-blue-600"
      />
      <Tile
        loading={loading}
        value={formatTalk(avgTalk)}
        label="Avg Talk Time"
        tooltip="Avg Talk Time = total talk seconds ÷ calls"
        deltas={isTeam ? talkDeltas : teamOnly}
        deltaOpts={{ asPct: true }}
        edge="bg-sky-500"
      />
      <Tile
        loading={loading}
        value={formatMinutes(idle)}
        label={selectedCallerId ? "Idle Minutes" : "Total Team Idle"}
        tooltip="Idle = active (logged-in) minutes minus talk minutes. Lower is better."
        deltas={isTeam ? idleDeltas : teamOnly}
        deltaOpts={{ unit: "min" }}
        edge="bg-amber-400"
      />
      <Tile
        loading={loading}
        value={String(conversions)}
        label="Conversions"
        tooltip="Conversions = calls with a 'converted' outcome today"
        deltas={isTeam ? convDeltas : teamOnly}
        edge="bg-emerald-500"
      />
      <Tile
        loading={loading}
        value={formatPct(convRate)}
        label="Conversion Rate"
        tooltip="Conversion Rate = converted ÷ calls"
        deltas={isTeam ? convRateDeltas : teamOnly}
        deltaOpts={{ unit: "pts" }}
        edge="bg-teal-500"
      />
      {!isTeam && evaluationVisible && (
        <Tile
          loading={loading}
          value={quality ? `${quality.toFixed(1)}/100` : "—"}
          label="Avg Score"
          tooltip="Average of this period's fully scored calls, out of 100. Each real sales conversation is marked on 10 checks. Unanswered, under-30-second and early-exit calls count toward calls, not the score."
          edge="bg-purple-500"
        />
      )}
      {!isTeam && (
        <Tile
          loading={loading}
          value={speedToLead != null ? `${speedToLead.toFixed(1)} min` : "—"}
          label="Speed to Lead"
          tooltip="Median minutes before calling back a new lead. Lower is better."
          edge="bg-yellow-400"
        />
      )}
      {!isTeam && (
        <Tile
          loading={loading}
          value={formatMinutes(talkMinutes)}
          label="Total Talk Time"
          tooltip="Total minutes spent talking today"
          edge="bg-cyan-500"
        />
      )}
      <Tile
        loading={loading}
        value={String(callsVal)}
        label="Total Calls Today"
        tooltip="Total dialed calls in the selected window"
        deltas={isTeam ? callsDeltas : teamOnly}
        edge="bg-rose-500"
      />
    </div>
  );
}

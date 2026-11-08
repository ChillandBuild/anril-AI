"use client";

import { useEffect, useState, useMemo } from "react";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
  ResponsiveContainer, CartesianGrid,
} from "recharts";
import {
  RefreshCw, Download
} from "lucide-react";
import { RangeValue } from "@/components/analytics/RangePicker";
import { FiltersToggleButton } from "@/components/analytics/FiltersToggleButton";
import {
  api, CompareParams, ComparePayload, ComparePeriod, ComparePoint, CompareMetric, CompareMovement,
} from "@/lib/api";
import { canLoadComparison, ComparisonSelection, isCompleteSelection } from "@/components/analytics/periodSelection";
import { buildFunnel, buildOverviewCards, buildTrend, FunnelStep, PerformanceCard } from "./overviewPresentation";
import { AiraLoader } from "@/components/AiraLoader";
import { KpiCard, edgeFromTone } from "@/components/kpi-card";

const CURRENT_COLOR = "var(--primary-800)";
const PREVIOUS_COLOR = "#94a3b8";

const SERIES_OPTIONS: { id: string; label: string }[] = [
  { id: "leads_inbound", label: "Inbound Leads" },
  { id: "leads_outbound", label: "Outbound Leads" },
  { id: "messages_in", label: "Messages Received" },
  { id: "messages_out", label: "Messages Sent" },
];

const TABLE_ROWS: { key: string; label: string }[] = [
  { key: "new_leads", label: "New leads" },
  { key: "inbound_leads", label: "— came to us" },
  { key: "outbound_leads", label: "— we reached out" },
  { key: "hot", label: "Hot leads" },
  { key: "warm", label: "Warm leads" },
  { key: "cold", label: "Cold leads" },
  { key: "disqualified", label: "Not Interested" },
  { key: "avg_score", label: "Average score" },
  { key: "messages_in", label: "Messages received" },
  { key: "messages_out", label: "Messages sent" },
  { key: "ai_replies", label: "— sent by AI" },
  { key: "human_replies", label: "— sent by a human" },
  { key: "converted", label: "Conversions" },
  { key: "engagement_rate", label: "Engagement rate (% of leads replied to)" },
];

// Past a few hundred percent a percentage stops communicating: "+13700%" is
// correct and unreadable. Show a multiple instead, matching the summary text.
const BIG_CHANGE_PCT = 300;

function formatDelta(pct: number): string {
  if (Math.abs(pct) < BIG_CHANGE_PCT) return `${pct >= 0 ? "+" : ""}${pct}%`;
  // pct = (cur - prev) / prev * 100, so the multiple is pct/100 + 1.
  return `${Math.round(Math.abs(pct) / 100 + 1)}×`;
}

type DeltaSense = "higher" | "lower" | "neutral";

function DeltaBadge({
  pct,
  sense = "higher",
}: {
  pct: number | null;
  sense?: DeltaSense;
}) {
  if (pct === null) {
    return <span className="font-label text-xs text-on-surface-muted">—</span>;
  }
  const up = pct >= 0;
  const tone =
    sense === "neutral"
      ? "text-on-surface-muted"
      : (sense === "lower" ? !up : up)
        ? "text-emerald-600"
        : "text-red-600";
  return (
    <span className={`font-label text-xs font-bold ${tone}`}>
      {up ? "▲" : "▼"} {formatDelta(pct)}
    </span>
  );
}

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return "₹" + Math.round(n).toLocaleString("en-IN");
}

function seconds(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 60) return `${Math.round(n)}s`;
  if (n < 3600) return `${Math.round(n / 60)}m`;
  return `${(n / 3600).toFixed(1)}h`;
}

function StatCard({
  label,
  value,
  sub,
  delta,
  sense,
  tone = "border-t-primary-500",
}: {
  label: string;
  value: string;
  sub?: string;
  delta?: number | null;
  sense?: DeltaSense;
  tone?: string;
}) {
  return (
    <KpiCard stacked label={label} value={value} edge={edgeFromTone(tone)}>
      {(delta !== undefined || sub) && (
        <div className="flex items-center gap-2">
          {delta !== undefined && <DeltaBadge pct={delta ?? null} sense={sense} />}
          {sub && <span className="font-label text-xs text-on-surface-muted">{sub}</span>}
        </div>
      )}
    </KpiCard>
  );
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-card bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15 sm:p-6">
      <h2 className="mb-4 font-display text-base font-bold text-primary sm:mb-5">{title}</h2>
      {children}
    </div>
  );
}

function FunnelSteps({ steps }: { steps: FunnelStep[] }) {
  const firstCount = steps[0]?.count ?? 0;
  return (
    <div className="space-y-3">
      {steps.map((step, i) => {
        const prevCount = i === 0 ? step.count : steps[i - 1].count;
        const retentionPct =
          i === 0 || prevCount === 0
            ? null
            : Math.round((step.count / prevCount) * 100);
        const dropPct = retentionPct !== null ? 100 - retentionPct : null;
        const widthPct = firstCount === 0
          ? 0
          : Math.min(Math.round((step.count / firstCount) * 100), 100);

        return (
          <div key={step.label} className="flex items-center gap-3">
            <span className="font-label text-xs text-on-surface-muted w-20 text-right shrink-0">
              {step.label}
            </span>
            <div className="flex-1 bg-surface-mid rounded-full h-6 overflow-hidden">
              <div
                className="h-6 rounded-full bg-primary transition-all"
                style={{ width: `${widthPct}%` }}
              />
            </div>
            <span className="font-display text-sm font-bold text-on-surface w-10 shrink-0">
              {step.count}
            </span>
            {dropPct !== null && (
              <span className="font-label text-xs text-on-surface-muted w-14 shrink-0">
                {dropPct}% drop
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function PerformanceKpi({ card }: { card: PerformanceCard }) {
  const improved = card.delta != null
    ? card.lowerIsBetter ? card.delta < 0 : card.delta > 0
    : null;
  const deltaLabel = card.delta == null
    ? null
    : `${card.delta >= 0 ? "+" : ""}${card.delta}% vs comparison`;
  return (
    <KpiCard
      stacked
      label={card.label}
      value={card.value}
      edge={edgeFromTone(card.tone ?? "border-t-primary-500")}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-label text-xs">
        <span className="text-on-surface-muted">{card.scope}</span>
        {deltaLabel && (
          <span className={improved ? "text-emerald-600" : card.delta === 0 ? "text-on-surface-muted" : "text-red-600"}>
            {deltaLabel}
          </span>
        )}
      </div>
    </KpiCard>
  );
}

const SEGMENT_LABEL: Record<string, string> = {
  A: "Hot", B: "Warm", C: "Cold", D: "Not Interested",
};

function MovementFlows({ flows }: { flows: CompareMovement["flows"] }) {
  if (flows.length === 0) {
    return (
      <p className="font-label text-sm text-on-surface-muted">
        No leads changed segment in this period.
      </p>
    );
  }
  const max = Math.max(...flows.map((f) => f.total), 1);
  const RANK: Record<string, number> = { D: 0, C: 1, B: 2, A: 3 };

  return (
    <div className="space-y-2.5">
      {flows.map((f) => {
        const up = (RANK[f.to] ?? 0) > (RANK[f.from] ?? 0);
        return (
          <div key={`${f.from}-${f.to}`} className="flex items-center gap-3">
            <span className="w-36 shrink-0 font-label text-xs text-on-surface-muted">
              {SEGMENT_LABEL[f.from] ?? f.from} → {SEGMENT_LABEL[f.to] ?? f.to}
            </span>
            <div className="h-4 flex-1 overflow-hidden rounded-full bg-surface-mid">
              <div
                className={`h-4 rounded-full ${up ? "bg-emerald-500" : "bg-red-400"}`}
                style={{ width: `${Math.round((f.total / max) * 100)}%` }}
              />
            </div>
            <span className="w-10 shrink-0 text-right font-label text-xs font-semibold text-on-surface">
              {f.total}
            </span>
          </div>
        );
      })}
    </div>
  );
}

const SEGMENT_MIX_COLORS = {
  hot: "#10b981", warm: "#3b82f6", cold: "#f59e0b", disqualified: "#f87171",
} as const;

function SegmentMixChart({
  points,
}: {
  points: ComparePeriod["daily_segment_mix"];
}) {
  if (!points || points.length === 0) {
    return (
      <p className="font-label text-sm text-on-surface-muted">
        No lead activity in this period.
      </p>
    );
  }
  return (
    <div role="img" aria-label="Lead quality mix per day">
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="day" tick={{ fontSize: 10, fill: "#94a3b8" }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "#94a3b8" }} />
          <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="hot" stackId="mix" fill={SEGMENT_MIX_COLORS.hot} name="Hot" />
          <Bar dataKey="warm" stackId="mix" fill={SEGMENT_MIX_COLORS.warm} name="Warm" />
          <Bar dataKey="cold" stackId="mix" fill={SEGMENT_MIX_COLORS.cold} name="Cold" />
          <Bar dataKey="disqualified" stackId="mix" fill={SEGMENT_MIX_COLORS.disqualified} name="Not Interested" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

const DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function LeadHeatmap({ points }: { points: ComparePeriod["heatmap"] }) {
  const lookup = useMemo(() => {
    const m: Record<string, number> = {};
    for (const p of points ?? []) m[`${p.dow}-${p.hour}`] = p.total;
    return m;
  }, [points]);
  const max = Math.max(1, ...(points ?? []).map((p) => p.total));

  if (!points || points.length === 0) {
    return (
      <p className="font-label text-sm text-on-surface-muted">
        No inbound leads in this period.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <div className="grid gap-0.5" style={{ gridTemplateColumns: "40px repeat(24, minmax(0, 1fr))" }}>
        <div />
        {Array.from({ length: 24 }, (_, h) => (
          <div key={h} className="text-center font-label text-[9px] text-on-surface-muted">
            {h % 3 === 0 ? h : ""}
          </div>
        ))}
        {DOW_LABELS.map((label, dow) => (
          <div key={label} className="contents">
            <div className="flex items-center font-label text-[9px] text-on-surface-muted">{label}</div>
            {Array.from({ length: 24 }, (_, hour) => {
              const count = lookup[`${dow}-${hour}`] ?? 0;
              const intensity = count === 0 ? 0 : 0.15 + 0.85 * (count / max);
              return (
                <div
                  key={hour}
                  title={`${label} ${hour}:00 — ${count} lead${count === 1 ? "" : "s"}`}
                  className="h-6 rounded-sm"
                  style={{ backgroundColor: `rgba(var(--primary-800-rgb), ${intensity})` }}
                />
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ComparisonHeader({ data }: { data: ComparePayload }) {
  const hasComparison = data.previous !== null;
  return (
    <div className="rounded-card bg-surface p-5 shadow-card ring-1 ring-[#c4c7c7]/15 sm:p-6">
      <p className="font-display text-lg font-bold leading-snug text-on-surface sm:text-xl">
        {hasComparison ? data.summary_text ?? "Period comparison" : "Selected period"}
      </p>
      <p className="mt-2 font-label text-xs text-on-surface-muted">
        {data.current.start} → {data.current.end}
        {data.previous !== null && `  vs  ${data.previous.start} → ${data.previous.end}`}
      </p>
    </div>
  );
}

export function shouldRenderComparisonChart(previous: ComparePeriod | null): boolean {
  return previous !== null;
}

function ComparisonChart({
  points,
  currentLabel,
  previousLabel,
}: {
  points: ComparePoint[];
  currentLabel: string;
  previousLabel?: string;
}) {
  return (
    <div role="img" aria-label="Period comparison chart">
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#94a3b8" }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "#94a3b8" }} />
          <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            type="monotone" dataKey="current" name={currentLabel}
            stroke={CURRENT_COLOR} strokeWidth={2.5} dot={false} connectNulls
          />
          {previousLabel && (
            <Line
              type="monotone" dataKey="previous" name={previousLabel}
              stroke={PREVIOUS_COLOR} strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function ComparisonTable({
  metrics,
  hasComparison,
}: {
  metrics: Record<string, CompareMetric>;
  hasComparison: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-surface-mid">
            {["Metric", "This period", ...(hasComparison ? ["Previous", "Change"] : [])].map((h) => (
              <th
                key={h}
                className="pb-3 pr-4 font-label text-xs font-semibold uppercase tracking-wider text-on-surface-muted"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {TABLE_ROWS.map((row) => {
            const metric = metrics[row.key];
            if (!metric) return null;
            return (
              <tr key={row.key} className="border-b border-surface-mid/50">
                <td className="py-3 pr-4 font-body text-sm text-on-surface">{row.label}</td>
                <td className="py-3 pr-4 font-display text-sm font-bold text-on-surface">
                  {metric.current.toLocaleString()}
                </td>
                {hasComparison && (
                  <>
                    <td className="py-3 pr-4 font-label text-sm text-on-surface-muted">
                      {metric.previous.toLocaleString()}
                    </td>
                    <td className="py-3 pr-4">
                      <DeltaBadge pct={metric.delta_pct} />
                    </td>
                  </>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function CompareTab({
  range,
  comparison,
  onDataChange,
  filtersOpen,
  onToggleFilters,
  hasActiveFilters,
}: {
  range: RangeValue;
  comparison: ComparisonSelection;
  onDataChange?: (ready: boolean) => void;
  filtersOpen: boolean;
  onToggleFilters: () => void;
  hasActiveFilters: boolean;
}) {
  const [seriesId, setSeriesId] = useState<string>("leads_inbound");
  const [data, setData] = useState<ComparePayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const rangeIsComplete = isCompleteSelection(range);
  const canLoadComparison_ = canLoadComparison(range, comparison);

  useEffect(() => {
    onDataChange?.(data !== null);
  }, [data, onDataChange]);

  const params = useMemo<CompareParams>(() => {
    const reporting = { preset: range.preset, start: range.start, end: range.end };
    if (comparison.mode === "custom") {
      return {
        ...reporting,
        comparison: "custom",
        comparison_start: comparison.start,
        comparison_end: comparison.end,
      };
    }
    return { ...reporting, comparison: comparison.mode };
  }, [range.preset, range.start, range.end, comparison.mode, comparison.start, comparison.end]);

  useEffect(() => {
    if (!rangeIsComplete) {
      setData(null);
      setErr(null);
      return;
    }
    let isCurrent = true;
    setErr(null);
    const fetchParams: CompareParams = canLoadComparison_
      ? params
      : { preset: range.preset, start: range.start, end: range.end, comparison: "off" };
    setData(null);
    api.analytics
      .compare(fetchParams)
      .then((d) => { if (isCurrent) setData(d); })
      .catch((e: unknown) => {
        if (isCurrent) setErr(e instanceof Error ? e.message : "Failed to load");
      });
    return () => { isCurrent = false; };
  }, [rangeIsComplete, canLoadComparison_, params, refreshKey]);

  const handleExport = () => {
    api.analytics.exportCompareCsv(params);
  };

  return (
    <div className="space-y-6">
      {!rangeIsComplete && (
        <p className="font-label text-sm text-on-surface-muted">
          Pick a valid start and end date for each custom period.
        </p>
      )}

      {err && (
        <div className="rounded-xl bg-red-50 p-4 font-label text-sm text-red-700 ring-1 ring-red-200">
          {err}
        </div>
      )}

      {rangeIsComplete && !err && (
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mb-5">
          <div className="md:col-span-4 grid grid-cols-2 lg:grid-cols-4 gap-4">
            {!data ? (
              <AiraLoader inline className="col-span-full min-h-24" />
            ) : (
              buildOverviewCards({ current: data.current, previous: data.previous }).map((card) => (
                <PerformanceKpi key={card.label} card={card} />
              ))
            )}
          </div>
          <div className="flex flex-col justify-start gap-2 p-1">
            <button
              onClick={() => setRefreshKey((k) => k + 1)}
              className="flex items-center justify-center gap-2 px-3 py-2 rounded-xl bg-white border border-[#e2e8f0] hover:bg-[#f1f5f9] text-[#0A1528] font-label text-xs font-bold transition-all shadow-sm"
            >
              <RefreshCw size={12} className={!data ? "animate-spin" : ""} />
              <span>Refresh</span>
            </button>
            <FiltersToggleButton
              open={filtersOpen}
              active={hasActiveFilters}
              onClick={onToggleFilters}
            />
            <button
              onClick={handleExport}
              disabled={!data}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-primary text-white rounded-xl font-label text-xs font-bold hover:bg-primary/90 transition-all disabled:opacity-40 shadow-sm"
            >
              <Download size={12} />
              <span>Download CSV</span>
            </button>
          </div>
        </div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:gap-6">
            <SectionCard title="Selected-period pipeline">
              <FunnelSteps steps={buildFunnel(data.current.summary)} />
            </SectionCard>
            <SectionCard title="New leads by day">
              <div role="img" aria-label="New leads in the selected period chart">
                <ResponsiveContainer width="100%" height={220}>
                  <AreaChart data={buildTrend(data.current)} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                    <defs>
                      <linearGradient id="leadGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="var(--primary-800)" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="var(--primary-800)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="day" tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }} />
                    <Area type="monotone" dataKey="count" stroke="var(--primary-800)" fill="url(#leadGrad)" strokeWidth={2} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </SectionCard>
          </div>

          {(() => {
            const previous = data.previous;
            const hasComparison = shouldRenderComparisonChart(previous);
            return (
              <>

          {/* Money — the question an owner actually asks. Cost metrics use
              sense="lower" so a rise never renders as good news; ad spend is
              neutral because neither spending more nor less is a result. */}
          {(data.current.money.spend ?? 0) > 0 && (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
              <StatCard
                label="Ad spend"
                value={money(data.current.money.spend)}
                delta={hasComparison ? data.money_metrics.spend?.delta_pct : undefined}
                sense="neutral"
                sub={previous ? `was ${money(previous.money.spend)}` : undefined}
                tone="border-t-sky-400"
              />
              <StatCard
                label="Cost per lead"
                value={money(data.current.money.cost_per_lead)}
                delta={hasComparison ? data.money_metrics.cost_per_lead?.delta_pct : undefined}
                sense="lower"
                sub={previous ? `was ${money(previous.money.cost_per_lead)}` : undefined}
                tone="border-t-amber-400"
              />
              <StatCard
                label="Cost per hot lead"
                value={money(data.current.money.cost_per_hot_lead)}
                delta={hasComparison ? data.money_metrics.cost_per_hot_lead?.delta_pct : undefined}
                sense="lower"
                sub={previous ? `was ${money(previous.money.cost_per_hot_lead)}` : undefined}
                tone="border-t-rose-400"
              />
              <StatCard
                label="Ad-attributed leads"
                value={(data.current.money.ad_leads ?? 0).toLocaleString()}
                delta={hasComparison ? data.money_metrics.ad_leads?.delta_pct : undefined}
                sub={`${data.current.money.ad_hot_leads ?? 0} hot`}
                tone="border-t-emerald-400"
              />
            </div>
          )}

          {/* Response speed — previously hardcoded to null and never shown. */}
          {(data.current.response.inbound_total ?? 0) > 0 && (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
              <StatCard
                label="Typical reply time"
                value={seconds(data.current.response.p50_seconds)}
                delta={hasComparison ? data.response_metrics.p50_seconds?.delta_pct : undefined}
                sense="lower"
                sub="median"
                tone="border-t-sky-400"
              />
              <StatCard
                label="Slowest 10%"
                value={seconds(data.current.response.p90_seconds)}
                delta={hasComparison ? data.response_metrics.p90_seconds?.delta_pct : undefined}
                sense="lower"
                sub="90th percentile"
                tone="border-t-amber-400"
              />
              <StatCard
                label="Messages answered"
                value={(data.current.response.answered ?? 0).toLocaleString()}
                sub={`of ${(data.current.response.inbound_total ?? 0).toLocaleString()} received`}
                tone="border-t-emerald-400"
              />
              <StatCard
                label="Leads warmed up"
                value={data.current.movement.promoted.toLocaleString()}
                delta={hasComparison ? data.movement_metrics.promoted?.delta_pct : undefined}
                sub={`${data.current.movement.promoted_to_hot} became hot`}
                tone="border-t-teal-400"
              />
            </div>
          )}

          {/* What the AI did -- straight from lead_stage_events. */}
          {data.current.movement.flows.length > 0 && (
            <div className="min-w-0 rounded-card bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15 sm:p-6">
              <h2 className="font-display text-base font-bold text-primary">
                What the AI did with your leads
              </h2>
              <p className="mb-4 mt-1 font-label text-xs text-on-surface-muted">
                The AI moved {data.current.movement.promoted} leads up and{" "}
                {data.current.movement.demoted} down.{" "}
                {data.current.movement.promoted_to_hot} became hot leads.
              </p>
              <MovementFlows flows={data.current.movement.flows} />
            </div>
          )}

          <div className="min-w-0 rounded-card bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15 sm:p-6">
            <h2 className="font-display text-base font-bold text-primary">
              Lead quality mix, day by day
            </h2>
            <p className="mb-4 mt-1 font-label text-xs text-on-surface-muted">
              How many leads landed in each segment on the day they arrived.
            </p>
            <SegmentMixChart points={data.current.daily_segment_mix} />
          </div>

          <div className="min-w-0 rounded-card bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15 sm:p-6">
            <h2 className="font-display text-base font-bold text-primary">
              When leads reach out (IST)
            </h2>
            <p className="mb-4 mt-1 font-label text-xs text-on-surface-muted">
              Inbound leads by day of week and hour.
            </p>
            <LeadHeatmap points={data.current.heatmap} />
          </div>

          {hasComparison && previous && (
            <div className="min-w-0 rounded-card bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15 sm:p-6">
              <div className="mb-4 flex flex-wrap gap-2">
                {SERIES_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    onClick={() => setSeriesId(option.id)}
                    className={`rounded-lg px-3 py-1.5 font-label text-xs font-semibold ring-1 transition-colors ${
                      seriesId === option.id
                        ? "bg-primary-light text-primary ring-primary-muted"
                        : "bg-surface text-on-surface-muted ring-[#c4c7c7]/15 hover:text-on-surface"
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <ComparisonChart
                points={data.series[seriesId] ?? []}
                currentLabel={`${data.current.start} → ${data.current.end}`}
                previousLabel={`${previous.start} → ${previous.end}`}
              />
            </div>
          )}

          <div className="min-w-0 rounded-card bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15 sm:p-6">
            <h2 className="mb-4 font-display text-base font-bold text-primary">
              {hasComparison ? "Every number, side by side" : "Selected-period metrics"}
            </h2>
            <ComparisonTable metrics={data.metrics} hasComparison={hasComparison} />
          </div>
              </>
            );
          })()}

        </>
      )}
    </div>
  );
}

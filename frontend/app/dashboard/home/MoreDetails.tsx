"use client";
import Link from "next/link";
import { cn } from "@/lib/utils";
import type { AnalyticsOverview } from "@/lib/api";
import { CHANNEL_LABELS } from "@/components/dashboard/LeadSourceSection";
import { AdSpendCard } from "./AdSpendCard";
import { CARD, ChartCard, WIDE_CARD } from "./ChartCard";
import { TeamCallsCard } from "./TeamCallsCard";
import { aiShare, barPct, dayName, donutSlices, linePlot, niceMax, pointsAttr } from "./homeCharts";

/**
 * "More details": six chart cards under the Today block. Each keeps the gating it had as a section:
 * Team calls only for clients with telecalling, Ad spend only when there are campaigns.
 */
export function MoreDetails({ overview, telecalling }: { overview: AnalyticsOverview; telecalling: boolean }) {
  return (
    <section aria-label="More details" className="space-y-3">
      <h2 className="font-label text-xs font-bold uppercase tracking-wider text-ink-muted">More details</h2>
      <div className="flex flex-wrap gap-3">
        <LeadsByDayCard overview={overview} />
        <LeadsByTypeCard bySegment={overview.by_segment_today} />
        <AiGaugeCard overview={overview} />
        <SourcesCard overview={overview} />
        {telecalling && <TeamCallsCard />}
        <AdSpendCard />
      </div>
    </section>
  );
}

// ───────────────────────────────────────────────────────────────── New leads by day (line)

const LINE = { w: 600, h: 178, left: 34, right: 590, top: 22, bottom: 150 };

function LeadsByDayCard({ overview }: { overview: AnalyticsOverview }) {
  // Fresh leads plus older leads an ad brought back: the "conversations started" number the old tiles used.
  const returning = new Map((overview.returning_ad_leads_daily ?? []).map((d) => [d.day, d.count]));
  const days = overview.daily_leads.map((d) => ({
    day: d.day,
    fresh: d.count,
    returned: returning.get(d.day) ?? 0,
    total: d.count + (returning.get(d.day) ?? 0),
  }));
  const values = days.map((d) => d.total);
  const sum = values.reduce((a, b) => a + b, 0);
  const trend = overview.daily_leads_trend_pct;
  const note =
    trend == null || trend === 0
      ? `${sum} this week`
      : `${sum} this week · ${trend > 0 ? "up" : "down"} ${Math.abs(trend)}% on last week`;

  if (days.length < 2) {
    return (
      <ChartCard title="New leads by day" note={note} className={WIDE_CARD}>
        <p className="font-body text-sm text-ink-muted">No leads in the last 7 days.</p>
      </ChartCard>
    );
  }

  const max = Math.max(...values);
  const yMax = niceMax(max);
  const pts = linePlot(values, LINE, yMax);
  const ticks = [0, yMax / 2, yMax];
  const tickY = (v: number) => LINE.bottom - (v / yMax) * (LINE.bottom - LINE.top);
  const peak = max > 0 ? values.indexOf(max) : -1;
  const summary = days.map((d) => `${dayName(d.day)} ${d.total}`).join(", ");
  const area = `M${LINE.left},${LINE.bottom} L${pointsAttr(pts).split(" ").join(" ")} L${pts[pts.length - 1].x},${LINE.bottom} Z`;

  return (
    <ChartCard title="New leads by day" note={note} className={WIDE_CARD}>
      <svg viewBox={`0 0 ${LINE.w} ${LINE.h}`} width="100%" role="img" aria-label={`New leads by day, last 7 days: ${summary}`}>
        <defs>
          <linearGradient id="homeLeadsArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" style={{ stopColor: "var(--primary-800)", stopOpacity: 0.22 }} />
            <stop offset="1" style={{ stopColor: "var(--primary-800)", stopOpacity: 0 }} />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={LINE.left} x2={LINE.right} y1={tickY(t)} y2={tickY(t)} className="stroke-border-subtle" strokeWidth={1} />
            <text x={LINE.left - 8} y={tickY(t) + 4} textAnchor="end" fontSize={11} className="fill-ink-muted max-md:[font-size:18px]">
              {t}
            </text>
          </g>
        ))}
        <path d={area} fill="url(#homeLeadsArea)" />
        <polyline points={pointsAttr(pts)} fill="none" className="stroke-primary-800" strokeWidth={2} strokeLinejoin="round" />
        {pts.map((p, i) => (
          <g key={days[i].day}>
            <circle cx={p.x} cy={p.y} r={14} fill="transparent">
              <title>
                {`${dayName(days[i].day)}: ${days[i].total} new leads${days[i].returned > 0 ? ` (${days[i].fresh} new, ${days[i].returned} came back through an ad)` : ""}`}
              </title>
            </circle>
            <circle cx={p.x} cy={p.y} r={4} className="fill-white stroke-primary-800" strokeWidth={2} pointerEvents="none" />
            <text x={p.x} y={LINE.h - 8} textAnchor="middle" fontSize={11} className="fill-ink-muted max-md:[font-size:18px]">
              {dayName(days[i].day)}
            </text>
          </g>
        ))}
        {peak >= 0 && (
          <text x={pts[peak].x} y={Math.max(pts[peak].y - 10, 12)} textAnchor="middle" fontSize={12} fontWeight={800} className="fill-ink max-md:[font-size:19px]">
            {values[peak]}
          </text>
        )}
      </svg>
    </ChartCard>
  );
}

// ───────────────────────────────────────────────────────────────── Hot / Warm / Cold (ring)

const SEGMENTS = [
  { key: "A", label: "Hot", stroke: "stroke-rose-600", swatch: "bg-rose-600" },
  { key: "B", label: "Warm", stroke: "stroke-amber-600", swatch: "bg-amber-600" },
  { key: "C", label: "Cold", stroke: "stroke-blue-500", swatch: "bg-blue-500" },
  { key: "D", label: "Not interested", stroke: "stroke-slate-400", swatch: "bg-slate-400" },
] as const;

function LeadsByTypeCard({ bySegment }: { bySegment: AnalyticsOverview["by_segment_today"] | undefined }) {
  const counts = SEGMENTS.map((s) => Math.max(0, bySegment?.[s.key] ?? 0));
  const total = counts.reduce((a, b) => a + b, 0);
  // "Not interested" is a legend row only when there is one; Hot, Warm and Cold always are.
  const rows = SEGMENTS.map((s, i) => ({ ...s, count: counts[i] })).filter((r) => r.key !== "D" || r.count > 0);
  const slices = donutSlices(counts, 46);
  const summary = rows.map((r) => `${r.label} ${r.count}`).join(", ");

  return (
    <ChartCard title="Leads by type" note="today" className={CARD}>
      {total === 0 ? (
        <p className="font-body text-sm text-ink-muted">No new leads today yet.</p>
      ) : (
        <div className="flex items-center gap-5">
          <svg width={120} height={120} viewBox="0 0 120 120" role="img" aria-label={`Leads by type today: ${summary}`} className="shrink-0">
            <circle cx={60} cy={60} r={46} fill="none" className="stroke-surface-mid" strokeWidth={16} />
            {SEGMENTS.map((s, i) =>
              slices[i].dash ? (
                <circle
                  key={s.key}
                  cx={60}
                  cy={60}
                  r={46}
                  fill="none"
                  className={s.stroke}
                  strokeWidth={16}
                  strokeDasharray={slices[i].dash ?? undefined}
                  strokeDashoffset={slices[i].offset}
                  transform="rotate(-90 60 60)"
                >
                  <title>{`${s.label}: ${counts[i]} of ${total}`}</title>
                </circle>
              ) : null,
            )}
            <text x={60} y={58} textAnchor="middle" fontSize={22} fontWeight={800} className="fill-ink">
              {total}
            </text>
            <text x={60} y={76} textAnchor="middle" fontSize={11} className="fill-ink-muted max-md:[font-size:18px]">
              today
            </text>
          </svg>
          <ul className="flex min-w-0 flex-1 flex-col gap-2.5">
            {rows.map((r) => (
              <li key={r.key} className="flex items-center gap-2 font-body text-[13px]">
                <span className={cn("h-2.5 w-2.5 shrink-0 rounded-[3px]", r.swatch)} aria-hidden />
                <span className="min-w-0 flex-1 truncate text-ink-secondary">{r.label}</span>
                <b className="tabular-nums text-ink">{r.count}</b>
              </li>
            ))}
          </ul>
        </div>
      )}
    </ChartCard>
  );
}

// ───────────────────────────────────────────────────────────────── % answered by AI (gauge)

function AiGaugeCard({ overview }: { overview: AnalyticsOverview }) {
  const answered = overview.ai_handled_today ?? 0;
  const couldnt = overview.couldnt_answer_today ?? 0;
  const pct = aiShare(answered, couldnt);
  const label = pct == null ? "No AI chats yet today" : `AI answered ${answered}, could not answer ${couldnt}: ${pct} percent`;

  return (
    <ChartCard title="AI did the talking" note="today" className={CARD}>
      <div className="flex items-center gap-4">
        <svg width={132} height={78} viewBox="0 0 132 78" role="img" aria-label={label} className="shrink-0">
          <path d="M14,68 A52,52 0 0 1 118,68" fill="none" className="stroke-surface-mid" strokeWidth={14} strokeLinecap="round" pathLength={100} />
          {pct != null && pct > 0 && (
            <path
              d="M14,68 A52,52 0 0 1 118,68"
              fill="none"
              className="stroke-primary-800"
              strokeWidth={14}
              strokeLinecap="round"
              pathLength={100}
              strokeDasharray={`${pct} 100`}
            >
              <title>{`AI answered ${answered}, could not answer ${couldnt}`}</title>
            </path>
          )}
          <text x={66} y={62} textAnchor="middle" fontSize={22} fontWeight={800} className="fill-ink">
            {pct == null ? "—" : `${pct}%`}
          </text>
        </svg>
        <div className="min-w-0 font-body text-[13px] leading-[1.9] text-ink-secondary">
          {pct == null ? (
            <p>No AI chats yet today.</p>
          ) : (
            <>
              <div>
                AI answered <b className="text-ink">{answered}</b>
              </div>
              <div>
                Couldn&apos;t answer <b className="text-ink">{couldnt}</b>
                {couldnt > 0 && (
                  <>
                    {" "}
                    <Link href="/dashboard/brain/couldnt-answer" className="inline-flex min-h-8 items-center font-label font-bold text-primary-700 hover:text-primary-900">
                      Teach ›
                    </Link>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </ChartCard>
  );
}

// ───────────────────────────────────────────────────────────────── Where leads came from this week (bars)

const SOURCE_ROWS = 6;

function SourcesCard({ overview }: { overview: AnalyticsOverview }) {
  // An older backend has no 7-day breakdown: show today's instead, and say so.
  const week = overview.channel_breakdown_7d;
  const breakdown = week ?? overview.channel_breakdown_today ?? {};
  const entries = (Object.entries(breakdown) as [string, number | undefined][])
    .map(([k, v]) => [k, v ?? 0] as [string, number])
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, SOURCE_ROWS);
  const max = entries[0]?.[1] ?? 0;

  return (
    <ChartCard title="Where leads came from" note={week ? "this week" : "today"} className={CARD}>
      {entries.length === 0 ? (
        <p className="font-body text-sm text-ink-muted">{week ? "No leads this week yet." : "No leads yet today."}</p>
      ) : (
        <ul className="flex flex-col gap-3.5">
          {entries.map(([channel, count]) => {
            const name = CHANNEL_LABELS[channel] ?? channel;
            return (
              <li key={channel} title={`${name}: ${count} leads`}>
                <div className="mb-1.5 flex justify-between gap-2 font-body text-[13px]">
                  <span className="min-w-0 truncate text-ink-secondary">{name}</span>
                  <b className="tabular-nums text-ink">{count}</b>
                </div>
                <div className="h-2.5 rounded-full bg-surface-mid">
                  <div className="h-2.5 rounded-full bg-primary-800" style={{ width: `${barPct(count, max)}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </ChartCard>
  );
}

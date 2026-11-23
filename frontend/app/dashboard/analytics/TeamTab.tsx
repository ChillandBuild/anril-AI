"use client";

import { formatRupees, formatSeconds, type ReplyTimes, type TeamReport } from "@/lib/reportsApi";
import { PeriodMetrics } from "./PeriodMetrics";
import { ReportFrame } from "./ReportFrame";
import { DataTable, Empty, SectionCard } from "./reportsUi";

const CALL_LABELS: Record<string, string> = {
  calls: "Calls made",
  total_calls: "Calls made",
  connected: "Calls picked up",
  talk_seconds: "Time on calls",
  avg_talk_seconds: "Average call",
};

function ReplyBlock({ who, t }: { who: string; t: ReplyTimes | null | undefined }) {
  return (
    <div className="rounded-xl bg-surface-low p-4">
      <p className="font-label text-xs font-bold text-[#556274]">{who}</p>
      {t ? (
        <>
          <p className="mt-1 font-display text-2xl font-extrabold text-on-surface">{formatSeconds(t.p50_seconds)}</p>
          <p className="font-label text-xs text-[#556274]">
            typical reply · slowest 10%: {formatSeconds(t.p90_seconds)} · {(t.answered ?? 0).toLocaleString("en-IN")} answered
          </p>
        </>
      ) : (
        <p className="mt-1 font-label text-sm text-[#556274]">Not enough replies to show.</p>
      )}
    </div>
  );
}

export function TeamTab({ query, telecallingOn }: { query: string | null; telecallingOn: boolean }) {
  return (
    <ReportFrame<TeamReport> tab="team" query={query} csvTab="team">
      {(data, tools) => {
        const handled = data.handled;
        const total = handled ? handled.by_ai_alone + handled.passed_to_person : 0;
        return (
          <div className="space-y-5">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:gap-6">
              <SectionCard title="How fast we reply">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <ReplyBlock who="AI agent" t={data.reply_times?.ai} />
                  <ReplyBlock who="Your team" t={data.reply_times?.staff} />
                </div>
              </SectionCard>
              <SectionCard title="Who handled the chats">
                {handled && total > 0 ? (
                  <p className="font-body text-sm text-on-surface">
                    <span className="font-bold">{handled.by_ai_alone.toLocaleString("en-IN")}</span> chats were handled by the AI agent alone.{" "}
                    <span className="font-bold">{handled.passed_to_person.toLocaleString("en-IN")}</span> were passed to a person.
                  </p>
                ) : (
                  <Empty>No chats in these days.</Empty>
                )}
              </SectionCard>
            </div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:gap-6">
              {data.sales_by_person && (
                <SectionCard title="Sales by person">
                  <DataTable
                    rows={data.sales_by_person}
                    rowKey={(r) => r.name}
                    empty="No sales in these days."
                    columns={[
                      { key: "name", label: "Who", render: (r) => <span className="font-semibold">{r.name}</span> },
                      { key: "count", label: "Sales", right: true, render: (r) => r.count.toLocaleString("en-IN") },
                      ...(data.money_hidden ? [] : [{ key: "paise", label: "Amount", right: true, render: (r: { sales_paise?: number | null }) => formatRupees(r.sales_paise) }]),
                    ]}
                  />
                </SectionCard>
              )}
              {data.stars_by_person && (
                <SectionCard title="Stars by person" hint="From customer feedback.">
                  <DataTable
                    rows={data.stars_by_person}
                    rowKey={(r) => r.name}
                    empty="No star ratings yet."
                    columns={[
                      { key: "name", label: "Who", render: (r) => <span className="font-semibold">{r.name}</span> },
                      { key: "avg", label: "Average", right: true, render: (r) => `${r.avg.toFixed(1)} ★` },
                      { key: "count", label: "Ratings", right: true, render: (r) => r.count.toLocaleString("en-IN") },
                    ]}
                  />
                </SectionCard>
              )}
            </div>
            {telecallingOn && data.calls && Object.keys(data.calls).length > 0 && (
              <SectionCard title="Calls">
                <PeriodMetrics report={{ period: data.calls, before: null }} tools={tools} labels={CALL_LABELS} />
              </SectionCard>
            )}
          </div>
        );
      }}
    </ReportFrame>
  );
}

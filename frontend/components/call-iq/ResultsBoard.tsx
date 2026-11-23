"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { ChevronDown, ChevronUp, Download, Loader2 } from "lucide-react";
import { AiraLoader } from "@/components/AiraLoader";
import { api, type TelecallingAnalyticsExtended } from "@/lib/api";
import { formatRupees } from "@/lib/reportsApi";
import { istTodayIso } from "@/lib/utils";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import OutcomeBreakdown from "@/app/dashboard/telecalling/components/sections/OutcomeBreakdown";
import CallsPerHour from "@/app/dashboard/telecalling/components/sections/CallsPerHour";
import {
  RESULTS_PERIODS, canDownloadCalls, canSeeCallCharts, getResults, periodDates, pickedUpText, showsMoney, sortResults, talkText,
  type ResultsPeriod, type ResultsResponse, type ResultsRow, type ResultsSortKey,
} from "@/lib/callIqApi";
import { Card, ErrorBox, PeriodPicker, Stat } from "./CallIqShell";
import { useCallIqData } from "./useCallIqData";

function Totals({ row, money }: { row: ResultsRow; money: boolean }) {
  return (
    <Card className="bg-primary/5">
      <h2 className="font-display text-base font-bold text-primary">Everyone together</h2>
      <div className={money ? "mt-3 grid grid-cols-2 gap-3 sm:grid-cols-6" : "mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5"}>
        <Stat label="Calls" value={row.calls} />
        <Stat label="Picked up" value={row.connected} hint={pickedUpText(row)} />
        <Stat label="Time on calls" value={talkText(row.talk_seconds)} />
        <Stat label="Visits booked" value={row.visits ?? 0} hint="Booked by phone" />
        <Stat label="Orders" value={row.orders} />
        {money ? <Stat label="Money" value={formatRupees(row.revenue_paise ?? 0)} hint="Sales before GST" /> : null}
      </div>
    </Card>
  );
}

const COLUMNS: { key: ResultsSortKey; label: string; money?: boolean }[] = [
  { key: "name", label: "Telecaller" },
  { key: "calls", label: "Calls" },
  { key: "connected", label: "Picked up" },
  { key: "talk_seconds", label: "Time on calls" },
  { key: "visits", label: "Visits" },
  { key: "orders", label: "Orders" },
  { key: "revenue_paise", label: "Money", money: true },
];

function PeopleTable({ data, money }: { data: ResultsResponse; money: boolean }) {
  const [sortKey, setSortKey] = useState<ResultsSortKey>("calls");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const rows = useMemo(() => sortResults(data.callers, sortKey, dir), [data.callers, sortKey, dir]);
  const columns = COLUMNS.filter((c) => !c.money || money);

  const sortBy = (key: ResultsSortKey) => {
    if (key === sortKey) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setDir(key === "name" ? "asc" : "desc");
    }
  };

  return (
    <Card>
      <h2 className="font-display text-base font-bold text-primary">Each telecaller</h2>
      <p className="mt-1 font-label text-xs text-ink-secondary">Tap a column name to sort by it.</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-left font-label text-sm">
          <thead>
            <tr className="border-b border-[#c4c7c7]/40">
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={sortKey === c.key ? (dir === "asc" ? "ascending" : "descending") : "none"}
                  className="py-2 pr-3 font-bold text-ink-secondary"
                >
                  <button type="button" onClick={() => sortBy(c.key)} className="inline-flex min-h-10 items-center gap-1 hover:text-primary">
                    {c.label}
                    {sortKey === c.key ? (dir === "asc" ? <ChevronUp size={12} aria-hidden /> : <ChevronDown size={12} aria-hidden />) : null}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.caller_id} className="border-b border-[#c4c7c7]/20 last:border-0">
                <td className="py-2.5 pr-3 font-bold text-primary">{p.name}</td>
                <td className="py-2.5 pr-3">{p.calls}</td>
                <td className="py-2.5 pr-3">
                  {p.connected}
                  <span className="block text-xs text-ink-secondary">{p.calls ? `${Math.round((p.connected / p.calls) * 100)}%` : "No calls"}</span>
                </td>
                <td className="py-2.5 pr-3">{talkText(p.talk_seconds)}</td>
                <td className="py-2.5 pr-3">{p.visits ?? 0}</td>
                <td className="py-2.5 pr-3">{p.orders}</td>
                {money ? <td className="py-2.5 pr-3">{formatRupees(p.revenue_paise ?? 0)}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function DownloadButton({ period }: { period: ResultsPeriod }) {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    const { from, to } = periodDates(period, istTodayIso());
    setBusy(true);
    try {
      await api.analytics.exportTelecallingCsv(from, to);
      toast.success("Download started");
    } catch {
      toast.error("The download did not start. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      onClick={run}
      disabled={busy}
      className="inline-flex min-h-10 items-center gap-2 rounded-lg px-3 font-label text-sm font-bold text-primary ring-1 ring-[#c4c7c7]/40 hover:bg-black/5 disabled:opacity-50"
    >
      {busy ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Download size={14} aria-hidden />}
      Download every call
    </button>
  );
}

/** What happened on picked-up calls, and calls by hour: the Reports numbers, for the same days. */
function CallCharts({ period }: { period: ResultsPeriod }) {
  const { data, err } = useCallIqData<TelecallingAnalyticsExtended>(
    () => api.analytics.telecallingExtended(periodDates(period, istTodayIso())),
    `charts:${period}`,
  );
  if (err) return null; // the table above still has every number; the charts are extra
  if (!data) return <AiraLoader inline className="min-h-24" />;
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <OutcomeBreakdown stats={data} />
      <CallsPerHour stats={data} />
    </div>
  );
}

export function ResultsBoard() {
  const [period, setPeriod] = useState<ResultsPeriod>("today");
  const { data, err, loading, reload } = useCallIqData<ResultsResponse>(() => getResults(period), period);
  const { role, roleSlug, permissions } = useAuthRole();
  const money = showsMoney(data);
  const charts = canSeeCallCharts(role, permissions, roleSlug);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PeriodPicker label="Days to look at" options={RESULTS_PERIODS} value={period} onChange={setPeriod} />
        {canDownloadCalls(role, permissions) ? <DownloadButton period={period} /> : null}
      </div>
      {err ? <ErrorBox message={err} onRetry={reload} /> : null}
      {loading && !data ? <AiraLoader inline className="min-h-40" /> : null}
      {data ? (
        data.callers.length === 0 ? (
          <Card><p className="font-label text-sm text-ink-secondary">No telecallers to show yet.</p></Card>
        ) : (
          <div className="space-y-3">
            <Totals row={data.totals} money={money} />
            <PeopleTable data={data} money={money} />
            {charts ? <CallCharts period={period} /> : null}
            <p className="font-label text-xs text-ink-secondary">
              An order counts for the person who sold it, on the day it was paid. Picked up means the telecaller marked the call as connected. A visit counts for the person who booked it, on the day they booked it. Time on calls adds up each call&apos;s recorded length.
            </p>
          </div>
        )
      ) : null}
    </div>
  );
}

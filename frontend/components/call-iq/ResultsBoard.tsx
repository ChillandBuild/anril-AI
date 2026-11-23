"use client";

import { useState } from "react";
import { AiraLoader } from "@/components/AiraLoader";
import { formatRupees } from "@/lib/reportsApi";
import {
  RESULTS_PERIODS, getResults, pickedUpText, showsMoney,
  type ResultsPeriod, type ResultsResponse, type ResultsRow,
} from "@/lib/callIqApi";
import { Card, ErrorBox, PeriodPicker, Stat } from "./CallIqShell";
import { useCallIqData } from "./useCallIqData";

function Row({ title, row, money, big }: { title: string; row: ResultsRow; money: boolean; big?: boolean }) {
  return (
    <Card className={big ? "bg-primary/5" : undefined}>
      <h2 className="font-display text-base font-bold text-primary">{title}</h2>
      <div className={money ? "mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4" : "mt-3 grid grid-cols-3 gap-3"}>
        <Stat label="Calls" value={row.calls} />
        <Stat label="Picked up" value={row.connected} hint={pickedUpText(row)} />
        <Stat label="Orders" value={row.orders} />
        {money ? <Stat label="Money" value={formatRupees(row.revenue_paise ?? 0)} hint="Sales before GST" /> : null}
      </div>
    </Card>
  );
}

export function ResultsBoard() {
  const [period, setPeriod] = useState<ResultsPeriod>("today");
  const { data, err, loading, reload } = useCallIqData<ResultsResponse>(() => getResults(period), period);
  const money = showsMoney(data);

  return (
    <div className="space-y-4">
      <PeriodPicker label="Days to look at" options={RESULTS_PERIODS} value={period} onChange={setPeriod} />
      {err ? <ErrorBox message={err} onRetry={reload} /> : null}
      {loading && !data ? <AiraLoader inline className="min-h-40" /> : null}
      {data ? (
        data.callers.length === 0 ? (
          <Card><p className="font-label text-sm text-ink-secondary">No telecallers to show yet.</p></Card>
        ) : (
          <div className="space-y-3">
            <Row title="Everyone together" row={data.totals} money={money} big />
            <div className="grid gap-3 lg:grid-cols-2">
              {data.callers.map((p) => <Row key={p.caller_id} title={p.name} row={p} money={money} />)}
            </div>
            <p className="font-label text-xs text-ink-secondary">
              An order counts for the person who sold it, on the day it was paid. Picked up means the telecaller marked the call as connected.
            </p>
          </div>
        )
      ) : null}
    </div>
  );
}
